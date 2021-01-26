#    Copyright 2014 Objectif Libre
#    Copyright 2015 Dot Hill Systems Corp.
#    Copyright 2016-2019 Seagate Technology or one of its affiliates
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

import hashlib
import math
import re
import time

from lxml import etree
from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import units
import requests
import six

from cinder import coordination
from cinder.i18n import _
import cinder.volume.drivers.stx.exception as stx_exception
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


@six.add_metaclass(volume_utils.TraceWrapperMetaclass)
class STXClient(object):
    def __init__(self, host, login, password, protocol, ssl_verify):
        self._mgmt_ip_addrs = list(map(str.strip, host.split(',')))
        self._login = login
        self._password = password
        self._protocol = protocol
        self._session_key = None
        self.ssl_verify = ssl_verify
        self._set_host(self._mgmt_ip_addrs[0])
        self._fw_type = ''
        self._fw_rev = 0
        self._driver_name = self.__class__.__name__.split('.')[0]
        self._array_name = 'unknown'
        self._luns_in_use_by_host = {}

    def _set_host(self, ip_addr):
        self._curr_ip_addr = ip_addr
        self._base_url = "%s://%s/api" % (self._protocol, ip_addr)

    def _get_auth_token(self, xml):
        """Parse an XML authentication reply to extract the session key."""
        self._session_key = None
        try:
            tree = etree.XML(xml)
            # The 'return-code' property is not valid in this context, so we
            # we check value of 'response-type-numeric' (0 => Success)
            rtn = tree.findtext(".//PROPERTY[@name='response-type-numeric']")
            session_key = tree.findtext(".//PROPERTY[@name='response']")
            if rtn == '0':
                self._session_key = session_key
        except Exception as e:
            msg = _("Cannot parse session key: %s") % e.msg
            raise stx_exception.ConnectionError(message=msg)

    def login(self):
        if self._session_key is None:
            return self.session_login()

    def session_login(self):
        """Authenticates the service on the device.

        Tries all the IP addrs listed in the san_ip parameter
        until a working one is found or the list is exhausted.
        """

        try:
            self._get_session_key()
            self.get_firmware_version()
            if not self._array_name or self._array_name == 'unknown':
                self._array_name = self.get_serial_number()
            LOG.debug("Logged in to array %s at %s (session %s)",
                      self._array_name, self._base_url, self._session_key)
            return
        except stx_exception.ConnectionError:
            not_responding = self._curr_ip_addr
            LOG.exception('session_login failed to connect to %s',
                          self._curr_ip_addr)
            # Loop through the remaining management addresses
            # to find one that's up.
            for host in self._mgmt_ip_addrs:
                if host is not_responding:
                    continue
                self._set_host(host)
                try:
                    self._get_session_key()
                    return
                except stx_exception.ConnectionError:
                    LOG.error('Failed to connect to %s',
                              self._curr_ip_addr)
                    continue
        raise stx_exception.ConnectionError(
            message=_("Failed to log in to management controller"))

    @coordination.synchronized('{self._driver_name}-{self._array_name}')
    def _get_session_key(self):
        """Retrieve a session key from the array."""

        # TODO(alee): This appears to use md5 in a security related
        # context in providing a session key and hashing a login and
        # password.  This should likely be replaced by a version that
        # does not use md5 here.
        self._session_key = None
        hash_ = "%s_%s" % (self._login, self._password)
        if six.PY3:
            hash_ = hash_.encode('utf-8')
        hash_ = hashlib.md5(hash_)  # nosec
        digest = hash_.hexdigest()

        url = self._base_url + "/login/" + digest
        try:
            if self._protocol == 'https':
                xml = requests.get(url, verify=self.ssl_verify, timeout=30,
                                   auth=(self._login, self._password))
            else:
                xml = requests.get(url, verify=self.ssl_verify, timeout=30)
        except requests.exceptions.RequestException:
            msg = _("Failed to obtain MC session key")
            LOG.exception(msg)
            raise stx_exception.ConnectionError(message=msg)

        self._get_auth_token(xml.text.encode('utf8'))
        LOG.debug("session key = %s", self._session_key)
        if self._session_key is None:
            raise stx_exception.AuthenticationError

    def _assert_response_ok(self, tree):
        """Parses the XML returned by the device to check the return code.

        Raises a RequestError error if the return code is not 0
        or if the return code is None.
        """
        # Get the return code for the operation, raising an exception
        # if it is not present.
        return_code = tree.findtext(".//PROPERTY[@name='return-code']")
        if not return_code:
            raise stx_exception.RequestError(message="No status found")

        # If no error occurred, just return.
        if return_code == '0':
            return

        # Format a message for the status code.
        msg = "%s (%s)" % (tree.findtext(".//PROPERTY[@name='response']"),
                           return_code)

        raise stx_exception.RequestError(message=msg)

    def _build_request_url(self, path, *args, **kargs):
        url = self._base_url + path
        if kargs:
            url += '/' + '/'.join(["%s/%s" % (k.replace('_', '-'), v)
                                   for (k, v) in kargs.items()])
        if args:
            url += '/' + '/'.join(args)

        return url

    def _request(self, path, *args, **kargs):
        """Performs an API request on the array, with retry.

        Propagates a ConnectionError if no valid response is
        received from the array, e.g. if the network is down.

        Propagates a RequestError if the device returned a response
        but the status is not 0. The device error message will be used
        in the exception message.

        If the status is OK, returns the XML data for further processing.
        """
        tries_left = 2
        while tries_left > 0:
            try:
                return self._api_request(path, *args, **kargs)
            except stx_exception.ConnectionError as e:
                if tries_left < 1:
                    LOG.error("Array Connection error: "
                              "%s (no more retries)", e.msg)
                    raise
                # Retry on any network connection errors, SSL errors, etc
                LOG.error("Array Connection error: %s (retrying)", e.msg)
            except stx_exception.RequestError as e:
                if tries_left < 1:
                    LOG.error("Array Request error: %s (no more retries)",
                              e.msg)
                    raise
                # Retry specific errors which may succeed if we log in again
                # -10027 => The user is not recognized on this system.
                if '(-10027)' in e.msg:
                    LOG.error("Array Request error: %s (retrying)", e.msg)
                else:
                    raise

            tries_left -= 1
            self.session_login()

    @coordination.synchronized('{self._driver_name}-{self._array_name}')
    def _api_request(self, path, *args, **kargs):
        """Performs an HTTP request on the device, with locking.

        Raises a RequestError if the device returned but the status is
        not 0. The device error message will be used in the exception message.

        If the status is OK, returns the XML data for further processing.
        """
        url = self._build_request_url(path, *args, **kargs)
        # Don't log the created URL since it may contain chap secret
        LOG.debug("Array Request path: %s, args: %s, kargs: %s (session %s)",
                  path, args, strutils.mask_password(kargs), self._session_key)
        headers = {'dataType': 'api', 'sessionKey': self._session_key}
        try:
            xml = requests.get(url, headers=headers,
                               verify=self.ssl_verify, timeout=60)
            tree = etree.XML(xml.text.encode('utf8'))
        except Exception as e:
            message = _("Exception handling URL %(url)s: %(msg)s") % {
                'url': url, 'msg': e}
            raise stx_exception.ConnectionError(message=message)

        if path == "/show/volumecopy-status":
            return tree
        self._assert_response_ok(tree)
        return tree

    def logout(self):
        pass

    def session_logout(self):
        url = self._base_url + '/exit'
        try:
            requests.get(url, verify=self.ssl_verify, timeout=30)
            return True
        except Exception:
            return False

    def is_titanium(self):
        """True for older array firmware."""
        return self._fw_type == 'T'

    def is_g5_fw(self):
        """Identify firmware updated in/after 2020.

        Long-deprecated commands have or will be removed.
        """
        if self._fw_type in ['I', 'V']:
            return True
        if self._fw_type == 'G' and self._fw_rev >= 280:
            return True
        return False

    def create_volume(self, name, size, backend_name, backend_type):
        # NOTE: size is in this format: [0-9]+GiB
        path_dict = {'size': size}
        if backend_type == "linear":
            path_dict['vdisk'] = backend_name
        else:
            path_dict['pool'] = backend_name

        try:
            self._request("/create/volume", name, **path_dict)
        except stx_exception.RequestError as e:
            # -10186 => The specified name is already in use.
            # This can occur during controller failover.
            if '(-10186)' in e.msg:
                LOG.warning("Ignoring error in create volume: %s", e.msg)
                return None
            raise

        return None

    def delete_volume(self, name):
        try:
            self._request("/delete/volumes", name)
        except stx_exception.RequestError as e:
            # -10075 => The specified volume was not found.
            # This can occur during controller failover.
            if '(-10075)' in e.msg:
                LOG.warning("Ignorning error while deleting %(volume)s:"
                            " %(reason)s",
                            {'volume': name, 'reason': e.msg})
                return
            raise

    def extend_volume(self, name, added_size):
        self._request("/expand/volume", name, size=added_size)

    def create_snapshot(self, volume_name, snap_name):
        try:
            self._request("/create/snapshots", snap_name, volumes=volume_name)
        except stx_exception.RequestError as e:
            # -10186 => The specified name is already in use.
            # This can occur during controller failover.
            if '(-10186)' in e.msg:
                LOG.warning("Ignoring error attempting to create snapshot:"
                            " %s", e.msg)
                return None

    def delete_snapshot(self, snap_name, backend_type):
        try:
            if backend_type == 'linear':
                self._request("/delete/snapshot", "cleanup", snap_name)
            else:
                self._request("/delete/snapshot", snap_name)
        except stx_exception.RequestError as e:
            # -10050 => The volume was not found on this system.
            # This can occur during controller failover.
            if '(-10050)' in e.msg:
                LOG.warning("Ignoring unmap error -10050: %s", e.msg)
                return None
            raise

    def backend_exists(self, backend_name, backend_type):
        try:
            if backend_type == "linear":
                path = "/show/vdisks"
            else:
                path = "/show/pools"
            self._request(path, backend_name)
            return True
        except stx_exception.RequestError:
            return False

    def _get_size(self, size):
        return int(math.ceil(float(size) * 512 / (units.G)))

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
        if self.is_titanium():
            tree = self._request("/show/host-maps", host)
        else:
            tree = self._request("/show/maps/initiator", host)
        return [int(prop.text) for prop in tree.xpath(
                "//PROPERTY[@name='lun']")]

    def _get_first_available_lun_for_host(self, host):
        """Find next available LUN number.

        Returns a lun number greater than 0 which is not known to be in
        use between the array and the specified host.
        """
        luns = self.list_luns_for_host(host)
        self._luns_in_use_by_host[host] = luns
        lun = 1
        while True:
            if lun not in luns:
                return lun
            lun += 1

    def _get_next_available_lun_for_host(self, host, after=0):
        # host can be a comma-separated list of WWPNs; we only use the first.
        firsthost = host.split(',')[0]
        LOG.debug('get_next_available_lun: host=%s, firsthost=%s, after=%d',
                  host, firsthost, after)
        if after == 0:
            return self._get_first_available_lun_for_host(firsthost)
        luns = self._luns_in_use_by_host[firsthost]
        lun = after + 1
        while lun < 1024:
            LOG.debug('get_next_available_lun: host=%s, trying lun %d',
                      firsthost, lun)
            if lun not in luns:
                LOG.debug('get_next_available_lun: host=%s, RETURNING lun %d',
                          firsthost, lun)
                return lun
            lun += 1
        raise stx_exception.RequestError(
            message=_("No LUNs available for mapping to host %s.") % host)

    def _is_mapped(self, volume_name, ids):
        if not isinstance(ids, list):
            ids = [ids]
        try:
            cmd = "/show/volume-maps" if self.is_titanium() else "/show/maps"
            xml = self._request(cmd, volume_name)

            for obj in xml.xpath("//OBJECT[@basetype='volume-view-mappings']"):
                lun = obj.findtext("PROPERTY[@name='lun']")
                iid = obj.findtext("PROPERTY[@name='identifier']")
                if iid in ids:
                    LOG.debug("volume '%s' is already mapped to %s at lun %s",
                              volume_name, iid, lun)
                    return int(lun)
        except Exception:
            LOG.exception("failed to look up mappings for volume '%s'",
                          volume_name)
            raise
        return None

    @coordination.synchronized('{self._driver_name}-{self._array_name}-map')
    def map_volume(self, volume_name, connector, connector_element):
        # If multiattach enabled, its possible the volume is already mapped
        lun = self._is_mapped(volume_name, connector[connector_element])
        if lun:
            return lun
        if connector_element == 'wwpns':
            lun = self._get_first_available_lun_for_host(connector['wwpns'][0])
            host = ",".join(connector['wwpns'])
        else:
            host = connector['initiator']
            host_status = self._check_host(host)
            if host_status != 0:
                hostname = self._safe_hostname(connector['host'])
                try:
                    if self.is_g5_fw():
                        self._request("/set/initiator", nickname=hostname,
                                      id=host)
                    else:
                        self._request("/create/host", hostname, id=host)
                except stx_exception.RequestError as e:
                    # -10058: The host identifier or nickname is already in use
                    if '(-10058)' in e.msg:
                        LOG.error("While trying to create host nickname"
                                  " %(nickname)s: %(error_msg)s",
                                  {'nickname': hostname,
                                   'error_msg': e.msg})
                    else:
                        raise
            lun = self._get_first_available_lun_for_host(host)

        while lun < 255:
            try:
                if self.is_g5_fw():
                    self._request("/map/volume",
                                  volume_name,
                                  lun=str(lun),
                                  initiator=host,
                                  access="rw")
                else:
                    self._request("/map/volume",
                                  volume_name,
                                  lun=str(lun),
                                  host=host,
                                  access="rw")
                return lun
            except stx_exception.RequestError as e:
                # -3177 => "The specified LUN overlaps a previously defined LUN
                if '(-3177)' in e.msg:
                    LOG.info("Unable to map volume"
                             " %(volume_name)s to lun %(lun)d:"
                             " %(reason)s",
                             {'volume_name': volume_name,
                              'lun': lun, 'reason': e.msg})
                    lun = self._get_next_available_lun_for_host(host,
                                                                after=lun)
                    continue
                raise
            except Exception as e:
                LOG.error("Error while mapping volume"
                          " %(volume_name)s to lun %(lun)d:",
                          {'volume_name': volume_name, 'lun': lun},
                          e)
                raise

        raise stx_exception.RequestError(
            message=_("Failed to find a free LUN for host %s") % host)

    def unmap_volume(self, volume_name, connector, connector_element):
        if connector_element == 'wwpns':
            host = ",".join(connector['wwpns'])
        else:
            host = connector['initiator']
        try:
            if self.is_g5_fw():
                self._request("/unmap/volume", volume_name, initiator=host)
            else:
                self._request("/unmap/volume", volume_name, host=host)
        except stx_exception.RequestError as e:
            # -10050 => The volume was not found on this system.
            # This can occur during controller failover.
            if '(-10050)' in e.msg:
                LOG.warning("Ignoring unmap error -10050: %s", e.msg)
                return None
            raise

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
                    LOG.error('Error in copying volume: %s', src_name)
                    raise stx_exception.RequestError

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
        """Return 0 if initiator id found in the array's host table."""
        if self.is_g5_fw():
            tree = self._request("/show/initiators")
            for prop in tree.xpath("//PROPERTY[@name='id' and text()='%s']"
                                   % host):
                return 0
            return -1

        # Use older syntax for older firmware
        tree = self._request("/show/hosts")
        for prop in tree.xpath("//PROPERTY[@name='host-id' and text()='%s']"
                               % host):
            return 0
        return -1

    def _safe_hostname(self, hostname):
        """Modify an initiator name to match firmware requirements.

           Initiator name cannot include certain characters and cannot exceed
           15 bytes in 'T' firmware (31 bytes in 'G' firmware).
        """
        for ch in [',', '"', '\\', '<', '>']:
            if ch in hostname:
                hostname = hostname.replace(ch, '')
        hostname = hostname.replace('.', '_')
        name_limit = 15 if self.is_titanium() else 31
        index = len(hostname)
        if index > name_limit:
            index = name_limit
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

    def get_firmware_version(self):
        """Get the array firmware version"""
        tree = self._request("/show/controllers")
        s = tree.xpath("//PROPERTY[@name='sc-fw']")[0].text
        if len(s):
            self._fw_type = s[0]
            fw_rev_match = re.match('^[^0-9]*([0-9]+).*', s)
            if not fw_rev_match:
                LOG.error('firmware revision not found in "%s"', s)
                return s
            self._fw_rev = int(fw_rev_match.groups()[0])
            LOG.debug("Array firmware is %s (%s%d)\n",
                      s, self._fw_type, self._fw_rev)
        return s
