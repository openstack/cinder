# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
"""
Tests for Volume Code.

"""

import datetime
import os
import re
import shutil
import tempfile

import mox
from oslo.config import cfg

from cinder.brick.iscsi import iscsi
from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder.openstack.common import importutils
from cinder.openstack.common.notifier import api as notifier_api
from cinder.openstack.common.notifier import test_notifier
from cinder.openstack.common import rpc
import cinder.policy
from cinder import quota
from cinder import test
from cinder.tests import conf_fixture
from cinder.tests.image import fake as fake_image
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume.drivers import lvm


QUOTAS = quota.QUOTAS

CONF = cfg.CONF

fake_opt = [
    cfg.StrOpt('fake_opt', default='fake', help='fake opts')
]


class VolumeTestCase(test.TestCase):
    """Test Case for volumes."""

    def setUp(self):
        super(VolumeTestCase, self).setUp()
        vol_tmpdir = tempfile.mkdtemp()
        self.flags(connection_type='fake',
                   volumes_dir=vol_tmpdir,
                   notification_driver=[test_notifier.__name__])
        self.volume = importutils.import_object(CONF.volume_manager)
        self.context = context.get_admin_context()
        self.stubs.Set(iscsi.TgtAdm, '_get_target', self.fake_get_target)
        fake_image.stub_out_image_service(self.stubs)
        test_notifier.NOTIFICATIONS = []

    def tearDown(self):
        try:
            shutil.rmtree(CONF.volumes_dir)
        except OSError:
            pass
        notifier_api._reset_drivers()
        super(VolumeTestCase, self).tearDown()

    def fake_get_target(obj, iqn):
        return 1

    @staticmethod
    def _create_volume(size=0, snapshot_id=None, image_id=None,
                       source_volid=None, metadata=None, status="creating"):
        """Create a volume object."""
        vol = {}
        vol['size'] = size
        vol['snapshot_id'] = snapshot_id
        vol['image_id'] = image_id
        vol['source_volid'] = source_volid
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['availability_zone'] = CONF.storage_availability_zone
        vol['status'] = status
        vol['attach_status'] = "detached"
        vol['host'] = CONF.host
        if metadata is not None:
            vol['metadata'] = metadata
        return db.volume_create(context.get_admin_context(), vol)

    def test_init_host_clears_downloads(self):
        """Test that init_host will unwedge a volume stuck in downloading."""
        volume = self._create_volume(status='downloading')
        volume_id = volume['id']
        self.volume.init_host()
        volume = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEquals(volume['status'], "error")
        self.volume.delete_volume(self.context, volume_id)

    def test_create_delete_volume(self):
        """Test volume can be created and deleted."""
        # Need to stub out reserve, commit, and rollback
        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit(context, reservations, project_id=None):
            pass

        def fake_rollback(context, reservations, project_id=None):
            pass

        self.stubs.Set(QUOTAS, "reserve", fake_reserve)
        self.stubs.Set(QUOTAS, "commit", fake_commit)
        self.stubs.Set(QUOTAS, "rollback", fake_rollback)

        volume = self._create_volume()
        volume_id = volume['id']
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 0)
        self.volume.create_volume(self.context, volume_id)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        msg = test_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg['event_type'], 'volume.create.start')
        expected = {
            'status': 'creating',
            'display_name': None,
            'availability_zone': 'nova',
            'tenant_id': 'fake',
            'created_at': 'DONTCARE',
            'volume_id': volume_id,
            'volume_type': None,
            'snapshot_id': None,
            'user_id': 'fake',
            'launched_at': '',
            'size': 0,
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = test_notifier.NOTIFICATIONS[1]
        self.assertEqual(msg['event_type'], 'volume.create.end')
        expected = {
            'status': 'available',
            'display_name': None,
            'availability_zone': 'nova',
            'tenant_id': 'fake',
            'created_at': 'DONTCARE',
            'volume_id': volume_id,
            'volume_type': None,
            'snapshot_id': None,
            'user_id': 'fake',
            'launched_at': '',
            'size': 0,
        }
        self.assertDictMatch(msg['payload'], expected)
        self.assertEqual(volume_id, db.volume_get(context.get_admin_context(),
                         volume_id).id)

        self.volume.delete_volume(self.context, volume_id)
        vol = db.volume_get(context.get_admin_context(read_deleted='yes'),
                            volume_id)
        self.assertEquals(vol['status'], 'deleted')
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 4)
        msg = test_notifier.NOTIFICATIONS[2]
        self.assertEqual(msg['event_type'], 'volume.delete.start')
        expected = {
            'status': 'available',
            'display_name': None,
            'availability_zone': 'nova',
            'tenant_id': 'fake',
            'created_at': 'DONTCARE',
            'volume_id': volume_id,
            'volume_type': None,
            'snapshot_id': None,
            'user_id': 'fake',
            'launched_at': 'DONTCARE',
            'size': 0,
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = test_notifier.NOTIFICATIONS[3]
        self.assertEqual(msg['event_type'], 'volume.delete.end')
        expected = {
            'status': 'available',
            'display_name': None,
            'availability_zone': 'nova',
            'tenant_id': 'fake',
            'created_at': 'DONTCARE',
            'volume_id': volume_id,
            'volume_type': None,
            'snapshot_id': None,
            'user_id': 'fake',
            'launched_at': 'DONTCARE',
            'size': 0,
        }
        self.assertDictMatch(msg['payload'], expected)
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_create_delete_volume_with_metadata(self):
        """Test volume can be created with metadata and deleted."""
        test_meta = {'fake_key': 'fake_value'}
        volume = self._create_volume(0, None, metadata=test_meta)
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        result_meta = {
            volume.volume_metadata[0].key: volume.volume_metadata[0].value}
        self.assertEqual(result_meta, test_meta)

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_create_volume_with_invalid_metadata(self):
        """Test volume create with too much metadata fails."""
        volume_api = cinder.volume.api.API()
        test_meta = {'fake_key': 'fake_value' * 256}
        self.assertRaises(exception.InvalidVolumeMetadataSize,
                          volume_api.create,
                          self.context,
                          1,
                          'name',
                          'description',
                          None,
                          None,
                          None,
                          test_meta)

    def test_create_volume_with_volume_type(self):
        """Test volume creation with default volume type."""
        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit(context, reservations, project_id=None):
            pass

        def fake_rollback(context, reservations, project_id=None):
            pass

        self.stubs.Set(QUOTAS, "reserve", fake_reserve)
        self.stubs.Set(QUOTAS, "commit", fake_commit)
        self.stubs.Set(QUOTAS, "rollback", fake_rollback)

        volume_api = cinder.volume.api.API()

        # Create volume with default volume type while default
        # volume type doesn't exist, volume_type_id should be NULL
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description')
        self.assertEquals(volume['volume_type_id'], None)

        # Create default volume type
        vol_type = conf_fixture.def_vol_type
        db.volume_type_create(context.get_admin_context(),
                              dict(name=vol_type, extra_specs={}))

        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 vol_type)

        # Create volume with default volume type
        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description')
        self.assertEquals(volume['volume_type_id'], db_vol_type.get('id'))

        # Create volume with specific volume type
        vol_type = 'test'
        db.volume_type_create(context.get_admin_context(),
                              dict(name=vol_type, extra_specs={}))
        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 vol_type)

        volume = volume_api.create(self.context,
                                   1,
                                   'name',
                                   'description',
                                   volume_type=db_vol_type)
        self.assertEquals(volume['volume_type_id'], db_vol_type.get('id'))

    def test_delete_busy_volume(self):
        """Test volume survives deletion if driver reports it as busy."""
        volume = self._create_volume()
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)

        self.mox.StubOutWithMock(self.volume.driver, 'delete_volume')
        self.volume.driver.delete_volume(
            mox.IgnoreArg()).AndRaise(exception.VolumeIsBusy(
                                      volume_name='fake'))
        self.mox.ReplayAll()
        res = self.volume.delete_volume(self.context, volume_id)
        self.assertEqual(True, res)
        volume_ref = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(volume_id, volume_ref.id)
        self.assertEqual("available", volume_ref.status)

        self.mox.UnsetStubs()
        self.volume.delete_volume(self.context, volume_id)

    def test_create_volume_from_snapshot(self):
        """Test volume can be created from a snapshot."""
        volume_src = self._create_volume()
        self.volume.create_volume(self.context, volume_src['id'])
        snapshot_id = self._create_snapshot(volume_src['id'])['id']
        self.volume.create_snapshot(self.context, volume_src['id'],
                                    snapshot_id)
        volume_dst = self._create_volume(0, snapshot_id)
        self.volume.create_volume(self.context, volume_dst['id'], snapshot_id)
        self.assertEqual(volume_dst['id'],
                         db.volume_get(
                             context.get_admin_context(),
                             volume_dst['id']).id)
        self.assertEqual(snapshot_id,
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).snapshot_id)

        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume_src['id'])

    def test_create_volume_from_snapshot_fail_bad_size(self):
        """Test volume can't be created from snapshot with bad volume size."""
        volume_api = cinder.volume.api.API()
        snapshot = dict(id=1234,
                        status='available',
                        volume_size=10)
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          size=1,
                          name='fake_name',
                          description='fake_desc',
                          snapshot=snapshot)

    def test_create_volume_with_invalid_exclusive_options(self):
        """Test volume create with multiple exclusive options fails."""
        volume_api = cinder.volume.api.API()
        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          1,
                          'name',
                          'description',
                          snapshot='fake_id',
                          image_id='fake_id',
                          source_volume='fake_id')

    def test_too_big_volume(self):
        """Ensure failure if a too large of a volume is requested."""
        # FIXME(vish): validation needs to move into the data layer in
        #              volume_create
        return True
        try:
            volume = self._create_volume(1001)
            self.volume.create_volume(self.context, volume)
            self.fail("Should have thrown TypeError")
        except TypeError:
            pass

    def test_run_attach_detach_volume(self):
        """Make sure volume can be attached and detached from instance."""
        mountpoint = "/dev/sdf"
        # attach volume to the instance then to detach
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        volume = self._create_volume()
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        self.volume.attach_volume(self.context, volume_id, instance_uuid,
                                  None, mountpoint)
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")
        self.assertEqual(vol['mountpoint'], mountpoint)
        self.assertEqual(vol['instance_uuid'], instance_uuid)
        self.assertEqual(vol['attached_host'], None)

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual(vol['status'], "available")

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

        # attach volume to the host then to detach
        volume = self._create_volume()
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        self.volume.attach_volume(self.context, volume_id, None,
                                  'fake_host', mountpoint)
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")
        self.assertEqual(vol['mountpoint'], mountpoint)
        self.assertEqual(vol['instance_uuid'], None)
        # sanitized, conforms to RFC-952 and RFC-1123 specs.
        self.assertEqual(vol['attached_host'], 'fake-host')

        self.assertRaises(exception.VolumeAttached,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        self.volume.detach_volume(self.context, volume_id)
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual(vol['status'], "available")

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.VolumeNotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_concurrent_volumes_get_different_targets(self):
        """Ensure multiple concurrent volumes get different targets."""
        volume_ids = []
        targets = []

        def _check(volume_id):
            """Make sure targets aren't duplicated."""
            volume_ids.append(volume_id)
            admin_context = context.get_admin_context()
            iscsi_target = db.volume_get_iscsi_target_num(admin_context,
                                                          volume_id)
            self.assert_(iscsi_target not in targets)
            targets.append(iscsi_target)

        total_slots = CONF.iscsi_num_targets
        for _index in xrange(total_slots):
            self._create_volume()
        for volume_id in volume_ids:
            self.volume.delete_volume(self.context, volume_id)

    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass

    @staticmethod
    def _create_snapshot(volume_id, size='0'):
        """Create a snapshot object."""
        snap = {}
        snap['volume_size'] = size
        snap['user_id'] = 'fake'
        snap['project_id'] = 'fake'
        snap['volume_id'] = volume_id
        snap['status'] = "creating"
        return db.snapshot_create(context.get_admin_context(), snap)

    def test_create_delete_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume = self._create_volume()
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 0)
        self.volume.create_volume(self.context, volume['id'])
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 2)
        snapshot_id = self._create_snapshot(volume['id'])['id']
        self.volume.create_snapshot(self.context, volume['id'], snapshot_id)
        self.assertEqual(snapshot_id,
                         db.snapshot_get(context.get_admin_context(),
                                         snapshot_id).id)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 4)
        msg = test_notifier.NOTIFICATIONS[2]
        self.assertEquals(msg['event_type'], 'snapshot.create.start')
        expected = {
            'created_at': 'DONTCARE',
            'deleted': '',
            'display_name': None,
            'snapshot_id': snapshot_id,
            'status': 'creating',
            'tenant_id': 'fake',
            'user_id': 'fake',
            'volume_id': volume['id'],
            'volume_size': 0,
            'availability_zone': 'nova'
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = test_notifier.NOTIFICATIONS[3]
        self.assertEquals(msg['event_type'], 'snapshot.create.end')
        expected = {
            'created_at': 'DONTCARE',
            'deleted': '',
            'display_name': None,
            'snapshot_id': snapshot_id,
            'status': 'creating',
            'tenant_id': 'fake',
            'user_id': 'fake',
            'volume_id': volume['id'],
            'volume_size': 0,
            'availability_zone': 'nova'
        }
        self.assertDictMatch(msg['payload'], expected)

        self.volume.delete_snapshot(self.context, snapshot_id)
        self.assertEquals(len(test_notifier.NOTIFICATIONS), 6)
        msg = test_notifier.NOTIFICATIONS[4]
        self.assertEquals(msg['event_type'], 'snapshot.delete.start')
        expected = {
            'created_at': 'DONTCARE',
            'deleted': '',
            'display_name': None,
            'snapshot_id': snapshot_id,
            'status': 'available',
            'tenant_id': 'fake',
            'user_id': 'fake',
            'volume_id': volume['id'],
            'volume_size': 0,
            'availability_zone': 'nova'
        }
        self.assertDictMatch(msg['payload'], expected)
        msg = test_notifier.NOTIFICATIONS[5]
        self.assertEquals(msg['event_type'], 'snapshot.delete.end')
        expected = {
            'created_at': 'DONTCARE',
            'deleted': '',
            'display_name': None,
            'snapshot_id': snapshot_id,
            'status': 'available',
            'tenant_id': 'fake',
            'user_id': 'fake',
            'volume_id': volume['id'],
            'volume_size': 0,
            'availability_zone': 'nova'
        }
        self.assertDictMatch(msg['payload'], expected)

        snap = db.snapshot_get(context.get_admin_context(read_deleted='yes'),
                               snapshot_id)
        self.assertEquals(snap['status'], 'deleted')
        self.assertRaises(exception.NotFound,
                          db.snapshot_get,
                          self.context,
                          snapshot_id)
        self.volume.delete_volume(self.context, volume['id'])

    def test_cant_delete_volume_in_use(self):
        """Test volume can't be deleted in invalid stats."""
        # create a volume and assign to host
        volume = self._create_volume()
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'in-use'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        # 'in-use' status raises InvalidVolume
        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete,
                          self.context,
                          volume)

        # clean up
        self.volume.delete_volume(self.context, volume['id'])

    def test_force_delete_volume(self):
        """Test volume can be forced to delete."""
        # create a volume and assign to host
        volume = self._create_volume()
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'error_deleting'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        # 'error_deleting' volumes can't be deleted
        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete,
                          self.context,
                          volume)

        # delete with force
        volume_api.delete(self.context, volume, force=True)

        # status is deleting
        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEquals(volume['status'], 'deleting')

        # clean up
        self.volume.delete_volume(self.context, volume['id'])

    def test_cant_force_delete_attached_volume(self):
        """Test volume can't be force delete in attached state"""
        volume = self._create_volume()
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'in-use'
        volume['attach_status'] = 'attached'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.VolumeAttached,
                          volume_api.delete,
                          self.context,
                          volume,
                          force=True)

        self.volume.delete_volume(self.context, volume['id'])

    def test_cant_delete_volume_with_snapshots(self):
        """Test volume can't be deleted with dependent snapshots."""
        volume = self._create_volume()
        self.volume.create_volume(self.context, volume['id'])
        snapshot_id = self._create_snapshot(volume['id'])['id']
        self.volume.create_snapshot(self.context, volume['id'], snapshot_id)
        self.assertEqual(snapshot_id,
                         db.snapshot_get(context.get_admin_context(),
                                         snapshot_id).id)

        volume['status'] = 'available'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.InvalidVolume,
                          volume_api.delete,
                          self.context,
                          volume)
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume['id'])

    def test_can_delete_errored_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume = self._create_volume()
        self.volume.create_volume(self.context, volume['id'])
        snapshot_id = self._create_snapshot(volume['id'])['id']
        self.volume.create_snapshot(self.context, volume['id'], snapshot_id)
        snapshot = db.snapshot_get(context.get_admin_context(),
                                   snapshot_id)

        volume_api = cinder.volume.api.API()

        snapshot['status'] = 'badstatus'
        self.assertRaises(exception.InvalidSnapshot,
                          volume_api.delete_snapshot,
                          self.context,
                          snapshot)

        snapshot['status'] = 'error'
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_snapshot_force(self):
        """Test snapshot in use can be created forcibly."""

        def fake_cast(ctxt, topic, msg):
            pass
        self.stubs.Set(rpc, 'cast', fake_cast)
        instance_uuid = '12345678-1234-5678-1234-567812345678'
        # create volume and attach to the instance
        volume = self._create_volume()
        self.volume.create_volume(self.context, volume['id'])
        db.volume_attached(self.context, volume['id'], instance_uuid,
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
        db.snapshot_destroy(self.context, snapshot_ref['id'])
        db.volume_destroy(self.context, volume['id'])

        # create volume and attach to the host
        volume = self._create_volume()
        self.volume.create_volume(self.context, volume['id'])
        db.volume_attached(self.context, volume['id'], None,
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
        db.snapshot_destroy(self.context, snapshot_ref['id'])
        db.volume_destroy(self.context, volume['id'])

    def test_delete_busy_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume = self._create_volume()
        volume_id = volume['id']
        self.volume.create_volume(self.context, volume_id)
        snapshot_id = self._create_snapshot(volume_id)['id']
        self.volume.create_snapshot(self.context, volume_id, snapshot_id)

        self.mox.StubOutWithMock(self.volume.driver, 'delete_snapshot')
        self.volume.driver.delete_snapshot(
            mox.IgnoreArg()).AndRaise(
                exception.SnapshotIsBusy(snapshot_name='fake'))
        self.mox.ReplayAll()
        self.volume.delete_snapshot(self.context, snapshot_id)
        snapshot_ref = db.snapshot_get(self.context, snapshot_id)
        self.assertEqual(snapshot_id, snapshot_ref.id)
        self.assertEqual("available", snapshot_ref.status)

        self.mox.UnsetStubs()
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume_id)

    def _create_volume_from_image(self, fakeout_copy_image_to_volume=False):
        """Call copy image to volume, Test the status of volume after calling
        copying image to volume.
        """
        def fake_local_path(volume):
            return dst_path

        def fake_copy_image_to_volume(context, volume,
                                      image_service, image_id):
            pass

        def fake_fetch_to_raw(context, image_service, image_id, vol_path):
            pass

        dst_fd, dst_path = tempfile.mkstemp()
        os.close(dst_fd)
        self.stubs.Set(self.volume.driver, 'local_path', fake_local_path)
        self.stubs.Set(image_utils, 'fetch_to_raw', fake_fetch_to_raw)
        if fakeout_copy_image_to_volume:
            self.stubs.Set(self.volume, '_copy_image_to_volume',
                           fake_copy_image_to_volume)

        image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        volume_id = self._create_volume(status='creating')['id']
        # creating volume testdata
        try:
            self.volume.create_volume(self.context,
                                      volume_id,
                                      image_id=image_id)
        finally:
            # cleanup
            os.unlink(dst_path)
            volume = db.volume_get(self.context, volume_id)
            return volume

    def test_create_volume_from_image_status_available(self):
        """Verify that before copying image to volume, it is in available
        state.
        """
        volume = self._create_volume_from_image()
        self.assertEqual(volume['status'], 'available')
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_volume_from_image_exception(self):
        """Verify that create volume from image, the volume status is
        'downloading'.
        """
        dst_fd, dst_path = tempfile.mkstemp()
        os.close(dst_fd)

        self.stubs.Set(self.volume.driver, 'local_path', lambda x: dst_path)

        image_id = 'aaaaaaaa-0000-0000-0000-000000000000'
        # creating volume testdata
        volume_id = 1
        db.volume_create(self.context,
                         {'id': volume_id,
                          'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'creating',
                          'host': 'dummy'})

        self.assertRaises(exception.ImageNotFound,
                          self.volume.create_volume,
                          self.context,
                          volume_id, None, None, None,
                          None,
                          image_id)
        volume = db.volume_get(self.context, volume_id)
        self.assertEqual(volume['status'], "error")
        # cleanup
        db.volume_destroy(self.context, volume_id)
        os.unlink(dst_path)

    def test_copy_volume_to_image_status_available(self):
        dst_fd, dst_path = tempfile.mkstemp()
        os.close(dst_fd)

        def fake_local_path(volume):
            return dst_path

        self.stubs.Set(self.volume.driver, 'local_path', fake_local_path)

        image_meta = {
            'id': '70a599e0-31e7-49b7-b260-868f441e862b',
            'container_format': 'bare',
            'disk_format': 'raw'}

        # creating volume testdata
        volume_id = 1
        db.volume_create(self.context,
                         {'id': volume_id,
                          'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'uploading',
                          'instance_uuid': None,
                          'host': 'dummy'})

        try:
            # start test
            self.volume.copy_volume_to_image(self.context,
                                             volume_id,
                                             image_meta)

            volume = db.volume_get(self.context, volume_id)
            self.assertEqual(volume['status'], 'available')
        finally:
            # cleanup
            db.volume_destroy(self.context, volume_id)
            os.unlink(dst_path)

    def test_copy_volume_to_image_status_use(self):
        dst_fd, dst_path = tempfile.mkstemp()
        os.close(dst_fd)

        def fake_local_path(volume):
            return dst_path

        self.stubs.Set(self.volume.driver, 'local_path', fake_local_path)

        image_meta = {
            'id': 'a440c04b-79fa-479c-bed1-0b816eaec379',
            'container_format': 'bare',
            'disk_format': 'raw'}
        # creating volume testdata
        volume_id = 1
        db.volume_create(
            self.context,
            {'id': volume_id,
             'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
             'display_description': 'Test Desc',
             'size': 20,
             'status': 'uploading',
             'instance_uuid': 'b21f957d-a72f-4b93-b5a5-45b1161abb02',
             'host': 'dummy'})

        try:
            # start test
            self.volume.copy_volume_to_image(self.context,
                                             volume_id,
                                             image_meta)

            volume = db.volume_get(self.context, volume_id)
            self.assertEqual(volume['status'], 'in-use')
        finally:
            # cleanup
            db.volume_destroy(self.context, volume_id)
            os.unlink(dst_path)

    def test_copy_volume_to_image_exception(self):
        dst_fd, dst_path = tempfile.mkstemp()
        os.close(dst_fd)

        def fake_local_path(volume):
            return dst_path

        self.stubs.Set(self.volume.driver, 'local_path', fake_local_path)

        image_meta = {
            'id': 'aaaaaaaa-0000-0000-0000-000000000000',
            'container_format': 'bare',
            'disk_format': 'raw'}
        # creating volume testdata
        volume_id = 1
        db.volume_create(self.context,
                         {'id': volume_id,
                          'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                          'display_description': 'Test Desc',
                          'size': 20,
                          'status': 'in-use',
                          'host': 'dummy'})

        try:
            # start test
            self.assertRaises(exception.ImageNotFound,
                              self.volume.copy_volume_to_image,
                              self.context,
                              volume_id,
                              image_meta)

            volume = db.volume_get(self.context, volume_id)
            self.assertEqual(volume['status'], 'available')
        finally:
            # cleanup
            db.volume_destroy(self.context, volume_id)
            os.unlink(dst_path)

    def test_create_volume_from_exact_sized_image(self):
        """Verify that an image which is exactly the same size as the
        volume, will work correctly.
        """
        class _FakeImageService:
            def __init__(self, db_driver=None, image_service=None):
                pass

            def show(self, context, image_id):
                return {'size': 2 * 1024 * 1024 * 1024,
                        'disk_format': 'raw',
                        'container_format': 'bare'}

        image_id = '70a599e0-31e7-49b7-b260-868f441e862b'

        try:
            volume_id = None
            volume_api = cinder.volume.api.API(
                image_service=_FakeImageService())
            volume = volume_api.create(self.context, 2, 'name', 'description',
                                       image_id=1)
            volume_id = volume['id']
            self.assertEqual(volume['status'], 'creating')

        finally:
            # cleanup
            db.volume_destroy(self.context, volume_id)

    def test_create_volume_from_oversized_image(self):
        """Verify that an image which is too big will fail correctly."""
        class _FakeImageService:
            def __init__(self, db_driver=None, image_service=None):
                pass

            def show(self, context, image_id):
                return {'size': 2 * 1024 * 1024 * 1024 + 1,
                        'disk_format': 'raw',
                        'container_format': 'bare'}

        image_id = '70a599e0-31e7-49b7-b260-868f441e862b'

        volume_api = cinder.volume.api.API(image_service=_FakeImageService())

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context, 2,
                          'name', 'description', image_id=1)

    def test_create_volume_with_mindisk_error(self):
        """Verify volumes smaller than image minDisk will cause an error."""
        class _FakeImageService:
            def __init__(self, db_driver=None, image_service=None):
                pass

            def show(self, context, image_id):
                return {'size': 2 * 1024 * 1024 * 1024,
                        'disk_format': 'raw',
                        'container_format': 'bare',
                        'min_disk': 5}

        image_id = '70a599e0-31e7-49b7-b260-868f441e862b'

        volume_api = cinder.volume.api.API(image_service=_FakeImageService())

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context, 2,
                          'name', 'description', image_id=1)

    def _do_test_create_volume_with_size(self, size):
        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit(context, reservations, project_id=None):
            pass

        def fake_rollback(context, reservations, project_id=None):
            pass

        self.stubs.Set(QUOTAS, "reserve", fake_reserve)
        self.stubs.Set(QUOTAS, "commit", fake_commit)
        self.stubs.Set(QUOTAS, "rollback", fake_rollback)

        volume_api = cinder.volume.api.API()

        volume = volume_api.create(self.context,
                                   size,
                                   'name',
                                   'description')
        self.assertEquals(volume['size'], int(size))

    def test_create_volume_int_size(self):
        """Test volume creation with int size."""
        self._do_test_create_volume_with_size(2)

    def test_create_volume_string_size(self):
        """Test volume creation with string size."""
        self._do_test_create_volume_with_size('2')

    def test_create_volume_with_bad_size(self):
        def fake_reserve(context, expire=None, project_id=None, **deltas):
            return ["RESERVATION"]

        def fake_commit(context, reservations, project_id=None):
            pass

        def fake_rollback(context, reservations, project_id=None):
            pass

        self.stubs.Set(QUOTAS, "reserve", fake_reserve)
        self.stubs.Set(QUOTAS, "commit", fake_commit)
        self.stubs.Set(QUOTAS, "rollback", fake_rollback)

        volume_api = cinder.volume.api.API()

        self.assertRaises(exception.InvalidInput,
                          volume_api.create,
                          self.context,
                          '2Gb',
                          'name',
                          'description')

    def test_begin_roll_detaching_volume(self):
        """Test begin_detaching and roll_detaching functions."""
        volume = self._create_volume()
        volume_api = cinder.volume.api.API()
        volume_api.begin_detaching(self.context, volume)
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual(volume['status'], "detaching")
        volume_api.roll_detaching(self.context, volume)
        volume = db.volume_get(self.context, volume['id'])
        self.assertEqual(volume['status'], "in-use")

    def test_volume_api_update(self):
        # create a raw vol
        volume = self._create_volume()
        # use volume.api to update name
        volume_api = cinder.volume.api.API()
        update_dict = {'display_name': 'test update name'}
        volume_api.update(self.context, volume, update_dict)
        # read changes from db
        vol = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEquals(vol['display_name'], 'test update name')

    def test_volume_api_update_snapshot(self):
        # create raw snapshot
        volume = self._create_volume()
        snapshot = self._create_snapshot(volume['id'])
        self.assertEquals(snapshot['display_name'], None)
        # use volume.api to update name
        volume_api = cinder.volume.api.API()
        update_dict = {'display_name': 'test update name'}
        volume_api.update_snapshot(self.context, snapshot, update_dict)
        # read changes from db
        snap = db.snapshot_get(context.get_admin_context(), snapshot['id'])
        self.assertEquals(snap['display_name'], 'test update name')

    def test_volume_get_active_by_window(self):
        # Find all all volumes valid within a timeframe window.
        try:  # Not in window
            db.volume_create(
                self.context,
                {
                    'id': 1,
                    'host': 'devstack',
                    'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'deleted': True, 'status': 'deleted',
                    'deleted_at': datetime.datetime(1, 2, 1, 1, 1, 1),
                }
            )
        except exception.VolumeNotFound:
            pass

        try:  # In - deleted in window
            db.volume_create(
                self.context,
                {
                    'id': 2,
                    'host': 'devstack',
                    'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'deleted': True, 'status': 'deleted',
                    'deleted_at': datetime.datetime(1, 3, 10, 1, 1, 1),
                }
            )
        except exception.VolumeNotFound:
            pass

        try:  # In - deleted after window
            db.volume_create(
                self.context,
                {
                    'id': 3,
                    'host': 'devstack',
                    'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'deleted': True, 'status': 'deleted',
                    'deleted_at': datetime.datetime(1, 5, 1, 1, 1, 1),
                }
            )
        except exception.VolumeNotFound:
            pass

        # In - created in window
        db.volume_create(
            self.context,
            {
                'id': 4,
                'host': 'devstack',
                'created_at': datetime.datetime(1, 3, 10, 1, 1, 1),
            }
        )

        # Not of window.
        db.volume_create(
            self.context,
            {
                'id': 5,
                'host': 'devstack',
                'created_at': datetime.datetime(1, 5, 1, 1, 1, 1),
            }
        )

        volumes = db.volume_get_active_by_window(
            self.context,
            datetime.datetime(1, 3, 1, 1, 1, 1),
            datetime.datetime(1, 4, 1, 1, 1, 1))
        self.assertEqual(len(volumes), 3)
        self.assertEqual(volumes[0].id, u'2')
        self.assertEqual(volumes[1].id, u'3')
        self.assertEqual(volumes[2].id, u'4')

    def test_snapshot_get_active_by_window(self):
        # Find all all snapshots valid within a timeframe window.
        vol = db.volume_create(self.context, {'id': 1})

        try:  # Not in window
            db.snapshot_create(
                self.context,
                {
                    'id': 1,
                    'host': 'devstack',
                    'volume_id': 1,
                    'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'deleted': True, 'status': 'deleted',
                    'deleted_at': datetime.datetime(1, 2, 1, 1, 1, 1),
                }
            )
        except exception.SnapshotNotFound:
            pass

        try:  # In - deleted in window
            db.snapshot_create(
                self.context,
                {
                    'id': 2,
                    'host': 'devstack',
                    'volume_id': 1,
                    'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'deleted': True, 'status': 'deleted',
                    'deleted_at': datetime.datetime(1, 3, 10, 1, 1, 1),
                }
            )
        except exception.SnapshotNotFound:
            pass

        try:  # In - deleted after window
            db.snapshot_create(
                self.context,
                {
                    'id': 3,
                    'host': 'devstack',
                    'volume_id': 1,
                    'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'deleted': True, 'status': 'deleted',
                    'deleted_at': datetime.datetime(1, 5, 1, 1, 1, 1),
                }
            )
        except exception.SnapshotNotFound:
            pass

        # In - created in window
        db.snapshot_create(
            self.context,
            {
                'id': 4,
                'host': 'devstack',
                'volume_id': 1,
                'created_at': datetime.datetime(1, 3, 10, 1, 1, 1),
            }
        )

        # Not of window.
        db.snapshot_create(
            self.context,
            {
                'id': 5,
                'host': 'devstack',
                'volume_id': 1,
                'created_at': datetime.datetime(1, 5, 1, 1, 1, 1),
            }
        )

        snapshots = db.snapshot_get_active_by_window(
            self.context,
            datetime.datetime(1, 3, 1, 1, 1, 1),
            datetime.datetime(1, 4, 1, 1, 1, 1))
        self.assertEqual(len(snapshots), 3)
        self.assertEqual(snapshots[0].id, u'2')
        self.assertEqual(snapshots[1].id, u'3')
        self.assertEqual(snapshots[2].id, u'4')

    def test_extend_volume(self):
        """Test volume can be extended."""
        # create a volume and assign to host
        volume = self._create_volume(2)
        self.volume.create_volume(self.context, volume['id'])
        volume['status'] = 'available'
        volume['host'] = 'fakehost'

        volume_api = cinder.volume.api.API()

        # Extend fails when new_size < orig_size
        self.assertRaises(exception.InvalidInput,
                          volume_api.extend,
                          self.context,
                          volume,
                          1)

        # Extend fails when new_size == orig_size
        self.assertRaises(exception.InvalidInput,
                          volume_api.extend,
                          self.context,
                          volume,
                          2)

        # works when new_size > orig_size
        volume_api.extend(self.context, volume, 3)

        volume = db.volume_get(context.get_admin_context(), volume['id'])
        self.assertEquals(volume['size'], 3)

        # clean up
        self.volume.delete_volume(self.context, volume['id'])

    def test_create_volume_from_unelevated_context(self):
        """Test context does't change after volume creation failure."""
        def fake_create_volume(context, volume_ref, snapshot_ref,
                               sourcevol_ref, image_service, image_id,
                               image_location):
            raise exception.CinderException('fake exception')

        def fake_reschedule_or_error(context, volume_id, exc_info,
                                     snapshot_id, image_id, request_spec,
                                     filter_properties):
            self.assertFalse(context.is_admin)
            self.assertFalse('admin' in context.roles)
            #compare context passed in with the context we saved
            self.assertDictMatch(self.saved_ctxt.__dict__,
                                 context.__dict__)

        #create context for testing
        ctxt = self.context.deepcopy()
        if 'admin' in ctxt.roles:
            ctxt.roles.remove('admin')
            ctxt.is_admin = False
        #create one copy of context for future comparison
        self.saved_ctxt = ctxt.deepcopy()

        self.stubs.Set(self.volume, '_reschedule_or_error',
                       fake_reschedule_or_error)
        self.stubs.Set(self.volume, '_create_volume',
                       fake_create_volume)

        volume_src = self._create_volume()
        self.assertRaises(exception.CinderException,
                          self.volume.create_volume, ctxt, volume_src['id'])

    def test_create_volume_from_sourcevol(self):
        """Test volume can be created from a source volume."""
        def fake_create_cloned_volume(volume, src_vref):
            pass

        self.stubs.Set(self.volume.driver, 'create_cloned_volume',
                       fake_create_cloned_volume)
        volume_src = self._create_volume()
        self.volume.create_volume(self.context, volume_src['id'])
        volume_dst = self._create_volume(source_volid=volume_src['id'])
        self.volume.create_volume(self.context, volume_dst['id'],
                                  source_volid=volume_src['id'])
        self.assertEqual('available',
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).status)
        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_volume(self.context, volume_src['id'])

    def test_create_volume_from_sourcevol_with_glance_metadata(self):
        """Test glance metadata can be correctly copied to new volume."""
        def fake_create_cloned_volume(volume, src_vref):
            pass

        self.stubs.Set(self.volume.driver, 'create_cloned_volume',
                       fake_create_cloned_volume)
        volume_src = self._create_volume_from_image()
        self.volume.create_volume(self.context, volume_src['id'])
        volume_dst = self._create_volume(source_volid=volume_src['id'])
        self.volume.create_volume(self.context, volume_dst['id'],
                                  source_volid=volume_src['id'])
        self.assertEqual('available',
                         db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).status)
        src_glancemeta = db.volume_get(context.get_admin_context(),
                                       volume_src['id']).volume_glance_metadata
        dst_glancemeta = db.volume_get(context.get_admin_context(),
                                       volume_dst['id']).volume_glance_metadata
        for meta_src in src_glancemeta:
            for meta_dst in dst_glancemeta:
                if meta_dst.key == meta_src.key:
                    self.assertEquals(meta_dst.value, meta_src.value)
        self.volume.delete_volume(self.context, volume_src['id'])
        self.volume.delete_volume(self.context, volume_dst['id'])

    def test_create_volume_from_sourcevol_failed_clone(self):
        """Test src vol status will be restore by error handling code."""
        def fake_error_create_cloned_volume(volume, src_vref):
            db.volume_update(self.context, src_vref['id'], {'status': 'error'})
            raise exception.CinderException('fake exception')

        def fake_reschedule_or_error(context, volume_id, exc_info,
                                     snapshot_id, image_id, request_spec,
                                     filter_properties):
            pass

        self.stubs.Set(self.volume, '_reschedule_or_error',
                       fake_reschedule_or_error)
        self.stubs.Set(self.volume.driver, 'create_cloned_volume',
                       fake_error_create_cloned_volume)
        volume_src = self._create_volume()
        self.volume.create_volume(self.context, volume_src['id'])
        volume_dst = self._create_volume(0, source_volid=volume_src['id'])
        self.assertRaises(exception.CinderException,
                          self.volume.create_volume,
                          self.context,
                          volume_dst['id'], None, None, None, None, None,
                          volume_src['id'])
        self.assertEqual(volume_src['status'], 'creating')
        self.volume.delete_volume(self.context, volume_dst['id'])
        self.volume.delete_volume(self.context, volume_src['id'])

    def test_list_availability_zones_enabled_service(self):
        services = [
            {'availability_zone': 'ping', 'disabled': 0},
            {'availability_zone': 'ping', 'disabled': 1},
            {'availability_zone': 'pong', 'disabled': 0},
            {'availability_zone': 'pung', 'disabled': 1},
        ]

        def stub_service_get_all_by_topic(*args, **kwargs):
            return services

        self.stubs.Set(db, 'service_get_all_by_topic',
                       stub_service_get_all_by_topic)

        volume_api = cinder.volume.api.API()
        azs = volume_api.list_availability_zones()

        expected = (
            {'name': 'pung', 'available': False},
            {'name': 'pong', 'available': True},
            {'name': 'ping', 'available': True},
        )

        self.assertEqual(expected, azs)


class DriverTestCase(test.TestCase):
    """Base Test class for Drivers."""
    driver_name = "cinder.volume.driver.FakeBaseDriver"

    def setUp(self):
        super(DriverTestCase, self).setUp()
        vol_tmpdir = tempfile.mkdtemp()
        self.flags(volume_driver=self.driver_name,
                   volumes_dir=vol_tmpdir)
        self.volume = importutils.import_object(CONF.volume_manager)
        self.context = context.get_admin_context()
        self.output = ""
        self.stubs.Set(iscsi.TgtAdm, '_get_target', self.fake_get_target)

        def _fake_execute(_command, *_args, **_kwargs):
            """Fake _execute."""
            return self.output, None
        self.volume.driver.set_execute(_fake_execute)

    def tearDown(self):
        try:
            shutil.rmtree(CONF.volumes_dir)
        except OSError:
            pass
        super(DriverTestCase, self).tearDown()

    def fake_get_target(obj, iqn):
        return 1

    def _attach_volume(self):
        """Attach volumes to an instance."""
        return []

    def _detach_volume(self, volume_id_list):
        """Detach volumes from an instance."""
        for volume_id in volume_id_list:
            db.volume_detached(self.context, volume_id)
            self.volume.delete_volume(self.context, volume_id)


class VolumeDriverTestCase(DriverTestCase):
    """Test case for VolumeDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMVolumeDriver"

    def test_delete_busy_volume(self):
        """Test deleting a busy volume."""
        self.stubs.Set(self.volume.driver, '_volume_not_present',
                       lambda x: False)
        self.stubs.Set(self.volume.driver, '_delete_volume',
                       lambda x: False)
        # Want DriverTestCase._fake_execute to return 'o' so that
        # volume.driver.delete_volume() raises the VolumeIsBusy exception.
        self.output = 'o'
        self.assertRaises(exception.VolumeIsBusy,
                          self.volume.driver.delete_volume,
                          {'name': 'test1', 'size': 1024})
        # when DriverTestCase._fake_execute returns something other than
        # 'o' volume.driver.delete_volume() does not raise an exception.
        self.output = 'x'
        self.volume.driver.delete_volume({'name': 'test1', 'size': 1024})


class LVMVolumeDriverTestCase(DriverTestCase):
    """Test case for VolumeDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMVolumeDriver"

    def test_convert_blocksize_option(self):
        # Test invalid volume_dd_blocksize
        configuration = conf.Configuration(fake_opt, 'fake_group')
        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration)

        # Test valid volume_dd_blocksize
        bs, count = lvm_driver._calculate_count('10M', 1)
        self.assertEquals(bs, '10M')
        self.assertEquals(count, 103)

        bs, count = lvm_driver._calculate_count('1xBBB', 1)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)

        # Test volume_dd_blocksize with fraction
        bs, count = lvm_driver._calculate_count('1.3M', 1)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)

        # Test zero-size volume_dd_blocksize
        bs, count = lvm_driver._calculate_count('0M', 1)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)

        # Test negative volume_dd_blocksize
        bs, count = lvm_driver._calculate_count('-1M', 1)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)

        # Test non-digital volume_dd_blocksize
        bs, count = lvm_driver._calculate_count('ABM', 1)
        self.assertEquals(bs, '1M')
        self.assertEquals(count, 1024)

    def test_clear_volume(self):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.volume_clear = 'zero'
        configuration.volume_clear_size = 0
        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration)
        self.stubs.Set(lvm_driver, '_copy_volume', lambda *a, **kw: True)

        fake_volume = {'name': 'test1',
                       'volume_name': 'test1',
                       'id': 'test1'}

        # Test volume has 'size' field
        volume = dict(fake_volume, size='123')
        self.assertEquals(True, lvm_driver.clear_volume(volume))

        # Test volume has 'volume_size' field
        volume = dict(fake_volume, volume_size='123')
        self.assertEquals(True, lvm_driver.clear_volume(volume))

        # Test volume without 'size' field and 'volume_size' field
        volume = dict(fake_volume)
        self.assertEquals(None, lvm_driver.clear_volume(volume))


class ISCSITestCase(DriverTestCase):
    """Test Case for ISCSIDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMISCSIDriver"

    def _attach_volume(self):
        """Attach volumes to an instance."""
        volume_id_list = []
        for index in xrange(3):
            vol = {}
            vol['size'] = 0
            vol_ref = db.volume_create(self.context, vol)
            self.volume.create_volume(self.context, vol_ref['id'])
            vol_ref = db.volume_get(self.context, vol_ref['id'])

            # each volume has a different mountpoint
            mountpoint = "/dev/sd" + chr((ord('b') + index))
            instance_uuid = '12345678-1234-5678-1234-567812345678'
            db.volume_attached(self.context, vol_ref['id'], instance_uuid,
                               mountpoint)
            volume_id_list.append(vol_ref['id'])

        return volume_id_list

    def test_do_iscsi_discovery(self):
        configuration = mox.MockObject(conf.Configuration)
        configuration.iscsi_ip_address = '0.0.0.0'
        configuration.append_config_values(mox.IgnoreArg())

        iscsi_driver = driver.ISCSIDriver(configuration=configuration)
        iscsi_driver._execute = lambda *a, **kw: \
            ("%s dummy" % CONF.iscsi_ip_address, '')
        volume = {"name": "dummy",
                  "host": "0.0.0.0"}
        iscsi_driver._do_iscsi_discovery(volume)

    def test_get_iscsi_properties(self):
        volume = {"provider_location": '',
                  "id": "0",
                  "provider_auth": "a b c"}
        iscsi_driver = driver.ISCSIDriver()
        iscsi_driver._do_iscsi_discovery = lambda v: "0.0.0.0:0000,0 iqn:iqn 0"
        result = iscsi_driver._get_iscsi_properties(volume)
        self.assertEquals(result["target_portal"], "0.0.0.0:0000")
        self.assertEquals(result["target_iqn"], "iqn:iqn")
        self.assertEquals(result["target_lun"], 0)

    def test_get_volume_stats(self):
        def _emulate_vgs_execute(_command, *_args, **_kwargs):
            out = "  test1-volumes  5,52  0,52"
            out += " test2-volumes  5.52  0.52"
            return out, None

        self.volume.driver.set_execute(_emulate_vgs_execute)

        self.volume.driver._update_volume_status()

        stats = self.volume.driver._stats

        self.assertEquals(stats['total_capacity_gb'], float('5.52'))
        self.assertEquals(stats['free_capacity_gb'], float('0.52'))

    def test_validate_connector(self):
        iscsi_driver = driver.ISCSIDriver()
        # Validate a valid connector
        connector = {'ip': '10.0.0.2',
                     'host': 'fakehost',
                     'initiator': 'iqn.2012-07.org.fake:01'}
        iscsi_driver.validate_connector(connector)

        # Validate a connector without the initiator
        connector = {'ip': '10.0.0.2', 'host': 'fakehost'}
        self.assertRaises(exception.VolumeBackendAPIException,
                          iscsi_driver.validate_connector, connector)


class FibreChannelTestCase(DriverTestCase):
    """Test Case for FibreChannelDriver"""
    driver_name = "cinder.volume.driver.FibreChannelDriver"

    def test_initialize_connection(self):
        self.driver = driver.FibreChannelDriver()
        self.driver.do_setup(None)
        self.assertRaises(NotImplementedError,
                          self.driver.initialize_connection, {}, {})


class VolumePolicyTestCase(test.TestCase):

    def setUp(self):
        super(VolumePolicyTestCase, self).setUp()

        cinder.policy.reset()
        cinder.policy.init()

        self.context = context.get_admin_context()

    def tearDown(self):
        super(VolumePolicyTestCase, self).tearDown()
        cinder.policy.reset()

    def _set_rules(self, rules):
        cinder.common.policy.set_brain(cinder.common.policy.Brain(rules))

    def test_check_policy(self):
        self.mox.StubOutWithMock(cinder.policy, 'enforce')
        target = {
            'project_id': self.context.project_id,
            'user_id': self.context.user_id,
        }
        cinder.policy.enforce(self.context, 'volume:attach', target)
        self.mox.ReplayAll()
        cinder.volume.api.check_policy(self.context, 'attach')

    def test_check_policy_with_target(self):
        self.mox.StubOutWithMock(cinder.policy, 'enforce')
        target = {
            'project_id': self.context.project_id,
            'user_id': self.context.user_id,
            'id': 2,
        }
        cinder.policy.enforce(self.context, 'volume:attach', target)
        self.mox.ReplayAll()
        cinder.volume.api.check_policy(self.context, 'attach', {'id': 2})
