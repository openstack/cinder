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
from oslotest import base as test_base

from cinder.db import migration
from cinder.db.sqlalchemy import api as db_api


class TestDBSync(test_base.BaseTestCase):

    def test_db_sync_legacy_version(self):
        """We don't allow users to request legacy versions."""
        self.assertRaises(ValueError, migration.db_sync, '402')

    @mock.patch.object(migration, '_upgrade_alembic')
    @mock.patch.object(migration, '_find_alembic_conf')
    @mock.patch.object(db_api, 'get_engine')
    def test_db_sync(self, mock_get_engine, mock_find_conf, mock_upgrade):
        migration.db_sync()
        mock_get_engine.assert_called_once_with()
        mock_find_conf.assert_called_once_with()
        mock_find_conf.return_value.set_main_option.assert_called_once_with(
            'sqlalchemy.url', str(mock_get_engine.return_value.url),
        )

        mock_upgrade.assert_called_once_with(
            mock_get_engine.return_value, mock_find_conf.return_value, None,
        )


@mock.patch.object(alembic_migration.MigrationContext, 'configure')
@mock.patch.object(db_api, 'get_engine')
class TestDBVersion(test_base.BaseTestCase):

    def test_db_version(self, mock_get_engine, mock_m_context_configure):
        """Database is controlled by alembic."""
        ret = migration.db_version()
        mock_m_context = mock_m_context_configure.return_value
        self.assertEqual(
            mock_m_context.get_current_revision.return_value,
            ret,
        )
        mock_get_engine.assert_called_once_with()
        mock_m_context_configure.assert_called_once()
