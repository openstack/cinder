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
HTTP or HTTPS protocol.
"""

import requests
import six
import time

from oslo_log import log as logging
from oslo_serialization import base64
from oslo_utils import encodeutils

from cinder import exception
from cinder.i18n import _
import cinder.zonemanager.drivers.brocade.fc_zone_constants as zone_constant


LOG = logging.getLogger(__name__)


class BrcdHTTPFCZoneClient(object):

    def __init__(self, ipaddress, username,
                 password, port, vfid, protocol):
        """Initializing the client with the parameters passed.

        Creates authentication token and authenticate with switch
        to ensure the credentials are correct and change the VF context.

        :param ipaddress: IP Address of the device.
        :param username: User id to login.
        :param password: User password.
        :param port: Device Communication port
        :param vfid: Virtual Fabric ID.
        :param protocol: Communication Protocol.
        """
        self.switch_ip = ipaddress
        self.switch_user = username
        self.switch_pwd = password
        self.protocol = protocol
        self.vfid = vfid
        self.cfgs = {}
        self.zones = {}
        self.alias = {}
        self.qlps = {}
        self.ifas = {}
        self.active_cfg = ''
        self.parsed_raw_zoneinfo = ""
        self.random_no = ''
        self.auth_version = ''
        self.session = None

        # Create and assign the authentication header based on the credentials
        self.auth_header = self.create_auth_token()

        # Authenticate with the switch
        # If authenticated successfully, save the auth status and
        # create auth header for future communication with the device.
        self.is_auth, self.auth_header = self.authenticate()
        self.check_change_vf_context()

    def connect(self, requestType, requestURL, payload='', header=None):
        """Connect to the switch using HTTP/HTTPS protocol.

        :param requestType: Connection Request method
        :param requestURL: Connection URL
        :param payload: Data to send with POST request
        :param header: Request Headers

        :returns: HTTP response data
        :raises BrocadeZoningHttpException:
        """
        try:
            if header is None:
                header = {}
            header.update({"User-Agent": "OpenStack Zone Driver"})

            # Ensure only one connection is made throughout the life cycle
            protocol = zone_constant.HTTP
            if self.protocol == zone_constant.PROTOCOL_HTTPS:
                protocol = zone_constant.HTTPS
            if self.session is None:
                self.session = requests.Session()
                adapter = requests.adapters.HTTPAdapter(pool_connections=1,
                                                        pool_maxsize=1)
                self.session.mount(protocol + '://', adapter)
            url = '%s://%s%s' % (protocol, self.switch_ip, requestURL)
            response = None
            if requestType == zone_constant.GET_METHOD:
                response = self.session.get(url,
                                            headers=(header),
                                            verify=False)
            elif requestType == zone_constant.POST_METHOD:
                response = self.session.post(url,
                                             payload,
                                             headers=(header),
                                             verify=False)

            # Throw exception when response status is not OK
            if response.status_code != zone_constant.STATUS_OK:
                msg = _("Error while querying page %(url)s on the switch, "
                        "reason %(error)s.") % {'url': url,
                                                'error': response.reason}
                raise exception.BrocadeZoningHttpException(msg)
            else:
                return response.text
        except requests.exceptions.ConnectionError as e:
            msg = (_("Error while connecting the switch %(switch_id)s "
                     "with protocol %(protocol)s. Error: %(error)s.")
                   % {'switch_id': self.switch_ip,
                      'protocol': self.protocol,
                      'error': six.text_type(e)})
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        except exception.BrocadeZoningHttpException as ex:
            msg = (_("Unexpected status code from the switch %(switch_id)s "
                     "with protocol %(protocol)s for url %(page)s. "
                     "Error: %(error)s")
                   % {'switch_id': self.switch_ip,
                      'protocol': self.protocol,
                      'page': requestURL,
                      'error': six.text_type(ex)})
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def create_auth_token(self):
        """Create the authentication token.

        Creates the authentication token to use in the authentication header
        return authentication header (Base64(username:password:random no)).

        :returns: Authentication Header
        :raises BrocadeZoningHttpException:
        """
        try:
            # Send GET request to secinfo.html to get random number
            response = self.connect(zone_constant.GET_METHOD,
                                    zone_constant.SECINFO_PAGE)
            parsed_data = self.get_parsed_data(response,
                                               zone_constant.SECINFO_BEGIN,
                                               zone_constant.SECINFO_END)

            # Get the auth version for 8.1.0b+ switches
            self.auth_version = self.get_nvp_value(parsed_data,
                                                   zone_constant.AUTHVERSION)

            if self.auth_version == "1":
                # Extract the random no from secinfo.html response
                self.random_no = self.get_nvp_value(parsed_data,
                                                    zone_constant.RANDOM)
                # Form the authentication string
                auth_string = '%s:%s:%s' % (self.switch_user, self.switch_pwd,
                                            self.random_no)
            else:
                auth_string = '%s:%s' % (self.switch_user, self.switch_pwd)
            auth_token = base64.encode_as_text(auth_string).strip()
            auth_header = (zone_constant.AUTH_STRING +
                           auth_token)  # Build the proper header
        except Exception as e:
            msg = (_("Error while creating authentication token: %s")
                   % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        return auth_header

    def authenticate(self):
        """Authenticate with the switch.

        Returns authentication status with modified authentication
        header (Base64(username:xxx:random no)).

        :returns: Authentication status
        :raises BrocadeZoningHttpException:
        """
        headers = {zone_constant.AUTH_HEADER: self.auth_header}
        try:
            # GET Request to authenticate.html to verify the credentials
            response = self.connect(zone_constant.GET_METHOD,
                                    zone_constant.AUTHEN_PAGE,
                                    header=headers)
            parsed_data = self.get_parsed_data(response,
                                               zone_constant.AUTHEN_BEGIN,
                                               zone_constant.AUTHEN_END)
            isauthenticated = self.get_nvp_value(
                parsed_data, zone_constant.AUTHENTICATED)
            if isauthenticated == "yes":
                if self.auth_version == "3":
                    auth_id = self.get_nvp_value(parsed_data,
                                                 zone_constant.IDENTIFIER)
                    auth_string = '%s:xxx:%s' % (self.switch_user, auth_id)
                else:
                    # Replace password in the authentication string with xxx
                    auth_string = '%s:xxx:%s' % (self.switch_user,
                                                 self.random_no)
                auth_token = base64.encode_as_text(auth_string).strip()
                auth_header = zone_constant.AUTH_STRING + auth_token
                return True, auth_header
            else:
                auth_error_code = self.get_nvp_value(parsed_data, "errCode")
                msg = (_("Authentication failed, verify the switch "
                         "credentials, error code %s.") % auth_error_code)
                LOG.error(msg)
                raise exception.BrocadeZoningHttpException(reason=msg)
        except Exception as e:
            msg = (_("Error while authenticating with switch: %s.")
                   % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def get_session_info(self):
        """Get the session information from the switch

        :returns: Connection status information.
        """
        try:
            headers = {zone_constant.AUTH_HEADER: self.auth_header}
            # GET request to session.html
            response = self.connect(zone_constant.GET_METHOD,
                                    zone_constant.SESSION_PAGE_ACTION,
                                    header=headers)
        except Exception as e:
            msg = (_("Error while getting session information %s.")
                   % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        return response

    def get_parsed_data(self, data, delim1, delim2):
        """Return the sub string between the delimiters.

        :param data: String to manipulate
        :param delim1: Delimiter 1
        :param delim2: Delimiter 2
        :returns: substring between the delimiters
        """
        try:
            start = data.index(delim1)
            start = start + len(delim1)
            end = data.index(delim2)
            return data[start:end]
        except ValueError as e:
            msg = (_("Error while parsing the data: %s.") % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def get_nvp_value(self, data, keyname):
        """Get the value for the key passed.

        :param data: NVP to manipulate
        :param keyname: Key name
        :returns: value for the NVP
        """
        try:
            start = data.index(keyname)
            start = start + len(keyname)
            temp = data[start:]
            end = temp.index("\n")
            return (temp[:end].lstrip('= '))
        except ValueError as e:
            msg = (_("Error while getting nvp value: %s.") % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def get_managable_vf_list(self, session_info):
        """List of VFIDs that can be managed.

        :param session_info: Session information from the switch
        :returns: manageable VF list
        :raises BrocadeZoningHttpException:
        """
        try:
            # Check the value of manageableLFList NVP,
            # throw exception as not supported if the nvp not available
            vf_list = self.get_nvp_value(session_info,
                                         zone_constant.MANAGEABLE_VF)
            if vf_list:
                vf_list = vf_list.split(",")  # convert the string to list
        except exception.BrocadeZoningHttpException as e:
            msg = (_("Error while checking whether "
                     "VF is available for management %s.") % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        return vf_list[:-1]

    def change_vf_context(self, vfid, session_data):
        """Change the VF context in the session.

        :param vfid: VFID to which context should be changed.
        :param session_data: Session information from the switch
        :raises BrocadeZoningHttpException:
        """
        try:
            managable_vf_list = self.get_managable_vf_list(session_data)
            LOG.debug("Manageable VF IDs are %(vflist)s.",
                      {'vflist': managable_vf_list})
            # proceed changing the VF context
            # if VF id can be managed if not throw exception
            if vfid in managable_vf_list:
                headers = {zone_constant.AUTH_HEADER: self.auth_header}
                data = zone_constant.CHANGE_VF.format(vfid=vfid)
                response = self.connect(zone_constant.POST_METHOD,
                                        zone_constant.SESSION_PAGE,
                                        data,
                                        headers)
                parsed_info = self.get_parsed_data(response,
                                                   zone_constant.SESSION_BEGIN,
                                                   zone_constant.SESSION_END)
                session_LF_Id = self.get_nvp_value(parsed_info,
                                                   zone_constant.SESSION_LF_ID)
                if session_LF_Id == vfid:
                    LOG.info("VF context is changed in the session.")
                else:
                    msg = _("Cannot change VF context in the session.")
                    LOG.error(msg)
                    raise exception.BrocadeZoningHttpException(reason=msg)

            else:
                msg = (_("Cannot change VF context, "
                         "specified VF is not available "
                         "in the manageable VF list %(vf_list)s.")
                       % {'vf_list': managable_vf_list})
                LOG.error(msg)
                raise exception.BrocadeZoningHttpException(reason=msg)
        except exception.BrocadeZoningHttpException as e:
            msg = (_("Error while changing VF context %s.") % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def get_zone_info(self):
        """Parse all the zone information and store it in the dictionary."""

        try:
            self.cfgs = {}
            self.zones = {}
            self.active_cfg = ''
            self.alias = {}
            self.qlps = {}
            self.ifas = {}
            headers = {zone_constant.AUTH_HEADER: self.auth_header}
            # GET request to gzoneinfo.htm
            response = self.connect(zone_constant.GET_METHOD,
                                    zone_constant.ZONE_PAGE,
                                    header=headers)
            # get the zone string from the response
            self.parsed_raw_zoneinfo = self.get_parsed_data(
                response,
                zone_constant.ZONEINFO_BEGIN,
                zone_constant.ZONEINFO_END).strip("\n")
            LOG.debug("Original zone string from the switch: %(zoneinfo)s",
                      {'zoneinfo': self.parsed_raw_zoneinfo})
            # convert the zone string to list
            zoneinfo = self.parsed_raw_zoneinfo.split()
            i = 0
            while i < len(zoneinfo):
                info = zoneinfo[i]
                # check for the cfg delimiter
                if zone_constant.CFG_DELIM in info:
                    # extract the cfg name
                    cfg_name = info.lstrip(zone_constant.CFG_DELIM)
                    # update the dict as
                    # self.cfgs={cfg_name:zone_name1;zone_name2}
                    self.cfgs.update({cfg_name: zoneinfo[i + 1]})
                    i = i + 2
                # check for the zone delimiter
                elif zone_constant.ZONE_DELIM in info:
                    # extract the zone name
                    zone_name = info.lstrip(zone_constant.ZONE_DELIM)
                    # update the dict as
                    # self.zones={zone_name:members1;members2}
                    self.zones.update({zone_name: zoneinfo[i + 1]})
                    i = i + 2
                elif zone_constant.ALIAS_DELIM in info:
                    alias_name = info.lstrip(zone_constant.ALIAS_DELIM)
                    # update the dict as
                    # self.alias={alias_name:members1;members2}
                    self.alias.update({alias_name: zoneinfo[i + 1]})
                    i = i + 2
                # check for quickloop zones
                elif zone_constant.QLP_DELIM in info:
                    qlp_name = info.lstrip(zone_constant.QLP_DELIM)
                    # update the map as self.qlps={qlp_name:members1;members2}
                    self.qlps.update({qlp_name: zoneinfo[i + 1]})
                    i = i + 2
                # check for fabric assist zones
                elif zone_constant.IFA_DELIM in info:
                    ifa_name = info.lstrip(zone_constant.IFA_DELIM)
                    # update the map as self.ifas={ifa_name:members1;members2}
                    self.ifas.update({ifa_name: zoneinfo[i + 1]})
                    i = i + 2
                elif zone_constant.ACTIVE_CFG_DELIM in info:
                    # update the string self.active_cfg=cfg_name
                    self.active_cfg = info.lstrip(
                        zone_constant.ACTIVE_CFG_DELIM)
                    if self.active_cfg == zone_constant.DEFAULT_CFG:
                        self.active_cfg = ""
                    i = i + 2
                else:
                    i = i + 1
        except Exception as e:
            msg = (_("Error while changing VF context %s.") % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def is_supported_firmware(self):
        """Check firmware version is v6.4 or higher.

        This API checks if the firmware version per the plug-in support level.
        This only checks major and minor version.

        :returns: True if firmware is supported else False.
        :raises BrocadeZoningHttpException:
        """

        isfwsupported = False

        try:
            headers = {zone_constant.AUTH_HEADER: self.auth_header}
            # GET request to switch.html
            response = self.connect(zone_constant.GET_METHOD,
                                    zone_constant.SWITCH_PAGE,
                                    header=headers)
            parsed_data = self.get_parsed_data(response,
                                               zone_constant.SWITCHINFO_BEGIN,
                                               zone_constant.SWITCHINFO_END)

            # get the firmware version nvp value
            fwVersion = self.get_nvp_value(
                parsed_data,
                zone_constant.FIRMWARE_VERSION).lstrip('v')

            ver = fwVersion.split(".")
            LOG.debug("Firmware version: %(version)s.", {'version': ver})
            if int(ver[0] + ver[1]) > 63:
                isfwsupported = True

        except Exception as e:
            msg = (_("Error while checking the firmware version %s.")
                   % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        return isfwsupported

    def get_active_zone_set(self):
        """Return the active zone configuration.

        Return active zoneset from fabric. When none of the configurations
        are active then it will return empty map.

        :returns: Map -- active zone set map in the following format

        .. code-block:: python

            {
                'zones':
                    {'openstack50060b0000c26604201900051ee8e329':
                        ['50060b0000c26604', '201900051ee8e329']
                    },
                'active_zone_config': 'OpenStack_Cfg'
            }

        :raises BrocadeZoningHttpException:
        """
        active_zone_set = {}
        zones_map = {}
        try:
            self.get_zone_info()  # get the zone information of the switch
            if self.active_cfg != '':
                # get the zones list of the active_Cfg
                zones_list = self.cfgs[self.active_cfg].split(";")
                for n in zones_list:
                    # build the zones map
                    zones_map.update(
                        {n: self.zones[n].split(";")})
            # Format map in the correct format
            active_zone_set = {
                "active_zone_config": self.active_cfg, "zones": zones_map}
            return active_zone_set
        except Exception as e:
            msg = (_("Failed getting active zone set from fabric %s.")
                   % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def add_zones(self, add_zones_info, activate, active_zone_set=None):
        """Add zone configuration.

        This method will add the zone configuration passed by user.

        :param add_zones_info: Zone names mapped to members. Zone members
                               are colon separated but case-insensitive

        .. code-block:: python

            {   zonename1:[zonememeber1,zonemember2,...],
                zonename2:[zonemember1, zonemember2,...]...}

            e.g:

            {
                'openstack50060b0000c26604201900051ee8e329':
                    ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:29']
            }

        :param activate: True will activate the zone config.
        :param active_zone_set: Active zone set dict retrieved from
                                get_active_zone_set method
        :raises BrocadeZoningHttpException:
        """
        LOG.debug("Add zones - zones passed: %(zones)s.",
                  {'zones': add_zones_info})
        cfg_name = zone_constant.CFG_NAME
        cfgs = self.cfgs
        zones = self.zones
        alias = self.alias
        qlps = self.qlps
        ifas = self.ifas
        active_cfg = self.active_cfg
        # update the active_cfg, zones and cfgs map with new information
        zones, cfgs, active_cfg = self.add_zones_cfgs(cfgs,
                                                      zones,
                                                      add_zones_info,
                                                      active_cfg,
                                                      cfg_name)
        # Build the zonestring with updated maps
        data = self.form_zone_string(cfgs,
                                     active_cfg,
                                     zones,
                                     alias,
                                     qlps,
                                     ifas,
                                     activate)
        LOG.debug("Add zones: final zone string after applying "
                  "to the switch: %(zonestring)s", {'zonestring': data})
        # Post the zone data to the switch
        error_code, error_msg = self.post_zone_data(data)
        if error_code != "0":
            msg = (_("Applying the zones and cfgs to the switch failed "
                     "(error code=%(err_code)s error msg=%(err_msg)s.")
                   % {'err_code': error_code, 'err_msg': error_msg})

            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def update_zones(self, zone_info, activate, operation,
                     active_zone_set=None):
        """Update zone configuration.

        This method will update the zone configuration passed by user.

        :param zone_info: Zone names mapped to members. Zone members
                          are colon separated but case-insensitive

        .. code-block:: python

            {   zonename1:[zonememeber1,zonemember2,...],
                zonename2:[zonemember1, zonemember2,...]...}

            e.g:

            {
                'openstack50060b0000c26604201900051ee8e329':
                    ['50:06:0b:00:00:c2:66:04', '20:19:00:05:1e:e8:e3:29']
            }

        :param activate: True will activate the zone config.
        :param operation: ZONE_ADD or ZONE_REMOVE
        :param active_zone_set: Active zone set dict retrieved from
                                get_active_zone_set method
        :raises BrocadeZoningHttpException:
        """
        LOG.debug("Update zones - zones passed: %(zones)s.",
                  {'zones': zone_info})
        cfgs = self.cfgs
        zones = self.zones
        alias = self.alias
        qlps = self.qlps
        ifas = self.ifas
        active_cfg = self.active_cfg
        # update the zones with new information
        zones = self._update_zones(zones, zone_info, operation)
        # Build the zonestring with updated maps
        data = self.form_zone_string(cfgs,
                                     active_cfg,
                                     zones,
                                     alias,
                                     qlps,
                                     ifas,
                                     activate)
        LOG.debug("Update zones: final zone string after applying "
                  "to the switch: %(zonestring)s", {'zonestring': data})
        # Post the zone data to the switch
        error_code, error_msg = self.post_zone_data(data)
        if error_code != "0":
            msg = (_("Applying the zones and cfgs to the switch failed "
                     "(error code=%(err_code)s error msg=%(err_msg)s.")
                   % {'err_code': error_code, 'err_msg': error_msg})

            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def form_zone_string(self, cfgs, active_cfg,
                         zones, alias, qlps, ifas, activate):
        """Build the zone string in the required format.

        :param cfgs:  cfgs map
        :param active_cfg: Active cfg string
        :param zones: zones map
        :param alias: alias map
        :param qlps: qlps map
        :param ifas: ifas map
        :param activate: True will activate config.
        :returns: zonestring in the required format
        :raises BrocadeZoningHttpException:
        """
        try:
            zoneString = zone_constant.ZONE_STRING_PREFIX

            # based on the activate save only will be changed
            saveonly = "false" if activate is True else "true"

            # Form the zone string based on the dictionary of each items
            for cfg in sorted(cfgs.keys()):
                zoneString += (zone_constant.CFG_DELIM +
                               cfg + " " + cfgs.get(cfg) + " ")
            for zone in sorted(zones.keys()):
                zoneString += (zone_constant.ZONE_DELIM +
                               zone + " " + zones.get(zone) + " ")
            for al in sorted(alias.keys()):
                zoneString += (zone_constant.ALIAS_DELIM +
                               al + " " + alias.get(al) + " ")
            for qlp in sorted(qlps.keys()):
                zoneString += (zone_constant.QLP_DELIM +
                               qlp + " " + qlps.get(qlp) + " ")
            for ifa in sorted(ifas.keys()):
                zoneString += (zone_constant.IFA_DELIM +
                               ifa + " " + ifas.get(ifa) + " ")
            # append the active_cfg string only if it is not null and activate
            # is true
            if active_cfg != "" and activate:
                zoneString += (zone_constant.ACTIVE_CFG_DELIM +
                               active_cfg + " null ")
            # Build the final zone string
            zoneString += zone_constant.ZONE_END_DELIM + saveonly
        except Exception as e:
            msg = (_("Exception while forming the zone string: %s.")
                   % six.text_type(e))
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        # Reconstruct the zoneString to type base string for OpenSSL
        return encodeutils.safe_encode(zoneString)

    def add_zones_cfgs(self, cfgs, zones, add_zones_info,
                       active_cfg, cfg_name):
        """Add the zones and cfgs map based on the new zones info.

        This method will return the updated zones,cfgs and active_cfg

        :param cfgs: Existing cfgs map
        :param active_cfg: Existing Active cfg string
        :param zones: Existing zones map
        :param add_zones_info: Zones map to add
        :param active_cfg: Existing active cfg
        :param cfg_name: New cfg name
        :returns: updated zones, zone configs map, and active_cfg
        """
        cfg_string = ""
        delimiter = ""
        zones_in_active_cfg = ""
        try:
            if active_cfg:
                zones_in_active_cfg = cfgs.get(active_cfg)
            for zone_name, members in add_zones_info.items():
                # if new zone is not active_cfg, build the cfg string with the
                # new zones
                if zone_name not in zones_in_active_cfg:
                    cfg_string += delimiter + zone_name
                    delimiter = ";"
                    # add a new zone with the members
                    zones.update({zone_name: ";".join(members)})
            # update cfg string
            if active_cfg:
                if cfg_string:
                    # update the existing active cfg map with cfgs string
                    cfgs.update(
                        {active_cfg: cfg_string + ";" + cfgs.get(active_cfg)})
            else:
                # create new cfg and update that cfgs map with the new cfg
                active_cfg = cfg_name
                cfgs.update({cfg_name: cfg_string})
        except Exception as e:
            msg = (_("Error while updating the new zones and cfgs "
                     "in the zone string. Error %(description)s.")
                   % {'description': six.text_type(e)})
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        return zones, cfgs, active_cfg

    def _update_zones(self, zones, updated_zones_info, operation):
        """Update the zones based on the updated zones info.

        This method will return the updated zones

        :param zones: Existing zones map
        :param updated_zones_info: Zones map to update
        :param operation: ZONE_ADD or ZONE_REMOVE
        :returns: updated zones
        """
        try:
            for zone_name in updated_zones_info:
                members = updated_zones_info[zone_name]
                # update the zone string
                # if zone name already exists and dont have the new members
                # already
                current_members = zones.get(zone_name).split(";")
                if operation == zone_constant.ZONE_ADD:
                    new_members = set(members).difference(set(current_members))
                    if new_members:
                        # update the existing zone with new members
                        zones.update({zone_name: (";".join(new_members) +
                                     ";" + zones.get(zone_name))})
                else:
                    new_members = set(current_members).difference(set(members))
                    if new_members:
                        zones.pop(zone_name)
                        zones.update({zone_name: ";".join(new_members)})
        except Exception as e:
            msg = (_("Error while updating the zones "
                     "in the zone string. Error %(description)s.")
                   % {'description': six.text_type(e)})
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        return zones

    def is_vf_enabled(self):
        """To check whether VF is enabled or not.

        :returns: boolean to indicate VF enabled and session information
        """
        session_info = self.get_session_info()
        parsed_data = self.get_parsed_data(session_info,
                                           zone_constant.SESSION_BEGIN,
                                           zone_constant.SESSION_END)
        try:
            is_vf_enabled = bool(self.get_nvp_value(
                parsed_data, zone_constant.VF_ENABLED))
        except exception.BrocadeZoningHttpException:
            is_vf_enabled = False
            parsed_data = None
        return is_vf_enabled, parsed_data

    def get_nameserver_info(self):
        """Get name server data from fabric.

        Return the connected node port wwn list(local
        and remote) for the given switch fabric.

        :returns: name server information.
        """
        nsinfo = []
        headers = {zone_constant.AUTH_HEADER: self.auth_header}
        response = self.connect(zone_constant.GET_METHOD,
                                zone_constant.NS_PAGE,
                                header=headers)  # GET request to nsinfo.html
        for line in response.splitlines():
            if line.startswith(zone_constant.NS_DELIM):
                nsinfo.append(line.split('=')[-1])
        return nsinfo

    def delete_zones_cfgs(
            self, cfgs, zones,
            delete_zones_info, active_cfg):
        """Delete the zones and cfgs map based on the new zones info.

        Return the updated zones, cfgs and active_cfg after deleting the
        required items.

        :param cfgs: Existing cfgs map
        :param active_cfg: Existing Active cfg string
        :param zones: Existing zones map
        :param delete_zones_info: Zones map to add
        :param active_cfg: Existing active cfg
        :returns: updated zones, zone config sets, and active zone config
        :raises BrocadeZoningHttpException:
        """
        try:
            delete_zones_info = delete_zones_info.split(";")
            for zone in delete_zones_info:
                # remove the zones from the zone map
                zones.pop(zone)
                # iterated all the cfgs, but need to check since in SSH only
                # active cfg is iterated
                for k, v in cfgs.items():
                    v = v.split(";")
                    if zone in v:
                        # remove the zone from the cfg string
                        v.remove(zone)
                        # if all the zones are removed, remove the cfg from the
                        # cfg map
                        if not v:
                            cfgs.pop(k)
                        # update the original cfg with the updated string
                        else:
                            cfgs[k] = ";".join(v)

            # if all the zones are removed in the active_cfg, update it with
            # empty string
            if active_cfg not in cfgs:
                active_cfg = ""
        except KeyError as e:
            msg = (_("Error while removing the zones and cfgs "
                     "in the zone string: %(description)s.")
                   % {'description': six.text_type(e)})
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        return zones, cfgs, active_cfg

    def delete_zones(self, delete_zones_info, activate, active_zone_set=None):
        """Delete zones from fabric.

        Deletes zones in the active zone config.

        :param zone_names: zoneNames separated by semicolon
        :param activate: True/False
        :param active_zone_set: the active zone set dict retrieved
                                from get_active_zone_set method
        """
        cfgs = self.cfgs
        zones = self.zones
        alias = self.alias
        qlps = self.qlps
        ifas = self.ifas
        active_cfg = self.active_cfg
        # update the active_cfg, zones and cfgs map with required information
        # being removed
        zones, cfgs, active_cfg = self.delete_zones_cfgs(
            cfgs,
            zones,
            delete_zones_info,
            active_cfg)
        # Build the zonestring with updated maps
        data = self.form_zone_string(cfgs,
                                     active_cfg,
                                     zones,
                                     alias,
                                     qlps,
                                     ifas,
                                     activate)
        LOG.debug("Delete zones: final zone string after applying "
                  "to the switch: %(zonestring)s", {'zonestring': data})
        error_code, error_msg = self.post_zone_data(data)
        if error_code != "0":
            msg = (_("Applying the zones and cfgs to the switch failed "
                     "(error code=%(err_code)s error msg=%(err_msg)s.")
                   % {'err_code': error_code, 'err_msg': error_msg})
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def post_zone_data(self, data):
        """Send POST request to the switch with the payload.

        :param data: payload to be sent to switch
        """

        status = "progress"
        parsed_data_txn = ""
        headers = {zone_constant.AUTH_HEADER: self.auth_header}

        LOG.debug("Requesting the switch with posting the zone string.")
        # POST request to gzoneinfo with zonestring as payload
        response = self.connect(zone_constant.POST_METHOD,
                                zone_constant.ZONE_PAGE,
                                data,
                                headers)
        parsed_data = self.get_parsed_data(response,
                                           zone_constant.ZONE_TX_BEGIN,
                                           zone_constant.ZONE_TX_END)
        transID = self.get_nvp_value(parsed_data,
                                     zone_constant.ZONE_TX_ID)
        transURL = zone_constant.ZONE_TRAN_STATUS.format(txnId=transID)
        timeout = 360
        sleep_time = 3
        time_elapsed = 0
        while(status != "done"):
            txn_response = self.connect(
                zone_constant.GET_METHOD, transURL, "", headers)
            parsed_data_txn = self.get_parsed_data(txn_response,
                                                   zone_constant.ZONE_TX_BEGIN,
                                                   zone_constant.ZONE_TX_END)
            status = self.get_nvp_value(parsed_data_txn,
                                        zone_constant.ZONE_TX_STATUS)
            time.sleep(sleep_time)
            time_elapsed += sleep_time
            if time_elapsed > timeout:
                break
        if status != "done":
            errorCode = -1
            errorMessage = ("Timed out, waiting for zone transaction on "
                            "the switch to complete")
        else:
            errorCode = self.get_nvp_value(parsed_data_txn,
                                           zone_constant.ZONE_ERROR_CODE)
            errorMessage = self.get_nvp_value(parsed_data_txn,
                                              zone_constant.ZONE_ERROR_MSG)
        return errorCode, errorMessage

    def check_change_vf_context(self):
        """Check whether VF related configurations is valid and proceed."""
        vf_enabled, session_data = self.is_vf_enabled()
        # VF enabled will be false if vf is disable or not supported
        LOG.debug("VF enabled on switch: %(vfenabled)s.",
                  {'vfenabled': vf_enabled})
        # Change the VF context in the session
        if vf_enabled:
            if self.vfid is None:
                msg = _("No VF ID is defined in the configuration file.")
                LOG.error(msg)
                raise exception.BrocadeZoningHttpException(reason=msg)
            elif self.vfid != 128:
                self.change_vf_context(self.vfid, session_data)
        else:
            if self.vfid is not None:
                msg = _("VF is not enabled.")
                LOG.error(msg)
                raise exception.BrocadeZoningHttpException(reason=msg)

    def _disconnect(self):
        """Disconnect from the switch using HTTP/HTTPS protocol.

        :raises BrocadeZoningHttpException:
        """
        try:
            headers = {zone_constant.AUTH_HEADER: self.auth_header}
            response = self.connect(zone_constant.GET_METHOD,
                                    zone_constant.LOGOUT_PAGE,
                                    header=headers)
            return response
        except requests.exceptions.ConnectionError as e:
            msg = (_("Error while connecting the switch %(switch_id)s "
                     "with protocol %(protocol)s. Error: %(error)s.")
                   % {'switch_id': self.switch_ip,
                      'protocol': self.protocol,
                      'error': six.text_type(e)})
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)
        except exception.BrocadeZoningHttpException as ex:
            msg = (_("Unexpected status code from the switch %(switch_id)s "
                     "with protocol %(protocol)s for url %(page)s. "
                     "Error: %(error)s")
                   % {'switch_id': self.switch_ip,
                      'protocol': self.protocol,
                      'page': zone_constant.LOGOUT_PAGE,
                      'error': six.text_type(ex)})
            LOG.error(msg)
            raise exception.BrocadeZoningHttpException(reason=msg)

    def cleanup(self):
        """Close session."""
        self._disconnect()
        self.session.close()
