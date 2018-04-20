
# Copyright 2012 Josh Durgin
# Copyright 2013 Canonical Ltd.
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

import ddt
import math
import os
import tempfile

import mock
from mock import call
from oslo_utils import imageutils
from oslo_utils import units

from cinder import context
from cinder import exception
import cinder.image.glance
from cinder.image import image_utils
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils
from cinder.tests.unit.volume import test_driver
from cinder.volume import configuration as conf
import cinder.volume.drivers.rbd as driver
from cinder.volume.flows.manager import create_volume


# This is used to collect raised exceptions so that tests may check what was
# raised.
# NOTE: this must be initialised in test setUp().
RAISED_EXCEPTIONS = []


class MockException(Exception):

    def __init__(self, *args, **kwargs):
        RAISED_EXCEPTIONS.append(self.__class__)


class MockImageNotFoundException(MockException):
    """Used as mock for rbd.ImageNotFound."""


class MockImageBusyException(MockException):
    """Used as mock for rbd.ImageBusy."""


class MockImageExistsException(MockException):
    """Used as mock for rbd.ImageExists."""


def common_mocks(f):
    """Decorator to set mocks common to all tests.

    The point of doing these mocks here is so that we don't accidentally set
    mocks that can't/don't get unset.
    """
    def _FakeRetrying(wait_func=None,
                      original_retrying = driver.utils.retrying.Retrying,
                      *args, **kwargs):
        return original_retrying(wait_func=lambda *a, **k: 0,
                                 *args, **kwargs)

    def _common_inner_inner1(inst, *args, **kwargs):
        @mock.patch('retrying.Retrying', _FakeRetrying)
        @mock.patch.object(driver.RBDDriver, '_get_usage_info')
        @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
        @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
        @mock.patch('cinder.backup.drivers.ceph.rbd')
        @mock.patch('cinder.backup.drivers.ceph.rados')
        def _common_inner_inner2(mock_rados, mock_rbd, mock_client,
                                 mock_proxy, mock_usage_info):
            inst.mock_rbd = mock_rbd
            inst.mock_rados = mock_rados
            inst.mock_client = mock_client
            inst.mock_proxy = mock_proxy
            inst.mock_rbd.RBD.Error = Exception
            inst.mock_rados.Error = Exception
            inst.mock_rbd.ImageBusy = MockImageBusyException
            inst.mock_rbd.ImageNotFound = MockImageNotFoundException
            inst.mock_rbd.ImageExists = MockImageExistsException
            inst.mock_rbd.InvalidArgument = MockImageNotFoundException

            inst.driver.rbd = inst.mock_rbd
            inst.driver.rados = inst.mock_rados
            return f(inst, *args, **kwargs)

        return _common_inner_inner2()

    return _common_inner_inner1


CEPH_MON_DUMP = r"""dumped monmap epoch 1
{ "epoch": 1,
  "fsid": "33630410-6d93-4d66-8e42-3b953cf194aa",
  "modified": "2013-05-22 17:44:56.343618",
  "created": "2013-05-22 17:44:56.343618",
  "mons": [
        { "rank": 0,
          "name": "a",
          "addr": "[::1]:6789\/0"},
        { "rank": 1,
          "name": "b",
          "addr": "[::1]:6790\/0"},
        { "rank": 2,
          "name": "c",
          "addr": "[::1]:6791\/0"},
        { "rank": 3,
          "name": "d",
          "addr": "127.0.0.1:6792\/0"},
        { "rank": 4,
          "name": "e",
          "addr": "example.com:6791\/0"}],
  "quorum": [
        0,
        1,
        2]}
"""


def mock_driver_configuration(value):
    if value == 'max_over_subscription_ratio':
        return 1.0
    if value == 'reserved_percentage':
        return 0
    return 'RBD'


@ddt.ddt
class RBDTestCase(test.TestCase):

    def setUp(self):
        global RAISED_EXCEPTIONS
        RAISED_EXCEPTIONS = []
        super(RBDTestCase, self).setUp()

        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.image_conversion_dir = None
        self.cfg.rbd_cluster_name = 'nondefault'
        self.cfg.rbd_pool = 'rbd'
        self.cfg.rbd_ceph_conf = '/etc/ceph/my_ceph.conf'
        self.cfg.rbd_keyring_conf = '/etc/ceph/my_ceph.client.keyring'
        self.cfg.rbd_secret_uuid = None
        self.cfg.rbd_user = 'cinder'
        self.cfg.volume_backend_name = None
        self.cfg.volume_dd_blocksize = '1M'
        self.cfg.rbd_store_chunk_size = 4
        self.cfg.rados_connection_retries = 3
        self.cfg.rados_connection_interval = 5

        mock_exec = mock.Mock()
        mock_exec.return_value = ('', '')

        self.driver = driver.RBDDriver(execute=mock_exec,
                                       configuration=self.cfg)
        self.driver.set_initialized()

        self.context = context.get_admin_context()

        self.volume_a = fake_volume.fake_volume_obj(
            self.context,
            **{'name': u'volume-0000000a',
               'id': '4c39c3c7-168f-4b32-b585-77f1b3bf0a38',
               'size': 10})

        self.volume_b = fake_volume.fake_volume_obj(
            self.context,
            **{'name': u'volume-0000000b',
               'id': '0c7d1f44-5a06-403f-bb82-ae7ad0d693a6',
               'size': 10})

        self.snapshot = fake_snapshot.fake_snapshot_obj(
            self.context, name='snapshot-0000000a')

        self.snapshot_b = fake_snapshot.fake_snapshot_obj(
            self.context,
            **{'name': u'snapshot-0000000n',
               'expected_attrs': ['volume'],
               'volume': {'id': fake.VOLUME_ID,
                          'name': 'cinder-volume',
                          'size': 128,
                          'host': 'host@fakebackend#fakepool'}
               })

    @ddt.data({'cluster_name': None, 'pool_name': 'rbd'},
              {'cluster_name': 'volumes', 'pool_name': None})
    @ddt.unpack
    def test_min_config(self, cluster_name, pool_name):
        self.cfg.rbd_cluster_name = cluster_name
        self.cfg.rbd_pool = pool_name

        with mock.patch('cinder.volume.drivers.rbd.rados'):
            self.assertRaises(exception.InvalidConfigurationValue,
                              self.driver.check_for_setup_error)

    def test_parse_replication_config_empty(self):
        self.driver._parse_replication_configs([])
        self.assertEqual([], self.driver._replication_targets)

    def test_parse_replication_config_missing(self):
        """Parsing replication_device without required backend_id."""
        cfg = [{'conf': '/etc/ceph/secondary.conf'}]
        self.assertRaises(exception.InvalidConfigurationValue,
                          self.driver._parse_replication_configs,
                          cfg)

    def test_parse_replication_config_defaults(self):
        """Parsing replication_device with default conf and user."""
        cfg = [{'backend_id': 'secondary-backend'}]
        expected = [{'name': 'secondary-backend',
                     'conf': '/etc/ceph/secondary-backend.conf',
                     'user': 'cinder'}]
        self.driver._parse_replication_configs(cfg)
        self.assertEqual(expected, self.driver._replication_targets)

    @ddt.data(1, 2)
    def test_parse_replication_config(self, num_targets):
        cfg = [{'backend_id': 'secondary-backend',
                'conf': 'foo',
                'user': 'bar'},
               {'backend_id': 'tertiary-backend'}]
        expected = [{'name': 'secondary-backend',
                     'conf': 'foo',
                     'user': 'bar'},
                    {'name': 'tertiary-backend',
                     'conf': '/etc/ceph/tertiary-backend.conf',
                     'user': 'cinder'}]
        self.driver._parse_replication_configs(cfg[:num_targets])
        self.assertEqual(expected[:num_targets],
                         self.driver._replication_targets)

    def test_do_setup_replication_disabled(self):
        with mock.patch.object(self.driver.configuration, 'safe_get',
                               return_value=None):
            self.driver.do_setup(self.context)
            self.assertFalse(self.driver._is_replication_enabled)
            self.assertEqual([], self.driver._replication_targets)
            self.assertEqual([], self.driver._target_names)
            self.assertEqual({'name': self.cfg.rbd_cluster_name,
                              'conf': self.cfg.rbd_ceph_conf,
                              'user': self.cfg.rbd_user},
                             self.driver._active_config)

    def test_do_setup_replication(self):
        cfg = [{'backend_id': 'secondary-backend',
                'conf': 'foo',
                'user': 'bar'}]
        expected = [{'name': 'secondary-backend',
                     'conf': 'foo',
                     'user': 'bar'}]

        with mock.patch.object(self.driver.configuration, 'safe_get',
                               return_value=cfg):
            self.driver.do_setup(self.context)
            self.assertTrue(self.driver._is_replication_enabled)
            self.assertEqual(expected, self.driver._replication_targets)
            self.assertEqual({'name': self.cfg.rbd_cluster_name,
                              'conf': self.cfg.rbd_ceph_conf,
                              'user': self.cfg.rbd_user},
                             self.driver._active_config)

    def test_do_setup_replication_failed_over(self):
        cfg = [{'backend_id': 'secondary-backend',
                'conf': 'foo',
                'user': 'bar'}]
        expected = [{'name': 'secondary-backend',
                     'conf': 'foo',
                     'user': 'bar'}]
        self.driver._active_backend_id = 'secondary-backend'

        with mock.patch.object(self.driver.configuration, 'safe_get',
                               return_value=cfg):
            self.driver.do_setup(self.context)
            self.assertTrue(self.driver._is_replication_enabled)
            self.assertEqual(expected, self.driver._replication_targets)
            self.assertEqual(expected[0], self.driver._active_config)

    def test_do_setup_replication_failed_over_unknown(self):
        cfg = [{'backend_id': 'secondary-backend',
                'conf': 'foo',
                'user': 'bar'}]
        self.driver._active_backend_id = 'unknown-backend'

        with mock.patch.object(self.driver.configuration, 'safe_get',
                               return_value=cfg):
            self.assertRaises(exception.InvalidReplicationTarget,
                              self.driver.do_setup,
                              self.context)

    @mock.patch.object(driver.RBDDriver, '_enable_replication',
                       return_value=mock.sentinel.volume_update)
    def test_enable_replication_if_needed_replicated_volume(self, mock_enable):
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            extra_specs={'replication_enabled': '<is> True'})
        res = self.driver._enable_replication_if_needed(self.volume_a)
        self.assertEqual(mock.sentinel.volume_update, res)
        mock_enable.assert_called_once_with(self.volume_a)

    @ddt.data(False, True)
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_enable_replication_if_needed_non_replicated(self, enabled,
                                                         mock_enable):
        self.driver._is_replication_enabled = enabled
        res = self.driver._enable_replication_if_needed(self.volume_a)
        if enabled:
            expect = {'replication_status': fields.ReplicationStatus.DISABLED}
        else:
            expect = None
        self.assertEqual(expect, res)
        mock_enable.assert_not_called()

    @ddt.data([True, False], [False, False], [True, True])
    @ddt.unpack
    @common_mocks
    def test_enable_replication(self, exclusive_lock_enabled,
                                journaling_enabled):
        """Test _enable_replication method.

        We want to confirm that if the Ceph backend has globally enabled
        'exclusive_lock' and 'journaling'. we don't try to enable them
        again and we properly indicate with our return value that they were
        already enabled.
        'journaling' depends on 'exclusive_lock', so if 'exclusive-lock'
        is disabled, 'journaling' can't be enabled so the '[False. True]'
        case is impossible.
        In this test case, there are three test scenarios:
        1. 'exclusive_lock' and 'journaling' both enabled,
        'image.features()' will not be called.
        2. 'exclusive_lock' enabled, 'journaling' disabled,
        'image.features()' will be only called for 'journaling'.
        3. 'exclusice_lock' and 'journaling' are both disabled,
        'image.features()'will be both called for 'exclusive-lock' and
        'journaling' in this order.
        """
        journaling_feat = 1
        exclusive_lock_feat = 2
        self.driver.rbd.RBD_FEATURE_JOURNALING = journaling_feat
        self.driver.rbd.RBD_FEATURE_EXCLUSIVE_LOCK = exclusive_lock_feat
        image = self.mock_proxy.return_value.__enter__.return_value
        image.features.return_value = 0
        if exclusive_lock_enabled:
            image.features.return_value += exclusive_lock_feat
        if journaling_enabled:
            image.features.return_value += journaling_feat
        journaling_status = str(journaling_enabled).lower()
        exclusive_lock_status = str(exclusive_lock_enabled).lower()
        expected = {
            'replication_driver_data': ('{"had_exclusive_lock":%s,'
                                        '"had_journaling":%s}' %
                                        (exclusive_lock_status,
                                         journaling_status)),
            'replication_status': 'enabled',
        }
        res = self.driver._enable_replication(self.volume_a)
        self.assertEqual(expected, res)
        if exclusive_lock_enabled and journaling_enabled:
            image.update_features.assert_not_called()
        elif exclusive_lock_enabled and not journaling_enabled:
            image.update_features.assert_called_once_with(journaling_feat,
                                                          True)
        else:
            calls = [call(exclusive_lock_feat, True),
                     call(journaling_feat, True)]
            image.update_features.assert_has_calls(calls, any_order=False)
        image.mirror_image_enable.assert_called_once_with()

    @ddt.data(['false', 'true'], ['true', 'true'], ['false', 'false'])
    @ddt.unpack
    @common_mocks
    def test_disable_replication(self, had_journaling, had_exclusive_lock):
        driver_data = ('{"had_journaling": %s,"had_exclusive_lock": %s}' %
                       (had_journaling, had_exclusive_lock))
        self.volume_a.replication_driver_data = driver_data
        image = self.mock_proxy.return_value.__enter__.return_value

        res = self.driver._disable_replication(self.volume_a)
        expected = {'replication_status': fields.ReplicationStatus.DISABLED,
                    'replication_driver_data': None}
        self.assertEqual(expected, res)
        image.mirror_image_disable.assert_called_once_with(False)

        if had_journaling == 'true' and had_exclusive_lock == 'true':
            image.update_features.assert_not_called()
        elif had_journaling == 'false' and had_exclusive_lock == 'true':
            image.update_features.assert_called_once_with(
                self.driver.rbd.RBD_FEATURE_JOURNALING, False)
        else:
            calls = [call(self.driver.rbd.RBD_FEATURE_JOURNALING, False),
                     call(self.driver.rbd.RBD_FEATURE_EXCLUSIVE_LOCK,
                          False)]
            image.update_features.assert_has_calls(calls, any_order=False)

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_create_volume(self, mock_enable_repl):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        res = self.driver.create_volume(self.volume_a)

        self.assertIsNone(res)
        chunk_size = self.cfg.rbd_store_chunk_size * units.Mi
        order = int(math.log(chunk_size, 2))
        args = [client.ioctx, str(self.volume_a.name),
                self.volume_a.size * units.Gi, order]
        kwargs = {'old_format': False,
                  'features': client.features}
        self.mock_rbd.RBD.return_value.create.assert_called_once_with(
            *args, **kwargs)
        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)
        mock_enable_repl.assert_not_called()

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_create_volume_replicated(self, mock_enable_repl):
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            extra_specs={'replication_enabled': '<is> True'})

        client = self.mock_client.return_value
        client.__enter__.return_value = client

        expected_update = {
            'replication_status': 'enabled',
            'replication_driver_data': '{"had_journaling": false}'
        }
        mock_enable_repl.return_value = expected_update

        res = self.driver.create_volume(self.volume_a)
        self.assertEqual(expected_update, res)
        mock_enable_repl.assert_called_once_with(self.volume_a)

        chunk_size = self.cfg.rbd_store_chunk_size * units.Mi
        order = int(math.log(chunk_size, 2))
        self.mock_rbd.RBD.return_value.create.assert_called_once_with(
            client.ioctx, self.volume_a.name, self.volume_a.size * units.Gi,
            order, old_format=False, features=client.features)

        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)

    @common_mocks
    def test_create_encrypted_volume(self):
        self.volume_a.encryption_key_id = \
            '00000000-0000-0000-0000-000000000000'
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume,
                          self.volume_a)

    @common_mocks
    def test_manage_existing_get_size(self):
        with mock.patch.object(self.driver.rbd.Image(), 'size') as \
                mock_rbd_image_size:
            with mock.patch.object(self.driver.rbd.Image(), 'close') \
                    as mock_rbd_image_close:
                mock_rbd_image_size.return_value = 2 * units.Gi
                existing_ref = {'source-name': self.volume_a.name}
                return_size = self.driver.manage_existing_get_size(
                    self.volume_a,
                    existing_ref)
                self.assertEqual(2, return_size)
                mock_rbd_image_size.assert_called_once_with()
                mock_rbd_image_close.assert_called_once_with()

    @common_mocks
    def test_manage_existing_get_non_integer_size(self):
        rbd_image = self.driver.rbd.Image.return_value
        rbd_image.size.return_value = int(1.75 * units.Gi)
        existing_ref = {'source-name': self.volume_a.name}
        return_size = self.driver.manage_existing_get_size(self.volume_a,
                                                           existing_ref)
        self.assertEqual(2, return_size)
        rbd_image.size.assert_called_once_with()
        rbd_image.close.assert_called_once_with()

    @common_mocks
    def test_manage_existing_get_invalid_size(self):

        with mock.patch.object(self.driver.rbd.Image(), 'size') as \
                mock_rbd_image_size:
            with mock.patch.object(self.driver.rbd.Image(), 'close') \
                    as mock_rbd_image_close:
                mock_rbd_image_size.return_value = 'abcd'
                existing_ref = {'source-name': self.volume_a.name}
                self.assertRaises(exception.VolumeBackendAPIException,
                                  self.driver.manage_existing_get_size,
                                  self.volume_a, existing_ref)

                mock_rbd_image_size.assert_called_once_with()
                mock_rbd_image_close.assert_called_once_with()

    @common_mocks
    def test_manage_existing(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver.rbd.RBD(), 'rename') as \
                mock_rbd_image_rename:
            exist_volume = 'vol-exist'
            existing_ref = {'source-name': exist_volume}
            mock_rbd_image_rename.return_value = 0
            self.driver.manage_existing(self.volume_a, existing_ref)
            mock_rbd_image_rename.assert_called_with(
                client.ioctx,
                exist_volume,
                self.volume_a.name)

    @common_mocks
    def test_manage_existing_with_exist_rbd_image(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        self.mock_rbd.RBD.return_value.rename.side_effect = (
            MockImageExistsException)

        exist_volume = 'vol-exist'
        existing_ref = {'source-name': exist_volume}
        self.assertRaises(self.mock_rbd.ImageExists,
                          self.driver.manage_existing,
                          self.volume_a, existing_ref)

        # Make sure the exception was raised
        self.assertEqual(RAISED_EXCEPTIONS,
                         [self.mock_rbd.ImageExists])

    @common_mocks
    def test_manage_existing_with_invalid_rbd_image(self):
        self.mock_rbd.Image.side_effect = self.mock_rbd.ImageNotFound

        invalid_volume = 'vol-invalid'
        invalid_ref = {'source-name': invalid_volume}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          self.volume_a, invalid_ref)
        # Make sure the exception was raised
        self.assertEqual([self.mock_rbd.ImageNotFound],
                         RAISED_EXCEPTIONS)

    @common_mocks
    def test_delete_backup_snaps(self):
        self.driver.rbd.Image.remove_snap = mock.Mock()
        with mock.patch.object(self.driver, '_get_backup_snaps') as \
                mock_get_backup_snaps:
            mock_get_backup_snaps.return_value = [{'name': 'snap1'}]
            rbd_image = self.driver.rbd.Image()
            self.driver._delete_backup_snaps(rbd_image)
            mock_get_backup_snaps.assert_called_once_with(rbd_image)
            self.assertTrue(
                self.driver.rbd.Image.return_value.remove_snap.called)

    @common_mocks
    def test_delete_volume(self):
        client = self.mock_client.return_value

        self.driver.rbd.Image.return_value.list_snaps.return_value = []

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            with mock.patch.object(self.driver, '_delete_backup_snaps') as \
                    mock_delete_backup_snaps:
                mock_get_clone_info.return_value = (None, None, None)

                self.driver.delete_volume(self.volume_a)

                mock_get_clone_info.assert_called_once_with(
                    self.mock_rbd.Image.return_value,
                    self.volume_a.name,
                    None)
                (self.driver.rbd.Image.return_value
                    .list_snaps.assert_called_once_with())
                client.__enter__.assert_called_once_with()
                client.__exit__.assert_called_once_with(None, None, None)
                mock_delete_backup_snaps.assert_called_once_with(
                    self.mock_rbd.Image.return_value)
                self.assertFalse(
                    self.driver.rbd.Image.return_value.unprotect_snap.called)
                self.assertEqual(
                    1, self.driver.rbd.RBD.return_value.remove.call_count)

    @common_mocks
    def delete_volume_not_found(self):
        self.mock_rbd.Image.side_effect = self.mock_rbd.ImageNotFound
        self.assertIsNone(self.driver.delete_volume(self.volume_a))
        self.mock_rbd.Image.assert_called_once_with()
        # Make sure the exception was raised
        self.assertEqual(RAISED_EXCEPTIONS, [self.mock_rbd.ImageNotFound])

    @common_mocks
    def test_delete_busy_volume(self):
        self.mock_rbd.Image.return_value.list_snaps.return_value = []

        self.mock_rbd.RBD.return_value.remove.side_effect = (
            self.mock_rbd.ImageBusy)

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            mock_get_clone_info.return_value = (None, None, None)
            with mock.patch.object(self.driver, '_delete_backup_snaps') as \
                    mock_delete_backup_snaps:
                with mock.patch.object(driver, 'RADOSClient') as \
                        mock_rados_client:
                    self.assertRaises(exception.VolumeIsBusy,
                                      self.driver.delete_volume, self.volume_a)

                    mock_get_clone_info.assert_called_once_with(
                        self.mock_rbd.Image.return_value,
                        self.volume_a.name,
                        None)
                    (self.mock_rbd.Image.return_value.list_snaps
                     .assert_called_once_with())
                    mock_rados_client.assert_called_once_with(self.driver)
                    mock_delete_backup_snaps.assert_called_once_with(
                        self.mock_rbd.Image.return_value)
                    self.assertFalse(
                        self.mock_rbd.Image.return_value.unprotect_snap.called)
                    self.assertEqual(
                        3, self.mock_rbd.RBD.return_value.remove.call_count)
                    self.assertEqual(3, len(RAISED_EXCEPTIONS))
                    # Make sure the exception was raised
                    self.assertIn(self.mock_rbd.ImageBusy, RAISED_EXCEPTIONS)

    @common_mocks
    def test_delete_volume_not_found(self):
        self.mock_rbd.Image.return_value.list_snaps.return_value = []

        self.mock_rbd.RBD.return_value.remove.side_effect = (
            self.mock_rbd.ImageNotFound)

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            mock_get_clone_info.return_value = (None, None, None)
            with mock.patch.object(self.driver, '_delete_backup_snaps') as \
                    mock_delete_backup_snaps:
                with mock.patch.object(driver, 'RADOSClient') as \
                        mock_rados_client:
                    self.assertIsNone(self.driver.delete_volume(self.volume_a))
                    mock_get_clone_info.assert_called_once_with(
                        self.mock_rbd.Image.return_value,
                        self.volume_a.name,
                        None)
                    (self.mock_rbd.Image.return_value.list_snaps
                     .assert_called_once_with())
                    mock_rados_client.assert_called_once_with(self.driver)
                    mock_delete_backup_snaps.assert_called_once_with(
                        self.mock_rbd.Image.return_value)
                    self.assertFalse(
                        self.mock_rbd.Image.return_value.unprotect_snap.called)
                    self.assertEqual(
                        1, self.mock_rbd.RBD.return_value.remove.call_count)
                    # Make sure the exception was raised
                    self.assertEqual(RAISED_EXCEPTIONS,
                                     [self.mock_rbd.ImageNotFound])

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    def test_create_snapshot(self, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        self.driver.create_snapshot(self.snapshot)

        args = [str(self.snapshot.name)]
        proxy.create_snap.assert_called_with(*args)
        proxy.protect_snap.assert_called_with(*args)

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    def test_delete_snapshot(self, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        self.driver.delete_snapshot(self.snapshot)

        proxy.remove_snap.assert_called_with(self.snapshot.name)
        proxy.unprotect_snap.assert_called_with(self.snapshot.name)

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    def test_delete_notfound_snapshot(self, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        proxy.unprotect_snap.side_effect = (
            self.mock_rbd.ImageNotFound)

        self.driver.delete_snapshot(self.snapshot)

        proxy.remove_snap.assert_called_with(self.snapshot.name)
        proxy.unprotect_snap.assert_called_with(self.snapshot.name)

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    def test_delete_notfound_on_remove_snapshot(self, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        proxy.remove_snap.side_effect = (
            self.mock_rbd.ImageNotFound)

        self.driver.delete_snapshot(self.snapshot)

        proxy.remove_snap.assert_called_with(self.snapshot.name)
        proxy.unprotect_snap.assert_called_with(self.snapshot.name)

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    def test_delete_unprotected_snapshot(self, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.unprotect_snap.side_effect = self.mock_rbd.InvalidArgument

        self.driver.delete_snapshot(self.snapshot)
        self.assertTrue(proxy.unprotect_snap.called)
        self.assertTrue(proxy.remove_snap.called)

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    def test_delete_busy_snapshot(self, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        proxy.unprotect_snap.side_effect = (
            self.mock_rbd.ImageBusy)

        with mock.patch.object(self.driver, '_get_children_info') as \
                mock_get_children_info:
            mock_get_children_info.return_value = [('pool', 'volume2')]

            with mock.patch.object(driver, 'LOG') as \
                    mock_log:

                self.assertRaises(exception.SnapshotIsBusy,
                                  self.driver.delete_snapshot,
                                  self.snapshot)

                mock_get_children_info.assert_called_once_with(
                    proxy,
                    self.snapshot.name)

                self.assertTrue(mock_log.info.called)
                self.assertTrue(proxy.unprotect_snap.called)
                self.assertFalse(proxy.remove_snap.called)

    @common_mocks
    def test_get_children_info(self):
        volume = self.mock_proxy
        volume.set_snap = mock.Mock()
        volume.list_children = mock.Mock()
        list_children = [('pool', 'volume2')]
        volume.list_children.return_value = list_children

        info = self.driver._get_children_info(volume,
                                              self.snapshot['name'])

        self.assertEqual(list_children, info)

    @common_mocks
    def test_get_clone_info(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_a.name))
        volume.parent_info.return_value = parent_info

        info = self.driver._get_clone_info(volume, self.volume_a.name)

        self.assertEqual(parent_info, info)

        self.assertFalse(volume.set_snap.called)
        volume.parent_info.assert_called_once_with()

    @common_mocks
    def test_get_clone_info_w_snap(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_a.name))
        volume.parent_info.return_value = parent_info

        snapshot = self.mock_rbd.ImageSnapshot()

        info = self.driver._get_clone_info(volume, self.volume_a.name,
                                           snap=snapshot)

        self.assertEqual(parent_info, info)

        self.assertEqual(2, volume.set_snap.call_count)
        volume.parent_info.assert_called_once_with()

    @common_mocks
    def test_get_clone_info_w_exception(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        volume.parent_info.side_effect = self.mock_rbd.ImageNotFound

        snapshot = self.mock_rbd.ImageSnapshot()

        info = self.driver._get_clone_info(volume, self.volume_a.name,
                                           snap=snapshot)

        self.assertEqual((None, None, None), info)

        self.assertEqual(2, volume.set_snap.call_count)
        volume.parent_info.assert_called_once_with()
        # Make sure the exception was raised
        self.assertEqual(RAISED_EXCEPTIONS, [self.mock_rbd.ImageNotFound])

    @common_mocks
    def test_get_clone_info_deleted_volume(self):
        volume = self.mock_rbd.Image()
        volume.set_snap = mock.Mock()
        volume.parent_info = mock.Mock()
        parent_info = ('a', 'b', '%s.clone_snap' % (self.volume_a.name))
        volume.parent_info.return_value = parent_info

        info = self.driver._get_clone_info(volume,
                                           "%s.deleted" % (self.volume_a.name))

        self.assertEqual(parent_info, info)

        self.assertFalse(volume.set_snap.called)
        volume.parent_info.assert_called_once_with()

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_create_cloned_volume_same_size(self, mock_enable_repl):
        self.cfg.rbd_max_clone_depth = 2

        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            with mock.patch.object(self.driver, '_resize') as mock_resize:
                mock_get_clone_depth.return_value = 1

                res = self.driver.create_cloned_volume(self.volume_b,
                                                       self.volume_a)

                self.assertIsNone(res)
                (self.mock_rbd.Image.return_value.create_snap
                    .assert_called_once_with('.'.join(
                        (self.volume_b.name, 'clone_snap'))))
                (self.mock_rbd.Image.return_value.protect_snap
                    .assert_called_once_with('.'.join(
                        (self.volume_b.name, 'clone_snap'))))
                self.assertEqual(
                    1, self.mock_rbd.RBD.return_value.clone.call_count)
                self.mock_rbd.Image.return_value.close \
                    .assert_called_once_with()
                self.assertTrue(mock_get_clone_depth.called)
                mock_resize.assert_not_called()
                mock_enable_repl.assert_not_called()

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_get_clone_depth', return_value=1)
    @mock.patch.object(driver.RBDDriver, '_resize')
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_create_cloned_volume_replicated(self,
                                             mock_enable_repl,
                                             mock_resize,
                                             mock_get_clone_depth):
        self.cfg.rbd_max_clone_depth = 2
        self.volume_b.volume_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            extra_specs={'replication_enabled': '<is> True'})

        expected_update = {
            'replication_status': 'enabled',
            'replication_driver_data': '{"had_journaling": false}'
        }
        mock_enable_repl.return_value = expected_update

        res = self.driver.create_cloned_volume(self.volume_b, self.volume_a)
        self.assertEqual(expected_update, res)
        mock_enable_repl.assert_called_once_with(self.volume_b)

        name = self.volume_b.name
        image = self.mock_rbd.Image.return_value

        image.create_snap.assert_called_once_with(name + '.clone_snap')
        image.protect_snap.assert_called_once_with(name + '.clone_snap')
        self.assertEqual(1, self.mock_rbd.RBD.return_value.clone.call_count)
        self.mock_rbd.Image.return_value.close.assert_called_once_with()
        mock_get_clone_depth.assert_called_once_with(
            self.mock_client().__enter__(), self.volume_a.name)
        mock_resize.assert_not_called()

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_create_cloned_volume_different_size(self, mock_enable_repl):
        self.cfg.rbd_max_clone_depth = 2

        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            with mock.patch.object(self.driver, '_resize') as mock_resize:
                mock_get_clone_depth.return_value = 1

                self.volume_b.size = 20
                res = self.driver.create_cloned_volume(self.volume_b,
                                                       self.volume_a)

                self.assertIsNone(res)
                (self.mock_rbd.Image.return_value.create_snap
                    .assert_called_once_with('.'.join(
                        (self.volume_b.name, 'clone_snap'))))
                (self.mock_rbd.Image.return_value.protect_snap
                    .assert_called_once_with('.'.join(
                        (self.volume_b.name, 'clone_snap'))))
                self.assertEqual(
                    1, self.mock_rbd.RBD.return_value.clone.call_count)
                self.mock_rbd.Image.return_value.close \
                    .assert_called_once_with()
                self.assertTrue(mock_get_clone_depth.called)
                self.assertEqual(
                    1, mock_resize.call_count)
                mock_enable_repl.assert_not_called()

    @common_mocks
    def test_create_cloned_volume_different_size_copy_only(self):
        self.cfg.rbd_max_clone_depth = 0

        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            with mock.patch.object(self.driver, '_resize') as mock_resize:
                mock_get_clone_depth.return_value = 1

                self.volume_b.size = 20
                self.driver.create_cloned_volume(self.volume_b, self.volume_a)

                self.assertEqual(1, mock_resize.call_count)

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_create_cloned_volume_w_flatten(self, mock_enable_repl):
        self.cfg.rbd_max_clone_depth = 1

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            mock_get_clone_info.return_value = (
                ('fake_pool', self.volume_b.name,
                 '.'.join((self.volume_b.name, 'clone_snap'))))
            with mock.patch.object(self.driver, '_get_clone_depth') as \
                    mock_get_clone_depth:
                # Try with no flatten required
                mock_get_clone_depth.return_value = 1

                res = self.driver.create_cloned_volume(self.volume_b,
                                                       self.volume_a)

                self.assertIsNone(res)
                (self.mock_rbd.Image.return_value.create_snap
                 .assert_called_once_with('.'.join(
                     (self.volume_b.name, 'clone_snap'))))
                (self.mock_rbd.Image.return_value.protect_snap
                 .assert_called_once_with('.'.join(
                     (self.volume_b.name, 'clone_snap'))))
                self.assertEqual(
                    1, self.mock_rbd.RBD.return_value.clone.call_count)
                (self.mock_rbd.Image.return_value.unprotect_snap
                 .assert_called_once_with('.'.join(
                     (self.volume_b.name, 'clone_snap'))))
                (self.mock_rbd.Image.return_value.remove_snap
                 .assert_called_once_with('.'.join(
                     (self.volume_b.name, 'clone_snap'))))

                # We expect the driver to close both volumes, so 2 is expected
                self.assertEqual(
                    2, self.mock_rbd.Image.return_value.close.call_count)
                self.assertTrue(mock_get_clone_depth.called)
                mock_enable_repl.assert_not_called()

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_create_cloned_volume_w_clone_exception(self, mock_enable_repl):
        self.cfg.rbd_max_clone_depth = 2
        self.mock_rbd.RBD.return_value.clone.side_effect = (
            self.mock_rbd.RBD.Error)
        with mock.patch.object(self.driver, '_get_clone_depth') as \
                mock_get_clone_depth:
            # Try with no flatten required
            mock_get_clone_depth.return_value = 1

            self.assertRaises(self.mock_rbd.RBD.Error,
                              self.driver.create_cloned_volume,
                              self.volume_b, self.volume_a)

            (self.mock_rbd.Image.return_value.create_snap
                .assert_called_once_with('.'.join(
                    (self.volume_b.name, 'clone_snap'))))
            (self.mock_rbd.Image.return_value.protect_snap
                .assert_called_once_with('.'.join(
                    (self.volume_b.name, 'clone_snap'))))
            self.assertEqual(
                1, self.mock_rbd.RBD.return_value.clone.call_count)
            (self.mock_rbd.Image.return_value.unprotect_snap
             .assert_called_once_with('.'.join(
                 (self.volume_b.name, 'clone_snap'))))
            (self.mock_rbd.Image.return_value.remove_snap
             .assert_called_once_with('.'.join(
                 (self.volume_b.name, 'clone_snap'))))
            self.mock_rbd.Image.return_value.close.assert_called_once_with()
            mock_enable_repl.assert_not_called()

    @common_mocks
    def test_good_locations(self):
        locations = ['rbd://fsid/pool/image/snap',
                     'rbd://%2F/%2F/%2F/%2F', ]
        map(self.driver._parse_location, locations)

    @common_mocks
    def test_bad_locations(self):
        locations = ['rbd://image',
                     'http://path/to/somewhere/else',
                     'rbd://image/extra',
                     'rbd://image/',
                     'rbd://fsid/pool/image/',
                     'rbd://fsid/pool/image/snap/',
                     'rbd://///', ]
        for loc in locations:
            self.assertRaises(exception.ImageUnacceptable,
                              self.driver._parse_location,
                              loc)
            self.assertFalse(
                self.driver._is_cloneable(loc, {'disk_format': 'raw'}))

    @common_mocks
    def test_cloneable(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://abc/pool/image/snap'
            info = {'disk_format': 'raw'}
            self.assertTrue(self.driver._is_cloneable(location, info))
            self.assertTrue(mock_get_fsid.called)

    @common_mocks
    def test_uncloneable_different_fsid(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://def/pool/image/snap'
            self.assertFalse(
                self.driver._is_cloneable(location, {'disk_format': 'raw'}))
            self.assertTrue(mock_get_fsid.called)

    @common_mocks
    def test_uncloneable_unreadable(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://abc/pool/image/snap'

            self.driver.rbd.Error = Exception
            self.mock_proxy.side_effect = Exception

            args = [location, {'disk_format': 'raw'}]
            self.assertFalse(self.driver._is_cloneable(*args))
            self.assertEqual(1, self.mock_proxy.call_count)
            self.assertTrue(mock_get_fsid.called)

    @common_mocks
    def test_uncloneable_bad_format(self):
        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            location = 'rbd://abc/pool/image/snap'
            formats = ['qcow2', 'vmdk', 'vdi']
            for f in formats:
                self.assertFalse(
                    self.driver._is_cloneable(location, {'disk_format': f}))
            self.assertTrue(mock_get_fsid.called)

    def _copy_image(self):
        with mock.patch.object(tempfile, 'NamedTemporaryFile'):
            with mock.patch.object(os.path, 'exists') as mock_exists:
                mock_exists.return_value = True
                with mock.patch.object(image_utils, 'fetch_to_raw'):
                    with mock.patch.object(self.driver, 'delete_volume'):
                        with mock.patch.object(self.driver, '_resize'):
                            mock_image_service = mock.MagicMock()
                            args = [None, self.volume_a,
                                    mock_image_service, None]
                            self.driver.copy_image_to_volume(*args)

    @common_mocks
    def test_copy_image_no_volume_tmp(self):
        self.cfg.image_conversion_dir = None
        self._copy_image()

    @common_mocks
    def test_copy_image_volume_tmp(self):
        self.cfg.image_conversion_dir = '/var/run/cinder/tmp'
        self._copy_image()

    @ddt.data(True, False)
    @common_mocks
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_usage_info')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_pool_stats')
    def test_update_volume_stats(self, replication_enabled, stats_mock,
                                 usage_mock):
        stats_mock.return_value = (mock.sentinel.free_capacity_gb,
                                   mock.sentinel.total_capacity_gb)
        usage_mock.return_value = mock.sentinel.provisioned_capacity_gb

        expected = dict(
            volume_backend_name='RBD',
            replication_enabled=replication_enabled,
            vendor_name='Open Source',
            driver_version=self.driver.VERSION,
            storage_protocol='ceph',
            total_capacity_gb=mock.sentinel.total_capacity_gb,
            free_capacity_gb=mock.sentinel.free_capacity_gb,
            reserved_percentage=0,
            thin_provisioning_support=True,
            provisioned_capacity_gb=mock.sentinel.provisioned_capacity_gb,
            max_over_subscription_ratio=1.0,
            multiattach=False)

        if replication_enabled:
            targets = [{'backend_id': 'secondary-backend'},
                       {'backend_id': 'tertiary-backend'}]
            with mock.patch.object(self.driver.configuration, 'safe_get',
                                   return_value=targets):
                self.driver._do_setup_replication()
            expected['replication_targets'] = [t['backend_id']for t in targets]
            expected['replication_targets'].append('default')

        self.mock_object(self.driver.configuration, 'safe_get',
                         mock_driver_configuration)

        actual = self.driver.get_volume_stats(True)
        self.assertDictEqual(expected, actual)

    @common_mocks
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_usage_info')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_pool_stats')
    def test_update_volume_stats_error(self, stats_mock, usage_mock):
        self.mock_object(self.driver.configuration, 'safe_get',
                         mock_driver_configuration)

        expected = dict(volume_backend_name='RBD',
                        replication_enabled=False,
                        vendor_name='Open Source',
                        driver_version=self.driver.VERSION,
                        storage_protocol='ceph',
                        total_capacity_gb='unknown',
                        free_capacity_gb='unknown',
                        reserved_percentage=0,
                        multiattach=False,
                        provisioned_capacity_gb=0,
                        max_over_subscription_ratio=1.0,
                        thin_provisioning_support=True)

        actual = self.driver.get_volume_stats(True)
        self.assertDictEqual(expected, actual)

    @ddt.data(
        # Normal case, no quota and dynamic total
        {'free_capacity': 27.0, 'total_capacity': 28.44},
        # No quota and static total
        {'dynamic_total': False,
         'free_capacity': 27.0, 'total_capacity': 59.96},
        # Quota and dynamic total
        {'quota_max_bytes': 3221225472, 'max_avail': 1073741824,
         'free_capacity': 1, 'total_capacity': 2.44},
        # Quota and static total
        {'quota_max_bytes': 3221225472, 'max_avail': 1073741824,
         'dynamic_total': False,
         'free_capacity': 1, 'total_capacity': 3.00},
        # Quota and dynamic total when free would be negative
        {'quota_max_bytes': 1073741824,
         'free_capacity': 0, 'total_capacity': 1.44},
    )
    @ddt.unpack
    @common_mocks
    def test_get_pool(self, free_capacity, total_capacity,
                      max_avail=28987613184, quota_max_bytes=0,
                      dynamic_total=True):
        client = self.mock_client.return_value
        client.__enter__.return_value = client
        client.cluster.mon_command.side_effect = [
            (0, '{"stats":{"total_bytes":64385286144,'
             '"total_used_bytes":3289628672,"total_avail_bytes":61095657472},'
             '"pools":[{"name":"rbd","id":2,"stats":{"kb_used":1510197,'
             '"bytes_used":1546440971,"max_avail":%s,"objects":412}},'
             '{"name":"volumes","id":3,"stats":{"kb_used":0,"bytes_used":0,'
             '"max_avail":28987613184,"objects":0}}]}\n' % max_avail, ''),
            (0, '{"pool_name":"volumes","pool_id":4,"quota_max_objects":0,'
             '"quota_max_bytes":%s}\n' % quota_max_bytes, ''),
        ]
        with mock.patch.object(self.driver.configuration, 'safe_get',
                               return_value=dynamic_total):
            result = self.driver._get_pool_stats()
        client.cluster.mon_command.assert_has_calls([
            mock.call('{"prefix":"df", "format":"json"}', ''),
            mock.call('{"prefix":"osd pool get-quota", "pool": "rbd",'
                      ' "format":"json"}', ''),
        ])
        self.assertEqual((free_capacity, total_capacity), result)

    @common_mocks
    def test_get_pool_stats_failure(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client
        client.cluster.mon_command.return_value = (-1, '', '')

        result = self.driver._get_pool_stats()
        self.assertEqual(('unknown', 'unknown'), result)

    @common_mocks
    def test_get_mon_addrs(self):
        with mock.patch.object(self.driver, '_execute') as mock_execute:
            mock_execute.return_value = (CEPH_MON_DUMP, '')
            hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
            ports = ['6789', '6790', '6791', '6792', '6791']
            self.assertEqual((hosts, ports), self.driver._get_mon_addrs())

    @common_mocks
    def _initialize_connection_helper(self, expected, hosts, ports):

        with mock.patch.object(self.driver, '_get_mon_addrs') as \
                mock_get_mon_addrs:
            mock_get_mon_addrs.return_value = (hosts, ports)
            actual = self.driver.initialize_connection(self.volume_a, None)
            self.assertDictEqual(expected, actual)
            self.assertTrue(mock_get_mon_addrs.called)

    @mock.patch.object(cinder.volume.drivers.rbd.RBDDriver,
                       '_get_keyring_contents')
    def test_initialize_connection(self, mock_keyring):
        hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']

        keyring_data = "[client.cinder]\n  key = test\n"
        mock_keyring.return_value = keyring_data

        expected = {
            'driver_volume_type': 'rbd',
            'data': {
                'name': '%s/%s' % (self.cfg.rbd_pool,
                                   self.volume_a.name),
                'hosts': hosts,
                'ports': ports,
                'cluster_name': self.cfg.rbd_cluster_name,
                'auth_enabled': True,
                'auth_username': self.cfg.rbd_user,
                'secret_type': 'ceph',
                'secret_uuid': None,
                'volume_id': self.volume_a.id,
                'discard': True,
                'keyring': keyring_data,
            }
        }
        self._initialize_connection_helper(expected, hosts, ports)

        # Check how it will work with empty keyring path
        mock_keyring.return_value = None
        expected['data']['keyring'] = None
        self._initialize_connection_helper(expected, hosts, ports)

    def test__get_keyring_contents_no_config_file(self):
        self.cfg.rbd_keyring_conf = ''
        self.assertIsNone(self.driver._get_keyring_contents())

    @mock.patch('os.path.isfile')
    def test__get_keyring_contents_read_file(self, mock_isfile):
        mock_isfile.return_value = True
        keyring_data = "[client.cinder]\n  key = test\n"
        mockopen = mock.mock_open(read_data=keyring_data)
        mockopen.return_value.__exit__ = mock.Mock()
        with mock.patch('cinder.volume.drivers.rbd.open', mockopen,
                        create=True):
            self.assertEqual(self.driver._get_keyring_contents(), keyring_data)

    @mock.patch('os.path.isfile')
    def test__get_keyring_contents_raise_error(self, mock_isfile):
        mock_isfile.return_value = True
        mockopen = mock.mock_open()
        mockopen.return_value.__exit__ = mock.Mock()
        with mock.patch('cinder.volume.drivers.rbd.open', mockopen,
                        create=True) as mock_keyring_file:
            mock_keyring_file.side_effect = IOError
            self.assertIsNone(self.driver._get_keyring_contents())

    @ddt.data({'rbd_chunk_size': 1, 'order': 20},
              {'rbd_chunk_size': 8, 'order': 23},
              {'rbd_chunk_size': 32, 'order': 25})
    @ddt.unpack
    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_clone(self, mock_enable_repl, rbd_chunk_size, order):
        self.cfg.rbd_store_chunk_size = rbd_chunk_size
        src_pool = u'images'
        src_image = u'image-name'
        src_snap = u'snapshot-name'

        client_stack = []

        def mock__enter__(inst):
            def _inner():
                client_stack.append(inst)
                return inst
            return _inner

        client = self.mock_client.return_value
        # capture both rados client used to perform the clone
        client.__enter__.side_effect = mock__enter__(client)

        res = self.driver._clone(self.volume_a, src_pool, src_image, src_snap)

        self.assertEqual({}, res)

        args = [client_stack[0].ioctx, str(src_image), str(src_snap),
                client_stack[1].ioctx, str(self.volume_a.name)]
        kwargs = {'features': client.features,
                  'order': order}
        self.mock_rbd.RBD.return_value.clone.assert_called_once_with(
            *args, **kwargs)
        self.assertEqual(2, client.__enter__.call_count)
        mock_enable_repl.assert_not_called()

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_clone_replicated(self, mock_enable_repl):
        rbd_chunk_size = 1
        order = 20
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            extra_specs={'replication_enabled': '<is> True'})

        expected_update = {
            'replication_status': 'enabled',
            'replication_driver_data': '{"had_journaling": false}'
        }
        mock_enable_repl.return_value = expected_update

        self.cfg.rbd_store_chunk_size = rbd_chunk_size
        src_pool = u'images'
        src_image = u'image-name'
        src_snap = u'snapshot-name'

        client_stack = []

        def mock__enter__(inst):
            def _inner():
                client_stack.append(inst)
                return inst
            return _inner

        client = self.mock_client.return_value
        # capture both rados client used to perform the clone
        client.__enter__.side_effect = mock__enter__(client)

        res = self.driver._clone(self.volume_a, src_pool, src_image, src_snap)

        self.assertEqual(expected_update, res)
        mock_enable_repl.assert_called_once_with(self.volume_a)

        args = [client_stack[0].ioctx, str(src_image), str(src_snap),
                client_stack[1].ioctx, str(self.volume_a.name)]
        kwargs = {'features': client.features,
                  'order': order}
        self.mock_rbd.RBD.return_value.clone.assert_called_once_with(
            *args, **kwargs)
        self.assertEqual(2, client.__enter__.call_count)

    @ddt.data({},
              {'replication_status': 'enabled',
               'replication_driver_data': '{"had_journaling": false}'})
    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_is_cloneable', return_value=True)
    def test_clone_image_replication(self, return_value, mock_cloneable):
        mock_clone = self.mock_object(self.driver, '_clone',
                                      return_value=return_value)
        image_loc = ('rbd://fee/fi/fo/fum', None)
        image_meta = {'disk_format': 'raw', 'id': 'id.foo'}

        res = self.driver.clone_image(self.context,
                                      self.volume_a,
                                      image_loc,
                                      image_meta,
                                      mock.Mock())

        expected = return_value.copy()
        expected['provider_location'] = None
        self.assertEqual((expected, True), res)

        mock_clone.assert_called_once_with(self.volume_a, 'fi', 'fo', 'fum')

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_clone',
                       return_value=mock.sentinel.volume_update)
    @mock.patch.object(driver.RBDDriver, '_resize', mock.Mock())
    def test_create_vol_from_snap_replication(self, mock_clone):
        self.cfg.rbd_flatten_volume_from_snapshot = False
        snapshot = mock.Mock()

        res = self.driver.create_volume_from_snapshot(self.volume_a, snapshot)

        self.assertEqual(mock.sentinel.volume_update, res)
        mock_clone.assert_called_once_with(self.volume_a,
                                           self.cfg.rbd_pool,
                                           snapshot.volume_name,
                                           snapshot.name)

    @common_mocks
    def test_extend_volume(self):
        fake_size = '20'
        size = int(fake_size) * units.Gi
        with mock.patch.object(self.driver, '_resize') as mock_resize:
            self.driver.extend_volume(self.volume_a, fake_size)
            mock_resize.assert_called_once_with(self.volume_a, size=size)

    @ddt.data(False, True)
    @common_mocks
    def test_retype(self, enabled):
        """Test retyping a non replicated volume.

        We will test on a system that doesn't have replication enabled and on
        one that hast it enabled.
        """
        self.driver._is_replication_enabled = enabled
        if enabled:
            expect = {'replication_status': fields.ReplicationStatus.DISABLED}
        else:
            expect = None
        context = {}
        diff = {'encryption': {},
                'extra_specs': {}}
        updates = {'name': 'testvolume',
                   'host': 'currenthost',
                   'id': fake.VOLUME_ID}
        fake_type = fake_volume.fake_volume_type_obj(context)
        volume = fake_volume.fake_volume_obj(context, **updates)
        volume.volume_type = None

        # The hosts have been checked same before rbd.retype
        # is called.
        # RBD doesn't support multiple pools in a driver.
        host = {'host': 'currenthost'}
        self.assertEqual((True, expect),
                         self.driver.retype(context, volume,
                                            fake_type, diff, host))

        # The encryptions have been checked as same before rbd.retype
        # is called.
        diff['encryption'] = {}
        self.assertEqual((True, expect),
                         self.driver.retype(context, volume,
                                            fake_type, diff, host))

        # extra_specs changes are supported.
        diff['extra_specs'] = {'non-empty': 'non-empty'}
        self.assertEqual((True, expect),
                         self.driver.retype(context, volume,
                                            fake_type, diff, host))
        diff['extra_specs'] = {}

        self.assertEqual((True, expect),
                         self.driver.retype(context, volume,
                                            fake_type, diff, host))

    @ddt.data({'old_replicated': False, 'new_replicated': False},
              {'old_replicated': False, 'new_replicated': True},
              {'old_replicated': True, 'new_replicated': False},
              {'old_replicated': True, 'new_replicated': True})
    @ddt.unpack
    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_disable_replication',
                       return_value=mock.sentinel.disable_replication)
    @mock.patch.object(driver.RBDDriver, '_enable_replication',
                       return_value=mock.sentinel.enable_replication)
    def test_retype_replicated(self, mock_disable, mock_enable, old_replicated,
                               new_replicated):
        """Test retyping a non replicated volume.

        We will test on a system that doesn't have replication enabled and on
        one that hast it enabled.
        """
        self.driver._is_replication_enabled = True
        replicated_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            extra_specs={'replication_enabled': '<is> True'})

        self.volume_a.volume_type = replicated_type if old_replicated else None

        if new_replicated:
            new_type = replicated_type
            if old_replicated:
                update = None
            else:
                update = mock.sentinel.enable_replication
        else:
            new_type = fake_volume.fake_volume_type_obj(
                self.context,
                id=fake.VOLUME_TYPE2_ID),
            if old_replicated:
                update = mock.sentinel.disable_replication
            else:
                update = {'replication_status':
                          fields.ReplicationStatus.DISABLED}

        res = self.driver.retype(self.context, self.volume_a, new_type, None,
                                 None)
        self.assertEqual((True, update), res)

    @common_mocks
    def test_update_migrated_volume(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver.rbd.RBD(), 'rename') as mock_rename:
            context = {}
            mock_rename.return_value = 0
            model_update = self.driver.update_migrated_volume(context,
                                                              self.volume_a,
                                                              self.volume_b,
                                                              'available')
            mock_rename.assert_called_with(client.ioctx,
                                           'volume-%s' % self.volume_b.id,
                                           'volume-%s' % self.volume_a.id)
            self.assertEqual({'_name_id': None,
                              'provider_location': None}, model_update)

    def test_rbd_volume_proxy_init(self):
        mock_driver = mock.Mock(name='driver')
        mock_driver._connect_to_rados.return_value = (None, None)
        with driver.RBDVolumeProxy(mock_driver, self.volume_a.name):
            self.assertEqual(1, mock_driver._connect_to_rados.call_count)
            self.assertFalse(mock_driver._disconnect_from_rados.called)

        self.assertEqual(1, mock_driver._disconnect_from_rados.call_count)

        mock_driver.reset_mock()

        snap = u'snapshot-name'
        with driver.RBDVolumeProxy(mock_driver, self.volume_a.name,
                                   snapshot=snap):
            self.assertEqual(1, mock_driver._connect_to_rados.call_count)
            self.assertFalse(mock_driver._disconnect_from_rados.called)

        self.assertEqual(1, mock_driver._disconnect_from_rados.call_count)

    @common_mocks
    def test_connect_to_rados(self):
        # Default
        self.cfg.rados_connect_timeout = -1

        self.mock_rados.Rados.return_value.open_ioctx.return_value = \
            self.mock_rados.Rados.return_value.ioctx

        # default configured pool
        ret = self.driver._connect_to_rados()
        self.assertTrue(self.mock_rados.Rados.return_value.connect.called)
        # Expect no timeout if default is used
        self.mock_rados.Rados.return_value.connect.assert_called_once_with()
        self.assertTrue(self.mock_rados.Rados.return_value.open_ioctx.called)
        self.assertEqual(self.mock_rados.Rados.return_value.ioctx, ret[1])
        self.mock_rados.Rados.return_value.open_ioctx.assert_called_with(
            self.cfg.rbd_pool)
        conf_set = self.mock_rados.Rados.return_value.conf_set
        conf_set.assert_not_called()

        # different pool
        ret = self.driver._connect_to_rados('alt_pool')
        self.assertTrue(self.mock_rados.Rados.return_value.connect.called)
        self.assertTrue(self.mock_rados.Rados.return_value.open_ioctx.called)
        self.assertEqual(self.mock_rados.Rados.return_value.ioctx, ret[1])
        self.mock_rados.Rados.return_value.open_ioctx.assert_called_with(
            'alt_pool')

        # With timeout
        self.cfg.rados_connect_timeout = 1
        self.mock_rados.Rados.return_value.connect.reset_mock()
        self.driver._connect_to_rados()
        conf_set.assert_has_calls((mock.call('rados_osd_op_timeout', '1'),
                                   mock.call('rados_mon_op_timeout', '1'),
                                   mock.call('client_mount_timeout', '1')))
        self.mock_rados.Rados.return_value.connect.assert_called_once_with()

        # error
        self.mock_rados.Rados.return_value.open_ioctx.reset_mock()
        self.mock_rados.Rados.return_value.shutdown.reset_mock()
        self.mock_rados.Rados.return_value.open_ioctx.side_effect = (
            self.mock_rados.Error)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._connect_to_rados)
        self.assertTrue(self.mock_rados.Rados.return_value.open_ioctx.called)
        self.assertEqual(
            3, self.mock_rados.Rados.return_value.shutdown.call_count)

    @common_mocks
    def test_failover_host_no_replication(self):
        self.driver._is_replication_enabled = False
        self.assertRaises(exception.UnableToFailOver,
                          self.driver.failover_host,
                          self.context, [self.volume_a], [])

    @ddt.data(None, 'tertiary-backend')
    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_get_failover_target_config')
    @mock.patch.object(driver.RBDDriver, '_failover_volume', autospec=True)
    def test_failover_host(self, secondary_id, mock_failover_vol,
                           mock_get_cfg):
        mock_failover_vol.side_effect = lambda self, v, r, d, s: v
        self.mock_object(self.driver.configuration, 'safe_get',
                         return_value=[{'backend_id': 'secondary-backend'},
                                       {'backend_id': 'tertiary-backend'}])
        self.driver._do_setup_replication()
        volumes = [self.volume_a, self.volume_b]
        remote = self.driver._replication_targets[1 if secondary_id else 0]
        mock_get_cfg.return_value = (remote['name'], remote)

        res = self.driver.failover_host(self.context, volumes, secondary_id,
                                        [])

        self.assertEqual((remote['name'], volumes, []), res)
        self.assertEqual(remote, self.driver._active_config)
        mock_failover_vol.assert_has_calls(
            [mock.call(mock.ANY, v, remote, False,
                       fields.ReplicationStatus.FAILED_OVER)
             for v in volumes])
        mock_get_cfg.assert_called_once_with(secondary_id)

    @mock.patch.object(driver.RBDDriver, '_failover_volume', autospec=True)
    def test_failover_host_failback(self, mock_failover_vol):
        mock_failover_vol.side_effect = lambda self, v, r, d, s: v
        self.driver._active_backend_id = 'secondary-backend'
        self.mock_object(self.driver.configuration, 'safe_get',
                         return_value=[{'backend_id': 'secondary-backend'},
                                       {'backend_id': 'tertiary-backend'}])
        self.driver._do_setup_replication()

        remote = self.driver._get_target_config('default')
        volumes = [self.volume_a, self.volume_b]
        res = self.driver.failover_host(self.context, volumes, 'default', [])

        self.assertEqual(('default', volumes, []), res)
        self.assertEqual(remote, self.driver._active_config)
        mock_failover_vol.assert_has_calls(
            [mock.call(mock.ANY, v, remote, False,
                       fields.ReplicationStatus.ENABLED)
             for v in volumes])

    @mock.patch.object(driver.RBDDriver, '_failover_volume')
    def test_failover_host_no_more_replica_targets(self, mock_failover_vol):
        mock_failover_vol.side_effect = lambda w, x, y, z: w
        self.driver._active_backend_id = 'secondary-backend'
        self.mock_object(self.driver.configuration, 'safe_get',
                         return_value=[{'backend_id': 'secondary-backend'}])
        self.driver._do_setup_replication()

        volumes = [self.volume_a, self.volume_b]
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver.failover_host,
                          self.context, volumes, None, [])

    def test_failover_volume_non_replicated(self):
        self.volume_a.replication_status = fields.ReplicationStatus.DISABLED
        remote = {'name': 'name', 'user': 'user', 'conf': 'conf',
                  'pool': 'pool'}
        expected = {
            'volume_id': self.volume_a.id,
            'updates': {
                'status': 'error',
                'previous_status': self.volume_a.status,
                'replication_status': fields.ReplicationStatus.NOT_CAPABLE,
            }
        }
        res = self.driver._failover_volume(
            self.volume_a, remote, False, fields.ReplicationStatus.FAILED_OVER)
        self.assertEqual(expected, res)

    @ddt.data(True, False)
    @mock.patch.object(driver.RBDDriver, '_exec_on_volume',
                       side_effect=Exception)
    def test_failover_volume_error(self, is_demoted, mock_exec):
        self.volume_a.replication_driver_data = '{"had_journaling": false}'
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            extra_specs={'replication_enabled': '<is> True'})
        remote = {'name': 'name', 'user': 'user', 'conf': 'conf',
                  'pool': 'pool'}
        repl_status = fields.ReplicationStatus.FAILOVER_ERROR
        expected = {'volume_id': self.volume_a.id,
                    'updates': {'status': 'error',
                                'previous_status': self.volume_a.status,
                                'replication_status': repl_status}}
        res = self.driver._failover_volume(
            self.volume_a, remote, is_demoted,
            fields.ReplicationStatus.FAILED_OVER)
        self.assertEqual(expected, res)
        mock_exec.assert_called_once_with(self.volume_a.name, remote,
                                          'mirror_image_promote',
                                          not is_demoted)

    @mock.patch.object(driver.RBDDriver, '_exec_on_volume')
    def test_failover_volume(self, mock_exec):
        self.volume_a.replication_driver_data = '{"had_journaling": false}'
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            extra_specs={'replication_enabled': '<is> True'})
        remote = {'name': 'name', 'user': 'user', 'conf': 'conf',
                  'pool': 'pool'}
        repl_status = fields.ReplicationStatus.FAILED_OVER
        expected = {'volume_id': self.volume_a.id,
                    'updates': {'replication_status': repl_status}}
        res = self.driver._failover_volume(self.volume_a, remote, True,
                                           repl_status)
        self.assertEqual(expected, res)
        mock_exec.assert_called_once_with(self.volume_a.name, remote,
                                          'mirror_image_promote', False)

    @common_mocks
    def test_manage_existing_snapshot_get_size(self):
        with mock.patch.object(self.driver.rbd.Image(), 'size') as \
                mock_rbd_image_size:
            with mock.patch.object(self.driver.rbd.Image(), 'close') \
                    as mock_rbd_image_close:
                mock_rbd_image_size.return_value = 2 * units.Gi
                existing_ref = {'source-name': self.snapshot_b.name}
                return_size = self.driver.manage_existing_snapshot_get_size(
                    self.snapshot_b,
                    existing_ref)
                self.assertEqual(2, return_size)
                mock_rbd_image_size.assert_called_once_with()
                mock_rbd_image_close.assert_called_once_with()

    @common_mocks
    def test_manage_existing_snapshot_get_non_integer_size(self):
        rbd_snapshot = self.driver.rbd.Image.return_value
        rbd_snapshot.size.return_value = int(1.75 * units.Gi)
        existing_ref = {'source-name': self.snapshot_b.name}
        return_size = self.driver.manage_existing_snapshot_get_size(
            self.snapshot_b, existing_ref)
        self.assertEqual(2, return_size)
        rbd_snapshot.size.assert_called_once_with()
        rbd_snapshot.close.assert_called_once_with()

    @common_mocks
    def test_manage_existing_snapshot_get_invalid_size(self):

        with mock.patch.object(self.driver.rbd.Image(), 'size') as \
                mock_rbd_image_size:
            with mock.patch.object(self.driver.rbd.Image(), 'close') \
                    as mock_rbd_image_close:
                mock_rbd_image_size.return_value = 'abcd'
                existing_ref = {'source-name': self.snapshot_b.name}
                self.assertRaises(
                    exception.VolumeBackendAPIException,
                    self.driver.manage_existing_snapshot_get_size,
                    self.snapshot_b, existing_ref)

                mock_rbd_image_size.assert_called_once_with()
                mock_rbd_image_close.assert_called_once_with()

    @common_mocks
    def test_manage_existing_snapshot_with_invalid_rbd_image(self):
        self.mock_rbd.Image.side_effect = self.mock_rbd.ImageNotFound

        invalid_snapshot = 'snapshot-invalid'
        invalid_ref = {'source-name': invalid_snapshot}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot_get_size,
                          self.snapshot_b, invalid_ref)
        # Make sure the exception was raised
        self.assertEqual([self.mock_rbd.ImageNotFound],
                         RAISED_EXCEPTIONS)

    @common_mocks
    def test_manage_existing_snapshot(self):
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        exist_snapshot = 'snapshot-exist'
        existing_ref = {'source-name': exist_snapshot}
        proxy.rename_snap.return_value = 0
        self.driver.manage_existing_snapshot(self.snapshot_b, existing_ref)
        proxy.rename_snap.assert_called_with(exist_snapshot,
                                             self.snapshot_b.name)

    @common_mocks
    def test_manage_existing_snapshot_with_exist_rbd_image(self):
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.rename_snap.side_effect = MockImageExistsException

        exist_snapshot = 'snapshot-exist'
        existing_ref = {'source-name': exist_snapshot}
        self.assertRaises(self.mock_rbd.ImageExists,
                          self.driver.manage_existing_snapshot,
                          self.snapshot_b, existing_ref)

        # Make sure the exception was raised
        self.assertEqual(RAISED_EXCEPTIONS,
                         [self.mock_rbd.ImageExists])

    @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver.RBDProxy')
    def test__get_usage_info(self, rbdproxy_mock, client_mock, volproxy_mock):

        def FakeVolProxy(size_or_exc):
            return mock.Mock(return_value=mock.Mock(
                size=mock.Mock(side_effect=(size_or_exc,))))

        volumes = ['volume-1', 'non-existent', 'non-cinder-volume']

        client = client_mock.return_value.__enter__.return_value
        rbdproxy_mock.return_value.list.return_value = volumes

        with mock.patch.object(self.driver, 'rbd',
                               ImageNotFound=MockImageNotFoundException):
            volproxy_mock.side_effect = [
                mock.MagicMock(**{'__enter__': FakeVolProxy(s)})
                for s in (1.0 * units.Gi,
                          self.driver.rbd.ImageNotFound,
                          2.0 * units.Gi)
            ]
            total_provision = self.driver._get_usage_info()

        rbdproxy_mock.return_value.list.assert_called_once_with(client.ioctx)

        expected_volproxy_calls = [
            mock.call(self.driver, v, read_only=True)
            for v in volumes]
        self.assertEqual(expected_volproxy_calls, volproxy_mock.mock_calls)

        self.assertEqual(3.00, total_provision)


class ManagedRBDTestCase(test_driver.BaseDriverTestCase):
    driver_name = "cinder.volume.drivers.rbd.RBDDriver"

    def setUp(self):
        super(ManagedRBDTestCase, self).setUp()
        self.volume.driver.set_initialized()
        self.volume.stats = {'allocated_capacity_gb': 0,
                             'pools': {}}
        self.called = []

    def _create_volume_from_image(self, expected_status, raw=False,
                                  clone_error=False):
        """Try to clone a volume from an image, and check status afterwards.

        NOTE: if clone_error is True we force the image type to raw otherwise
              clone_image is not called
        """

        # See tests.image.fake for image types.
        if raw:
            image_id = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        else:
            image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'

        # creating volume testdata
        db_volume = {'display_description': 'Test Desc',
                     'size': 20,
                     'status': 'creating',
                     'availability_zone': 'fake_zone',
                     'attach_status': fields.VolumeAttachStatus.DETACHED,
                     'host': 'dummy'}
        volume = objects.Volume(context=self.context, **db_volume)
        volume.create()

        try:
            if not clone_error:
                self.volume.create_volume(self.context, volume,
                                          request_spec={'image_id': image_id})
            else:
                self.assertRaises(exception.CinderException,
                                  self.volume.create_volume,
                                  self.context,
                                  volume,
                                  request_spec={'image_id': image_id})

            volume = objects.Volume.get_by_id(self.context, volume.id)
            self.assertEqual(expected_status, volume.status)
        finally:
            # cleanup
            volume.destroy()

    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch.object(cinder.image.glance, 'get_default_image_service')
    def test_create_vol_from_image_status_available(self, mock_gdis,
                                                    mock_check_space):
        """Clone raw image then verify volume is in available state."""

        def _mock_clone_image(context, volume, image_location,
                              image_meta, image_service):
            return {'provider_location': None}, True

        with mock.patch.object(self.volume.driver, 'clone_image') as \
                mock_clone_image:
            mock_clone_image.side_effect = _mock_clone_image
            with mock.patch.object(self.volume.driver, 'create_volume') as \
                    mock_create:
                with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                                       '_copy_image_to_volume') as mock_copy:
                    self._create_volume_from_image('available', raw=True)
                    self.assertFalse(mock_copy.called)

                self.assertTrue(mock_clone_image.called)
                self.assertFalse(mock_create.called)
                self.assertTrue(mock_gdis.called)

    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch.object(cinder.image.glance, 'get_default_image_service')
    @mock.patch('cinder.image.image_utils.TemporaryImages.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    def test_create_vol_from_non_raw_image_status_available(
            self, mock_qemu_info, mock_fetch, mock_gdis, mock_check_space):
        """Clone non-raw image then verify volume is in available state."""

        def _mock_clone_image(context, volume, image_location,
                              image_meta, image_service):
            return {'provider_location': None}, False

        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info

        mock_fetch.return_value = mock.MagicMock(spec=utils.get_file_spec())
        with mock.patch.object(self.volume.driver, 'clone_image') as \
                mock_clone_image:
            mock_clone_image.side_effect = _mock_clone_image
            with mock.patch.object(self.volume.driver, 'create_volume') as \
                    mock_create:
                with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                                       '_copy_image_to_volume') as mock_copy:
                    self._create_volume_from_image('available', raw=False)
                    self.assertTrue(mock_copy.called)

                self.assertTrue(mock_clone_image.called)
                self.assertTrue(mock_create.called)
                self.assertTrue(mock_gdis.called)

    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch.object(cinder.image.glance, 'get_default_image_service')
    def test_create_vol_from_image_status_error(self, mock_gdis,
                                                mock_check_space):
        """Fail to clone raw image then verify volume is in error state."""
        with mock.patch.object(self.volume.driver, 'clone_image') as \
                mock_clone_image:
            mock_clone_image.side_effect = exception.CinderException
            with mock.patch.object(self.volume.driver, 'create_volume'):
                with mock.patch.object(create_volume.CreateVolumeFromSpecTask,
                                       '_copy_image_to_volume') as mock_copy:
                    self._create_volume_from_image('error', raw=True,
                                                   clone_error=True)
                    self.assertFalse(mock_copy.called)

                self.assertTrue(mock_clone_image.called)
                self.assertFalse(self.volume.driver.create_volume.called)
                self.assertTrue(mock_gdis.called)

    def test_clone_failure(self):
        driver = self.volume.driver

        with mock.patch.object(driver, '_is_cloneable', lambda *args: False):
            image_loc = (mock.Mock(), None)
            actual = driver.clone_image(mock.Mock(),
                                        mock.Mock(),
                                        image_loc,
                                        {},
                                        mock.Mock())
            self.assertEqual(({}, False), actual)

        self.assertEqual(({}, False),
                         driver.clone_image('', object(), None, {}, ''))

    def test_clone_success(self):
        expected = ({'provider_location': None}, True)
        driver = self.volume.driver

        with mock.patch.object(self.volume.driver, '_is_cloneable') as \
                mock_is_cloneable:
            mock_is_cloneable.return_value = True
            with mock.patch.object(self.volume.driver, '_clone') as \
                    mock_clone:
                with mock.patch.object(self.volume.driver, '_resize') as \
                        mock_resize:
                    mock_clone.return_value = {}
                    image_loc = ('rbd://fee/fi/fo/fum', None)

                    volume = {'name': 'vol1'}
                    actual = driver.clone_image(mock.Mock(),
                                                volume,
                                                image_loc,
                                                {'disk_format': 'raw',
                                                 'id': 'id.foo'},
                                                mock.Mock())

                    self.assertEqual(expected, actual)
                    mock_clone.assert_called_once_with(volume,
                                                       'fi', 'fo', 'fum')
                    mock_resize.assert_called_once_with(volume)

    def test_clone_multilocation_success(self):
        expected = ({'provider_location': None}, True)
        driver = self.volume.driver

        def cloneable_side_effect(url_location, image_meta):
            return url_location == 'rbd://fee/fi/fo/fum'

        with mock.patch.object(self.volume.driver, '_is_cloneable') \
            as mock_is_cloneable, \
            mock.patch.object(self.volume.driver, '_clone') as mock_clone, \
            mock.patch.object(self.volume.driver, '_resize') \
                as mock_resize:
            mock_is_cloneable.side_effect = cloneable_side_effect
            mock_clone.return_value = {}
            image_loc = ('rbd://bee/bi/bo/bum',
                         [{'url': 'rbd://bee/bi/bo/bum'},
                          {'url': 'rbd://fee/fi/fo/fum'}])
            volume = {'name': 'vol1'}
            image_meta = mock.sentinel.image_meta
            image_service = mock.sentinel.image_service

            actual = driver.clone_image(self.context,
                                        volume,
                                        image_loc,
                                        image_meta,
                                        image_service)

            self.assertEqual(expected, actual)
            self.assertEqual(2, mock_is_cloneable.call_count)
            mock_clone.assert_called_once_with(volume,
                                               'fi', 'fo', 'fum')
            mock_is_cloneable.assert_called_with('rbd://fee/fi/fo/fum',
                                                 image_meta)
            mock_resize.assert_called_once_with(volume)

    def test_clone_multilocation_failure(self):
        expected = ({}, False)
        driver = self.volume.driver

        with mock.patch.object(driver, '_is_cloneable', return_value=False) \
            as mock_is_cloneable, \
            mock.patch.object(self.volume.driver, '_clone') as mock_clone, \
            mock.patch.object(self.volume.driver, '_resize') \
                as mock_resize:
            image_loc = ('rbd://bee/bi/bo/bum',
                         [{'url': 'rbd://bee/bi/bo/bum'},
                          {'url': 'rbd://fee/fi/fo/fum'}])

            volume = {'name': 'vol1'}
            image_meta = mock.sentinel.image_meta
            image_service = mock.sentinel.image_service
            actual = driver.clone_image(self.context,
                                        volume,
                                        image_loc,
                                        image_meta,
                                        image_service)

            self.assertEqual(expected, actual)
            self.assertEqual(2, mock_is_cloneable.call_count)
            mock_is_cloneable.assert_any_call('rbd://bee/bi/bo/bum',
                                              image_meta)
            mock_is_cloneable.assert_any_call('rbd://fee/fi/fo/fum',
                                              image_meta)
            self.assertFalse(mock_clone.called)
            self.assertFalse(mock_resize.called)
