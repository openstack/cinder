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
Tests for database migrations. This test case reads the configuration
file test_migrations.conf for database connection settings
to use in the tests. For each connection found in the config file,
the test case runs a series of test cases to ensure that migrations work
properly both upgrading and downgrading, and that no data loss occurs
if possible.
"""

import os
import uuid

from migrate.versioning import api as migration_api
from migrate.versioning import repository
from oslo_db.sqlalchemy import test_base
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as db_utils
import sqlalchemy

from cinder.db import migration
import cinder.db.sqlalchemy.migrate_repo


class MigrationsMixin(test_migrations.WalkVersionsMixin):
    """Test sqlalchemy-migrate migrations."""

    BOOL_TYPE = sqlalchemy.types.BOOLEAN
    TIME_TYPE = sqlalchemy.types.DATETIME

    @property
    def INIT_VERSION(self):
        return migration.INIT_VERSION

    @property
    def REPOSITORY(self):
        migrate_file = cinder.db.sqlalchemy.migrate_repo.__file__
        return repository.Repository(
            os.path.abspath(os.path.dirname(migrate_file)))

    @property
    def migration_api(self):
        return migration_api

    @property
    def migrate_engine(self):
        return self.engine

    def get_table_ref(self, engine, name, metadata):
        metadata.bind = engine
        return sqlalchemy.Table(name, metadata, autoload=True)

    def _pre_upgrade_004(self, engine):
        """Change volume types to UUID """
        data = {
            'volumes': [{'id': str(uuid.uuid4()), 'host': 'test1',
                         'volume_type_id': 1},
                        {'id': str(uuid.uuid4()), 'host': 'test2',
                         'volume_type_id': 1},
                        {'id': str(uuid.uuid4()), 'host': 'test3',
                         'volume_type_id': 3},
                        ],
            'volume_types': [{'name': 'vtype1'},
                             {'name': 'vtype2'},
                             {'name': 'vtype3'},
                             ],
            'volume_type_extra_specs': [{'volume_type_id': 1,
                                         'key': 'v1',
                                         'value': 'hotep',
                                         },
                                        {'volume_type_id': 1,
                                         'key': 'v2',
                                         'value': 'bending rodrigez',
                                         },
                                        {'volume_type_id': 2,
                                         'key': 'v3',
                                         'value': 'bending rodrigez',
                                         },
                                        ]}

        volume_types = db_utils.get_table(engine, 'volume_types')
        for vtype in data['volume_types']:
            r = volume_types.insert().values(vtype).execute()
            vtype['id'] = r.inserted_primary_key[0]

        volume_type_es = db_utils.get_table(engine, 'volume_type_extra_specs')
        for vtes in data['volume_type_extra_specs']:
            r = volume_type_es.insert().values(vtes).execute()
            vtes['id'] = r.inserted_primary_key[0]

        volumes = db_utils.get_table(engine, 'volumes')
        for vol in data['volumes']:
            r = volumes.insert().values(vol).execute()
            vol['id'] = r.inserted_primary_key[0]

        return data

    def _check_004(self, engine, data):
        volumes = db_utils.get_table(engine, 'volumes')
        v1 = volumes.select(volumes.c.id ==
                            data['volumes'][0]['id']
                            ).execute().first()
        v2 = volumes.select(volumes.c.id ==
                            data['volumes'][1]['id']
                            ).execute().first()
        v3 = volumes.select(volumes.c.id ==
                            data['volumes'][2]['id']
                            ).execute().first()

        volume_types = db_utils.get_table(engine, 'volume_types')
        vt1 = volume_types.select(volume_types.c.name ==
                                  data['volume_types'][0]['name']
                                  ).execute().first()
        vt2 = volume_types.select(volume_types.c.name ==
                                  data['volume_types'][1]['name']
                                  ).execute().first()
        vt3 = volume_types.select(volume_types.c.name ==
                                  data['volume_types'][2]['name']
                                  ).execute().first()

        vtes = db_utils.get_table(engine, 'volume_type_extra_specs')
        vtes1 = vtes.select(vtes.c.key ==
                            data['volume_type_extra_specs'][0]['key']
                            ).execute().first()
        vtes2 = vtes.select(vtes.c.key ==
                            data['volume_type_extra_specs'][1]['key']
                            ).execute().first()
        vtes3 = vtes.select(vtes.c.key ==
                            data['volume_type_extra_specs'][2]['key']
                            ).execute().first()

        self.assertEqual(v1['volume_type_id'], vt1['id'])
        self.assertEqual(v2['volume_type_id'], vt1['id'])
        self.assertEqual(v3['volume_type_id'], vt3['id'])

        self.assertEqual(vtes1['volume_type_id'], vt1['id'])
        self.assertEqual(vtes2['volume_type_id'], vt1['id'])
        self.assertEqual(vtes3['volume_type_id'], vt2['id'])

    def _check_005(self, engine, data):
        """Test that adding source_volid column works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.source_volid.type,
                              sqlalchemy.types.VARCHAR)

    def _check_006(self, engine, data):
        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertIsInstance(snapshots.c.provider_location.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_006(self, engine):
        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertNotIn('provider_location', snapshots.c)

    def _check_007(self, engine, data):
        snapshots = db_utils.get_table(engine, 'snapshots')
        fkey, = snapshots.c.volume_id.foreign_keys

        self.assertIsNotNone(fkey)

    def _post_downgrade_007(self, engine):
        snapshots = db_utils.get_table(engine, 'snapshots')

        self.assertEqual(0, len(snapshots.c.volume_id.foreign_keys))

    def _pre_upgrade_008(self, engine):
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "backups"))

    def _check_008(self, engine, data):
        """Test that adding and removing the backups table works correctly."""

        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "backups"))
        backups = db_utils.get_table(engine, 'backups')

        self.assertIsInstance(backups.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(backups.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(backups.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(backups.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(backups.c.id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.volume_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.user_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.project_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.host.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.availability_zone.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.display_name.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.display_description.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.container.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.status.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.fail_reason.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.service_metadata.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.service.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(backups.c.size.type,
                              sqlalchemy.types.INTEGER)
        self.assertIsInstance(backups.c.object_count.type,
                              sqlalchemy.types.INTEGER)

    def _check_009(self, engine, data):
        """Test adding snapshot_metadata table works correctly."""
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "snapshot_metadata"))
        snapshot_metadata = db_utils.get_table(engine, 'snapshot_metadata')

        self.assertIsInstance(snapshot_metadata.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(snapshot_metadata.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(snapshot_metadata.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(snapshot_metadata.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(snapshot_metadata.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(snapshot_metadata.c.id.type,
                              sqlalchemy.types.INTEGER)
        self.assertIsInstance(snapshot_metadata.c.snapshot_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(snapshot_metadata.c.key.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(snapshot_metadata.c.value.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_008(self, engine):
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "snapshot_metadata"))

    def _check_010(self, engine, data):
        """Test adding transfers table works correctly."""
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "transfers"))
        transfers = db_utils.get_table(engine, 'transfers')

        self.assertIsInstance(transfers.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(transfers.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(transfers.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(transfers.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(transfers.c.id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(transfers.c.volume_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(transfers.c.display_name.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(transfers.c.salt.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(transfers.c.crypt_hash.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(transfers.c.expires_at.type,
                              self.TIME_TYPE)

    def _post_downgrade_010(self, engine):
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "transfers"))

    def _check_011(self, engine, data):
        """Test adding transfers table works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIn('bootable', volumes.c)
        self.assertIsInstance(volumes.c.bootable.type,
                              self.BOOL_TYPE)

    def _post_downgrade_011(self, engine):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('bootable', volumes.c)

    def _check_012(self, engine, data):
        """Test that adding attached_host column works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.attached_host.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_012(self, engine):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('attached_host', volumes.c)

    def _check_013(self, engine, data):
        """Test that adding provider_geometry column works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.provider_geometry.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_013(self, engine):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('provider_geometry', volumes.c)

    def _check_014(self, engine, data):
        """Test that adding _name_id column works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c._name_id.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_014(self, engine):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('_name_id', volumes.c)

    def _check_015(self, engine, data):
        """Test removing migrations table works correctly."""
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "migrations"))

    def _post_downgrade_015(self, engine):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "migrations"))

    def _check_016(self, engine, data):
        """Test that dropping xen storage manager tables works correctly."""
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  'sm_flavors'))
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  'sm_backend_config'))
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  'sm_volume'))

    def _post_downgrade_016(self, engine):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 'sm_flavors'))
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 'sm_backend_config'))
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 'sm_volume'))

    def _check_017(self, engine, data):
        """Test that added encryption information works correctly."""
        # encryption key UUID
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIn('encryption_key_id', volumes.c)
        self.assertIsInstance(volumes.c.encryption_key_id.type,
                              sqlalchemy.types.VARCHAR)

        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertIn('encryption_key_id', snapshots.c)
        self.assertIsInstance(snapshots.c.encryption_key_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIn('volume_type_id', snapshots.c)
        self.assertIsInstance(snapshots.c.volume_type_id.type,
                              sqlalchemy.types.VARCHAR)

        # encryption types table
        encryption = db_utils.get_table(engine, 'encryption')
        self.assertIsInstance(encryption.c.volume_type_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(encryption.c.cipher.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(encryption.c.key_size.type,
                              sqlalchemy.types.INTEGER)
        self.assertIsInstance(encryption.c.provider.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_017(self, engine):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('encryption_key_id', volumes.c)

        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertNotIn('encryption_key_id', snapshots.c)

        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  'encryption'))

    def _check_018(self, engine, data):
        """Test that added qos_specs table works correctly."""
        self.assertTrue(engine.dialect.has_table(
            engine.connect(), "quality_of_service_specs"))
        qos_specs = db_utils.get_table(engine, 'quality_of_service_specs')
        self.assertIsInstance(qos_specs.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(qos_specs.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(qos_specs.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(qos_specs.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(qos_specs.c.id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(qos_specs.c.specs_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(qos_specs.c.key.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(qos_specs.c.value.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_018(self, engine):
        self.assertFalse(engine.dialect.has_table(
            engine.connect(), "quality_of_service_specs"))

    def _check_019(self, engine, data):
        """Test that adding migration_status column works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.migration_status.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_019(self, engine):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('migration_status', volumes.c)

    def _check_020(self, engine, data):
        """Test adding volume_admin_metadata table works correctly."""
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "volume_admin_metadata"))
        volume_admin_metadata = db_utils.get_table(engine,
                                                   'volume_admin_metadata')

        self.assertIsInstance(volume_admin_metadata.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(volume_admin_metadata.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(volume_admin_metadata.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(volume_admin_metadata.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(volume_admin_metadata.c.id.type,
                              sqlalchemy.types.INTEGER)
        self.assertIsInstance(volume_admin_metadata.c.volume_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(volume_admin_metadata.c.key.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(volume_admin_metadata.c.value.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_020(self, engine):
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "volume_admin_metadata"))

    def _verify_quota_defaults(self, engine):
        quota_class_metadata = db_utils.get_table(engine, 'quota_classes')

        num_defaults = quota_class_metadata.count().\
            where(quota_class_metadata.c.class_name == 'default').\
            execute().scalar()

        self.assertEqual(3, num_defaults)

    def _check_021(self, engine, data):
        """Test adding default data for quota classes works correctly."""
        self._verify_quota_defaults(engine)

    def _post_downgrade_021(self, engine):
        # Defaults should not be deleted during downgrade
        self._verify_quota_defaults(engine)

    def _check_022(self, engine, data):
        """Test that adding disabled_reason column works correctly."""
        services = db_utils.get_table(engine, 'services')
        self.assertIsInstance(services.c.disabled_reason.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_022(self, engine):
        services = db_utils.get_table(engine, 'services')
        self.assertNotIn('disabled_reason', services.c)

    def _check_023(self, engine, data):
        """Test that adding reservations index works correctly."""
        reservations = db_utils.get_table(engine, 'reservations')
        index_columns = []
        for idx in reservations.indexes:
            if idx.name == 'reservations_deleted_expire_idx':
                index_columns = idx.columns.keys()
                break

        self.assertEqual(sorted(['deleted', 'expire']),
                         sorted(index_columns))

    def _post_downgrade_023(self, engine):
        reservations = db_utils.get_table(engine, 'reservations')
        index_names = [idx.name for idx in reservations.indexes]
        self.assertNotIn('reservations_deleted_expire_idx', index_names)

    def _check_024(self, engine, data):
        """Test adding replication columns to volume table."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.replication_status.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(volumes.c.replication_extended_status.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(volumes.c.replication_driver_data.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_024(self, engine):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('replication_status', volumes.c)
        self.assertNotIn('replication_extended_status', volumes.c)
        self.assertNotIn('replication_driver_data', volumes.c)

    def _check_025(self, engine, data):
        """Test adding table and columns for consistencygroups."""
        # Test consistencygroup_id is in Table volumes
        metadata = sqlalchemy.MetaData()
        volumes = self.get_table_ref(engine, 'volumes', metadata)
        self.assertIsInstance(volumes.c.consistencygroup_id.type,
                              sqlalchemy.types.VARCHAR)

        # Test cgsnapshot_id is in Table snapshots
        snapshots = self.get_table_ref(engine, 'snapshots', metadata)
        self.assertIsInstance(snapshots.c.cgsnapshot_id.type,
                              sqlalchemy.types.VARCHAR)

        # Test Table consistencygroups exists
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "consistencygroups"))
        consistencygroups = self.get_table_ref(engine,
                                               'consistencygroups',
                                               metadata)
        self.assertIsInstance(consistencygroups.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(consistencygroups.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(consistencygroups.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(consistencygroups.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(consistencygroups.c.id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(consistencygroups.c.user_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(consistencygroups.c.project_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(consistencygroups.c.host.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(consistencygroups.c.availability_zone.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(consistencygroups.c.name.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(consistencygroups.c.description.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(consistencygroups.c.volume_type_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(consistencygroups.c.status.type,
                              sqlalchemy.types.VARCHAR)

        # Test Table cgsnapshots exists
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "cgsnapshots"))
        cgsnapshots = self.get_table_ref(engine,
                                         'cgsnapshots',
                                         metadata)

        self.assertIsInstance(cgsnapshots.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(cgsnapshots.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(cgsnapshots.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(cgsnapshots.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(cgsnapshots.c.id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(cgsnapshots.c.user_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(cgsnapshots.c.project_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(cgsnapshots.c.consistencygroup_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(cgsnapshots.c.name.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(cgsnapshots.c.description.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(cgsnapshots.c.status.type,
                              sqlalchemy.types.VARCHAR)

        # Verify foreign keys are created
        fkey, = volumes.c.consistencygroup_id.foreign_keys
        self.assertEqual(consistencygroups.c.id, fkey.column)
        self.assertEqual(1, len(volumes.foreign_keys))

        fkey, = snapshots.c.cgsnapshot_id.foreign_keys
        self.assertEqual(cgsnapshots.c.id, fkey.column)
        fkey, = snapshots.c.volume_id.foreign_keys
        self.assertEqual(volumes.c.id, fkey.column)
        # 2 foreign keys in Table snapshots
        self.assertEqual(2, len(snapshots.foreign_keys))

    def _post_downgrade_025(self, engine):
        metadata = sqlalchemy.MetaData()
        # Test consistencygroup_id is not in Table volumes
        volumes = self.get_table_ref(engine, 'volumes', metadata)
        self.assertNotIn('consistencygroup_id', volumes.c)

        # Test cgsnapshot_id is not in Table snapshots
        snapshots = self.get_table_ref(engine, 'snapshots', metadata)
        self.assertNotIn('cgsnapshot_id', snapshots.c)

        # Verify foreign keys are removed
        self.assertEqual(0, len(volumes.foreign_keys))
        self.assertEqual(1, len(snapshots.foreign_keys))
        # volume_id foreign key is still in Table snapshots
        fkey, = snapshots.c.volume_id.foreign_keys
        self.assertEqual(volumes.c.id, fkey.column)

        # Test Table cgsnapshots doesn't exist any more
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "cgsnapshots"))

        # Test Table consistencygroups doesn't exist any more
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "consistencygroups"))

    def _pre_upgrade_026(self, engine):
        """Test adding default data for consistencygroups quota class."""
        quota_class_metadata = db_utils.get_table(engine, 'quota_classes')

        num_defaults = quota_class_metadata.count().\
            where(quota_class_metadata.c.class_name == 'default').\
            execute().scalar()

        self.assertEqual(3, num_defaults)

    def _check_026(self, engine, data):
        quota_class_metadata = db_utils.get_table(engine, 'quota_classes')
        num_defaults = quota_class_metadata.count().\
            where(quota_class_metadata.c.class_name == 'default').\
            execute().scalar()

        self.assertEqual(4, num_defaults)

    def _post_downgrade_026(self, engine):
        # Defaults should not be deleted during downgrade
        quota_class_metadata = db_utils.get_table(engine, 'quota_classes')
        num_defaults = quota_class_metadata.count().\
            where(quota_class_metadata.c.class_name == 'default').\
            execute().scalar()

        self.assertEqual(4, num_defaults)

    def _check_032(self, engine, data):
        """Test adding volume_type_projects table works correctly."""
        volume_type_projects = db_utils.get_table(engine,
                                                  'volume_type_projects')
        self.assertIsInstance(volume_type_projects.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(volume_type_projects.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(volume_type_projects.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(volume_type_projects.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(volume_type_projects.c.id.type,
                              sqlalchemy.types.INTEGER)
        self.assertIsInstance(volume_type_projects.c.volume_type_id.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(volume_type_projects.c.project_id.type,
                              sqlalchemy.types.VARCHAR)

        volume_types = db_utils.get_table(engine, 'volume_types')
        self.assertIsInstance(volume_types.c.is_public.type,
                              self.BOOL_TYPE)

    def _post_downgrade_032(self, engine):
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "volume_type_projects"))
        volume_types = db_utils.get_table(engine, 'volume_types')
        self.assertNotIn('is_public', volume_types.c)

    def _check_033(self, engine, data):
        """Test adding encryption_id column to encryption table."""
        encryptions = db_utils.get_table(engine, 'encryption')
        self.assertIsInstance(encryptions.c.encryption_id.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_033(self, engine):
        metadata = sqlalchemy.schema.MetaData()
        metadata.bind = engine

        encryptions = db_utils.get_table(engine, 'encryption')
        self.assertNotIn('encryption_id', encryptions.c)

    def _check_034(self, engine, data):
        """Test adding description columns to volume_types table."""
        volume_types = db_utils.get_table(engine, 'volume_types')
        self.assertIsInstance(volume_types.c.description.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_034(self, engine):
        volume_types = db_utils.get_table(engine, 'volume_types')
        self.assertNotIn('description', volume_types.c)

    def _check_035(self, engine, data):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.provider_id.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_035(self, engine):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('provider_id', volumes.c)

    def _check_036(self, engine, data):
        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertIsInstance(snapshots.c.provider_id.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_036(self, engine):
        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertNotIn('provider_id', snapshots.c)

    def _check_037(self, engine, data):
        consistencygroups = db_utils.get_table(engine, 'consistencygroups')
        self.assertIsInstance(consistencygroups.c.cgsnapshot_id.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_037(self, engine):
        consistencygroups = db_utils.get_table(engine, 'consistencygroups')
        self.assertNotIn('cgsnapshot_id', consistencygroups.c)

    def _check_038(self, engine, data):
        """Test adding and removing driver_initiator_data table."""

        has_table = engine.dialect.has_table(engine.connect(),
                                             "driver_initiator_data")
        self.assertTrue(has_table)

        private_data = db_utils.get_table(
            engine,
            'driver_initiator_data'
        )

        self.assertIsInstance(private_data.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(private_data.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(private_data.c.id.type,
                              sqlalchemy.types.INTEGER)
        self.assertIsInstance(private_data.c.initiator.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(private_data.c.namespace.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(private_data.c.key.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(private_data.c.value.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_038(self, engine):
        has_table = engine.dialect.has_table(engine.connect(),
                                             "driver_initiator_data")
        self.assertFalse(has_table)

    def _check_039(self, engine, data):
        backups = db_utils.get_table(engine, 'backups')
        self.assertIsInstance(backups.c.parent_id.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_039(self, engine):
        backups = db_utils.get_table(engine, 'backups')
        self.assertNotIn('parent_id', backups.c)

    def _check_40(self, engine, data):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('instance_uuid', volumes.c)
        self.assertNotIn('attached_host', volumes.c)
        self.assertNotIn('attach_time', volumes.c)
        self.assertNotIn('mountpoint', volumes.c)
        self.assertIsInstance(volumes.c.multiattach.type,
                              self.BOOL_TYPE)

        attachments = db_utils.get_table(engine, 'volume_attachment')
        self.assertIsInstance(attachments.c.attach_mode.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(attachments.c.instance_uuid.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(attachments.c.attached_host.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(attachments.c.mountpoint.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(attachments.c.attach_status.type,
                              sqlalchemy.types.VARCHAR)

    def _post_downgrade_040(self, engine):
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "volume_attachment"))
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('multiattach', volumes.c)
        self.assertIsInstance(volumes.c.instance_uuid.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(volumes.c.attached_host.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(volumes.c.attach_time.type,
                              sqlalchemy.types.VARCHAR)
        self.assertIsInstance(volumes.c.mountpoint.type,
                              sqlalchemy.types.VARCHAR)

    def _check_041(self, engine, data):
        """Test that adding modified_at column works correctly."""
        services = db_utils.get_table(engine, 'services')
        self.assertIsInstance(services.c.modified_at.type,
                              self.TIME_TYPE)

    def _post_downgrade_041(self, engine):
        services = db_utils.get_table(engine, 'services')
        self.assertNotIn('modified_at', services.c)

    def test_walk_versions(self):
        self.walk_versions(True, False)


class TestSqliteMigrations(test_base.DbTestCase,
                           MigrationsMixin):
    pass


class TestMysqlMigrations(test_base.MySQLOpportunisticTestCase,
                          MigrationsMixin):

    BOOL_TYPE = sqlalchemy.dialects.mysql.TINYINT

    def test_mysql_innodb(self):
        """Test that table creation on mysql only builds InnoDB tables."""
        # add this to the global lists to make reset work with it, it's removed
        # automatically in tearDown so no need to clean it up here.
        # sanity check
        migration.db_sync(engine=self.migrate_engine)

        total = self.migrate_engine.execute(
            "SELECT count(*) "
            "from information_schema.TABLES "
            "where TABLE_SCHEMA='{0}'".format(
                self.migrate_engine.url.database))
        self.assertGreater(total.scalar(), 0,
                           msg="No tables found. Wrong schema?")

        noninnodb = self.migrate_engine.execute(
            "SELECT count(*) "
            "from information_schema.TABLES "
            "where TABLE_SCHEMA='openstack_citest' "
            "and ENGINE!='InnoDB' "
            "and TABLE_NAME!='migrate_version'")
        count = noninnodb.scalar()
        self.assertEqual(count, 0, "%d non InnoDB tables created" % count)


class TestPostgresqlMigrations(test_base.PostgreSQLOpportunisticTestCase,
                               MigrationsMixin):
    TIME_TYPE = sqlalchemy.types.TIMESTAMP
