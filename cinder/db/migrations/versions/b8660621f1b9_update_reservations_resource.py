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

"""Update reservations resource

Revision ID: b8660621f1b9
Revises: 89aa6f9639f9
Create Date: 2021-10-27 17:25:16.790525
"""

from alembic import op
from oslo_log import log as logging
import sqlalchemy as sa


LOG = logging.getLogger(__name__)


# revision identifiers, used by Alembic.
revision = 'b8660621f1b9'
down_revision = '89aa6f9639f9'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()

    for table_name in ('quotas', 'quota_classes', 'reservations'):
        table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
        col = table.c.resource
        # SQLite doesn't support altering tables, so we use a workaround
        if connection.engine.name == 'sqlite':
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.alter_column('resource',
                                      existing_type=col.type,
                                      type_=sa.String(length=300))

        else:
            # MySQL ALTER needs to have existing_type, existing_server_default,
            # and existing_nullable or it will do who-knows-what
            try:
                op.alter_column(table_name, 'resource',
                                existing_type=col.type,
                                existing_nullable=col.nullable,
                                existing_server_default=col.server_default,
                                type_=sa.String(length=300))
            except Exception:
                # On MariaDB, max length varies depending on the version and
                # the InnoDB page size [1], so it is possible to have error
                # 1071 ('Specified key was too long; max key length is 767
                # bytes").  Since this migration is to resolve a corner case,
                # deployments with those DB versions won't be covered.
                # [1]: https://mariadb.com/kb/en/library/innodb-limitations/#page-sizes  # noqa
                if not connection.engine.name == 'mysql':
                    raise
                LOG.warning('Error in migration %s, Cinder still affected by '
                            'bug #1948962', revision)
