#    (c) Copyright 2019 Brocade, a Broadcom Company
#    All Rights Reserved.
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
"""
Brocade south bound connector to communicate with switch using
REST over HTTP or HTTPS protocol.
"""

import json

from oslo_log import log as logging
from oslo_serialization import base64
import requests
import six

from cinder.i18n import _
from cinder.zonemanager.drivers.brocade import exception
from cinder.zonemanager.drivers.brocade import fc_zone_constants
from cinder.zonemanager.drivers.brocade import rest_constants

LOG = logging.getLogger(__name__)


class BrcdRestFCZoneClient(object):

    def __init__(self, ipaddress, username,
                 password, port, vfid, protocol):
        """Initializing the client with the parameters passed.

        :param ipaddress: IP Address of the device.
        :param username: User id to login.
        :param password: User password.
        :param port: Device Communication port
        :param vfid: Virtual Fabric ID.
        :param protocol: Communication Protocol.

        """
        self.sw_ip = ipaddress
        self.sw_user = username
        self.sw_pwd = password
        self.protocol = protocol
        self.vfid = vfid
        self.status_code = ''
        self.session = None
        self._login()

    def is_supported_firmware(self):
        is_supported_firmware = False
        fw_version = self._get_firmware_version()
        ver = fw_version.split(".")
        if len(ver[0]) > 1:
            major_ver = ver[0]
            ver[0] = major_ver[1]
        if len(ver[2]) > 1:
            patch_ver = ver[2]
            ver[2] = patch_ver[0]
        LOG.debug("Firmware version: %(version)s.", {'version': ver})
        if int(ver[0] + ver[1] + ver[2]) > 820:
            is_supported_firmware = True
        return is_supported_firmware

    def get_active_zone_set(self):
        active_zone_set, checksum = self._get_effective_zone_set()
        return active_zone_set

    def get_nameserver_info(self):
        return self._get_name_server()

    def add_zones(self, add_zone_map, activate, active_zone_set=None):
        self._add_zones(add_zone_map, activate)

    def update_zones(self, update_zone_map, activate, operation,
                     active_zone_set=None):
        self._update_zones(update_zone_map, activate, operation)

    def delete_zones(self, zone_names_to_delete, activate,
                     active_zone_set=None):
        self._delete_zones(zone_names_to_delete, activate)

    def cleanup(self):
        self._logout()

    def _login(self):
        if self.protocol == fc_zone_constants.REST_HTTPS:
            self.protocol = fc_zone_constants.HTTPS
        else:
            self.protocol = fc_zone_constants.HTTP
        if self.session is None:
            self.session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=1,
                                                    pool_maxsize=1)
            self.session.mount(self.protocol + '://', adapter)
            credentials = base64.encode_as_text('%s:%s' % (self.sw_user,
                                                self.sw_pwd)).replace('\n', '')
            self.session.headers = {rest_constants.USER_AGENT:
                                    rest_constants.ZONE_DRIVER,
                                    rest_constants.ACCEPT: rest_constants.YANG,
                                    rest_constants.AUTHORIZATION:
                                        "Basic %s" % credentials}
        response = self.session.post(self._build_url(rest_constants.LOGIN))
        if response.status_code == 200:
            auth = response.headers.get('Authorization')
            LOG.info("REST login success, setting auth: %s", auth)
            self.session.headers = {rest_constants.USER_AGENT:
                                    rest_constants.ZONE_DRIVER,
                                    rest_constants.ACCEPT: rest_constants.YANG,
                                    rest_constants.CONTENT_TYPE:
                                        rest_constants.YANG,
                                    rest_constants.AUTHORIZATION: auth}
        else:
            msg = (_("REST login failed: %s")
                   % six.text_type(response.text))
            LOG.error(msg)
            raise exception.BrocadeZoningRestException(reason=msg)
        return response.status_code

    def _logout(self):
        response = self.session.post(self._build_url(rest_constants.LOGOUT))
        if response.status_code == 204:
            LOG.info("REST logout success")
        else:
            msg = (_("REST logout failed: %s")
                   % six.text_type(response.text))
            LOG.error(msg)
            raise exception.BrocadeZoningRestException(reason=msg)

    def _get_firmware_version(self):
        response = self.session.get(self._build_url(rest_constants.GET_SWITCH))
        firmware_version = ''
        if response.status_code == 200:
            data = response.json()
            json_response = data[rest_constants.RESPONSE]
            switch = json_response[rest_constants.SWITCH]
            firmware_version = switch[rest_constants.FIRMWARE_VERSION]
            LOG.info("REST firmware version: %s", firmware_version)
        else:
            msg = (_("REST get switch fw version failed: %s")
                   % six.text_type(response.text))
            LOG.error(msg)
            raise exception.BrocadeZoningRestException(reason=msg)
        return firmware_version

    def _get_name_server(self):
        port_names = []
        url = self._build_url(rest_constants.GET_NAMESERVER)
        response = self.session.get(url)
        if response.status_code == 200:
            data = response.json()
            json_response = data[rest_constants.RESPONSE]
            nsinfos = json_response[rest_constants.FC_NAME_SERVER]
            i = 0
            for nsinfo in nsinfos:
                port_names.append(nsinfos[i][rest_constants.PORT_NAME])
                i = i + 1
        else:
            msg = (_("REST get NS info failed: %s")
                   % six.text_type(response.text))
            LOG.error(msg)
            raise exception.BrocadeZoningRestException(reason=msg)
        return port_names

    def _get_effective_zone_set(self):
        active_zone_set = {}
        zones_map = {}
        url = self._build_url(rest_constants.GET_ACTIVE_ZONE_CFG)
        response = self.session.get(url)
        checksum = ''
        active_cfg_name = ''
        if response.status_code == 200:
            data = response.json()
            json_response = data[rest_constants.RESPONSE]
            effective_cfg = json_response[rest_constants.EFFECTIVE_CFG]
            checksum = effective_cfg[rest_constants.CHECKSUM]
            try:
                active_cfg_name = effective_cfg[rest_constants.CFG_NAME]
                zones = effective_cfg[rest_constants.ENABLED_ZONE]
                if type(zones) is list:
                    for i, zone in enumerate(zones):
                        zones_map.update({zones[i][rest_constants.ZONE_NAME]:
                                          zones[i][rest_constants.MEMBER_ENTRY]
                                                  [rest_constants.ENTRY_NAME]})
                else:
                    zones_map.update({zones[rest_constants.ZONE_NAME]:
                                      zones[rest_constants.MEMBER_ENTRY]
                                           [rest_constants.ENTRY_NAME]})
            except Exception:
                active_cfg_name = ''
            LOG.info("REST get effective zoneset success: "
                     "active cfg: %(cfg_name)s, checksum: %(chksum)s",
                     {'cfg_name': active_cfg_name, 'chksum': checksum})
        else:
            msg = (_("REST get effective zoneset failed: %s")
                   % six.text_type(response.text))
            LOG.error(msg)
            raise exception.BrocadeZoningRestException(reason=msg)
        active_zone_set = {"active_zone_config": active_cfg_name,
                           "zones": zones_map}
        return active_zone_set, checksum

    def _add_zones(self, add_zone_map, activate):
        active_zone_set, checksum = self._get_effective_zone_set()
        # if activate, get the zones already configured in the active cfg
        if activate:
            zones_in_active_cfg = active_zone_set.get("zones")
        # for each new zone, create a zone entry in defined zone db
        for zone_name, members in add_zone_map.items():
            if zone_name not in zones_in_active_cfg:
                body = {rest_constants.MEMBER_ENTRY:
                        {rest_constants.ENTRY_NAME:
                         add_zone_map.get(zone_name)}}
                json_str = json.dumps(body)
                url = self._build_url(rest_constants.POST_ZONE + zone_name)
                response = self.session.post(url, data=json_str)
                if response.status_code == 201:
                    LOG.info("REST create zone success: %s", zone_name)
                else:
                    msg = (_("REST create zone failed: %s")
                           % six.text_type(response.text))
                    LOG.error(msg)
                    raise exception.BrocadeZoningRestException(reason=msg)
        # update the cfg with the new zones
        active_cfg_name = active_zone_set.get("active_zone_config")
        active_zones = active_zone_set.get("zones")
        active_zone_names = active_zones.keys()
        active_zone_names.extend(add_zone_map.keys())
        body = {rest_constants.MEMBER_ZONE:
                {rest_constants.ZONE_NAME: active_zone_names}}
        json_str = json.dumps(body)
        if active_cfg_name == '':
            active_cfg_name = fc_zone_constants.CFG_NAME
            url = self._build_url(rest_constants.POST_CFG + active_cfg_name)
            response = self.session.post(url, data=json_str)
            if response.status_code == 201:
                LOG.info("REST cfg create success: %s", active_cfg_name)
                self._save_and_activate_cfg(checksum, activate,
                                            active_cfg_name)
            else:
                msg = (_("REST cfg create failed: %s")
                       % six.text_type(response.text))
                LOG.error(msg)
                raise exception.BrocadeZoningRestException(reason=msg)
        else:
            url = self._build_url(rest_constants.PATCH_CFG + active_cfg_name)
            response = self.session.patch(url, data=json_str)
            # if update successful, save the configuration changes
            if response.status_code == 204:
                LOG.info("REST cfg update success: %s", active_cfg_name)
                self._save_and_activate_cfg(checksum, activate,
                                            active_cfg_name)
            else:
                msg = (_("REST cfg update failed: %s")
                       % six.text_type(response.text))
                LOG.error(msg)
                raise exception.BrocadeZoningRestException(reason=msg)

    def _update_zones(self, update_zone_map, activate, operation):
        active_zone_set, checksum = self._get_effective_zone_set()
        active_cfg_name = active_zone_set.get("active_zone_config")
        active_zones = active_zone_set.get("zones")
        # for each zone, update the zone members in defined zone db
        for zone_name, members in update_zone_map.items():
            current_members = active_zones.get(zone_name)
            if operation == "ADD":
                new_members = set(members).difference(set(current_members))
                if new_members:
                    update_zone_map.update({zone_name: new_members})
            elif operation == "REMOVE":
                new_members = set(current_members).difference(set(members))
                if new_members:
                    update_zone_map.update({zone_name: new_members})
        # for each zone to be updated, make REST PATCH call to update
        for zone in update_zone_map.keys():
            body = {rest_constants.MEMBER_ENTRY:
                    {rest_constants.ENTRY_NAME: update_zone_map.get(zone)}}
            json_str = json.dumps(body)
            url = self._build_url(rest_constants.POST_ZONE + zone)
            response = self.session.patch(url, data=json_str)
            if response.status_code == 204:
                LOG.info("REST zone update success: %s", zone)
            else:
                msg = (_("REST zone update failed: %s")
                       % six.text_type(response.text))
                LOG.error(msg)
                raise exception.BrocadeZoningRestException(reason=msg)
        # save and activate the config changes
        self._save_and_activate_cfg(checksum, activate, active_cfg_name)

    def _delete_zones(self, zone_names_to_delete, activate):
        zone_names_to_delete = zone_names_to_delete.split(";")
        active_zone_set, checksum = self._get_effective_zone_set()
        # for each zone name, make REST DELETE call
        for zone in zone_names_to_delete:
            url = self._build_url(rest_constants.DELETE_ZONE + zone)
            response = self.session.delete(url)
            if response.status_code == 204:
                LOG.info("REST delete zone success: %s", zone)
            else:
                msg = (_("REST delete zone failed: %s")
                       % six.text_type(response.text))
                LOG.error(msg)
                raise exception.BrocadeZoningRestException(reason=msg)
        # update the cfg removing the deleted zones
        active_cfg_name = active_zone_set.get("active_zone_config")
        active_zones = active_zone_set.get("zones")
        active_zone_names = active_zones.keys()
        if len(active_zone_names) == len(zone_names_to_delete):
            # disable the cfg
            url = self._build_url(rest_constants.PATCH_CFG_DISABLE)
            body = {"checksum": checksum}
            json_str = json.dumps(body)
            response = self.session.patch(url, data=json_str)
            if response.status_code == 204:
                LOG.info("REST cfg disable success")
            else:
                msg = (_("REST cfg disable failed: %s")
                       % six.text_type(response.text))
                LOG.error(msg)
                raise exception.BrocadeZoningRestException(reason=msg)
            # delete the cfg
            url = self._build_url(rest_constants.DELETE_CFG + active_cfg_name)
            response = self.session.delete(url)
            if response.status_code == 204:
                LOG.info("REST cfg delete success: %s", active_cfg_name)
            else:
                msg = (_("REST cfg delete failed: %s")
                       % six.text_type(response.text))
                LOG.error(msg)
                raise exception.BrocadeZoningRestException(reason=msg)
            checksum = self._get_checksum()
            self._save_and_activate_cfg(checksum, False, active_cfg_name)
        else:
            # update the cfg by removing the deleted zones
            zone_names_in_cfg = list(set(active_zone_names)
                                     .difference(set(zone_names_to_delete)))
            body = {rest_constants.MEMBER_ZONE:
                    {rest_constants.ZONE_NAME: zone_names_in_cfg}}
            json_str = json.dumps(body)
            url = self._build_url(rest_constants.PATCH_CFG + active_cfg_name)
            response = self.session.patch(url, data=json_str)
            # if update successful, save the configuration changes
            if response.status_code == 204:
                LOG.info("REST cfg update success: %s", active_cfg_name)
                self._save_and_activate_cfg(checksum, activate,
                                            active_cfg_name)
            else:
                msg = (_("REST cfg update failed: %s")
                       % six.text_type(response.text))
                LOG.error(msg)
                raise exception.BrocadeZoningRestException(reason=msg)

    def _save_and_activate_cfg(self, checksum, activate, active_cfg_name):
        body = {"checksum": checksum}
        json_str = json.dumps(body)
        url = self._build_url(rest_constants.PATCH_CFG_SAVE)
        response = self.session.patch(url, data=json_str)
        if response.status_code == 204:
            LOG.info("REST cfg save success")
        else:
            msg = (_("REST cfg save failed: %s")
                   % six.text_type(response.text))
            LOG.error(msg)
            raise exception.BrocadeZoningRestException(reason=msg)
        # if activate=true, then enable the cfg changes to effective cfg
        if activate:
            checksum = self._get_checksum()
            body = {"checksum": checksum}
            json_str = json.dumps(body)
            url = self._build_url(rest_constants.PATCH_CFG_ENABLE
                                  + active_cfg_name)
            response = self.session.patch(url, data=json_str)
            if response.status_code == 204:
                LOG.info("REST cfg activate success: %s", active_cfg_name)
            else:
                msg = (_("REST cfg activate failed: %s")
                       % six.text_type(response.text))
                LOG.error(msg)
                raise exception.BrocadeZoningRestException(reason=msg)

    def _get_checksum(self):
        url = self._build_url(rest_constants.GET_CHECKSUM)
        response = self.session.get(url)
        checksum = ''
        if response.status_code == 200:
            data = response.json()
            json_response = data[rest_constants.RESPONSE]
            effective_cfg = json_response[rest_constants.EFFECTIVE_CFG]
            checksum = effective_cfg[rest_constants.CHECKSUM]
            LOG.info("REST get checksum success: %s", checksum)
        else:
            msg = (_("REST get checksum failed: %s")
                   % six.text_type(response.text))
            LOG.error(msg)
            raise exception.BrocadeZoningRestException(reason=msg)
        return checksum

    def _build_url(self, path):
        url = '%s://%s%s' % (self.protocol, self.sw_ip, path)
        if self.vfid is not None:
            url = '%s?vf-id=%s' % (url, self.vfid)
        return url
