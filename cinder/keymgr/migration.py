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
import itertools

from oslo_config import cfg
from oslo_log import log as logging

from barbicanclient import client as barbican_client
from castellan import options as castellan_options
from keystoneauth1 import loading as ks_loading
from keystoneauth1 import session as ks_session

from cinder import context
from cinder import coordination
from cinder import objects
from cinder.volume import volume_migration

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

    def handle_key_migration(self, volumes, backups):
        castellan_options.set_defaults(self.conf)
        try:
            self.conf.import_opt(name='fixed_key',
                                 module_str='cinder.keymgr.conf_key_mgr',
                                 group='key_manager')
        except cfg.DuplicateOptError:
            pass
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
        elif not volumes and not backups:
            LOG.info("Not migrating encryption keys because there are no "
                     "volumes or backups associated with this host.")
            self._log_migration_status()
        else:
            self.fixed_key_bytes = bytes(binascii.unhexlify(fixed_key))
            self.fixed_key_length = len(self.fixed_key_bytes) * 8
            self._migrate_keys(volumes, backups)
            self._log_migration_status()

    def _migrate_keys(self, volumes, backups):
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
        for item in itertools.chain(volumes, backups):
            try:
                self._migrate_encryption_key(item)
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

    @coordination.synchronized('{item.id}-{f_name}')
    def _migrate_encryption_key(self, item):
        if item.encryption_key_id == self.fixed_key_id:
            self._update_encryption_key_id(item)

    def _get_barbican_key_id(self, user_id):
        # Create a Barbican secret using the same fixed_key algorithm.
        secret = self.barbican.secrets.create(algorithm='AES',
                                              bit_length=self.fixed_key_length,
                                              secret_type='symmetric',
                                              mode=None,
                                              payload=self.fixed_key_bytes)
        secret_ref = secret.store()

        # Create a Barbican ACL so the user can access the secret.
        acl = self.barbican.acls.create(entity_ref=secret_ref,
                                        users=[user_id])
        acl.submit()

        _, _, encryption_key_id = secret_ref.rpartition('/')
        return encryption_key_id

    def _update_encryption_key_id(self, item):
        LOG.info("Migrating %(item_type)s %(item_id)s encryption key "
                 "to Barbican",
                 {'item_type': type(item).__name__, 'item_id': item.id})

        encryption_key_id = self._get_barbican_key_id(item.user_id)
        item.encryption_key_id = encryption_key_id
        item.save()

        allowTypes = (volume_migration.VolumeMigration, objects.volume.Volume)
        if isinstance(item, allowTypes):
            snapshots = objects.snapshot.SnapshotList.get_all_for_volume(
                self.admin_context,
                item.id)
            for snapshot in snapshots:
                snapshot.encryption_key_id = encryption_key_id
                snapshot.save()

    def _log_migration_status(self):
        volumes_to_migrate = len(objects.volume.VolumeList.get_all(
            context=self.admin_context,
            filters={'encryption_key_id': self.fixed_key_id}))
        if volumes_to_migrate == 0:
            LOG.info("No volumes are using the ConfKeyManager's "
                     "encryption_key_id.")
        else:
            LOG.warning("There are still %d volume(s) using the "
                        "ConfKeyManager's all-zeros encryption key ID.",
                        volumes_to_migrate)

        backups_to_migrate = len(objects.backup.BackupList.get_all(
            context=self.admin_context,
            filters={'encryption_key_id': self.fixed_key_id}))
        if backups_to_migrate == 0:
            # Old backups may exist that were created prior to when the
            # encryption_key_id is stored in the backup table. It's not
            # easy to tell whether the backup was of an encrypted volume,
            # in which case an all-zeros encryption key ID might be present
            # in the backup's metadata.
            LOG.info("No backups are known to be using the ConfKeyManager's "
                     "encryption_key_id.")
        else:
            LOG.warning("There are still %d backups(s) using the "
                        "ConfKeyManager's all-zeros encryption key ID.",
                        backups_to_migrate)


def migrate_fixed_key(volumes=None, backups=None, conf=CONF):
    volumes = volumes or []
    backups = backups or []
    KeyMigrator(conf).handle_key_migration(volumes, backups)
