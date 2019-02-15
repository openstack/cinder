#    Copyright 2012 OpenStack Foundation
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

from oslo_utils import timeutils

from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit.brick import fake_lvm
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers import lvm
from cinder.volume import utils as vol_utils
from cinder.zonemanager import utils as fczm_utils


# TODO(e0ne): inherit from driver.VolumeDriver and fix unit-tests
class FakeLoggingVolumeDriver(lvm.LVMVolumeDriver):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        super(FakeLoggingVolumeDriver, self).__init__(
            execute=self.fake_execute, *args, **kwargs)

        self.backend_name = 'fake'
        self.protocol = 'fake'
        self.vg = fake_lvm.FakeBrickLVM('cinder-volumes', False,
                                        None, 'default',
                                        self.fake_execute)

    @utils.trace_method
    def check_for_setup_error(self):
        """No setup necessary in fake mode."""
        pass

    @utils.trace_method
    def create_volume(self, volume):
        """Creates a volume."""
        super(FakeLoggingVolumeDriver, self).create_volume(volume)
        model_update = {}
        try:
            if (volume.volume_type and volume.volume_type.extra_specs and
                    vol_utils.is_replicated_spec(
                        volume.volume_type.extra_specs)):
                # Sets the new volume's replication_status to disabled
                model_update['replication_status'] = (
                    fields.ReplicationStatus.DISABLED)
        except exception.VolumeTypeNotFound:
            pass
        if model_update:
            return model_update

    @utils.trace_method
    def delete_volume(self, volume):
        pass

    @utils.trace_method
    def create_snapshot(self, snapshot):
        pass

    @utils.trace_method
    def delete_snapshot(self, snapshot):
        pass

    @utils.trace_method
    def ensure_export(self, context, volume):
        pass

    @utils.trace_method
    def create_export(self, context, volume, connector):
        pass

    @utils.trace_method
    def remove_export(self, context, volume):
        pass

    @utils.trace_method
    def create_export_snapshot(self, context, snapshot):
        pass

    @utils.trace_method
    def remove_export_snapshot(self, context, snapshot):
        pass

    @utils.trace_method
    def terminate_connection_snapshot(self, snapshot, connector):
        pass

    @utils.trace_method
    def create_cloned_volume(self, volume, src_vol):
        pass

    @utils.trace_method
    def create_volume_from_snapshot(self, volume, snapshot):
        pass

    @utils.trace_method
    def initialize_connection(self, volume, connector):
        # NOTE(thangp): There are several places in the core cinder code where
        # the volume passed through is a dict and not an oslo_versionedobject.
        # We need to react appropriately to what type of volume is passed in,
        # until the switch over to oslo_versionedobjects is complete.
        if isinstance(volume, objects.Volume):
            volume_metadata = volume.admin_metadata
        else:
            volume_metadata = {}
            for metadata in volume['volume_admin_metadata']:
                volume_metadata[metadata['key']] = metadata['value']

        access_mode = volume_metadata.get('attached_mode')
        if access_mode is None:
            access_mode = ('ro'
                           if volume_metadata.get('readonly') == 'True'
                           else 'rw')

        return {'driver_volume_type': 'iscsi',
                'data': {'access_mode': access_mode}}

    @utils.trace_method
    def initialize_connection_snapshot(self, snapshot, connector):
        return {
            'driver_volume_type': 'iscsi',
        }

    @utils.trace_method
    def terminate_connection(self, volume, connector, **kwargs):
        pass

    # Replication Group (Tiramisu)
    @utils.trace_method
    def enable_replication(self, context, group, volumes):
        """Enables replication for a group and volumes in the group."""
        model_update = {
            'replication_status': fields.ReplicationStatus.ENABLED}
        volume_model_updates = []
        for volume_ref in volumes:
            volume_model_update = {'id': volume_ref.id}
            volume_model_update['replication_status'] = (
                fields.ReplicationStatus.ENABLED)
            volume_model_updates.append(volume_model_update)

        return model_update, volume_model_updates

    # Replication Group (Tiramisu)
    @utils.trace_method
    def disable_replication(self, context, group, volumes):
        """Disables replication for a group and volumes in the group."""
        model_update = {
            'replication_status': fields.ReplicationStatus.DISABLED}
        volume_model_updates = []
        for volume_ref in volumes:
            volume_model_update = {'id': volume_ref.id}
            volume_model_update['replication_status'] = (
                fields.ReplicationStatus.DISABLED)
            volume_model_updates.append(volume_model_update)

        return model_update, volume_model_updates

    # Replication Group (Tiramisu)
    @utils.trace_method
    def failover_replication(self, context, group, volumes,
                             secondary_backend_id=None):
        """Fails over replication for a group and volumes in the group."""
        model_update = {
            'replication_status': fields.ReplicationStatus.FAILED_OVER}
        volume_model_updates = []
        for volume_ref in volumes:
            volume_model_update = {'id': volume_ref.id}
            volume_model_update['replication_status'] = (
                fields.ReplicationStatus.FAILED_OVER)
            volume_model_updates.append(volume_model_update)

        return model_update, volume_model_updates

    # Replication Group (Tiramisu)
    @utils.trace_method
    def create_group(self, context, group):
        """Creates a group."""
        model_update = super(FakeLoggingVolumeDriver, self).create_group(
            context, group)
        try:
            if group.is_replicated:
                # Sets the new group's replication_status to disabled
                model_update['replication_status'] = (
                    fields.ReplicationStatus.DISABLED)
        except exception.GroupTypeNotFound:
            pass

        return model_update

    def _update_volume_stats(self):
        data = {'volume_backend_name': self.backend_name,
                'vendor_name': 'Open Source',
                'driver_version': self.VERSION,
                'storage_protocol': self.protocol,
                'pools': []}

        fake_pool = {'pool_name': data['volume_backend_name'],
                     'total_capacity_gb': 'infinite',
                     'free_capacity_gb': 'infinite',
                     'provisioned_capacity_gb': 0,
                     'reserved_percentage': 100,
                     'QoS_support': False,
                     'filter_function': self.get_filter_function(),
                     'goodness_function': self.get_goodness_function(),
                     'consistencygroup_support': False,
                     'replication_enabled': True,
                     'group_replication_enabled': True, }

        data['pools'].append(fake_pool)
        self._stats = data

    @staticmethod
    def fake_execute(cmd, *_args, **_kwargs):
        """Execute that simply logs the command."""
        return (None, None)


class FakeISERDriver(FakeLoggingVolumeDriver):
    def __init__(self, *args, **kwargs):
        super(FakeISERDriver, self).__init__(execute=self.fake_execute,
                                             *args, **kwargs)

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'iser',
            'data': {}
        }


class FakeFibreChannelDriver(driver.FibreChannelDriver):

    def initialize_connection(self, volume, connector):
        conn_info = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'initiator_target_map': {'fake_wwn': ['fake_wwn2']},
            }}
        fczm_utils.add_fc_zone(conn_info)
        return conn_info

    def initialize_connection_with_empty_map(self, volume, connector):
        conn_info = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'initiator_target_map': {},
            }}
        fczm_utils.add_fc_zone(conn_info)
        return conn_info

    def no_zone_initialize_connection(self, volume, connector):
        """This shouldn't call the ZM."""
        conn_info = {
            'driver_volume_type': 'bogus',
            'data': {
                'initiator_target_map': {'fake_wwn': ['fake_wwn2']},
            }}
        fczm_utils.add_fc_zone(conn_info)
        return conn_info

    def terminate_connection(self, volume, connector, **kwargs):
        conn_info = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'initiator_target_map': {'fake_wwn': ['fake_wwn2']},
            }}
        fczm_utils.remove_fc_zone(conn_info)
        return conn_info

    def terminate_connection_with_empty_map(self, volume, connector, **kwargs):
        conn_info = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'initiator_target_map': {},
            }}
        fczm_utils.remove_fc_zone(conn_info)
        return conn_info

    def no_zone_terminate_connection(self, volume, connector, **kwargs):
        conn_info = {
            'driver_volume_type': 'bogus',
            'data': {
                'initiator_target_map': {'fake_wwn': ['fake_wwn2']},
            }}
        fczm_utils.remove_fc_zone(conn_info)
        return conn_info


class FakeGateDriver(lvm.LVMVolumeDriver):
    """Class designation for FakeGateDriver.

    FakeGateDriver is for TESTING ONLY. There are a few
    driver features such as CG and replication that are not
    supported by the reference driver LVM currently. Adding
    those functions in this fake driver will help detect
    problems when changes are introduced in those functions.

    Implementation of this driver is NOT meant for production.
    They are implemented simply to make sure calls to the driver
    functions are passing in the correct parameters, and the
    results returned by the driver are handled properly by the manager.

    """
    def __init__(self, *args, **kwargs):
        super(FakeGateDriver, self).__init__(*args, **kwargs)

    def _update_volume_stats(self):
        super(FakeGateDriver, self)._update_volume_stats()
        self._stats["pools"][0]["consistencygroup_support"] = True

    # NOTE(xyang): Consistency Group functions implemented below
    # are for testing purpose only. Data consistency cannot be
    # achieved by running these functions.
    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""
        # A consistencygroup entry is already created in db
        # This driver just returns a status
        now = timeutils.utcnow()
        model_update = {'status': fields.ConsistencyGroupStatus.AVAILABLE,
                        'updated_at': now}

        return model_update

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         soure_cg=None, source_vols=None):
        """Creates a consistencygroup from cgsnapshot or source cg."""
        for vol in volumes:
            try:
                if snapshots:
                    for snapshot in snapshots:
                        if vol['snapshot_id'] == snapshot['id']:
                            self.create_volume_from_snapshot(vol, snapshot)
                            break
            except Exception:
                raise
            try:
                if source_vols:
                    for source_vol in source_vols:
                        if vol['source_volid'] == source_vol['id']:
                            self.create_cloned_volume(vol, source_vol)
                            break
            except Exception:
                raise
        return None, None

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistencygroup and volumes in the group."""
        model_update = {'status': group.status}
        volume_model_updates = []
        for volume_ref in volumes:
            volume_model_update = {'id': volume_ref.id}
            try:
                self.remove_export(context, volume_ref)
                self.delete_volume(volume_ref)
                volume_model_update['status'] = 'deleted'
            except exception.VolumeIsBusy:
                volume_model_update['status'] = 'available'
            except Exception:
                volume_model_update['status'] = 'error'
                model_update['status'] = fields.ConsistencyGroupStatus.ERROR
            volume_model_updates.append(volume_model_update)

        return model_update, volume_model_updates

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Updates a consistency group."""
        return None, None, None

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot.

        Snapshots created here are NOT consistent. This is for
        testing purpose only.
        """
        model_update = {'status': 'available'}
        snapshot_model_updates = []
        for snapshot in snapshots:
            snapshot_model_update = {'id': snapshot.id}
            try:
                self.create_snapshot(snapshot)
                snapshot_model_update['status'] = (
                    fields.SnapshotStatus.AVAILABLE)
            except Exception:
                snapshot_model_update['status'] = fields.SnapshotStatus.ERROR
                model_update['status'] = 'error'
            snapshot_model_updates.append(snapshot_model_update)

        return model_update, snapshot_model_updates

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot."""
        model_update = {'status': cgsnapshot.status}
        snapshot_model_updates = []
        for snapshot in snapshots:
            snapshot_model_update = {'id': snapshot.id}
            try:
                self.delete_snapshot(snapshot)
                snapshot_model_update['status'] = (
                    fields.SnapshotStatus.DELETED)
            except exception.SnapshotIsBusy:
                snapshot_model_update['status'] = (
                    fields.SnapshotStatus.AVAILABLE)
            except Exception:
                snapshot_model_update['status'] = (
                    fields.SnapshotStatus.ERROR)
                model_update['status'] = 'error'
            snapshot_model_updates.append(snapshot_model_update)

        return model_update, snapshot_model_updates


class FakeHAReplicatedLoggingVolumeDriver(FakeLoggingVolumeDriver):
    SUPPORTS_ACTIVE_ACTIVE = True

    @utils.trace_method
    def failover_completed(self, context, active_backend_id=None):
        pass
