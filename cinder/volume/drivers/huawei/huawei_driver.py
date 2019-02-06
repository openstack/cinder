# Copyright (c) 2016 Huawei Technologies Co., Ltd.
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

from oslo_log import log as logging
from oslo_utils import strutils

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.huawei import common
from cinder.volume.drivers.huawei import constants
from cinder.volume.drivers.huawei import fc_zone_helper
from cinder.volume.drivers.huawei import huawei_utils
from cinder.volume.drivers.huawei import hypermetro
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class HuaweiISCSIDriver(common.HuaweiBaseDriver, driver.ISCSIDriver):
    """ISCSI driver for Huawei storage arrays.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        1.1.0 - Provide Huawei OceanStor storage 18000 driver
        1.1.1 - Code refactor
                CHAP support
                Multiple pools support
                ISCSI multipath support
                SmartX support
                Volume migration support
                Volume retype support
        2.0.0 - Rename to HuaweiISCSIDriver
        2.0.1 - Manage/unmanage volume support
        2.0.2 - Refactor HuaweiISCSIDriver
        2.0.3 - Manage/unmanage snapshot support
        2.0.5 - Replication V2 support
        2.0.6 - Support iSCSI configuration in Replication
        2.0.7 - Hypermetro support
                Hypermetro consistency group support
                Consistency group support
                Cgsnapshot support
        2.0.8 - Backup snapshot optimal path support
        2.0.9 - Support reporting disk type of pool
    """

    VERSION = "2.0.9"

    def __init__(self, *args, **kwargs):
        super(HuaweiISCSIDriver, self).__init__(*args, **kwargs)

    def get_volume_stats(self, refresh=False):
        """Get volume status."""
        data = self._get_volume_stats(refresh=False)
        data['storage_protocol'] = 'iSCSI'
        data['driver_version'] = self.VERSION
        return data

    @coordination.synchronized('huawei-mapping-{connector[host]}')
    def initialize_connection(self, volume, connector):
        """Map a volume to a host and return target iSCSI information."""
        lun_id, lun_type = self.get_lun_id_and_type(volume)
        initiator_name = connector['initiator']
        LOG.info(
            'initiator name: %(initiator_name)s, '
            'LUN ID: %(lun_id)s.',
            {'initiator_name': initiator_name,
             'lun_id': lun_id})

        (iscsi_iqns,
         target_ips,
         portgroup_id) = self.client.get_iscsi_params(connector)
        LOG.info('initialize_connection, iscsi_iqn: %(iscsi_iqn)s, '
                 'target_ip: %(target_ip)s, '
                 'portgroup_id: %(portgroup_id)s.',
                 {'iscsi_iqn': iscsi_iqns,
                  'target_ip': target_ips,
                  'portgroup_id': portgroup_id},)

        # Create hostgroup if not exist.
        host_id = self.client.add_host_with_check(connector['host'])

        # Add initiator to the host.
        self.client.ensure_initiator_added(initiator_name,
                                           host_id)
        hostgroup_id = self.client.add_host_to_hostgroup(host_id)

        # Mapping lungroup and hostgroup to view.
        self.client.do_mapping(lun_id, hostgroup_id,
                               host_id, portgroup_id,
                               lun_type)

        hostlun_id = self.client.get_host_lun_id(host_id, lun_id,
                                                 lun_type)

        LOG.info("initialize_connection, host lun id is: %s.",
                 hostlun_id)

        chapinfo = self.client.find_chap_info(self.client.iscsi_info,
                                              initiator_name)

        # Return iSCSI properties.
        properties = {}
        properties['target_discovered'] = False
        properties['volume_id'] = volume.id
        multipath = connector.get('multipath', False)
        hostlun_id = int(hostlun_id)
        if not multipath:
            properties['target_portal'] = ('%s:3260' % target_ips[0])
            properties['target_iqn'] = iscsi_iqns[0]
            properties['target_lun'] = hostlun_id
        else:
            properties['target_iqns'] = [iqn for iqn in iscsi_iqns]
            properties['target_portals'] = [
                '%s:3260' % ip for ip in target_ips]
            properties['target_luns'] = [hostlun_id] * len(target_ips)

        # If use CHAP, return CHAP info.
        if chapinfo:
            chap_username, chap_password = chapinfo.split(';')
            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = chap_username
            properties['auth_password'] = chap_password

        LOG.info("initialize_connection success. Return data: %s.",
                 strutils.mask_password(properties))
        return {'driver_volume_type': 'iscsi', 'data': properties}

    @coordination.synchronized('huawei-mapping-{connector[host]}')
    def terminate_connection(self, volume, connector, **kwargs):
        """Delete map between a volume and a host."""
        lun_id, lun_type = self.get_lun_id_and_type(volume)
        initiator_name = connector['initiator']
        host_name = connector['host']
        lungroup_id = None

        LOG.info(
            'terminate_connection: initiator name: %(ini)s, '
            'LUN ID: %(lunid)s.',
            {'ini': initiator_name,
             'lunid': lun_id},)

        portgroup = None
        portgroup_id = None
        view_id = None
        left_lunnum = -1
        ini = self.client.iscsi_info['initiators'].get(initiator_name)
        if ini and ini.get('TargetPortGroup'):
            portgroup = ini['TargetPortGroup']

        if portgroup:
            portgroup_id = self.client.get_tgt_port_group(portgroup)
        host_id = huawei_utils.get_host_id(self.client, host_name)
        if host_id:
            mapping_view_name = constants.MAPPING_VIEW_PREFIX + host_id
            view_id = self.client.find_mapping_view(mapping_view_name)
            if view_id:
                lungroup_id = self.client.find_lungroup_from_map(view_id)

        # Remove lun from lungroup.
        if lun_id and lungroup_id:
            lungroup_ids = self.client.get_lungroupids_by_lunid(
                lun_id, lun_type)
            if lungroup_id in lungroup_ids:
                self.client.remove_lun_from_lungroup(lungroup_id,
                                                     lun_id,
                                                     lun_type)
            else:
                LOG.warning("LUN is not in lungroup. "
                            "LUN ID: %(lun_id)s. "
                            "Lungroup id: %(lungroup_id)s.",
                            {"lun_id": lun_id,
                             "lungroup_id": lungroup_id})

        # Remove portgroup from mapping view if no lun left in lungroup.
        if lungroup_id:
            left_lunnum = self.client.get_obj_count_from_lungroup(lungroup_id)

        if portgroup_id and view_id and (int(left_lunnum) <= 0):
            if self.client.is_portgroup_associated_to_view(view_id,
                                                           portgroup_id):
                self.client.delete_portgroup_mapping_view(view_id,
                                                          portgroup_id)
        if view_id and (int(left_lunnum) <= 0):
            self.client.remove_chap(initiator_name)

            if self.client.lungroup_associated(view_id, lungroup_id):
                self.client.delete_lungroup_mapping_view(view_id,
                                                         lungroup_id)
            self.client.delete_lungroup(lungroup_id)
            if self.client.is_initiator_associated_to_host(initiator_name,
                                                           host_id):
                self.client.remove_iscsi_from_host(initiator_name)
            hostgroup_name = constants.HOSTGROUP_PREFIX + host_id
            hostgroup_id = self.client.find_hostgroup(hostgroup_name)
            if hostgroup_id:
                if self.client.hostgroup_associated(view_id, hostgroup_id):
                    self.client.delete_hostgoup_mapping_view(view_id,
                                                             hostgroup_id)
                self.client.remove_host_from_hostgroup(hostgroup_id,
                                                       host_id)
                self.client.delete_hostgroup(hostgroup_id)
            self.client.remove_host(host_id)
            self.client.delete_mapping_view(view_id)


@interface.volumedriver
class HuaweiFCDriver(common.HuaweiBaseDriver, driver.FibreChannelDriver):
    """FC driver for Huawei OceanStor storage arrays.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        1.1.0 - Provide Huawei OceanStor 18000 storage volume driver
        1.1.1 - Code refactor
                Multiple pools support
                SmartX support
                Volume migration support
                Volume retype support
                FC zone enhancement
                Volume hypermetro support
        2.0.0 - Rename to HuaweiFCDriver
        2.0.1 - Manage/unmanage volume support
        2.0.2 - Refactor HuaweiFCDriver
        2.0.3 - Manage/unmanage snapshot support
        2.0.4 - Balanced FC port selection
        2.0.5 - Replication V2 support
        2.0.7 - Hypermetro support
                Hypermetro consistency group support
                Consistency group support
                Cgsnapshot support
        2.0.8 - Backup snapshot optimal path support
        2.0.9 - Support reporting disk type of pool
    """

    VERSION = "2.0.9"

    def __init__(self, *args, **kwargs):
        super(HuaweiFCDriver, self).__init__(*args, **kwargs)
        self.fcsan = None

    def get_volume_stats(self, refresh=False):
        """Get volume status."""
        data = self._get_volume_stats(refresh=False)
        data['storage_protocol'] = 'FC'
        data['driver_version'] = self.VERSION
        return data

    @coordination.synchronized('huawei-mapping-{connector[host]}')
    def initialize_connection(self, volume, connector):
        lun_id, lun_type = self.get_lun_id_and_type(volume)
        wwns = connector['wwpns']
        LOG.info(
            'initialize_connection, initiator: %(wwpns)s,'
            ' LUN ID: %(lun_id)s.',
            {'wwpns': wwns,
             'lun_id': lun_id},)

        portg_id = None
        host_id = self.client.add_host_with_check(connector['host'])

        if not self.fcsan:
            self.fcsan = fczm_utils.create_lookup_service()

        if self.fcsan:
            # Use FC switch.
            zone_helper = fc_zone_helper.FCZoneHelper(self.fcsan, self.client)
            try:
                (tgt_port_wwns, portg_id, init_targ_map) = (
                    zone_helper.build_ini_targ_map(wwns, host_id, lun_id,
                                                   lun_type))
            except Exception as err:
                self.remove_host_with_check(host_id)
                msg = _('build_ini_targ_map fails. %s') % err
                raise exception.VolumeBackendAPIException(data=msg)

            for ini in init_targ_map:
                self.client.ensure_fc_initiator_added(ini, host_id)
        else:
            # Not use FC switch.
            online_wwns_in_host = (
                self.client.get_host_online_fc_initiators(host_id))
            online_free_wwns = self.client.get_online_free_wwns()
            fc_initiators_on_array = self.client.get_fc_initiator_on_array()
            wwns = [i for i in wwns if i in fc_initiators_on_array]

            for wwn in wwns:
                if (wwn not in online_wwns_in_host
                        and wwn not in online_free_wwns):
                    wwns_in_host = (
                        self.client.get_host_fc_initiators(host_id))
                    iqns_in_host = (
                        self.client.get_host_iscsi_initiators(host_id))
                    if not (wwns_in_host or iqns_in_host or
                       self.client.is_host_associated_to_hostgroup(host_id)):
                        self.client.remove_host(host_id)

                    msg = _('No FC initiator can be added to host.')
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

            for wwn in wwns:
                if wwn in online_free_wwns:
                    self.client.add_fc_port_to_host(host_id, wwn)

            (tgt_port_wwns, init_targ_map) = (
                self.client.get_init_targ_map(wwns))

        # Add host into hostgroup.
        hostgroup_id = self.client.add_host_to_hostgroup(host_id)

        metadata = huawei_utils.get_volume_private_data(volume)
        LOG.info("initialize_connection, metadata is: %s.", metadata)
        hypermetro_lun = metadata.get('hypermetro_id') is not None

        map_info = self.client.do_mapping(lun_id, hostgroup_id,
                                          host_id, portg_id,
                                          lun_type, hypermetro_lun)
        host_lun_id = self.client.get_host_lun_id(host_id, lun_id,
                                                  lun_type)

        # Return FC properties.
        fc_info = {'driver_volume_type': 'fibre_channel',
                   'data': {'target_lun': int(host_lun_id),
                            'target_discovered': True,
                            'target_wwn': tgt_port_wwns,
                            'volume_id': volume.id,
                            'initiator_target_map': init_targ_map,
                            'map_info': map_info}, }

        # Deal with hypermetro connection.
        if hypermetro_lun:
            loc_tgt_wwn = fc_info['data']['target_wwn']
            local_ini_tgt_map = fc_info['data']['initiator_target_map']
            hyperm = hypermetro.HuaweiHyperMetro(self.client,
                                                 self.rmt_client,
                                                 self.configuration)
            rmt_fc_info = hyperm.connect_volume_fc(volume, connector)

            rmt_tgt_wwn = rmt_fc_info['data']['target_wwn']
            rmt_ini_tgt_map = rmt_fc_info['data']['initiator_target_map']
            fc_info['data']['target_wwn'] = (loc_tgt_wwn + rmt_tgt_wwn)
            wwns = connector['wwpns']
            for wwn in wwns:
                if (wwn in local_ini_tgt_map
                        and wwn in rmt_ini_tgt_map):
                    fc_info['data']['initiator_target_map'][wwn].extend(
                        rmt_ini_tgt_map[wwn])

                elif (wwn not in local_ini_tgt_map
                        and wwn in rmt_ini_tgt_map):
                    fc_info['data']['initiator_target_map'][wwn] = (
                        rmt_ini_tgt_map[wwn])
                # else, do nothing

            loc_map_info = fc_info['data']['map_info']
            rmt_map_info = rmt_fc_info['data']['map_info']
            same_host_id = self._get_same_hostid(loc_map_info,
                                                 rmt_map_info)

            self.client.change_hostlun_id(loc_map_info, same_host_id)
            hyperm.rmt_client.change_hostlun_id(rmt_map_info, same_host_id)

            fc_info['data']['target_lun'] = same_host_id
            hyperm.rmt_client.logout()

        fczm_utils.add_fc_zone(fc_info)
        LOG.info("Return FC info is: %s.", fc_info)
        return fc_info

    def _get_same_hostid(self, loc_fc_info, rmt_fc_info):
        loc_aval_luns = loc_fc_info['aval_luns']
        loc_aval_luns = json.loads(loc_aval_luns)

        rmt_aval_luns = rmt_fc_info['aval_luns']
        rmt_aval_luns = json.loads(rmt_aval_luns)
        same_host_id = None

        for i in range(1, 512):
            if i in rmt_aval_luns and i in loc_aval_luns:
                same_host_id = i
                break

        LOG.info("The same hostid is: %s.", same_host_id)
        if not same_host_id:
            msg = _("Can't find the same host id from arrays.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return same_host_id

    @coordination.synchronized('huawei-mapping-{connector[host]}')
    def terminate_connection(self, volume, connector, **kwargs):
        """Delete map between a volume and a host."""
        lun_id, lun_type = self.get_lun_id_and_type(volume)
        wwns = connector['wwpns']
        host_name = connector['host']
        left_lunnum = -1
        lungroup_id = None
        view_id = None
        LOG.info('terminate_connection: wwpns: %(wwns)s, '
                 'LUN ID: %(lun_id)s.',
                 {'wwns': wwns, 'lun_id': lun_id})

        host_id = huawei_utils.get_host_id(self.client, host_name)
        if host_id:
            mapping_view_name = constants.MAPPING_VIEW_PREFIX + host_id
            view_id = self.client.find_mapping_view(mapping_view_name)
            if view_id:
                lungroup_id = self.client.find_lungroup_from_map(view_id)

        if lun_id and lungroup_id:
            lungroup_ids = self.client.get_lungroupids_by_lunid(lun_id,
                                                                lun_type)
            if lungroup_id in lungroup_ids:
                self.client.remove_lun_from_lungroup(lungroup_id,
                                                     lun_id,
                                                     lun_type)
            else:
                LOG.warning("LUN is not in lungroup. "
                            "LUN ID: %(lun_id)s. "
                            "Lungroup id: %(lungroup_id)s.",
                            {"lun_id": lun_id,
                             "lungroup_id": lungroup_id})

        else:
            LOG.warning("Can't find lun on the array.")
        if lungroup_id:
            left_lunnum = self.client.get_obj_count_from_lungroup(lungroup_id)
        if int(left_lunnum) > 0:
            fc_info = {'driver_volume_type': 'fibre_channel',
                       'data': {}}
        else:
            fc_info, portg_id = self._delete_zone_and_remove_fc_initiators(
                wwns, host_id)
            if lungroup_id:
                if view_id and self.client.lungroup_associated(
                        view_id, lungroup_id):
                    self.client.delete_lungroup_mapping_view(view_id,
                                                             lungroup_id)
                self.client.delete_lungroup(lungroup_id)
            if portg_id:
                if view_id and self.client.is_portgroup_associated_to_view(
                        view_id, portg_id):
                    self.client.delete_portgroup_mapping_view(view_id,
                                                              portg_id)
                    self.client.delete_portgroup(portg_id)

            if host_id:
                hostgroup_name = constants.HOSTGROUP_PREFIX + host_id
                hostgroup_id = self.client.find_hostgroup(hostgroup_name)
                if hostgroup_id:
                    if view_id and self.client.hostgroup_associated(
                            view_id, hostgroup_id):
                        self.client.delete_hostgoup_mapping_view(
                            view_id, hostgroup_id)
                    self.client.remove_host_from_hostgroup(
                        hostgroup_id, host_id)
                    self.client.delete_hostgroup(hostgroup_id)

                if not self.client.check_fc_initiators_exist_in_host(
                        host_id):
                    self.client.remove_host(host_id)

            if view_id:
                self.client.delete_mapping_view(view_id)

        # Deal with hypermetro connection.
        metadata = huawei_utils.get_volume_private_data(volume)
        LOG.info("Detach Volume, metadata is: %s.", metadata)

        if metadata.get('hypermetro_id'):
            hyperm = hypermetro.HuaweiHyperMetro(self.client,
                                                 self.rmt_client,
                                                 self.configuration)
            hyperm.disconnect_volume_fc(volume, connector)

        LOG.info("terminate_connection, return data is: %s.",
                 fc_info)

        # This only does something if and only if the initiator_target_map
        # exists in fc_info
        fczm_utils.remove_fc_zone(fc_info)
        return fc_info

    def _delete_zone_and_remove_fc_initiators(self, wwns, host_id):
        # Get tgt_port_wwns and init_targ_map to remove zone.
        portg_id = None
        if not self.fcsan:
            self.fcsan = fczm_utils.create_lookup_service()
        if self.fcsan:
            zone_helper = fc_zone_helper.FCZoneHelper(self.fcsan,
                                                      self.client)
            (tgt_port_wwns, portg_id, init_targ_map) = (
                zone_helper.get_init_targ_map(wwns, host_id))
        else:
            (tgt_port_wwns, init_targ_map) = (
                self.client.get_init_targ_map(wwns))

        # Remove the initiators from host if need.
        if host_id:
            fc_initiators = self.client.get_host_fc_initiators(host_id)
            for wwn in wwns:
                if wwn in fc_initiators:
                    self.client.remove_fc_from_host(wwn)

        info = {'driver_volume_type': 'fibre_channel',
                'data': {'target_wwn': tgt_port_wwns,
                         'initiator_target_map': init_targ_map}}
        return info, portg_id
