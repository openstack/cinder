# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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
from cinder import coordination
from cinder.volume import driver
from cinder.volume.drivers.san import san


class PowerMaxNVMEBaseDriver(san.SanDriver, driver.BaseVD):

    driver_prefix = 'powermax'

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        pass

    def remove_export(self, context, volume):
        pass

    @staticmethod
    def check_for_export(context, volume_id):
        """Make sure volume is exported.

        :param context: the context
        :param volume_id: the volume id
        """
        pass

    def check_for_setup_error(self):
        """Validate the Unisphere version."""
        pass

    def create_volume(self, volume):
        """Creates a PowerMax volume.

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
        """Deletes a PowerMax volume.

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

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info."""
        pass

    @coordination.synchronized('{self.driver_prefix}-{volume.id}')
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

    def manage_existing(self, volume, existing_ref):
        """Manages an existing PowerMax Volume (import to Cinder).

        Renames the Volume to match the expected name for the volume.
        Also need to consider things like QoS, Emulation, account/tenant.
        """
        return self.common.manage_existing(volume, existing_ref)

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of an existing PowerMax volume to manage_existing.

        :param self: reference to class
        :param volume: the volume object including the volume_type_id
        :param external_ref: reference to the existing volume
        :returns: size of the volume in GB
        """
        return self.common.manage_existing_get_size(volume, existing_ref)

    def unmanage(self, volume):
        """Export PowerMax volume from Cinder.

        Leave the volume intact on the backend array.
        """
        return self.common.unmanage(volume)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Manage an existing PowerMax Snapshot (import to Cinder).

        Renames the Snapshot to prefix it with OS- to indicate
        it is managed by Cinder.

        :param snapshot: the snapshot object
        :param existing_ref: the snapshot name on the backend PowerMax
        :returns: model_update
        """
        return self.common.manage_existing_snapshot(snapshot, existing_ref)

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return the size of the source volume for manage-existing-snapshot.

        :param snapshot: the snapshot object
        :param existing_ref: the snapshot name on the backend PowerMax
        :returns: size of the source volume in GB
        """
        return self.common.manage_existing_snapshot_get_size(snapshot)

    def unmanage_snapshot(self, snapshot):
        """Export PowerMax Snapshot from Cinder.

        Leaves the snapshot intact on the backend PowerMax.

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
        :returns: List of dicts containing all manageable volumes.
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
        :returns: List of dicts containing all manageable snapshots.
        """
        return self.common.get_manageable_snapshots(marker, limit, offset,
                                                    sort_keys, sort_dirs)

    def retype(self, context, volume, new_type, diff, host):
        """Migrate volume to another host using retype.

        :param context: context
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
        active_backend_id, volume_update_list, group_update_list = (
            self.common.failover(volumes, secondary_id, groups))
        self.common.failover_completed(secondary_id, False)
        return active_backend_id, volume_update_list, group_update_list

    def failover(self, context, volumes, secondary_id=None, groups=None):
        """Like failover but for a host that is clustered."""
        return self.common.failover(volumes, secondary_id, groups)

    def failover_completed(self, context, active_backend_id=None):
        """This method is called after failover for clustered backends."""
        return self.common.failover_completed(active_backend_id, True)

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

    @classmethod
    def clean_volume_file_locks(cls, volume_id):
        coordination.synchronized_remove(f'{cls.driver_prefix}-{volume_id}')
