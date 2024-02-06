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

"""Quota: Add backup defaults in quota class

Revision ID: 9c74c1c6971f
Revises: b7b88f50aab5
Create Date: 2021-11-10 12:17:06.713239
"""

from datetime import datetime

from alembic import op
from oslo_config import cfg
import sqlalchemy as sa

from cinder.db.sqlalchemy import models

# revision identifiers, used by Alembic.
revision = '9c74c1c6971f'
down_revision = 'b7b88f50aab5'
branch_labels = None
depends_on = None


def _create_default(bind, resource, hard_limit):
    session = sa.orm.Session(bind=bind)

    class_name = 'default'
    created_at = datetime.now()  # noqa

    with session.begin():
        if session.query(sa.sql.exists()
                         .where(
                             sa.and_(
                                 ~models.QuotaClass.deleted,
                                 models.QuotaClass.class_name == class_name,
                                 models.QuotaClass.resource == resource)))\
                .scalar():
            return

        quota_class = models.QuotaClass(created_at=created_at,
                                        class_name=class_name,
                                        resource=resource,
                                        hard_limit=hard_limit,
                                        deleted=False)

        session.add(quota_class)


def upgrade():
    bind = op.get_bind()

    _create_default(bind, 'backups', cfg.CONF.quota_backups)
    _create_default(bind, 'backup_gigabytes', cfg.CONF.quota_backup_gigabytes)
