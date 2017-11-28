# Copyright 2017 Red Hat, Inc.
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

import binascii

from oslo_config import cfg
from oslo_log import log as logging

from barbicanclient import client as barbican_client
from castellan import options as castellan_options
from keystoneauth1 import loading as ks_loading
from keystoneauth1 import session as ks_session

from cinder import context
from cinder import coordination
from cinder import objects

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

MAX_KEY_MIGRATION_ERRORS = 3


class KeyMigrator(object):
    def __init__(self, conf):
        self.conf = conf
        self.admin_context = context.get_admin_context()
        self.fixed_key_id = '00000000-0000-0000-0000-000000000000'
        self.fixed_key_bytes = None
        self.fixed_key_length = None

    def handle_key_migration(self, volumes):
        castellan_options.set_defaults(self.conf)
        self.conf.import_opt(name='fixed_key',
                             module_str='cinder.keymgr.conf_key_mgr',
                             group='key_manager')
        fixed_key = self.conf.key_manager.fixed_key
        backend = self.conf.key_manager.backend or ''

        backend = backend.split('.')[-1]

        if backend == 'ConfKeyManager':
            LOG.info("Not migrating encryption keys because the "
                     "ConfKeyManager is still in use.")
        elif not fixed_key:
            LOG.info("Not migrating encryption keys because the "
                     "ConfKeyManager's fixed_key is not in use.")
        elif backend != 'barbican' and backend != 'BarbicanKeyManager':
            # Note: There are two ways of specifying the Barbican backend.
            # The long-hand method contains the "BarbicanKeyManager" class
            # name, and the short-hand method is just "barbican" with no
            # module path prefix.
            LOG.warning("Not migrating encryption keys because migration to "
                        "the '%s' key_manager backend is not supported.",
                        backend)
            self._log_migration_status()
        elif not volumes:
            LOG.info("Not migrating encryption keys because there are no "
                     "volumes associated with this host.")
            self._log_migration_status()
        else:
            self.fixed_key_bytes = bytes(binascii.unhexlify(fixed_key))
            self.fixed_key_length = len(self.fixed_key_bytes) * 8
            self._migrate_keys(volumes)
            self._log_migration_status()

    def _migrate_keys(self, volumes):
        LOG.info("Starting migration of ConfKeyManager keys.")

        # Establish a Barbican client session that will be used for the entire
        # key migration process. Use cinder's own service credentials.
        try:
            ks_loading.register_auth_conf_options(self.conf,
                                                  'keystone_authtoken')
            auth = ks_loading.load_auth_from_conf_options(self.conf,
                                                          'keystone_authtoken')
            sess = ks_session.Session(auth=auth)
            self.barbican = barbican_client.Client(session=sess)
        except Exception as e:
            LOG.error("Aborting encryption key migration due to "
                      "error creating Barbican client: %s", e)
            return

        errors = 0
        for volume in volumes:
            try:
                self._migrate_volume_key(volume)
            except Exception as e:
                LOG.error("Error migrating encryption key: %s", e)
                # NOTE(abishop): There really shouldn't be any soft errors, so
                # if an error occurs migrating one key then chances are they
                # will all fail. This avoids filling the log with the same
                # error in situations where there are many keys to migrate.
                errors += 1
                if errors > MAX_KEY_MIGRATION_ERRORS:
                    LOG.error("Aborting encryption key migration "
                              "(too many errors).")
                    break

    @coordination.synchronized('{volume.id}-{f_name}')
    def _migrate_volume_key(self, volume):
        if volume.encryption_key_id == self.fixed_key_id:
            self._update_encryption_key_id(volume)

    def _update_encryption_key_id(self, volume):
        LOG.info("Migrating volume %s encryption key to Barbican", volume.id)

        # Create a Barbican secret using the same fixed_key algorithm.
        secret = self.barbican.secrets.create(algorithm='AES',
                                              bit_length=self.fixed_key_length,
                                              secret_type='symmetric',
                                              mode=None,
                                              payload=self.fixed_key_bytes)
        secret_ref = secret.store()

        # Create a Barbican ACL so the volume's user can access the secret.
        acl = self.barbican.acls.create(entity_ref=secret_ref,
                                        users=[volume.user_id])
        acl.submit()

        _, _, encryption_key_id = secret_ref.rpartition('/')
        volume.encryption_key_id = encryption_key_id
        volume.save()

        # TODO(abishop): need to determine if any snapshot creations are
        # in-flight that might be added to the db with the volume's old
        # fixed key ID.
        snapshots = objects.snapshot.SnapshotList.get_all_for_volume(
            self.admin_context,
            volume.id)
        for snapshot in snapshots:
            snapshot.encryption_key_id = encryption_key_id
            snapshot.save()

    def _log_migration_status(self):
        num_to_migrate = len(objects.volume.VolumeList.get_all(
            context=self.admin_context,
            filters={'encryption_key_id': self.fixed_key_id}))
        if num_to_migrate == 0:
            LOG.info("No volumes are using the ConfKeyManager's "
                     "encryption_key_id.")
        else:
            LOG.warning("There are still %d volume(s) using the "
                        "ConfKeyManager's all-zeros encryption key ID.",
                        num_to_migrate)


def migrate_fixed_key(volumes, conf=CONF):
    KeyMigrator(conf).handle_key_migration(volumes)
