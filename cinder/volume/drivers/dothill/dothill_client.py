#    Copyright 2014 Objectif Libre
#    Copyright 2015 DotHill Systems
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

from hashlib import md5
import math
import time

from lxml import etree
from oslo_log import log as logging
import requests
import six

from cinder import exception
from cinder.i18n import _LE

LOG = logging.getLogger(__name__)


class DotHillClient(object):
    def __init__(self, host, login, password, protocol, ssl_verify):
        self._login = login
        self._password = password
        self._base_url = "%s://%s/api" % (protocol, host)
        self._session_key = None
        self.ssl_verify = ssl_verify

    def _get_auth_token(self, xml):
        """Parse an XML authentication reply to extract the session key."""
        self._session_key = None
        tree = etree.XML(xml)
        if tree.findtext(".//PROPERTY[@name='response-type']") == "success":
            self._session_key = tree.findtext(".//PROPERTY[@name='response']")

    def login(self):
        """Authenticates the service on the device."""
        hash_ = "%s_%s" % (self._login, self._password)
        if six.PY3:
            hash_ = hash_.encode('utf-8')
        hash_ = md5(hash_)
        digest = hash_.hexdigest()

        url = self._base_url + "/login/" + digest
        try:
            xml = requests.get(url, verify=self.ssl_verify)
        except requests.exceptions.RequestException:
            raise exception.DotHillConnectionError

        self._get_auth_token(xml.text.encode('utf8'))

        if self._session_key is None:
            raise exception.DotHillAuthenticationError

    def _assert_response_ok(self, tree):
        """Parses the XML returned by the device to check the return code.

        Raises a DotHillRequestError error if the return code is not 0
        or if the return code is None.
        """
        # Get the return code for the operation, raising an exception
        # if it is not present.
        return_code = tree.findtext(".//PROPERTY[@name='return-code']")
        if not return_code:
            raise exception.DotHillRequestError(message="No status found")

        # If no error occurred, just return.
        if return_code == '0':
            return

        # Format a message for the status code.
        msg = "%s (%s)" % (tree.findtext(".//PROPERTY[@name='response']"),
                           return_code)

        raise exception.DotHillRequestError(message=msg)

    def _build_request_url(self, path, *args, **kargs):
        url = self._base_url + path
        if kargs:
            url += '/' + '/'.join(["%s/%s" % (k.replace('_', '-'), v)
                                   for (k, v) in kargs.items()])
        if args:
            url += '/' + '/'.join(args)

        return url

    def _request(self, path, *args, **kargs):
        """Performs an HTTP request on the device.

        Raises a DotHillRequestError if the device returned but the status is
        not 0. The device error message will be used in the exception message.

        If the status is OK, returns the XML data for further processing.
        """

        url = self._build_request_url(path, *args, **kargs)
        LOG.debug("DotHill Request URL: %s", url)
        headers = {'dataType': 'api', 'sessionKey': self._session_key}
        try:
            xml = requests.get(url, headers=headers, verify=self.ssl_verify)
            tree = etree.XML(xml.text.encode('utf8'))
        except Exception:
            raise exception.DotHillConnectionError

        if path == "/show/volumecopy-status":
            return tree
        self._assert_response_ok(tree)
        return tree

    def logout(self):
        url = self._base_url + '/exit'
        try:
            requests.get(url, verify=self.ssl_verify)
            return True
        except Exception:
            return False

    def create_volume(self, name, size, backend_name, backend_type):
        # NOTE: size is in this format: [0-9]+GB
        path_dict = {'size': size}
        if backend_type == "linear":
            path_dict['vdisk'] = backend_name
        else:
            path_dict['pool'] = backend_name

        self._request("/create/volume", name, **path_dict)
        return None

    def delete_volume(self, name):
        self._request("/delete/volumes", name)

    def extend_volume(self, name, added_size):
        self._request("/expand/volume", name, size=added_size)

    def create_snapshot(self, volume_name, snap_name):
        self._request("/create/snapshots", snap_name, volumes=volume_name)

    def delete_snapshot(self, snap_name):
        self._request("/delete/snapshot", "cleanup", snap_name)

    def backend_exists(self, backend_name, backend_type):
        try:
            if backend_type == "linear":
                path = "/show/vdisks"
            else:
                path = "/show/pools"
            self._request(path, backend_name)
            return True
        except exception.DotHillRequestError:
            return False

    def _get_size(self, size):
        return int(math.ceil(float(size) * 512 / (10 ** 9)))

    def backend_stats(self, backend_name, backend_type):
        stats = {'free_capacity_gb': 0,
                 'total_capacity_gb': 0}
        prop_list = []
        if backend_type == "linear":
            path = "/show/vdisks"
            prop_list = ["size-numeric", "freespace-numeric"]
        else:
            path = "/show/pools"
            prop_list = ["total-size-numeric", "total-avail-numeric"]
        tree = self._request(path, backend_name)

        size = tree.findtext(".//PROPERTY[@name='%s']" % prop_list[0])
        if size:
            stats['total_capacity_gb'] = self._get_size(size)

        size = tree.findtext(".//PROPERTY[@name='%s']" % prop_list[1])
        if size:
            stats['free_capacity_gb'] = self._get_size(size)
        return stats

    def list_luns_for_host(self, host):
        tree = self._request("/show/host-maps", host)
        return [int(prop.text) for prop in tree.xpath(
                "//PROPERTY[@name='lun']")]

    def _get_first_available_lun_for_host(self, host):
        luns = self.list_luns_for_host(host)
        lun = 1
        while True:
            if lun not in luns:
                return lun
            lun += 1

    def map_volume(self, volume_name, connector, connector_element):
        if connector_element == 'wwpns':
            lun = self._get_first_available_lun_for_host(connector['wwpns'][0])
            host = ",".join(connector['wwpns'])
        else:
            host = connector['initiator']
            host_status = self._check_host(host)
            if host_status != 0:
                hostname = self._safe_hostname(connector['host'])
                self._request("/create/host", hostname, id=host)
            lun = self._get_first_available_lun_for_host(host)

        self._request("/map/volume",
                      volume_name,
                      lun=str(lun),
                      host=host,
                      access="rw")
        return lun

    def unmap_volume(self, volume_name, connector, connector_element):
        if connector_element == 'wwpns':
            host = ",".join(connector['wwpns'])
        else:
            host = connector['initiator']
        self._request("/unmap/volume", volume_name, host=host)

    def get_active_target_ports(self):
        ports = []
        tree = self._request("/show/ports")

        for obj in tree.xpath("//OBJECT[@basetype='port']"):
            port = {prop.get('name'): prop.text
                    for prop in obj.iter("PROPERTY")
                    if prop.get('name') in
                    ["port-type", "target-id", "status"]}
            if port['status'] == 'Up':
                ports.append(port)
        return ports

    def get_active_fc_target_ports(self):
        return [port['target-id'] for port in self.get_active_target_ports()
                if port['port-type'] == "FC"]

    def get_active_iscsi_target_iqns(self):
        return [port['target-id'] for port in self.get_active_target_ports()
                if port['port-type'] == "iSCSI"]

    def linear_copy_volume(self, src_name, dest_name, dest_bknd_name):
        """Copy a linear volume."""

        self._request("/volumecopy",
                      dest_name,
                      dest_vdisk=dest_bknd_name,
                      source_volume=src_name,
                      prompt='yes')

        # The copy has started; now monitor until the operation completes.
        count = 0
        while True:
            tree = self._request("/show/volumecopy-status")
            return_code = tree.findtext(".//PROPERTY[@name='return-code']")

            if return_code == '0':
                status = tree.findtext(".//PROPERTY[@name='progress']")
                progress = False
                if status:
                    progress = True
                    LOG.debug("Volume copy is in progress: %s", status)
                if not progress:
                    LOG.debug("Volume copy completed: %s", status)
                    break
            else:
                if count >= 5:
                    LOG.error(_LE('Error in copying volume: %s'), src_name)
                    raise exception.DotHillRequestError

                time.sleep(1)
                count += 1

        time.sleep(5)

    def copy_volume(self, src_name, dest_name, dest_bknd_name,
                    backend_type='virtual'):
        """Copy a linear or virtual volume."""

        if backend_type == 'linear':
            return self.linear_copy_volume(src_name, dest_name, dest_bknd_name)
        # Copy a virtual volume to another in the same pool.
        self._request("/copy/volume", src_name, name=dest_name)
        LOG.debug("Volume copy of source_volume: %(src_name)s to "
                  "destination_volume: %(dest_name)s started.",
                  {'src_name': src_name, 'dest_name': dest_name, })

        # Loop until this volume copy is no longer in progress.
        while self.volume_copy_in_progress(src_name):
            time.sleep(5)

        # Once the copy operation is finished, check to ensure that
        # the volume was not deleted because of a subsequent error. An
        # exception will be raised if the named volume is not present.
        self._request("/show/volumes", dest_name)
        LOG.debug("Volume copy of source_volume: %(src_name)s to "
                  "destination_volume: %(dest_name)s completed.",
                  {'src_name': src_name, 'dest_name': dest_name, })

    def volume_copy_in_progress(self, src_name):
        """Check if a volume copy is in progress for the named volume."""

        # 'show volume-copies' always succeeds, even if none in progress.
        tree = self._request("/show/volume-copies")

        # Find 0 or 1 job(s) with source volume we're interested in
        q = "OBJECT[PROPERTY[@name='source-volume']/text()='%s']" % src_name
        joblist = tree.xpath(q)
        if len(joblist) == 0:
            return False
        LOG.debug("Volume copy of volume: %(src_name)s is "
                  "%(pc)s percent completed.",
                  {'src_name': src_name,
                   'pc': joblist[0].findtext("PROPERTY[@name='progress']"), })
        return True

    def _check_host(self, host):
        host_status = -1
        tree = self._request("/show/hosts")
        for prop in tree.xpath("//PROPERTY[@name='host-id' and text()='%s']"
                               % host):
            host_status = 0
        return host_status

    def _safe_hostname(self, hostname):
        """Modify an initiator name to match firmware requirements.

           Initiator name cannot include certain characters and cannot exceed
           15 bytes in 'T' firmware (32 bytes in 'G' firmware).
        """
        for ch in [',', '"', '\\', '<', '>']:
            if ch in hostname:
                hostname = hostname.replace(ch, '')
        index = len(hostname)
        if index > 15:
            index = 15
        return hostname[:index]

    def get_active_iscsi_target_portals(self):
        # This function returns {'ip': status,}
        portals = {}
        prop = 'ip-address'
        tree = self._request("/show/ports")
        for el in tree.xpath("//PROPERTY[@name='primary-ip-address']"):
            prop = 'primary-ip-address'
            break
        iscsi_ips = [ip.text for ip in tree.xpath(
                     "//PROPERTY[@name='%s']" % prop)]
        if not iscsi_ips:
            return portals
        for index, port_type in enumerate(tree.xpath(
                "//PROPERTY[@name='port-type' and text()='iSCSI']")):
            status = port_type.getparent().findtext("PROPERTY[@name='status']")
            if status == 'Up':
                portals[iscsi_ips[index]] = status
        return portals

    def get_chap_record(self, initiator_name):
        tree = self._request("/show/chap-records")
        for prop in tree.xpath("//PROPERTY[@name='initiator-name' and "
                               "text()='%s']" % initiator_name):
            chap_secret = prop.getparent().findtext("PROPERTY[@name='initiator"
                                                    "-secret']")
            return chap_secret

    def create_chap_record(self, initiator_name, chap_secret):
        self._request("/create/chap-record",
                      name=initiator_name,
                      secret=chap_secret)

    def get_serial_number(self):
        tree = self._request("/show/system")
        return tree.findtext(".//PROPERTY[@name='midplane-serial-number']")

    def get_owner_info(self, backend_name, backend_type):
        if backend_type == 'linear':
            tree = self._request("/show/vdisks", backend_name)
        else:
            tree = self._request("/show/pools", backend_name)

        return tree.findtext(".//PROPERTY[@name='owner']")

    def modify_volume_name(self, old_name, new_name):
        self._request("/set/volume", old_name, name=new_name)

    def get_volume_size(self, volume_name):
        tree = self._request("/show/volumes", volume_name)
        size = tree.findtext(".//PROPERTY[@name='size-numeric']")
        return self._get_size(size)
