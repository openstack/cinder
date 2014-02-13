#    Copyright 2014 Objectif Libre
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
import urllib2

from lxml import etree


class HPMSAConnectionError(Exception):
    pass


class HPMSAAuthenticationError(Exception):
    pass


class HPMSARequestError(Exception):
    pass


class HPMSAClient(object):
    def __init__(self, host, login, password, protocol='http'):
        self._login = login
        self._password = password
        self._base_url = "%s://%s/api" % (protocol, host)
        self._session_key = None

    def _get_auth_token(self, xml):
        """Parse an XML authentication reply to extract the session key."""

        self._session_key = None
        obj = etree.XML(xml).find("OBJECT")
        for prop in obj.iter("PROPERTY"):
            if prop.get("name") == "response":
                self._session_key = prop.text
                break

    def login(self):
        """Authenticates the service on the device."""
        hash = md5("%s_%s" % (self._login, self._password))
        digest = hash.hexdigest()

        url = self._base_url + "/login/" + digest
        try:
            xml = urllib2.urlopen(url).read()
        except urllib2.URLError:
            raise HPMSAConnectionError()

        self._get_auth_token(xml)

        if self._session_key is None:
            raise HPMSAAuthenticationError()

    def _assert_response_ok(self, tree):
        """Parses the XML returned by the device to check the return code.

        Raises a HPMSARequestError error if the return code is not 0.
        """

        for obj in tree.iter():
            if obj.get("basetype") != "status":
                continue

            ret_code = ret_str = None
            for prop in obj.iter("PROPERTY"):
                if prop.get("name") == "return-code":
                    ret_code = prop.text
                elif prop.get("name") == "response":
                    ret_str = prop.text

            if ret_code != "0":
                raise HPMSARequestError(ret_str)
            else:
                return

        raise HPMSARequestError("No status found")

    def _build_request_url(self, path, args=None, **kargs):
        url = self._base_url + path
        if kargs:
            url += '/' + '/'.join(["%s/%s" % (k.replace('_', '-'), v)
                                   for (k, v) in kargs.items()])
        if args:
            if not isinstance(args, list):
                args = [args]
            url += '/' + '/'.join(args)

        return url

    def _request(self, path, args=None, **kargs):
        """Performs an HTTP request on the device.

        Raises a HPMSARequestError if the device returned but the status is
        not 0. The device error message will be used in the exception message.

        If the status is OK, returns the XML data for further processing.
        """

        url = self._build_request_url(path, args, **kargs)
        headers = {'dataType': 'api', 'sessionKey': self._session_key}
        req = urllib2.Request(url, headers=headers)
        try:
            xml = urllib2.urlopen(req).read()
        except urllib2.URLError:
            raise HPMSAConnectionError()

        try:
            tree = etree.XML(xml)
        except etree.LxmlError:
            raise HPMSAConnectionError()

        self._assert_response_ok(tree)
        return tree

    def logout(self):
        url = self._base_url + '/exit'
        try:
            urllib2.urlopen(url)
            return True
        except HPMSARequestError:
            return False

    def create_volume(self, vdisk, name, size):
        # NOTE: size is in this format: [0-9]+GB
        self._request("/create/volume", name, vdisk=vdisk, size=size)
        return None

    def delete_volume(self, name):
        self._request("/delete/volumes", name)

    def extend_volume(self, name, added_size):
        self._request("/expand/volume", name, size=added_size)

    def create_snapshot(self, volume_name, snap_name):
        self._request("/create/snapshots", snap_name, volumes=volume_name)

    def delete_snapshot(self, snap_name):
        self._request("/delete/snapshot", ["cleanup", snap_name])

    def vdisk_exists(self, vdisk):
        try:
            self._request("/show/vdisks", vdisk)
            return True
        except HPMSARequestError:
            return False

    def vdisk_stats(self, vdisk):
        stats = {'free_capacity_gb': 0,
                 'total_capacity_gb': 0}
        tree = self._request("/show/vdisks", vdisk)

        for obj in tree.iter():
            if obj.get("basetype") != "virtual-disks":
                continue

            for prop in obj.iter("PROPERTY"):
                # the sizes are given in number of blocks of 512 octets
                if prop.get("name") == "size-numeric":
                    stats['total_capacity_gb'] = \
                        int(prop.text) * 512 / (10 ** 9)
                elif prop.get("name") == "freespace-numeric":
                    stats['free_capacity_gb'] = \
                        int(prop.text) * 512 / (10 ** 9)

        return stats

    def _get_first_available_lun_for_host(self, host):
        luns = []
        tree = self._request("/show/host-maps", host)

        for obj in tree.iter():
            if obj.get("basetype") != "host-view-mappings":
                continue

            for prop in obj.iter("PROPERTY"):
                if prop.get("name") == "lun":
                    luns.append(int(prop.text))

        lun = 1
        while True:
            if lun not in luns:
                return lun
            lun += 1

    def map_volume(self, volume_name, wwpns):
        # NOTE(gpocentek): we assume that luns will be the same for all hosts
        lun = self._get_first_available_lun_for_host(wwpns[0])
        hosts = ",".join(wwpns)
        self._request("/map/volume", volume_name,
                      lun=str(lun), host=hosts, access="rw")
        return lun

    def unmap_volume(self, volume_name, wwpns):
        hosts = ",".join(wwpns)
        self._request("/unmap/volume", volume_name, host=hosts)

    def get_active_target_ports(self):
        ports = []
        tree = self._request("/show/ports")

        for obj in tree.iter():
            if obj.get("basetype") != "port":
                continue

            port = {}
            for prop in obj.iter("PROPERTY"):
                prop_name = prop.get("name")
                if prop_name in ["port-type", "target-id", "status"]:
                    port[prop_name] = prop.text
            if port['status'] != 'Up':
                continue
            ports.append(port)

        return ports

    def get_active_fc_target_ports(self):
        ports = []
        for port in self.get_active_target_ports():
            if port['port-type'] == "FC":
                ports.append(port['target-id'])

        return ports

    def copy_volume(self, source_name, target_name, vdisk):
        self._request("/volumecopy", target_name,
                      dest_vdisk=vdisk,
                      source_volume=source_name,
                      prompt='yes')
