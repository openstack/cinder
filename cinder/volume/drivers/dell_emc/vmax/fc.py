# Copyright (c) 2017 Dell Inc. or its subsidiaries.
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

import ast

from oslo_log import log as logging

from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.dell_emc.vmax import common
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)


@interface.volumedriver
class VMAXFCDriver(driver.FibreChannelDriver):
    """FC Drivers for VMAX using REST.

    Version history:

    .. code-block:: none

        1.0.0 - Initial driver
        1.1.0 - Multiple pools and thick/thin provisioning,
                performance enhancement.
        2.0.0 - Add driver requirement functions
        2.1.0 - Add consistency group functions
        2.1.1 - Fixed issue with mismatched config (bug #1442376)
        2.1.2 - Clean up failed clones (bug #1440154)
        2.1.3 - Fixed a problem with FAST support (bug #1435069)
        2.2.0 - Add manage/unmanage
        2.2.1 - Support for SE 8.0.3
        2.2.2 - Update Consistency Group
        2.2.3 - Pool aware scheduler(multi-pool) support
        2.2.4 - Create CG from CG snapshot
        2.3.0 - Name change for MV and SG for FAST (bug #1515181)
              - Fix for randomly choosing port group. (bug #1501919)
              - get_short_host_name needs to be called in find_device_number
                (bug #1520635)
              - Proper error handling for invalid SLOs (bug #1512795)
              - Extend Volume for VMAX3, SE8.1.0.3
              https://blueprints.launchpad.net/cinder/+spec/vmax3-extend-volume
              - Incorrect SG selected on an attach (#1515176)
              - Cleanup Zoning (bug #1501938)  NOTE: FC only
              - Last volume in SG fix
              - _remove_last_vol_and_delete_sg is not being called
                for VMAX3 (bug #1520549)
              - necessary updates for CG changes (#1534616)
              - Changing PercentSynced to CopyState (bug #1517103)
              - Getting iscsi ip from port in existing masking view
              - Replacement of EMCGetTargetEndpoints api (bug #1512791)
              - VMAX3 snapvx improvements (bug #1522821)
              - Operations and timeout issues (bug #1538214)
        2.4.0 - EMC VMAX - locking SG for concurrent threads (bug #1554634)
              - SnapVX licensing checks for VMAX3 (bug #1587017)
              - VMAX oversubscription Support (blueprint vmax-oversubscription)
              - QoS support (blueprint vmax-qos)
        2.5.0 - Attach and detach snapshot (blueprint vmax-attach-snapshot)
              - MVs and SGs not reflecting correct protocol (bug #1640222)
              - Storage assisted volume migration via retype
                (bp vmax-volume-migration)
              - Support for compression on All Flash
              - Volume replication 2.1 (bp add-vmax-replication)
              - rename and restructure driver (bp vmax-rename-dell-emc)
        3.0.0 - REST based driver
              - Retype (storage-assisted migration)
              - QoS support
              - Support for compression on All Flash
              - Support for volume replication
              - Support for live migration
              - Support for Generic Volume Group
        backport from 3.3.0
              - Fix for initiator retrieval and short hostname unmapping
                (bugs #1783855 #1783867)
    """

    VERSION = "3.0.0"

    # ThirdPartySystems wiki
    CI_WIKI_NAME = "EMC_VMAX_CI"

    def __init__(self, *args, **kwargs):

        super(VMAXFCDriver, self).__init__(*args, **kwargs)
        self.active_backend_id = kwargs.get('active_backend_id', None)
        self.common = common.VMAXCommon(
            'FC',
            self.VERSION,
            configuration=self.configuration,
            active_backend_id=self.active_backend_id)
        self.zonemanager_lookup_service = fczm_utils.create_lookup_service()

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a VMAX volume.

        :param volume: the cinder volume object
        :returns: provider location dict
        """
        return self.common.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        :param volume: the cinder volume object
        :param snapshot: the cinder snapshot object
        :returns: provider location dict
        """
        return self.common.create_volume_from_snapshot(
            volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume.

        :param volume: the cinder volume object
        :param src_vref: the source volume reference
        :returns: provider location dict
        """
        return self.common.create_cloned_volume(volume, src_vref)

    def delete_volume(self, volume):
        """Deletes a VMAX volume.

        :param volume: the cinder volume object
        """
        self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot.

        :param snapshot: the cinder snapshot object
        :returns: provider location dict
        """
        src_volume = snapshot.volume
        return self.common.create_snapshot(snapshot, src_volume)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot.

        :param snapshot: the cinder snapshot object
        """
        src_volume = snapshot.volume
        self.common.delete_snapshot(snapshot, src_volume)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume.

        :param context: the context
        :param volume: the cinder volume object
        """
        pass

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume.

        :param context: the context
        :param volume: the cinder volume object
        :param connector: the connector object
        """
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume.

        :param context: the context
        :param volume: the cinder volume object
        """
        pass

    @staticmethod
    def check_for_export(context, volume_id):
        """Make sure volume is exported.

        :param context: the context
        :param volume_id: the volume id
        """
        pass

    @fczm_utils.add_fc_zone
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        Example return values:
            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '1234567890123',
                }
            }

            or

            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                }
            }
        :param volume: the cinder volume object
        :param connector: the connector object
        :returns: dict -- the target_wwns and initiator_target_map
        """
        device_info = self.common.initialize_connection(
            volume, connector)
        return self.populate_data(device_info, volume, connector)

    def populate_data(self, device_info, volume, connector):
        """Populate data dict.

        Add relevant data to data dict, target_lun, target_wwn and
        initiator_target_map.
        :param device_info: device_info
        :param volume: the volume object
        :param connector: the connector object
        :returns: dict -- the target_wwns and initiator_target_map
        """
        device_number = device_info['hostlunid']
        target_wwns, init_targ_map = self._build_initiator_target_map(
            volume, connector)

        data = {'driver_volume_type': 'fibre_channel',
                'data': {'target_lun': device_number,
                         'target_discovered': True,
                         'target_wwn': target_wwns,
                         'initiator_target_map': init_targ_map}}

        LOG.debug("Return FC data for zone addition: %(data)s.",
                  {'data': data})

        return data

    @fczm_utils.remove_fc_zone
    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector.

        Return empty data if other volumes are in the same zone.
        The FibreChannel ZoneManager doesn't remove zones
        if there isn't an initiator_target_map in the
        return of terminate_connection.

        :param volume: the volume object
        :param connector: the connector object
        :returns: dict -- the target_wwns and initiator_target_map if the
            zone is to be removed, otherwise empty
        """
        data = {'driver_volume_type': 'fibre_channel', 'data': {}}
        zoning_mappings = {}
        if connector:
            zoning_mappings = self._get_zoning_mappings(volume, connector)

        if zoning_mappings:
            self.common.terminate_connection(volume, connector)
            data = self._cleanup_zones(zoning_mappings)
        return data

    def _get_zoning_mappings(self, volume, connector):
        """Get zoning mappings by building up initiator/target map.

        :param volume: the volume object
        :param connector: the connector object
        :returns: dict -- the target_wwns and initiator_target_map if the
            zone is to be removed, otherwise empty
        """
        loc = volume.provider_location
        name = ast.literal_eval(loc)
        host = self.common.utils.get_host_short_name(connector['host'])
        try:
            array = name['array']
            device_id = name['device_id']
        except KeyError:
            array = name['keybindings']['SystemName'].split('+')[1].strip('-')
            device_id = name['keybindings']['DeviceID']
        LOG.debug("Start FC detach process for volume: %(volume)s.",
                  {'volume': volume.name})

        masking_views = self.common.get_masking_views_from_volume(
            array, device_id, host)
        if masking_views:
            portgroup = (
                self.common.get_port_group_from_masking_view(
                    array, masking_views[0]))
            initiator_group = (
                self.common.get_initiator_group_from_masking_view(
                    array, masking_views[0]))

            LOG.debug("Found port group: %(portGroup)s "
                      "in masking view %(maskingView)s.",
                      {'portGroup': portgroup,
                       'maskingView': masking_views[0]})
            # Map must be populated before the terminate_connection
            target_wwns, init_targ_map = self._build_initiator_target_map(
                volume, connector)
            zoning_mappings = {'port_group': portgroup,
                               'initiator_group': initiator_group,
                               'target_wwns': target_wwns,
                               'init_targ_map': init_targ_map,
                               'array': array}
        else:
            LOG.warning("Volume %(volume)s is not in any masking view.",
                        {'volume': volume.name})
            zoning_mappings = {}
        return zoning_mappings

    def _cleanup_zones(self, zoning_mappings):
        """Cleanup zones after terminate connection.

        :param zoning_mappings: zoning mapping dict
        :returns: data - dict
        """
        LOG.debug("Looking for masking views still associated with "
                  "Port Group %s.", zoning_mappings['port_group'])
        masking_views = self.common.get_common_masking_views(
            zoning_mappings['array'], zoning_mappings['port_group'],
            zoning_mappings['initiator_group'])

        if masking_views:
            LOG.debug("Found %(numViews)d MaskingViews.",
                      {'numViews': len(masking_views)})
            data = {'driver_volume_type': 'fibre_channel', 'data': {}}
        else:  # no masking views found
            LOG.debug("No MaskingViews were found. Deleting zone.")
            data = {'driver_volume_type': 'fibre_channel',
                    'data': {'target_wwn': zoning_mappings['target_wwns'],
                             'initiator_target_map':
                                 zoning_mappings['init_targ_map']}}

            LOG.debug("Return FC data for zone removal: %(data)s.",
                      {'data': data})

        return data

    def _build_initiator_target_map(self, volume, connector):
        """Build the target_wwns and the initiator target map.

        :param volume: the cinder volume object
        :param connector: the connector object
        :returns: target_wwns -- list, init_targ_map -- dict
        """
        target_wwns, init_targ_map = [], {}
        initiator_wwns = connector['wwpns']
        fc_targets = self.common.get_target_wwns_from_masking_view(
            volume, connector)

        if self.zonemanager_lookup_service:
            mapping = (
                self.zonemanager_lookup_service.
                get_device_mapping_from_network(initiator_wwns, fc_targets))
            for entry in mapping:
                map_d = mapping[entry]
                target_wwns.extend(map_d['target_port_wwn_list'])
                for initiator in map_d['initiator_port_wwn_list']:
                    init_targ_map[initiator] = map_d['target_port_wwn_list']
        else:  # No lookup service, pre-zoned case.
            target_wwns = fc_targets
            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwns

        return list(set(target_wwns)), init_targ_map

    def extend_volume(self, volume, new_size):
        """Extend an existing volume.

        :param volume: the cinder volume object
        :param new_size: the required new size
        """
        self.common.extend_volume(volume, new_size)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        :param refresh: boolean -- If True, run update the stats first.
        :returns: dict -- the stats dict
        """
        if refresh:
            self.update_volume_stats()

        return self._stats

    def update_volume_stats(self):
        """Retrieve stats info from volume group."""
        LOG.debug("Updating volume stats")
        data = self.common.update_volume_stats()
        data['storage_protocol'] = 'FC'
        data['driver_version'] = self.VERSION
        self._stats = data

    def manage_existing(self, volume, external_ref):
        """Manages an existing VMAX Volume (import to Cinder).

        Renames the Volume to match the expected name for the volume.
        Also need to consider things like QoS, Emulation, account/tenant.
        :param volume: the volume object
        :param external_ref: the reference for the VMAX volume
        :returns: model_update
        """
        return self.common.manage_existing(volume, external_ref)

    def manage_existing_get_size(self, volume, external_ref):
        """Return size of an existing VMAX volume to manage_existing.

        :param self: reference to class
        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: size of the volume in GB
        """
        return self.common.manage_existing_get_size(volume, external_ref)

    def unmanage(self, volume):
        """Export VMAX volume from Cinder.

        Leave the volume intact on the backend array.
        """
        return self.common.unmanage(volume)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Migrate volume to another host using retype.

        :param ctxt: context
        :param volume: the volume object including the volume_type_id
        :param new_type: the new volume type.
        :param diff: difference between old and new volume types.
            Unused in driver.
        :param host: the host dict holding the relevant
            target(destination) information
        :returns: boolean -- True if retype succeeded, False if error
        """
        return self.common.retype(volume, new_type, host)

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failover volumes to a secondary host/ backend.

        :param context: the context
        :param volumes: the list of volumes to be failed over
        :param secondary_id: the backend to be failed over to, is 'default'
                             if fail back
        :param groups: replication groups
        :returns: secondary_id, volume_update_list, group_update_list
        """
        return self.common.failover_host(volumes, secondary_id, groups)

    def create_group(self, context, group):
        """Creates a generic volume group.

        :param context: the context
        :param group: the group object
        """
        self.common.create_group(context, group)

    def delete_group(self, context, group, volumes):
        """Deletes a generic volume group.

        :param context: the context
        :param group: the group object
        :param volumes: the member volumes
        """
        return self.common.delete_group(
            context, group, volumes)

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group snapshot.

        :param context: the context
        :param group_snapshot: the grouop snapshot
        :param snapshots: snapshots list
        """
        return self.common.create_group_snapshot(context,
                                                 group_snapshot, snapshots)

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group snapshot.

        :param context: the context
        :param group_snapshot: the grouop snapshot
        :param snapshots: snapshots list
        """
        return self.common.delete_group_snapshot(context,
                                                 group_snapshot, snapshots)

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Updates LUNs in generic volume group.

        :param context: the context
        :param group: the group object
        :param add_volumes: flag for adding volumes
        :param remove_volumes: flag for removing volumes
        """
        return self.common.update_group(group, add_volumes,
                                        remove_volumes)

    def create_group_from_src(
            self, context, group, volumes, group_snapshot=None,
            snapshots=None, source_group=None, source_vols=None):
        """Creates the volume group from source.

        :param context: the context
        :param group: the group object to be created
        :param volumes: volumes in the group
        :param group_snapshot: the source volume group snapshot
        :param snapshots: snapshots of the source volumes
        :param source_group: the dictionary of a volume group as source.
        :param source_vols: a list of volume dictionaries in the source_group.
        """
        return self.common.create_group_from_src(
            context, group, volumes, group_snapshot, snapshots, source_group,
            source_vols)
