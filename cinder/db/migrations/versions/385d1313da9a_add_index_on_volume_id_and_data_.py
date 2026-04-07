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

"""Add index on volume_id and data_timestamp to backups

Revision ID: 385d1313da9a
Revises: 9c74c1c6971f
Create Date: 2026-09-02 09:45:20.896636
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '385d1313da9a'
down_revision = '9c74c1c6971f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('backups_volume_id_data_timestamp_idx',
                    'backups',
                    ['volume_id', 'data_timestamp'],
                    unique=False)
