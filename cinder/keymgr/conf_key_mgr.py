# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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
An implementation of a key manager that reads its key from the project's
configuration options.

This key manager implementation provides limited security, assuming that the
key remains secret. Using the volume encryption feature as an example,
encryption provides protection against a lost or stolen disk, assuming that
the configuration file that contains the key is not stored on the disk.
Encryption also protects the confidentiality of data as it is transmitted via
iSCSI from the compute host to the storage host (again assuming that an
attacker who intercepts the data does not know the secret key).

Because this implementation uses a single, fixed key, it proffers no
protection once that key is compromised. In particular, different volumes
encrypted with a key provided by this key manager actually share the same
encryption key so *any* volume can be decrypted once the fixed key is known.
"""

import array

from oslo.config import cfg

from cinder import exception
from cinder.i18n import _
from cinder.keymgr import key
from cinder.keymgr import key_mgr
from cinder.openstack.common import log as logging


key_mgr_opts = [
    cfg.StrOpt('fixed_key',
               help='Fixed key returned by key manager, specified in hex'),
]

CONF = cfg.CONF
CONF.register_opts(key_mgr_opts, group='keymgr')


LOG = logging.getLogger(__name__)


class ConfKeyManager(key_mgr.KeyManager):
    """Key Manager that supports one key defined by the fixed_key conf option.

    This key manager implementation supports all the methods specified by the
    key manager interface. This implementation creates a single key in response
    to all invocations of create_key. Side effects (e.g., raising exceptions)
    for each method are handled as specified by the key manager interface.
    """

    def __init__(self):
        super(ConfKeyManager, self).__init__()

        self.key_id = '00000000-0000-0000-0000-000000000000'

    def _generate_key(self, **kwargs):
        _hex = self._generate_hex_key(**kwargs)
        return key.SymmetricKey('AES',
                                array.array('B', _hex.decode('hex')).tolist())

    def _generate_hex_key(self, **kwargs):
        if CONF.keymgr.fixed_key is None:
            LOG.warn(_('config option keymgr.fixed_key has not been defined: '
                       'some operations may fail unexpectedly'))
            raise ValueError(_('keymgr.fixed_key not defined'))
        return CONF.keymgr.fixed_key

    def create_key(self, ctxt, **kwargs):
        """Creates a key.

        This implementation returns a UUID for the created key. A
        NotAuthorized exception is raised if the specified context is None.
        """
        if ctxt is None:
            raise exception.NotAuthorized()

        return self.key_id

    def store_key(self, ctxt, key, **kwargs):
        """Stores (i.e., registers) a key with the key manager."""
        if ctxt is None:
            raise exception.NotAuthorized()

        if key != self._generate_key():
            raise exception.KeyManagerError(
                reason="cannot store arbitrary keys")

        return self.key_id

    def copy_key(self, ctxt, key_id, **kwargs):
        if ctxt is None:
            raise exception.NotAuthorized()

        return self.key_id

    def get_key(self, ctxt, key_id, **kwargs):
        """Retrieves the key identified by the specified id.

        This implementation returns the key that is associated with the
        specified UUID. A NotAuthorized exception is raised if the specified
        context is None; a KeyError is raised if the UUID is invalid.
        """
        if ctxt is None:
            raise exception.NotAuthorized()

        if key_id != self.key_id:
            raise KeyError(key_id)

        return self._generate_key()

    def delete_key(self, ctxt, key_id, **kwargs):
        if ctxt is None:
            raise exception.NotAuthorized()

        if key_id != self.key_id:
            raise exception.KeyManagerError(
                reason="cannot delete non-existent key")

        LOG.warn(_("Not deleting key %s"), key_id)
