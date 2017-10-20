# Copyright 2013 IBM Corp.
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


import copy

import mock

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.ibm.ibm_storage import ibm_storage
from cinder.volume import volume_types

FAKE = "fake"
FAKE2 = "fake2"
CANNOT_DELETE = "Can not delete"
TOO_BIG_VOLUME_SIZE = 12000
POOL_SIZE = 100
GROUP_ID = 1
VOLUME = {'size': 16,
          'name': FAKE,
          'id': 1,
          'status': 'available'}
VOLUME2 = {'size': 32,
           'name': FAKE2,
           'id': 2,
           'status': 'available'}
GROUP_VOLUME = {'size': 16,
                'name': FAKE,
                'id': 3,
                'group_id': GROUP_ID,
                'status': 'available'}

MANAGED_FAKE = "managed_fake"
MANAGED_VOLUME = {'size': 16,
                  'name': MANAGED_FAKE,
                  'id': 2}

REPLICA_FAKE = "repicated_fake"
REPLICATED_VOLUME = {'size': 64,
                     'name': REPLICA_FAKE,
                     'id': '2',
                     'replication_status': fields.ReplicationStatus.ENABLED}

REPLICATED_VOLUME_DISABLED = REPLICATED_VOLUME.copy()
REPLICATED_VOLUME_DISABLED['replication_status'] = (
    fields.ReplicationStatus.DISABLED)

REPLICATION_TARGETS = [{'target_device_id': 'fakedevice'}]
SECONDARY = 'fakedevice'
FAKE_FAILOVER_HOST = 'fakehost@fakebackend#fakepool'
FAKE_PROVIDER_LOCATION = 'fake_provider_location'
FAKE_DRIVER_DATA = 'fake_driver_data'

CONTEXT = {}

FAKESNAPSHOT = 'fakesnapshot'
SNAPSHOT = {'name': 'fakesnapshot',
            'id': 3}

GROUP = {'id': GROUP_ID, }
GROUP_SNAPSHOT_ID = 1
GROUP_SNAPSHOT = {'id': GROUP_SNAPSHOT_ID,
                  'group_id': GROUP_ID}

CONNECTOR = {'initiator': "iqn.2012-07.org.fake:01:948f189c4695", }

FAKE_PROXY = 'cinder.tests.unit.volume.drivers.ibm.test_ibm_storage' \
    '.IBMStorageFakeProxyDriver'


class IBMStorageFakeProxyDriver(object):
    """Fake IBM Storage driver

    Fake IBM Storage driver for IBM XIV, Spectrum Accelerate,
    FlashSystem A9000, FlashSystem A9000R and DS8000 storage systems.
    """

    def __init__(self, ibm_storage_info, logger, expt,
                 driver=None, active_backend_id=None, host=None):
        """Initialize Proxy."""

        self.ibm_storage_info = ibm_storage_info
        self.logger = logger
        self.exception = expt
        self.storage_portal = \
            self.storage_iqn = FAKE

        self.volumes = {}
        self.snapshots = {}
        self.driver = driver

    def setup(self, context):
        if self.ibm_storage_info['user'] != self.driver\
                .configuration.san_login:
            raise self.exception.NotAuthorized()

        if self.ibm_storage_info['address'] != self.driver\
                .configuration.san_ip:
            raise self.exception.HostNotFound(host='fake')

    def create_volume(self, volume):
        if volume['size'] > POOL_SIZE:
            raise self.exception.VolumeBackendAPIException(data='blah')
        self.volumes[volume['name']] = volume

    def volume_exists(self, volume):
        return self.volumes.get(volume['name'], None) is not None

    def delete_volume(self, volume):
        if self.volumes.get(volume['name'], None) is not None:
            del self.volumes[volume['name']]

    def manage_volume_get_size(self, volume, existing_ref):
        if self.volumes.get(existing_ref['source-name'], None) is None:
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        return self.volumes[existing_ref['source-name']]['size']

    def manage_volume(self, volume, existing_ref):
        if self.volumes.get(existing_ref['source-name'], None) is None:
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        volume['size'] = MANAGED_VOLUME['size']
        return {}

    def unmanage_volume(self, volume):
        pass

    def initialize_connection(self, volume, connector):
        if not self.volume_exists(volume):
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        lun_id = volume['id']

        self.volumes[volume['name']]['attached'] = connector

        return {'driver_volume_type': 'iscsi',
                'data': {'target_discovered': True,
                         'target_portal': self.storage_portal,
                         'target_iqn': self.storage_iqn,
                         'target_lun': lun_id,
                         'volume_id': volume['id'],
                         'multipath': True,
                         'provider_location': "%s,1 %s %s" % (
                             self.storage_portal,
                             self.storage_iqn,
                             lun_id), },
                }

    def terminate_connection(self, volume, connector):
        if not self.volume_exists(volume):
            raise self.exception.VolumeNotFound(volume_id=volume['id'])
        if not self.is_volume_attached(volume, connector):
            raise self.exception.NotFound(_('Volume not found for '
                                            'instance %(instance_id)s.')
                                          % {'instance_id': 'fake'})
        del self.volumes[volume['name']]['attached']

    def is_volume_attached(self, volume, connector):
        if not self.volume_exists(volume):
            raise self.exception.VolumeNotFound(volume_id=volume['id'])

        return (self.volumes[volume['name']].get('attached', None)
                == connector)

    def get_replication_status(self, context, volume):
        if volume['replication_status'] == 'invalid_status_val':
            raise exception.CinderException()
        return {'replication_status': 'active'}

    def retype(self, ctxt, volume, new_type, diff, host):
        volume['easytier'] = new_type['extra_specs']['easytier']
        return True, volume

    def create_group(self, ctxt, group):

        volumes = [volume for k, volume in self.volumes.items()
                   if volume['group_id'] == group['id']]

        if volumes:
            raise exception.CinderException(
                message='The group id of volume may be wrong.')

        return {'status': fields.GroupStatus.AVAILABLE}

    def delete_group(self, ctxt, group, volumes):
        for volume in self.volumes.values():
            if group.get('id') == volume.get('group_id'):
                if volume['name'] == CANNOT_DELETE:
                    raise exception.VolumeBackendAPIException(
                        message='Volume can not be deleted')
                else:
                    volume['status'] = 'deleted'
                    volumes.append(volume)

        # Delete snapshots in group
        self.snapshots = {k: snap for k, snap in self.snapshots.items()
                          if not(snap.get('group_id') == group.get('id'))}

        # Delete volume in group
        self.volumes = {k: vol for k, vol in self.volumes.items()
                        if not(vol.get('group_id') == group.get('id'))}

        return {'status': fields.GroupStatus.DELETED}, volumes

    def update_group(self, context, group, add_volumes, remove_volumes):
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        return model_update, None, None

    def create_group_from_src(self, context, group, volumes, group_snapshot,
                              snapshots, source_group=None, source_vols=None):

        return None, None

    def create_group_snapshot(self, ctxt, group_snapshot, snapshots):
        for volume in self.volumes.values():
            if group_snapshot.get('group_id') == volume.get('group_id'):
                if volume['size'] > POOL_SIZE / 2:
                    raise self.exception.VolumeBackendAPIException(data='blah')

                snapshot = copy.deepcopy(volume)
                snapshot['name'] = (
                    CANNOT_DELETE if snapshot['name'] == CANNOT_DELETE
                    else snapshot['name'] + 'Snapshot')
                snapshot['status'] = 'available'
                snapshot['group_snapshot_id'] = group_snapshot.get('id')
                snapshot['group_id'] = group_snapshot.get('group_id')
                self.snapshots[snapshot['name']] = snapshot
                snapshots.append(snapshot)

        return {'status': fields.GroupSnapshotStatus.AVAILABLE}, snapshots

    def delete_group_snapshot(self, ctxt, group_snapshot, snapshots):
        updated_snapshots = []
        for snapshot in snapshots:
            if snapshot['name'] == CANNOT_DELETE:
                raise exception.VolumeBackendAPIException(
                    message='Snapshot can not be deleted')
            else:
                snapshot['status'] = 'deleted'
                updated_snapshots.append(snapshot)

        # Delete snapshots in group
        self.snapshots = {k: snap for k, snap in self.snapshots.items()
                          if not(snap.get('group_id')
                                 == group_snapshot.get('group_snapshot_id'))}

        return {'status': 'deleted'}, updated_snapshots

    def freeze_backend(self, context):
        return True

    def thaw_backend(self, context):
        return True

    def failover_host(self, context, volumes, secondary_id, groups=None):
        target_id = 'BLA'
        volume_update_list = []
        for volume in volumes:
            status = 'failed-over'
            if volume['replication_status'] == 'invalid_status_val':
                status = 'error'
            volume_update_list.append(
                {'volume_id': volume['id'],
                 'updates': {'replication_status': status}})

        return target_id, volume_update_list, []

    def enable_replication(self, context, group, volumes):
        vol_status = []
        for vol in volumes:
            vol_status.append(
                {'id': vol['id'],
                 'replication_status': fields.ReplicationStatus.ENABLED})
        return (
            {'replication_status': fields.ReplicationStatus.ENABLED},
            vol_status)

    def disable_replication(self, context, group, volumes):
        volume_update_list = []
        for volume in volumes:
            volume_update_list.append(
                {'id': volume['id'],
                 'replication_status': fields.ReplicationStatus.DISABLED})
        return (
            {'replication_status': fields.ReplicationStatus.DISABLED},
            volume_update_list)

    def failover_replication(self, context, group, volumes, secondary_id):
        volume_update_list = []
        for volume in volumes:
            volume_update_list.append(
                {'id': volume['id'],
                 'replication_status': fields.ReplicationStatus.FAILED_OVER})
        return ({'replication_status': fields.ReplicationStatus.FAILED_OVER},
                volume_update_list)

    def get_replication_error_status(self, context, groups):
        return(
            [{'group_id': groups[0]['id'],
              'replication_status': fields.ReplicationStatus.ERROR}],
            [{'volume_id': VOLUME['id'],
              'replication_status': fields.ReplicationStatus.ERROR}])


class IBMStorageVolumeDriverTest(test.TestCase):
    """Test IBM Storage driver

    Test IBM Storage driver for IBM XIV, Spectrum Accelerate,
    FlashSystem A9000, FlashSystem A9000R and DS8000 storage Systems.
    """

    def setUp(self):
        """Initialize IBM Storage Driver."""
        super(IBMStorageVolumeDriverTest, self).setUp()

        configuration = mock.Mock(conf.Configuration)
        configuration.san_is_local = False
        configuration.proxy = FAKE_PROXY
        configuration.connection_type = 'iscsi'
        configuration.chap = 'disabled'
        configuration.san_ip = FAKE
        configuration.management_ips = FAKE
        configuration.san_login = FAKE
        configuration.san_clustername = FAKE
        configuration.san_password = FAKE
        configuration.append_config_values(mock.ANY)

        self.driver = ibm_storage.IBMStorageDriver(
            configuration=configuration)

    def test_initialized_should_set_ibm_storage_info(self):
        """Test that the san flags are passed to the IBM proxy."""

        self.assertEqual(
            self.driver.proxy.ibm_storage_info['user'],
            self.driver.configuration.san_login)
        self.assertEqual(
            self.driver.proxy.ibm_storage_info['password'],
            self.driver.configuration.san_password)
        self.assertEqual(
            self.driver.proxy.ibm_storage_info['address'],
            self.driver.configuration.san_ip)
        self.assertEqual(
            self.driver.proxy.ibm_storage_info['vol_pool'],
            self.driver.configuration.san_clustername)

    def test_setup_should_fail_if_credentials_are_invalid(self):
        """Test that the proxy validates credentials."""

        self.driver.proxy.ibm_storage_info['user'] = 'invalid'
        self.assertRaises(exception.NotAuthorized, self.driver.do_setup, None)

    def test_setup_should_fail_if_connection_is_invalid(self):
        """Test that the proxy validates connection."""

        self.driver.proxy.ibm_storage_info['address'] = \
            'invalid'
        self.assertRaises(exception.HostNotFound, self.driver.do_setup, None)

    def test_create_volume(self):
        """Test creating a volume."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        has_volume = self.driver.proxy.volume_exists(VOLUME)
        self.assertTrue(has_volume)
        self.driver.delete_volume(VOLUME)

    def test_volume_exists(self):
        """Test the volume exist method with a volume that doesn't exist."""

        self.driver.do_setup(None)

        self.assertFalse(
            self.driver.proxy.volume_exists({'name': FAKE})
        )

    def test_delete_volume(self):
        """Verify that a volume is deleted."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        self.driver.delete_volume(VOLUME)
        has_volume = self.driver.proxy.volume_exists(VOLUME)
        self.assertFalse(has_volume)

    def test_delete_volume_should_fail_for_not_existing_volume(self):
        """Verify that deleting a non-existing volume is OK."""

        self.driver.do_setup(None)
        self.driver.delete_volume(VOLUME)

    def test_create_volume_should_fail_if_no_pool_space_left(self):
        """Verify that the proxy validates volume pool space."""

        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          {'name': FAKE,
                           'id': 1,
                           'size': TOO_BIG_VOLUME_SIZE})

    def test_initialize_connection(self):
        """Test that inititialize connection attaches volume to host."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        self.driver.initialize_connection(VOLUME, CONNECTOR)

        self.assertTrue(
            self.driver.proxy.is_volume_attached(VOLUME, CONNECTOR))

        self.driver.terminate_connection(VOLUME, CONNECTOR)
        self.driver.delete_volume(VOLUME)

    def test_initialize_connection_should_fail_for_non_existing_volume(self):
        """Verify that initialize won't work for non-existing volume."""

        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.initialize_connection,
                          VOLUME,
                          CONNECTOR)

    def test_terminate_connection(self):
        """Test terminating a connection."""

        self.driver.do_setup(None)
        self.driver.create_volume(VOLUME)
        self.driver.initialize_connection(VOLUME, CONNECTOR)
        self.driver.terminate_connection(VOLUME, CONNECTOR)

        self.assertFalse(self.driver.proxy.is_volume_attached(
            VOLUME,
            CONNECTOR))

        self.driver.delete_volume(VOLUME)

    def test_terminate_connection_should_fail_on_non_existing_volume(self):
        """Test that terminate won't work for non-existing volumes."""

        self.driver.do_setup(None)
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.terminate_connection,
                          VOLUME,
                          CONNECTOR)

    def test_manage_existing_get_size(self):
        """Test that manage_existing_get_size returns the expected size. """

        self.driver.do_setup(None)
        self.driver.create_volume(MANAGED_VOLUME)
        existing_ref = {'source-name': MANAGED_VOLUME['name']}
        return_size = self.driver.manage_existing_get_size(
            VOLUME,
            existing_ref)
        self.assertEqual(MANAGED_VOLUME['size'], return_size)

        # cover both case, whether driver renames the volume or not
        self.driver.delete_volume(VOLUME)
        self.driver.delete_volume(MANAGED_VOLUME)

    def test_manage_existing_get_size_should_fail_on_non_existing_volume(self):
        """Test that manage_existing_get_size fails on non existing volume. """

        self.driver.do_setup(None)
        # on purpose - do NOT create managed volume
        existing_ref = {'source-name': MANAGED_VOLUME['name']}
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.manage_existing_get_size,
                          VOLUME,
                          existing_ref)

    def test_manage_existing(self):
        """Test that manage_existing returns successfully. """

        self.driver.do_setup(None)
        self.driver.create_volume(MANAGED_VOLUME)
        existing_ref = {'source-name': MANAGED_VOLUME['name']}
        self.driver.manage_existing(VOLUME, existing_ref)
        self.assertEqual(MANAGED_VOLUME['size'], VOLUME['size'])

        # cover both case, whether driver renames the volume or not
        self.driver.delete_volume(VOLUME)
        self.driver.delete_volume(MANAGED_VOLUME)

    def test_manage_existing_should_fail_on_non_existing_volume(self):
        """Test that manage_existing fails on non existing volume. """

        self.driver.do_setup(None)
        # on purpose - do NOT create managed volume
        existing_ref = {'source-name': MANAGED_VOLUME['name']}
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.manage_existing,
                          VOLUME,
                          existing_ref)

    def test_get_replication_status(self):
        """Test that get_replication_status return successfully. """

        self.driver.do_setup(None)

        # assume the replicated volume is inactive
        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        replicated_volume['replication_status'] = 'inactive'
        model_update = self.driver.get_replication_status(
            CONTEXT,
            replicated_volume
        )
        self.assertEqual('active', model_update['replication_status'])

    def test_get_replication_status_fail_on_exception(self):
        """Test that get_replication_status fails on exception"""

        self.driver.do_setup(None)

        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        # on purpose - set invalid value to replication_status
        # expect an exception.
        replicated_volume['replication_status'] = 'invalid_status_val'
        self.assertRaises(
            exception.CinderException,
            self.driver.get_replication_status,
            CONTEXT,
            replicated_volume
        )

    def test_retype(self):
        """Test that retype returns successfully."""

        self.driver.do_setup(None)

        # prepare parameters
        ctxt = context.get_admin_context()

        host = {
            'host': 'foo',
            'capabilities': {
                'location_info': 'ibm_storage_fake_1',
                'extent_size': '1024'
            }
        }

        key_specs_old = {'easytier': False, 'warning': 2, 'autoexpand': True}
        key_specs_new = {'easytier': True, 'warning': 5, 'autoexpand': False}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        diff, equal = volume_types.volume_types_diff(
            ctxt,
            old_type_ref['id'],
            new_type_ref['id'],
        )

        volume = copy.deepcopy(VOLUME)
        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        self.driver.create_volume(volume)
        ret = self.driver.retype(ctxt, volume, new_type, diff, host)
        self.assertTrue(bool(ret))
        self.assertEqual('1', volume['easytier'])

    def test_retype_fail_on_exception(self):
        """Test that retype fails on exception."""

        self.driver.do_setup(None)

        # prepare parameters
        ctxt = context.get_admin_context()

        host = {
            'host': 'foo',
            'capabilities': {
                'location_info': 'ibm_storage_fake_1',
                'extent_size': '1024'
            }
        }

        key_specs_old = {'easytier': False, 'warning': 2, 'autoexpand': True}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new')

        diff, equal = volume_types.volume_types_diff(
            ctxt,
            old_type_ref['id'],
            new_type_ref['id'],
        )

        volume = copy.deepcopy(VOLUME)
        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        self.driver.create_volume(volume)
        self.assertRaises(
            KeyError,
            self.driver.retype,
            ctxt, volume, new_type, diff, host
        )

    def test_create_group(self):
        """Test that create_group return successfully."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create group
        model_update = self.driver.create_group(ctxt, GROUP)

        self.assertEqual(fields.GroupStatus.AVAILABLE,
                         model_update['status'],
                         "Group created failed")

    def test_create_group_fail_on_group_not_empty(self):
        """Test create_group with empty group."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create volumes
        # And add the volumes into the group before creating group
        self.driver.create_volume(GROUP_VOLUME)

        self.assertRaises(exception.CinderException,
                          self.driver.create_group,
                          ctxt, GROUP)

    def test_delete_group(self):
        """Test that delete_group return successfully."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create group
        self.driver.create_group(ctxt, GROUP)

        # Create volumes and add them to group
        self.driver.create_volume(GROUP_VOLUME)

        # Delete group
        model_update, volumes = self.driver.delete_group(ctxt, GROUP,
                                                         [GROUP_VOLUME])

        # Verify the result
        self.assertEqual(fields.GroupStatus.DELETED,
                         model_update['status'],
                         'Group deleted failed')
        for volume in volumes:
            self.assertEqual('deleted',
                             volume['status'],
                             'Group deleted failed')

    def test_delete_group_fail_on_volume_not_delete(self):
        """Test delete_group with volume delete failure."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create group
        self.driver.create_group(ctxt, GROUP)

        # Set the volume not to be deleted
        volume = copy.deepcopy(GROUP_VOLUME)
        volume['name'] = CANNOT_DELETE

        # Create volumes and add them to group
        self.driver.create_volume(volume)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_group,
                          ctxt, GROUP, [volume])

    def test_create_group_snapshot(self):
        """Test that create_group_snapshot return successfully."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create group
        self.driver.create_group(ctxt, GROUP)

        # Create volumes and add them to group
        self.driver.create_volume(VOLUME)

        # Create group snapshot
        model_update, snapshots = self.driver.create_group_snapshot(
            ctxt, GROUP_SNAPSHOT, [VOLUME])

        # Verify the result
        self.assertEqual(fields.GroupSnapshotStatus.AVAILABLE,
                         model_update['status'],
                         'Group Snapshot created failed')
        for snap in snapshots:
            self.assertEqual('available',
                             snap['status'])

        # Clean the environment
        self.driver.delete_group_snapshot(ctxt, GROUP_SNAPSHOT, [VOLUME])
        self.driver.delete_group(ctxt, GROUP, [VOLUME])

    def test_create_group_snapshot_fail_on_no_pool_space_left(self):
        """Test create_group_snapshot when no pool space left."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create group
        self.driver.create_group(ctxt, GROUP)

        # Set the volume size
        volume = copy.deepcopy(GROUP_VOLUME)
        volume['size'] = POOL_SIZE / 2 + 1

        # Create volumes and add them to group
        self.driver.create_volume(volume)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_group_snapshot,
                          ctxt, GROUP_SNAPSHOT, [volume])

        # Clean the environment
        self.driver.volumes = None
        self.driver.delete_group(ctxt, GROUP, [volume])

    def test_delete_group_snapshot(self):
        """Test that delete_group_snapshot return successfully."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create group
        self.driver.create_group(ctxt, GROUP)

        # Create volumes and add them to group
        self.driver.create_volume(GROUP_VOLUME)

        # Create group snapshot
        self.driver.create_group_snapshot(ctxt, GROUP_SNAPSHOT, [GROUP_VOLUME])

        # Delete group snapshot
        model_update, snapshots = self.driver.delete_group_snapshot(
            ctxt, GROUP_SNAPSHOT, [GROUP_VOLUME])

        # Verify the result
        self.assertEqual(fields.GroupSnapshotStatus.DELETED,
                         model_update['status'],
                         'Group Snapshot deleted failed')
        for snap in snapshots:
            self.assertEqual('deleted',
                             snap['status'])

        # Clean the environment
        self.driver.delete_group(ctxt, GROUP, [GROUP_VOLUME])

    def test_delete_group_snapshot_fail_on_snapshot_not_delete(self):
        """Test delete_group_snapshot when the snapshot cannot be deleted."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create group
        self.driver.create_group(ctxt, GROUP)

        # Set the snapshot not to be deleted
        volume = copy.deepcopy(GROUP_VOLUME)
        volume['name'] = CANNOT_DELETE

        # Create volumes and add them to group
        self.driver.create_volume(volume)

        # Create group snapshot
        self.driver.create_group_snapshot(ctxt, GROUP_SNAPSHOT, [volume])

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_group_snapshot,
                          ctxt, GROUP_SNAPSHOT, [volume])

    def test_update_group_without_volumes(self):
        """Test update_group when there are no volumes specified."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Update group
        model_update, added, removed = self.driver.update_group(
            ctxt, GROUP, [], [])

        self.assertEqual(fields.GroupStatus.AVAILABLE,
                         model_update['status'],
                         "Group update failed")
        self.assertIsNone(added,
                          "added volumes list is not empty")
        self.assertIsNone(removed,
                          "removed volumes list is not empty")

    def test_update_group_with_volumes(self):
        """Test update_group when there are volumes specified."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Update group
        model_update, added, removed = self.driver.update_group(
            ctxt, GROUP, [VOLUME], [VOLUME2])

        self.assertEqual(fields.GroupStatus.AVAILABLE,
                         model_update['status'],
                         "Group update failed")
        self.assertIsNone(added,
                          "added volumes list is not empty")
        self.assertIsNone(removed,
                          "removed volumes list is not empty")

    def test_create_group_from_src_without_volumes(self):
        """Test create_group_from_src with no volumes specified."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create group from source
        model_update, volumes_model_update = (
            self.driver.create_group_from_src(
                ctxt, GROUP, [], GROUP_SNAPSHOT, []))

        # model_update can be None or return available in status
        if model_update:
            self.assertEqual(fields.GroupStatus.AVAILABLE,
                             model_update['status'],
                             "Group create from source failed")
        # volumes_model_update can be None or return available in status
        if volumes_model_update:
            self.assertFalse(volumes_model_update,
                             "volumes list is not empty")

    def test_create_group_from_src_with_volumes(self):
        """Test create_group_from_src with volumes specified."""

        self.driver.do_setup(None)

        ctxt = context.get_admin_context()

        # Create group from source
        model_update, volumes_model_update = (
            self.driver.create_group_from_src(
                ctxt, GROUP, [VOLUME], GROUP_SNAPSHOT, [SNAPSHOT]))

        # model_update can be None or return available in status
        if model_update:
            self.assertEqual(fields.GroupStatus.AVAILABLE,
                             model_update['status'],
                             "Group create from source failed")
        # volumes_model_update can be None or return available in status
        if volumes_model_update:
            self.assertEqual(fields.GroupStatus.AVAILABLE,
                             volumes_model_update['status'],
                             "volumes list status failed")

    def test_freeze_backend(self):
        """Test that freeze_backend returns successful"""

        self.driver.do_setup(None)

        # not much we can test here...
        self.assertTrue(self.driver.freeze_backend(CONTEXT))

    def test_thaw_backend(self):
        """Test that thaw_backend returns successful"""

        self.driver.do_setup(None)

        # not much we can test here...
        self.assertTrue(self.driver.thaw_backend(CONTEXT))

    def test_failover_host(self):
        """Test that failover_host returns expected values"""

        self.driver.do_setup(None)

        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        # assume the replication_status is active
        replicated_volume['replication_status'] = 'active'

        expected_target_id = 'BLA'
        expected_volume_update_list = [
            {'volume_id': REPLICATED_VOLUME['id'],
             'updates': {'replication_status': 'failed-over'}}]

        target_id, volume_update_list, __ = self.driver.failover_host(
            CONTEXT,
            [replicated_volume],
            SECONDARY,
            []
        )

        self.assertEqual(expected_target_id, target_id)
        self.assertEqual(expected_volume_update_list, volume_update_list)

    def test_failover_host_bad_state(self):
        """Test that failover_host returns with error"""

        self.driver.do_setup(None)

        replicated_volume = copy.deepcopy(REPLICATED_VOLUME)
        # assume the replication_status is active
        replicated_volume['replication_status'] = 'invalid_status_val'

        expected_target_id = 'BLA'
        expected_volume_update_list = [
            {'volume_id': REPLICATED_VOLUME['id'],
             'updates': {'replication_status': 'error'}}]

        target_id, volume_update_list, __ = self.driver.failover_host(
            CONTEXT,
            [replicated_volume],
            SECONDARY,
            []
        )

        self.assertEqual(expected_target_id, target_id)
        self.assertEqual(expected_volume_update_list, volume_update_list)

    def test_enable_replication(self):
        self.driver.do_setup(None)
        model_update, volumes_model_update = self.driver.enable_replication(
            CONTEXT, GROUP, [REPLICATED_VOLUME])
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         model_update['replication_status'])
        for vol in volumes_model_update:
            self.assertEqual(fields.ReplicationStatus.ENABLED,
                             vol['replication_status'])

    def test_disable_replication(self):
        self.driver.do_setup(None)
        model_update, volumes_model_update = self.driver.disable_replication(
            CONTEXT, GROUP, [REPLICATED_VOLUME_DISABLED])
        self.assertEqual(fields.ReplicationStatus.DISABLED,
                         model_update['replication_status'])
        for vol in volumes_model_update:
            self.assertEqual(fields.ReplicationStatus.DISABLED,
                             volumes_model_update[0]['replication_status'])

    def test_failover_replication(self):
        self.driver.do_setup(None)
        model_update, volumes_model_update = self.driver.failover_replication(
            CONTEXT, GROUP, [VOLUME], SECONDARY)
        self.assertEqual(fields.ReplicationStatus.FAILED_OVER,
                         model_update['replication_status'])

    def test_get_replication_error_status(self):
        self.driver.do_setup(None)
        group_model_updates, volume_model_updates = (
            self.driver.get_replication_error_status(CONTEXT, [GROUP]))
        self.assertEqual(fields.ReplicationStatus.ERROR,
                         group_model_updates[0]['replication_status'])
        self.assertEqual(fields.ReplicationStatus.ERROR,
                         volume_model_updates[0]['replication_status'])
