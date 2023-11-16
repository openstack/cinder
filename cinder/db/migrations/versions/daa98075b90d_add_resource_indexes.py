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

"""Add resource indexes

Revision ID: daa98075b90d
Revises: c92a3e68beed
Create Date: 2021-11-26 10:26:41.883072
"""

from alembic import op
from oslo_db.sqlalchemy import utils
from oslo_log import log as logging


LOG = logging.getLogger(__name__)


# revision identifiers, used by Alembic.
revision = 'daa98075b90d'
down_revision = 'c92a3e68beed'
branch_labels = None
depends_on = None

INDEXES = (
    ('groups', 'groups_deleted_project_id_idx', ('deleted', 'project_id')),

    ('group_snapshots', 'group_snapshots_deleted_project_id_idx',
     ('deleted', 'project_id')),

    ('volumes', 'volumes_deleted_project_id_idx', ('deleted', 'project_id')),
    ('volumes', 'volumes_deleted_host_idx', ('deleted', 'host')),

    ('backups', 'backups_deleted_project_id_idx', ('deleted', 'project_id')),

    ('snapshots', 'snapshots_deleted_project_id_idx', ('deleted',
                                                       'project_id')),
)


def upgrade():
    conn = op.get_bind()
    is_mysql = conn.dialect.name == 'mysql'

    for table, idx_name, fields in INDEXES:
        # Skip creation in mysql if it already has the index
        if is_mysql and utils.index_exists(conn, table, idx_name):
            LOG.info('Skipping index %s, already exists', idx_name)
        else:
            op.create_index(idx_name, table, fields)
