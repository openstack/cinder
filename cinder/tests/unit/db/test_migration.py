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

from unittest import mock

from alembic.runtime import migration as alembic_migration
from migrate import exceptions as migrate_exceptions
from migrate.versioning import api as migrate_api
from oslotest import base as test_base

from cinder.db import migration
from cinder.db.sqlalchemy import api as db_api


class TestDBSync(test_base.BaseTestCase):

    def test_db_sync_legacy_version(self):
        """We don't allow users to request legacy versions."""
        self.assertRaises(ValueError, migration.db_sync, '402')

    @mock.patch.object(migration, '_upgrade_alembic')
    @mock.patch.object(migration, '_init_alembic_on_legacy_database')
    @mock.patch.object(migration, '_is_database_under_alembic_control')
    @mock.patch.object(migration, '_is_database_under_migrate_control')
    @mock.patch.object(migration, '_find_alembic_conf')
    @mock.patch.object(migration, '_find_migrate_repo')
    @mock.patch.object(db_api, 'get_engine')
    def _test_db_sync(
        self, has_migrate, has_alembic, mock_get_engine, mock_find_repo,
        mock_find_conf, mock_is_migrate, mock_is_alembic, mock_init,
        mock_upgrade,
    ):
        mock_is_migrate.return_value = has_migrate
        mock_is_alembic.return_value = has_alembic
        migration.db_sync()
        mock_get_engine.assert_called_once_with()
        mock_find_repo.assert_called_once_with()
        mock_find_conf.assert_called_once_with()
        mock_find_conf.return_value.set_main_option.assert_called_once_with(
            'sqlalchemy.url', str(mock_get_engine.return_value.url),
        )
        mock_is_migrate.assert_called_once_with(
            mock_get_engine.return_value, mock_find_repo.return_value)
        if has_migrate:
            mock_is_alembic.assert_called_once_with(
                mock_get_engine.return_value)
        else:
            mock_is_alembic.assert_not_called()

        # we should only attempt the upgrade of the remaining
        # sqlalchemy-migrate-based migrations and fake apply of the initial
        # alembic migrations if sqlalchemy-migrate is in place but alembic
        # hasn't been used yet
        if has_migrate and not has_alembic:
            mock_init.assert_called_once_with(
                mock_get_engine.return_value,
                mock_find_repo.return_value, mock_find_conf.return_value)
        else:
            mock_init.assert_not_called()

        # however, we should always attempt to upgrade the requested migration
        # to alembic
        mock_upgrade.assert_called_once_with(
            mock_get_engine.return_value, mock_find_conf.return_value, None)

    def test_db_sync_new_deployment(self):
        """Mimic a new deployment without existing sqlalchemy-migrate cruft."""
        has_migrate = False
        has_alembic = False
        self._test_db_sync(has_migrate, has_alembic)

    def test_db_sync_with_existing_migrate_database(self):
        """Mimic a deployment currently managed by sqlalchemy-migrate."""
        has_migrate = True
        has_alembic = False
        self._test_db_sync(has_migrate, has_alembic)

    def test_db_sync_with_existing_alembic_database(self):
        """Mimic a deployment that's already switched to alembic."""
        has_migrate = True
        has_alembic = True
        self._test_db_sync(has_migrate, has_alembic)


@mock.patch.object(alembic_migration.MigrationContext, 'configure')
@mock.patch.object(migrate_api, 'db_version')
@mock.patch.object(migration, '_is_database_under_alembic_control')
@mock.patch.object(migration, '_is_database_under_migrate_control')
@mock.patch.object(db_api, 'get_engine')
@mock.patch.object(migration, '_find_migrate_repo')
class TestDBVersion(test_base.BaseTestCase):

    def test_db_version_migrate(
        self, mock_find_repo, mock_get_engine, mock_is_migrate,
        mock_is_alembic, mock_migrate_version, mock_m_context_configure,
    ):
        """Database is controlled by sqlalchemy-migrate."""
        mock_is_migrate.return_value = True
        mock_is_alembic.return_value = False
        ret = migration.db_version()
        self.assertEqual(mock_migrate_version.return_value, ret)
        mock_find_repo.assert_called_once_with()
        mock_get_engine.assert_called_once_with()
        mock_is_migrate.assert_called_once()
        mock_is_alembic.assert_called_once()
        mock_migrate_version.assert_called_once_with(
            mock_get_engine.return_value, mock_find_repo.return_value)
        mock_m_context_configure.assert_not_called()

    def test_db_version_alembic(
        self, mock_find_repo, mock_get_engine, mock_is_migrate,
        mock_is_alembic, mock_migrate_version, mock_m_context_configure,
    ):
        """Database is controlled by alembic."""
        mock_is_migrate.return_value = False
        mock_is_alembic.return_value = True
        ret = migration.db_version()
        mock_m_context = mock_m_context_configure.return_value
        self.assertEqual(
            mock_m_context.get_current_revision.return_value,
            ret,
        )
        mock_find_repo.assert_called_once_with()
        mock_get_engine.assert_called_once_with()
        mock_is_migrate.assert_called_once()
        mock_is_alembic.assert_called_once()
        mock_migrate_version.assert_not_called()
        mock_m_context_configure.assert_called_once()

    def test_db_version_not_controlled(
        self, mock_find_repo, mock_get_engine, mock_is_migrate,
        mock_is_alembic, mock_migrate_version, mock_m_context_configure,
    ):
        """Database is not controlled."""
        mock_is_migrate.return_value = False
        mock_is_alembic.return_value = False
        ret = migration.db_version()
        self.assertIsNone(ret)
        mock_find_repo.assert_called_once_with()
        mock_get_engine.assert_called_once_with()
        mock_is_migrate.assert_called_once()
        mock_is_alembic.assert_called_once()
        mock_migrate_version.assert_not_called()
        mock_m_context_configure.assert_not_called()


class TestDatabaseUnderVersionControl(test_base.BaseTestCase):

    @mock.patch.object(migrate_api, 'db_version')
    def test__is_database_under_migrate_control__true(self, mock_db_version):
        ret = migration._is_database_under_migrate_control('engine', 'repo')
        self.assertTrue(ret)
        mock_db_version.assert_called_once_with('engine', 'repo')

    @mock.patch.object(migrate_api, 'db_version')
    def test__is_database_under_migrate_control__false(self, mock_db_version):
        mock_db_version.side_effect = \
            migrate_exceptions.DatabaseNotControlledError()
        ret = migration._is_database_under_migrate_control('engine', 'repo')
        self.assertFalse(ret)
        mock_db_version.assert_called_once_with('engine', 'repo')

    @mock.patch.object(alembic_migration.MigrationContext, 'configure')
    def test__is_database_under_alembic_control__true(self, mock_configure):
        context = mock_configure.return_value
        context.get_current_revision.return_value = 'foo'
        engine = mock.MagicMock()
        ret = migration._is_database_under_alembic_control(engine)
        self.assertTrue(ret)
        context.get_current_revision.assert_called_once_with()

    @mock.patch.object(alembic_migration.MigrationContext, 'configure')
    def test__is_database_under_alembic_control__false(self, mock_configure):
        context = mock_configure.return_value
        context.get_current_revision.return_value = None
        engine = mock.MagicMock()
        ret = migration._is_database_under_alembic_control(engine)
        self.assertFalse(ret)
        context.get_current_revision.assert_called_once_with()
