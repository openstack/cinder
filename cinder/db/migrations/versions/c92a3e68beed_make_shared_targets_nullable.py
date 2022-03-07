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

"""Make shared_targets nullable

Revision ID: c92a3e68beed
Revises: 921e1a36b076
Create Date: 2022-03-23 21:30:18.585830
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c92a3e68beed'
down_revision = '921e1a36b076'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()

    # Preserve existing type, be it boolean or tinyint treated as boolean
    table = sa.Table('volumes', sa.MetaData(), autoload_with=connection)
    existing_type = table.c.shared_targets.type

    # SQLite doesn't support altering tables, so we use a workaround
    if connection.engine.name == 'sqlite':
        with op.batch_alter_table('volumes') as batch_op:
            batch_op.alter_column('shared_targets',
                                  existing_type=existing_type,
                                  type_=sa.Boolean(),
                                  nullable=True)

    else:
        op.alter_column('volumes', 'shared_targets',
                        existing_type=existing_type,
                        type_=sa.Boolean(),
                        nullable=True)
