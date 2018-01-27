# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""Tests for global snapshot cases."""

import ddt
import os
import sys

import mock
from oslo_config import cfg
from oslo_utils import imageutils

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder import test
from cinder.tests.unit.brick import fake_lvm
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base
import cinder.volume

QUOTAS = quota.QUOTAS

CONF = cfg.CONF

OVER_SNAPSHOT_QUOTA_EXCEPTION = exception.OverQuota(
    overs=['snapshots'],
    usages = {'snapshots': {'reserved': 1, 'in_use': 9}},
    quotas = {'gigabytes': 10, 'snapshots': 10})


def create_snapshot(volume_id, size=1, metadata=None, ctxt=None,
                    **kwargs):
    """Create a snapshot object."""
    metadata = metadata or {}
    snap = objects.Snapshot(ctxt or context.get_admin_context())
    snap.volume_size = size
    snap.user_id = fake.USER_ID
    snap.project_id = fake.PROJECT_ID
    snap.volume_id = volume_id
    snap.status = fields.SnapshotStatus.CREATING
    if metadata is not None:
        snap.metadata = metadata
    snap.update(kwargs)

    snap.create()
    return snap


@ddt.ddt
class SnapshotTestCase(base.BaseVolumeTestCase):
    def test_delete_snapshot_frozen(self):
        service = tests_utils.create_service(self.context, {'frozen': True})
        volume = tests_utils.create_volume(self.context, host=service.host)
        snapshot = tests_utils.create_snapshot(self.context, volume.id)
        self.assertRaises(exception.InvalidInput,
                          self.volume_api.delete_snapshot, self.context,
                          snapshot)

    @ddt.data('create_snapshot', 'create_snapshot_force')
    def test_create_snapshot_frozen(self, method):
        service = tests_utils.create_service(self.context, {'frozen': True})
        volume = tests_utils.create_volume(self.context, host=service.host)
        method = getattr(self.volume_api, method)
        self.assertRaises(exception.InvalidInput,
                          method, self.context, volume, 'name', 'desc')

    def test_create_snapshot_driver_not_initialized(self):
        volume_src = tests_utils.create_volume(self.context,
                                               **self.volume_params)
        self.volume.create_volume(self.context, volume_src)
        snapshot_id = create_snapshot(volume_src['id'],
                                      size=volume_src['size'])['id']
        snapshot_obj = objects.Snapshot.get_by_id(self.context, snapshot_id)

        self.volume.driver._initialized = False

        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.create_snapshot,
                          self.context, snapshot_obj)

        # NOTE(flaper87): The volume status should be error.
        self.assertEqual(fields.SnapshotStatus.ERROR, snapshot_obj.status)

        # lets cleanup the mess
        self.volume.driver._initialized = True
        self.volume.delete_snapshot(self.context, snapshot_obj)
        self.volume.delete_volume(self.context, volume_src)

    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    def test_create_delete_snapshot(self, mock_notify):
        """Test snapshot can be created and deleted."""
        volume = tests_utils.create_volume(
            self.context,
            availability_zone=CONF.storage_availability_zone,
            **self.volume_params)

        mock_notify.assert_not_called()

        self.volume.create_volume(self.context, volume)

        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end']))

        snapshot = create_snapshot(volume['id'], size=volume['size'])
        snapshot_id = snapshot.id
        self.volume.create_snapshot(self.context, snapshot)
        self.assertEqual(
            snapshot_id, objects.Snapshot.get_by_id(self.context,
                                                    snapshot_id).id)

        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end'],
                                   ['INFO', 'snapshot.create.start'],
                                   ['INFO', 'snapshot.create.end']))

        self.volume.delete_snapshot(self.context, snapshot)
        self.assert_notify_called(mock_notify,
                                  (['INFO', 'volume.create.start'],
                                   ['INFO', 'volume.create.end'],
                                   ['INFO', 'snapshot.create.start'],
                                   ['INFO', 'snapshot.create.end'],
                                   ['INFO', 'snapshot.delete.start'],
                                   ['INFO', 'snapshot.delete.end']))

        snap = objects.Snapshot.get_by_id(context.get_admin_context(
            read_deleted='yes'), snapshot_id)
        self.assertEqual(fields.SnapshotStatus.DELETED, snap.status)
        self.assertRaises(exception.NotFound,
                          db.snapshot_get,
                          self.context,
                          snapshot_id)
        self.volume.delete_volume(self.context, volume)

    def test_create_delete_snapshot_with_metadata(self):
        """Test snapshot can be created with metadata and deleted."""
        test_meta = {'fake_key': 'fake_value'}
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        snapshot = create_snapshot(volume['id'], size=volume['size'],
                                   metadata=test_meta)
        snapshot_id = snapshot.id

        result_dict = snapshot.metadata

        self.assertEqual(test_meta, result_dict)
        self.volume.delete_snapshot(self.context, snapshot)
        self.assertRaises(exception.NotFound,
                          db.snapshot_get,
                          self.context,
                          snapshot_id)

    def test_delete_snapshot_another_cluster_fails(self):
        """Test delete of snapshot from another cluster fails."""
        self.volume.cluster = 'mycluster'
        volume = tests_utils.create_volume(self.context, status='available',
                                           size=1, host=CONF.host + 'fake',
                                           cluster_name=self.volume.cluster)
        snapshot = create_snapshot(volume.id, size=volume.size)

        self.volume.delete_snapshot(self.context, snapshot)
        self.assertRaises(exception.NotFound,
                          db.snapshot_get,
                          self.context,
                          snapshot.id)

    @mock.patch.object(db, 'snapshot_create',
                       side_effect=exception.InvalidSnapshot(
                           'Create snapshot in db failed!'))
    def test_create_snapshot_failed_db_snapshot(self, mock_snapshot):
        """Test exception handling when create snapshot in db failed."""
        test_volume = tests_utils.create_volume(
            self.context,
            status='available',
            host=CONF.host)
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidSnapshot,
                          volume_api.create_snapshot,
                          self.context,
                          test_volume,
                          'fake_name',
                          'fake_description')

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_create_snapshot_in_db_invalid_volume_status(self, mock_get):
        test_volume1 = tests_utils.create_volume(
            self.context,
            status='available',
            host=CONF.host)
        test_volume2 = tests_utils.create_volume(
            self.context,
            status='deleting',
            host=CONF.host)
        mock_get.return_value = test_volume2
        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.InvalidVolume,
                          volume_api.create_snapshot_in_db,
                          self.context, test_volume1, "fake_snapshot_name",
                          "fake_description", False, {}, None,
                          commit_quota=False)

    def test_create_snapshot_failed_maintenance(self):
        """Test exception handling when create snapshot in maintenance."""
        test_volume = tests_utils.create_volume(
            self.context,
            status='maintenance',
            host=CONF.host)
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.create_snapshot,
                          self.context,
                          test_volume,
                          'fake_name',
                          'fake_description')

    @mock.patch.object(QUOTAS, 'commit',
                       side_effect=exception.QuotaError(
                           'Snapshot quota commit failed!'))
    def test_create_snapshot_failed_quota_commit(self, mock_snapshot):
        """Test exception handling when snapshot quota commit failed."""
        test_volume = tests_utils.create_volume(
            self.context,
            status='available',
            host=CONF.host)
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.QuotaError,
                          volume_api.create_snapshot,
                          self.context,
                          test_volume,
                          'fake_name',
                          'fake_description')

    @mock.patch.object(QUOTAS, 'reserve',
                       side_effect = OVER_SNAPSHOT_QUOTA_EXCEPTION)
    def test_create_snapshot_failed_quota_reserve(self, mock_reserve):
        """Test exception handling when snapshot quota reserve failed."""
        test_volume = tests_utils.create_volume(
            self.context,
            status='available',
            host=CONF.host)
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.SnapshotLimitExceeded,
                          volume_api.create_snapshot,
                          self.context,
                          test_volume,
                          'fake_name',
                          'fake_description')

    @mock.patch.object(QUOTAS, 'reserve',
                       side_effect = OVER_SNAPSHOT_QUOTA_EXCEPTION)
    def test_create_snapshots_in_db_failed_quota_reserve(self, mock_reserve):
        """Test exception handling when snapshot quota reserve failed."""
        test_volume = tests_utils.create_volume(
            self.context,
            status='available',
            host=CONF.host)
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.SnapshotLimitExceeded,
                          volume_api.create_snapshots_in_db,
                          self.context,
                          [test_volume],
                          'fake_name',
                          'fake_description',
                          fake.CONSISTENCY_GROUP_ID)

    def test_create_snapshot_failed_host_is_None(self):
        """Test exception handling when create snapshot and host is None."""
        test_volume = tests_utils.create_volume(
            self.context,
            host=None)
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidVolume,
                          volume_api.create_snapshot,
                          self.context,
                          test_volume,
                          'fake_name',
                          'fake_description')

    def test_create_snapshot_force(self):
        """Test snapshot in use can be created forcibly."""

        instance_uuid = '12345678-1234-5678-1234-567812345678'
        # create volume and attach to the instance
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume)
        values = {'volume_id': volume['id'],
                  'instance_uuid': instance_uuid,
                  'attach_status': fields.VolumeAttachStatus.ATTACHING, }
        attachment = db.volume_attach(self.context, values)
        db.volume_attached(self.context, attachment['id'], instance_uuid,
                           None, '/dev/sda1')

        volume_api = cinder.volume.api.API()
        volume = volume_api.get(self.context, volume['id'])
        self.assertRaises(exception.InvalidVolume,
                          volume_api.create_snapshot,
                          self.context, volume,
                          'fake_name', 'fake_description')
        snapshot_ref = volume_api.create_snapshot_force(self.context,
                                                        volume,
                                                        'fake_name',
                                                        'fake_description')
        snapshot_ref.destroy()
        db.volume_destroy(self.context, volume['id'])

        # create volume and attach to the host
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        self.volume.create_volume(self.context, volume)
        values = {'volume_id': volume['id'],
                  'attached_host': 'fake_host',
                  'attach_status': fields.VolumeAttachStatus.ATTACHING, }
        attachment = db.volume_attach(self.context, values)
        db.volume_attached(self.context, attachment['id'], None,
                           'fake_host', '/dev/sda1')

        volume_api = cinder.volume.api.API()
        volume = volume_api.get(self.context, volume['id'])
        self.assertRaises(exception.InvalidVolume,
                          volume_api.create_snapshot,
                          self.context, volume,
                          'fake_name', 'fake_description')
        snapshot_ref = volume_api.create_snapshot_force(self.context,
                                                        volume,
                                                        'fake_name',
                                                        'fake_description')
        snapshot_ref.destroy()
        db.volume_destroy(self.context, volume['id'])

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_snapshot_from_bootable_volume(self, mock_qemu_info):
        """Test create snapshot from bootable volume."""
        # create bootable volume from image
        volume = self._create_volume_from_image()
        volume_id = volume['id']
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])

        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        # get volume's volume_glance_metadata
        ctxt = context.get_admin_context()
        vol_glance_meta = db.volume_glance_metadata_get(ctxt, volume_id)
        self.assertTrue(vol_glance_meta)

        # create snapshot from bootable volume
        snap = create_snapshot(volume_id)
        self.volume.create_snapshot(ctxt, snap)

        # get snapshot's volume_glance_metadata
        snap_glance_meta = db.volume_snapshot_glance_metadata_get(
            ctxt, snap.id)
        self.assertTrue(snap_glance_meta)

        # ensure that volume's glance metadata is copied
        # to snapshot's glance metadata
        self.assertEqual(len(vol_glance_meta), len(snap_glance_meta))
        vol_glance_dict = {x.key: x.value for x in vol_glance_meta}
        snap_glance_dict = {x.key: x.value for x in snap_glance_meta}
        self.assertDictEqual(vol_glance_dict, snap_glance_dict)

        # ensure that snapshot's status is changed to 'available'
        self.assertEqual(fields.SnapshotStatus.AVAILABLE, snap.status)

        # cleanup resource
        snap.destroy()
        db.volume_destroy(ctxt, volume_id)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_snapshot_from_bootable_volume_fail(self, mock_qemu_info):
        """Test create snapshot from bootable volume.

        But it fails to volume_glance_metadata_copy_to_snapshot.
        As a result, status of snapshot is changed to ERROR.
        """
        # create bootable volume from image
        volume = self._create_volume_from_image()
        volume_id = volume['id']
        self.assertEqual('available', volume['status'])
        self.assertTrue(volume['bootable'])

        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        # get volume's volume_glance_metadata
        ctxt = context.get_admin_context()
        vol_glance_meta = db.volume_glance_metadata_get(ctxt, volume_id)
        self.assertTrue(vol_glance_meta)
        snap = create_snapshot(volume_id)
        self.assertEqual(36, len(snap.id))  # dynamically-generated UUID
        self.assertEqual('creating', snap.status)

        # set to return DB exception
        with mock.patch.object(db, 'volume_glance_metadata_copy_to_snapshot')\
                as mock_db:
            mock_db.side_effect = exception.MetadataCopyFailure(
                reason="Because of DB service down.")
            # create snapshot from bootable volume
            self.assertRaises(exception.MetadataCopyFailure,
                              self.volume.create_snapshot,
                              ctxt,
                              snap)

        # get snapshot's volume_glance_metadata
        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_snapshot_glance_metadata_get,
                          ctxt, snap.id)

        # ensure that status of snapshot is 'error'
        self.assertEqual(fields.SnapshotStatus.ERROR, snap.status)

        # cleanup resource
        snap.destroy()
        db.volume_destroy(ctxt, volume_id)

    def test_create_snapshot_from_bootable_volume_with_volume_metadata_none(
            self):
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']

        self.volume.create_volume(self.context, volume)
        # set bootable flag of volume to True
        db.volume_update(self.context, volume_id, {'bootable': True})

        snapshot = create_snapshot(volume['id'])
        self.volume.create_snapshot(self.context, snapshot)
        self.assertRaises(exception.GlanceMetadataNotFound,
                          db.volume_snapshot_glance_metadata_get,
                          self.context, snapshot.id)

        # ensure that status of snapshot is 'available'
        self.assertEqual(fields.SnapshotStatus.AVAILABLE, snapshot.status)

        # cleanup resource
        snapshot.destroy()
        db.volume_destroy(self.context, volume_id)

    def test_delete_busy_snapshot(self):
        """Test snapshot can be created and deleted."""

        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        snapshot = create_snapshot(volume_id, size=volume['size'])
        self.volume.create_snapshot(self.context, snapshot)

        with mock.patch.object(self.volume.driver, 'delete_snapshot',
                               side_effect=exception.SnapshotIsBusy(
                                   snapshot_name='fake')
                               ) as mock_del_snap:
            snapshot_id = snapshot.id
            self.volume.delete_snapshot(self.context, snapshot)
            snapshot_ref = objects.Snapshot.get_by_id(self.context,
                                                      snapshot_id)
            self.assertEqual(snapshot_id, snapshot_ref.id)
            self.assertEqual(fields.SnapshotStatus.AVAILABLE,
                             snapshot_ref.status)
            mock_del_snap.assert_called_once_with(snapshot)

    @test.testtools.skipIf(sys.platform == "darwin", "SKIP on OSX")
    def test_delete_no_dev_fails(self):
        """Test delete snapshot with no dev file fails."""
        self.mock_object(os.path, 'exists', lambda x: False)
        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

        volume = tests_utils.create_volume(self.context, **self.volume_params)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume)
        snapshot = create_snapshot(volume_id)
        snapshot_id = snapshot.id
        self.volume.create_snapshot(self.context, snapshot)

        with mock.patch.object(self.volume.driver, 'delete_snapshot',
                               side_effect=exception.SnapshotIsBusy(
                                   snapshot_name='fake')) as mock_del_snap:
            self.volume.delete_snapshot(self.context, snapshot)
            snapshot_ref = objects.Snapshot.get_by_id(self.context,
                                                      snapshot_id)
            self.assertEqual(snapshot_id, snapshot_ref.id)
            self.assertEqual(fields.SnapshotStatus.AVAILABLE,
                             snapshot_ref.status)
            mock_del_snap.assert_called_once_with(snapshot)

    def test_volume_api_update_snapshot(self):
        # create raw snapshot
        volume = tests_utils.create_volume(self.context, **self.volume_params)
        snapshot = create_snapshot(volume['id'])
        snapshot_id = snapshot.id
        self.assertIsNone(snapshot.display_name)
        # use volume.api to update name
        volume_api = cinder.volume.api.API()
        update_dict = {'display_name': 'test update name'}
        volume_api.update_snapshot(self.context, snapshot, update_dict)
        # read changes from db
        snap = objects.Snapshot.get_by_id(context.get_admin_context(),
                                          snapshot_id)
        self.assertEqual('test update name', snap.display_name)

    @mock.patch.object(QUOTAS, 'reserve',
                       side_effect = OVER_SNAPSHOT_QUOTA_EXCEPTION)
    def test_existing_snapshot_failed_quota_reserve(self, mock_reserve):
        vol = tests_utils.create_volume(self.context)
        snap = tests_utils.create_snapshot(self.context, vol.id)
        with mock.patch.object(
                self.volume.driver,
                'manage_existing_snapshot_get_size') as mock_get_size:
            mock_get_size.return_value = 1
            self.assertRaises(exception.SnapshotLimitExceeded,
                              self.volume.manage_existing_snapshot,
                              self.context,
                              snap)
