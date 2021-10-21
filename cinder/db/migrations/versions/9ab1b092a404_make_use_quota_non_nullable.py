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

"""Make use_quota non nullable

Revision ID: 9ab1b092a404
Revises: b8660621f1b9
Create Date: 2021-10-22 16:23:17.080934
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9ab1b092a404'
down_revision = 'b8660621f1b9'
branch_labels = None
depends_on = None


def upgrade():
    # It's safe to set them as non nullable because when we run db sync on this
    # release the online migrations from the previous release must already have
    # been run.
    connection = op.get_bind()
    # SQLite doesn't support dropping/altering tables, so we use a workaround
    if connection.engine.name == 'sqlite':
        with op.batch_alter_table('volumes') as batch_op:
            batch_op.alter_column('use_quota',
                                  existing_type=sa.BOOLEAN,
                                  nullable=False, server_default=sa.true())
        with op.batch_alter_table('snapshots') as batch_op:
            batch_op.alter_column('use_quota',
                                  existing_type=sa.BOOLEAN,
                                  nullable=False, server_default=sa.true())

    else:
        op.alter_column('volumes', 'use_quota',
                        existing_type=sa.BOOLEAN,
                        nullable=False, server_default=sa.true())
        op.alter_column('snapshots', 'use_quota',
                        existing_type=sa.BOOLEAN,
                        nullable=False, server_default=sa.true())
