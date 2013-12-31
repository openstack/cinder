# Copyright (c) 2013 Huawei Technologies Co., Ltd.
# Copyright (c) 2013 OpenStack Foundation
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
"""Common class for Huawei HVS storage drivers."""

import base64
import cookielib
import json
import time
import urllib2
import uuid

from xml.etree import ElementTree as ET

from cinder import context
from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder import units
from cinder import utils
from cinder.volume.drivers.huawei import huawei_utils
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)

QOS_KEY = ["Qos-high", "Qos-normal", "Qos-low"]
TIER_KEY = ["Tier-high", "Tier-normal", "Tier-low"]


class HVSCommon():
    """Common class for Huawei OceanStor HVS storage system."""

    def __init__(self, configuration):
        self.configuration = configuration
        self.cookie = cookielib.CookieJar()
        self.url = None
        self.xml_conf = self.configuration.cinder_huawei_conf_file

    def call(self, url=False, data=None, method=None):
        """Send requests to HVS server.

        Send HTTPS call, get response in JSON.
        Convert response into Python Object and return it.
        """

        LOG.debug(_('HVS Request URL: %(url)s') % {'url': url})
        LOG.debug(_('HVS Request Data: %(data)s') % {'data': data})

        headers = {"Connection": "keep-alive",
                   "Content-Type": "application/json"}
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cookie))
        urllib2.install_opener(opener)

        try:
            urllib2.socket.setdefaulttimeout(720)
            req = urllib2.Request(url, data, headers)
            if method:
                req.get_method = lambda: method
            res = urllib2.urlopen(req).read().decode("utf-8")
            LOG.debug(_('HVS Response Data: %(res)s') % {'res': res})
        except Exception as err:
            err_msg = _('Bad response from server: %s') % err
            LOG.error(err_msg)
            raise err

        try:
            res_json = json.loads(res)
        except Exception as err:
            LOG.error(_('JSON transfer error'))
            raise err

        return res_json

    def login(self):
        """Log in HVS array.

        If login failed, the driver will sleep 30's to avoid frequent
        connection to the server.
        """

        login_info = self._get_login_info()
        url = login_info['HVSURL'] + "xx/sessions"
        data = json.dumps({"username": login_info['UserName'],
                           "password": login_info['UserPassword'],
                           "scope": "0"})
        result = self.call(url, data)
        if (result['error']['code'] != 0) or ("data" not in result):
            time.sleep(30)
            msg = _("Login error, reason is %s") % result
            LOG.error(msg)
            raise exception.CinderException(msg)

        deviceid = result['data']['deviceid']
        self.url = login_info['HVSURL'] + deviceid
        return deviceid

    def _init_tier_parameters(self, parameters, lunparam):
        """Init the LUN parameters through the volume type "performance"."""
        if "tier" in parameters:
            smart_tier = parameters['tier']
            if smart_tier == 'Tier_high':
                lunparam['INITIALDISTRIBUTEPOLICY'] = "1"
            elif smart_tier == 'Tier_normal':
                lunparam['INITIALDISTRIBUTEPOLICY'] = "2"
            elif smart_tier == 'Tier_low':
                lunparam['INITIALDISTRIBUTEPOLICY'] = "3"
            else:
                lunparam['INITIALDISTRIBUTEPOLICY'] = "2"

    def _init_lun_parameters(self, name, parameters):
        """Init basic LUN parameters."""
        lunparam = {"TYPE": "11",
                    "NAME": name,
                    "PARENTTYPE": "216",
                    "PARENTID": parameters['pool_id'],
                    "DESCRIPTION": "",
                    "ALLOCTYPE": parameters['LUNType'],
                    "CAPACITY": parameters['volume_size'],
                    "WRITEPOLICY": parameters['WriteType'],
                    "MIRRORPOLICY": parameters['MirrorSwitch'],
                    "PREFETCHPOLICY": parameters['PrefetchType'],
                    "PREFETCHVALUE": parameters['PrefetchValue'],
                    "DATATRANSFERPOLICY": "1",
                    "INITIALDISTRIBUTEPOLICY": "0"}

        return lunparam

    def _init_qos_parameters(self, parameters, lun_param):
        """Init the LUN parameters through the volume type "Qos-xxx"."""
        policy_id = None
        policy_info = None
        if "qos" in parameters:
            policy_info = self._find_qos_policy_info(parameters['qos'])
            if policy_info:
                policy_id = policy_info['ID']

                lun_param['IOClASSID'] = policy_info['ID']
                qos_level = parameters['qos_level']
                if qos_level == 'Qos-high':
                    lun_param['IOPRIORITY'] = "3"
                elif qos_level == 'Qos-normal':
                    lun_param['IOPRIORITY'] = "2"
                elif qos_level == 'Qos-low':
                    lun_param['IOPRIORITY'] = "1"
                else:
                    lun_param['IOPRIORITY'] = "2"

        return (policy_info, policy_id)

    def _assert_rest_result(self, result, err_str):
        error_code = result['error']['code']
        if error_code != 0:
            msg = _('%(err)s\nresult: %(res)s') % {'err': err_str,
                                                   'res': result}
            LOG.error(msg)
            raise exception.CinderException(msg)

    def _assert_data_in_result(self, result, msg):
        if "data" not in result:
            err_msg = _('%s "data" was not in result.') % msg
            LOG.error(err_msg)
            raise exception.CinderException(err_msg)

    def _create_volume(self, lun_param):
        url = self.url + "/lun"
        data = json.dumps(lun_param)
        result = self.call(url, data)

        msg = 'Create volume error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']['ID']

    def create_volume(self, volume):
        volume_name = self._encode_name(volume['id'])
        config_params = self._parse_volume_type(volume)

        # Prepare lun parameters, including qos parameter and tier parameter.
        lun_param = self._init_lun_parameters(volume_name, config_params)
        self._init_tier_parameters(config_params, lun_param)
        policy_info, policy_id = self._init_qos_parameters(config_params,
                                                           lun_param)

        # Create LUN in array
        lunid = self._create_volume(lun_param)

        # Enable qos, need to add lun into qos policy
        if "qos" in config_params:
            lun_list = policy_info['LUNLIST']
            lun_list.append(lunid)
            if policy_id:
                self._update_qos_policy_lunlist(lun_list, policy_id)
            else:
                LOG.warn(_("Can't find the Qos policy in array"))

        # Create lun group and add LUN into to lun group
        lungroup_id = self._create_lungroup(volume_name)
        self._associate_lun_to_lungroup(lungroup_id, lunid)

        return lunid

    def _get_volume_size(self, poolinfo, volume):
        """Calculate the volume size.

        We should divide the given volume size by 512 for the HVS system
        calculates volume size with sectors, which is 512 bytes.
        """

        volume_size = units.GiB / 512  # 1G
        if int(volume['size']) != 0:
            volume_size = int(volume['size']) * units.GiB / 512

        return volume_size

    def delete_volume(self, volume):
        """Delete a volume.

        Three steps: first, remove associate from lun group.
        Second, remove associate from qos policy. Third, remove the lun.
        """

        name = self._encode_name(volume['id'])
        lun_id = self._get_volume_by_name(name)
        lungroup_id = self._find_lungroup(name)

        if lun_id and lungroup_id:
            self._delete_lun_from_qos_policy(volume, lun_id)
            self._delete_associated_lun_from_lungroup(lungroup_id, lun_id)
            self._delete_lungroup(lungroup_id)
            self._delete_lun(lun_id)
        else:
            LOG.warn(_("Can't find lun or lun group in array"))

    def _delete_lun_from_qos_policy(self, volume, lun_id):
        """Remove lun from qos policy."""
        parameters = self._parse_volume_type(volume)

        if "qos" in parameters:
            qos = parameters['qos']
            policy_info = self._find_qos_policy_info(qos)
            if policy_info:
                lun_list = policy_info['LUNLIST']
                for item in lun_list:
                    if lun_id == item:
                        lun_list.remove(item)
                self._update_qos_policy_lunlist(lun_list, policy_info['ID'])

    def _delete_lun(self, lun_id):
        url = self.url + "/lun/" + lun_id
        data = json.dumps({"TYPE": "11",
                           "ID": lun_id})
        result = self.call(url, data, "DELETE")
        self._assert_rest_result(result, 'delete lun error')

    def _encode_name(self, name):
        uuid_str = name.replace("-", "")
        vol_uuid = uuid.UUID('urn:uuid:%s' % uuid_str)
        vol_encoded = base64.urlsafe_b64encode(vol_uuid.bytes)
        newuuid = vol_encoded.replace("=", "")
        return newuuid

    def _find_pool_info(self):
        root = huawei_utils.parse_xml_file(self.xml_conf)
        pool_name = root.findtext('LUN/StoragePool')
        if not pool_name:
            err_msg = _("Invalid resource pool: %s") % pool_name
            LOG.error(err_msg)
            raise exception.InvalidInput(err_msg)

        url = self.url + "/storagepool"
        result = self.call(url, None)
        self._assert_rest_result(result, 'Query resource pool error')

        poolinfo = {}
        if "data" in result:
            for item in result['data']:
                if pool_name.strip() == item['NAME']:
                    poolinfo['ID'] = item['ID']
                    poolinfo['CAPACITY'] = item['USERFREECAPACITY']
                    poolinfo['TOTALCAPACITY'] = item['USERTOTALCAPACITY']
                    break

        if not poolinfo:
            msg = (_('Get pool info error, pool name is:%s') % pool_name)
            LOG.error(msg)
            raise exception.CinderException(msg)

        return poolinfo

    def _get_volume_by_name(self, name):
        url = self.url + "/lun"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, 'Get volume by name error!')

        volume_id = None
        if "data" in result:
            for item in result['data']:
                if name == item['NAME']:
                    volume_id = item['ID']
                    break
        return volume_id

    def _active_snapshot(self, snapshot_id):
        activeurl = self.url + "/snapshot/activate"
        data = json.dumps({"SNAPSHOTLIST": [snapshot_id]})
        result = self.call(activeurl, data)
        self._assert_rest_result(result, 'Active snapshot error.')

    def _create_snapshot(self, snapshot):
        snapshot_name = self._encode_name(snapshot['id'])
        volume_name = self._encode_name(snapshot['volume_id'])

        LOG.debug(_('create_snapshot:snapshot name:%(snapshot)s, '
                    'volume name:%(volume)s.')
                  % {'snapshot': snapshot_name,
                     'volume': volume_name})

        lun_id = self._get_volume_by_name(volume_name)
        url = self.url + "/snapshot"
        data = json.dumps({"TYPE": "27",
                           "NAME": snapshot_name,
                           "PARENTTYPE": "11",
                           "PARENTID": lun_id})
        result = self.call(url, data)

        msg = 'Create snapshot error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']['ID']

    def create_snapshot(self, snapshot):
        snapshot_id = self._create_snapshot(snapshot)
        self._active_snapshot(snapshot_id)

    def _stop_snapshot(self, snapshot):
        snapshot_name = self._encode_name(snapshot['id'])
        volume_name = self._encode_name(snapshot['volume_id'])

        LOG.debug(_('_stop_snapshot:snapshot name:%(snapshot)s, '
                    'volume name:%(volume)s.')
                  % {'snapshot': snapshot_name,
                     'volume': volume_name})

        snapshotid = self._get_snapshotid_by_name(snapshot_name)
        stopdata = json.dumps({"ID": snapshotid})
        url = self.url + "/snapshot/stop"
        result = self.call(url, stopdata, "PUT")
        self._assert_rest_result(result, 'Stop snapshot error.')

        return snapshotid

    def _delete_snapshot(self, snapshotid):
        url = self.url + "/snapshot/%s" % snapshotid
        data = json.dumps({"TYPE": "27", "ID": snapshotid})
        result = self.call(url, data, "DELETE")
        self._assert_rest_result(result, 'Delete snapshot error.')

    def delete_snapshot(self, snapshot):
        snapshotid = self._stop_snapshot(snapshot)
        self._delete_snapshot(snapshotid)

    def _get_snapshotid_by_name(self, name):
        url = self.url + "/snapshot"
        data = json.dumps({"TYPE": "27"})
        result = self.call(url, data, "GET")
        self._assert_rest_result(result, 'Get snapshot id error.')

        snapshot_id = None
        if "data" in result:
            for item in result['data']:
                if name == item['NAME']:
                    snapshot_id = item['ID']
                    break
        return snapshot_id

    def _copy_volume(self, volume, copy_name, src_lun, tgt_lun):
        luncopy_id = self._create_luncopy(copy_name,
                                          src_lun, tgt_lun)
        try:
            self._start_luncopy(luncopy_id)
            self._wait_for_luncopy(luncopy_id)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._delete_luncopy(luncopy_id)
                self.delete_volume(volume)

        self._delete_luncopy(luncopy_id)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        We use LUNcopy to copy a new volume from snapshot.
        The time needed increases as volume size does.
        """

        snapshot_name = self._encode_name(snapshot['id'])
        src_lun_id = self._get_snapshotid_by_name(snapshot_name)
        tgt_lun_id = self.create_volume(volume)
        luncopy_name = self._encode_name(volume['id'])

        self._copy_volume(volume, luncopy_name, src_lun_id, tgt_lun_id)

    def create_cloned_volume(self, volume, src_vref):
        """Clone a new volume from an existing volume."""
        volume_name = self._encode_name(src_vref['id'])
        src_lun_id = self._get_volume_by_name(volume_name)
        tgt_lun_id = self.create_volume(volume)
        luncopy_name = self._encode_name(volume['id'])

        self._copy_volume(volume, luncopy_name, src_lun_id, tgt_lun_id)

    def _create_luncopy(self, luncopyname, srclunid, tgtlunid):
        """Create a luncopy."""
        url = self.url + "/luncopy"
        data = json.dumps({"TYPE": "219",
                           "NAME": luncopyname,
                           "DESCRIPTION": luncopyname,
                           "COPYSPEED": "2",
                           "LUNCOPYTYPE": "1",
                           "SOURCELUN": ("INVALID;%s;INVALID;INVALID;INVALID"
                                         % srclunid),
                           "TARGETLUN": ("INVALID;%s;INVALID;INVALID;INVALID"
                                         % tgtlunid)})
        result = self.call(url, data)

        msg = 'Create lun copy error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']['ID']

    def _add_host_into_hostgroup(self, host_name, host_ip):
        """Associate host to hostgroup.

        If host group doesn't exist, create one.

        """

        hostgroup_id = self._find_hostgroup(host_name)
        if hostgroup_id is None:
            hostgroup_id = self._create_hostgroup(host_name)

        hostid = self._find_host(host_name)
        if hostid is None:
            os_type = huawei_utils.get_conf_host_os_type(host_ip,
                                                         self.xml_conf)
            hostid = self._add_host(host_name, os_type)
            self._associate_host_to_hostgroup(hostgroup_id, hostid)

        return hostid, hostgroup_id

    def _mapping_hostgroup_and_lungroup(self, volume_name,
                                        hostgroup_id, host_id):
        """Add hostgroup and lungroup to view."""
        lungroup_id = self._find_lungroup(volume_name)
        lun_id = self._get_volume_by_name(volume_name)
        view_id = self._find_mapping_view(volume_name)

        LOG.debug(_('_mapping_hostgroup_and_lungroup: lun_group: %(lun_group)s'
                    'view_id: %(view_id)s')
                  % {'lun_group': str(lungroup_id),
                     'view_id': str(view_id)})

        try:
            if view_id is None:
                view_id = self._add_mapping_view(volume_name, host_id)
                self._associate_hostgroup_to_view(view_id, hostgroup_id)
                self._associate_lungroup_to_view(view_id, lungroup_id)
            else:
                if not self._hostgroup_associated(view_id, hostgroup_id):
                    self._associate_hostgroup_to_view(view_id, hostgroup_id)
                if not self._lungroup_associated(view_id, lungroup_id):
                    self._associate_lungroup_to_view(view_id, lungroup_id)

        except Exception:
            with excutils.save_and_reraise_exception():
                self._delete_hostgoup_mapping_view(view_id, hostgroup_id)
                self._delete_lungroup_mapping_view(view_id, lungroup_id)
                self._delete_mapping_view(view_id)

        return lun_id

    def _ensure_initiator_added(self, initiator_name, hostid):
        added = self._initiator_is_added_to_array(initiator_name)
        if not added:
            self._add_initiator_to_array(initiator_name)
        else:
            if self._is_initiator_associated_to_host(initiator_name) is False:
                self._associate_initiator_to_host(initiator_name, hostid)

    def initialize_connection_iscsi(self, volume, connector):
        """Map a volume to a host and return target iSCSI information."""
        initiator_name = connector['initiator']
        volume_name = self._encode_name(volume['id'])

        LOG.debug(_('initiator name:%(initiator_name)s, '
                    'volume name:%(volume)s.')
                  % {'initiator_name': initiator_name,
                     'volume': volume_name})

        (iscsi_iqn, target_ip) = self._get_iscsi_params(connector)

        #create host_group if not exist
        hostid, hostgroup_id = self._add_host_into_hostgroup(connector['host'],
                                                             connector['ip'])
        self._ensure_initiator_added(initiator_name, hostid)

        # Mapping lungroup and hostgroup to view
        lun_id = self._mapping_hostgroup_and_lungroup(volume_name,
                                                      hostgroup_id, hostid)
        hostlunid = self._find_host_lun_id(hostid, lun_id)
        LOG.debug(_("host lun id is %s") % hostlunid)

        # Return iSCSI properties.
        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = ('%s:%s' % (target_ip, '3260'))
        properties['target_iqn'] = iscsi_iqn
        properties['target_lun'] = int(hostlunid)
        properties['volume_id'] = volume['id']

        return {'driver_volume_type': 'iscsi', 'data': properties}

    def initialize_connection_fc(self, volume, connector):
        wwns = connector['wwpns']
        volume_name = self._encode_name(volume['id'])

        LOG.debug(_('initiator name:%(initiator_name)s, '
                    'volume name:%(volume)s.')
                  % {'initiator_name': wwns,
                     'volume': volume_name})

        # Create host group if not exist
        hostid, hostgroup_id = self._add_host_into_hostgroup(connector['host'],
                                                             connector['ip'])

        free_wwns = self._get_connected_free_wwns()
        LOG.debug(_("the free wwns %s") % free_wwns)
        for wwn in wwns:
            if wwn in free_wwns:
                self._add_fc_port_to_host(hostid, wwn)

        lun_id = self._mapping_hostgroup_and_lungroup(volume_name,
                                                      hostgroup_id, hostid)
        host_lun_id = self._find_host_lun_id(hostid, lun_id)

        tgt_port_wwns = []
        for wwn in wwns:
            tgtwwpns = self._get_fc_target_wwpns(wwn)
            if tgtwwpns:
                tgt_port_wwns.append(tgtwwpns)

        # Return FC properties.
        properties = {}
        properties['target_discovered'] = False
        properties['target_wwn'] = tgt_port_wwns
        properties['target_lun'] = int(host_lun_id)
        properties['volume_id'] = volume['id']
        LOG.debug(_("the fc server properties is:%s") % properties)

        return {'driver_volume_type': 'fibre_channel',
                'data': properties}

    def _get_iscsi_tgt_port(self):
        url = self.url + "/iscsidevicename"
        result = self.call(url, None)

        msg = 'Get iSCSI target port error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data'][0]['CMO_ISCSI_DEVICE_NAME']

    def _find_hostgroup(self, groupname):
        """Get the given hostgroup id."""
        url = self.url + "/hostgroup"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, 'Get host group information error.')

        host_group_id = None
        if "data" in result:
            for item in result['data']:
                if groupname == item['NAME']:
                    host_group_id = item['ID']
                    break
        return host_group_id

    def _find_lungroup(self, lungroupname):
        """Get the given hostgroup id."""
        url = self.url + "/lungroup"
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, 'Get lun group information error.')

        lun_group_id = None
        if 'data' in result:
            for item in result['data']:
                if lungroupname == item['NAME']:
                    lun_group_id = item['ID']
                    break
        return lun_group_id

    def _create_hostgroup(self, hostgroupname):
        url = self.url + "/hostgroup"
        data = json.dumps({"TYPE": "14", "NAME": hostgroupname})
        result = self.call(url, data)

        msg = 'Create host group error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']['ID']

    def _create_lungroup(self, lungroupname):
        url = self.url + "/lungroup"
        data = json.dumps({"DESCRIPTION": lungroupname,
                           "NAME": lungroupname})
        result = self.call(url, data)

        msg = 'Create lun group error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        return result['data']['ID']

    def _delete_lungroup(self, lungroupid):
        url = self.url + "/LUNGroup/" + lungroupid
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, 'Delete lun group error.')

    def _lungroup_associated(self, viewid, lungroupid):
        url_subfix = ("/mappingview/associate?TYPE=245&"
                      "ASSOCIATEOBJTYPE=256&ASSOCIATEOBJID=%s" % lungroupid)
        url = self.url + url_subfix
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, 'Check lun group associated error.')

        if "data" in result:
            for item in result['data']:
                if viewid == item['ID']:
                    return True
        return False

    def _hostgroup_associated(self, viewid, hostgroupid):
        url_subfix = ("/mappingview/associate?TYPE=245&"
                      "ASSOCIATEOBJTYPE=14&ASSOCIATEOBJID=%s" % hostgroupid)
        url = self.url + url_subfix
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, 'Check host group associated error.')

        if "data" in result:
            for item in result['data']:
                if viewid == item['ID']:
                    return True
        return False

    def _find_host_lun_id(self, hostid, lunid):
        time.sleep(2)
        url = self.url + ("/lun/associate?TYPE=11&ASSOCIATEOBJTYPE=21"
                          "&ASSOCIATEOBJID=%s" % (hostid))
        result = self.call(url, None, "GET")
        self._assert_rest_result(result, 'Find host lun id error.')

        host_lun_id = 1
        if "data" in result:
            for item in result['data']:
                if lunid == item['ID']:
                    associate_data = result['data'][0]['ASSOCIATEMETADATA']
                    try:
                        hostassoinfo = json.loads(associate_data)
                        host_lun_id = hostassoinfo['HostLUNID']
                        break
                    except Exception as err:
                        msg = _("JSON transfer data error. %s") % err
                        LOG.error(msg)
                        raise err
        return host_lun_id

    def _find_host(self, hostname):
        """Get the given host ID."""
        url = self.url + "/host"
        data = json.dumps({"TYPE": "21"})
        result = self.call(url, data, "GET")
        self._assert_rest_result(result, 'Find host in host group error.')

        host_id = None
        if "data" in result:
            for item in result['data']:
                if hostname == item['NAME']:
                    host_id = item['ID']
                    break
        return host_id

    def _add_host(self, hostname, type):
        """Add a new host."""
        url = self.url + "/host"
        data = json.dumps({"TYPE": "21",
                           "NAME": hostname,
                           "OPERATIONSYSTEM": type})
        result = self.call(url, data)
        self._assert_rest_result(result, 'Add new host error.')

        if "data" in result:
            return result['data']['ID']
        else:
            return None

    def _associate_host_to_hostgroup(self, hostgroupid, hostid):
        url = self.url + "/host/associate"
        data = json.dumps({"ID": hostgroupid,
                           "ASSOCIATEOBJTYPE": "21",
                           "ASSOCIATEOBJID": hostid})

        result = self.call(url, data)
        self._assert_rest_result(result, 'Associate host to host group error.')

    def _associate_lun_to_lungroup(self, lungroupid, lunid):
        """Associate lun to lun group."""
        url = self.url + "/lungroup/associate"
        data = json.dumps({"ID": lungroupid,
                           "ASSOCIATEOBJTYPE": "11",
                           "ASSOCIATEOBJID": lunid})
        result = self.call(url, data)
        self._assert_rest_result(result, 'Associate lun to lun group error.')

    def _delete_associated_lun_from_lungroup(self, lungroupid, lunid):
        """Remove lun from lun group."""

        url = self.url + ("/lungroup/associate?ID=%s"
                          "&ASSOCIATEOBJTYPE=11&ASSOCIATEOBJID=%s"
                          % (lungroupid, lunid))

        result = self.call(url, None, 'DELETE')
        self._assert_rest_result(result,
                                 'Delete associated lun from lun group error')

    def _initiator_is_added_to_array(self, ininame):
        """Check whether the initiator is already added in array."""
        url = self.url + "/iscsi_initiator"
        data = json.dumps({"TYPE": "222", "ID": ininame})
        result = self.call(url, data, "GET")
        self._assert_rest_result(result,
                                 'Check initiator added to array error.')

        if "data" in result:
            for item in result['data']:
                if item["ID"] == ininame:
                    return True
        return False

    def _is_initiator_associated_to_host(self, ininame):
        """Check whether the initiator is associated to the host."""
        url = self.url + "/iscsi_initiator"
        data = json.dumps({"TYPE": "222", "ID": ininame})
        result = self.call(url, data, "GET")
        self._assert_rest_result(result,
                                 'Check initiator associated to host error.')

        if "data" in result:
            for item in result['data']:
                if item['ID'] == ininame and item['ISFREE'] == "true":
                    return False
        return True

    def _add_initiator_to_array(self, ininame):
        """Add a new initiator to storage device."""
        url = self.url + "/iscsi_initiator/"
        data = json.dumps({"TYPE": "222",
                           "ID": ininame,
                           "USECHAP": "False"})
        result = self.call(url, data)
        self._assert_rest_result(result, 'Add initiator to array error.')

    def _associate_initiator_to_host(self, ininame, hostid):
        """Associate initiator with the host."""
        url = self.url + "/iscsi_initiator/" + ininame
        data = json.dumps({"TYPE": "222",
                           "ID": ininame,
                           "USECHAP": "False",
                           "PARENTTYPE": "21",
                           "PARENTID": hostid})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, 'Associate initiator to host error.')

    def _find_mapping_view(self, name):
        """Find mapping view."""
        url = self.url + "/mappingview"
        data = json.dumps({"TYPE": "245"})
        result = self.call(url, data, "GET")

        msg = 'Find map view error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        viewid = None
        for item in result['data']:
            if name == item['NAME']:
                viewid = item['ID']
                break
        return viewid

    def _add_mapping_view(self, name, host_id):
        url = self.url + "/mappingview"
        data = json.dumps({"NAME": name, "TYPE": "245"})
        result = self.call(url, data)
        self._assert_rest_result(result, 'Add map view error.')

        return result['data']['ID']

    def _associate_hostgroup_to_view(self, viewID, hostGroupID):
        url = self.url + "/MAPPINGVIEW/CREATE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "14",
                           "ASSOCIATEOBJID": hostGroupID,
                           "TYPE": "245",
                           "ID": viewID})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, 'Associate host to view error.')

    def _associate_lungroup_to_view(self, viewID, lunGroupID):
        url = self.url + "/MAPPINGVIEW/CREATE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "256",
                           "ASSOCIATEOBJID": lunGroupID,
                           "TYPE": "245",
                           "ID": viewID})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, 'Associate lun group to view error.')

    def _delete_lungroup_mapping_view(self, view_id, lungroup_id):
        """remove lun group associate from the mapping view."""
        url = self.url + "/mappingview/REMOVE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "256",
                           "ASSOCIATEOBJID": lungroup_id,
                           "TYPE": "245",
                           "ID": view_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, 'Delete lun group from view error.')

    def _delete_hostgoup_mapping_view(self, view_id, hostgroup_id):
        """remove host group associate from the mapping view."""
        url = self.url + "/mappingview/REMOVE_ASSOCIATE"
        data = json.dumps({"ASSOCIATEOBJTYPE": "14",
                           "ASSOCIATEOBJID": hostgroup_id,
                           "TYPE": "245",
                           "ID": view_id})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, 'Delete host group from view error.')

    def _delete_mapping_view(self, view_id):
        """remove mapping view from the storage."""
        url = self.url + "/mappingview/" + view_id
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, 'Delete map view error.')

    def terminate_connection(self, volume, connector, **kwargs):
        """Delete map between a volume and a host."""
        initiator_name = connector['initiator']
        volume_name = self._encode_name(volume['id'])
        host_name = connector['host']

        LOG.debug(_('terminate_connection:volume name: %(volume)s, '
                    'initiator name: %(ini)s.')
                  % {'volume': volume_name,
                     'ini': initiator_name})

        view_id = self._find_mapping_view(volume_name)
        hostgroup_id = self._find_hostgroup(host_name)
        lungroup_id = self._find_lungroup(volume_name)

        if view_id is not None:
            self._delete_hostgoup_mapping_view(view_id, hostgroup_id)
            self._delete_lungroup_mapping_view(view_id, lungroup_id)
            self._delete_mapping_view(view_id)

    def login_out(self):
        """logout the session."""
        url = self.url + "/sessions"
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, 'Log out of session error.')

    def _start_luncopy(self, luncopyid):
        """Start a LUNcopy."""
        url = self.url + "/LUNCOPY/start"
        data = json.dumps({"TYPE": "219", "ID": luncopyid})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, 'Start lun copy error.')

    def _get_capacity(self):
        """Get free capacity and total capacity of the pools."""
        poolinfo = self._find_pool_info()
        pool_capacity = {'total_capacity': 0.0,
                         'CAPACITY': 0.0}

        if poolinfo:
            total = int(poolinfo['TOTALCAPACITY']) / 1024.0 / 1024.0 / 2
            free = int(poolinfo['CAPACITY']) / 1024.0 / 1024.0 / 2
            pool_capacity['total_capacity'] = total
            pool_capacity['free_capacity'] = free

        return pool_capacity

    def _get_lun_conf_params(self):
        """Get parameters from config file for creating lun."""
        # Default lun set information
        lunsetinfo = {'LUNType': 'Thick',
                      'StripUnitSize': '64',
                      'WriteType': '1',
                      'MirrorSwitch': '1',
                      'PrefetchType': '3',
                      'PrefetchValue': '0',
                      'PrefetchTimes': '0'}

        root = huawei_utils.parse_xml_file(self.xml_conf)
        luntype = root.findtext('LUN/LUNType')
        if luntype:
            if luntype.strip() in ['Thick', 'Thin']:
                lunsetinfo['LUNType'] = luntype.strip()
                if luntype.strip() == 'Thick':
                    lunsetinfo['LUNType'] = 0
                if luntype.strip() == 'Thin':
                    lunsetinfo['LUNType'] = 1

            elif luntype is not '' and luntype is not None:
                err_msg = (_('Config file is wrong. LUNType must be "Thin"'
                             ' or "Thick". LUNType:%(fetchtype)s')
                           % {'fetchtype': luntype})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

        stripunitsize = root.findtext('LUN/StripUnitSize')
        if stripunitsize is not None:
            lunsetinfo['StripUnitSize'] = stripunitsize.strip()
        writetype = root.findtext('LUN/WriteType')
        if writetype is not None:
            lunsetinfo['WriteType'] = writetype.strip()
        mirrorswitch = root.findtext('LUN/MirrorSwitch')
        if mirrorswitch is not None:
            lunsetinfo['MirrorSwitch'] = mirrorswitch.strip()

        prefetch = root.find('LUN/Prefetch')
        fetchtype = prefetch.attrib['Type']
        if prefetch is not None and prefetch.attrib['Type']:
            if fetchtype in ['0', '1', '2', '3']:
                lunsetinfo['PrefetchType'] = fetchtype.strip()
                typevalue = prefetch.attrib['Value'].strip()
                if lunsetinfo['PrefetchType'] == '1':
                    lunsetinfo['PrefetchValue'] = typevalue
                elif lunsetinfo['PrefetchType'] == '2':
                    lunsetinfo['PrefetchValue'] = typevalue
            else:
                err_msg = (_('PrefetchType config is wrong. PrefetchType'
                             ' must in 1,2,3,4. fetchtype is:%(fetchtype)s')
                           % {'fetchtype': fetchtype})
                LOG.error(err_msg)
                raise exception.CinderException(err_msg)
        else:
            LOG.debug(_('Use default prefetch fetchtype. '
                        'Prefetch fetchtype:Intelligent.'))

        return lunsetinfo

    def _wait_for_luncopy(self, luncopyid):
        """Wait for LUNcopy to complete."""
        while True:
            luncopy_info = self._get_luncopy_info(luncopyid)
            if luncopy_info['status'] == '40':
                break
            elif luncopy_info['state'] != '1':
                err_msg = (_('_wait_for_luncopy:LUNcopy status is not normal.'
                             'LUNcopy name: %(luncopyname)s')
                           % {'luncopyname': luncopyid})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)
            time.sleep(10)

    def _get_luncopy_info(self, luncopyid):
        """Get LUNcopy information."""
        url = self.url + "/LUNCOPY?range=[0-100000]"
        data = json.dumps({"TYPE": "219", })
        result = self.call(url, data, "GET")
        self._assert_rest_result(result, 'Get lun copy information error.')

        luncopyinfo = {}
        if "data" in result:
            for item in result['data']:
                if luncopyid == item['ID']:
                    luncopyinfo['name'] = item['NAME']
                    luncopyinfo['id'] = item['ID']
                    luncopyinfo['state'] = item['HEALTHSTATUS']
                    luncopyinfo['status'] = item['RUNNINGSTATUS']
                    break
        return luncopyinfo

    def _delete_luncopy(self, luncopyid):
        """Delete a LUNcopy."""
        url = self.url + "/LUNCOPY/%s" % luncopyid
        result = self.call(url, None, "DELETE")
        self._assert_rest_result(result, 'Delete lun copy error.')

    def _get_connected_free_wwns(self):
        """Get free connected FC port WWNs.

        If no new ports connected, return an empty list.
        """
        url = self.url + "/fc_initiator?ISFREE=true&range=[0-1000]"
        result = self.call(url, None, "GET")

        msg = 'Get connected free FC wwn error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        wwns = []
        for item in result['data']:
            wwns.append(item['ID'])
        return wwns

    def _add_fc_port_to_host(self, hostid, wwn, multipathtype=0):
        """Add a FC port to the host."""
        url = self.url + "/fc_initiator/" + wwn
        data = json.dumps({"TYPE": "223",
                           "ID": wwn,
                           "PARENTTYPE": 21,
                           "PARENTID": hostid})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, 'Add FC port to host error.')

    def _get_iscsi_port_info(self, ip):
        """Get iscsi port info in order to build the iscsi target iqn."""
        url = self.url + "/eth_port"
        result = self.call(url, None, "GET")

        msg = 'Get iSCSI port information error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        iscsi_port_info = None
        for item in result['data']:
            if ip == item['IPV4ADDR']:
                iscsi_port_info = item['LOCATION']
                break

        if not iscsi_port_info:
            msg = (_('_get_iscsi_port_info: Failed to get iscsi port info '
                     'through config IP %(ip)s, please check config file.')
                   % {'ip': ip})
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        return iscsi_port_info

    def _get_iscsi_conf(self):
        """Get iSCSI info from config file."""
        iscsiinfo = {}
        root = huawei_utils.parse_xml_file(self.xml_conf)
        iscsiinfo['DefaultTargetIP'] = \
            root.findtext('iSCSI/DefaultTargetIP').strip()
        initiator_list = []
        tmp_dic = {}
        for dic in root.findall('iSCSI/Initiator'):
            # Strip values of dic
            for k, v in dic.items():
                tmp_dic[k] = v.strip()
            initiator_list.append(tmp_dic)
        iscsiinfo['Initiator'] = initiator_list

        return iscsiinfo

    def _get_tgt_iqn(self, iscsiip):
        """Get target iSCSI iqn."""
        LOG.debug(_('_get_tgt_iqn: iSCSI IP is %s.') % iscsiip)
        ip_info = self._get_iscsi_port_info(iscsiip)
        iqn_prefix = self._get_iscsi_tgt_port()

        split_list = ip_info.split(".")
        newstr = split_list[1] + split_list[2]
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
        iqn = iqn_prefix + ':' + iqn_suffix + ':' + iscsiip
        LOG.debug(_('_get_tgt_iqn: iSCSI target iqn is %s') % iqn)
        return iqn

    def _get_fc_target_wwpns(self, wwn):
        url = (self.url +
               "/host_link?INITIATOR_TYPE=223&INITIATOR_PORT_WWN=" + wwn)
        result = self.call(url, None, "GET")

        msg = 'Get FC target wwpn error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        fc_wwpns = None
        for item in result['data']:
            if wwn == item['INITIATOR_PORT_WWN']:
                fc_wwpns = item['TARGET_PORT_WWN']
                break

        return fc_wwpns

    def _parse_volume_type(self, volume):
        type_id = volume['volume_type_id']
        params = self._get_lun_conf_params()
        LOG.debug(_('_parse_volume_type: type id: %(type_id)s '
                    'config parameter is: %(params)s')
                  % {'type_id': type_id,
                     'params': params})

        poolinfo = self._find_pool_info()
        volume_size = self._get_volume_size(poolinfo, volume)
        params['volume_size'] = volume_size
        params['pool_id'] = poolinfo['ID']

        if type_id is not None:
            ctxt = context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            specs = volume_type.get('extra_specs')
            for key, value in specs.iteritems():
                key_split = key.split(':')
                if len(key_split) > 1:
                    if key_split[0] == 'drivers':
                        key = key_split[1]
                    else:
                        continue
                else:
                    key = key_split[0]

                if key in QOS_KEY:
                    params["qos"] = value.strip()
                    params["qos_level"] = key
                elif key in TIER_KEY:
                    params["tier"] = value.strip()
                elif key in params.keys():
                    params[key] = value.strip()
                else:
                    conf = self.configuration.cinder_huawei_conf_file
                    LOG.warn(_('_parse_volume_type: Unacceptable parameter '
                               '%(key)s. Please check this key in extra_specs '
                               'and make it consistent with the configuration '
                               'file %(conf)s.') % {'key': key, 'conf': conf})

        LOG.debug(_("The config parameters are: %s") % params)
        return params

    def update_volume_stats(self, refresh=False):
        capacity = self._get_capacity()
        data = {}
        data['vendor_name'] = 'Huawei'
        data['total_capacity_gb'] = capacity['total_capacity']
        data['free_capacity_gb'] = capacity['free_capacity']
        data['reserved_percentage'] = 0
        data['QoS_support'] = True
        data['Tier_support'] = True
        return data

    def _find_qos_policy_info(self, policy_name):
        url = self.url + "/ioclass"
        result = self.call(url, None, "GET")

        msg = 'Get qos policy error.'
        self._assert_rest_result(result, msg)
        self._assert_data_in_result(result, msg)

        qos_info = {}
        for item in result['data']:
            if policy_name == item['NAME']:
                qos_info['ID'] = item['ID']
                lun_list = json.loads(item['LUNLIST'])
                qos_info['LUNLIST'] = lun_list
                break
        return qos_info

    def _update_qos_policy_lunlist(self, lunlist, policy_id):
        url = self.url + "/ioclass/" + policy_id
        data = json.dumps({"TYPE": "230",
                           "ID": policy_id,
                           "LUNLIST": lunlist})
        result = self.call(url, data, "PUT")
        self._assert_rest_result(result, 'Up date qos policy error.')

    def _get_login_info(self):
        """Get login IP, username and password from config file."""
        logininfo = {}
        filename = self.configuration.cinder_huawei_conf_file
        tree = ET.parse(filename)
        root = tree.getroot()
        logininfo['HVSURL'] = root.findtext('Storage/HVSURL').strip()

        need_encode = False
        for key in ['UserName', 'UserPassword']:
            node = root.find('Storage/%s' % key)
            node_text = node.text
            # Prefix !$$$ means encoded already.
            if node_text.find('!$$$') > -1:
                logininfo[key] = base64.b64decode(node_text[4:])
            else:
                logininfo[key] = node_text
                node.text = '!$$$' + base64.b64encode(node_text)
                need_encode = True
        if need_encode:
            self._change_file_mode(filename)
            try:
                tree.write(filename, 'UTF-8')
            except Exception as err:
                LOG.warn(_('%s') % err)

        return logininfo

    def _change_file_mode(self, filepath):
        utils.execute('chmod', '777', filepath, run_as_root=True)

    def _check_conf_file(self):
        """Check the config file, make sure the essential items are set."""
        root = huawei_utils.parse_xml_file(self.xml_conf)
        check_list = ['Storage/HVSURL', 'Storage/UserName',
                      'Storage/UserPassword']
        for item in check_list:
            if not huawei_utils.is_xml_item_exist(root, item):
                err_msg = (_('_check_conf_file: Config file invalid. '
                             '%s must be set.') % item)
                LOG.error(err_msg)
                raise exception.InvalidInput(reason=err_msg)

        # make sure storage pool is set
        if not huawei_utils.is_xml_item_exist(root, 'LUN/StoragePool'):
            err_msg = _('_check_conf_file: Config file invalid. '
                        'StoragePool must be set.')
            LOG.error(err_msg)
            raise exception.InvalidInput(reason=err_msg)

        # make sure host os type valid
        if huawei_utils.is_xml_item_exist(root, 'Host', 'OSType'):
            os_list = huawei_utils.os_type.keys()
            if not huawei_utils.is_xml_item_valid(root, 'Host', os_list,
                                                  'OSType'):
                err_msg = (_('_check_conf_file: Config file invalid. '
                             'Host OSType invalid.\n'
                             'The valid values are: %(os_list)s')
                           % {'os_list': os_list})
                LOG.error(err_msg)
                raise exception.InvalidInput(reason=err_msg)

    def _get_iscsi_params(self, connector):
        """Get target iSCSI params, including iqn, IP."""
        initiator = connector['initiator']
        iscsi_conf = self._get_iscsi_conf()
        target_ip = None
        for ini in iscsi_conf['Initiator']:
            if ini['Name'] == initiator:
                target_ip = ini['TargetIP']
                break
        # If didn't specify target IP for some initiator, use default IP.
        if not target_ip:
            if iscsi_conf['DefaultTargetIP']:
                target_ip = iscsi_conf['DefaultTargetIP']

            else:
                msg = (_('_get_iscsi_params: Failed to get target IP '
                         'for initiator %(ini)s, please check config file.')
                       % {'ini': initiator})
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

        target_iqn = self._get_tgt_iqn(target_ip)

        return (target_iqn, target_ip)

    def extend_volume(self, volume, new_size):
        name = self._encode_name(volume['id'])
        lun_id = self._get_volume_by_name(name)
        if lun_id:
            url = self.url + "/lun/expand"
            capacity = int(new_size) * units.GiB / 512
            data = json.dumps({"TYPE": "11",
                               "ID": lun_id,
                               "CAPACITY": capacity})
            result = self.call(url, data, "PUT")
            self._assert_rest_result(result, 'Extend lun error.')
        else:
            LOG.warn(_('Can not find lun in array'))
