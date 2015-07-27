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

import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _, _LI, _LW
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.huawei import constants
from cinder.volume.drivers.huawei import huawei_utils
from cinder.volume.drivers.huawei import rest_client
from cinder.volume import utils as volume_utils
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

huawei_opt = [
    cfg.StrOpt('cinder_huawei_conf_file',
               default='/etc/cinder/cinder_huawei_conf.xml',
               help='The configuration file for the Cinder Huawei '
                    'driver.')]

CONF = cfg.CONF
CONF.register_opts(huawei_opt)


class HuaweiBaseDriver(driver.VolumeDriver):

    def __init__(self, *args, **kwargs):
        super(HuaweiBaseDriver, self).__init__(*args, **kwargs)
        self.configuration = kwargs.get('configuration', None)
        if not self.configuration:
            msg = _('_instantiate_driver: configuration not found.')
            raise exception.InvalidInput(reason=msg)

        self.configuration.append_config_values(huawei_opt)
        self.xml_file_path = self.configuration.cinder_huawei_conf_file

    def do_setup(self, context):
        """Instantiate common class and login storage system."""
        self.restclient = rest_client.RestClient(self.configuration)
        return self.restclient.login()

    def check_for_setup_error(self):
        """Check configuration file."""
        return huawei_utils.check_conf_file(self.xml_file_path)

    def get_volume_stats(self, refresh=False):
        """Get volume status."""
        return self.restclient.update_volume_stats()

    @utils.synchronized('huawei', external=True)
    def create_volume(self, volume):
        """Create a volume."""
        pool_name = volume_utils.extract_host(volume['host'],
                                              level='pool')
        pools = self.restclient.find_all_pools()
        pool_info = self.restclient.find_pool_info(pool_name, pools)
        if not pool_info:
            msg = (_('Error in getting pool information for the pool: %s.')
                   % pool_name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        volume_name = huawei_utils.encode_name(volume['id'])
        volume_description = volume['name']
        volume_size = huawei_utils.get_volume_size(volume)

        LOG.info(_LI(
            'Create volume: %(volume)s, size: %(size)s.'),
            {'volume': volume_name,
             'size': volume_size})

        params = huawei_utils.get_lun_conf_params(self.xml_file_path)
        params['pool_id'] = pool_info['ID']
        params['volume_size'] = volume_size
        params['volume_description'] = volume_description

        # Prepare LUN parameters.
        lun_param = huawei_utils.init_lun_parameters(volume_name, params)

        # Create LUN on the array.
        lun_info = self.restclient.create_volume(lun_param)
        lun_id = lun_info['ID']

        return {'provider_location': lun_info['ID'],
                'ID': lun_id,
                'lun_info': lun_info}

    @utils.synchronized('huawei', external=True)
    def delete_volume(self, volume):
        """Delete a volume.

        Three steps:
        Firstly, remove associate from lungroup.
        Secondly, remove associate from QoS policy.
        Thirdly, remove the lun.
        """
        name = huawei_utils.encode_name(volume['id'])
        lun_id = volume.get('provider_location', None)
        LOG.info(_LI('Delete volume: %(name)s, array lun id: %(lun_id)s.'),
                 {'name': name, 'lun_id': lun_id},)
        if lun_id:
            if self.restclient.check_lun_exist(lun_id):
                self.restclient.delete_lun(lun_id)
        else:
            LOG.warning(_LW("Can't find %s on the array."), lun_id)
            return False

        return True

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        We use LUNcopy to copy a new volume from snapshot.
        The time needed increases as volume size does.
        """
        snapshotname = huawei_utils.encode_name(snapshot['id'])

        snapshot_id = snapshot.get('provider_location', None)
        if snapshot_id is None:
            snapshot_id = self.restclient.get_snapshotid_by_name(snapshotname)
            if snapshot_id is None:
                err_msg = (_(
                    'create_volume_from_snapshot: Snapshot %(name)s '
                    'does not exist.')
                    % {'name': snapshotname})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

        lun_info = self.create_volume(volume)

        tgt_lun_id = lun_info['ID']
        luncopy_name = huawei_utils.encode_name(volume['id'])

        LOG.info(_LI(
            'create_volume_from_snapshot: src_lun_id: %(src_lun_id)s, '
            'tgt_lun_id: %(tgt_lun_id)s, copy_name: %(copy_name)s.'),
            {'src_lun_id': snapshot_id,
             'tgt_lun_id': tgt_lun_id,
             'copy_name': luncopy_name})

        event_type = 'LUNReadyWaitInterval'

        wait_interval = huawei_utils.get_wait_interval(self.xml_file_path,
                                                       event_type)

        def _volume_ready():
            result = self.restclient.get_lun_info(tgt_lun_id)

            if result['HEALTHSTATUS'] == constants.STATUS_HEALTH:
                if result['RUNNINGSTATUS'] == constants.STATUS_VOLUME_READY:
                    return True
            return False

        huawei_utils.wait_for_condition(self.xml_file_path,
                                        _volume_ready,
                                        wait_interval,
                                        wait_interval * 10)

        self._copy_volume(volume, luncopy_name,
                          snapshot_id, tgt_lun_id)

        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    def create_cloned_volume(self, volume, src_vref):
        """Clone a new volume from an existing volume."""
        # Form the snapshot structure.
        snapshot = {'id': uuid.uuid4().__str__(), 'volume_id': src_vref['id']}

        # Create snapshot.
        self.create_snapshot(snapshot)

        try:
            # Create volume from snapshot.
            lun_info = self.create_volume_from_snapshot(volume, snapshot)
        finally:
            try:
                # Delete snapshot.
                self.delete_snapshot(snapshot)
            except exception.VolumeBackendAPIException:
                LOG.warning(_LW(
                    'Failure deleting the snapshot %(snapshot_id)s '
                    'of volume %(volume_id)s.'),
                    {'snapshot_id': snapshot['id'],
                     'volume_id': src_vref['id']},)

        return {'provider_location': lun_info['ID'],
                'lun_info': lun_info}

    @utils.synchronized('huawei', external=True)
    def extend_volume(self, volume, new_size):
        """Extend a volume."""
        volume_size = huawei_utils.get_volume_size(volume)
        new_volume_size = int(new_size) * units.Gi / 512
        volume_name = huawei_utils.encode_name(volume['id'])

        LOG.info(_LI(
            'Extend volume: %(volumename)s, oldsize:'
            ' %(oldsize)s  newsize: %(newsize)s.'),
            {'volumename': volume_name,
             'oldsize': volume_size,
             'newsize': new_volume_size},)

        lun_id = self.restclient.get_volume_by_name(volume_name)

        if lun_id is None:
            msg = (_(
                "Can't find lun info on the array, lun name is: %(name)s.")
                % {'name': volume_name})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        luninfo = self.restclient.extend_volume(lun_id, new_volume_size)

        return {'provider_location': luninfo['ID'],
                'lun_info': luninfo}

    @utils.synchronized('huawei', external=True)
    def create_snapshot(self, snapshot):
        snapshot_info = self.restclient.create_snapshot(snapshot)
        snapshot_id = snapshot_info['ID']
        self.restclient.active_snapshot(snapshot_id)

        return {'provider_location': snapshot_info['ID'],
                'lun_info': snapshot_info}

    @utils.synchronized('huawei', external=True)
    def delete_snapshot(self, snapshot):
        snapshotname = huawei_utils.encode_name(snapshot['id'])
        volume_name = huawei_utils.encode_name(snapshot['volume_id'])

        LOG.info(_LI(
            'stop_snapshot: snapshot name: %(snapshot)s, '
            'volume name: %(volume)s.'),
            {'snapshot': snapshotname,
             'volume': volume_name},)

        snapshot_id = snapshot.get('provider_location', None)
        if snapshot_id is None:
            snapshot_id = self.restclient.get_snapshotid_by_name(snapshotname)

        if snapshot_id is not None:
            if self.restclient.check_snapshot_exist(snapshot_id):
                self.restclient.stop_snapshot(snapshot_id)
                self.restclient.delete_snapshot(snapshot_id)
            else:
                LOG.warning(_LW("Can't find snapshot on the array."))
        else:
            LOG.warning(_LW("Can't find snapshot on the array."))
            return False

        return True

    @utils.synchronized('huawei', external=True)
    def initialize_connection_fc(self, volume, connector):
        wwns = connector['wwpns']
        volume_name = huawei_utils.encode_name(volume['id'])

        LOG.info(_LI(
            'initialize_connection_fc, initiator: %(wwpns)s,'
            ' volume name: %(volume)s.'),
            {'wwpns': wwns,
             'volume': volume_name},)

        host_name_before_hash = None
        host_name = connector['host']
        if host_name and (len(host_name) > constants.MAX_HOSTNAME_LENTH):
            host_name_before_hash = host_name
            host_name = str(hash(host_name))

        # Create hostgroup if not exist.
        host_id = self.restclient.add_host_with_check(host_name,
                                                      host_name_before_hash)

        # Add host into hostgroup.
        hostgroup_id = self.restclient.add_host_into_hostgroup(host_id)

        free_wwns = self.restclient.get_connected_free_wwns()
        LOG.info(_LI("initialize_connection_fc, the array has free wwns: %s."),
                 free_wwns)
        for wwn in wwns:
            if wwn in free_wwns:
                self.restclient.add_fc_port_to_host(host_id, wwn)

        lun_id = self.restclient.mapping_hostgroup_and_lungroup(volume_name,
                                                                hostgroup_id,
                                                                host_id)
        host_lun_id = self.restclient.find_host_lun_id(host_id, lun_id)

        tgt_port_wwns = []
        for wwn in wwns:
            tgtwwpns = self.restclient.get_fc_target_wwpns(wwn)
            if tgtwwpns:
                tgt_port_wwns.append(tgtwwpns)

        init_targ_map = {}
        for initiator in wwns:
            init_targ_map[initiator] = tgt_port_wwns

        # Return FC properties.
        info = {'driver_volume_type': 'fibre_channel',
                'data': {'target_lun': int(host_lun_id),
                         'target_discovered': True,
                         'target_wwn': tgt_port_wwns,
                         'volume_id': volume['id'],
                         'initiator_target_map': init_targ_map}, }

        LOG.info(_LI("initialize_connection_fc, return data is: %s."),
                 info)

        return info

    @utils.synchronized('huawei', external=True)
    def initialize_connection_iscsi(self, volume, connector):
        """Map a volume to a host and return target iSCSI information."""
        LOG.info(_LI('Enter initialize_connection_iscsi.'))
        initiator_name = connector['initiator']
        volume_name = huawei_utils.encode_name(volume['id'])

        LOG.info(_LI(
            'initiator name: %(initiator_name)s, '
            'volume name: %(volume)s.'),
            {'initiator_name': initiator_name,
             'volume': volume_name})

        (iscsi_iqn,
         target_ip,
         portgroup_id) = self.restclient.get_iscsi_params(self.xml_file_path,
                                                          connector)
        LOG.info(_LI('initialize_connection_iscsi, iscsi_iqn: %(iscsi_iqn)s, '
                     'target_ip: %(target_ip)s, '
                     'TargetPortGroup: %(portgroup_id)s.'),
                 {'iscsi_iqn': iscsi_iqn,
                  'target_ip': target_ip,
                  'portgroup_id': portgroup_id},)

        # Create hostgroup if not exist.
        host_name = connector['host']
        host_name_before_hash = None
        if host_name and (len(host_name) > constants.MAX_HOSTNAME_LENTH):
            host_name_before_hash = host_name
            host_name = str(hash(host_name))
        host_id = self.restclient.add_host_with_check(host_name,
                                                      host_name_before_hash)

        # Add initiator to the host.
        self.restclient.ensure_initiator_added(self.xml_file_path,
                                               initiator_name,
                                               host_id)
        hostgroup_id = self.restclient.add_host_into_hostgroup(host_id)

        # Mapping lungroup and hostgroup to view.
        lun_id = self.restclient.mapping_hostgroup_and_lungroup(volume_name,
                                                                hostgroup_id,
                                                                host_id,
                                                                portgroup_id)

        hostlun_id = self.restclient.find_host_lun_id(host_id, lun_id)

        LOG.info(_LI("initialize_connection_iscsi, host lun id is: %s."),
                 hostlun_id)

        iscsi_conf = huawei_utils.get_iscsi_conf(self.xml_file_path)
        chapinfo = self.restclient.find_chap_info(iscsi_conf,
                                                  initiator_name)
        # Return iSCSI properties.
        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = ('%s:%s' % (target_ip, '3260'))
        properties['target_iqn'] = iscsi_iqn
        properties['target_lun'] = int(hostlun_id)
        properties['volume_id'] = volume['id']

        # If use CHAP, return CHAP info.
        if chapinfo:
            chap_username, chap_password = chapinfo.split(';')
            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = chap_username
            properties['auth_password'] = chap_password

        LOG.info(_LI("initialize_connection_iscsi success. Return data: %s."),
                 properties)
        return {'driver_volume_type': 'iscsi', 'data': properties}

    @utils.synchronized('huawei', external=True)
    def terminate_connection_iscsi(self, volume, connector):
        """Delete map between a volume and a host."""
        initiator_name = connector['initiator']
        volume_name = huawei_utils.encode_name(volume['id'])
        lun_id = volume.get('provider_location', None)
        host_name = connector['host']

        LOG.info(_LI(
            'terminate_connection_iscsi: volume name: %(volume)s, '
            'initiator name: %(ini)s, '
            'lun_id: %(lunid)s.'),
            {'volume': volume_name,
             'ini': initiator_name,
             'lunid': lun_id},)

        iscsi_conf = huawei_utils.get_iscsi_conf(self.xml_file_path)
        portgroup = None
        portgroup_id = None
        left_lunnum = -1
        for ini in iscsi_conf['Initiator']:
            if ini['Name'] == initiator_name:
                for key in ini:
                    if key == 'TargetPortGroup':
                        portgroup = ini['TargetPortGroup']
                        break
        # Remove lun from lungroup.
        if lun_id:
            if self.restclient.check_lun_exist(lun_id):
                # Get lungroup id by lun id.
                lungroup_id = self.restclient.get_lungroupid_by_lunid(lun_id)
                if lungroup_id:
                    self.restclient.remove_lun_from_lungroup(lungroup_id,
                                                             lun_id)
            else:
                LOG.warning(_LW("Can't find lun on the array."))
        # Remove portgroup from mapping view if no lun left in lungroup.
        if portgroup:
            portgroup_id = self.restclient.find_tgt_port_group(portgroup)
        host_id = self.restclient.find_host(host_name)
        if host_id:
            mapping_view_name = constants.MAPPING_VIEW_PREFIX + host_id
            view_id = self.restclient.find_mapping_view(mapping_view_name)
            if view_id:
                lungroup_id = self.restclient.find_lungroup_from_map(view_id)
        if lungroup_id:
            left_lunnum = self.restclient.get_lunnum_from_lungroup(lungroup_id)

        if portgroup_id and view_id and (int(left_lunnum) <= 0):
            if self.restclient.is_portgroup_associated_to_view(view_id,
                                                               portgroup_id):
                self.restclient.delete_portgroup_mapping_view(view_id,
                                                              portgroup_id)
        if view_id and (int(left_lunnum) <= 0):
            self.restclient.remove_chap(initiator_name)

            if self.restclient.lungroup_associated(view_id, lungroup_id):
                self.restclient.delete_lungroup_mapping_view(view_id,
                                                             lungroup_id)
            self.restclient.delete_lungroup(lungroup_id)
            if self.restclient.is_initiator_associated_to_host(initiator_name):
                self.restclient.remove_iscsi_from_host(initiator_name)
            hostgroup_name = constants.HOSTGROUP_PREFIX + host_id
            hostgroup_id = self.restclient.find_hostgroup(hostgroup_name)
            if hostgroup_id:
                if self.restclient.hostgroup_associated(view_id, hostgroup_id):
                    self.restclient.delete_hostgoup_mapping_view(view_id,
                                                                 hostgroup_id)
                self.restclient.remove_host_from_hostgroup(hostgroup_id,
                                                           host_id)
                self.restclient.delete_hostgroup(hostgroup_id)
            self.restclient.remove_host(host_id)
            self.restclient.delete_mapping_view(view_id)

    def terminate_connection_fc(self, volume, connector):
        """Delete map between a volume and a host."""
        wwns = connector['wwpns']
        volume_name = huawei_utils.encode_name(volume['id'])
        lun_id = volume.get('provider_location', None)
        host_name = connector['host']
        left_lunnum = -1

        LOG.info(_LI('terminate_connection_fc: volume name: %(volume)s, '
                     'wwpns: %(wwns)s, '
                     'lun_id: %(lunid)s.'),
                 {'volume': volume_name,
                  'wwns': wwns,
                  'lunid': lun_id},)
        if lun_id:
            if self.restclient.check_lun_exist(lun_id):
                # Get lungroup id by lun id.
                lungroup_id = self.restclient.get_lungroupid_by_lunid(lun_id)
                if not lungroup_id:
                    LOG.info(_LI("Can't find lun in lungroup."))
                else:
                    self.restclient.remove_lun_from_lungroup(lungroup_id,
                                                             lun_id)
            else:
                LOG.warning(_LW("Can't find lun on the array."))
        tgt_port_wwns = []
        for wwn in wwns:
            tgtwwpns = self.restclient.get_fc_target_wwpns(wwn)
            if tgtwwpns:
                tgt_port_wwns.append(tgtwwpns)

        init_targ_map = {}
        for initiator in wwns:
            init_targ_map[initiator] = tgt_port_wwns
        host_id = self.restclient.find_host(host_name)
        if host_id:
            mapping_view_name = constants.MAPPING_VIEW_PREFIX + host_id
            view_id = self.restclient.find_mapping_view(mapping_view_name)
            if view_id:
                lungroup_id = self.restclient.find_lungroup_from_map(view_id)
        if lungroup_id:
            left_lunnum = self.restclient.get_lunnum_from_lungroup(lungroup_id)
        if int(left_lunnum) > 0:
            info = {'driver_volume_type': 'fibre_channel',
                    'data': {}}
        else:
            info = {'driver_volume_type': 'fibre_channel',
                    'data': {'target_wwn': tgt_port_wwns,
                             'initiator_target_map': init_targ_map}, }

        return info

    def migrate_volume(self, context, volume, host):
        return (False, None)

    def create_export(self, context, volume):
        """Export a volume."""
        pass

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass

    def _copy_volume(self, volume, copy_name, src_lun, tgt_lun):
        luncopy_id = self.restclient.create_luncopy(copy_name,
                                                    src_lun, tgt_lun)
        event_type = 'LUNcopyWaitInterval'
        wait_interval = huawei_utils.get_wait_interval(self.xml_file_path,
                                                       event_type)

        try:
            self.restclient.start_luncopy(luncopy_id)

            def _luncopy_complete():
                luncopy_info = self.restclient.get_luncopy_info(luncopy_id)
                if luncopy_info['status'] == constants.STATUS_LUNCOPY_READY:
                    # luncopy_info['status'] means for the running status of
                    # the luncopy. If luncopy_info['status'] is equal to '40',
                    # this luncopy is completely ready.
                    return True
                elif luncopy_info['state'] != constants.STATUS_HEALTH:
                    # luncopy_info['state'] means for the healthy status of the
                    # luncopy. If luncopy_info['state'] is not equal to '1',
                    # this means that an error occurred during the LUNcopy
                    # operation and we should abort it.
                    err_msg = (_(
                        'An error occurred during the LUNcopy operation. '
                        'LUNcopy name: %(luncopyname)s. '
                        'LUNcopy status: %(luncopystatus)s. '
                        'LUNcopy state: %(luncopystate)s.')
                        % {'luncopyname': luncopy_id,
                           'luncopystatus': luncopy_info['status'],
                           'luncopystate': luncopy_info['state']},)
                    LOG.error(err_msg)
                    raise exception.VolumeBackendAPIException(data=err_msg)
            huawei_utils.wait_for_condition(self.xml_file_path,
                                            _luncopy_complete,
                                            wait_interval)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.restclient.delete_luncopy(luncopy_id)
                self.delete_volume(volume)

        self.restclient.delete_luncopy(luncopy_id)


class Huawei18000ISCSIDriver(HuaweiBaseDriver, driver.ISCSIDriver):
    """ISCSI driver for Huawei OceanStor 18000 storage arrays.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Provide Huawei OceanStor 18000 storage volume driver.
    """

    VERSION = "1.1.1"

    def __init__(self, *args, **kwargs):
        super(Huawei18000ISCSIDriver, self).__init__(*args, **kwargs)

    def get_volume_stats(self, refresh=False):
        """Get volume status."""
        data = HuaweiBaseDriver.get_volume_stats(self, refresh=False)
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['storage_protocol'] = 'iSCSI'
        data['driver_version'] = self.VERSION
        data['vendor_name'] = 'Huawei'
        return data

    def initialize_connection(self, volume, connector):
        return HuaweiBaseDriver.initialize_connection_iscsi(self,
                                                            volume,
                                                            connector)

    def terminate_connection(self, volume, connector, **kwargs):
        return HuaweiBaseDriver.terminate_connection_iscsi(self,
                                                           volume,
                                                           connector)


class Huawei18000FCDriver(HuaweiBaseDriver, driver.FibreChannelDriver):
    """FC driver for Huawei OceanStor 18000 storage arrays.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Provide Huawei OceanStor 18000 storage volume driver.
    """

    VERSION = "1.1.1"

    def __init__(self, *args, **kwargs):
        super(Huawei18000FCDriver, self).__init__(*args, **kwargs)

    def get_volume_stats(self, refresh=False):
        """Get volume status."""
        data = HuaweiBaseDriver.get_volume_stats(self, refresh=False)
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['storage_protocol'] = 'FC'
        data['driver_version'] = self.VERSION
        data['verdor_name'] = 'Huawei'
        return data

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        return HuaweiBaseDriver.initialize_connection_fc(self,
                                                         volume,
                                                         connector)

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        return HuaweiBaseDriver.terminate_connection_fc(self,
                                                        volume,
                                                        connector)
