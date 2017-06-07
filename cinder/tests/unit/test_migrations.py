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

import fixtures
from migrate.versioning import api as migration_api
from migrate.versioning import repository
from oslo_db.sqlalchemy import test_base
from oslo_db.sqlalchemy import test_migrations
from oslo_db.sqlalchemy import utils as db_utils
import sqlalchemy
from sqlalchemy.engine import reflection
from sqlalchemy import func, select

from cinder.db import migration
import cinder.db.sqlalchemy.migrate_repo
from cinder.volume import group_types as volume_group_types


class MigrationsMixin(test_migrations.WalkVersionsMixin):
    """Test sqlalchemy-migrate migrations."""

    BOOL_TYPE = sqlalchemy.types.BOOLEAN
    TIME_TYPE = sqlalchemy.types.DATETIME
    INTEGER_TYPE = sqlalchemy.types.INTEGER
    VARCHAR_TYPE = sqlalchemy.types.VARCHAR
    TEXT_TYPE = sqlalchemy.types.Text

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

    class BannedDBSchemaOperations(fixtures.Fixture):
        """Ban some operations for migrations"""
        def __init__(self, banned_resources=None):
            super(MigrationsMixin.BannedDBSchemaOperations, self).__init__()
            self._banned_resources = banned_resources or []

        @staticmethod
        def _explode(resource, op):
            print('%s.%s()' % (resource, op))  # noqa
            raise Exception(
                'Operation %s.%s() is not allowed in a database migration' % (
                    resource, op))

        def setUp(self):
            super(MigrationsMixin.BannedDBSchemaOperations, self).setUp()
            for thing in self._banned_resources:
                self.useFixture(fixtures.MonkeyPatch(
                    'sqlalchemy.%s.drop' % thing,
                    lambda *a, **k: self._explode(thing, 'drop')))
                self.useFixture(fixtures.MonkeyPatch(
                    'sqlalchemy.%s.alter' % thing,
                    lambda *a, **k: self._explode(thing, 'alter')))

    def migrate_up(self, version, with_data=False):
        # NOTE(dulek): This is a list of migrations where we allow dropping
        # things. The rules for adding things here are very very specific.
        # Insight on how to drop things from the DB in a backward-compatible
        # manner is provided in Cinder's developer documentation.
        # Reviewers: DO NOT ALLOW THINGS TO BE ADDED HERE WITHOUT CARE
        exceptions = [
            # NOTE(dulek): 62 alters the column type from boolean to integer to
            # fix the bug 1518363. If we've followed the guidelines for live
            # schema upgrades we would end up either waiting 3 releases to fix
            # a simple bug or trigger a rebuild index operation in migration
            # (because constraint was impossible to delete without deleting
            # other foreign key constraints). Either way it's harsh... We've
            # decided to go with alter to minimise upgrade impact. The only
            # consequence for deployments running recent MySQL is inability
            # to perform volume-type-access modifications while running this
            # migration.
            62,
            # NOTE(dulek): 66 sets reservations.usage_id to nullable. This is
            # 100% backward compatible and according to MySQL docs such ALTER
            # is performed with the same restrictions as column addition, which
            # we of course allow.
            66,
            # NOTE(dulek): 73 drops tables and columns we've stopped using a
            # release ago.
            73,
            # NOTE(ameade): 87 sets messages.request_id to nullable. This
            # should be safe for the same reason as migration 66.
            87,
            # NOTE : 104 modifies size of messages.project_id to 255.
            # This should be safe for the same reason as migration 87.
            104,
        ]

        # NOTE(dulek): We only started requiring things be additive in
        # Mitaka, so ignore all migrations before that point.
        MITAKA_START = 61

        if version >= MITAKA_START and version not in exceptions:
            banned = ['Table', 'Column']
        else:
            banned = None
        with MigrationsMixin.BannedDBSchemaOperations(banned):
            super(MigrationsMixin, self).migrate_up(version, with_data)

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
                              self.VARCHAR_TYPE)

    def _check_006(self, engine, data):
        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertIsInstance(snapshots.c.provider_location.type,
                              self.VARCHAR_TYPE)

    def _check_007(self, engine, data):
        snapshots = db_utils.get_table(engine, 'snapshots')
        fkey, = snapshots.c.volume_id.foreign_keys

        self.assertIsNotNone(fkey)

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
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.volume_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.user_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.project_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.host.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.availability_zone.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.display_name.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.display_description.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.container.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.status.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.fail_reason.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.service_metadata.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.service.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.size.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(backups.c.object_count.type,
                              self.INTEGER_TYPE)

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
                              self.INTEGER_TYPE)
        self.assertIsInstance(snapshot_metadata.c.snapshot_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(snapshot_metadata.c.key.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(snapshot_metadata.c.value.type,
                              self.VARCHAR_TYPE)

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
                              self.VARCHAR_TYPE)
        self.assertIsInstance(transfers.c.volume_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(transfers.c.display_name.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(transfers.c.salt.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(transfers.c.crypt_hash.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(transfers.c.expires_at.type,
                              self.TIME_TYPE)

    def _check_011(self, engine, data):
        """Test adding transfers table works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIn('bootable', volumes.c)
        self.assertIsInstance(volumes.c.bootable.type,
                              self.BOOL_TYPE)

    def _check_012(self, engine, data):
        """Test that adding attached_host column works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.attached_host.type,
                              self.VARCHAR_TYPE)

    def _check_013(self, engine, data):
        """Test that adding provider_geometry column works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.provider_geometry.type,
                              self.VARCHAR_TYPE)

    def _check_014(self, engine, data):
        """Test that adding _name_id column works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c._name_id.type,
                              self.VARCHAR_TYPE)

    def _check_015(self, engine, data):
        """Test removing migrations table works correctly."""
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  "migrations"))

    def _check_016(self, engine, data):
        """Test that dropping xen storage manager tables works correctly."""
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  'sm_flavors'))
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  'sm_backend_config'))
        self.assertFalse(engine.dialect.has_table(engine.connect(),
                                                  'sm_volume'))

    def _check_017(self, engine, data):
        """Test that added encryption information works correctly."""
        # encryption key UUID
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIn('encryption_key_id', volumes.c)
        self.assertIsInstance(volumes.c.encryption_key_id.type,
                              self.VARCHAR_TYPE)

        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertIn('encryption_key_id', snapshots.c)
        self.assertIsInstance(snapshots.c.encryption_key_id.type,
                              self.VARCHAR_TYPE)
        self.assertIn('volume_type_id', snapshots.c)
        self.assertIsInstance(snapshots.c.volume_type_id.type,
                              self.VARCHAR_TYPE)

        # encryption types table
        encryption = db_utils.get_table(engine, 'encryption')
        self.assertIsInstance(encryption.c.volume_type_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(encryption.c.cipher.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(encryption.c.key_size.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(encryption.c.provider.type,
                              self.VARCHAR_TYPE)

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
                              self.VARCHAR_TYPE)
        self.assertIsInstance(qos_specs.c.specs_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(qos_specs.c.key.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(qos_specs.c.value.type,
                              self.VARCHAR_TYPE)

    def _check_019(self, engine, data):
        """Test that adding migration_status column works correctly."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.migration_status.type,
                              self.VARCHAR_TYPE)

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
                              self.INTEGER_TYPE)
        self.assertIsInstance(volume_admin_metadata.c.volume_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(volume_admin_metadata.c.key.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(volume_admin_metadata.c.value.type,
                              self.VARCHAR_TYPE)

    def _verify_quota_defaults(self, engine):
        quota_class_metadata = db_utils.get_table(engine, 'quota_classes')

        num_defaults = quota_class_metadata.count().\
            where(quota_class_metadata.c.class_name == 'default').\
            execute().scalar()

        self.assertEqual(3, num_defaults)

    def _check_021(self, engine, data):
        """Test adding default data for quota classes works correctly."""
        self._verify_quota_defaults(engine)

    def _check_022(self, engine, data):
        """Test that adding disabled_reason column works correctly."""
        services = db_utils.get_table(engine, 'services')
        self.assertIsInstance(services.c.disabled_reason.type,
                              self.VARCHAR_TYPE)

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

    def _check_024(self, engine, data):
        """Test adding replication columns to volume table."""
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.replication_status.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(volumes.c.replication_extended_status.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(volumes.c.replication_driver_data.type,
                              self.VARCHAR_TYPE)

    def _check_025(self, engine, data):
        """Test adding table and columns for consistencygroups."""
        # Test consistencygroup_id is in Table volumes
        metadata = sqlalchemy.MetaData()
        volumes = self.get_table_ref(engine, 'volumes', metadata)
        self.assertIsInstance(volumes.c.consistencygroup_id.type,
                              self.VARCHAR_TYPE)

        # Test cgsnapshot_id is in Table snapshots
        snapshots = self.get_table_ref(engine, 'snapshots', metadata)
        self.assertIsInstance(snapshots.c.cgsnapshot_id.type,
                              self.VARCHAR_TYPE)

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
                              self.VARCHAR_TYPE)
        self.assertIsInstance(consistencygroups.c.user_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(consistencygroups.c.project_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(consistencygroups.c.host.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(consistencygroups.c.availability_zone.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(consistencygroups.c.name.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(consistencygroups.c.description.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(consistencygroups.c.volume_type_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(consistencygroups.c.status.type,
                              self.VARCHAR_TYPE)

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
                              self.VARCHAR_TYPE)
        self.assertIsInstance(cgsnapshots.c.user_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(cgsnapshots.c.project_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(cgsnapshots.c.consistencygroup_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(cgsnapshots.c.name.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(cgsnapshots.c.description.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(cgsnapshots.c.status.type,
                              self.VARCHAR_TYPE)

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
                              self.INTEGER_TYPE)
        self.assertIsInstance(volume_type_projects.c.volume_type_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(volume_type_projects.c.project_id.type,
                              self.VARCHAR_TYPE)

        volume_types = db_utils.get_table(engine, 'volume_types')
        self.assertIsInstance(volume_types.c.is_public.type,
                              self.BOOL_TYPE)

    def _check_033(self, engine, data):
        """Test adding encryption_id column to encryption table."""
        encryptions = db_utils.get_table(engine, 'encryption')
        self.assertIsInstance(encryptions.c.encryption_id.type,
                              self.VARCHAR_TYPE)

    def _check_034(self, engine, data):
        """Test adding description columns to volume_types table."""
        volume_types = db_utils.get_table(engine, 'volume_types')
        self.assertIsInstance(volume_types.c.description.type,
                              self.VARCHAR_TYPE)

    def _check_035(self, engine, data):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.provider_id.type,
                              self.VARCHAR_TYPE)

    def _check_036(self, engine, data):
        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertIsInstance(snapshots.c.provider_id.type,
                              self.VARCHAR_TYPE)

    def _check_037(self, engine, data):
        consistencygroups = db_utils.get_table(engine, 'consistencygroups')
        self.assertIsInstance(consistencygroups.c.cgsnapshot_id.type,
                              self.VARCHAR_TYPE)

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
                              self.INTEGER_TYPE)
        self.assertIsInstance(private_data.c.initiator.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(private_data.c.namespace.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(private_data.c.key.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(private_data.c.value.type,
                              self.VARCHAR_TYPE)

    def _check_039(self, engine, data):
        backups = db_utils.get_table(engine, 'backups')
        self.assertIsInstance(backups.c.parent_id.type,
                              self.VARCHAR_TYPE)

    def _check_040(self, engine, data):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertNotIn('instance_uuid', volumes.c)
        self.assertNotIn('attached_host', volumes.c)
        self.assertNotIn('attach_time', volumes.c)
        self.assertNotIn('mountpoint', volumes.c)
        self.assertIsInstance(volumes.c.multiattach.type,
                              self.BOOL_TYPE)

        attachments = db_utils.get_table(engine, 'volume_attachment')
        self.assertIsInstance(attachments.c.attach_mode.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(attachments.c.instance_uuid.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(attachments.c.attached_host.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(attachments.c.mountpoint.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(attachments.c.attach_status.type,
                              self.VARCHAR_TYPE)

    def _check_041(self, engine, data):
        """Test that adding modified_at column works correctly."""
        services = db_utils.get_table(engine, 'services')
        self.assertIsInstance(services.c.modified_at.type,
                              self.TIME_TYPE)

    def _check_048(self, engine, data):
        quotas = db_utils.get_table(engine, 'quotas')
        self.assertIsInstance(quotas.c.allocated.type,
                              self.INTEGER_TYPE)

    def _check_049(self, engine, data):
        backups = db_utils.get_table(engine, 'backups')
        self.assertIsInstance(backups.c.temp_volume_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.temp_snapshot_id.type,
                              self.VARCHAR_TYPE)

    def _check_050(self, engine, data):
        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.previous_status.type,
                              self.VARCHAR_TYPE)

    def _check_051(self, engine, data):
        consistencygroups = db_utils.get_table(engine, 'consistencygroups')
        self.assertIsInstance(consistencygroups.c.source_cgid.type,
                              self.VARCHAR_TYPE)

    def _check_052(self, engine, data):
        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertIsInstance(snapshots.c.provider_auth.type,
                              self.VARCHAR_TYPE)

    def _check_053(self, engine, data):
        services = db_utils.get_table(engine, 'services')
        self.assertIsInstance(services.c.rpc_current_version.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(services.c.rpc_available_version.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(services.c.object_current_version.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(services.c.object_available_version.type,
                              self.VARCHAR_TYPE)

    def _check_054(self, engine, data):
        backups = db_utils.get_table(engine, 'backups')
        self.assertIsInstance(backups.c.num_dependent_backups.type,
                              self.INTEGER_TYPE)

    def _check_055(self, engine, data):
        """Test adding image_volume_cache_entries table."""
        has_table = engine.dialect.has_table(engine.connect(),
                                             "image_volume_cache_entries")
        self.assertTrue(has_table)

        private_data = db_utils.get_table(
            engine,
            'image_volume_cache_entries'
        )

        self.assertIsInstance(private_data.c.id.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(private_data.c.host.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(private_data.c.image_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(private_data.c.image_updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(private_data.c.volume_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(private_data.c.size.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(private_data.c.last_used.type,
                              self.TIME_TYPE)

    def _check_061(self, engine, data):
        backups = db_utils.get_table(engine, 'backups')
        self.assertIsInstance(backups.c.snapshot_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backups.c.data_timestamp.type,
                              self.TIME_TYPE)

    def _check_062(self, engine, data):
        volume_type_projects = db_utils.get_table(engine,
                                                  'volume_type_projects')
        self.assertIsInstance(volume_type_projects.c.id.type,
                              self.INTEGER_TYPE)

    def _check_064(self, engine, data):
        backups = db_utils.get_table(engine, 'backups')
        self.assertIsInstance(backups.c.restore_volume_id.type,
                              self.VARCHAR_TYPE)

    def _check_065(self, engine, data):
        services = db_utils.get_table(engine, 'services')
        self.assertIsInstance(services.c.replication_status.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(services.c.frozen.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(services.c.active_backend_id.type,
                              self.VARCHAR_TYPE)

    def _check_066(self, engine, data):
        reservations = db_utils.get_table(engine, 'reservations')
        self.assertIsInstance(reservations.c.allocated_id.type,
                              self.INTEGER_TYPE)

    def __check_cinderbase_fields(self, columns):
        """Check fields inherited from CinderBase ORM class."""
        self.assertIsInstance(columns.created_at.type, self.TIME_TYPE)
        self.assertIsInstance(columns.updated_at.type, self.TIME_TYPE)
        self.assertIsInstance(columns.deleted_at.type, self.TIME_TYPE)
        self.assertIsInstance(columns.deleted.type, self.BOOL_TYPE)

    def _check_067(self, engine, data):
        iscsi_targets = db_utils.get_table(engine, 'iscsi_targets')
        fkey, = iscsi_targets.c.volume_id.foreign_keys
        self.assertIsNotNone(fkey)

    def _check_074(self, engine, data):
        """Test adding message table."""
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "messages"))
        messages = db_utils.get_table(engine, 'messages')

        self.assertIsInstance(messages.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(messages.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(messages.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(messages.c.message_level.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(messages.c.project_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(messages.c.id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(messages.c.request_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(messages.c.resource_uuid.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(messages.c.event_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(messages.c.resource_type.type,
                              self.VARCHAR_TYPE)

    def _check_075(self, engine, data):
        """Test adding cluster table and cluster_id fields."""
        self.assertTrue(engine.dialect.has_table(engine.connect(), 'clusters'))
        clusters = db_utils.get_table(engine, 'clusters')
        columns = clusters.c
        self.__check_cinderbase_fields(columns)

        # Cluster specific fields
        self.assertIsInstance(columns.id.type, self.INTEGER_TYPE)
        self.assertIsInstance(columns.name.type, self.VARCHAR_TYPE)
        self.assertIsInstance(columns.binary.type, self.VARCHAR_TYPE)
        self.assertIsInstance(columns.disabled.type, self.BOOL_TYPE)
        self.assertIsInstance(columns.disabled_reason.type, self.VARCHAR_TYPE)

        # Check that we have added cluster_name field to all required tables
        for table_name in ('services', 'consistencygroups', 'volumes'):
            table = db_utils.get_table(engine, table_name)
            self.assertIsInstance(table.c.cluster_name.type,
                                  self.VARCHAR_TYPE)

    def _check_076(self, engine, data):
        workers = db_utils.get_table(engine, 'workers')
        columns = workers.c
        self.__check_cinderbase_fields(columns)

        # Workers specific fields
        self.assertIsInstance(columns.id.type, self.INTEGER_TYPE)
        self.assertIsInstance(columns.resource_type.type, self.VARCHAR_TYPE)
        self.assertIsInstance(columns.resource_id.type, self.VARCHAR_TYPE)
        self.assertIsInstance(columns.status.type, self.VARCHAR_TYPE)
        self.assertIsInstance(columns.service_id.type, self.INTEGER_TYPE)

    def _check_077(self, engine, data):
        """Test adding group types and specs tables."""
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "group_types"))
        group_types = db_utils.get_table(engine, 'group_types')

        self.assertIsInstance(group_types.c.id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_types.c.name.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_types.c.description.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_types.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(group_types.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(group_types.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(group_types.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(group_types.c.is_public.type,
                              self.BOOL_TYPE)

        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "group_type_specs"))
        group_specs = db_utils.get_table(engine, 'group_type_specs')

        self.assertIsInstance(group_specs.c.id.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(group_specs.c.key.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_specs.c.value.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_specs.c.group_type_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_specs.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(group_specs.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(group_specs.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(group_specs.c.deleted.type,
                              self.BOOL_TYPE)

        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "group_type_projects"))
        type_projects = db_utils.get_table(engine, 'group_type_projects')

        self.assertIsInstance(type_projects.c.id.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(type_projects.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(type_projects.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(type_projects.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(type_projects.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(type_projects.c.group_type_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(type_projects.c.project_id.type,
                              self.VARCHAR_TYPE)

    def _check_078(self, engine, data):
        """Test adding groups tables."""
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "groups"))
        groups = db_utils.get_table(engine, 'groups')

        self.assertIsInstance(groups.c.id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(groups.c.name.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(groups.c.description.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(groups.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(groups.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(groups.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(groups.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(groups.c.user_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(groups.c.project_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(groups.c.host.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(groups.c.availability_zone.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(groups.c.group_type_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(groups.c.status.type,
                              self.VARCHAR_TYPE)

        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "group_volume_type_mapping"))
        mapping = db_utils.get_table(engine, 'group_volume_type_mapping')

        self.assertIsInstance(mapping.c.id.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(mapping.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(mapping.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(mapping.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(mapping.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(mapping.c.volume_type_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(mapping.c.group_id.type,
                              self.VARCHAR_TYPE)

        volumes = db_utils.get_table(engine, 'volumes')
        self.assertIsInstance(volumes.c.group_id.type,
                              self.VARCHAR_TYPE)

        quota_classes = db_utils.get_table(engine, 'quota_classes')
        rows = select([func.count()]).select_from(
            quota_classes).where(quota_classes.c.resource == 'groups').\
            execute().scalar()
        self.assertEqual(1, rows)

    def _check_079(self, engine, data):
        """Test adding group_snapshots tables."""
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "group_snapshots"))
        group_snapshots = db_utils.get_table(engine, 'group_snapshots')

        self.assertIsInstance(group_snapshots.c.id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_snapshots.c.name.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_snapshots.c.description.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_snapshots.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(group_snapshots.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(group_snapshots.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(group_snapshots.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(group_snapshots.c.user_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_snapshots.c.project_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_snapshots.c.group_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_snapshots.c.group_type_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(group_snapshots.c.status.type,
                              self.VARCHAR_TYPE)

        snapshots = db_utils.get_table(engine, 'snapshots')
        self.assertIsInstance(snapshots.c.group_snapshot_id.type,
                              self.VARCHAR_TYPE)

        groups = db_utils.get_table(engine, 'groups')
        self.assertIsInstance(groups.c.group_snapshot_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(groups.c.source_group_id.type,
                              self.VARCHAR_TYPE)

    def _check_086(self, engine, data):
        """Test inserting default cgsnapshot group type."""
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "group_types"))
        group_types = db_utils.get_table(engine, 'group_types')
        t1 = (group_types.select(group_types.c.name ==
                                 volume_group_types.DEFAULT_CGSNAPSHOT_TYPE).
              execute().first())
        self.assertIsNotNone(t1)

        group_specs = db_utils.get_table(engine, 'group_type_specs')
        specs = group_specs.select(
            group_specs.c.group_type_id == t1.id and
            group_specs.c.key == 'consistent_group_snapshot_enabled'
        ).execute().first()
        self.assertIsNotNone(specs)
        self.assertEqual('<is> True', specs.value)

    def _check_087(self, engine, data):
        """Test request_id column in messages is nullable."""
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "messages"))
        messages = db_utils.get_table(engine, 'messages')

        self.assertIsInstance(messages.c.request_id.type,
                              self.VARCHAR_TYPE)
        self.assertTrue(messages.c.request_id.nullable)

    def _check_088(self, engine, data):
        """Test adding replication data to cluster table."""
        clusters = db_utils.get_table(engine, 'clusters')
        self.assertIsInstance(clusters.c.replication_status.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(clusters.c.active_backend_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(clusters.c.frozen.type,
                              self.BOOL_TYPE)

    def _check_089(self, engine, data):
        """Test adding cluster_name to image volume cache table."""
        image_cache = db_utils.get_table(engine, 'image_volume_cache_entries')
        self.assertIsInstance(image_cache.c.cluster_name.type,
                              self.VARCHAR_TYPE)

    def _check_090(self, engine, data):
        """Test adding race_preventer to workers table."""
        workers = db_utils.get_table(engine, 'workers')
        self.assertIsInstance(workers.c.race_preventer.type,
                              self.INTEGER_TYPE)

    def _check_091(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "attachment_specs"))
        attachment = db_utils.get_table(engine, 'attachment_specs')

        self.assertIsInstance(attachment.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(attachment.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(attachment.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(attachment.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(attachment.c.id.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(attachment.c.key.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(attachment.c.value.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(attachment.c.attachment_id.type,
                              self.VARCHAR_TYPE)
        f_keys = self.get_foreign_key_columns(engine, 'attachment_specs')
        self.assertEqual({'attachment_id'}, f_keys)

    def _check_098(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "messages"))
        ids = self.get_indexed_columns(engine, 'messages')
        self.assertTrue('expires_at' in ids)

    def _check_099(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "volume_attachment"))
        attachment = db_utils.get_table(engine, 'volume_attachment')

        self.assertIsInstance(attachment.c.connection_info.type,
                              self.TEXT_TYPE)

    def get_table_names(self, engine):
        inspector = reflection.Inspector.from_engine(engine)
        return inspector.get_table_names()

    def get_foreign_key_columns(self, engine, table_name):
        foreign_keys = set()
        table = db_utils.get_table(engine, table_name)
        inspector = reflection.Inspector.from_engine(engine)
        for column_dict in inspector.get_columns(table_name):
            column_name = column_dict['name']
            column = getattr(table.c, column_name)
            if column.foreign_keys:
                foreign_keys.add(column_name)
        return foreign_keys

    def get_indexed_columns(self, engine, table_name):
        indexed_columns = set()
        for index in db_utils.get_indexes(engine, table_name):
            for column_name in index['column_names']:
                indexed_columns.add(column_name)
        return indexed_columns

    def assert_each_foreign_key_is_part_of_an_index(self):
        engine = self.migrate_engine

        non_indexed_foreign_keys = set()

        for table_name in self.get_table_names(engine):
            indexed_columns = self.get_indexed_columns(engine, table_name)
            foreign_key_columns = self.get_foreign_key_columns(
                engine, table_name
            )
            for column_name in foreign_key_columns - indexed_columns:
                non_indexed_foreign_keys.add(table_name + '.' + column_name)

        self.assertSetEqual(set(), non_indexed_foreign_keys)

    def _pre_upgrade_101(self, engine):
        """Add data to test the SQL migration."""
        types_table = db_utils.get_table(engine, 'volume_types')
        for i in range(1, 5):
            types_table.insert().execute({'id': str(i)})

        specs_table = db_utils.get_table(engine, 'volume_type_extra_specs')
        specs = [
            {'volume_type_id': '1', 'key': 'key', 'value': '<is> False'},
            {'volume_type_id': '2', 'key': 'replication_enabled',
             'value': '<is> False'},
            {'volume_type_id': '3', 'key': 'replication_enabled',
             'value': '<is> True', 'deleted': True},
            {'volume_type_id': '3', 'key': 'key', 'value': '<is> True'},
            {'volume_type_id': '4', 'key': 'replication_enabled',
             'value': '<is> True'},
            {'volume_type_id': '4', 'key': 'key', 'value': '<is> True'},
        ]
        for spec in specs:
            specs_table.insert().execute(spec)

        volumes_table = db_utils.get_table(engine, 'volumes')
        volumes = [
            {'id': '1', 'replication_status': 'disabled',
             'volume_type_id': None},
            {'id': '2', 'replication_status': 'disabled',
             'volume_type_id': ''},
            {'id': '3', 'replication_status': 'disabled',
             'volume_type_id': '1'},
            {'id': '4', 'replication_status': 'disabled',
             'volume_type_id': '2'},
            {'id': '5', 'replication_status': 'disabled',
             'volume_type_id': '2'},
            {'id': '6', 'replication_status': 'disabled',
             'volume_type_id': '3'},
            {'id': '7', 'replication_status': 'error', 'volume_type_id': '4'},
            {'id': '8', 'deleted': True, 'replication_status': 'disabled',
             'volume_type_id': '4'},
            {'id': '9', 'replication_status': 'disabled', 'deleted': None,
             'volume_type_id': '4'},
            {'id': '10', 'replication_status': 'disabled', 'deleted': False,
             'volume_type_id': '4'},
        ]
        for volume in volumes:
            volumes_table.insert().execute(volume)

        # Only the last volume should be changed to enabled
        expected = {v['id']: v['replication_status'] for v in volumes}
        expected['9'] = 'enabled'
        expected['10'] = 'enabled'
        return expected

    def _check_101(self, engine, data):
        # Get existing volumes after the migration
        volumes_table = db_utils.get_table(engine, 'volumes')
        volumes = volumes_table.select().execute()
        # Check that the replication_status is the one we expect according to
        # _pre_upgrade_098
        for volume in volumes:
            self.assertEqual(data[volume.id], volume.replication_status,
                             'id %s' % volume.id)

    def _check_102(self, engine, data):
        """Test adding replication_status to groups table."""
        groups = db_utils.get_table(engine, 'groups')
        self.assertIsInstance(groups.c.replication_status.type,
                              self.VARCHAR_TYPE)

    def _check_103(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "messages"))
        attachment = db_utils.get_table(engine, 'messages')

        self.assertIsInstance(attachment.c.detail_id.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(attachment.c.action_id.type,
                              self.VARCHAR_TYPE)

    def _check_104(self, engine, data):
        messages = db_utils.get_table(engine, 'messages')
        self.assertEqual(255, messages.c.project_id.type.length)

    def _check_105(self, engine, data):
        self.assertTrue(engine.dialect.has_table(engine.connect(),
                                                 "backup_metadata"))
        backup_metadata = db_utils.get_table(engine, 'backup_metadata')

        self.assertIsInstance(backup_metadata.c.created_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(backup_metadata.c.updated_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(backup_metadata.c.deleted_at.type,
                              self.TIME_TYPE)
        self.assertIsInstance(backup_metadata.c.deleted.type,
                              self.BOOL_TYPE)
        self.assertIsInstance(backup_metadata.c.id.type,
                              self.INTEGER_TYPE)
        self.assertIsInstance(backup_metadata.c.key.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backup_metadata.c.value.type,
                              self.VARCHAR_TYPE)
        self.assertIsInstance(backup_metadata.c.backup_id.type,
                              self.VARCHAR_TYPE)
        f_keys = self.get_foreign_key_columns(engine, 'backup_metadata')
        self.assertEqual({'backup_id'}, f_keys)

    def test_walk_versions(self):
        self.walk_versions(False, False)
        self.assert_each_foreign_key_is_part_of_an_index()


class TestSqliteMigrations(test_base.DbTestCase,
                           MigrationsMixin):
    def assert_each_foreign_key_is_part_of_an_index(self):
        # Skip the test for SQLite because SQLite does not list
        # UniqueConstraints as indexes, which makes this test fail.
        # Given that SQLite is only for testing purposes, it is safe to skip
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
