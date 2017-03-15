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
"""Tests for Volume Code."""

import ddt
import time

import mock
import os_brick
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import imageutils

from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base
import cinder.volume
from cinder.volume import api as volume_api
from cinder.volume.flows.manager import create_volume as create_volume_manager
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as volutils
from cinder.volume import volume_types


QUOTAS = quota.QUOTAS

CONF = cfg.CONF


def create_snapshot(volume_id, size=1, metadata=None, ctxt=None,
                    **kwargs):
    """Create a snapshot object."""
    metadata = metadata or {}
    snap = objects.Snapshot(ctxt or context.get_admin_context())
    snap.volume_size = size
    snap.user_id = kwargs.get('user_id', fake.USER_ID)
    snap.project_id = kwargs.get('project_id', fake.PROJECT_ID)
    snap.volume_id = volume_id
    snap.status = fields.SnapshotStatus.CREATING
    if metadata is not None:
        snap.metadata = metadata
    snap.update(kwargs)

    snap.create()
    return snap


@ddt.ddt
class VolumeMigrationTestCase(base.BaseVolumeTestCase):

    def setUp(self):
        super(VolumeMigrationTestCase, self).setUp()
        self._clear_patch = mock.patch('cinder.volume.utils.clear_volume',
                                       autospec=True)
        self._clear_patch.start()
        self.expected_status = 'available'

    def tearDown(self):
        super(VolumeMigrationTestCase, self).tearDown()
        self._clear_patch.stop()

    def test_migrate_volume_driver(self):
        """Test volume migration done by driver."""
        # Mock driver and rpc functions
        self.mock_object(self.volume.driver, 'migrate_volume',
                         lambda x, y, z, new_type_id=None: (
                             True, {'user_id': fake.USER_ID}))

        volume = tests_utils.create_volume(self.context, size=0,
                                           host=CONF.host,
                                           migration_status='migrating')
        host_obj = {'host': 'newhost', 'capabilities': {}}
        self.volume.migrate_volume(self.context, volume, host_obj, False)

        # check volume properties
        volume = objects.Volume.get_by_id(context.get_admin_context(),
                                          volume.id)
        self.assertEqual('newhost', volume.host)
        self.assertEqual('success', volume.migration_status)

    def _fake_create_volume(self, ctxt, volume, req_spec, filters,
                            allow_reschedule=True):
        return db.volume_update(ctxt, volume['id'],
                                {'status': self.expected_status})

    def test_migrate_volume_error(self):
        with mock.patch.object(self.volume.driver, 'migrate_volume') as \
                mock_migrate,\
                mock.patch.object(self.volume.driver, 'create_export') as \
                mock_create_export:

            # Exception case at self.driver.migrate_volume and create_export
            mock_migrate.side_effect = processutils.ProcessExecutionError
            mock_create_export.side_effect = processutils.ProcessExecutionError
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(processutils.ProcessExecutionError,
                              self.volume.migrate_volume,
                              self.context,
                              volume,
                              host_obj,
                              False)
            volume = objects.Volume.get_by_id(context.get_admin_context(),
                                              volume.id)
            self.assertEqual('error', volume.migration_status)
            self.assertEqual('available', volume.status)

    @mock.patch('cinder.compute.API')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                'migrate_volume_completion')
    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_migrate_volume_generic(self, volume_get,
                                    migrate_volume_completion,
                                    nova_api):
        fake_db_new_volume = {'status': 'available', 'id': fake.VOLUME_ID}
        fake_new_volume = fake_volume.fake_db_volume(**fake_db_new_volume)
        new_volume_obj = fake_volume.fake_volume_obj(self.context,
                                                     **fake_new_volume)
        host_obj = {'host': 'newhost', 'capabilities': {}}
        volume_get.return_value = fake_new_volume
        update_server_volume = nova_api.return_value.update_server_volume
        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host)
        with mock.patch.object(self.volume, '_copy_volume_data') as \
                mock_copy_volume:
            self.volume._migrate_volume_generic(self.context, volume,
                                                host_obj, None)
            mock_copy_volume.assert_called_with(self.context, volume,
                                                new_volume_obj,
                                                remote='dest')
            migrate_volume_completion.assert_called_with(
                self.context, volume, new_volume_obj, error=False)
            self.assertFalse(update_server_volume.called)

    @mock.patch('cinder.compute.API')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                'migrate_volume_completion')
    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_migrate_volume_generic_attached_volume(self, volume_get,
                                                    migrate_volume_completion,
                                                    nova_api):
        attached_host = 'some-host'
        fake_volume_id = fake.VOLUME_ID
        fake_db_new_volume = {'status': 'available', 'id': fake_volume_id}
        fake_new_volume = fake_volume.fake_db_volume(**fake_db_new_volume)
        host_obj = {'host': 'newhost', 'capabilities': {}}
        fake_uuid = fakes.get_fake_uuid()
        update_server_volume = nova_api.return_value.update_server_volume
        volume_get.return_value = fake_new_volume
        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host)
        volume_attach = tests_utils.attach_volume(
            self.context, volume['id'], fake_uuid, attached_host, '/dev/vda')
        self.assertIsNotNone(volume_attach['volume_attachment'][0]['id'])
        self.assertEqual(
            fake_uuid, volume_attach['volume_attachment'][0]['instance_uuid'])
        self.assertEqual('in-use', volume_attach['status'])
        self.volume._migrate_volume_generic(self.context, volume,
                                            host_obj, None)
        self.assertFalse(migrate_volume_completion.called)
        update_server_volume.assert_called_with(self.context, fake_uuid,
                                                volume['id'], fake_volume_id)

    @mock.patch('cinder.objects.volume.Volume.save')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.create_volume')
    @mock.patch('cinder.compute.API')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                'migrate_volume_completion')
    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_migrate_volume_generic_volume_from_snap(self, volume_get,
                                                     migrate_volume_completion,
                                                     nova_api, create_volume,
                                                     save):
        def fake_create_volume(*args, **kwargs):
            context, volume, request_spec, filter_properties = args
            fake_db = mock.Mock()
            task = create_volume_manager.ExtractVolumeSpecTask(fake_db)
            specs = task.execute(context, volume, {})
            self.assertEqual('raw', specs['type'])

        def fake_copy_volume_data_with_chk_param(*args, **kwargs):
            context, src, dest = args
            self.assertEqual(src['snapshot_id'], dest['snapshot_id'])

        fake_db_new_volume = {'status': 'available', 'id': fake.VOLUME_ID}
        fake_new_volume = fake_volume.fake_db_volume(**fake_db_new_volume)
        host_obj = {'host': 'newhost', 'capabilities': {}}
        volume_get.return_value = fake_new_volume

        volume_from_snap = tests_utils.create_volume(self.context, size=1,
                                                     host=CONF.host)
        volume_from_snap['snapshot_id'] = fake.SNAPSHOT_ID
        create_volume.side_effect = fake_create_volume

        with mock.patch.object(self.volume, '_copy_volume_data') as \
                mock_copy_volume:
            mock_copy_volume.side_effect = fake_copy_volume_data_with_chk_param
            self.volume._migrate_volume_generic(self.context, volume_from_snap,
                                                host_obj, None)

    @mock.patch('cinder.objects.volume.Volume.save')
    @mock.patch('cinder.volume.rpcapi.VolumeAPI.create_volume')
    @mock.patch('cinder.compute.API')
    @mock.patch('cinder.volume.manager.VolumeManager.'
                'migrate_volume_completion')
    @mock.patch('cinder.db.sqlalchemy.api.volume_get')
    def test_migrate_volume_generic_for_clone(self, volume_get,
                                              migrate_volume_completion,
                                              nova_api, create_volume, save):
        def fake_create_volume(*args, **kwargs):
            context, volume, request_spec, filter_properties = args
            fake_db = mock.Mock()
            task = create_volume_manager.ExtractVolumeSpecTask(fake_db)
            specs = task.execute(context, volume, {})
            self.assertEqual('raw', specs['type'])

        def fake_copy_volume_data_with_chk_param(*args, **kwargs):
            context, src, dest = args
            self.assertEqual(src['source_volid'], dest['source_volid'])

        fake_db_new_volume = {'status': 'available', 'id': fake.VOLUME_ID}
        fake_new_volume = fake_volume.fake_db_volume(**fake_db_new_volume)
        host_obj = {'host': 'newhost', 'capabilities': {}}
        volume_get.return_value = fake_new_volume

        clone = tests_utils.create_volume(self.context, size=1,
                                          host=CONF.host)
        clone['source_volid'] = fake.VOLUME2_ID
        create_volume.side_effect = fake_create_volume

        with mock.patch.object(self.volume, '_copy_volume_data') as \
                mock_copy_volume:
            mock_copy_volume.side_effect = fake_copy_volume_data_with_chk_param
            self.volume._migrate_volume_generic(self.context, clone,
                                                host_obj, None)

    @mock.patch.object(volume_rpcapi.VolumeAPI, 'update_migrated_volume')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')
    def test_migrate_volume_for_volume_generic(self, create_volume,
                                               rpc_delete_volume,
                                               update_migrated_volume):
        fake_volume = tests_utils.create_volume(self.context, size=1,
                                                previous_status='available',
                                                host=CONF.host)

        host_obj = {'host': 'newhost', 'capabilities': {}}
        with mock.patch.object(self.volume.driver, 'migrate_volume') as \
                mock_migrate_volume,\
                mock.patch.object(self.volume, '_copy_volume_data'),\
                mock.patch.object(self.volume.driver, 'delete_volume') as \
                delete_volume:
            create_volume.side_effect = self._fake_create_volume
            self.volume.migrate_volume(self.context, fake_volume, host_obj,
                                       True)
            volume = objects.Volume.get_by_id(context.get_admin_context(),
                                              fake_volume.id)
            self.assertEqual('newhost', volume.host)
            self.assertEqual('success', volume.migration_status)
            self.assertFalse(mock_migrate_volume.called)
            self.assertFalse(delete_volume.called)
            self.assertTrue(rpc_delete_volume.called)
            self.assertTrue(update_migrated_volume.called)

    def test_migrate_volume_generic_copy_error(self):
        with mock.patch.object(self.volume.driver, 'migrate_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')\
                as mock_create_volume,\
                mock.patch.object(self.volume, '_copy_volume_data') as \
                mock_copy_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(self.volume, 'migrate_volume_completion'),\
                mock.patch.object(self.volume.driver, 'create_export'):

            # Exception case at migrate_volume_generic
            # source_volume['migration_status'] is 'migrating'
            mock_create_volume.side_effect = self._fake_create_volume
            mock_copy_volume.side_effect = processutils.ProcessExecutionError
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(processutils.ProcessExecutionError,
                              self.volume.migrate_volume,
                              self.context,
                              volume,
                              host_obj,
                              True)
            volume = objects.Volume.get_by_id(context.get_admin_context(),
                                              volume.id)
            self.assertEqual('error', volume.migration_status)
            self.assertEqual('available', volume.status)

    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_migrate_volume_with_glance_metadata(self, mock_qemu_info):
        volume = self._create_volume_from_image(clone_image_volume=True)
        glance_metadata = volume.glance_metadata

        # We imitate the behavior of rpcapi, by serializing and then
        # deserializing the volume object we created earlier.
        serializer = objects.base.CinderObjectSerializer()
        serialized_volume = serializer.serialize_entity(self.context, volume)
        volume = serializer.deserialize_entity(self.context, serialized_volume)

        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        host_obj = {'host': 'newhost', 'capabilities': {}}
        with mock.patch.object(self.volume.driver,
                               'migrate_volume') as mock_migrate_volume:
            mock_migrate_volume.side_effect = (
                lambda x, y, z, new_type_id=None: (
                    True, {'user_id': fake.USER_ID}))
            self.volume.migrate_volume(self.context, volume, host_obj,
                                       False)
        self.assertEqual('newhost', volume.host)
        self.assertEqual('success', volume.migration_status)
        self.assertEqual(glance_metadata, volume.glance_metadata)

    @mock.patch('cinder.db.volume_update')
    def test_update_migrated_volume(self, volume_update):
        fake_host = 'fake_host'
        fake_new_host = 'fake_new_host'
        fake_update = {'_name_id': fake.VOLUME2_NAME_ID,
                       'provider_location': 'updated_location'}
        fake_elevated = context.RequestContext(fake.USER_ID, self.project_id,
                                               is_admin=True)
        volume = tests_utils.create_volume(self.context, size=1,
                                           status='available',
                                           host=fake_host)
        new_volume = tests_utils.create_volume(
            self.context, size=1,
            status='available',
            provider_location='fake_provider_location',
            _name_id=fake.VOLUME_NAME_ID,
            host=fake_new_host)
        new_volume._name_id = fake.VOLUME_NAME_ID
        new_volume.provider_location = 'fake_provider_location'
        fake_update_error = {'_name_id': new_volume._name_id,
                             'provider_location':
                             new_volume.provider_location}
        expected_update = {'_name_id': volume._name_id,
                           'provider_location': volume.provider_location}
        with mock.patch.object(self.volume.driver,
                               'update_migrated_volume') as migrate_update,\
                mock.patch.object(self.context, 'elevated') as elevated:
            migrate_update.return_value = fake_update
            elevated.return_value = fake_elevated
            self.volume.update_migrated_volume(self.context, volume,
                                               new_volume, 'available')
            volume_update.assert_has_calls((
                mock.call(fake_elevated, new_volume.id, expected_update),
                mock.call(fake_elevated, volume.id, fake_update)))

            # Test the case for update_migrated_volume not implemented
            # for the driver.
            migrate_update.reset_mock()
            volume_update.reset_mock()
            # Reset the volume objects to their original value, since they
            # were changed in the last call.
            new_volume._name_id = fake.VOLUME_NAME_ID
            new_volume.provider_location = 'fake_provider_location'
            migrate_update.side_effect = NotImplementedError
            self.volume.update_migrated_volume(self.context, volume,
                                               new_volume, 'available')
            volume_update.assert_has_calls((
                mock.call(fake_elevated, new_volume.id, fake_update),
                mock.call(fake_elevated, volume.id, fake_update_error)))

    def test_migrate_volume_generic_create_volume_error(self):
        self.expected_status = 'error'

        with mock.patch.object(self.volume.driver, 'migrate_volume'), \
                mock.patch.object(volume_rpcapi.VolumeAPI,
                                  'create_volume') as mock_create_volume, \
                mock.patch.object(self.volume, '_clean_temporary_volume') as \
                clean_temporary_volume:

            # Exception case at the creation of the new temporary volume
            mock_create_volume.side_effect = self._fake_create_volume
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(exception.VolumeMigrationFailed,
                              self.volume.migrate_volume,
                              self.context,
                              volume,
                              host_obj,
                              True)
            volume = objects.Volume.get_by_id(context.get_admin_context(),
                                              volume.id)
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])
            self.assertTrue(clean_temporary_volume.called)
        self.expected_status = 'available'

    def test_migrate_volume_generic_timeout_error(self):
        CONF.set_override("migration_create_volume_timeout_secs", 2)

        with mock.patch.object(self.volume.driver, 'migrate_volume'), \
                mock.patch.object(volume_rpcapi.VolumeAPI,
                                  'create_volume') as mock_create_volume, \
                mock.patch.object(self.volume, '_clean_temporary_volume') as \
                clean_temporary_volume, \
                mock.patch.object(time, 'sleep'):

            # Exception case at the timeout of the volume creation
            self.expected_status = 'creating'
            mock_create_volume.side_effect = self._fake_create_volume
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(exception.VolumeMigrationFailed,
                              self.volume.migrate_volume,
                              self.context,
                              volume,
                              host_obj,
                              True)
            volume = objects.Volume.get_by_id(context.get_admin_context(),
                                              volume.id)
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])
            self.assertTrue(clean_temporary_volume.called)
        self.expected_status = 'available'

    def test_migrate_volume_generic_create_export_error(self):
        with mock.patch.object(self.volume.driver, 'migrate_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')\
                as mock_create_volume,\
                mock.patch.object(self.volume, '_copy_volume_data') as \
                mock_copy_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(self.volume, 'migrate_volume_completion'),\
                mock.patch.object(self.volume.driver, 'create_export') as \
                mock_create_export:

            # Exception case at create_export
            mock_create_volume.side_effect = self._fake_create_volume
            mock_copy_volume.side_effect = processutils.ProcessExecutionError
            mock_create_export.side_effect = processutils.ProcessExecutionError
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(processutils.ProcessExecutionError,
                              self.volume.migrate_volume,
                              self.context,
                              volume,
                              host_obj,
                              True)
            volume = objects.Volume.get_by_id(context.get_admin_context(),
                                              volume.id)
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])

    def test_migrate_volume_generic_migrate_volume_completion_error(self):
        def fake_migrate_volume_completion(ctxt, volume, new_volume,
                                           error=False):
            db.volume_update(ctxt, volume['id'],
                             {'migration_status': 'completing'})
            raise processutils.ProcessExecutionError

        with mock.patch.object(self.volume.driver, 'migrate_volume'),\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'create_volume')\
                as mock_create_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI, 'delete_volume'),\
                mock.patch.object(self.volume, 'migrate_volume_completion')\
                as mock_migrate_compl,\
                mock.patch.object(self.volume.driver, 'create_export'), \
                mock.patch.object(self.volume, '_attach_volume') \
                as mock_attach, \
                mock.patch.object(self.volume, '_detach_volume'), \
                mock.patch.object(os_brick.initiator.connector,
                                  'get_connector_properties') \
                as mock_get_connector_properties, \
                mock.patch.object(volutils, 'copy_volume') as mock_copy, \
                mock.patch.object(volume_rpcapi.VolumeAPI,
                                  'get_capabilities') \
                as mock_get_capabilities:

            # Exception case at delete_volume
            # source_volume['migration_status'] is 'completing'
            mock_create_volume.side_effect = self._fake_create_volume
            mock_migrate_compl.side_effect = fake_migrate_volume_completion
            mock_get_connector_properties.return_value = {}
            mock_attach.side_effect = [{'device': {'path': 'bar'}},
                                       {'device': {'path': 'foo'}}]
            mock_get_capabilities.return_value = {'sparse_copy_volume': True}
            volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host)
            host_obj = {'host': 'newhost', 'capabilities': {}}
            self.assertRaises(processutils.ProcessExecutionError,
                              self.volume.migrate_volume,
                              self.context,
                              volume,
                              host_obj,
                              True)
            volume = db.volume_get(context.get_admin_context(), volume['id'])
            self.assertEqual('error', volume['migration_status'])
            self.assertEqual('available', volume['status'])
            mock_copy.assert_called_once_with('foo', 'bar', 0, '1M',
                                              sparse=True)

    def fake_attach_volume(self, ctxt, volume, instance_uuid, host_name,
                           mountpoint, mode):
            tests_utils.attach_volume(ctxt, volume.id,
                                      instance_uuid, host_name,
                                      '/dev/vda')

    def _test_migrate_volume_completion(self, status='available',
                                        instance_uuid=None, attached_host=None,
                                        retyping=False,
                                        previous_status='available'):

        initial_status = retyping and 'retyping' or status
        old_volume = tests_utils.create_volume(self.context, size=0,
                                               host=CONF.host,
                                               status=initial_status,
                                               migration_status='migrating',
                                               previous_status=previous_status)
        attachment = None
        if status == 'in-use':
            vol = tests_utils.attach_volume(self.context, old_volume.id,
                                            instance_uuid, attached_host,
                                            '/dev/vda')
            self.assertEqual('in-use', vol['status'])
            attachment = vol['volume_attachment'][0]
        target_status = 'target:%s' % old_volume.id
        new_host = CONF.host + 'new'
        new_volume = tests_utils.create_volume(self.context, size=0,
                                               host=new_host,
                                               migration_status=target_status)
        with mock.patch.object(self.volume, 'detach_volume') as \
                mock_detach_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI,
                                  'delete_volume') as mock_delete_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI,
                                  'attach_volume') as mock_attach_volume,\
                mock.patch.object(volume_rpcapi.VolumeAPI,
                                  'update_migrated_volume'),\
                mock.patch.object(self.volume.driver, 'attach_volume'):
            mock_attach_volume.side_effect = self.fake_attach_volume
            old_volume_host = old_volume.host
            new_volume_host = new_volume.host
            self.volume.migrate_volume_completion(self.context, old_volume,
                                                  new_volume)
            after_new_volume = objects.Volume.get_by_id(self.context,
                                                        new_volume.id)
            after_old_volume = objects.Volume.get_by_id(self.context,
                                                        old_volume.id)
            if status == 'in-use':
                mock_detach_volume.assert_called_with(self.context,
                                                      old_volume.id,
                                                      attachment['id'])
                attachments = db.volume_attachment_get_all_by_instance_uuid(
                    self.context, instance_uuid)
                mock_attach_volume.assert_called_once_with(
                    self.context,
                    old_volume,
                    attachment['instance_uuid'],
                    attachment['attached_host'],
                    attachment['mountpoint'],
                    'rw'
                )
                self.assertIsNotNone(attachments)
                self.assertEqual(attached_host,
                                 attachments[0]['attached_host'])
                self.assertEqual(instance_uuid,
                                 attachments[0]['instance_uuid'])
            else:
                self.assertFalse(mock_detach_volume.called)
            self.assertTrue(mock_delete_volume.called)
            # NOTE(sborkows): the migrate_volume_completion method alters
            # old and new volume objects, so we need to check the equality
            # between the former host value and the actual one.
            self.assertEqual(old_volume_host, after_new_volume.host)
            self.assertEqual(new_volume_host, after_old_volume.host)

    def test_migrate_volume_completion_retype_available(self):
        self._test_migrate_volume_completion('available', retyping=True)

    def test_migrate_volume_completion_retype_in_use(self):
        self._test_migrate_volume_completion(
            'in-use',
            '83c969d5-065e-4c9c-907d-5394bc2e98e2',
            'some-host',
            retyping=True,
            previous_status='in-use')

    def test_migrate_volume_completion_migrate_available(self):
        self._test_migrate_volume_completion()

    def test_migrate_volume_completion_migrate_in_use(self):
        self._test_migrate_volume_completion(
            'in-use',
            '83c969d5-065e-4c9c-907d-5394bc2e98e2',
            'some-host',
            retyping=False,
            previous_status='in-use')

    @ddt.data(False, True)
    def test_api_migrate_volume_completion_from_swap_with_no_migration(
            self, swap_error):
        # This test validates that Cinder properly finishes the swap volume
        # status updates for the case that no migration has occurred
        instance_uuid = '83c969d5-065e-4c9c-907d-5394bc2e98e2'
        attached_host = 'attached-host'
        orig_attached_vol = tests_utils.create_volume(self.context, size=0)
        orig_attached_vol = tests_utils.attach_volume(
            self.context, orig_attached_vol['id'], instance_uuid,
            attached_host, '/dev/vda')
        new_volume = tests_utils.create_volume(self.context, size=0)

        @mock.patch.object(volume_rpcapi.VolumeAPI, 'detach_volume')
        @mock.patch.object(volume_rpcapi.VolumeAPI, 'attach_volume')
        def _run_migration_completion(rpc_attach_volume,
                                      rpc_detach_volume):
            attachment = orig_attached_vol['volume_attachment'][0]
            attachment_id = attachment['id']
            rpc_attach_volume.side_effect = self.fake_attach_volume
            vol_id = volume_api.API().migrate_volume_completion(
                self.context, orig_attached_vol, new_volume, swap_error)
            if swap_error:
                # When swap failed, we don't want to finish attachment
                self.assertFalse(rpc_detach_volume.called)
                self.assertFalse(rpc_attach_volume.called)
            else:
                # When no error, we should be finishing the attachment
                rpc_detach_volume.assert_called_with(self.context,
                                                     orig_attached_vol,
                                                     attachment_id)
                rpc_attach_volume.assert_called_with(
                    self.context, new_volume, attachment['instance_uuid'],
                    attachment['attached_host'], attachment['mountpoint'],
                    'rw')
            self.assertEqual(new_volume['id'], vol_id)

        _run_migration_completion()

    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    def test_retype_setup_fail_volume_is_available(self, mock_notify):
        """Verify volume is still available if retype prepare failed."""
        elevated = context.get_admin_context()
        project_id = self.context.project_id

        db.volume_type_create(elevated, {'name': 'old', 'extra_specs': {}})
        old_vol_type = db.volume_type_get_by_name(elevated, 'old')
        db.volume_type_create(elevated, {'name': 'new', 'extra_specs': {}})
        new_vol_type = db.volume_type_get_by_name(elevated, 'new')
        db.quota_create(elevated, project_id, 'volumes_new', 0)

        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host, status='available',
                                           volume_type_id=old_vol_type['id'])

        api = cinder.volume.api.API()
        self.assertRaises(exception.VolumeLimitExceeded, api.retype,
                          self.context, volume, new_vol_type['id'])

        volume = db.volume_get(elevated, volume.id)
        mock_notify.assert_not_called()
        self.assertEqual('available', volume['status'])

    @mock.patch('cinder.tests.unit.fake_notifier.FakeNotifier._notify')
    def _retype_volume_exec(self, driver, mock_notify,
                            snap=False, policy='on-demand',
                            migrate_exc=False, exc=None, diff_equal=False,
                            replica=False, reserve_vol_type_only=False,
                            encryption_changed=False,
                            replica_new=None):
        elevated = context.get_admin_context()
        project_id = self.context.project_id

        if replica:
            rep_status = 'enabled'
            extra_specs = {'replication_enabled': '<is> True'}
        else:
            rep_status = 'disabled'
            extra_specs = {}

        if replica_new is None:
            replica_new = replica
        new_specs = {'replication_enabled': '<is> True'} if replica_new else {}

        db.volume_type_create(elevated, {'name': 'old',
                                         'extra_specs': extra_specs})
        old_vol_type = db.volume_type_get_by_name(elevated, 'old')

        db.volume_type_create(elevated, {'name': 'new',
                                         'extra_specs': new_specs})
        vol_type = db.volume_type_get_by_name(elevated, 'new')
        db.quota_create(elevated, project_id, 'volumes_new', 10)

        volume = tests_utils.create_volume(self.context, size=1,
                                           host=CONF.host, status='retyping',
                                           volume_type_id=old_vol_type['id'],
                                           replication_status=rep_status)
        volume.previous_status = 'available'
        volume.save()
        if snap:
            create_snapshot(volume.id, size=volume.size,
                            user_id=self.user_context.user_id,
                            project_id=self.user_context.project_id,
                            ctxt=self.user_context)
        if driver or diff_equal:
            host_obj = {'host': CONF.host, 'capabilities': {}}
        else:
            host_obj = {'host': 'newhost', 'capabilities': {}}

        reserve_opts = {'volumes': 1, 'gigabytes': volume.size}
        QUOTAS.add_volume_type_opts(self.context,
                                    reserve_opts,
                                    vol_type['id'])
        if reserve_vol_type_only:
            reserve_opts.pop('volumes')
            reserve_opts.pop('gigabytes')
            try:
                usage = db.quota_usage_get(elevated, project_id, 'volumes')
                total_volumes_in_use = usage.in_use
                usage = db.quota_usage_get(elevated, project_id, 'gigabytes')
                total_gigabytes_in_use = usage.in_use
            except exception.QuotaUsageNotFound:
                total_volumes_in_use = 0
                total_gigabytes_in_use = 0
        reservations = QUOTAS.reserve(self.context,
                                      project_id=project_id,
                                      **reserve_opts)

        old_reserve_opts = {'volumes': -1, 'gigabytes': -volume.size}
        QUOTAS.add_volume_type_opts(self.context,
                                    old_reserve_opts,
                                    old_vol_type['id'])
        old_reservations = QUOTAS.reserve(self.context,
                                          project_id=project_id,
                                          **old_reserve_opts)

        with mock.patch.object(self.volume.driver, 'retype') as _retype,\
                mock.patch.object(volume_types, 'volume_types_diff') as _diff,\
                mock.patch.object(self.volume, 'migrate_volume') as _mig,\
                mock.patch.object(db.sqlalchemy.api, 'volume_get') as _vget,\
                mock.patch.object(context.RequestContext, 'elevated') as _ctx:
            _vget.return_value = volume
            _retype.return_value = driver
            _ctx.return_value = self.context
            returned_diff = {
                'encryption': {},
                'qos_specs': {},
                'extra_specs': {},
            }
            if replica != replica_new:
                returned_diff['extra_specs']['replication_enabled'] = (
                    extra_specs.get('replication_enabled'),
                    new_specs.get('replication_enabled'))
            expected_replica_status = 'enabled' if replica_new else 'disabled'

            if encryption_changed:
                returned_diff['encryption'] = 'fake'
            _diff.return_value = (returned_diff, diff_equal)
            if migrate_exc:
                _mig.side_effect = KeyError
            else:
                _mig.return_value = True

            if not exc:
                self.volume.retype(self.context, volume,
                                   vol_type['id'], host_obj,
                                   migration_policy=policy,
                                   reservations=reservations,
                                   old_reservations=old_reservations)
            else:
                self.assertRaises(exc, self.volume.retype,
                                  self.context, volume,
                                  vol_type['id'], host_obj,
                                  migration_policy=policy,
                                  reservations=reservations,
                                  old_reservations=old_reservations)
            if host_obj['host'] != CONF.host:
                _retype.assert_not_called()

        # get volume/quota properties
        volume = objects.Volume.get_by_id(elevated, volume.id)
        try:
            usage = db.quota_usage_get(elevated, project_id, 'volumes_new')
            volumes_in_use = usage.in_use
        except exception.QuotaUsageNotFound:
            volumes_in_use = 0

        # Get new in_use after retype, it should not be changed.
        if reserve_vol_type_only:
            try:
                usage = db.quota_usage_get(elevated, project_id, 'volumes')
                new_total_volumes_in_use = usage.in_use
                usage = db.quota_usage_get(elevated, project_id, 'gigabytes')
                new_total_gigabytes_in_use = usage.in_use
            except exception.QuotaUsageNotFound:
                new_total_volumes_in_use = 0
                new_total_gigabytes_in_use = 0
            self.assertEqual(total_volumes_in_use, new_total_volumes_in_use)
            self.assertEqual(total_gigabytes_in_use,
                             new_total_gigabytes_in_use)

        # check properties
        if driver or diff_equal:
            self.assertEqual(vol_type['id'], volume.volume_type_id)
            self.assertEqual('available', volume.status)
            self.assertEqual(CONF.host, volume.host)
            self.assertEqual(1, volumes_in_use)
            self.assert_notify_called(mock_notify,
                                      (['INFO', 'volume.retype'],))
        elif not exc:
            self.assertEqual(old_vol_type['id'], volume.volume_type_id)
            self.assertEqual('retyping', volume.status)
            self.assertEqual(CONF.host, volume.host)
            self.assertEqual(1, volumes_in_use)
            self.assert_notify_called(mock_notify,
                                      (['INFO', 'volume.retype'],))
        else:
            self.assertEqual(old_vol_type['id'], volume.volume_type_id)
            self.assertEqual('available', volume.status)
            self.assertEqual(CONF.host, volume.host)
            self.assertEqual(0, volumes_in_use)
            mock_notify.assert_not_called()
        if encryption_changed:
            self.assertTrue(_mig.called)
        self.assertEqual(expected_replica_status, volume.replication_status)

    def test_retype_volume_driver_success(self):
        self._retype_volume_exec(True)

    @ddt.data((False, False), (False, True), (True, False), (True, True))
    @ddt.unpack
    def test_retype_volume_replica(self, replica, replica_new):
        self._retype_volume_exec(True, replica=replica,
                                 replica_new=replica_new)

    def test_retype_volume_migration_bad_policy(self):
        # Test volume retype that requires migration by not allowed
        self._retype_volume_exec(False, policy='never',
                                 exc=exception.VolumeMigrationFailed)

    def test_retype_volume_migration_with_replica(self):
        self._retype_volume_exec(False,
                                 replica=True,
                                 exc=exception.InvalidVolume)

    def test_retype_volume_migration_with_snaps(self):
        self._retype_volume_exec(False, snap=True, exc=exception.InvalidVolume)

    def test_retype_volume_migration_failed(self):
        self._retype_volume_exec(False, migrate_exc=True, exc=KeyError)

    def test_retype_volume_migration_success(self):
        self._retype_volume_exec(False, migrate_exc=False, exc=None)

    def test_retype_volume_migration_equal_types(self):
        self._retype_volume_exec(False, diff_equal=True)

    def test_retype_volume_with_type_only(self):
        self._retype_volume_exec(True, reserve_vol_type_only=True)

    def test_retype_volume_migration_encryption(self):
        self._retype_volume_exec(False, encryption_changed=True)

    def test_migrate_driver_not_initialized(self):
        volume = tests_utils.create_volume(self.context, size=0,
                                           host=CONF.host)
        host_obj = {'host': 'newhost', 'capabilities': {}}

        self.volume.driver._initialized = False
        self.assertRaises(exception.DriverNotInitialized,
                          self.volume.migrate_volume,
                          self.context, volume, host_obj, True)

        volume = objects.Volume.get_by_id(context.get_admin_context(),
                                          volume.id)
        self.assertEqual('error', volume.migration_status)

        # lets cleanup the mess.
        self.volume.driver._initialized = True
        self.volume.delete_volume(self.context, volume)

    def test_delete_source_volume_in_migration(self):
        """Test deleting a source volume that is in migration."""
        self._test_delete_volume_in_migration('migrating')

    def test_delete_destination_volume_in_migration(self):
        """Test deleting a destination volume that is in migration."""
        self._test_delete_volume_in_migration('target:vol-id')

    def _test_delete_volume_in_migration(self, migration_status):
        """Test deleting a volume that is in migration."""
        volume = tests_utils.create_volume(self.context, host=CONF.host,
                                           migration_status=migration_status)
        self.volume.delete_volume(self.context, volume=volume)

        # The volume is successfully removed during the volume delete
        # and won't exist in the database any more.
        self.assertRaises(exception.VolumeNotFound, volume.refresh)
