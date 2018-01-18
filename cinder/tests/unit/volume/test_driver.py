# Copyright (c) 2016 Red Hat Inc.
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
import mock
import shutil
import tempfile

import os_brick
from oslo_config import cfg
from oslo_utils import importutils

from cinder.brick.local_dev import lvm as brick_lvm
from cinder import context
from cinder import db
from cinder import exception
from cinder.image import image_utils
from cinder import objects
from cinder.objects import fields
import cinder.policy
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import utils as tests_utils
from cinder import utils
import cinder.volume
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume import manager
from cinder.volume import rpcapi as volume_rpcapi
import cinder.volume.targets.tgt
from cinder.volume import utils as volutils


CONF = cfg.CONF


def my_safe_get(self, value):
    if value == 'replication_device':
        return ['replication']
    return None


@ddt.ddt
class DriverTestCase(test.TestCase):

    @staticmethod
    def _get_driver(relicated, version):
        class NonReplicatedDriver(driver.VolumeDriver):
            pass

        class V21Driver(driver.VolumeDriver):
            def failover_host(*args, **kwargs):
                pass

        class AADriver(V21Driver):
            def failover_completed(*args, **kwargs):
                pass

        if not relicated:
            return NonReplicatedDriver

        if version == 'v2.1':
            return V21Driver

        return AADriver

    @ddt.data('v2.1', 'a/a', 'newfeature')
    def test_supports_replication_feature_none(self, rep_version):
        my_driver = self._get_driver(False, None)
        self.assertFalse(my_driver.supports_replication_feature(rep_version))

    @ddt.data('v2.1', 'a/a', 'newfeature')
    def test_supports_replication_feature_only_21(self, rep_version):
        version = 'v2.1'
        my_driver = self._get_driver(True, version)
        self.assertEqual(rep_version == version,
                         my_driver.supports_replication_feature(rep_version))

    @ddt.data('v2.1', 'a/a', 'newfeature')
    def test_supports_replication_feature_aa(self, rep_version):
        my_driver = self._get_driver(True, 'a/a')
        self.assertEqual(rep_version in ('v2.1', 'a/a'),
                         my_driver.supports_replication_feature(rep_version))

    def test_init_non_replicated(self):
        config = manager.config.Configuration(manager.volume_manager_opts,
                                              config_group='volume')
        # No exception raised
        self._get_driver(False, None)(configuration=config)

    @ddt.data('v2.1', 'a/a')
    @mock.patch('cinder.volume.configuration.Configuration.safe_get',
                my_safe_get)
    def test_init_replicated_non_clustered(self, version):
        def append_config_values(self, volume_opts):
            pass

        config = manager.config.Configuration(manager.volume_manager_opts,
                                              config_group='volume')
        # No exception raised
        self._get_driver(True, version)(configuration=config)

    @mock.patch('cinder.volume.configuration.Configuration.safe_get',
                my_safe_get)
    def test_init_replicated_clustered_not_supported(self):
        config = manager.config.Configuration(manager.volume_manager_opts,
                                              config_group='volume')
        # Raises exception because we are trying to run a replicated service
        # in clustered mode but the driver doesn't support it.
        self.assertRaises(exception.Invalid, self._get_driver(True, 'v2.1'),
                          configuration=config, cluster_name='mycluster')

    @mock.patch('cinder.volume.configuration.Configuration.safe_get',
                my_safe_get)
    def test_init_replicated_clustered_supported(self):
        config = manager.config.Configuration(manager.volume_manager_opts,
                                              config_group='volume')
        # No exception raised
        self._get_driver(True, 'a/a')(configuration=config,
                                      cluster_name='mycluster')

    def test_failover(self):
        """Test default failover behavior of calling failover_host."""
        my_driver = self._get_driver(True, 'a/a')()
        with mock.patch.object(my_driver, 'failover_host') as failover_mock:
            res = my_driver.failover(mock.sentinel.context,
                                     mock.sentinel.volumes,
                                     secondary_id=mock.sentinel.secondary_id,
                                     groups=[])
        self.assertEqual(failover_mock.return_value, res)
        failover_mock.assert_called_once_with(mock.sentinel.context,
                                              mock.sentinel.volumes,
                                              mock.sentinel.secondary_id,
                                              [])


class BaseDriverTestCase(test.TestCase):
    """Base Test class for Drivers."""
    driver_name = "cinder.volume.driver.FakeBaseDriver"

    def setUp(self):
        super(BaseDriverTestCase, self).setUp()
        vol_tmpdir = tempfile.mkdtemp()
        self.override_config('volume_driver', self.driver_name,
                             conf.SHARED_CONF_GROUP)
        self.override_config('volumes_dir', vol_tmpdir,
                             conf.SHARED_CONF_GROUP)
        self.volume = importutils.import_object(CONF.volume_manager)
        self.context = context.get_admin_context()
        self.output = ""
        self.configuration = conf.Configuration(None)
        self.mock_object(brick_lvm.LVM, '_vg_exists', lambda x: True)

        def _fake_execute(_command, *_args, **_kwargs):
            """Fake _execute."""
            return self.output, None
        exec_patcher = mock.patch.object(self.volume.driver, '_execute',
                                         _fake_execute)
        exec_patcher.start()
        self.addCleanup(exec_patcher.stop)
        self.volume.driver.set_initialized()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            shutil.rmtree(CONF.volumes_dir)
        except OSError:
            pass

    def _attach_volume(self):
        """Attach volumes to an instance."""
        return []


@ddt.ddt
class GenericVolumeDriverTestCase(BaseDriverTestCase):
    """Test case for VolumeDriver."""
    driver_name = "cinder.tests.fake_driver.FakeLoggingVolumeDriver"

    def test_create_temp_cloned_volume(self):
        with mock.patch.object(
                self.volume.driver,
                'create_cloned_volume') as mock_create_cloned_volume:
            model_update = {'provider_location': 'dummy'}
            mock_create_cloned_volume.return_value = model_update
            vol = tests_utils.create_volume(self.context,
                                            status='backing-up')
            cloned_vol = self.volume.driver._create_temp_cloned_volume(
                self.context, vol)
            self.assertEqual('dummy', cloned_vol.provider_location)
            self.assertEqual('available', cloned_vol.status)

            mock_create_cloned_volume.return_value = None
            vol = tests_utils.create_volume(self.context,
                                            status='backing-up')
            cloned_vol = self.volume.driver._create_temp_cloned_volume(
                self.context, vol)
            self.assertEqual('available', cloned_vol.status)

    def test_get_backup_device_available(self):
        vol = tests_utils.create_volume(self.context)
        self.context.user_id = fake.USER_ID
        self.context.project_id = fake.PROJECT_ID
        backup_obj = tests_utils.create_backup(self.context,
                                               vol['id'])
        (backup_device, is_snapshot) = self.volume.driver.get_backup_device(
            self.context, backup_obj)
        volume = objects.Volume.get_by_id(self.context, vol.id)
        self.assertNotIn('temporary', backup_device.admin_metadata.keys())
        self.assertEqual(volume, backup_device)
        self.assertFalse(is_snapshot)
        backup_obj.refresh()
        self.assertIsNone(backup_obj.temp_volume_id)

    def test_get_backup_device_in_use(self):
        vol = tests_utils.create_volume(self.context,
                                        status='backing-up',
                                        previous_status='in-use')
        admin_meta = {'temporary': 'True'}
        temp_vol = tests_utils.create_volume(self.context,
                                             admin_metadata=admin_meta)
        self.context.user_id = fake.USER_ID
        self.context.project_id = fake.PROJECT_ID
        backup_obj = tests_utils.create_backup(self.context,
                                               vol['id'])
        with mock.patch.object(
                self.volume.driver,
                '_create_temp_cloned_volume') as mock_create_temp:
            mock_create_temp.return_value = temp_vol
            (backup_device, is_snapshot) = (
                self.volume.driver.get_backup_device(self.context,
                                                     backup_obj))
            self.assertEqual(temp_vol, backup_device)
            self.assertFalse(is_snapshot)
            backup_obj.refresh()
            self.assertEqual(temp_vol.id, backup_obj.temp_volume_id)

    def test_create_temp_volume_from_snapshot(self):
        volume_dict = {'id': fake.SNAPSHOT_ID,
                       'host': 'fakehost',
                       'cluster_name': 'fakecluster',
                       'availability_zone': 'fakezone',
                       'size': 1}
        vol = fake_volume.fake_volume_obj(self.context, **volume_dict)
        snapshot = fake_snapshot.fake_snapshot_obj(self.context)

        with mock.patch.object(
                self.volume.driver,
                'create_volume_from_snapshot'):
            temp_vol = self.volume.driver._create_temp_volume_from_snapshot(
                self.context,
                vol, snapshot)
            self.assertEqual(fields.VolumeAttachStatus.DETACHED,
                             temp_vol.attach_status)
            self.assertEqual('fakezone', temp_vol.availability_zone)
            self.assertEqual('fakecluster', temp_vol.cluster_name)

    @mock.patch.object(utils, 'brick_get_connector_properties')
    @mock.patch.object(cinder.volume.manager.VolumeManager, '_attach_volume')
    @mock.patch.object(cinder.volume.manager.VolumeManager, '_detach_volume')
    @mock.patch.object(volutils, 'copy_volume')
    @mock.patch.object(volume_rpcapi.VolumeAPI, 'get_capabilities')
    @mock.patch.object(cinder.volume.volume_types,
                       'volume_types_encryption_changed')
    @ddt.data(False, True)
    def test_copy_volume_data_mgr(self,
                                  encryption_changed,
                                  mock_encryption_changed,
                                  mock_get_capabilities,
                                  mock_copy,
                                  mock_detach,
                                  mock_attach,
                                  mock_get_connector):
        """Test function of _copy_volume_data."""

        src_vol = tests_utils.create_volume(self.context, size=1,
                                            host=CONF.host)
        dest_vol = tests_utils.create_volume(self.context, size=1,
                                             host=CONF.host)
        mock_get_connector.return_value = {}
        mock_encryption_changed.return_value = encryption_changed
        self.volume.driver._throttle = mock.MagicMock()

        attach_expected = [
            mock.call(self.context, dest_vol, {},
                      remote=False,
                      attach_encryptor=encryption_changed),
            mock.call(self.context, src_vol, {},
                      remote=False,
                      attach_encryptor=encryption_changed)]

        detach_expected = [
            mock.call(self.context, {'device': {'path': 'bar'}},
                      dest_vol, {}, force=True, remote=False,
                      attach_encryptor=encryption_changed),
            mock.call(self.context, {'device': {'path': 'foo'}},
                      src_vol, {}, force=True, remote=False,
                      attach_encryptor=encryption_changed)]

        attach_volume_returns = [
            {'device': {'path': 'bar'}},
            {'device': {'path': 'foo'}}
        ]

        #  Test case for sparse_copy_volume = False
        mock_attach.side_effect = attach_volume_returns
        mock_get_capabilities.return_value = {}
        self.volume._copy_volume_data(self.context,
                                      src_vol,
                                      dest_vol)

        self.assertEqual(attach_expected, mock_attach.mock_calls)
        mock_copy.assert_called_with('foo', 'bar', 1024, '1M', sparse=False)
        self.assertEqual(detach_expected, mock_detach.mock_calls)

        #  Test case for sparse_copy_volume = True
        mock_attach.reset_mock()
        mock_detach.reset_mock()
        mock_attach.side_effect = attach_volume_returns
        mock_get_capabilities.return_value = {'sparse_copy_volume': True}
        self.volume._copy_volume_data(self.context,
                                      src_vol,
                                      dest_vol)

        self.assertEqual(attach_expected, mock_attach.mock_calls)
        mock_copy.assert_called_with('foo', 'bar', 1024, '1M', sparse=True)
        self.assertEqual(detach_expected, mock_detach.mock_calls)

        # cleanup resource
        db.volume_destroy(self.context, src_vol['id'])
        db.volume_destroy(self.context, dest_vol['id'])

    @mock.patch(driver_name + '.initialize_connection')
    @mock.patch(driver_name + '.create_export', return_value=None)
    @mock.patch(driver_name + '._connect_device')
    def test_attach_volume_encrypted(self, connect_mock, export_mock,
                                     initialize_mock):
        properties = {'host': 'myhost', 'ip': '192.168.1.43',
                      'initiator': u'iqn.1994-05.com.redhat:d9be887375',
                      'multipath': False, 'os_type': 'linux2',
                      'platform': 'x86_64'}

        data = {'target_discovered': True,
                'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                'target_portal': '127.0.0.0.1:3260',
                'volume_id': 1,
                'discard': False}

        passed_conn = {'driver_volume_type': 'iscsi', 'data': data.copy()}
        initialize_mock.return_value = passed_conn

        # _attach_volume adds the encrypted value based on the volume
        expected_conn = {'driver_volume_type': 'iscsi', 'data': data.copy()}
        expected_conn['data']['encrypted'] = True

        volume = tests_utils.create_volume(
            self.context, status='available',
            size=2,
            encryption_key_id=fake.ENCRYPTION_KEY_ID)

        attach_info, vol = self.volume.driver._attach_volume(self.context,
                                                             volume,
                                                             properties)

        export_mock.assert_called_once_with(self.context, volume, properties)
        initialize_mock.assert_called_once_with(volume, properties)

        connect_mock.assert_called_once_with(expected_conn)

        self.assertEqual(connect_mock.return_value, attach_info)
        self.assertEqual(volume, vol)

    @mock.patch.object(os_brick.initiator.connector,
                       'get_connector_properties')
    @mock.patch.object(image_utils, 'fetch_to_raw')
    @mock.patch.object(cinder.volume.driver.VolumeDriver, '_attach_volume')
    @mock.patch.object(cinder.volume.driver.VolumeDriver, '_detach_volume')
    @mock.patch.object(cinder.utils, 'brick_attach_volume_encryptor')
    @mock.patch.object(cinder.utils, 'brick_detach_volume_encryptor')
    def test_copy_image_to_encrypted_volume(self,
                                            mock_detach_encryptor,
                                            mock_attach_encryptor,
                                            mock_detach_volume,
                                            mock_attach_volume,
                                            mock_fetch_to_raw,
                                            mock_get_connector_properties):
        properties = {}
        volume = tests_utils.create_volume(
            self.context, status='available',
            size=2,
            encryption_key_id=fake.ENCRYPTION_KEY_ID)
        volume_id = volume['id']
        volume = db.volume_get(context.get_admin_context(), volume_id)
        image_service = fake_image.FakeImageService()
        local_path = 'dev/sda'
        attach_info = {'device': {'path': local_path},
                       'conn': {'driver_volume_type': 'iscsi',
                                'data': {}, }}

        mock_get_connector_properties.return_value = properties
        mock_attach_volume.return_value = [attach_info, volume]

        self.volume.driver.copy_image_to_encrypted_volume(
            self.context, volume, image_service, fake.IMAGE_ID)

        encryption = {'encryption_key_id': fake.ENCRYPTION_KEY_ID}
        mock_attach_volume.assert_called_once_with(
            self.context, volume, properties)
        mock_attach_encryptor.assert_called_once_with(
            self.context, attach_info, encryption)
        mock_fetch_to_raw.assert_called_once_with(
            self.context, image_service, fake.IMAGE_ID,
            local_path, '1M', size=2)
        mock_detach_encryptor.assert_called_once_with(
            attach_info, encryption)
        mock_detach_volume.assert_called_once_with(
            self.context, attach_info, volume, properties, force=True)

    @mock.patch.object(os_brick.initiator.connector,
                       'get_connector_properties')
    @mock.patch.object(image_utils, 'fetch_to_raw')
    @mock.patch.object(cinder.volume.driver.VolumeDriver, '_attach_volume')
    @mock.patch.object(cinder.volume.driver.VolumeDriver, '_detach_volume')
    @mock.patch.object(cinder.utils, 'brick_attach_volume_encryptor')
    @mock.patch.object(cinder.utils, 'brick_detach_volume_encryptor')
    def test_copy_image_to_encrypted_volume_failed_attach_encryptor(
            self,
            mock_detach_encryptor,
            mock_attach_encryptor,
            mock_detach_volume,
            mock_attach_volume,
            mock_fetch_to_raw,
            mock_get_connector_properties):
        properties = {}
        volume = tests_utils.create_volume(
            self.context, status='available',
            size=2,
            encryption_key_id=fake.ENCRYPTION_KEY_ID)
        volume_id = volume['id']
        volume = db.volume_get(context.get_admin_context(), volume_id)
        image_service = fake_image.FakeImageService()
        attach_info = {'device': {'path': 'dev/sda'},
                       'conn': {'driver_volume_type': 'iscsi',
                                'data': {}, }}

        mock_get_connector_properties.return_value = properties
        mock_attach_volume.return_value = [attach_info, volume]
        raised_exception = os_brick.exception.VolumeEncryptionNotSupported(
            volume_id = "123",
            volume_type = "abc")
        mock_attach_encryptor.side_effect = raised_exception

        self.assertRaises(os_brick.exception.VolumeEncryptionNotSupported,
                          self.volume.driver.copy_image_to_encrypted_volume,
                          self.context, volume, image_service, fake.IMAGE_ID)

        encryption = {'encryption_key_id': fake.ENCRYPTION_KEY_ID}
        mock_attach_volume.assert_called_once_with(
            self.context, volume, properties)
        mock_attach_encryptor.assert_called_once_with(
            self.context, attach_info, encryption)
        self.assertFalse(mock_fetch_to_raw.called)
        self.assertFalse(mock_detach_encryptor.called)
        mock_detach_volume.assert_called_once_with(
            self.context, attach_info, volume, properties, force=True)

    @mock.patch.object(os_brick.initiator.connector,
                       'get_connector_properties')
    @mock.patch.object(image_utils, 'fetch_to_raw')
    @mock.patch.object(cinder.volume.driver.VolumeDriver, '_attach_volume')
    @mock.patch.object(cinder.volume.driver.VolumeDriver, '_detach_volume')
    @mock.patch.object(cinder.utils, 'brick_attach_volume_encryptor')
    @mock.patch.object(cinder.utils, 'brick_detach_volume_encryptor')
    @ddt.data(exception.ImageUnacceptable(
              reason='fake', image_id=fake.IMAGE_ID),
              exception.ImageTooBig(
              reason='fake image size exceeded', image_id=fake.IMAGE_ID))
    def test_copy_image_to_encrypted_volume_failed_fetch(
            self, excep,
            mock_detach_encryptor, mock_attach_encryptor,
            mock_detach_volume, mock_attach_volume, mock_fetch_to_raw,
            mock_get_connector_properties):
        properties = {}
        volume = tests_utils.create_volume(
            self.context, status='available',
            size=2,
            encryption_key_id=fake.ENCRYPTION_KEY_ID)
        volume_id = volume['id']
        volume = db.volume_get(context.get_admin_context(), volume_id)
        image_service = fake_image.FakeImageService()
        local_path = 'dev/sda'
        attach_info = {'device': {'path': local_path},
                       'conn': {'driver_volume_type': 'iscsi',
                                'data': {}, }}

        mock_get_connector_properties.return_value = properties
        mock_attach_volume.return_value = [attach_info, volume]
        mock_fetch_to_raw.side_effect = excep

        encryption = {'encryption_key_id': fake.ENCRYPTION_KEY_ID}
        self.assertRaises(type(excep),
                          self.volume.driver.copy_image_to_encrypted_volume,
                          self.context, volume, image_service, fake.IMAGE_ID)

        mock_attach_volume.assert_called_once_with(
            self.context, volume, properties)
        mock_attach_encryptor.assert_called_once_with(
            self.context, attach_info, encryption)
        mock_fetch_to_raw.assert_called_once_with(
            self.context, image_service, fake.IMAGE_ID,
            local_path, '1M', size=2)
        mock_detach_encryptor.assert_called_once_with(
            attach_info, encryption)
        mock_detach_volume.assert_called_once_with(
            self.context, attach_info, volume, properties, force=True)

    @mock.patch('cinder.volume.driver.brick_exception')
    @mock.patch('cinder.tests.fake_driver.FakeLoggingVolumeDriver.'
                'terminate_connection', side_effect=Exception)
    @mock.patch('cinder.tests.fake_driver.FakeLoggingVolumeDriver.'
                'remove_export', side_effect=Exception)
    def test_detach_volume_force(self, remove_mock, terminate_mock, exc_mock):
        """Test force parameter on _detach_volume.

        On the driver if we receive the force parameter we will do everything
        even with Exceptions on disconnect, terminate, and remove export.
        """
        connector = mock.Mock()
        connector.disconnect_volume.side_effect = Exception
        # TODO(geguileo): Remove this ExceptionChainer simulation once we
        # release OS-Brick version with it and bump min version.
        exc = exc_mock.ExceptionChainer.return_value
        exc.context.return_value.__enter__.return_value = exc
        exc.context.return_value.__exit__.return_value = True

        volume = {'id': fake.VOLUME_ID}
        attach_info = {'device': {},
                       'connector': connector,
                       'conn': {'data': {}, }}

        # TODO(geguileo): Change TypeError to ExceptionChainer once we release
        # OS-Brick version with it and bump min version.
        self.assertRaises(TypeError,
                          self.volume.driver._detach_volume, self.context,
                          attach_info, volume, {}, force=True)

        self.assertTrue(connector.disconnect_volume.called)
        self.assertTrue(remove_mock.called)
        self.assertTrue(terminate_mock.called)
        self.assertEqual(3, exc.context.call_count)


class FibreChannelTestCase(BaseDriverTestCase):
    """Test Case for FibreChannelDriver."""
    driver_name = "cinder.volume.driver.FibreChannelDriver"

    def test_initialize_connection(self):
        self.assertRaises(NotImplementedError,
                          self.volume.driver.initialize_connection, {}, {})

    def test_validate_connector(self):
        """validate_connector() successful use case.

        validate_connector() does not throw an exception when
        wwpns and wwnns are both set and both are not empty.
        """
        connector = {'wwpns': ["not empty"],
                     'wwnns': ["not empty"]}
        self.volume.driver.validate_connector(connector)

    def test_validate_connector_no_wwpns(self):
        """validate_connector() throws exception when it has no wwpns."""
        connector = {'wwnns': ["not empty"]}
        self.assertRaises(exception.InvalidConnectorException,
                          self.volume.driver.validate_connector, connector)

    def test_validate_connector_empty_wwpns(self):
        """validate_connector() throws exception when it has empty wwpns."""
        connector = {'wwpns': [],
                     'wwnns': ["not empty"]}
        self.assertRaises(exception.InvalidConnectorException,
                          self.volume.driver.validate_connector, connector)

    def test_validate_connector_no_wwnns(self):
        """validate_connector() throws exception when it has no wwnns."""
        connector = {'wwpns': ["not empty"]}
        self.assertRaises(exception.InvalidConnectorException,
                          self.volume.driver.validate_connector, connector)

    def test_validate_connector_empty_wwnns(self):
        """validate_connector() throws exception when it has empty wwnns."""
        connector = {'wwnns': [],
                     'wwpns': ["not empty"]}
        self.assertRaises(exception.InvalidConnectorException,
                          self.volume.driver.validate_connector, connector)
