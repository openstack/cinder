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

"""Remove quota consistencygroups

Revision ID: b7b88f50aab5
Revises: 9ab1b092a404
Create Date: 2021-11-10 11:54:50.123389
"""

from alembic import op
from sqlalchemy import orm

from cinder.db.sqlalchemy import models


# revision identifiers, used by Alembic.
revision = 'b7b88f50aab5'
down_revision = '9ab1b092a404'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    session = orm.Session(bind=bind)

    with session.begin():
        for model in (models.QuotaClass,
                      models.Quota,
                      models.QuotaUsage,
                      models.Reservation):

            session.query(model)\
                .filter_by(deleted=False, resource='consistencygroups')\
                .update(model.delete_values())
