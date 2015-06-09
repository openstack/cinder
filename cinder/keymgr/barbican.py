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
Key manager implementation for Barbican
"""

import array
import base64
import binascii

from barbicanclient import client as barbican_client
from keystoneclient.auth import identity
from keystoneclient import session
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from cinder import exception
from cinder.i18n import _, _LE
from cinder.keymgr import key as keymgr_key
from cinder.keymgr import key_mgr

CONF = cfg.CONF
CONF.import_opt('encryption_auth_url', 'cinder.keymgr.key_mgr', group='keymgr')
CONF.import_opt('encryption_api_url', 'cinder.keymgr.key_mgr', group='keymgr')
LOG = logging.getLogger(__name__)


class BarbicanKeyManager(key_mgr.KeyManager):
    """Key Manager Interface that wraps the Barbican client API."""

    def __init__(self):
        self._base_url = CONF.keymgr.encryption_api_url
        # the barbican endpoint can't have the '/v1' on the end
        self._barbican_endpoint = self._base_url.rpartition('/')[0]
        self._barbican_client = None

    def _get_barbican_client(self, ctxt):
        """Creates a client to connect to the Barbican service.

        :param ctxt: the user context for authentication
        :return: a Barbican Client object
        :throws NotAuthorized: if the ctxt is None
        :throws KeyManagerError: if ctxt is missing project_id
                                 or project_id is None
        """

        if not self._barbican_client:
            # Confirm context is provided, if not raise not authorized
            if not ctxt:
                msg = _("User is not authorized to use key manager.")
                LOG.error(msg)
                raise exception.NotAuthorized(msg)

            if not hasattr(ctxt, 'project_id') or ctxt.project_id is None:
                msg = _("Unable to create Barbican Client without project_id.")
                LOG.error(msg)
                raise exception.KeyManagerError(msg)

            try:
                auth = identity.v3.Token(
                    auth_url=CONF.keymgr.encryption_auth_url,
                    token=ctxt.auth_token,
                    project_id=ctxt.project_id)
                sess = session.Session(auth=auth)
                self._barbican_client = barbican_client.Client(
                    session=sess,
                    endpoint=self._barbican_endpoint)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_LE("Error creating Barbican client."))

        return self._barbican_client

    def create_key(self, ctxt, expiration=None, name='Cinder Volume Key',
                   payload_content_type='application/octet-stream', mode='CBC',
                   algorithm='AES', length=256):
        """Creates a key.

        :param ctxt: contains information of the user and the environment
                     for the request (cinder/context.py)
        :param expiration: the date the key will expire
        :param name: a friendly name for the secret
        :param payload_content_type: the format/type of the secret data
        :param mode: the algorithm mode (e.g. CBC or CTR mode)
        :param algorithm: the algorithm associated with the secret
        :param length: the bit length of the secret

        :return: the UUID of the new key
        :throws Exception: if key creation fails
        """
        barbican_client = self._get_barbican_client(ctxt)

        try:
            key_order = barbican_client.orders.create_key(
                name,
                algorithm,
                length,
                mode,
                payload_content_type,
                expiration)
            order_ref = key_order.submit()
            order = barbican_client.orders.get(order_ref)
            secret_uuid = order.secret_ref.rpartition('/')[2]
            return secret_uuid
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error creating key."))

    def store_key(self, ctxt, key, expiration=None, name='Cinder Volume Key',
                  payload_content_type='application/octet-stream',
                  payload_content_encoding='base64', algorithm='AES',
                  bit_length=256, mode='CBC', from_copy=False):
        """Stores (i.e., registers) a key with the key manager.

        :param ctxt: contains information of the user and the environment for
                     the request (cinder/context.py)
        :param key: the unencrypted secret data. Known as "payload" to the
                    barbicanclient api
        :param expiration: the expiration time of the secret in ISO 8601
                           format
        :param name: a friendly name for the key
        :param payload_content_type: the format/type of the secret data
        :param payload_content_encoding: the encoding of the secret data
        :param algorithm: the algorithm associated with this secret key
        :param bit_length: the bit length of this secret key
        :param mode: the algorithm mode used with this secret key
        :param from_copy: establishes whether the function is being used
                    to copy a key. In case of the latter, it does not
                    try to decode the key

        :returns: the UUID of the stored key
        :throws Exception: if key storage fails
        """
        barbican_client = self._get_barbican_client(ctxt)

        try:
            if key.get_algorithm():
                algorithm = key.get_algorithm()
            if payload_content_type == 'text/plain':
                payload_content_encoding = None
                encoded_key = key.get_encoded()
            elif (payload_content_type == 'application/octet-stream' and
                  not from_copy):
                key_list = key.get_encoded()
                string_key = ''.join(map(lambda byte: "%02x" % byte, key_list))
                encoded_key = base64.b64encode(binascii.unhexlify(string_key))
            else:
                encoded_key = key.get_encoded()
            secret = barbican_client.secrets.create(name,
                                                    encoded_key,
                                                    payload_content_type,
                                                    payload_content_encoding,
                                                    algorithm,
                                                    bit_length,
                                                    mode,
                                                    expiration)
            secret_ref = secret.store()
            secret_uuid = secret_ref.rpartition('/')[2]
            return secret_uuid
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error storing key."))

    def copy_key(self, ctxt, key_id):
        """Copies (i.e., clones) a key stored by barbican.

        :param ctxt: contains information of the user and the environment for
                     the request (cinder/context.py)
        :param key_id: the UUID of the key to copy
        :return: the UUID of the key copy
        :throws Exception: if key copying fails
        """
        barbican_client = self._get_barbican_client(ctxt)

        try:
            secret_ref = self._create_secret_ref(key_id, barbican_client)
            secret = self._get_secret(ctxt, secret_ref)
            con_type = secret.content_types['default']
            secret_data = self._get_secret_data(secret,
                                                payload_content_type=con_type)
            key = keymgr_key.SymmetricKey(secret.algorithm, secret_data)
            copy_uuid = self.store_key(ctxt, key, secret.expiration,
                                       secret.name, con_type,
                                       'base64',
                                       secret.algorithm, secret.bit_length,
                                       secret.mode, True)
            return copy_uuid
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error copying key."))

    def _create_secret_ref(self, key_id, barbican_client):
        """Creates the URL required for accessing a secret.

        :param key_id: the UUID of the key to copy
        :param barbican_client: barbican key manager object

        :return: the URL of the requested secret
        """
        if not key_id:
            msg = "Key ID is None"
            raise exception.KeyManagerError(msg)
        return self._base_url + "/secrets/" + key_id

    def _get_secret_data(self,
                         secret,
                         payload_content_type='application/octet-stream'):
        """Retrieves the secret data given a secret_ref and content_type.

        :param ctxt: contains information of the user and the environment for
                     the request (cinder/context.py)
        :param secret_ref: URL to access the secret
        :param payload_content_type: the format/type of the secret data

        :returns: the secret data
        :throws Exception: if data cannot be retrieved
        """
        try:
            generated_data = secret.payload
            if payload_content_type == 'application/octet-stream':
                secret_data = base64.b64encode(generated_data)
            else:
                secret_data = generated_data
            return secret_data
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error getting secret data."))

    def _get_secret(self, ctxt, secret_ref):
        """Creates the URL required for accessing a secret's metadata.

        :param ctxt: contains information of the user and the environment for
                     the request (cinder/context.py)
        :param secret_ref: URL to access the secret

        :return: the secret's metadata
        :throws Exception: if there is an error retrieving the data
        """

        barbican_client = self._get_barbican_client(ctxt)

        try:
            return barbican_client.secrets.get(secret_ref)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error getting secret metadata."))

    def get_key(self, ctxt, key_id,
                payload_content_type='application/octet-stream'):
        """Retrieves the specified key.

        :param ctxt: contains information of the user and the environment for
                     the request (cinder/context.py)
        :param key_id: the UUID of the key to retrieve
        :param payload_content_type: The format/type of the secret data

        :return: SymmetricKey representation of the key
        :throws Exception: if key retrieval fails
        """
        try:
            secret_ref = self._create_secret_ref(key_id, barbican_client)
            secret = self._get_secret(ctxt, secret_ref)
            secret_data = self._get_secret_data(secret,
                                                payload_content_type)
            if payload_content_type == 'application/octet-stream':
                # convert decoded string to list of unsigned ints for each byte
                key_data = array.array('B',
                                       base64.b64decode(secret_data)).tolist()
            else:
                key_data = secret_data
            key = keymgr_key.SymmetricKey(secret.algorithm, key_data)
            return key
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error getting key."))

    def delete_key(self, ctxt, key_id):
        """Deletes the specified key.

        :param ctxt: contains information of the user and the environment for
                     the request (cinder/context.py)
        :param key_id: the UUID of the key to delete
        :throws Exception: if key deletion fails
        """
        barbican_client = self._get_barbican_client(ctxt)

        try:
            secret_ref = self._create_secret_ref(key_id, barbican_client)
            barbican_client.secrets.delete(secret_ref)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error deleting key."))
