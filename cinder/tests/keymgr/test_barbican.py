# Copyright (c) 2014 The Johns Hopkins University/Applied Physics Laboratory
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
Test cases for the barbican key manager.
"""

import array
import base64
import binascii

from barbicanclient import client as barbican_client
from barbicanclient.common import auth
from keystoneclient.v2_0 import client as keystone_client
import mock
from oslo.config import cfg

from cinder import exception
from cinder.keymgr import barbican
from cinder.keymgr import key as keymgr_key
from cinder.tests.keymgr import test_key_mgr

CONF = cfg.CONF
CONF.import_opt('encryption_auth_url', 'cinder.keymgr.key_mgr', group='keymgr')
CONF.import_opt('encryption_api_url', 'cinder.keymgr.key_mgr', group='keymgr')


class BarbicanKeyManagerTestCase(test_key_mgr.KeyManagerTestCase):

    def _create_key_manager(self):
        return barbican.BarbicanKeyManager()

    def setUp(self):
        super(BarbicanKeyManagerTestCase, self).setUp()

        # Create fake auth_token
        self.ctxt = mock.Mock()
        self.ctxt.auth_token = "fake_token"

        # Create mock keystone auth
        self._build_mock_auth()

        # Create mock barbican client
        self._build_mock_barbican()

        # Create mock keystone client
        self._build_mock_keystone()

        # Create a key_id, secret_ref, pre_hex, and hex to use
        self.key_id = "d152fa13-2b41-42ca-a934-6c21566c0f40"
        self.secret_ref = self.key_mgr._create_secret_ref(self.key_id,
                                                          self.mock_barbican)
        self.pre_hex = "AIDxQp2++uAbKaTVDMXFYIu8PIugJGqkK0JLqkU0rhY="
        self.hex = ("0080f1429dbefae01b29a4d50cc5c5608bbc3c8ba0246aa42b424baa4"
                    "534ae16")
        self.addCleanup(self._restore)

    def _restore(self):
        auth.KeystoneAuthV2 = self.original_auth
        barbican_client.Client = self.original_barbican
        keystone_client.Client = self.original_keystone
        if hasattr(self, 'original_key'):
            keymgr_key.SymmetricKey = self.original_key
        if hasattr(self, 'original_base64'):
            base64.b64encode = self.original_base64

    def _build_mock_auth(self):
        self.mock_auth = mock.Mock()

        def fake_keystone_auth(keystone):
            return self.mock_auth
        self.original_auth = auth.KeystoneAuthV2
        auth.KeystoneAuthV2 = fake_keystone_auth

    def _build_mock_barbican(self):
        self.mock_barbican = mock.MagicMock(name='mock_barbican')
        self.mock_barbican.base_url = "http://localhost:9311/v1/None"

        # Set commonly used methods
        self.get = self.mock_barbican.secrets.get
        self.decrypt = self.mock_barbican.secrets.decrypt
        self.delete = self.mock_barbican.secrets.delete
        self.store = self.mock_barbican.secrets.store

        def fake_barbican_client(auth_plugin):
            return self.mock_barbican
        self.original_barbican = barbican_client.Client
        barbican_client.Client = fake_barbican_client

    def _build_mock_keystone(self):
        self.mock_keystone = mock.Mock()

        def fake_keystone_client(token, endpoint):
            self.barbican_auth_endpoint = endpoint
            return self.mock_keystone
        self.original_keystone = keystone_client.Client
        keystone_client.Client = fake_keystone_client

    def _build_mock_symKey(self):
        self.mock_symKey = mock.Mock()

        def fake_sym_key(alg, key):
            self.mock_symKey.get_encoded.return_value = key
            self.mock_symKey.get_algorithm.return_value = alg
            return self.mock_symKey
        self.original_key = keymgr_key.SymmetricKey
        keymgr_key.SymmetricKey = fake_sym_key

    def _build_mock_base64(self):

        def fake_base64_b64encode(string):
            return self.pre_hex

        self.original_base64 = base64.b64encode
        base64.b64encode = fake_base64_b64encode

    def test_conf_urls(self):
        # Create a Key
        self.key_mgr.create_key(self.ctxt)

        # Confirm proper URL's were used
        self.assertEqual(self.barbican_auth_endpoint,
                         CONF.keymgr.encryption_auth_url)
        self.assertEqual(self.mock_auth._barbican_url,
                         CONF.keymgr.encryption_api_url)

    def test_copy_key(self):
        # Create metadata for original secret
        original_secret_metadata = mock.Mock()
        original_secret_metadata.algorithm = 'fake_algorithm'
        original_secret_metadata.bit_length = 'fake_bit_length'
        original_secret_metadata.name = 'original_name'
        original_secret_metadata.expiration = 'fake_expiration'
        original_secret_metadata.mode = 'fake_mode'
        content_types = {'default': 'fake_type'}
        original_secret_metadata.content_types = content_types
        self.get.return_value = original_secret_metadata

        # Create data for original secret
        original_secret_data = mock.Mock()
        self.decrypt.return_value = original_secret_data

        # Create the mock key
        self._build_mock_symKey()

        # Copy the original
        self.key_mgr.copy_key(self.ctxt, self.key_id)

        # Assert proper methods were called
        self.get.assert_called_once_with(self.secret_ref)
        self.decrypt.assert_called_once_with(self.secret_ref,
                                             content_types['default'])
        self.store.assert_called_once_with(original_secret_metadata.name,
                                           self.mock_symKey.get_encoded(),
                                           content_types['default'],
                                           'base64',
                                           original_secret_metadata.algorithm,
                                           original_secret_metadata.bit_length,
                                           original_secret_metadata.mode,
                                           original_secret_metadata.expiration)

    def test_copy_null_context(self):
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.copy_key, None, None)

    def test_create_key(self):
        # Create order_ref_url and assign return value
        order_ref_url = ("http://localhost:9311/v1/None/orders/"
                         "4fe939b7-72bc-49aa-bd1e-e979589858af")
        self.mock_barbican.orders.create.return_value = order_ref_url

        # Create order and assign return value
        order = mock.Mock()
        order.secret_ref = self.secret_ref
        self.mock_barbican.orders.get.return_value = order

        # Create the key, get the UUID
        returned_uuid = self.key_mgr.create_key(self.ctxt)

        self.mock_barbican.orders.get.assert_called_once_with(order_ref_url)
        self.assertEqual(returned_uuid, self.key_id)

    def test_create_null_context(self):
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.create_key, None)

    def test_delete_null_context(self):
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.delete_key, None, None)

    def test_delete_key(self):
        self.key_mgr.delete_key(self.ctxt, self.key_id)
        self.delete.assert_called_once_with(self.secret_ref)

    def test_delete_unknown_key(self):
        self.assertRaises(TypeError, self.key_mgr.delete_key, self.ctxt, None)

    def test_get_key(self):
        self._build_mock_base64()
        content_type = 'application/octet-stream'

        key = self.key_mgr.get_key(self.ctxt, self.key_id, content_type)

        self.decrypt.assert_called_once_with(self.secret_ref,
                                             content_type)
        encoded = array.array('B', binascii.unhexlify(self.hex)).tolist()
        self.assertEqual(key.get_encoded(), encoded)

    def test_get_null_context(self):
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.get_key, None, None)

    def test_get_unknown_key(self):
        self.assertRaises(TypeError, self.key_mgr.get_key, self.ctxt, None)

    def test_store_key_base64(self):
        # Create Key to store
        secret_key = array.array('B', [0x01, 0x02, 0xA0, 0xB3]).tolist()
        _key = keymgr_key.SymmetricKey('AES', secret_key)

        # Define the return value
        self.store.return_value = self.secret_ref

        # Store the Key
        returned_uuid = self.key_mgr.store_key(self.ctxt, _key, bit_length=32)

        self.store.assert_called_once_with('Cinder Volume Key',
                                           'AQKgsw==',
                                           'application/octet-stream',
                                           'base64',
                                           'AES', 32, 'CBC',
                                           None)
        self.assertEqual(returned_uuid, self.key_id)

    def test_store_key_plaintext(self):
        # Create the plaintext key
        secret_key_text = "This is a test text key."
        _key = keymgr_key.SymmetricKey('AES', secret_key_text)

        # Store the Key
        self.key_mgr.store_key(self.ctxt, _key,
                               payload_content_type='text/plain',
                               payload_content_encoding=None)
        self.store.assert_called_once_with('Cinder Volume Key',
                                           secret_key_text,
                                           'text/plain',
                                           None,
                                           'AES', 256, 'CBC',
                                           None)

    def test_store_null_context(self):
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.store_key, None, None)
