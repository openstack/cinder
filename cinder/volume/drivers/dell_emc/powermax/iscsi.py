# Copyright (c) 2017-2018 Dell Inc. or its subsidiaries.
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
"""
ISCSI Drivers for Dell EMC PowerMax/PowerMax/VMAX arrays based on REST.

"""
from oslo_log import log as logging
from oslo_utils import strutils
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume.drivers.dell_emc.powermax import common
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)


@interface.volumedriver
class PowerMaxISCSIDriver(san.SanISCSIDriver):
    """ISCSI Drivers for PowerMax using Rest.

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
              - VMAX2/VMAX3 iscsi multipath support (iscsi only)
              https://blueprints.launchpad.net/cinder/+spec/vmax-iscsi-multipath
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
        3.1.0 - Support for replication groups (Tiramisu)
              - Deprecate backend xml configuration
              - Support for async replication (vmax-replication-enhancements)
              - Support for SRDF/Metro (vmax-replication-enhancements)
              - Support for manage/unmanage snapshots
                (vmax-manage-unmanage-snapshot)
              - Support for revert to volume snapshot
        3.2.0 - Support for retyping replicated volumes (bp
                vmax-retype-replicated-volumes)
              - Support for multiattach volumes (bp vmax-allow-multi-attach)
              - Support for list manageable volumes and snapshots
                (bp/vmax-list-manage-existing)
              - Fix for SSL verification/cert application (bug #1772924)
              - Log VMAX metadata of a volume (bp vmax-metadata)
              - Fix for get-pools command (bug #1784856)
        4.0.0 - Fix for initiator retrieval and short hostname unmapping
                (bugs #1783855 #1783867)
              - Fix for HyperMax OS Upgrade Bug (bug #1790141)
              - Support for failover to secondary Unisphere
                (bp/vmax-unisphere-failover)
              - Rebrand from VMAX to PowerMax(bp/vmax-powermax-rebrand)
              - Change from 84 to 90 REST endpoints (bug #1808539)
              - Fix for PowerMax OS replication settings (bug #1812685)
              - Support for storage-assisted in-use retype
                (bp/powermax-storage-assisted-inuse-retype)
        4.0.1 - PowerMax OS Metro formatted volumes fix (bug #1829876)
        4.0.2 - Volume group delete failure (bug #1853589)
        4.0.3 - Legacy volume not found fix (#1867163)
        4.0.4 - Fix to enable legacy volumes to live migrate (#1867163)
    """

    VERSION = "4.0.4"

    # ThirdPartySystems wiki
    CI_WIKI_NAME = "EMC_VMAX_CI"

    def __init__(self, *args, **kwargs):

        super(PowerMaxISCSIDriver, self).__init__(*args, **kwargs)
        self.active_backend_id = kwargs.get('active_backend_id', None)
        self.common = (
            common.PowerMaxCommon(
                'iSCSI',
                self.VERSION,
                configuration=self.configuration,
                active_backend_id=self.active_backend_id))

    @staticmethod
    def get_driver_options():
        return common.powermax_opts

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a PowerMax/VMAX volume.

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
        """Deletes a PowerMax/VMAX volume.

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

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        the format of the driver data is defined in smis_get_iscsi_properties.
        Example return value:

        .. code-block:: default

            {
                'driver_volume_type': 'iscsi',
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': '12345678-1234-4321-1234-123456789012'
                }
            }

        Example return value (multipath is enabled):

        .. code-block:: default

            {
                'driver_volume_type': 'iscsi',
                'data': {
                    'target_discovered': True,
                    'target_iqns': ['iqn.2010-10.org.openstack:volume-00001',
                                    'iqn.2010-10.org.openstack:volume-00002'],
                    'target_portals': ['127.0.0.1:3260', '127.0.1.1:3260'],
                    'target_luns': [1, 1]
                }
            }

        :param volume: the cinder volume object
        :param connector: the connector object
        :returns: dict -- the iscsi dict
        """
        device_info = self.common.initialize_connection(
            volume, connector)
        if device_info:
            return self.get_iscsi_dict(device_info, volume)
        else:
            return {}

    def get_iscsi_dict(self, device_info, volume):
        """Populate iscsi dict to pass to nova.

        :param device_info: device info dict
        :param volume: volume object
        :returns: iscsi dict
        """
        metro_ip_iqn, metro_host_lun = None, None
        try:
            ip_and_iqn = device_info['ip_and_iqn']
            is_multipath = device_info['is_multipath']
            host_lun_id = device_info['hostlunid']
        except KeyError as e:
            exception_message = (_("Cannot get iSCSI ipaddresses, multipath "
                                   "flag, or hostlunid. Exception is %(e)s.")
                                 % {'e': six.text_type(e)})
            raise exception.VolumeBackendAPIException(
                message=exception_message)

        if device_info.get('metro_ip_and_iqn'):
            LOG.debug("Volume is Metro device...")
            metro_ip_iqn = device_info['metro_ip_and_iqn']
            metro_host_lun = device_info['metro_hostlunid']

        iscsi_properties = self.vmax_get_iscsi_properties(
            volume, ip_and_iqn, is_multipath, host_lun_id,
            metro_ip_iqn, metro_host_lun)

        LOG.info("iSCSI properties are: %(props)s",
                 {'props': strutils.mask_dict_password(iscsi_properties)})
        return {'driver_volume_type': 'iscsi',
                'data': iscsi_properties}

    def vmax_get_iscsi_properties(self, volume, ip_and_iqn,
                                  is_multipath, host_lun_id,
                                  metro_ip_iqn, metro_host_lun):
        """Gets iscsi configuration.

        We ideally get saved information in the volume entity, but fall back
        to discovery if need be. Discovery may be completely removed in future
        The properties are:
        :target_discovered:    boolean indicating whether discovery was used
        :target_iqn:    the IQN of the iSCSI target
        :target_portal:    the portal of the iSCSI target
        :target_lun:    the lun of the iSCSI target
        :volume_id:    the UUID of the volume
        :auth_method:, :auth_username:, :auth_password:
        the authentication details. Right now, either auth_method is not
        present meaning no authentication, or auth_method == `CHAP`
        meaning use CHAP with the specified credentials.

        :param volume: the cinder volume object
        :param ip_and_iqn: list of ip and iqn dicts
        :param is_multipath: flag for multipath
        :param host_lun_id: the host lun id of the device
        :param metro_ip_iqn: metro remote device ip and iqn, if applicable
        :param metro_host_lun: metro remote host lun, if applicable
        :returns: properties
        """
        properties = {}
        populate_plurals = False
        if len(ip_and_iqn) > 1 and is_multipath:
            populate_plurals = True
        elif len(ip_and_iqn) == 1 and is_multipath and metro_ip_iqn:
            populate_plurals = True
        if populate_plurals:
            properties['target_portals'] = ([t['ip'] + ":3260" for t in
                                             ip_and_iqn])
            properties['target_iqns'] = ([t['iqn'].split(",")[0] for t in
                                          ip_and_iqn])
            properties['target_luns'] = [host_lun_id] * len(ip_and_iqn)
        if metro_ip_iqn:
            LOG.info("Volume %(vol)s is metro-enabled - "
                     "adding additional attachment information",
                     {'vol': volume.name})
            properties['target_portals'].extend(([t['ip'] + ":3260" for t in
                                                 metro_ip_iqn]))
            properties['target_iqns'].extend(([t['iqn'].split(",")[0] for t in
                                              metro_ip_iqn]))
            properties['target_luns'].extend(
                [metro_host_lun] * len(metro_ip_iqn))
        properties['target_discovered'] = True
        properties['target_iqn'] = ip_and_iqn[0]['iqn'].split(",")[0]
        properties['target_portal'] = ip_and_iqn[0]['ip'] + ":3260"
        properties['target_lun'] = host_lun_id
        properties['volume_id'] = volume.id

        LOG.info("ISCSI properties: %(properties)s.",
                 {'properties': properties})
        LOG.info("ISCSI volume is: %(volume)s.", {'volume': volume})

        if self.configuration.safe_get('use_chap_auth'):
            LOG.info("Chap authentication enabled.")
            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = self.configuration.safe_get(
                'chap_username')
            properties['auth_password'] = self.configuration.safe_get(
                'chap_password')

        return properties

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector.

        :param volume: the volume object
        :param connector: the connector object
        """
        self.common.terminate_connection(volume, connector)

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
        data['storage_protocol'] = 'iSCSI'
        data['driver_version'] = self.VERSION
        self._stats = data

    def manage_existing(self, volume, external_ref):
        """Manages an existing PowerMax/VMAX Volume (import to Cinder).

        Renames the Volume to match the expected name for the volume.
        Also need to consider things like QoS, Emulation, account/tenant.
        """
        return self.common.manage_existing(volume, external_ref)

    def manage_existing_get_size(self, volume, external_ref):
        """Return size of an existing PowerMax/VMAX volume to manage_existing.

        :param self: reference to class
        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: size of the volume in GB
        """
        return self.common.manage_existing_get_size(volume, external_ref)

    def unmanage(self, volume):
        """Export PowerMax/VMAX volume from Cinder.

        Leave the volume intact on the backend array.
        """
        return self.common.unmanage(volume)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Manage an existing PowerMax/VMAX Snapshot (import to Cinder).

        Renames the Snapshot to prefix it with OS- to indicate
        it is managed by Cinder.

        :param snapshot: the snapshot object
        :param existing_ref: the snapshot name on the backend PowerMax/VMAX
        :returns: model_update
        """
        return self.common.manage_existing_snapshot(snapshot, existing_ref)

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return the size of the source volume for manage-existing-snapshot.

        :param snapshot: the snapshot object
        :param existing_ref: the snapshot name on the backend PowerMax/VMAX
        :returns: size of the source volume in GB
        """
        return self.common.manage_existing_snapshot_get_size(snapshot)

    def unmanage_snapshot(self, snapshot):
        """Export PowerMax/VMAX Snapshot from Cinder.

        Leaves the snapshot intact on the backend PowerMax/VMAX.

        :param snapshot: the snapshot object
        """
        self.common.unmanage_snapshot(snapshot)

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """Lists all manageable volumes.

        :param cinder_volumes: List of currently managed Cinder volumes.
                               Unused in driver.
        :param marker: Begin returning volumes that appear later in the volume
                       list than that represented by this reference.
        :param limit: Maximum number of volumes to return. Default=1000.
        :param offset: Number of volumes to skip after marker.
        :param sort_keys: Results sort key. Valid keys: size, reference.
        :param sort_dirs: Results sort direction. Valid dirs: asc, desc.
        :return: List of dicts containing all manageable volumes.
        """
        return self.common.get_manageable_volumes(marker, limit, offset,
                                                  sort_keys, sort_dirs)

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """Lists all manageable snapshots.

        :param cinder_snapshots: List of currently managed Cinder snapshots.
                                 Unused in driver.
        :param marker: Begin returning volumes that appear later in the
                       snapshot list than that represented by this reference.
        :param limit: Maximum number of snapshots to return. Default=1000.
        :param offset: Number of snapshots to skip after marker.
        :param sort_keys: Results sort key. Valid keys: size, reference.
        :param sort_dirs: Results sort direction. Valid dirs: asc, desc.
        :return: List of dicts containing all manageable snapshots.
        """
        return self.common.get_manageable_snapshots(marker, limit, offset,
                                                    sort_keys, sort_dirs)

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
        :returns: model_update
        """
        return self.common.create_group(context, group)

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
        :param group_snapshot: the group snapshot
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
        """Updates LUNs in group.

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
        :param group: the consistency group object to be created
        :param volumes: volumes in the group
        :param group_snapshot: the source volume group snapshot
        :param snapshots: snapshots of the source volumes
        :param source_group: the dictionary of a volume group as source.
        :param source_vols: a list of volume dictionaries in the source_group.
        """
        return self.common.create_group_from_src(
            context, group, volumes, group_snapshot, snapshots, source_group,
            source_vols)

    def enable_replication(self, context, group, volumes):
        """Enable replication for a group.

        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :returns: model_update, None
        """
        return self.common.enable_replication(context, group, volumes)

    def disable_replication(self, context, group, volumes):
        """Disable replication for a group.

        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :returns: model_update, None
        """
        return self.common.disable_replication(context, group, volumes)

    def failover_replication(self, context, group, volumes,
                             secondary_backend_id=None):
        """Failover replication for a group.

        :param context: the context
        :param group: the group object
        :param volumes: the list of volumes
        :param secondary_backend_id: the secondary backend id - default None
        :returns: model_update, vol_model_updates
        """
        return self.common.failover_replication(
            context, group, volumes, secondary_backend_id)

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert volume to snapshot

        :param context: the context
        :param volume: the cinder volume object
        :param snapshot: the cinder snapshot object
        """
        self.common.revert_to_snapshot(volume, snapshot)
