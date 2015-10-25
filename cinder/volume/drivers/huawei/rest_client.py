# Copyright (c) 2015 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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

import json
import six
import socket
import time

from oslo_log import log as logging
from oslo_utils import excutils
from six.moves import http_cookiejar
from six.moves import urllib

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils
from cinder.volume.drivers.huawei import constants
from cinder.volume.drivers.huawei import huawei_utils

LOG = logging.getLogger(__name__)


class RestClient(object):
    """Common class for Huawei OceanStor 18000 storage system."""

    def __init__(self, configuration):
        self.configuration = configuration
        self.xml_file_path = configuration.cinder_huawei_conf_file
        self.productversion = None
        self.init_http_head()

    def init_http_head(self):
        self.cookie = http_cookiejar.CookieJar()
        self.url = None
        self.device_id = None
        self.headers = {
            "Connection": "keep-alive",
            "Content-Type": "application/json",
        }

    def do_call(self, url=None, data=None, method=None,
                calltimeout=constants.SOCKET_TIMEOUT):
        """Send requests to 18000 server.

        Send HTTPS call, get response in JSON.
        Convert response into Python Object and return it.
        """
        if self.url:
            url = self.url + url
        handler = urllib.request.HTTPCookieProcessor(self.cookie)
        opener = urllib.request.build_opener(handler)
        urllib.request.install_opener(opener)
        res_json = None

        try:
            socket.setdefaulttimeout(calltimeout)
            req = urllib.request.Request(url, data, self.headers)
            if method:
                req.get_method = lambda: method
            res = urllib.request.urlopen(req).read().decode("utf-8")

            if "xx/sessions" not in url:
                LOG.info(_LI('\n\n\n\nRequest URL: %(url)s\n\n'
                             'Call Method: %(method)s\n\n'
                             'Request Data: %(data)s\n\n'
                             'Response Data:%(res)s\n\n'), {'url': url,
                                                            'method': method,
                                                            'data': data,
                                                            'res': res})

        except Exception as err:
            LOG.error(_LE('Bad response from server: %(url)s.'
                          ' Error: %(err)s'), {'url': url, 'err': err})
            json_msg = ('{"error":{"code": %s,"description": "Connect to '
                        'server error."}}') % constants.ERROR_CONNECT_TO_SERVER
            res_json = json.loads(json_msg)
            return res_json

        try:
            res_json = json.loads(res)
        except Exception as err:
            LOG.error(_LE('JSON transfer error: %s.'), err)
            raise

        return res_json

    def login(self):
        """Login 18000 array."""
        login_info = huawei_utils.get_login_info(self.xml_file_path)
        urlstr = login_info['RestURL']
        url_list = urlstr.split(";")
        device_id = None
        for item_url in url_list:
            url = item_url + "xx/sessions"
            data = json.dumps({"username": login_info['UserName'],
                               "password": login_info['UserPassword'],
                               "scope": "0"})
            self.init_http_head()
            result = self.do_call(url, data,
                                  calltimeout=constants.LOGIN_SOCKET_TIMEOUT)

            if (result['error']['code'] != 0) or ("data" not in result):
                LOG.error(_LE("Login error, reason is: %s."), result)
                continue

            LOG.debug('Login success: %(url)s', {'url': item_url})
            device_id = result['data']['deviceid']
            self.device_id = device_id
            self.url = item_url + device_id
            self.headers['iBaseToken'] = result['data']['iBaseToken']
            break

        if device_id is None:
            msg = _("Failed to login with all rest URLs.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return device_id

    @utils.synchronized('huawei_cinder_call', external=True)
    def call(self, url, data=None, method=None):
        """Send requests to server.

        If fail, try another RestURL.
        """
        device_id = None
        old_url = self.url
        result = self.do_call(url, data, method)
        error_code = result['error']['code']
        if (error_code == constants.ERROR_CONNECT_TO_SERVER
                or error_code == constants.ERROR_UNAUTHORIZED_TO_SERVER):
            LOG.error(_LE("Can't open the recent url, relogin."))
            device_id = self.login()

        if device_id is not None:
            LOG.debug('Replace URL: \n'
                      'Old URL: %(old_url)s\n,'
                      'New URL: %(new_url)s\n.',
                      {'old_url': old_url,
                       'new_url': self.url})
            result = self.do_call(url, data, method)
            if result['error']['code'] in constants.RELOGIN_ERROR_PASS:
                result['error']['code'] = 0
        return result

    def login_with_ip(self, login_info):
        """Login 18000 array with the specific URL."""
        urlstr = login_info['RestURL']
        url_list = urlstr.split(";")
        for item_url in url_list:
            url = item_url + "xx/sessions"
            data = json.dumps({"username": login_info['UserName'],
                               "password": login_info['UserPassword'],
                               "scope": '0'})
            result = self.call(url, data)

            if result['error']['code'] == constants.ERROR_CONNECT_TO_SERVER:
                continue

            if (result['error']['code'] != 0) or ('data' not in result):
                msg = (_("Login error, reason is: %s.") % result)
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            device_id = result['data']['deviceid']
            self.device_id = device_id
            self.url = item_url + device_id
            self.headers['iBaseToken'] = result['data']['iBaseToken']

            return device_id

        msg = _("Login error: Can not connect to server.")
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(data=msg)

    def logout(self):
        """Logout the session."""
        url = "/sessions"
        if self.url:
            result = self.call(url, None, "DELETE")
            self._assert_rest_result(result, _('Logout session error.'))

    def _assert_rest_result(self, result, err_str):
        if result['error']['code'] != 0:
            msg = (_('%(err)s\nresult: %(res)s.') % {'err': err_str,
                                                     'res': result})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _assert_data_in_result(self, result, msg):
        if 'data' not in result:
            err_msg = (_('%s "data" was not in result.') % msg)
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def create_volume(self, lun_param):
        url = "/lun"
        data = json.dumps(lun_param)
        result = self.call(url, data)
        if result['error']['code'] == constants.ERROR_VOLUME_ALREADY_EXIST:
            lun_id = self.get_volume_by_name(lun_param["NAME"])
            if lun_id:
                return self.get_lun_info(lun_id)

        msg = _('Create volume error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']

    def check_lun_exist(self, lun_id):
        url = "/lun/" + lun_id
        result = self.call(url, None, "GET")
        error_code = result['error']['code']
        if error_code != 0:
            return False

        return True

    def delete_lun(self, lun_id):
        lun_group_ids = self.get_lungroupids_by_lunid(lun_id)
        if lun_group_ids and len(lun_group_ids) == 1:
            self.remove_lun_from_lungroup(lun_group_ids[0], lun_id)

        url = "/lun/" + lun_id
        data = json.dumps({"TYPE": "11",
                           "ID": lun_id})
        result = self.call(url, data, "DELETE")
        self._assert_rest_result(result, _('Delete lun error.'))

    def find_all_pools(self):
        url = "/storagepool"
        result = self.call(url, None)
        msg = _('Query resource pool error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)
        return result

    def find_pool_info(self, pool_name=None, result=None):
        pool_info = {}
        if not pool_name:
            return pool_info

        if 'data' in result:
            for item in result['data']:
                if pool_name.strip() == item['NAME']:
                    # USAGETYPE means pool type.
                    if ('USAGETYPE' in item and
                       item['USAGETYPE'] == constants.FILE_SYSTEM_POOL_TYPE):
                        break
                    pool_info['ID'] = item['ID']
                    pool_info['CAPACITY'] = item.get('DATASPACE',
                                                     item['USERFREECAPACITY'])
                    pool_info['TOTALCAPACITY'] = item['USERTOTALCAPACITY']
                    break
        return pool_info

    def _get_id_from_result(self, result, name, key):
        if 'data' in result:
            for item in result['data']:
                if name == item.get(key):
                    return item['ID']

    def get_volume_by_name(self, name):
        url = "/lun?range=[0-65535]"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get volume by name error.'))

        return self._get_id_from_result(result, name, 'NAME')

    def activate_snapshot(self, snapshot_id):
        activate_url = "/snapshot/activate"
        data = json.dumps({"SNAPSHOTLIST": [snapshot_id]})
        result = self.call(activate_url, data)
        self._assert_rest_result(result, _('Activate snapshot error.'))

    def create_snapshot(self, snapshot):
        snapshot_name = huawei_utils.encode_name(snapshot['id'])
        snapshot_description = snapshot['id']
        volume_name = huawei_utils.encode_name(snapshot['volume_id'])

        LOG.info(_LI(
            'create_snapshot:snapshot name: %(snapshot)s, '
            'volume name: %(volume)s.'),
            {'snapshot': snapshot_name,
             'volume': volume_name})

        volume = snapshot['volume']
        lun_id = self.get_lunid(volume, volume_name)

        url = "/snapshot"
        data = json.dumps({"TYPE": "27",
                           "NAME": snapshot_name,
                           "PARENTTYPE": "11",
                           "DESCRIPTION": snapshot_description,
                           "PARENTID": lun_id})
        result = self.call(url, data)

        msg = _('Create snapshot error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']

    def get_lunid(self, volume, volume_name):
        lun_id = (volume.get('provider_location') or
                  self.get_volume_by_name(volume_name))
        if not lun_id:
            msg = (_("Can't find lun info on the array, "
                     "lun name is: %(name)s.") % {'name': volume_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return lun_id

    def check_snapshot_exist(self, snapshot_id):
        url = "/snapshot/%s" % snapshot_id
        result = self.call(url, None, "GET")
        error_code = result['error']['code']
        if error_code != 0:
            return False

        return True

    def stop_snapshot(self, snapshot_id):
        url = "/snapshot/stop"
        stopdata = json.dumps({"ID": snapshot_id})
        result = self.call(url, stopdata, "PUT")
        self._assert_rest_result(result, _('Stop snapshot error.'))

    def delete_snapshot(self, snapshotid):
        url = "/snapshot/%s" % snapshotid
        data = json.dumps({"TYPE": "27", "ID": snapshotid})
        result = self.call(url, data, "DELETE")
        self._assert_rest_result(result, _('Delete snapshot error.'))

    def get_snapshotid_by_name(self, name):
        url = "/snapshot?range=[0-32767]"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get snapshot id error.'))

        return self._get_id_from_result(result, name, 'NAME')

    def create_luncopy(self, luncopyname, srclunid, tgtlunid):
        """Create a luncopy."""
        url = "/luncopy"
        data = json.dumps({"TYPE": 219,
                           "NAME": luncopyname,
                           "DESCRIPTION": luncopyname,
                           "COPYSPEED": 2,
                           "LUNCOPYTYPE": "1",
                           "SOURCELUN": ("INVALID;%s;INVALID;INVALID;INVALID"
                                         % srclunid),
                           "TARGETLUN": ("INVALID;%s;INVALID;INVALID;INVALID"
                                         % tgtlunid)})
        result = self.call(url, data)

        msg = _('Create luncopy error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']['ID']

    def add_host_into_hostgroup(self, host_id):
        """Associate host to hostgroup.

        If hostgroup doesn't exist, create one.
        """
        hostgroup_name = constants.HOSTGROUP_PREFIX + host_id
        hostgroup_id = self.create_hostgroup_with_check(hostgroup_name)
        is_associated = self._is_host_associate_to_hostgroup(hostgroup_id,
                                                             host_id)
        if not is_associated:
            self._associate_host_to_hostgroup(hostgroup_id, host_id)

        return hostgroup_id

    def find_tgt_port_group(self, tgt_port_group):
        """Find target portgroup id by target port group name."""
        url = "/portgroup?range=[0-8191]&TYPE=257"
        result = self.call(url, None, "GET")

        msg = _('Find portgroup error.')
        self._assert_rest_result(result, msg)
        msg = _('Can not find the portgroup on the array.')
        self._assert_data_in_result(result, msg)

        return self._get_id_from_result(result, tgt_port_group, 'NAME')

    def _associate_portgroup_to_view(self, view_id, portgroup_id):
        url = "/MAPPINGVIEW/CREATE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "257",
                           "ASSOCIATEOBJID": portgroup_id,
                           "TYPE": "245",
                           "ID": view_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Associate portgroup to mapping '
                                 'view error.'))

    def _portgroup_associated(self, view_id, portgroup_id):
        url = ("/mappingview/associate?TYPE=245&"
               "ASSOCIATEOBJTYPE=257&ASSOCIATEOBJID=%s" % portgroup_id)
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Check portgroup associate error.'))

        if self._get_id_from_result(result, view_id, 'ID'):
            return True
        return False

    def do_mapping(self, lun_id, hostgroup_id, host_id, tgtportgroup_id=None):
        """Add hostgroup and lungroup to mapping view."""
        lungroup_name = constants.LUNGROUP_PREFIX + host_id
        mapping_view_name = constants.MAPPING_VIEW_PREFIX + host_id
        lungroup_id = self._find_lungroup(lungroup_name)
        view_id = self.find_mapping_view(mapping_view_name)
        map_info = {}

        LOG.info(_LI(
            'do_mapping, lun_group: %(lun_group)s, '
            'view_id: %(view_id)s, lun_id: %(lun_id)s.'),
            {'lun_group': lungroup_id,
             'view_id': view_id,
             'lun_id': lun_id})

        try:
            # Create lungroup and add LUN into to lungroup.
            if lungroup_id is None:
                lungroup_id = self._create_lungroup(lungroup_name)
            is_associated = self._is_lun_associated_to_lungroup(lungroup_id,
                                                                lun_id)
            if not is_associated:
                self.associate_lun_to_lungroup(lungroup_id, lun_id)

            if view_id is None:
                view_id = self._add_mapping_view(mapping_view_name)
                self._associate_hostgroup_to_view(view_id, hostgroup_id)
                self._associate_lungroup_to_view(view_id, lungroup_id)
                if tgtportgroup_id:
                    self._associate_portgroup_to_view(view_id, tgtportgroup_id)

            else:
                if not self.hostgroup_associated(view_id, hostgroup_id):
                    self._associate_hostgroup_to_view(view_id, hostgroup_id)
                if not self.lungroup_associated(view_id, lungroup_id):
                    self._associate_lungroup_to_view(view_id, lungroup_id)
                if tgtportgroup_id:
                    if not self._portgroup_associated(view_id,
                                                      tgtportgroup_id):
                        self._associate_portgroup_to_view(view_id,
                                                          tgtportgroup_id)

            version = self.find_array_version()
            if version >= constants.ARRAY_VERSION:
                aval_luns = self.find_view_by_id(view_id)
                map_info["lun_id"] = lun_id
                map_info["view_id"] = view_id
                map_info["aval_luns"] = aval_luns

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE(
                    'Error occurred when adding hostgroup and lungroup to '
                    'view. Remove lun from lungroup now.'))
                self.remove_lun_from_lungroup(lungroup_id, lun_id)

        return map_info

    def ensure_initiator_added(self, xml_file_path, initiator_name, host_id):
        added = self._initiator_is_added_to_array(initiator_name)
        if not added:
            self._add_initiator_to_array(initiator_name)
        if not self.is_initiator_associated_to_host(initiator_name):
            self._associate_initiator_to_host(xml_file_path,
                                              initiator_name,
                                              host_id)

    def _get_iscsi_tgt_port(self):
        url = "/iscsidevicename"
        result = self.call(url, None)

        msg = _('Get iSCSI target port error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data'][0]['CMO_ISCSI_DEVICE_NAME']

    def find_hostgroup(self, groupname):
        """Get the given hostgroup id."""
        url = "/hostgroup?range=[0-8191]"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get hostgroup information error.'))

        return self._get_id_from_result(result, groupname, 'NAME')

    def _find_lungroup(self, lungroup_name):
        """Get the given hostgroup id."""
        url = "/lungroup?range=[0-8191]"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get lungroup information error.'))

        return self._get_id_from_result(result, lungroup_name, 'NAME')

    def create_hostgroup_with_check(self, hostgroup_name):
        """Check if host exists on the array, or create it."""
        hostgroup_id = self.find_hostgroup(hostgroup_name)
        if hostgroup_id:
            LOG.info(_LI(
                'create_hostgroup_with_check. '
                'hostgroup name: %(name)s, '
                'hostgroup id: %(id)s'),
                {'name': hostgroup_name,
                 'id': hostgroup_id})
            return hostgroup_id

        try:
            hostgroup_id = self._create_hostgroup(hostgroup_name)
        except Exception:
            LOG.info(_LI(
                'Failed to create hostgroup: %(name)s. '
                'Please check if it exists on the array.'),
                {'name': hostgroup_name})
            hostgroup_id = self.find_hostgroup(hostgroup_name)
            if hostgroup_id is None:
                err_msg = (_(
                    'Failed to create hostgroup: %(name)s. '
                    'Check if it exists on the array.')
                    % {'name': hostgroup_name})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

        LOG.info(_LI(
            'create_hostgroup_with_check. '
            'Create hostgroup success. '
            'hostgroup name: %(name)s, '
            'hostgroup id: %(id)s'),
            {'name': hostgroup_name,
             'id': hostgroup_id})
        return hostgroup_id

    def _create_hostgroup(self, hostgroup_name):
        url = "/hostgroup"
        data = json.dumps({"TYPE": "14", "NAME": hostgroup_name})
        result = self.call(url, data)

        msg = _('Create hostgroup error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']['ID']

    def _create_lungroup(self, lungroup_name):
        url = "/lungroup"
        data = json.dumps({"DESCRIPTION": lungroup_name,
                           "APPTYPE": '0',
                           "GROUPTYPE": '0',
                           "NAME": lungroup_name})
        result = self.call(url, data)

        msg = _('Create lungroup error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']['ID']

    def delete_lungroup(self, lungroup_id):
        url = "/LUNGroup/" + lungroup_id
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, _('Delete lungroup error.'))

    def lungroup_associated(self, view_id, lungroup_id):
        url_subfix = ("/mappingview/associate?TYPE=245&"
                      "ASSOCIATEOBJTYPE=256&ASSOCIATEOBJID=%s" % lungroup_id)
        url = url_subfix
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Check lungroup associate error.'))

        if self._get_id_from_result(result, view_id, 'ID'):
            return True
        return False

    def hostgroup_associated(self, view_id, hostgroup_id):
        url_subfix = ("/mappingview/associate?TYPE=245&"
                      "ASSOCIATEOBJTYPE=14&ASSOCIATEOBJID=%s" % hostgroup_id)
        url = url_subfix
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Check hostgroup associate error.'))

        if self._get_id_from_result(result, view_id, 'ID'):
            return True
        return False

    def find_host_lun_id(self, host_id, lun_id):
        url = ("/lun/associate?TYPE=11&ASSOCIATEOBJTYPE=21"
               "&ASSOCIATEOBJID=%s" % (host_id))
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Find host lun id error.'))

        host_lun_id = 1
        if 'data' in result:
            for item in result['data']:
                if lun_id == item['ID']:
                    associate_data = item['ASSOCIATEMETADATA']
                    try:
                        hostassoinfo = json.loads(associate_data)
                        host_lun_id = hostassoinfo['HostLUNID']
                        break
                    except Exception as err:
                        LOG.error(_LE("JSON transfer data error. %s."), err)
                        raise
        return host_lun_id

    def find_host(self, host_name):
        """Get the given host ID."""
        url = "/host?range=[0-65535]"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Find host in hostgroup error.'))

        return self._get_id_from_result(result, host_name, 'NAME')

    def add_host_with_check(self, host_name, host_name_before_hash):
        host_id = self.find_host(host_name)
        if host_id:
            LOG.info(_LI(
                'add_host_with_check. '
                'host name: %(name)s, '
                'host id: %(id)s'),
                {'name': host_name,
                 'id': host_id})
            return host_id

        try:
            host_id = self._add_host(host_name, host_name_before_hash)
        except Exception:
            LOG.info(_LI(
                'Failed to create host: %(name)s. '
                'Check if it exists on the array.'),
                {'name': host_name})
            host_id = self.find_host(host_name)
            if not host_id:
                err_msg = (_(
                    'Failed to create host: %(name)s. '
                    'Please check if it exists on the array.'),
                    {'name': host_name})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

        LOG.info(_LI(
            'add_host_with_check. '
            'create host success. '
            'host name: %(name)s, '
            'host id: %(id)s'),
            {'name': host_name,
             'id': host_id})
        return host_id

    def _add_host(self, hostname, host_name_before_hash):
        """Add a new host."""
        url = "/host"
        data = json.dumps({"TYPE": "21",
                           "NAME": hostname,
                           "OPERATIONSYSTEM": "0",
                           "DESCRIPTION": host_name_before_hash})
        result = self.call(url, data)
        self._assert_rest_result(result, _('Add new host error.'))

        if 'data' in result:
            return result['data']['ID']

    def _is_host_associate_to_hostgroup(self, hostgroup_id, host_id):
        """Check whether the host is associated to the hostgroup."""
        url_subfix = ("/host/associate?TYPE=21&"
                      "ASSOCIATEOBJTYPE=14&ASSOCIATEOBJID=%s" % hostgroup_id)

        url = url_subfix
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Check hostgroup associate error.'))

        if self._get_id_from_result(result, host_id, 'ID'):
            return True

        return False

    def _is_lun_associated_to_lungroup(self, lungroup_id, lun_id):
        """Check whether the lun is associated to the lungroup."""
        url_subfix = ("/lun/associate?TYPE=11&"
                      "ASSOCIATEOBJTYPE=256&ASSOCIATEOBJID=%s" % lungroup_id)

        url = url_subfix
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Check lungroup associate error.'))

        if self._get_id_from_result(result, lun_id, 'ID'):
            return True

        return False

    def _associate_host_to_hostgroup(self, hostgroup_id, host_id):
        url = "/hostgroup/associate"
        data = json.dumps({"TYPE": "14",
                           "ID": hostgroup_id,
                           "ASSOCIATEOBJTYPE": "21",
                           "ASSOCIATEOBJID": host_id})

        result = self.call(url, data)
        self._assert_rest_result(result, _('Associate host to hostgroup '
                                 'error.'))

    def associate_lun_to_lungroup(self, lungroup_id, lun_id):
        """Associate lun to lungroup."""
        url = "/lungroup/associate"
        data = json.dumps({"ID": lungroup_id,
                           "ASSOCIATEOBJTYPE": "11",
                           "ASSOCIATEOBJID": lun_id})
        result = self.call(url, data)
        self._assert_rest_result(result, _('Associate lun to lungroup error.'))

    def remove_lun_from_lungroup(self, lungroup_id, lun_id):
        """Remove lun from lungroup."""
        url = ("/lungroup/associate?ID=%s&ASSOCIATEOBJTYPE=11"
               "&ASSOCIATEOBJID=%s" % (lungroup_id, lun_id))

        result = self.call(url, None, 'DELETE')
        self._assert_rest_result(
            result, _('Delete associated lun from lungroup error.'))

    def _initiator_is_added_to_array(self, ininame):
        """Check whether the initiator is already added on the array."""
        url = "/iscsi_initiator?range=[0-256]"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result,
                                 _('Check initiator added to array error.'))

        if self._get_id_from_result(result, ininame, 'ID'):
            return True
        return False

    def is_initiator_associated_to_host(self, ininame):
        """Check whether the initiator is associated to the host."""
        url = "/iscsi_initiator?range=[0-256]"
        result = self.call(url, None, "GET")
        self._assert_rest_result(
            result, _('Check initiator associated to host error.'))

        if 'data' in result:
            for item in result['data']:
                if item['ID'] == ininame and item['ISFREE'] == "true":
                    return False
        return True

    def _add_initiator_to_array(self, initiator_name):
        """Add a new initiator to storage device."""
        url = "/iscsi_initiator"
        data = json.dumps({"TYPE": "222",
                           "ID": initiator_name,
                           "USECHAP": "false"})
        result = self.call(url, data, "POST")
        self._assert_rest_result(result,
                                 _('Add initiator to array error.'))

    def _add_initiator_to_host(self, initiator_name, host_id):
        url = "/iscsi_initiator/" + initiator_name
        data = json.dumps({"TYPE": "222",
                           "ID": initiator_name,
                           "USECHAP": "false",
                           "PARENTTYPE": "21",
                           "PARENTID": host_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result,
                                 _('Associate initiator to host error.'))

    def _associate_initiator_to_host(self,
                                     xml_file_path,
                                     initiator_name,
                                     host_id):
        """Associate initiator with the host."""
        iscsi_conf = huawei_utils.get_iscsi_conf(xml_file_path)

        chapinfo = self.find_chap_info(iscsi_conf,
                                       initiator_name)
        multipath_type = self._find_alua_info(iscsi_conf,
                                              initiator_name)
        if chapinfo:
            LOG.info(_LI('Use CHAP when adding initiator to host.'))
            self._use_chap(chapinfo, initiator_name, host_id)
        else:
            self._add_initiator_to_host(initiator_name, host_id)

        if multipath_type:
            LOG.info(_LI('Use ALUA when adding initiator to host.'))
            self._use_alua(initiator_name, multipath_type)

    def find_chap_info(self, iscsi_conf, initiator_name):
        """Find CHAP info from xml."""
        chapinfo = None
        for ini in iscsi_conf['Initiator']:
            if ini['Name'] == initiator_name:
                if 'CHAPinfo' in ini:
                    chapinfo = ini['CHAPinfo']
                    break

        return chapinfo

    def _find_alua_info(self, iscsi_conf, initiator_name):
        """Find ALUA info from xml."""
        multipath_type = 0
        for ini in iscsi_conf['Initiator']:
            if ini['Name'] == initiator_name:
                if 'ALUA' in ini:
                    if ini['ALUA'] != '1' and ini['ALUA'] != '0':
                        msg = (_(
                            'Invalid ALUA value. '
                            'ALUA value must be 1 or 0.'))
                        LOG.error(msg)
                        raise exception.InvalidInput(msg)
                    else:
                        multipath_type = ini['ALUA']
                        break
        return multipath_type

    def _use_chap(self, chapinfo, initiator_name, host_id):
        """Use CHAP when adding initiator to host."""
        (chap_username, chap_password) = chapinfo.split(";")

        url = "/iscsi_initiator/" + initiator_name
        data = json.dumps({"TYPE": "222",
                           "USECHAP": "true",
                           "CHAPNAME": chap_username,
                           "CHAPPASSWORD": chap_password,
                           "ID": initiator_name,
                           "PARENTTYPE": "21",
                           "PARENTID": host_id})
        result = self.call(url, data, "PUT")
        msg = _('Use CHAP to associate initiator to host error. '
                'Please check the CHAP username and password.')
        self._assert_rest_result(result, msg)

    def _use_alua(self, initiator_name, multipath_type):
        """Use ALUA when adding initiator to host."""
        url = "/iscsi_initiator"
        data = json.dumps({"ID": initiator_name,
                           "MULTIPATHTYPE": multipath_type})
        result = self.call(url, data, "PUT")

        self._assert_rest_result(
            result, _('Use ALUA to associate initiator to host error.'))

    def remove_chap(self, initiator_name):
        """Remove CHAP when terminate connection."""
        url = "/iscsi_initiator"
        data = json.dumps({"USECHAP": "false",
                           "MULTIPATHTYPE": "0",
                           "ID": initiator_name})
        result = self.call(url, data, "PUT")

        self._assert_rest_result(result, _('Remove CHAP error.'))

    def find_mapping_view(self, name):
        """Find mapping view."""
        url = "/mappingview?range=[0-8191]"
        result = self.call(url, None, "GET")

        msg = _('Find mapping view error.')
        self._assert_rest_result(result, msg)

        return self._get_id_from_result(result, name, 'NAME')

    def _add_mapping_view(self, name):
        url = "/mappingview"
        data = json.dumps({"NAME": name, "TYPE": "245"})
        result = self.call(url, data)
        self._assert_rest_result(result, _('Add mapping view error.'))

        return result['data']['ID']

    def _associate_hostgroup_to_view(self, view_id, hostgroup_id):
        url = "/MAPPINGVIEW/CREATE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "14",
                           "ASSOCIATEOBJID": hostgroup_id,
                           "TYPE": "245",
                           "ID": view_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Associate host to mapping view '
                                 'error.'))

    def _associate_lungroup_to_view(self, view_id, lungroup_id):
        url = "/MAPPINGVIEW/CREATE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "256",
                           "ASSOCIATEOBJID": lungroup_id,
                           "TYPE": "245",
                           "ID": view_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(
            result, _('Associate lungroup to mapping view error.'))

    def delete_lungroup_mapping_view(self, view_id, lungroup_id):
        """Remove lungroup associate from the mapping view."""
        url = "/mappingview/REMOVE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "256",
                           "ASSOCIATEOBJID": lungroup_id,
                           "TYPE": "245",
                           "ID": view_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Delete lungroup from mapping view '
                                 'error.'))

    def delete_hostgoup_mapping_view(self, view_id, hostgroup_id):
        """Remove hostgroup associate from the mapping view."""
        url = "/mappingview/REMOVE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "14",
                           "ASSOCIATEOBJID": hostgroup_id,
                           "TYPE": "245",
                           "ID": view_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(
            result, _('Delete hostgroup from mapping view error.'))

    def delete_portgroup_mapping_view(self, view_id, portgroup_id):
        """Remove portgroup associate from the mapping view."""
        url = "/mappingview/REMOVE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "257",
                           "ASSOCIATEOBJID": portgroup_id,
                           "TYPE": "245",
                           "ID": view_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(
            result, _('Delete portgroup from mapping view error.'))

    def delete_mapping_view(self, view_id):
        """Remove mapping view from the storage."""
        url = "/mappingview/" + view_id
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, _('Delete mapping view error.'))

    def get_lunnum_from_lungroup(self, lungroup_id):
        """Check if there are still other luns associated to the lungroup."""
        url_subfix = ("/lun/count?TYPE=11&ASSOCIATEOBJTYPE=256&"
                      "ASSOCIATEOBJID=%s" % lungroup_id)
        url = url_subfix
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Find lun number error.'))
        lunnum = -1
        if 'data' in result:
            lunnum = result['data']['COUNT']
        return lunnum

    def is_portgroup_associated_to_view(self, view_id, portgroup_id):
        """Check whether the port group is associated to the mapping view."""
        url_subfix = ("/portgroup/associate?ASSOCIATEOBJTYPE=245&"
                      "ASSOCIATEOBJID=%s&range=[0-8191]" % view_id)
        url = url_subfix
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Find portgroup from mapping view '
                                 'error.'))

        if self._get_id_from_result(result, portgroup_id, 'ID'):
            return True
        return False

    def find_lungroup_from_map(self, view_id):
        """Get lungroup from the given map"""
        url_subfix = ("/mappingview/associate/lungroup?TYPE=256&"
                      "ASSOCIATEOBJTYPE=245&ASSOCIATEOBJID=%s" % view_id)
        url = url_subfix
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Find lun group from mapping view '
                                 'error.'))
        lungroup_id = None
        if 'data' in result:
            # One map can have only one lungroup.
            for item in result['data']:
                lungroup_id = item['ID']

        return lungroup_id

    def start_luncopy(self, luncopy_id):
        """Start a LUNcopy."""
        url = "/LUNCOPY/start"
        data = json.dumps({"TYPE": "219", "ID": luncopy_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Start LUNcopy error.'))

    def _get_capacity(self, pool_name, result):
        """Get free capacity and total capacity of the pool."""
        pool_info = self.find_pool_info(pool_name, result)
        pool_capacity = {'total_capacity': 0.0,
                         'free_capacity': 0.0}

        if pool_info:
            total = float(pool_info['TOTALCAPACITY']) / constants.CAPACITY_UNIT
            free = float(pool_info['CAPACITY']) / constants.CAPACITY_UNIT
            pool_capacity['total_capacity'] = total
            pool_capacity['free_capacity'] = free

        return pool_capacity

    def get_luncopy_info(self, luncopy_id):
        """Get LUNcopy information."""
        url = "/LUNCOPY?range=[0-1023]"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get LUNcopy information error.'))

        luncopyinfo = {}
        if 'data' in result:
            for item in result['data']:
                if luncopy_id == item['ID']:
                    luncopyinfo['name'] = item['NAME']
                    luncopyinfo['id'] = item['ID']
                    luncopyinfo['state'] = item['HEALTHSTATUS']
                    luncopyinfo['status'] = item['RUNNINGSTATUS']
                    break
        return luncopyinfo

    def delete_luncopy(self, luncopy_id):
        """Delete a LUNcopy."""
        url = "/LUNCOPY/%s" % luncopy_id
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, _('Delete LUNcopy error.'))

    def get_init_targ_map(self, wwns):
        init_targ_map = {}
        tgt_port_wwns = []
        for wwn in wwns:
            tgtwwpns = self.get_fc_target_wwpns(wwn)
            if not tgtwwpns:
                continue

            init_targ_map[wwn] = tgtwwpns
            for tgtwwpn in tgtwwpns:
                if tgtwwpn not in tgt_port_wwns:
                    tgt_port_wwns.append(tgtwwpn)

        return (tgt_port_wwns, init_targ_map)

    def get_online_free_wwns(self):
        """Get online free WWNs.

        If no new ports connected, return an empty list.
        """
        url = "/fc_initiator?ISFREE=true&range=[0-8191]"
        result = self.call(url, None, "GET")

        msg = _('Get connected free FC wwn error.')
        self._assert_rest_result(result, msg)

        wwns = []
        if 'data' in result:
            for item in result['data']:
                wwns.append(item['ID'])

        return wwns

    def add_fc_port_to_host(self, host_id, wwn):
        """Add a FC port to the host."""
        url = "/fc_initiator/" + wwn
        data = json.dumps({"TYPE": "223",
                           "ID": wwn,
                           "PARENTTYPE": 21,
                           "PARENTID": host_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Add FC port to host error.'))

    def _get_iscsi_port_info(self, ip):
        """Get iscsi port info in order to build the iscsi target iqn."""
        url = "/eth_port"
        result = self.call(url, None, "GET")

        msg = _('Get iSCSI port information error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        iscsi_port_info = None
        for item in result['data']:
            if ip == item['IPV4ADDR']:
                iscsi_port_info = item['LOCATION']
                break

        return iscsi_port_info

    def _get_tgt_iqn(self, iscsi_ip):
        """Get target iSCSI iqn."""
        ip_info = self._get_iscsi_port_info(iscsi_ip)
        iqn_prefix = self._get_iscsi_tgt_port()
        if not ip_info:
            err_msg = (_(
                'Get iSCSI port info error, please check the target IP '
                'configured in huawei conf file.'))
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        LOG.debug('Request ip info is: %s.', ip_info)
        split_list = ip_info.split(".")
        newstr = split_list[1] + split_list[2]
        LOG.info(_LI('New str info is: %s.'), newstr)

        if ip_info:
            if newstr[0] == 'A':
                ctr = "0"
            elif newstr[0] == 'B':
                ctr = "1"
            interface = '0' + newstr[1]
            port = '0' + newstr[3]
            iqn_suffix = ctr + '02' + interface + port
            for i in range(0, len(iqn_suffix)):
                if iqn_suffix[i] != '0':
                    iqn_suffix = iqn_suffix[i:]
                    break
            iqn = iqn_prefix + ':' + iqn_suffix + ':' + iscsi_ip
            LOG.info(_LI('_get_tgt_iqn: iSCSI target iqn is: %s.'), iqn)
            return iqn

    def get_fc_target_wwpns(self, wwn):
        url = ("/host_link?INITIATOR_TYPE=223&INITIATOR_PORT_WWN=" + wwn)
        result = self.call(url, None, "GET")

        msg = _('Get FC target wwpn error.')
        self._assert_rest_result(result, msg)

        fc_wwpns = []
        if "data" in result:
            for item in result['data']:
                if wwn == item['INITIATOR_PORT_WWN']:
                    fc_wwpns.append(item['TARGET_PORT_WWN'])

        return fc_wwpns

    def update_volume_stats(self):
        root = huawei_utils.parse_xml_file(self.xml_file_path)
        pool_names = root.findtext('LUN/StoragePool')
        if not pool_names:
            msg = _(
                'Invalid resource pool name. '
                'Please check the config file.')
            LOG.error(msg)
            raise exception.InvalidInput(msg)
        data = {}
        data['pools'] = []
        result = self.find_all_pools()
        for pool_name in pool_names.split(";"):
            pool_name = pool_name.strip(' \t\n\r')
            capacity = self._get_capacity(pool_name, result)
            pool = {}
            pool.update(dict(
                location_info=self.device_id,
                pool_name=pool_name,
                total_capacity_gb=capacity['total_capacity'],
                free_capacity_gb=capacity['free_capacity'],
                reserved_percentage=self.configuration.safe_get(
                    'reserved_percentage'),
                QoS_support=True,
                max_over_subscription_ratio=self.configuration.safe_get(
                    'max_over_subscription_ratio'),
                thin_provisioning_support=True,
                thick_provisioning_support=True,
                smarttier=True,
                smartcache=True,
                smartpartition=True,
                hypermetro=True,
            ))
            data['pools'].append(pool)
        return data

    def _find_qos_policy_info(self, policy_name):
        url = "/ioclass"
        result = self.call(url, None, "GET")

        msg = _('Get QoS policy error.')
        self._assert_rest_result(result, msg)

        qos_info = {}
        if 'data' in result:
            for item in result['data']:
                if policy_name == item['NAME']:
                    qos_info['ID'] = item['ID']
                    lun_list = json.loads(item['LUNLIST'])
                    qos_info['LUNLIST'] = lun_list
                    qos_info['RUNNINGSTATUS'] = item['RUNNINGSTATUS']
                    break

        return qos_info

    def _update_qos_policy_lunlist(self, lun_list, policy_id):
        url = "/ioclass/" + policy_id
        data = json.dumps({"TYPE": "230",
                           "ID": policy_id,
                           "LUNLIST": lun_list})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Update QoS policy error.'))

    def _get_tgt_ip_from_portgroup(self, portgroup_id):
        target_ips = []
        url = ("/eth_port/associate?TYPE=213&ASSOCIATEOBJTYPE=257"
               "&ASSOCIATEOBJID=%s" % portgroup_id)
        result = self.call(url, None, "GET")

        msg = _('Get target IP error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        if 'data' in result:
            for item in result['data']:
                if (item['IPV4ADDR'] and item['HEALTHSTATUS'] ==
                    constants.STATUS_HEALTH
                   and item['RUNNINGSTATUS'] == constants.STATUS_RUNNING):
                    target_ip = item['IPV4ADDR']
                    LOG.info(_LI('_get_tgt_ip_from_portgroup: Get ip: %s.'),
                             target_ip)
                    target_ips.append(target_ip)

        return target_ips

    def get_iscsi_params(self, xml_file_path, connector):
        """Get target iSCSI params, including iqn, IP."""
        initiator = connector['initiator']
        iscsi_conf = huawei_utils.get_iscsi_conf(xml_file_path)
        target_ips = []
        target_iqns = []
        portgroup = None
        portgroup_id = None
        for ini in iscsi_conf['Initiator']:
            if ini['Name'] == initiator:
                for key in ini:
                    if key == 'TargetPortGroup':
                        portgroup = ini['TargetPortGroup']
                    elif key == 'TargetIP':
                        target_ips.append(ini['TargetIP'])

        if portgroup:
            portgroup_id = self.find_tgt_port_group(portgroup)
            target_ips = self._get_tgt_ip_from_portgroup(portgroup_id)

        # If not specify target IP for some initiators, use default IP.
        if not target_ips:
            if iscsi_conf['DefaultTargetIP']:
                target_ips.append(iscsi_conf['DefaultTargetIP'])

            else:
                msg = (_(
                    'get_iscsi_params: Failed to get target IP '
                    'for initiator %(ini)s, please check config file.')
                    % {'ini': initiator})
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

        # Deal with the remote tgt ip.
        if 'remote_target_ip' in connector:
            target_ips.append(connector['remote_target_ip'])
        LOG.info(_LI('Get the default ip: %s.'), target_ips)
        for ip in target_ips:
            target_iqn = self._get_tgt_iqn_from_rest(ip)
            if not target_iqn:
                target_iqn = self._get_tgt_iqn(ip)
            if target_iqn:
                target_iqns.append(target_iqn)

        return (target_iqns, target_ips, portgroup_id)

    def _get_tgt_iqn_from_rest(self, target_ip):
        url = "/iscsi_tgt_port"
        result = self.call(url, None, "GET")

        target_iqn = None
        if result['error']['code'] != 0:
            LOG.warning(_LW("Can't find target iqn from rest."))
            return target_iqn

        if 'data' in result:
            for item in result['data']:
                if target_ip in item['ID']:
                    target_iqn = item['ID']

        if not target_iqn:
            LOG.warning(_LW("Can't find target iqn from rest."))
            return target_iqn

        split_list = target_iqn.split(",")
        target_iqn_before = split_list[0]

        split_list_new = target_iqn_before.split("+")
        target_iqn = split_list_new[1]

        return target_iqn

    def create_qos_policy(self, qos, lun_id):
        # Get local time.
        localtime = time.strftime('%Y%m%d%H%M%S', time.localtime(time.time()))
        # Package QoS name.
        qos_name = constants.QOS_NAME_PREFIX + lun_id + '_' + localtime

        mergedata = {"TYPE": "230",
                     "NAME": qos_name,
                     "LUNLIST": ["%s" % lun_id],
                     "CLASSTYPE": "1",
                     "SCHEDULEPOLICY": "2",
                     "SCHEDULESTARTTIME": "1410969600",
                     "STARTTIME": "08:00",
                     "DURATION": "86400",
                     "CYCLESET": "[1,2,3,4,5,6,0]",
                     }
        mergedata.update(qos)
        data = json.dumps(mergedata)
        url = "/ioclass/"

        result = self.call(url, data)
        self._assert_rest_result(result, _('Create QoS policy error.'))

        return result['data']['ID']

    def delete_qos_policy(self, qos_id):
        """Delete a QoS policy."""
        url = "/ioclass/" + qos_id
        data = json.dumps({"TYPE": "230",
                           "ID": qos_id})

        result = self.call(url, data, 'DELETE')
        self._assert_rest_result(result, _('Delete QoS policy error.'))

    def activate_deactivate_qos(self, qos_id, enablestatus):
        """Activate or deactivate QoS.

        enablestatus: true (activate)
        enbalestatus: false (deactivate)
        """
        url = "/ioclass/active/" + qos_id
        data = json.dumps({"TYPE": 230,
                           "ID": qos_id,
                           "ENABLESTATUS": enablestatus})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(
            result, _('Activate or deactivate QoS error.'))

    def get_qos_info(self, qos_id):
        """Get QoS information."""
        url = "/ioclass/" + qos_id
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get QoS information error.'))

        return result['data']

    def get_lun_list_in_qos(self, qos_id):
        """Get the lun list in QoS."""
        qos_info = self.get_qos_info(qos_id)
        lun_list = []
        lun_string = qos_info['LUNLIST'][1:-1]

        for lun in lun_string.split(","):
            str = lun[1:-1]
            lun_list.append(str)

        return lun_list

    def remove_lun_from_qos(self, lun_id, lun_list, qos_id):
        """Remove lun from QoS."""
        lun_list = [i for i in lun_list if i != lun_id]
        url = "/ioclass/" + qos_id
        data = json.dumps({"LUNLIST": lun_list,
                           "TYPE": 230,
                           "ID": qos_id})
        result = self.call(url, data, "PUT")

        msg = _('Remove lun from Qos error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

    def change_lun_priority(self, lun_id):
        """Change lun priority to high."""
        url = "/lun/" + lun_id
        data = json.dumps({"TYPE": "11",
                           "ID": lun_id,
                           "IOPRIORITY": "3"})

        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Change lun priority error.'))

    def change_lun_smarttier(self, lunid, smarttier_policy):
        """Change lun smarttier policy."""
        url = "/lun/" + lunid
        data = json.dumps({"TYPE": "11",
                           "ID": lunid,
                           "DATATRANSFERPOLICY": smarttier_policy})

        result = self.call(url, data, "PUT")
        self._assert_rest_result(
            result, _('Change lun smarttier policy error.'))

    def get_qosid_by_lunid(self, lun_id):
        """Get QoS id by lun id."""
        url = "/lun/" + lun_id
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get QoS id by lun id error.'))

        return result['data']['IOCLASSID']

    def get_lungroupids_by_lunid(self, lun_id):
        """Get lungroup ids by lun id."""
        url = ("/lungroup/associate?TYPE=256"
               "&ASSOCIATEOBJTYPE=11&ASSOCIATEOBJID=%s" % lun_id)

        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get lungroup id by lun id error.'))

        lungroup_ids = []
        if 'data' in result:
            for item in result['data']:
                lungroup_ids.append(item['ID'])

        return lungroup_ids

    def get_lun_info(self, lun_id):
        url = "/lun/" + lun_id
        result = self.call(url, None, "GET")

        msg = _('Get volume error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']

    def extend_volume(self, lun_id, new_volume_size):
        url = "/lun/expand"
        data = json.dumps({"TYPE": 11, "ID": lun_id,
                           "CAPACITY": new_volume_size})
        result = self.call(url, data, 'PUT')

        msg = _('Extend volume error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']

    def create_lun_migration(self, src_id, dst_id, speed=2):
        url = "/LUN_MIGRATION"
        data = json.dumps({"TYPE": '253',
                           "PARENTID": src_id,
                           "TARGETLUNID": dst_id,
                           "SPEED": speed,
                           "WORKMODE": 0})

        result = self.call(url, data, "POST")
        msg = _('Create lun migration error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

    def get_lun_migration_task(self):
        url = '/LUN_MIGRATION?range=[0-100]'
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get lun migration task error.'))
        return result

    def delete_lun_migration(self, src_id, dst_id):
        url = '/LUN_MIGRATION/' + src_id
        result = self.call(url, None, "DELETE")
        msg = _('Delete lun migration error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

    def get_partition_id_by_name(self, name):
        url = "/cachepartition"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get partition by name error.'))

        return self._get_id_from_result(result, name, 'NAME')

    def get_partition_info_by_id(self, partition_id):

        url = '/cachepartition/' + partition_id
        result = self.call(url, None, "GET")
        self._assert_rest_result(result,
                                 _('Get partition by partition id error.'))

        return result['data']

    def add_lun_to_partition(self, lun_id, partition_id):
        url = "/lun/associate/cachepartition"
        data = json.dumps({"ID": partition_id,
                           "ASSOCIATEOBJTYPE": 11,
                           "ASSOCIATEOBJID": lun_id, })
        result = self.call(url, data, "POST")
        self._assert_rest_result(result, _('Add lun to partition error.'))

    def remove_lun_from_partition(self, lun_id, partition_id):
        url = ('/lun/associate/cachepartition?ID=' + partition_id
               + '&ASSOCIATEOBJTYPE=11&ASSOCIATEOBJID=' + lun_id)

        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, _('Remove lun from partition error.'))

    def get_cache_id_by_name(self, name):
        url = "/SMARTCACHEPARTITION"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get cache by name error.'))

        return self._get_id_from_result(result, name, 'NAME')

    def get_cache_info_by_id(self, cacheid):
        url = "/SMARTCACHEPARTITION/" + cacheid
        data = json.dumps({"TYPE": "273",
                           "ID": cacheid})

        result = self.call(url, data, "GET")
        self._assert_rest_result(
            result, _('Get smartcache by cache id error.'))

        return result['data']

    def remove_lun_from_cache(self, lun_id, cache_id):
        url = "/SMARTCACHEPARTITION/REMOVE_ASSOCIATE"
        data = json.dumps({"ID": cache_id,
                           "ASSOCIATEOBJTYPE": 11,
                           "ASSOCIATEOBJID": lun_id,
                           "TYPE": 273})

        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Remove lun from cache error.'))

    def get_qos(self):
        url = "/ioclass"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get QoS information error.'))
        return result

    def find_available_qos(self, qos):
        """"Find available QoS on the array."""
        qos_id = None
        lun_list = []
        result = self.get_qos()

        if 'data' in result:
            for item in result['data']:
                qos_flag = 0
                for key in qos:
                    if key not in item:
                        break
                    elif qos[key] != item[key]:
                        break
                    qos_flag = qos_flag + 1
                lun_num = len(item['LUNLIST'].split(","))
                # We use this QoS only if the LUNs in it is less than 64,
                # else we cannot add LUN to this QoS any more.
                if (qos_flag == len(qos)
                        and lun_num < constants.MAX_LUN_NUM_IN_QOS):
                    qos_id = item['ID']
                    lun_list = item['LUNLIST']
                    break

        return (qos_id, lun_list)

    def add_lun_to_qos(self, qos_id, lun_id, lun_list):
        """Add lun to QoS."""
        url = "/ioclass/" + qos_id
        new_lun_list = []
        lun_list_string = lun_list[1:-1]
        for lun_string in lun_list_string.split(","):
            tmp_lun_id = lun_string[1:-1]
            if '' != tmp_lun_id and tmp_lun_id != lun_id:
                new_lun_list.append(tmp_lun_id)

        new_lun_list.append(lun_id)

        data = json.dumps({"LUNLIST": new_lun_list,
                           "TYPE": 230,
                           "ID": qos_id})
        result = self.call(url, data, "PUT")
        msg = _('Associate lun to Qos error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

    def add_lun_to_cache(self, lun_id, cache_id):
        url = "/SMARTCACHEPARTITION/CREATE_ASSOCIATE"
        data = json.dumps({"ID": cache_id,
                           "ASSOCIATEOBJTYPE": 11,
                           "ASSOCIATEOBJID": lun_id,
                           "TYPE": 273})
        result = self.call(url, data, "PUT")

        self._assert_rest_result(result, _('Add lun to cache error.'))

    def find_array_version(self):
        url = "/system/"
        result = self.call(url, None)
        self._assert_rest_result(result, _('Find array version error.'))
        return result['data']['PRODUCTVERSION']

    def remove_host(self, host_id):
        url = "/host/%s" % host_id
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, _('Remove host from array error.'))

    def delete_hostgroup(self, hostgroup_id):
        url = "/hostgroup/%s" % hostgroup_id
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, _('Delete hostgroup error.'))

    def remove_host_from_hostgroup(self, hostgroup_id, host_id):
        url_subfix001 = "/host/associate?TYPE=14&ID=%s" % hostgroup_id
        url_subfix002 = "&ASSOCIATEOBJTYPE=21&ASSOCIATEOBJID=%s" % host_id
        url = url_subfix001 + url_subfix002
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result,
                                 _('Remove host from hostgroup error.'))

    def remove_iscsi_from_host(self, initiator):
        url = "/iscsi_initiator/remove_iscsi_from_host"
        data = json.dumps({"TYPE": '222',
                           "ID": initiator})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Remove iscsi from host error.'))

    def get_host_online_fc_initiators(self, host_id):
        url = "/fc_initiator?PARENTTYPE=21&PARENTID=%s" % host_id
        result = self.call(url, None, "GET")

        initiators = []
        if 'data' in result:
            for item in result['data']:
                if (('PARENTID' in item) and (item['PARENTID'] == host_id)
                   and (item['RUNNINGSTATUS'] == constants.FC_INIT_ONLINE)):
                    initiators.append(item['ID'])

        return initiators

    def get_host_fc_initiators(self, host_id):
        url = "/fc_initiator?PARENTTYPE=21&PARENTID=%s" % host_id
        result = self.call(url, None, "GET")

        initiators = []
        if 'data' in result:
            for item in result['data']:
                if (('PARENTID' in item) and (item['PARENTID'] == host_id)):
                    initiators.append(item['ID'])

        return initiators

    def get_host_iscsi_initiators(self, host_id):
        url = "/iscsi_initiator?PARENTTYPE=21&PARENTID=%s" % host_id
        result = self.call(url, None, "GET")

        initiators = []
        if 'data' in result:
            for item in result['data']:
                if (('PARENTID' in item) and (item['PARENTID'] == host_id)):
                    initiators.append(item['ID'])

        return initiators

    def rename_lun(self, lun_id, new_name):
        url = "/lun/" + lun_id
        data = json.dumps({"NAME": new_name})
        result = self.call(url, data, "PUT")
        msg = _('Rename lun on array error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

    def is_fc_initiator_associated_to_host(self, ininame):
        """Check whether the initiator is associated to the host."""
        url = '/fc_initiator?range=[0-256]'
        result = self.call(url, None, "GET")
        self._assert_rest_result(result,
                                 'Check initiator associated to host error.')

        if "data" in result:
            for item in result['data']:
                if item['ID'] == ininame and item['ISFREE'] != "true":
                    return True
        return False

    def remove_fc_from_host(self, initiator):
        url = '/fc_initiator/remove_fc_from_host'
        data = json.dumps({"TYPE": '223',
                           "ID": initiator})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, _('Remove fc from host error.'))

    def check_fc_initiators_exist_in_host(self, host_id):
        url = "/fc_initiator?range=[0-100]&PARENTID=%s" % host_id
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, _('Get host initiators info failed.'))
        if 'data' in result:
            return True

        return False

    def _fc_initiator_is_added_to_array(self, ininame):
        """Check whether the fc initiator is already added on the array."""
        url = "/fc_initiator/" + ininame
        result = self.call(url, None, "GET")
        error_code = result['error']['code']
        if error_code != 0:
            return False

        return True

    def _add_fc_initiator_to_array(self, ininame):
        """Add a fc initiator to storage device."""
        url = '/fc_initiator/'
        data = json.dumps({"TYPE": '223',
                           "ID": ininame})
        result = self.call(url, data)
        self._assert_rest_result(result, _('Add fc initiator to array error.'))

    def ensure_fc_initiator_added(self, initiator_name, host_id):
        added = self._fc_initiator_is_added_to_array(initiator_name)
        if not added:
            self._add_fc_initiator_to_array(initiator_name)
        # Just add, no need to check whether have been added.
        self.add_fc_port_to_host(host_id, initiator_name)

    def get_fc_ports_on_array(self):
        url = '/fc_port'
        result = self.call(url, None, "GET")
        msg = _('Get FC ports from array error.')
        self._assert_rest_result(result, msg)

        return result['data']

    def get_fc_ports_from_contr(self, contr):
        port_list_from_contr = []
        location = []
        data = self.get_fc_ports_on_array()
        for item in data:
            location = item['PARENTID'].split('.')
            if (location[0][1] == contr) and (item['RUNNINGSTATUS'] ==
                                              constants.FC_PORT_CONNECTED):
                port_list_from_contr.append(item['WWN'])
        return port_list_from_contr

    def get_hyper_domain_id(self, domain_name):
        url = "/HyperMetroDomain?range=[0-100]"
        result = self.call(url, None, "GET")
        domain_id = None
        if "data" in result:
            for item in result['data']:
                if domain_name == item['NAME']:
                    domain_id = item['ID']
                    break

        msg = _('get_hyper_domain_id error.')
        self._assert_rest_result(result, msg)
        return domain_id

    def create_hypermetro(self, hcp_param):
        url = "/HyperMetroPair"
        data = json.dumps(hcp_param)
        result = self.call(url, data, "POST")

        msg = _('create_hypermetro_pair error.')
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)
        return result['data']

    def delete_hypermetro(self, metro_id):
        url = "/HyperMetroPair/" + metro_id
        result = self.call(url, None, "DELETE")

        msg = _('delete_hypermetro error.')
        self._assert_rest_result(result, msg)

    def sync_hypermetro(self, metro_id):
        url = "/HyperMetroPair/synchronize_hcpair"

        data = json.dumps({"ID": metro_id,
                           "TYPE": "15361"})
        result = self.call(url, data, "PUT")

        msg = _('sync_hypermetro error.')
        self._assert_rest_result(result, msg)

    def stop_hypermetro(self, metro_id):
        url = '/HyperMetroPair/disable_hcpair'

        data = json.dumps({"ID": metro_id,
                           "TYPE": "15361"})
        result = self.call(url, data, "PUT")

        msg = _('stop_hypermetro error.')
        self._assert_rest_result(result, msg)

    def get_hypermetro_by_id(self, metro_id):
        url = "/HyperMetroPair/" + metro_id
        result = self.call(url, None, "GET")

        msg = _('get_hypermetro_by_id error.')
        self._assert_rest_result(result, msg)
        return result

    def check_hypermetro_exist(self, metro_id):
        url = "/HyperMetroPair/" + metro_id
        result = self.call(url, None, "GET")
        error_code = result['error']['code']

        if (error_code == constants.ERROR_CONNECT_TO_SERVER
                or error_code == constants.ERROR_UNAUTHORIZED_TO_SERVER):
            LOG.error(_LE("Can not open the recent url, login again."))
            self.login()
            result = self.call(url, None, "GET")

        error_code = result['error']['code']
        if (error_code == constants.ERROR_CONNECT_TO_SERVER
                or error_code == constants.ERROR_UNAUTHORIZED_TO_SERVER):
            msg = _("check_hypermetro_exist error.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if error_code != 0:
            return False

        return True

    def change_hostlun_id(self, map_info, hostlun_id):
        url = "/mappingview"
        view_id = six.text_type(map_info['view_id'])
        lun_id = six.text_type(map_info['lun_id'])
        hostlun_id = six.text_type(hostlun_id)
        data = json.dumps({"TYPE": 245,
                           "ID": view_id,
                           "ASSOCIATEOBJTYPE": 11,
                           "ASSOCIATEOBJID": lun_id,
                           "ASSOCIATEMETADATA": [{"LUNID": lun_id,
                                                  "hostLUNId": hostlun_id}]
                           })

        result = self.call(url, data, "PUT")

        msg = 'change hostlun id error.'
        self._assert_rest_result(result, msg)

    def find_view_by_id(self, view_id):
        url = "/MAPPINGVIEW/" + view_id
        result = self.call(url, None, "GET")

        msg = _('Change hostlun id error.')
        self._assert_rest_result(result, msg)
        if 'data' in result:
            return result["data"]["AVAILABLEHOSTLUNIDLIST"]
