# Copyright 2022 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Tests for encryption key transfer."""

from unittest import mock

from castellan.common.credentials import keystone_password
from oslo_config import cfg

from cinder.common import constants
from cinder import context
from cinder.keymgr import conf_key_mgr
from cinder.keymgr import transfer
from cinder import objects
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils

CONF = cfg.CONF

ENCRYPTION_SECRET = 'the_secret'
CINDER_USERNAME = 'cinder'
CINDER_PASSWORD = 'key_transfer_test'


class KeyTransferTestCase(test.TestCase):
    OLD_ENCRYPTION_KEY_ID = fake.ENCRYPTION_KEY_ID
    NEW_ENCRYPTION_KEY_ID = fake.ENCRYPTION_KEY2_ID

    key_manager_class = ('castellan.key_manager.barbican_key_manager.'
                         'BarbicanKeyManager')

    def setUp(self):
        super(KeyTransferTestCase, self).setUp()
        self.conf = CONF
        self.conf.set_override('backend',
                               self.key_manager_class,
                               group='key_manager')
        self.conf.set_override('username',
                               CINDER_USERNAME,
                               group='keystone_authtoken')
        self.conf.set_override('password',
                               CINDER_PASSWORD,
                               group='keystone_authtoken')

        self.context = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)

    def _create_volume_and_snapshots(self):
        volume = test_utils.create_volume(
            self.context,
            testcase_instance=self,
            encryption_key_id=self.OLD_ENCRYPTION_KEY_ID)

        _ = test_utils.create_snapshot(
            self.context,
            volume.id,
            display_name='snap_1',
            testcase_instance=self,
            encryption_key_id=self.OLD_ENCRYPTION_KEY_ID)

        _ = test_utils.create_snapshot(
            self.context,
            volume.id,
            display_name='snap_2',
            testcase_instance=self,
            encryption_key_id=self.OLD_ENCRYPTION_KEY_ID)

        return volume

    def _verify_service_context(self, mocked_call):
        service_context = mocked_call.call_args.args[0]
        self.assertIsInstance(service_context,
                              keystone_password.KeystonePassword)
        self.assertEqual(service_context.username, CINDER_USERNAME)
        self.assertEqual(service_context.password, CINDER_PASSWORD)

    def _verify_encryption_key_id(self, volume_id, encryption_key_id):
        volume = objects.Volume.get_by_id(self.context, volume_id)
        self.assertEqual(volume.encryption_key_id, encryption_key_id)

        snapshots = objects.snapshot.SnapshotList.get_all_for_volume(
            self.context, volume.id)
        self.assertEqual(len(snapshots), 2)
        for snapshot in snapshots:
            self.assertEqual(snapshot.encryption_key_id, encryption_key_id)

    def _test_transfer_from_user_to_cinder(self, transfer_fn):
        volume = self._create_volume_and_snapshots()
        with mock.patch(
                self.key_manager_class + '.get',
                return_value=ENCRYPTION_SECRET) as mock_key_get, \
            mock.patch(
                self.key_manager_class + '.store',
                return_value=self.NEW_ENCRYPTION_KEY_ID) as mock_key_store, \
            mock.patch(
                self.key_manager_class + '.delete') as mock_key_delete:

            transfer_fn(self.context, volume)

            # Verify the user's context was used to fetch and delete the
            # volume's current key ID.
            mock_key_get.assert_called_once_with(
                self.context, self.OLD_ENCRYPTION_KEY_ID)
            mock_key_delete.assert_called_once_with(
                self.context, self.OLD_ENCRYPTION_KEY_ID)

            # Verify the cinder service created the new key ID.
            mock_key_store.assert_called_once_with(
                mock.ANY, ENCRYPTION_SECRET)
            self._verify_service_context(mock_key_store)

        # Verify the volume (and its snaps) reference the new key ID.
        self._verify_encryption_key_id(volume.id, self.NEW_ENCRYPTION_KEY_ID)

    def _test_transfer_from_cinder_to_user(self, transfer_fn):
        volume = self._create_volume_and_snapshots()
        with mock.patch(
                self.key_manager_class + '.get',
                return_value=ENCRYPTION_SECRET) as mock_key_get, \
            mock.patch(
                self.key_manager_class + '.store',
                return_value=self.NEW_ENCRYPTION_KEY_ID) as mock_key_store, \
            mock.patch(
                self.key_manager_class + '.delete') as mock_key_delete:

            transfer_fn(self.context, volume)

            # Verify the cinder service was used to fetch and delete the
            # volume's current key ID.
            mock_key_get.assert_called_once_with(
                mock.ANY, self.OLD_ENCRYPTION_KEY_ID)
            self._verify_service_context(mock_key_get)

            mock_key_delete.assert_called_once_with(
                mock.ANY, self.OLD_ENCRYPTION_KEY_ID)
            self._verify_service_context(mock_key_delete)

            # Verify the user's context created the new key ID.
            mock_key_store.assert_called_once_with(
                self.context, ENCRYPTION_SECRET)

        # Verify the volume (and its snaps) reference the new key ID.
        self._verify_encryption_key_id(volume.id, self.NEW_ENCRYPTION_KEY_ID)

    def test_transfer_create(self):
        self._test_transfer_from_user_to_cinder(transfer.transfer_create)

    def test_transfer_accept(self):
        self._test_transfer_from_cinder_to_user(transfer.transfer_accept)

    def test_transfer_delete(self):
        self._test_transfer_from_cinder_to_user(transfer.transfer_delete)


class KeyTransferFixedKeyTestCase(KeyTransferTestCase):
    OLD_ENCRYPTION_KEY_ID = constants.FIXED_KEY_ID
    NEW_ENCRYPTION_KEY_ID = constants.FIXED_KEY_ID

    key_manager_class = 'cinder.keymgr.conf_key_mgr.ConfKeyManager'

    def setUp(self):
        super(KeyTransferFixedKeyTestCase, self).setUp()
        self.conf.register_opts(conf_key_mgr.key_mgr_opts, group='key_manager')
        self.conf.set_override('fixed_key',
                               'df393fca58657e6dc76a6fea31c3e7e0',
                               group='key_manager')
