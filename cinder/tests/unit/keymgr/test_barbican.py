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

import mock
from oslo_config import cfg

from cinder import exception
from cinder.keymgr import barbican
from cinder.keymgr import key as keymgr_key
from cinder.tests.unit.keymgr import test_key_mgr

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
        self.ctxt.project_id = "fake_project_id"

        # Create mock barbican client
        self._build_mock_barbican()

        # Create a key_id, secret_ref, pre_hex, and hex to use
        self.key_id = "d152fa13-2b41-42ca-a934-6c21566c0f40"
        self.secret_ref = self.key_mgr._create_secret_ref(self.key_id,
                                                          self.mock_barbican)
        self.pre_hex = "AIDxQp2++uAbKaTVDMXFYIu8PIugJGqkK0JLqkU0rhY="
        self.hex = ("0080f1429dbefae01b29a4d50cc5c5608bbc3c8ba0246aa42b424baa4"
                    "534ae16")
        self.original_api_url = CONF.keymgr.encryption_api_url
        self.addCleanup(self._restore)

    def _restore(self):
        if hasattr(self, 'original_key'):
            keymgr_key.SymmetricKey = self.original_key
        if hasattr(self, 'original_base64'):
            base64.b64encode = self.original_base64
        if hasattr(self, 'original_api_url'):
            CONF.keymgr.encryption_api_url = self.original_api_url

    def _build_mock_barbican(self):
        self.mock_barbican = mock.MagicMock(name='mock_barbican')

        # Set commonly used methods
        self.get = self.mock_barbican.secrets.get
        self.delete = self.mock_barbican.secrets.delete
        self.store = self.mock_barbican.secrets.store
        self.create = self.mock_barbican.secrets.create

        self.key_mgr._barbican_client = self.mock_barbican

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
        original_secret_data = mock.Mock()
        original_secret_metadata.payload = original_secret_data
        self.get.return_value = original_secret_metadata

        # Create the mock key
        self._build_mock_symKey()

        # Copy the original
        self.key_mgr.copy_key(self.ctxt, self.key_id)

        # Assert proper methods were called
        self.get.assert_called_once_with(self.secret_ref)
        self.create.assert_called_once_with(
            original_secret_metadata.name,
            self.mock_symKey.get_encoded(),
            content_types['default'],
            'base64',
            original_secret_metadata.algorithm,
            original_secret_metadata.bit_length,
            original_secret_metadata.mode,
            original_secret_metadata.expiration)
        self.create.return_value.store.assert_called_once_with()

    def test_copy_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.copy_key, None, self.key_id)

    def test_create_key(self):
        # Create order_ref_url and assign return value
        order_ref_url = ("http://localhost:9311/v1/None/orders/"
                         "4fe939b7-72bc-49aa-bd1e-e979589858af")
        key_order = mock.Mock()
        self.mock_barbican.orders.create_key.return_value = key_order
        key_order.submit.return_value = order_ref_url

        # Create order and assign return value
        order = mock.Mock()
        order.secret_ref = self.secret_ref
        self.mock_barbican.orders.get.return_value = order

        # Create the key, get the UUID
        returned_uuid = self.key_mgr.create_key(self.ctxt)

        self.mock_barbican.orders.get.assert_called_once_with(order_ref_url)
        self.assertEqual(self.key_id, returned_uuid)

    def test_create_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.create_key, None)

    def test_delete_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.delete_key, None, self.key_id)

    def test_delete_key(self):
        self.key_mgr.delete_key(self.ctxt, self.key_id)
        self.delete.assert_called_once_with(self.secret_ref)

    def test_delete_unknown_key(self):
        self.assertRaises(exception.KeyManagerError,
                          self.key_mgr.delete_key, self.ctxt, None)

    def test_get_key(self):
        self._build_mock_base64()
        content_type = 'application/octet-stream'

        key = self.key_mgr.get_key(self.ctxt, self.key_id, content_type)

        self.get.assert_called_once_with(self.secret_ref)
        encoded = array.array('B', binascii.unhexlify(self.hex)).tolist()
        self.assertEqual(encoded, key.get_encoded())

    def test_get_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.get_key, None, self.key_id)

    def test_get_unknown_key(self):
        self.assertRaises(exception.KeyManagerError,
                          self.key_mgr.get_key, self.ctxt, None)

    def test_store_key_base64(self):
        # Create Key to store
        secret_key = array.array('B', [0x01, 0x02, 0xA0, 0xB3]).tolist()
        _key = keymgr_key.SymmetricKey('AES', secret_key)

        # Define the return values
        secret = mock.Mock()
        self.create.return_value = secret
        secret.store.return_value = self.secret_ref

        # Store the Key
        returned_uuid = self.key_mgr.store_key(self.ctxt, _key, bit_length=32)

        self.create.assert_called_once_with('Cinder Volume Key',
                                            'AQKgsw==',
                                            'application/octet-stream',
                                            'base64',
                                            'AES', 32, 'CBC',
                                            None)
        self.assertEqual(self.key_id, returned_uuid)

    def test_store_key_plaintext(self):
        # Create the plaintext key
        secret_key_text = "This is a test text key."
        _key = keymgr_key.SymmetricKey('AES', secret_key_text)

        # Store the Key
        self.key_mgr.store_key(self.ctxt, _key,
                               payload_content_type='text/plain',
                               payload_content_encoding=None)
        self.create.assert_called_once_with('Cinder Volume Key',
                                            secret_key_text,
                                            'text/plain',
                                            None,
                                            'AES', 256, 'CBC',
                                            None)
        self.create.return_value.store.assert_called_once_with()

    def test_store_null_context(self):
        self.key_mgr._barbican_client = None
        self.assertRaises(exception.NotAuthorized,
                          self.key_mgr.store_key, None, None)

    def test_null_project_id(self):
        self.key_mgr._barbican_client = None
        self.ctxt.project_id = None
        self.assertRaises(exception.KeyManagerError,
                          self.key_mgr.create_key, self.ctxt)

    def test_ctxt_without_project_id(self):
        self.key_mgr._barbican_client = None
        del self.ctxt.project_id
        self.assertRaises(exception.KeyManagerError,
                          self.key_mgr.create_key, self.ctxt)

    @mock.patch('cinder.keymgr.barbican.identity.v3.Token')
    @mock.patch('cinder.keymgr.barbican.session.Session')
    @mock.patch('cinder.keymgr.barbican.barbican_client.Client')
    def test_ctxt_with_project_id(self, mock_client, mock_session,
                                  mock_token):
        # set client to None so that client creation will occur
        self.key_mgr._barbican_client = None

        # mock the return values
        mock_auth = mock.Mock()
        mock_token.return_value = mock_auth
        mock_sess = mock.Mock()
        mock_session.return_value = mock_sess

        # mock the endpoint
        mock_endpoint = mock.Mock()
        self.key_mgr._barbican_endpoint = mock_endpoint

        self.key_mgr.create_key(self.ctxt)

        # assert proper calls occurred, including with project_id
        mock_token.assert_called_once_with(
            auth_url=CONF.keymgr.encryption_auth_url,
            token=self.ctxt.auth_token,
            project_id=self.ctxt.project_id)
        mock_session.assert_called_once_with(auth=mock_auth)
        mock_client.assert_called_once_with(session=mock_sess,
                                            endpoint=mock_endpoint)

    def test_parse_barbican_api_url(self):
        # assert that the correct format is handled correctly
        CONF.keymgr.encryption_api_url = "http://host:port/v1/"
        dummy = barbican.BarbicanKeyManager()
        self.assertEqual(dummy._barbican_endpoint, "http://host:port")

        # assert that invalid api url formats will raise an exception
        CONF.keymgr.encryption_api_url = "http://host:port/"
        self.assertRaises(exception.KeyManagerError,
                          barbican.BarbicanKeyManager)
        CONF.keymgr.encryption_api_url = "http://host:port/secrets"
        self.assertRaises(exception.KeyManagerError,
                          barbican.BarbicanKeyManager)
