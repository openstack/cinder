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

import errno
import math
import os
import tempfile
import time
import types
from unittest import mock
from unittest.mock import call
import uuid

import castellan
import ddt
from oslo_utils import imageutils
from oslo_utils import units

from cinder import context
from cinder import db
from cinder import exception
import cinder.image.glance
from cinder.image import image_utils
from cinder import objects
from cinder.objects import fields
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.keymgr import fake as fake_keymgr
from cinder.tests.unit import test
from cinder.tests.unit import utils
from cinder.tests.unit.volume import test_driver
from cinder.volume import configuration as conf
import cinder.volume.drivers.rbd as driver
from cinder.volume import qos_specs
from cinder.volume import volume_utils

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


class MockOSErrorException(MockException):
    """Used as mock for rbd.OSError."""


class MockPermissionError(MockException):
    """Used as mock for PermissionError."""
    errno = errno.EPERM


class MockImageHasSnapshotsException(MockException):
    """Used as mock for rbd.ImageHasSnapshots."""


class MockInvalidArgument(MockException):
    """Used as mock for rbd.InvalidArgument."""


class KeyObject(object):
    def get_encoded(arg):
        return "asdf".encode('utf-8')


def common_mocks(f):
    """Decorator to set mocks common to all tests.

    The point of doing these mocks here is so that we don't accidentally set
    mocks that can't/don't get unset.
    """
    def _common_inner_inner1(inst, *args, **kwargs):
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
            inst.mock_rbd.ImageHasSnapshots = MockImageHasSnapshotsException
            inst.mock_rbd.InvalidArgument = MockInvalidArgument
            inst.mock_rbd.PermissionError = MockPermissionError

            inst.driver.rbd = inst.mock_rbd
            aux = inst.driver.rbd
            aux.Image.return_value.stripe_unit.return_value = 4194304

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


class MockDriverConfig(object):
    def __init__(self, **kwargs):
        my_dict = vars(self)
        my_dict.update(kwargs)
        my_dict.setdefault('max_over_subscription_ratio', 1.0)
        my_dict.setdefault('reserved_percentage', 0)
        my_dict.setdefault('volume_backend_name', 'RBD')
        my_dict.setdefault('_default', None)

    def __call__(self, value):
        return getattr(self, value, self._default)


@ddt.ddt
class RBDTestCase(test.TestCase):

    @classmethod
    def _make_configuration(cls, conf_in=None):
        cfg = mock.Mock(spec=conf.Configuration)
        cfg.image_conversion_dir = None
        cfg.rbd_cluster_name = 'nondefault'
        cfg.rbd_pool = 'rbd'
        cfg.rbd_ceph_conf = '/etc/ceph/my_ceph.conf'
        cfg.rbd_secret_uuid = '5fe62cc7-0392-4a32-8466-081ce0ea970f'
        cfg.rbd_user = 'cinder'
        cfg.volume_backend_name = None
        cfg.volume_dd_blocksize = '1M'
        cfg.rbd_store_chunk_size = 4
        cfg.rados_connection_retries = 3
        cfg.rados_connection_interval = 5
        cfg.backup_use_temp_snapshot = False
        cfg.enable_deferred_deletion = False
        cfg.rbd_concurrent_flatten_operations = 3

        # Because the mocked conf doesn't actually have an underlying oslo conf
        # it doesn't have the set_default method, so we use a fake one.
        cfg.set_default = types.MethodType(cls._set_default, cfg)

        if conf_in is not None:
            for k in conf_in:
                setattr(cfg, k, conf_in[k])

        return cfg

    @staticmethod
    def _set_default(cfg, name, value, group=None):
        # Ignore the group for now
        if not getattr(cfg, name):
            setattr(cfg, name, value)

    @staticmethod
    def _make_drv(conf_in):
        cfg = RBDTestCase._make_configuration(conf_in)

        mock_exec = mock.Mock(return_value=('', ''))

        drv = driver.RBDDriver(execute=mock_exec,
                               configuration=cfg,
                               rbd=mock.MagicMock())
        drv.set_initialized()
        return drv

    def setUp(self):
        global RAISED_EXCEPTIONS
        RAISED_EXCEPTIONS = []
        super(RBDTestCase, self).setUp()

        self.cfg = self._make_configuration()

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
               'use_quota': True,
               'size': 10})

        self.temp_volume = fake_volume.fake_volume_obj(
            self.context,
            **{'name': u'volume-0000000t',
               'id': '4c39c3c7-168f-4b32-b585-77f1b3bf0a44',
               'use_quota': False,
               'size': 10})

        self.volume_b = fake_volume.fake_volume_obj(
            self.context,
            **{'name': u'volume-0000000b',
               'id': '0c7d1f44-5a06-403f-bb82-ae7ad0d693a6',
               'use_quota': True,
               'size': 10})

        self.volume_c = fake_volume.fake_volume_obj(
            self.context,
            **{'name': u'volume-0000000a',
               'id': '55555555-222f-4b32-b585-9991b3bf0a99',
               'size': 12,
               'use_quota': True,
               'encryption_key_id': fake.ENCRYPTION_KEY_ID})

        self.snapshot = fake_snapshot.fake_snapshot_obj(
            self.context, name='snapshot-0000000a', use_quota=True)

        self.snapshot_b = fake_snapshot.fake_snapshot_obj(
            self.context,
            **{'name': u'snapshot-0000000n',
               'expected_attrs': ['volume'],
               'use_quota': True,
               'volume': {'id': fake.VOLUME_ID,
                          'name': 'cinder-volume',
                          'size': 128,
                          'host': 'host@fakebackend#fakepool'}
               })

        self.qos_policy_a = {"total_iops_sec": "100",
                             "total_bytes_sec": "1024"}
        self.qos_policy_b = {"read_iops_sec": "500",
                             "write_iops_sec": "200"}

    @ddt.data({'cluster_name': None, 'pool_name': 'rbd'},
              {'cluster_name': 'volumes', 'pool_name': None})
    @ddt.unpack
    def test_min_config(self, cluster_name, pool_name):
        self.cfg.rbd_cluster_name = cluster_name
        self.cfg.rbd_pool = pool_name

        with mock.patch('cinder.volume.drivers.rbd.rados'):
            self.assertRaises(exception.InvalidConfigurationValue,
                              self.driver.check_for_setup_error)

    @mock.patch.object(driver, 'rados', mock.Mock())
    @mock.patch.object(driver, 'RADOSClient')
    def test_check_for_setup_error_missing_keyring_data(self, mock_client):
        self.driver.keyring_file = '/etc/ceph/ceph.client.admin.keyring'
        self.driver.keyring_data = None

        self.assertRaises(exception.InvalidConfigurationValue,
                          self.driver.check_for_setup_error)
        mock_client.assert_called_once_with(self.driver)

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
                     'user': 'cinder',
                     'secret_uuid': self.cfg.rbd_secret_uuid}]
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
                     'user': 'bar',
                     'secret_uuid': self.cfg.rbd_secret_uuid},
                    {'name': 'tertiary-backend',
                     'conf': '/etc/ceph/tertiary-backend.conf',
                     'user': 'cinder',
                     'secret_uuid': self.cfg.rbd_secret_uuid}]
        self.driver._parse_replication_configs(cfg[:num_targets])
        self.assertEqual(expected[:num_targets],
                         self.driver._replication_targets)

    def test_do_setup_replication_disabled(self):
        with mock.patch.object(self.driver.configuration, 'safe_get',
                               return_value=None), \
                mock.patch.object(self.driver,
                                  '_set_default_secret_uuid') as mock_secret:
            self.driver.do_setup(self.context)
            mock_secret.assert_called_once_with()
            self.assertFalse(self.driver._is_replication_enabled)
            self.assertEqual([], self.driver._replication_targets)
            self.assertEqual([], self.driver._target_names)
            self.assertEqual({'name': self.cfg.rbd_cluster_name,
                              'conf': self.cfg.rbd_ceph_conf,
                              'user': self.cfg.rbd_user,
                              'secret_uuid': self.cfg.rbd_secret_uuid},
                             self.driver._active_config)

    @ddt.data('', None)
    @mock.patch.object(driver.RBDDriver, '_get_fsid')
    def test__set_default_secret_uuid_missing(self, secret_uuid, mock_fsid):
        # Clear the current values
        self.cfg.rbd_secret_uuid = secret_uuid
        self.driver._active_config['secret_uuid'] = secret_uuid
        # Fake fsid value returned by the cluster
        fsid = str(uuid.uuid4())
        mock_fsid.return_value = fsid

        self.driver._set_default_secret_uuid()

        mock_fsid.assert_called_once_with()
        self.assertEqual(fsid, self.driver._active_config['secret_uuid'])
        self.assertEqual(fsid, self.cfg.rbd_secret_uuid)

    @mock.patch.object(driver.RBDDriver, '_get_fsid')
    def test__set_default_secret_uuid_present(self, mock_fsid):
        # Set secret_uuid like _get_target_config does on do_setup
        secret_uuid = self.cfg.rbd_secret_uuid
        self.driver._active_config['secret_uuid'] = secret_uuid
        # Fake fsid value returned by the cluster (should not be callled)
        mock_fsid.return_value = str(uuid.uuid4())
        self.driver._set_default_secret_uuid()
        mock_fsid.assert_not_called()
        # Values must not have changed
        self.assertEqual(secret_uuid,
                         self.driver._active_config['secret_uuid'])
        self.assertEqual(secret_uuid, self.cfg.rbd_secret_uuid)

    def test_do_setup_replication(self):
        cfg = [{'backend_id': 'secondary-backend',
                'conf': 'foo',
                'user': 'bar',
                'secret_uuid': 'secondary_secret_uuid'}]
        expected = [{'name': 'secondary-backend',
                     'conf': 'foo',
                     'user': 'bar',
                     'secret_uuid': 'secondary_secret_uuid'}]

        with mock.patch.object(self.driver.configuration, 'safe_get',
                               return_value=cfg):
            self.driver.do_setup(self.context)
            self.assertTrue(self.driver._is_replication_enabled)
            self.assertEqual(expected, self.driver._replication_targets)
            self.assertEqual({'name': self.cfg.rbd_cluster_name,
                              'conf': self.cfg.rbd_ceph_conf,
                              'user': self.cfg.rbd_user,
                              'secret_uuid': self.cfg.rbd_secret_uuid},
                             self.driver._active_config)

    def test_do_setup_replication_failed_over(self):
        cfg = [{'backend_id': 'secondary-backend',
                'conf': 'foo',
                'user': 'bar',
                'secret_uuid': 'secondary_secret_uuid'}]
        expected = [{'name': 'secondary-backend',
                     'conf': 'foo',
                     'user': 'bar',
                     'secret_uuid': 'secondary_secret_uuid'}]
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
                       return_value={'replication': 'enabled'})
    def test_setup_volume_with_replication(self, mock_enable):
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            self.context,
            id=fake.VOLUME_TYPE_ID,
            extra_specs={'replication_enabled': '<is> True'})
        res = self.driver._setup_volume(self.volume_a)
        self.assertEqual('enabled', res['replication'])
        mock_enable.assert_called_once_with(self.volume_a)

    @ddt.data(False, True)
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_setup_volume_without_replication(self, enabled, mock_enable):
        self.driver._is_replication_enabled = enabled
        res = self.driver._setup_volume(self.volume_a)
        if enabled:
            expect = {'replication_status': fields.ReplicationStatus.DISABLED}
        else:
            expect = {}
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
        image = self.mock_proxy.return_value.__enter__.return_value

        image_features = 0
        if exclusive_lock_enabled:
            image_features |= self.driver.RBD_FEATURE_EXCLUSIVE_LOCK
        if journaling_enabled:
            image_features |= self.driver.RBD_FEATURE_JOURNALING

        image.features.return_value = image_features

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
            image.update_features.assert_called_once_with(
                self.driver.RBD_FEATURE_JOURNALING, True)
        else:
            calls = [call(self.driver.RBD_FEATURE_EXCLUSIVE_LOCK, True),
                     call(self.driver.RBD_FEATURE_JOURNALING, True)]
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
                self.driver.RBD_FEATURE_JOURNALING, False)
        else:
            calls = [call(self.driver.RBD_FEATURE_JOURNALING, False),
                     call(self.driver.RBD_FEATURE_EXCLUSIVE_LOCK,
                          False)]
            image.update_features.assert_has_calls(calls, any_order=False)

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_qos_specs_from_volume_type')
    @mock.patch.object(driver.RBDDriver, '_supports_qos')
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_create_volume(self, mock_enable_repl, mock_qos_vers,
                           mock_get_qos_specs):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        mock_qos_vers.return_value = True
        mock_get_qos_specs.return_value = None

        res = self.driver.create_volume(self.volume_a)

        self.assertEqual({}, res)
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
        mock_qos_vers.assert_not_called()

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
    @mock.patch.object(driver.RBDDriver, '_supports_qos')
    @mock.patch.object(driver.RBDDriver, 'update_rbd_image_qos')
    def test_create_volume_with_qos(self, mock_update_qos, mock_qos_supported):

        ctxt = context.get_admin_context()
        qos = qos_specs.create(ctxt, "qos-iops-bws", self.qos_policy_a)
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            ctxt,
            id=fake.VOLUME_TYPE_ID,
            qos_specs_id = qos.id)

        client = self.mock_client.return_value
        client.__enter__.return_value = client

        mock_qos_supported.return_value = True
        res = self.driver.create_volume(self.volume_a)
        self.assertEqual({}, res)

        chunk_size = self.cfg.rbd_store_chunk_size * units.Mi
        order = int(math.log(chunk_size, 2))
        args = [client.ioctx, str(self.volume_a.name),
                self.volume_a.size * units.Gi, order]
        kwargs = {'old_format': False,
                  'features': client.features}
        self.mock_rbd.RBD.return_value.create.assert_called_once_with(
            *args, **kwargs)

        mock_update_qos.assert_called_once_with(self.volume_a, qos.specs)

        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)

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
        self.assertEqual([self.mock_rbd.ImageExists], RAISED_EXCEPTIONS)

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
    @mock.patch.object(driver.RBDDriver, '_get_image_status')
    def test_get_manageable_volumes(self, mock_get_image_status):
        cinder_vols = [{'id': '00000000-0000-0000-0000-000000000000'}]
        vols = ['volume-00000000-0000-0000-0000-000000000000', 'vol1', 'vol2',
                'volume-11111111-1111-1111-1111-111111111111.deleted']
        self.mock_rbd.RBD.return_value.list.return_value = vols
        image = self.mock_proxy.return_value.__enter__.return_value
        image.size.side_effect = [2 * units.Gi, 4 * units.Gi, 6 * units.Gi,
                                  8 * units.Gi]
        mock_get_image_status.side_effect = [
            {'watchers': []},
            {'watchers': [{"address": "192.168.120.61:0/3012034728",
                           "client": 44431941, "cookie": 94077162321152}]},
            {'watchers': []}]
        res = self.driver.get_manageable_volumes(
            cinder_vols, None, 1000, 0, ['size'], ['asc'])
        exp = [{'size': 2, 'reason_not_safe': 'already managed',
                'extra_info': None, 'safe_to_manage': False,
                'reference': {'source-name':
                              'volume-00000000-0000-0000-0000-000000000000'},
                'cinder_id': '00000000-0000-0000-0000-000000000000'},
               {'size': 4, 'reason_not_safe': None,
                'safe_to_manage': True, 'reference': {'source-name': 'vol1'},
                'cinder_id': None, 'extra_info': None},
               {'size': 6, 'reason_not_safe': 'volume in use',
                'safe_to_manage': False, 'reference': {'source-name': 'vol2'},
                'cinder_id': None, 'extra_info': None},
               {'size': 8, 'reason_not_safe': 'volume marked as deleted',
                'safe_to_manage': False, 'cinder_id': None, 'extra_info': None,
                'reference': {
                    'source-name':
                        'volume-11111111-1111-1111-1111-111111111111.deleted'}}
               ]
        self.assertEqual(exp, res)

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
                    self.mock_proxy.return_value.__enter__.return_value,
                    self.volume_a.name,
                    None)
                self.mock_proxy.return_value.__enter__.return_value.\
                    list_snaps.assert_called_once_with()
                client.__enter__.assert_called_once_with()
                client.__exit__.assert_called_once_with(None, None, None)
                mock_delete_backup_snaps.assert_called_once_with(
                    self.mock_proxy.return_value.__enter__.return_value)
                self.assertFalse(
                    self.driver.rbd.Image.return_value.unprotect_snap.called)
                self.assertEqual(
                    1, self.driver.rbd.RBD.return_value.remove.call_count)

    @common_mocks
    def test_delete_volume_clone_info_return_parent(self):
        client = self.mock_client.return_value
        self.driver.rbd.Image.return_value.list_snaps.return_value = []
        pool = 'volumes'
        parent = True
        parent_snap = self.snapshot_b

        mock_get_clone_info = self.mock_object(self.driver, '_get_clone_info',
                                               return_value=(pool,
                                                             parent,
                                                             parent_snap))

        m_del_clone_parent_refs = self.mock_object(self.driver,
                                                   '_delete_clone_parent_refs')
        m_del_back_snaps = self.mock_object(self.driver,
                                            '_delete_backup_snaps')

        self.driver.delete_volume(self.volume_a)

        mock_get_clone_info.assert_called_once_with(
            self.mock_proxy.return_value.__enter__.return_value,
            self.volume_a.name,
            None)
        m_del_clone_parent_refs.assert_not_called()
        self.mock_proxy.return_value.__enter__.return_value.list_snaps.\
            assert_called_once_with()
        client.__enter__.assert_called_once_with()
        client.__exit__.assert_called_once_with(None, None, None)
        m_del_back_snaps.assert_called_once_with(
            self.mock_proxy.return_value.__enter__.return_value)
        self.assertFalse(
            self.driver.rbd.Image.return_value.unprotect_snap.called)
        self.assertEqual(
            1, self.driver.rbd.RBD.return_value.remove.call_count)
        self.driver.rbd.RBD.return_value.trash_move.assert_not_called()

    @common_mocks
    def test_deferred_deletion(self):
        drv = self._make_drv({'enable_deferred_deletion': True,
                              'deferred_deletion_delay': 0})

        client = self.mock_client.return_value

        with mock.patch.object(drv, '_get_clone_info') as \
                mock_get_clone_info:
            with mock.patch.object(drv, '_delete_backup_snaps') as \
                    mock_delete_backup_snaps:
                mock_get_clone_info.return_value = (None, None, None)

                drv.delete_volume(self.volume_a)

                mock_get_clone_info.assert_called_once_with(
                    self.mock_proxy.return_value.__enter__.return_value,
                    self.volume_a.name,
                    None)
                client.__enter__.assert_called_once_with()
                client.__exit__.assert_called_once_with(None, None, None)
                mock_delete_backup_snaps.assert_called_once_with(
                    self.mock_proxy.return_value.__enter__.return_value)
                self.assertFalse(
                    drv.rbd.Image.return_value.unprotect_snap.called)
                self.assertEqual(
                    0, drv.rbd.RBD.return_value.trash_move.call_count)
                self.driver.rbd.RBD.return_value.remove.assert_not_called()

    @common_mocks
    def test_deferred_deletion_periodic_task(self):
        drv = self._make_drv({'rados_connect_timeout': -1,
                              'enable_deferred_deletion': True,
                              'deferred_deletion_purge_interval': 1})
        drv._start_periodic_tasks()

        time.sleep(1.2)
        self.assertTrue(drv.rbd.RBD.return_value.trash_list.called)
        self.assertFalse(drv.rbd.RBD.return_value.trash_remove.called)

    @common_mocks
    def test_deferred_deletion_trash_purge(self):
        drv = self._make_drv({'enable_deferred_deletion': True})
        with mock.patch.object(drv.rbd.RBD(), 'trash_list') as mock_trash_list:
            mock_trash_list.return_value = [self.volume_a]
            drv._trash_purge()

            self.assertEqual(
                1, drv.rbd.RBD.return_value.trash_list.call_count)
            self.assertEqual(
                1, drv.rbd.RBD.return_value.trash_remove.call_count)

    @common_mocks
    def test_deferred_deletion_trash_purge_not_expired(self):
        drv = self._make_drv({'enable_deferred_deletion': True})
        with mock.patch.object(drv.rbd.RBD(), 'trash_list') as mock_trash_list:
            mock_trash_list.return_value = [self.volume_a]
            drv.rbd.RBD.return_value.trash_remove.side_effect = (
                self.mock_rbd.PermissionError)

            drv._trash_purge()

            self.assertEqual(
                1, drv.rbd.RBD.return_value.trash_list.call_count)
            self.assertEqual(
                1, drv.rbd.RBD.return_value.trash_remove.call_count)
            # Make sure the exception was raised
            self.assertEqual(1, len(RAISED_EXCEPTIONS))
            self.assertIn(self.mock_rbd.PermissionError, RAISED_EXCEPTIONS)

    @common_mocks
    def test_deferred_deletion_w_parent(self):
        drv = self._make_drv({'enable_deferred_deletion': True,
                              'deferred_deletion_delay': 0})
        _get_clone_info_return_values = [
            (None, self.volume_b.name, None),
            (None, None, None)]
        with mock.patch.object(drv, '_get_clone_info',
                               side_effect = _get_clone_info_return_values):
            drv.delete_volume(self.volume_a)

            self.assertEqual(
                0, drv.rbd.RBD.return_value.trash_move.call_count)

    @common_mocks
    def test_deferred_deletion_w_deleted_parent(self):
        drv = self._make_drv({'enable_deferred_deletion': True,
                              'deferred_deletion_delay': 0})
        _get_clone_info_return_values = [
            (None, "%s.deleted" % self.volume_b.name, None),
            (None, None, None)]
        with mock.patch.object(drv, '_get_clone_info',
                               side_effect = _get_clone_info_return_values):
            drv.delete_volume(self.volume_a)

            self.assertEqual(
                0, drv.rbd.RBD.return_value.trash_move.call_count)

    @common_mocks
    def test_delete_volume_not_found_at_open(self):
        self.mock_rbd.Image.side_effect = self.mock_rbd.ImageNotFound
        self.mock_proxy.side_effect = self.mock_rbd.ImageNotFound
        self.assertIsNone(self.driver.delete_volume(self.volume_a))
        with mock.patch.object(driver, 'RADOSClient') as client:
            client = self.mock_client.return_value.__enter__.return_value
            self.mock_proxy.assert_called_once_with(self.driver,
                                                    self.volume_a.name,
                                                    ioctx=client.ioctx)
        # Make sure the exception was raised
        self.assertEqual([self.mock_rbd.ImageNotFound], RAISED_EXCEPTIONS)

    @common_mocks
    def test_delete_busy_volume(self):
        self.mock_rbd.Image.return_value.list_snaps.return_value = []

        self.mock_rbd.RBD.return_value.remove.side_effect = (
            self.mock_rbd.ImageBusy,
            None)

        mock_delete_backup_snaps = self.mock_object(self.driver,
                                                    '_delete_backup_snaps')
        mock_rados_client = self.mock_object(driver, 'RADOSClient')
        mock_flatten = self.mock_object(self.driver, '_flatten')

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            mock_get_clone_info.return_value = (None, None, None)
            self.driver.rbd.Image.return_value.list_children.\
                return_value = [('pool1', 'child1'),
                                ('pool1', 'child2')]
            self.mock_proxy.return_value.__enter__.return_value.list_children.\
                return_value = [('pool1', 'child1'), ('pool1', 'child2')]
            self.driver.delete_volume(self.volume_a)

            mock_flatten.assert_has_calls(
                [mock.call('pool1', 'child1'),
                 mock.call('pool1', 'child2')])

            mock_get_clone_info.assert_called_once_with(
                self.mock_proxy.return_value.__enter__.return_value,
                self.volume_a.name,
                None)
            self.mock_proxy.return_value.__enter__.return_value.list_snaps.\
                assert_called_once_with()
            mock_rados_client.assert_called_once_with(self.driver)
            mock_delete_backup_snaps.assert_called_once_with(
                self.mock_proxy.return_value.__enter__.return_value)
            self.assertFalse(
                self.mock_rbd.Image.return_value.unprotect_snap.
                called)
            self.assertEqual(
                2,
                self.mock_rbd.RBD.return_value.remove.call_count)
            self.assertEqual(1, len(RAISED_EXCEPTIONS))
            # Make sure the exception was raised
            self.assertIn(self.mock_rbd.ImageBusy,
                          RAISED_EXCEPTIONS)

            self.mock_rbd.RBD.return_value.trash_move.assert_not_called()

    @common_mocks
    def test_delete_volume_has_snapshots(self):
        self.mock_rbd.Image.return_value.list_snaps.return_value = []

        self.mock_rbd.RBD.return_value.remove.side_effect = (
            self.mock_rbd.ImageHasSnapshots,  # initial vol remove attempt
            None                              # removal of child image
        )
        mock_get_clone_info = self.mock_object(self.driver,
                                               '_get_clone_info',
                                               return_value=(None,
                                                             None,
                                                             None))
        m_del_backup_snaps = self.mock_object(self.driver,
                                              '_delete_backup_snaps')

        mock_try_remove_volume = self.mock_object(self.driver,
                                                  '_try_remove_volume',
                                                  return_value=True)

        mock_rados_client = self.mock_object(driver, 'RADOSClient')

        self.driver.delete_volume(self.volume_a)

        mock_get_clone_info.assert_called_once_with(
            self.mock_proxy.return_value.__enter__.return_value,
            self.volume_a.name,
            None)
        mock_rados_client.assert_called_once_with(self.driver)
        m_del_backup_snaps.assert_called_once_with(
            self.mock_proxy.return_value.__enter__.return_value)
        self.assertFalse(
            self.mock_rbd.Image.return_value.unprotect_snap.called)
        self.assertEqual(
            1, self.mock_rbd.RBD.return_value.remove.call_count)
        self.assertEqual(1, len(RAISED_EXCEPTIONS))
        # Make sure the exception was raised
        self.assertIn(self.mock_rbd.ImageHasSnapshots,
                      RAISED_EXCEPTIONS)

        self.mock_rbd.RBD.return_value.trash_move.assert_not_called()

        mock_try_remove_volume.assert_called_once_with(mock.ANY,
                                                       self.volume_a.name)

    @common_mocks
    def test_delete_volume_has_snapshots_trash(self):
        self.mock_rbd.Image.return_value.list_snaps.return_value = []

        self.mock_rbd.RBD.return_value.remove.side_effect = (
            self.mock_rbd.ImageHasSnapshots,  # initial vol remove attempt
            None                              # removal of child image
        )
        mock_get_clone_info = self.mock_object(self.driver,
                                               '_get_clone_info',
                                               return_value=(None,
                                                             None,
                                                             None))
        m_del_backup_snaps = self.mock_object(self.driver,
                                              '_delete_backup_snaps')

        mock_try_remove_volume = self.mock_object(self.driver,
                                                  '_try_remove_volume',
                                                  return_value=False)

        mock_trash_volume = self.mock_object(self.driver,
                                             '_move_volume_to_trash')

        with mock.patch.object(driver, 'RADOSClient') as mock_rados_client:
            self.driver.delete_volume(self.volume_a)

            mock_get_clone_info.assert_called_once_with(
                self.mock_proxy.return_value.__enter__.return_value,
                self.volume_a.name,
                None)
            self.mock_proxy.return_value.__enter__.return_value.list_snaps.\
                assert_called_once_with()
            mock_rados_client.assert_called_once_with(self.driver)
            m_del_backup_snaps.assert_called_once_with(
                self.mock_proxy.return_value.__enter__.return_value)
            self.assertFalse(
                self.mock_rbd.Image.return_value.unprotect_snap.called)
            self.assertEqual(
                1, self.mock_rbd.RBD.return_value.remove.call_count)
            self.assertEqual(1, len(RAISED_EXCEPTIONS))
            # Make sure the exception was raised
            self.assertIn(self.mock_rbd.ImageHasSnapshots,
                          RAISED_EXCEPTIONS)

            self.mock_rbd.RBD.return_value.trash_move.\
                assert_not_called()

            mock_trash_volume.assert_called_once_with(mock.ANY,
                                                      self.volume_a.name,
                                                      0)

            mock_try_remove_volume.assert_called_once_with(mock.ANY,
                                                           self.volume_a.name)

    @common_mocks
    def test_delete_volume_not_found(self):
        self.mock_rbd.Image.return_value.list_snaps.return_value = []

        self.mock_rbd.RBD.return_value.remove.side_effect = (
            self.mock_rbd.ImageNotFound)

        mock_delete_backup_snaps = self.mock_object(self.driver,
                                                    '_delete_backup_snaps')
        mock_rados_client = self.mock_object(driver, 'RADOSClient')

        mock_get_clone_info = self.mock_object(self.driver, '_get_clone_info')
        mock_get_clone_info.return_value = (None, None, None)

        mock_find_clone_snap = self.mock_object(self.driver,
                                                '_find_clone_snap',
                                                return_value=None)

        self.assertIsNone(self.driver.delete_volume(self.volume_a))
        image = self.mock_proxy.return_value.__enter__.return_value
        mock_get_clone_info.assert_called_once_with(
            image,
            self.volume_a.name,
            None)
        mock_find_clone_snap.assert_called_once_with(image)
        mock_rados_client.assert_called_once_with(self.driver)
        mock_delete_backup_snaps.assert_called_once_with(image)

        self.assertFalse(
            self.mock_rbd.Image.return_value.unprotect_snap.called)
        self.assertEqual(
            1, self.mock_rbd.RBD.return_value.remove.call_count)
        # Make sure the exception was raised
        self.assertEqual([self.mock_rbd.ImageNotFound],
                         RAISED_EXCEPTIONS)

    @common_mocks
    def test_delete_volume_w_clone_snaps(self):
        client = self.mock_client.return_value
        snapshots = [
            {'id': 1, 'name': 'snapshot-00000000-0000-0000-0000-000000000000',
                'size': 2147483648},
            {'id': 2, 'name': 'snap1', 'size': 6442450944},
            {'id': 3, 'size': 8589934592,
                'name':
                'volume-22222222-2222-2222-2222-222222222222.clone_snap'},
            {'id': 4, 'size': 5368709120,
                'name':
                'backup.33333333-3333-3333-3333-333333333333.snap.123'}]

        self.mock_rbd.Image.return_value.list_snaps.return_value = snapshots
        mock_get_clone_info = self.mock_object(self.driver,
                                               '_get_clone_info',
                                               return_value=(None,
                                                             None,
                                                             None))

        self.mock_object(self.driver, '_find_clone_snap',
                         return_value=snapshots[2]['name'])
        with mock.patch.object(self.driver, '_delete_backup_snaps') as \
                mock_delete_backup_snaps:

            self.driver.delete_volume(self.volume_a)

            mock_get_clone_info.assert_called_once_with(
                self.mock_proxy.return_value.__enter__.return_value,
                self.volume_a.name,
                snapshots[2]['name'])
            client.__enter__.assert_called_once_with()
            client.__exit__.assert_called_once_with(None, None, None)
            mock_delete_backup_snaps.assert_called_once_with(
                self.mock_proxy.return_value.__enter__.return_value)
            self.assertFalse(
                self.driver.rbd.Image.return_value.unprotect_snap.called)
            self.assertEqual(
                1, self.driver.rbd.RBD.return_value.rename.call_count)

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
    @mock.patch.object(driver.RBDDriver, '_resize', mock.Mock())
    def test_log_create_vol_from_snap_w_v2_clone_api(self, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a

        self.mock_proxy().__enter__().volume.op_features.return_value = 1
        self.mock_rbd.RBD_OPERATION_FEATURE_CLONE_PARENT = 1

        self.cfg.rbd_flatten_volume_from_snapshot = False

        with mock.patch.object(driver, 'LOG') as mock_log:
            with mock.patch.object(self.driver.rbd.Image(), 'stripe_unit') as \
                    mock_rbd_image_stripe_unit:
                mock_rbd_image_stripe_unit.return_value = 4194304
                self.driver.create_volume_from_snapshot(self.volume_a,
                                                        self.snapshot)

            mock_log.info.assert_called_with('Using v2 Clone API')

        self.assertTrue(self.driver._clone_v2_api_checked)

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch.object(driver.RBDDriver, '_resize', mock.Mock())
    def test_log_create_vol_from_snap_without_v2_clone_api(self,
                                                           volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a

        self.mock_proxy().__enter__().volume.op_features.return_value = 0
        self.mock_rbd.RBD_OPERATION_FEATURE_CLONE_PARENT = 1

        self.cfg.rbd_flatten_volume_from_snapshot = False

        with mock.patch.object(driver, 'LOG') as mock_log:
            with mock.patch.object(self.driver.rbd.Image(), 'stripe_unit') as \
                    mock_rbd_image_stripe_unit:
                mock_rbd_image_stripe_unit.return_value = 4194304
                self.driver.create_volume_from_snapshot(self.volume_a,
                                                        self.snapshot)

            self.assertTrue(any(m for m in mock_log.warning.call_args_list
                                if 'Not using v2 clone API' in m[0][0]))

        self.assertTrue(self.driver._clone_v2_api_checked)

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch.object(driver.RBDDriver, '_get_stripe_unit',
                       mock.Mock(return_value=4194304))
    @mock.patch.object(driver.RBDDriver, '_resize', mock.Mock())
    @mock.patch.object(driver.RBDDriver, '_flatten')
    def test_create_temp_vol_from_snap(self, flatten_mock, volume_get_by_id):
        volume_get_by_id.return_value = self.temp_volume

        snapshot = mock.Mock(volume_name='volume-name',
                             volume_size=self.temp_volume.size)
        # This is a temp vol so this option will be ignored and won't flatten
        self.cfg.rbd_flatten_volume_from_snapshot = True

        self.driver.create_volume_from_snapshot(self.temp_volume, snapshot)
        flatten_mock.assert_not_called()

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch.object(driver.RBDDriver, '_get_stripe_unit',
                       mock.Mock(return_value=4194304))
    @mock.patch.object(driver.RBDDriver, '_resize', mock.Mock())
    @mock.patch.object(driver.RBDDriver, '_flatten')
    def test_create_vol_from_snap(self, flatten_mock, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a

        snapshot = mock.Mock(volume_name='volume-name',
                             volume_size=self.volume_a.size)
        self.cfg.rbd_flatten_volume_from_snapshot = True

        self.driver.create_volume_from_snapshot(self.volume_a, snapshot)
        flatten_mock.assert_called_once_with(self.cfg.rbd_pool,
                                             self.volume_a.name)

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch.object(driver.RBDDriver, '_resize', mock.Mock())
    def test_log_create_vol_from_snap_raise(self, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a

        self.mock_proxy().__enter__().volume.op_features.side_effect = \
            Exception
        self.mock_rbd.RBD_OPERATION_FEATURE_CLONE_PARENT = 1

        snapshot = self.snapshot
        self.cfg.rbd_flatten_volume_from_snapshot = False

        with mock.patch.object(driver, 'LOG') as mock_log:
            # Fist call
            self.driver.create_volume_from_snapshot(self.volume_a, snapshot)
            self.assertTrue(self.driver._clone_v2_api_checked)
            # Second call
            self.driver.create_volume_from_snapshot(self.volume_a, snapshot)
            # Check that that the second call to create_volume_from_snapshot
            # doesn't log anything
            mock_log.warning.assert_called_once_with(mock.ANY)

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

        proxy.remove_snap.assert_not_called()
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
            self.mock_rbd.ImageBusy,
            None)

        with mock.patch.object(self.driver, '_flatten_children') as \
                mock_flatten_children:
            self.driver.delete_snapshot(self.snapshot)

            mock_flatten_children.assert_called_once_with(mock.ANY,
                                                          self.volume_a.name,
                                                          self.snapshot.name)

            self.assertTrue(proxy.unprotect_snap.called)
            self.assertTrue(proxy.remove_snap.called)

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_flatten')
    @mock.patch('cinder.objects.Volume.get_by_id')
    def test_delete_busy_snapshot_fail(self, volume_get_by_id, flatten_mock):
        volume_get_by_id.return_value = self.volume_a
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy

        proxy.unprotect_snap.side_effect = (
            self.mock_rbd.ImageBusy,
            self.mock_rbd.ImageBusy,
            self.mock_rbd.ImageBusy)
        flatten_mock.side_effect = exception.SnapshotIsBusy(self.snapshot.name)

        self.assertRaises(exception.SnapshotIsBusy,
                          self.driver.delete_snapshot,
                          self.snapshot)

        self.assertTrue(proxy.unprotect_snap.called)
        self.assertFalse(proxy.remove_snap.called)

    @common_mocks
    @mock.patch('cinder.objects.Volume.get_by_id')
    def test_delete_snapshot_volume_not_found(self, volume_get_by_id):
        volume_get_by_id.return_value = self.volume_a
        proxy = self.mock_proxy.return_value
        proxy.__enter__.side_effect = self.mock_rbd.ImageNotFound

        self.driver.delete_snapshot(self.snapshot)

        proxy.remove_snap.assert_not_called()
        proxy.unprotect_snap.assert_not_called()

    @common_mocks
    def test_snapshot_revert_use_temp_snapshot(self):
        self.assertFalse(self.driver.snapshot_revert_use_temp_snapshot())

    @common_mocks
    def test_revert_to_snapshot(self):
        image = self.mock_proxy.return_value.__enter__.return_value
        self.driver.revert_to_snapshot(self.context, self.volume_a,
                                       self.snapshot)
        image.rollback_to_snap.assert_called_once_with(self.snapshot.name)

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
        self.assertEqual([self.mock_rbd.ImageNotFound], RAISED_EXCEPTIONS)

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

    @ddt.data(3, 2, 1, 0)
    @common_mocks
    def test_get_clone_depth(self, expected_depth):
        # set the max_clone_depth option to check for Bug #1901241, where
        # lowering the configured rbd_max_clone_depth prevented cloning of
        # volumes that had already (legally) exceeded the new value because
        # _get_clone_depth would raise an uncaught exception
        self.cfg.rbd_max_clone_depth = 1

        # create a list of fake parents for the expected depth
        vols = [self.volume_a, self.volume_b, self.volume_c]
        volume_list = vols[:expected_depth]

        def fake_clone_info(volume, volume_name):
            parent = volume_list.pop() if volume_list else None
            return (None, parent, None)

        with mock.patch.object(
                self.driver, '_get_clone_info') as mock_get_clone_info:
            mock_get_clone_info.side_effect = fake_clone_info
            with mock.patch.object(
                    self.driver.rbd.Image(),
                    'close') as mock_rbd_image_close:

                depth = self.driver._get_clone_depth(self.mock_client,
                                                     "volume-00000000d")
                self.assertEqual(expected_depth, depth)
                # each parent must be closed plus the original volume
                self.assertEqual(expected_depth + 1,
                                 mock_rbd_image_close.call_count)

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

                self.assertEqual({}, res)
                (self.mock_rbd.Image.return_value.create_snap
                    .assert_called_once_with('.'.join(
                        (self.volume_b.name, 'clone_snap'))))
                (self.mock_rbd.Image.return_value.protect_snap
                    .assert_called_once_with('.'.join(
                        (self.volume_b.name, 'clone_snap'))))
                # We expect clone() to be called exactly once.
                self.assertEqual(
                    1, self.mock_rbd.RBD.return_value.clone.call_count)
                # Without flattening, only the source volume is opened,
                # so only one call to close() should occur.
                self.assertEqual(
                    1, self.mock_rbd.Image.return_value.close.call_count)
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
        self.assertEqual(
            1, self.mock_rbd.Image.return_value.close.call_count)
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

                self.assertEqual({}, res)
                (self.mock_rbd.Image.return_value.create_snap
                    .assert_called_once_with('.'.join(
                        (self.volume_b.name, 'clone_snap'))))
                (self.mock_rbd.Image.return_value.protect_snap
                    .assert_called_once_with('.'.join(
                        (self.volume_b.name, 'clone_snap'))))
                self.assertEqual(
                    1, self.mock_rbd.RBD.return_value.clone.call_count)
                self.assertEqual(
                    1, self.mock_rbd.Image.return_value.close.call_count)
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

    @ddt.data(True, False)
    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_create_cloned_volume_max_depth(self, use_quota, mock_enable_repl):
        """Test clone when we reach max depth.

        It will flatten for normal volumes and skip flattening for temporary
        volumes.
        """
        self.cfg.rbd_max_clone_depth = 1

        dest_vol = self.volume_b if use_quota else self.temp_volume

        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver, '_get_clone_info') as \
                mock_get_clone_info:
            mock_get_clone_info.return_value = (
                ('fake_pool', dest_vol.name,
                 '.'.join((dest_vol.name, 'clone_snap'))))
            with mock.patch.object(self.driver, '_get_clone_depth') as \
                    mock_get_clone_depth:
                # Force flatten
                mock_get_clone_depth.return_value = 1

                res = self.driver.create_cloned_volume(dest_vol,
                                                       self.volume_a)

                self.assertEqual({}, res)
                (self.mock_rbd.Image.return_value.create_snap
                 .assert_called_once_with('.'.join(
                     (dest_vol.name, 'clone_snap'))))
                (self.mock_rbd.Image.return_value.protect_snap
                 .assert_called_once_with('.'.join(
                     (dest_vol.name, 'clone_snap'))))
                self.assertEqual(
                    1, self.mock_rbd.RBD.return_value.clone.call_count)

                proxy = self.mock_proxy.return_value.__enter__.return_value
                if dest_vol.use_quota:
                    clone_snap_name = '.'.join((dest_vol.name, 'clone_snap'))
                    self.mock_rbd.Image.return_value.unprotect_snap.\
                        assert_called_once_with(clone_snap_name)
                    self.mock_rbd.Image.return_value.remove_snap.\
                        assert_called_once_with(clone_snap_name)
                    self.mock_proxy.assert_called_once_with(
                        self.driver, dest_vol.name,
                        client=client, ioctx=client.ioctx)
                    proxy.flatten.assert_called_once_with()

                else:
                    self.mock_rbd.Image.return_value.unprotect_snap.\
                        assert_not_called()
                    self.mock_rbd.Image.return_value.remove_snap.\
                        assert_not_called()
                    self.mock_proxy.assert_not_called()
                    proxy.flatten.assert_not_called()

                # Source volume is closed by direct call of close()
                self.assertEqual(
                    1, self.mock_rbd.Image.return_value.close.call_count)
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
            self.assertEqual(
                1, self.mock_rbd.Image.return_value.close.call_count)
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

    def _copy_image(self, volume_busy=False):
        with mock.patch.object(tempfile, 'NamedTemporaryFile'):
            with mock.patch.object(os.path, 'exists') as mock_exists:
                mock_exists.return_value = True
                with mock.patch.object(image_utils, 'fetch_to_raw'):
                    with mock.patch.object(self.driver, 'delete_volume') \
                            as mock_dv:
                        with mock.patch.object(self.driver, '_resize'):
                            mock_image_service = mock.MagicMock()
                            args = [None, self.volume_a,
                                    mock_image_service, None]
                            if volume_busy:
                                mock_dv.side_effect = (
                                    exception.VolumeIsBusy("doh"))
                                self.assertRaises(
                                    exception.VolumeIsBusy,
                                    self.driver.copy_image_to_volume,
                                    *args)
                                self.assertEqual(
                                    self.cfg.rados_connection_retries,
                                    mock_dv.call_count)
                            else:
                                self.driver.copy_image_to_volume(*args)

    @mock.patch('cinder.volume.drivers.rbd.fileutils.delete_if_exists')
    @mock.patch('cinder.image.image_utils.convert_image')
    def _copy_image_encrypted(self, mock_convert, mock_temp_delete):
        key_mgr = fake_keymgr.fake_api()
        self.mock_object(castellan.key_manager, 'API', return_value=key_mgr)
        key_id = key_mgr.store(self.context, KeyObject())
        self.volume_a.encryption_key_id = key_id

        enc_info = {'encryption_key_id': key_id,
                    'cipher': 'aes-xts-essiv',
                    'key_size': 256}
        with mock.patch('cinder.volume.volume_utils.check_encryption_provider',
                        return_value=enc_info), \
                mock.patch('cinder.volume.drivers.rbd.open'), \
                mock.patch('os.rename'):
            with mock.patch.object(tempfile, 'NamedTemporaryFile'):
                with mock.patch.object(os.path, 'exists') as mock_exists:
                    mock_exists.return_value = True
                    with mock.patch.object(image_utils, 'fetch_to_raw'):
                        with mock.patch.object(self.driver, 'delete_volume'):
                            with mock.patch.object(self.driver, '_resize'):
                                mock_image_service = mock.MagicMock()
                                args = [self.context, self.volume_a,
                                        mock_image_service, None]
                                self.driver.copy_image_to_encrypted_volume(
                                    *args)
                                mock_temp_delete.assert_called()
                                self.assertEqual(1,
                                                 mock_temp_delete.call_count)

    @common_mocks
    def test_copy_image_no_volume_tmp(self):
        self.cfg.image_conversion_dir = None
        self._copy_image()

    @common_mocks
    def test_copy_image_volume_tmp(self):
        self.cfg.image_conversion_dir = '/var/run/cinder/tmp'
        self._copy_image()

    @common_mocks
    def test_copy_image_volume_tmp_encrypted(self):
        self.cfg.image_conversion_dir = '/var/run/cinder/tmp'
        self._copy_image_encrypted()

    @common_mocks
    def test_copy_image_busy_volume(self):
        self.cfg.image_conversion_dir = '/var/run/cinder/tmp'
        self._copy_image(volume_busy=True)

    @ddt.data(True, False)
    @common_mocks
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._supports_qos')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_usage_info')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_pool_stats')
    def test_update_volume_stats(self, replication_enabled, stats_mock,
                                 usage_mock, mock_qos_supported):
        stats_mock.return_value = (mock.sentinel.free_capacity_gb,
                                   mock.sentinel.total_capacity_gb)
        usage_mock.return_value = mock.sentinel.provisioned_capacity_gb

        mock_qos_supported.return_value = True

        expected_fsid = 'abc'
        expected_location_info = ('nondefault:%s:%s:%s:rbd' %
                                  (self.cfg.rbd_ceph_conf, expected_fsid,
                                   self.cfg.rbd_user))
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
            multiattach=True,
            location_info=expected_location_info,
            backend_state='up',
            qos_support=True)

        if replication_enabled:
            targets = [{'backend_id': 'secondary-backend'},
                       {'backend_id': 'tertiary-backend'}]
            with mock.patch.object(self.driver.configuration, 'safe_get',
                                   return_value=targets):
                self.driver._do_setup_replication()
            expected['replication_targets'] = [t['backend_id']for t in targets]
            expected['replication_targets'].append('default')

        my_safe_get = MockDriverConfig(rbd_exclusive_cinder_pool=False)
        self.mock_object(self.driver.configuration, 'safe_get',
                         my_safe_get)

        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = expected_fsid
            actual = self.driver.get_volume_stats(True)
            self.assertDictEqual(expected, actual)
            mock_qos_supported.assert_called_once_with()

    @common_mocks
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._supports_qos')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_usage_info')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_pool_stats')
    def test_update_volume_stats_exclusive_pool(self, stats_mock, usage_mock,
                                                mock_qos_supported):
        stats_mock.return_value = (mock.sentinel.free_capacity_gb,
                                   mock.sentinel.total_capacity_gb)

        # Set the version to unsupported, leading to the qos_support parameter
        # in the actual output differing to the one set below in expected.
        mock_qos_supported.return_value = False

        expected_fsid = 'abc'
        expected_location_info = ('nondefault:%s:%s:%s:rbd' %
                                  (self.cfg.rbd_ceph_conf, expected_fsid,
                                   self.cfg.rbd_user))
        expected = dict(
            volume_backend_name='RBD',
            replication_enabled=False,
            vendor_name='Open Source',
            driver_version=self.driver.VERSION,
            storage_protocol='ceph',
            total_capacity_gb=mock.sentinel.total_capacity_gb,
            free_capacity_gb=mock.sentinel.free_capacity_gb,
            reserved_percentage=0,
            thin_provisioning_support=True,
            max_over_subscription_ratio=1.0,
            multiattach=True,
            location_info=expected_location_info,
            backend_state='up',
            qos_support=False)

        my_safe_get = MockDriverConfig(rbd_exclusive_cinder_pool=True)
        self.mock_object(self.driver.configuration, 'safe_get',
                         my_safe_get)

        with mock.patch.object(self.driver, '_get_fsid',
                               return_value=expected_fsid):
            actual = self.driver.get_volume_stats(True)

        self.assertDictEqual(expected, actual)
        usage_mock.assert_not_called()
        mock_qos_supported.assert_called_once_with()

    @common_mocks
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._supports_qos')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_usage_info')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver._get_pool_stats')
    def test_update_volume_stats_error(self, stats_mock, usage_mock,
                                       mock_qos_supported):
        my_safe_get = MockDriverConfig(rbd_exclusive_cinder_pool=False)
        self.mock_object(self.driver.configuration, 'safe_get',
                         my_safe_get)

        mock_qos_supported.return_value = True

        expected_fsid = 'abc'
        expected_location_info = ('nondefault:%s:%s:%s:rbd' %
                                  (self.cfg.rbd_ceph_conf, expected_fsid,
                                   self.cfg.rbd_user))
        expected = dict(volume_backend_name='RBD',
                        replication_enabled=False,
                        vendor_name='Open Source',
                        driver_version=self.driver.VERSION,
                        storage_protocol='ceph',
                        total_capacity_gb='unknown',
                        free_capacity_gb='unknown',
                        reserved_percentage=0,
                        multiattach=True,
                        max_over_subscription_ratio=1.0,
                        thin_provisioning_support=True,
                        location_info=expected_location_info,
                        backend_state='down',
                        qos_support=True)

        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = expected_fsid
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
            mock.call('{"prefix":"df", "format":"json"}', b''),
            mock.call('{"prefix":"osd pool get-quota", "pool": "rbd",'
                      ' "format":"json"}', b''),
        ])
        self.assertEqual((free_capacity, total_capacity), result)

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
    def test_get_pool_nautilus(self, free_capacity, total_capacity,
                               max_avail=28987613184, quota_max_bytes=0,
                               dynamic_total=True):
        client = self.mock_client.return_value
        client.__enter__.return_value = client
        client.cluster.mon_command.side_effect = [
            (0, '{"stats":{"total_bytes":64385286144,'
             '"total_used_bytes":3289628672,"total_avail_bytes":61095657472},'
             '"pools":[{"name":"rbd","id":2,"stats":{"kb_used":1510197,'
             '"stored":1546440971,"bytes_used":4639322913,"max_avail":%s,'
             '"objects":412}},{"name":"volumes","id":3,"stats":{"kb_used":0,'
             '"bytes_used":0,"max_avail":28987613184,"objects":0}}]}\n' %
             max_avail, ''),
            (0, '{"pool_name":"volumes","pool_id":4,"quota_max_objects":0,'
             '"quota_max_bytes":%s}\n' % quota_max_bytes, ''),
        ]
        with mock.patch.object(self.driver.configuration, 'safe_get',
                               return_value=dynamic_total):
            result = self.driver._get_pool_stats()
        client.cluster.mon_command.assert_has_calls([
            mock.call('{"prefix":"df", "format":"json"}', b''),
            mock.call('{"prefix":"osd pool get-quota", "pool": "rbd",'
                      ' "format":"json"}', b''),
        ])
        self.assertEqual((free_capacity, total_capacity), result)

    @common_mocks
    def test_get_pool_bytes(self):
        """Test for mon_commands returning bytes instead of strings."""
        client = self.mock_client.return_value
        client.__enter__.return_value = client
        client.cluster.mon_command.side_effect = [
            (0, b'{"stats":{"total_bytes":64385286144,'
             b'"total_used_bytes":3289628672,"total_avail_bytes":61095657472},'
             b'"pools":[{"name":"rbd","id":2,"stats":{"kb_used":1510197,'
             b'"bytes_used":1546440971,"max_avail":2897613184,"objects":412}},'
             b'{"name":"volumes","id":3,"stats":{"kb_used":0,"bytes_used":0,'
             b'"max_avail":28987613184,"objects":0}}]}\n', ''),
            (0, b'{"pool_name":"volumes","pool_id":4,"quota_max_objects":0,'
             b'"quota_max_bytes":3221225472}\n', ''),
        ]
        result = self.driver._get_pool_stats()
        client.cluster.mon_command.assert_has_calls([
            mock.call('{"prefix":"df", "format":"json"}', b''),
            mock.call('{"prefix":"osd pool get-quota", "pool": "rbd",'
                      ' "format":"json"}', b''),
        ])
        free_capacity = 1.56
        total_capacity = 3.0
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

    def test_initialize_connection(self):
        hosts = ['::1', '::1', '::1', '127.0.0.1', 'example.com']
        ports = ['6789', '6790', '6791', '6792', '6791']

        self.driver._active_config = {'name': 'secondary_id',
                                      'user': 'foo',
                                      'conf': 'bar',
                                      'secret_uuid': self.cfg.rbd_secret_uuid}
        expected = {
            'driver_volume_type': 'rbd',
            'data': {
                'name': '%s/%s' % (self.cfg.rbd_pool,
                                   self.volume_a.name),
                'hosts': hosts,
                'ports': ports,
                'cluster_name': 'secondary_id',
                'auth_enabled': True,
                'auth_username': 'foo',
                'secret_type': 'ceph',
                'secret_uuid': self.cfg.rbd_secret_uuid,
                'volume_id': self.volume_a.id,
                'discard': True,
            }
        }
        self._initialize_connection_helper(expected, hosts, ports)

        # Check how it will work with keyring data (for cinderlib)
        keyring_data = "[client.cinder]\n  key = test\n"
        self.driver.keyring_data = keyring_data
        expected['data']['keyring'] = keyring_data
        self._initialize_connection_helper(expected, hosts, ports)

        self.driver._active_config = {'name': 'secondary_id',
                                      'user': 'foo',
                                      'conf': 'bar',
                                      'secret_uuid': 'secondary_secret_uuid'}
        expected['data']['secret_uuid'] = 'secondary_secret_uuid'
        self._initialize_connection_helper(expected, hosts, ports)

    def test__set_keyring_attributes_openstack(self):
        # OpenStack usage doesn't have the rbd_keyring_conf Oslo Config option
        self.assertFalse(hasattr(self.driver.configuration,
                                 'rbd_keyring_conf'))
        # Set initial values so we can confirm that we set them to None
        self.driver.keyring_file = mock.sentinel.keyring_file
        self.driver.keyring_data = mock.sentinel.keyring_data

        self.driver._set_keyring_attributes()

        self.assertIsNone(self.driver.keyring_file)
        self.assertIsNone(self.driver.keyring_data)

    def test__set_keyring_attributes_cinderlib(self):
        # OpenStack usage doesn't have the rbd_keyring_conf Oslo Config option
        cfg_file = '/etc/ceph/ceph.client.admin.keyring'
        self.driver.configuration.rbd_keyring_conf = cfg_file
        with mock.patch('os.path.isfile', return_value=False):
            self.driver._set_keyring_attributes()
        self.assertEqual(cfg_file, self.driver.keyring_file)
        self.assertIsNone(self.driver.keyring_data)

    @mock.patch('os.path.isfile')
    @mock.patch.object(driver, 'open')
    def test__set_keyring_attributes_cinderlib_read_file(self, mock_open,
                                                         mock_isfile):
        cfg_file = '/etc/ceph/ceph.client.admin.keyring'
        # This is how cinderlib sets the config option
        setattr(self.driver.configuration, 'rbd_keyring_conf', cfg_file)

        keyring_data = "[client.cinder]\n  key = test\n"
        mock_read = mock_open.return_value.__enter__.return_value.read
        mock_read.return_value = keyring_data

        self.assertIsNone(self.driver.keyring_file)
        self.assertIsNone(self.driver.keyring_data)

        self.driver._set_keyring_attributes()

        mock_isfile.assert_called_once_with(cfg_file)
        mock_open.assert_called_once_with(cfg_file, 'r')
        mock_read.assert_called_once_with()
        self.assertEqual(cfg_file, self.driver.keyring_file)
        self.assertEqual(keyring_data, self.driver.keyring_data)

    @mock.patch('os.path.isfile')
    @mock.patch.object(driver, 'open', side_effect=IOError)
    def test__set_keyring_attributes_cinderlib_error(self, mock_open,
                                                     mock_isfile):
        cfg_file = '/etc/ceph/ceph.client.admin.keyring'
        # This is how cinderlib sets the config option
        setattr(self.driver.configuration, 'rbd_keyring_conf', cfg_file)

        self.assertIsNone(self.driver.keyring_file)
        self.driver.keyring_data = mock.sentinel.keyring_data

        self.driver._set_keyring_attributes()

        mock_isfile.assert_called_once_with(cfg_file)
        mock_open.assert_called_once_with(cfg_file, 'r')
        self.assertEqual(cfg_file, self.driver.keyring_file)
        self.assertIsNone(self.driver.keyring_data)

    @ddt.data({'rbd_chunk_size': 1},
              {'rbd_chunk_size': 8},
              {'rbd_chunk_size': 32})
    @ddt.unpack
    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_clone(self, mock_enable_repl, rbd_chunk_size):
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

        with mock.patch.object(self.driver.rbd.Image(), 'stripe_unit') as \
                mock_rbd_image_stripe_unit:
            mock_rbd_image_stripe_unit.return_value = 4194304
            res = self.driver._clone(self.volume_a, src_pool, src_image,
                                     src_snap)

        self.assertEqual({}, res)

        args = [client_stack[0].ioctx, str(src_image), str(src_snap),
                client_stack[1].ioctx, str(self.volume_a.name)]
        stripe_unit = max(4194304, rbd_chunk_size * 1048576)
        expected_order = int(math.log(stripe_unit, 2))
        kwargs = {'features': client.features,
                  'order': expected_order}
        self.mock_rbd.RBD.return_value.clone.assert_called_once_with(
            *args, **kwargs)
        self.assertEqual(2, client.__enter__.call_count)
        mock_enable_repl.assert_not_called()

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_enable_replication')
    def test_clone_replicated(self, mock_enable_repl):
        order = 20
        rbd_chunk_size = 1
        stripe_unit = 1048576
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

        with mock.patch.object(self.driver.rbd.Image(), 'stripe_unit') as \
                mock_rbd_image_stripe_unit:
            mock_rbd_image_stripe_unit.return_value = stripe_unit
            res = self.driver._clone(self.volume_a, src_pool, src_image,
                                     src_snap)

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
        snapshot = self.snapshot_b

        res = self.driver.create_volume_from_snapshot(self.volume_a, snapshot)

        self.assertEqual(mock.sentinel.volume_update, res)
        mock_clone.assert_called_once_with(self.volume_a,
                                           self.cfg.rbd_pool,
                                           snapshot.volume_name,
                                           snapshot.name)

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_clone',
                       return_value=mock.sentinel.volume_update)
    def test_create_encrypted_vol_from_snap_same_size(self, mock_clone):
        """Test create encrypted volume from encrypted snapshot.

        When creating an encrypted volume from encrypted snapshot
        the new volume is same size than the snapshot.
        """
        self.cfg.rbd_flatten_volume_from_snapshot = False
        volume_size = self.volume_c.size
        self.snapshot_b.volume_size = volume_size

        mock_resize = self.mock_object(self.driver, '_resize')
        mock_new_size = self.mock_object(self.driver,
                                         '_calculate_new_size')

        res = self.driver.create_volume_from_snapshot(self.volume_c,
                                                      self.snapshot_b)
        self.assertEqual(mock.sentinel.volume_update, res)
        mock_resize.assert_not_called()
        mock_new_size.assert_not_called()

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_clone',
                       return_value=mock.sentinel.volume_update)
    def test_create_encrypted_vol_from_snap(self, mock_clone):
        """Test create encrypted volume from encrypted snapshot.

        When creating an encrypted volume from encrypted snapshot
        the new volume is larger than the snapshot (12GB vs 11GB).
        """
        self.cfg.rbd_flatten_volume_from_snapshot = False
        new_size_bytes = 12288
        diff_size = 1
        volume_size = 11
        self.snapshot_b.volume_size = volume_size

        mock_resize = self.mock_object(self.driver, '_resize')
        mock_new_size = self.mock_object(self.driver,
                                         '_calculate_new_size')

        mock_new_size.return_value = new_size_bytes
        res = self.driver.create_volume_from_snapshot(self.volume_c,
                                                      self.snapshot_b)
        self.assertEqual(mock.sentinel.volume_update, res)
        mock_resize.assert_called_once_with(self.volume_c,
                                            size=new_size_bytes)
        volume_name = self.volume_c.name
        mock_new_size.assert_called_once_with(diff_size,
                                              volume_name)

    @common_mocks
    @mock.patch.object(driver.RBDDriver, '_clone',
                       return_value=mock.sentinel.volume_update)
    def test_create_unencrypted_vol_from_snap(self, mock_clone):
        """Test create regular volume from regular snapshot"""

        self.cfg.rbd_flatten_volume_from_snapshot = False
        self.snapshot_b.volume.size = 9
        mock_resize = self.mock_object(self.driver, '_resize')
        mock_new_size = self.mock_object(self.driver,
                                         '_calculate_new_size')
        res = self.driver.create_volume_from_snapshot(self.volume_b,
                                                      self.snapshot_b)
        self.assertEqual(mock.sentinel.volume_update, res)
        mock_resize.assert_called_once_with(self.volume_b, size=None)
        mock_new_size.assert_not_called()

    @common_mocks
    def test_extend_volume(self):
        fake_size = '20'
        size = int(fake_size) * units.Gi
        with mock.patch.object(self.driver, '_resize') as mock_resize:
            self.driver.extend_volume(self.volume_a, fake_size)
            mock_resize.assert_called_once_with(self.volume_a, size=size)

    @mock.patch.object(driver.RBDDriver, '_qos_specs_from_volume_type')
    @mock.patch.object(driver.RBDDriver, '_supports_qos')
    @ddt.data(False, True)
    @common_mocks
    def test_retype(self, enabled, mock_qos_vers, mock_get_qos_specs):
        """Test retyping a non replicated volume.

        We will test on a system that doesn't have replication enabled and on
        one that hast it enabled.
        """
        self.driver._is_replication_enabled = enabled
        mock_qos_vers.return_value = False
        if enabled:
            expect = {'replication_status': fields.ReplicationStatus.DISABLED}
        else:
            expect = {}
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
    @mock.patch.object(driver.RBDDriver, '_qos_specs_from_volume_type')
    @mock.patch.object(driver.RBDDriver, '_supports_qos')
    @mock.patch.object(driver.RBDDriver, '_disable_replication',
                       return_value={'replication': 'disabled'})
    @mock.patch.object(driver.RBDDriver, '_enable_replication',
                       return_value={'replication': 'enabled'})
    def test_retype_replicated(self, mock_disable, mock_enable, mock_qos_vers,
                               mock_get_qos_specs, old_replicated,
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

        mock_qos_vers.return_value = False
        mock_get_qos_specs.return_value = False

        if new_replicated:
            new_type = replicated_type
            if old_replicated:
                update = {}
            else:
                update = {'replication': 'enabled'}
        else:
            new_type = fake_volume.fake_volume_type_obj(
                self.context,
                id=fake.VOLUME_TYPE2_ID),
            if old_replicated:
                update = {'replication': 'disabled'}
            else:
                update = {'replication_status':
                          fields.ReplicationStatus.DISABLED}

        res = self.driver.retype(self.context, self.volume_a, new_type, None,
                                 None)
        self.assertEqual((True, update), res)

    @common_mocks
    @mock.patch.object(driver.RBDDriver, 'delete_rbd_image_qos_keys')
    @mock.patch.object(driver.RBDDriver, 'get_rbd_image_qos')
    @mock.patch.object(driver.RBDDriver, '_supports_qos')
    @mock.patch.object(driver.RBDDriver, 'update_rbd_image_qos')
    def test_retype_qos(self, mock_update_qos, mock_qos_supported,
                        mock_get_vol_qos, mock_del_vol_qos):

        ctxt = context.get_admin_context()
        qos_a = qos_specs.create(ctxt, "qos-vers-a", self.qos_policy_a)
        qos_b = qos_specs.create(ctxt, "qos-vers-b", self.qos_policy_b)

        # The vol_config dictionary containes supported as well as currently
        # unsupported values (CNA). The latter will be marked accordingly to
        # indicate the current support status.
        vol_config = {
            "rbd_qos_bps_burst": "0",
            "rbd_qos_bps_burst_seconds": "1",  # CNA
            "rbd_qos_bps_limit": "1024",
            "rbd_qos_iops_burst": "0",
            "rbd_qos_iops_burst_seconds": "1",  # CNA
            "rbd_qos_iops_limit": "100",
            "rbd_qos_read_bps_burst": "0",
            "rbd_qos_read_bps_burst_seconds": "1",  # CNA
            "rbd_qos_read_bps_limit": "0",
            "rbd_qos_read_iops_burst": "0",
            "rbd_qos_read_iops_burst_seconds": "1",  # CNA
            "rbd_qos_read_iops_limit": "0",
            "rbd_qos_schedule_tick_min": "50",  # CNA
            "rbd_qos_write_bps_burst": "0",
            "rbd_qos_write_bps_burst_seconds": "1",  # CNA
            "rbd_qos_write_bps_limit": "0",
            "rbd_qos_write_iops_burst": "0",
            "rbd_qos_write_iops_burst_seconds": "1",  # CNA
            "rbd_qos_write_iops_limit": "0",
        }

        mock_get_vol_qos.return_value = vol_config

        diff = {'encryption': {},
                'extra_specs': {},
                'qos_specs': {'consumer': (u'front-end', u'back-end'),
                              'created_at': (123, 456),
                              u'total_bytes_sec': (u'1024', None),
                              u'total_iops_sec': (u'200', None)}}

        delete_qos = ['total_iops_sec', 'total_bytes_sec']

        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            ctxt,
            id=fake.VOLUME_TYPE_ID,
            qos_specs_id = qos_a.id)

        new_type = fake_volume.fake_volume_type_obj(
            ctxt,
            id=fake.VOLUME_TYPE2_ID,
            qos_specs_id = qos_b.id)

        mock_qos_supported.return_value = True

        res = self.driver.retype(ctxt, self.volume_a, new_type, diff,
                                 None)
        self.assertEqual((True, {}), res)

        assert delete_qos == [key for key in delete_qos
                              if key in driver.QOS_KEY_MAP]
        mock_update_qos.assert_called_once_with(self.volume_a, qos_b.specs)
        mock_del_vol_qos.assert_called_once_with(self.volume_a, delete_qos)

    @common_mocks
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver.RBDProxy')
    def test__supports_qos(self, rbdproxy_mock):
        rbdproxy_ver = 20
        rbdproxy_mock.return_value.version.return_value = (0, rbdproxy_ver)

        self.assertTrue(self.driver._supports_qos())

    @common_mocks
    def test__qos_specs_from_volume_type(self):
        ctxt = context.get_admin_context()
        qos = qos_specs.create(ctxt, "qos-vers-a", self.qos_policy_a)
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            ctxt,
            id=fake.VOLUME_TYPE_ID,
            qos_specs_id = qos.id)

        self.assertEqual(
            {'total_iops_sec': '100', 'total_bytes_sec': '1024'},
            self.driver._qos_specs_from_volume_type(self.volume_a.volume_type))

    @common_mocks
    def test_get_rbd_image_qos(self):
        ctxt = context.get_admin_context()
        qos = qos_specs.create(ctxt, "qos-vers-a", self.qos_policy_a)
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            ctxt,
            id=fake.VOLUME_TYPE_ID,
            qos_specs_id = qos.id)

        rbd_image_conf = []
        for qos_key, qos_val in (
                self.volume_a.volume_type.qos_specs.specs.items()):
            rbd_image_conf.append(
                {'name': driver.QOS_KEY_MAP[qos_key]['ceph_key'],
                 'value': int(qos_val)})

        rbd_image = self.mock_proxy.return_value.__enter__.return_value
        rbd_image.config_list.return_value = rbd_image_conf

        self.assertEqual(
            {'rbd_qos_bps_limit': 1024, 'rbd_qos_iops_limit': 100},
            self.driver.get_rbd_image_qos(self.volume_a))

    @common_mocks
    def test_update_rbd_image_qos(self):
        ctxt = context.get_admin_context()
        qos = qos_specs.create(ctxt, "qos-vers-a", self.qos_policy_a)
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            ctxt,
            id=fake.VOLUME_TYPE_ID,
            qos_specs_id = qos.id)

        rbd_image = self.mock_proxy.return_value.__enter__.return_value

        updated_specs = {"total_iops_sec": '50'}
        rbd_image.config_set.return_value = qos_specs.update(ctxt,
                                                             qos.id,
                                                             updated_specs)

        self.driver.update_rbd_image_qos(self.volume_a, updated_specs)
        self.assertEqual(
            {'total_bytes_sec': '1024', 'total_iops_sec': '50'},
            self.volume_a.volume_type.qos_specs.specs)

    @common_mocks
    def test_delete_rbd_image_qos_key(self):
        ctxt = context.get_admin_context()
        qos = qos_specs.create(ctxt, 'qos-vers-a', self.qos_policy_a)
        self.volume_a.volume_type = fake_volume.fake_volume_type_obj(
            ctxt,
            id=fake.VOLUME_TYPE_ID,
            qos_specs_id = qos.id)

        rbd_image = self.mock_proxy.return_value.__enter__.return_value

        keys = ['total_iops_sec']
        rbd_image.config_remove.return_value = qos_specs.delete_keys(ctxt,
                                                                     qos.id,
                                                                     keys)

        self.driver.delete_rbd_image_qos_keys(self.volume_a, keys)

        self.assertEqual(
            {'total_bytes_sec': '1024'},
            self.volume_a.volume_type.qos_specs.specs)

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

    @common_mocks
    def test_update_migrated_volume_in_use(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver.rbd.RBD(), 'rename') as mock_rename:
            context = {}
            mock_rename.return_value = 0
            model_update = self.driver.update_migrated_volume(context,
                                                              self.volume_a,
                                                              self.volume_b,
                                                              'in-use')
            mock_rename.assert_not_called()
            self.assertEqual({'_name_id': self.volume_b.id,
                              'provider_location':
                                  self.volume_b['provider_location']},
                             model_update)

    @common_mocks
    def test_update_migrated_volume_image_exists(self):
        client = self.mock_client.return_value
        client.__enter__.return_value = client

        with mock.patch.object(self.driver.rbd.RBD(), 'rename') as mock_rename:
            context = {}
            mock_rename.return_value = 1
            mock_rename.side_effect = MockImageExistsException

            model_update = self.driver.update_migrated_volume(context,
                                                              self.volume_a,
                                                              self.volume_b,
                                                              'available')
            mock_rename.assert_called_with(client.ioctx,
                                           'volume-%s' % self.volume_b.id,
                                           'volume-%s' % self.volume_a.id)
            self.assertEqual({'_name_id': self.volume_b.id,
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

    def test_rbd_volume_proxy_external_conn(self):
        mock_driver = mock.Mock(name='driver')
        mock_driver._connect_to_rados.return_value = (None, None)
        with driver.RBDVolumeProxy(mock_driver, self.volume_a.name,
                                   client='fake_cl', ioctx='fake_io'):

            mock_driver._connect_to_rados.assert_not_called()

        mock_driver._disconnect_from_rados.assert_not_called()

    def test_rbd_volume_proxy_external_conn_no_iocxt(self):
        mock_driver = mock.Mock(name='driver')
        mock_driver._connect_to_rados.return_value = ('fake_cl', 'fake_io')
        with driver.RBDVolumeProxy(mock_driver, self.volume_a.name,
                                   client='fake_cl', pool='vol_pool'):
            mock_driver._connect_to_rados.assert_called_once_with(
                'vol_pool', None, None)

        mock_driver._disconnect_from_rados.assert_called_once_with(
            'fake_cl', 'fake_io')

    def test_rbd_volume_proxy_external_conn_error(self):
        mock_driver = mock.Mock(name='driver')
        mock_driver._connect_to_rados.return_value = (None, None)

        class RBDError(Exception):
            pass

        mock_driver.rbd.Error = RBDError
        mock_driver.rbd.Image.side_effect = RBDError()

        self.assertRaises(RBDError, driver.RBDVolumeProxy,
                          mock_driver, self.volume_a.name,
                          client='fake_cl', ioctx='fake_io')

        mock_driver._connect_to_rados.assert_not_called()
        mock_driver._disconnect_from_rados.assert_not_called()

    def test_rbd_volume_proxy_conn_error(self):
        mock_driver = mock.Mock(name='driver')
        mock_driver._connect_to_rados.return_value = (
            'fake_client', 'fake_ioctx')

        class RBDError(Exception):
            pass

        mock_driver.rbd.Error = RBDError
        mock_driver.rbd.Image.side_effect = RBDError()

        self.assertRaises(RBDError, driver.RBDVolumeProxy,
                          mock_driver, self.volume_a.name,
                          pool='fake-volumes')

        mock_driver._connect_to_rados.assert_called_once_with(
            'fake-volumes', None, None)
        mock_driver._disconnect_from_rados.assert_called_once_with(
            'fake_client', 'fake_ioctx')

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
        mock_get_cfg.assert_called_with(secondary_id)

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
        proxy.is_protected_snap.return_value = False
        self.driver.manage_existing_snapshot(self.snapshot_b, existing_ref)
        proxy.rename_snap.assert_called_with(exist_snapshot,
                                             self.snapshot_b.name)
        proxy.protect_snap.assert_called_with(self.snapshot_b.name)

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
        self.assertEqual([self.mock_rbd.ImageExists], RAISED_EXCEPTIONS)

    @common_mocks
    def test_get_manageable_snapshots(self):
        cinder_snaps = [{'id': '00000000-0000-0000-0000-000000000000',
                         'volume_id': '11111111-1111-1111-1111-111111111111'}]
        vols = ['volume-11111111-1111-1111-1111-111111111111', 'vol1']
        self.mock_rbd.RBD.return_value.list.return_value = vols
        image = self.mock_proxy.return_value.__enter__.return_value
        image.list_snaps.side_effect = [
            [{'id': 1, 'name': 'snapshot-00000000-0000-0000-0000-000000000000',
              'size': 2 * units.Gi},
             {'id': 2, 'name': 'snap1', 'size': 6 * units.Gi},
             {'id': 3, 'size': 8 * units.Gi,
              'name': 'volume-22222222-2222-2222-2222-222222222222.clone_snap'
              },
             {'id': 4, 'size': 5 * units.Gi,
              'name': 'backup.33333333-3333-3333-3333-333333333333.snap.123'}],
            [{'id': 1, 'name': 'snap2', 'size': 4 * units.Gi}]]
        res = self.driver.get_manageable_snapshots(
            cinder_snaps, None, 1000, 0, ['size'], ['desc'])
        exp = [
            {'size': 8, 'safe_to_manage': False, 'extra_info': None,
             'reason_not_safe': 'used for clone snap', 'cinder_id': None,
             'reference': {
                 'source-name':
                     'volume-22222222-2222-2222-2222-222222222222.clone_snap'},
             'source_reference': {
                 'source-name': 'volume-11111111-1111-1111-1111-111111111111'}
             },
            {'size': 6, 'safe_to_manage': True, 'extra_info': None,
             'reason_not_safe': None, 'cinder_id': None,
             'reference': {'source-name': 'snap1'},
             'source_reference': {
                 'source-name': 'volume-11111111-1111-1111-1111-111111111111'}
             },
            {'size': 5, 'safe_to_manage': False, 'extra_info': None,
             'reason_not_safe': 'used for volume backup', 'cinder_id': None,
             'reference': {
                 'source-name':
                     'backup.33333333-3333-3333-3333-333333333333.snap.123'},
             'source_reference': {
                 'source-name': 'volume-11111111-1111-1111-1111-111111111111'}
             },
            {'size': 4, 'safe_to_manage': True, 'extra_info': None,
             'reason_not_safe': None, 'cinder_id': None,
             'reference': {'source-name': 'snap2'},
             'source_reference': {'source-name': 'vol1'}
             },
            {'size': 2, 'safe_to_manage': False, 'extra_info': None,
             'reason_not_safe': 'already managed',
             'cinder_id': '00000000-0000-0000-0000-000000000000',
             'reference': {'source-name':
                           'snapshot-00000000-0000-0000-0000-000000000000'},
             'source_reference': {
                 'source-name': 'volume-11111111-1111-1111-1111-111111111111'}
             }]
        self.assertEqual(exp, res)

    @common_mocks
    def test_unmanage_snapshot(self):
        proxy = self.mock_proxy.return_value
        proxy.__enter__.return_value = proxy
        proxy.list_children.return_value = []
        proxy.is_protected_snap.return_value = True
        self.driver.unmanage_snapshot(self.snapshot_b)
        proxy.unprotect_snap.assert_called_with(self.snapshot_b.name)

    @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
    @mock.patch('cinder.volume.drivers.rbd.RADOSClient')
    @mock.patch('cinder.volume.drivers.rbd.RBDDriver.RBDProxy')
    def test__get_usage_info(self, rbdproxy_mock, client_mock, volproxy_mock):

        def FakeVolProxy(size_or_exc):
            return mock.Mock(return_value=mock.Mock(
                size=mock.Mock(side_effect=(size_or_exc,))))

        volumes = [
            'volume-1',
            'non-existent',
            'non-existent',
            'non-cinder-volume'
        ]

        client = client_mock.return_value.__enter__.return_value
        rbdproxy_mock.return_value.list.return_value = volumes

        with mock.patch.object(self.driver, 'rbd',
                               ImageNotFound=MockImageNotFoundException,
                               OSError=MockOSErrorException):
            volproxy_mock.side_effect = [
                mock.MagicMock(**{'__enter__': FakeVolProxy(s)})
                for s in (1.0 * units.Gi,
                          self.driver.rbd.ImageNotFound,
                          self.driver.rbd.OSError,
                          2.0 * units.Gi)
            ]
            total_provision = self.driver._get_usage_info()

        rbdproxy_mock.return_value.list.assert_called_once_with(client.ioctx)

        expected_volproxy_calls = [
            mock.call(self.driver, v, read_only=True,
                      client=client.cluster, ioctx=client.ioctx)
            for v in volumes]
        self.assertEqual(expected_volproxy_calls, volproxy_mock.mock_calls)

        self.assertEqual(3.00, total_provision)

    def test_migrate_volume_bad_volume_status(self):
        self.volume_a.status = 'backingup'
        ret = self.driver.migrate_volume(context, self.volume_a, None)
        self.assertEqual((False, None), ret)

    def test_migrate_volume_bad_host(self):
        host = {
            'capabilities': {
                'storage_protocol': 'not-ceph'}}
        ret = self.driver.migrate_volume(context, self.volume_a, host)
        self.assertEqual((False, None), ret)

    def test_migrate_volume_missing_location_info(self):
        host = {
            'capabilities': {
                'storage_protocol': 'ceph'}}
        ret = self.driver.migrate_volume(context, self.volume_a, host)
        self.assertEqual((False, None), ret)

    def test_migrate_volume_invalid_location_info(self):
        host = {
            'capabilities': {
                'storage_protocol': 'ceph',
                'location_info': 'foo:bar:baz'}}
        ret = self.driver.migrate_volume(context, self.volume_a, host)
        self.assertEqual((False, None), ret)

    @mock.patch('os_brick.initiator.linuxrbd.rbd')
    @mock.patch('os_brick.initiator.linuxrbd.RBDClient')
    def test_migrate_volume_mismatch_fsid(self, mock_client, mock_rbd):
        host = {
            'capabilities': {
                'storage_protocol': 'ceph',
                'location_info': 'nondefault:None:abc:None:rbd'}}

        mock_client().__enter__().client.get_fsid.return_value = 'abc'

        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'not-abc'
            ret = self.driver.migrate_volume(context, self.volume_a, host)
            self.assertEqual((False, None), ret)

        mock_client().__enter__().client.get_fsid.return_value = 'not-abc'

        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            ret = self.driver.migrate_volume(context, self.volume_a, host)
            self.assertEqual((False, None), ret)

        host = {
            'capabilities': {
                'storage_protocol': 'ceph',
                'location_info': 'nondefault:None:not-abc:None:rbd'}}

        mock_client().__enter__().client.get_fsid.return_value = 'abc'

        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            ret = self.driver.migrate_volume(context, self.volume_a, host)
            self.assertEqual((False, None), ret)

    @mock.patch('os_brick.initiator.linuxrbd.rbd')
    @mock.patch('os_brick.initiator.linuxrbd.RBDClient')
    def test_migrate_volume_same_pool(self, mock_client, mock_rbd):
        host = {
            'capabilities': {
                'storage_protocol': 'ceph',
                'location_info': 'nondefault:None:abc:None:rbd'}}

        mock_client().__enter__().client.get_fsid.return_value = 'abc'

        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            ret = self.driver.migrate_volume(context, self.volume_a, host)
            self.assertEqual((True, None), ret)

    @mock.patch('os_brick.initiator.linuxrbd.rbd')
    @mock.patch('os_brick.initiator.linuxrbd.RBDClient')
    def test_migrate_volume_insue_different_pool(self, mock_client, mock_rbd):
        self.volume_a.status = 'in-use'
        host = {
            'capabilities': {
                'storage_protocol': 'ceph',
                'location_info': 'nondefault:None:abc:None:rbd2'}}

        mock_client().__enter__().client.get_fsid.return_value = 'abc'

        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid:
            mock_get_fsid.return_value = 'abc'
            ret = self.driver.migrate_volume(context, self.volume_a, host)
            self.assertEqual((False, None), ret)

    @mock.patch('os_brick.initiator.linuxrbd.rbd')
    @mock.patch('os_brick.initiator.linuxrbd.RBDClient')
    @mock.patch('cinder.volume.drivers.rbd.RBDVolumeProxy')
    def test_migrate_volume_different_pool(self, mock_proxy, mock_client,
                                           mock_rbcd):
        host = {
            'capabilities': {
                'storage_protocol': 'ceph',
                'location_info': 'nondefault:None:abc:None:rbd2'}}

        mock_client().__enter__().client.get_fsid.return_value = 'abc'

        with mock.patch.object(self.driver, '_get_fsid') as mock_get_fsid, \
                mock.patch.object(self.driver, 'delete_volume') as mock_delete:
            mock_get_fsid.return_value = 'abc'
            proxy = mock_proxy.return_value
            proxy.__enter__.return_value = proxy
            ret = self.driver.migrate_volume(context, self.volume_a,
                                             host)
            proxy.copy.assert_called_once_with(
                mock_client.return_value.__enter__.return_value.ioctx,
                self.volume_a.name)
            mock_delete.assert_called_once_with(self.volume_a)
            self.assertEqual((True, None), ret)

    @mock.patch('tempfile.NamedTemporaryFile')
    @mock.patch('cinder.volume.volume_utils.check_encryption_provider',
                return_value={'encryption_key_id': fake.ENCRYPTION_KEY_ID})
    def test_create_encrypted_volume(self,
                                     mock_check_enc_prov,
                                     mock_temp_file):
        class DictObj(object):
            # convert a dict to object w/ attributes
            def __init__(self, d):
                self.__dict__ = d

        mock_temp_file.return_value.__enter__.side_effect = [
            DictObj({'name': '/imgfile'}),
            DictObj({'name': '/passfile'})]

        key_mgr = fake_keymgr.fake_api()

        self.mock_object(castellan.key_manager, 'API', return_value=key_mgr)
        key_id = key_mgr.store(self.context, KeyObject())
        self.volume_c.encryption_key_id = key_id

        enc_info = {'encryption_key_id': key_id,
                    'cipher': 'aes-xts-essiv',
                    'key_size': 256}

        with mock.patch('cinder.volume.volume_utils.check_encryption_provider',
                        return_value=enc_info), \
                mock.patch('cinder.volume.drivers.rbd.open') as mock_open, \
                mock.patch.object(self.driver, '_execute') as mock_exec:
            self.driver._create_encrypted_volume(self.volume_c,
                                                 self.context)
            mock_open.assert_called_with('/passfile', 'w')

            mock_exec.assert_any_call(
                'qemu-img', 'create', '-f', 'luks', '-o',
                'cipher-alg=aes-256,cipher-mode=xts,ivgen-alg=essiv',
                '--object',
                'secret,id=luks_sec,format=raw,file=/passfile',
                '-o', 'key-secret=luks_sec', '/imgfile', '12288M')
            mock_exec.assert_any_call(
                'rbd', 'import', '--dest-pool', 'rbd', '--order', 22,
                '/imgfile', self.volume_c.name)

    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.db.volume_glance_metadata_get', return_value={})
    @common_mocks
    def test_get_backup_device_ceph(self, mock_gm_get, volume_get_by_id):
        # Use the same volume for backup (volume_a)
        volume_get_by_id.return_value = self.volume_a
        driver = self.driver

        self._create_backup_db_entry(fake.BACKUP_ID, self.volume_a['id'], 1)
        backup = objects.Backup.get_by_id(self.context, fake.BACKUP_ID)
        backup.service = 'cinder.backup.drivers.ceph'

        ret = driver.get_backup_device(self.context, backup)
        self.assertEqual(ret, (self.volume_a, False))

    def _create_backup_db_entry(self, backupid, volid, size,
                                userid=str(uuid.uuid4()),
                                projectid=str(uuid.uuid4())):
        backup = {'id': backupid, 'size': size, 'volume_id': volid,
                  'user_id': userid, 'project_id': projectid}
        return db.backup_create(self.context, backup)['id']

    @mock.patch('cinder.volume.driver.BaseVD._get_backup_volume_temp_snapshot')
    @mock.patch('cinder.volume.driver.BaseVD._get_backup_volume_temp_volume')
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.db.volume_glance_metadata_get', return_value={})
    @common_mocks
    def test_get_backup_device_other(self,
                                     mock_gm_get,
                                     volume_get_by_id,
                                     mock_get_temp_volume,
                                     mock_get_temp_snapshot):
        # Use a cloned volume for backup (volume_b)
        self.volume_a.previous_status = 'in-use'
        mock_get_temp_volume.return_value = self.volume_b
        mock_get_temp_snapshot.return_value = (self.volume_b, False)

        volume_get_by_id.return_value = self.volume_a
        driver = self.driver

        self._create_backup_db_entry(fake.BACKUP_ID, self.volume_a['id'], 1)
        backup = objects.Backup.get_by_id(self.context, fake.BACKUP_ID)
        backup.service = 'asdf'

        ret = driver.get_backup_device(self.context, backup)
        self.assertEqual(ret, (self.volume_b, False))

    @common_mocks
    def test_multiattach_exclusions(self):
        self.assertEqual(
            self.driver.RBD_FEATURE_JOURNALING |
            self.driver.RBD_FEATURE_FAST_DIFF |
            self.driver.RBD_FEATURE_OBJECT_MAP |
            self.driver.RBD_FEATURE_EXCLUSIVE_LOCK,
            self.driver.MULTIATTACH_EXCLUSIONS)

    MULTIATTACH_FULL_FEATURES = (
        driver.RBDDriver.RBD_FEATURE_LAYERING |
        driver.RBDDriver.RBD_FEATURE_EXCLUSIVE_LOCK |
        driver.RBDDriver.RBD_FEATURE_OBJECT_MAP |
        driver.RBDDriver.RBD_FEATURE_FAST_DIFF |
        driver.RBDDriver.RBD_FEATURE_JOURNALING)

    MULTIATTACH_REDUCED_FEATURES = (
        driver.RBDDriver.RBD_FEATURE_LAYERING |
        driver.RBDDriver.RBD_FEATURE_EXCLUSIVE_LOCK)

    @ddt.data(MULTIATTACH_FULL_FEATURES, MULTIATTACH_REDUCED_FEATURES)
    @common_mocks
    def test_enable_multiattach(self, features):
        image = self.mock_proxy.return_value.__enter__.return_value
        image_features = features
        image.features.return_value = image_features

        ret = self.driver._enable_multiattach(self.volume_a)

        image.update_features.assert_called_once_with(
            self.driver.MULTIATTACH_EXCLUSIONS & image_features, False)

        self.assertEqual(
            {'provider_location':
             "{\"saved_features\":%s}" % image_features}, ret)

    @common_mocks
    def test_enable_multiattach_no_features(self):
        image = self.mock_proxy.return_value.__enter__.return_value
        image.features.return_value = 0

        ret = self.driver._enable_multiattach(self.volume_a)

        image.update_features.assert_not_called()

        self.assertEqual({'provider_location': '{"saved_features":0}'}, ret)

    @ddt.data(MULTIATTACH_FULL_FEATURES, MULTIATTACH_REDUCED_FEATURES)
    @common_mocks
    def test_disable_multiattach(self, features):
        image = self.mock_proxy.return_value.__enter__.return_value
        self.volume_a.provider_location = '{"saved_features": %s}' % features

        ret = self.driver._disable_multiattach(self.volume_a)

        image.update_features.assert_called_once_with(
            self.driver.MULTIATTACH_EXCLUSIONS & features, True)

        self.assertEqual({'provider_location': None}, ret)

    @common_mocks
    def test_disable_multiattach_no_features(self):
        image = self.mock_proxy.return_value.__enter__.return_value
        self.volume_a.provider_location = '{"saved_features": 0}'
        image.features.return_value = 0

        ret = self.driver._disable_multiattach(self.volume_a)

        image.update_features.assert_not_called()

        self.assertEqual({'provider_location': None}, ret)


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
                with mock.patch.object(volume_utils,
                                       'copy_image_to_volume') as mock_copy:
                    self._create_volume_from_image('available', raw=True)
                    self.assertFalse(mock_copy.called)

                self.assertTrue(mock_clone_image.called)
                self.assertFalse(mock_create.called)
                self.assertTrue(mock_gdis.called)

    @mock.patch('cinder.image.image_utils.check_available_space')
    @mock.patch.object(cinder.image.glance, 'get_default_image_service')
    @mock.patch('cinder.image.image_utils.TemporaryImages.fetch')
    @mock.patch('cinder.image.image_utils.qemu_img_info')
    @mock.patch('cinder.image.image_utils.verify_glance_image_signature')
    def test_create_vol_from_non_raw_image_status_available(
            self, mock_verify, mock_qemu_info, mock_fetch, mock_gdis,
            mock_check_space):
        """Clone non-raw image then verify volume is in available state."""

        def _mock_clone_image(context, volume, image_location,
                              image_meta, image_service):
            return {'provider_location': None}, False

        image_info = imageutils.QemuImgInfo()
        image_info.virtual_size = '1073741824'
        mock_qemu_info.return_value = image_info
        self.flags(verify_glance_signatures='disabled')

        mock_fetch.return_value = mock.MagicMock(spec=utils.get_file_spec())
        with mock.patch.object(self.volume.driver, 'clone_image') as \
                mock_clone_image:
            mock_clone_image.side_effect = _mock_clone_image
            with mock.patch.object(self.volume.driver, 'create_volume') as \
                    mock_create:
                with mock.patch.object(volume_utils,
                                       'copy_image_to_volume') as mock_copy:
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
                with mock.patch.object(volume_utils,
                                       'copy_image_to_volume') as mock_copy:
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
