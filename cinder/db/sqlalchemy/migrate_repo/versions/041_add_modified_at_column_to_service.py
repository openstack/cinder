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

from oslo_log import log as logging
from sqlalchemy import Column, MetaData, DateTime, Table

from cinder.i18n import _LE

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    services = Table('services', meta, autoload=True)
    modified_at = Column('modified_at', DateTime(timezone=False))
    try:
        services.create_column(modified_at)
    except Exception:
        LOG.error(_LE("Adding modified_at column to services table failed."))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    services = Table('services', meta, autoload=True)
    try:
        services.drop_column('modified_at')
    except Exception:
        LOG.error(_LE("Unable to drop modified_at column from services"
                  "table."))
        raise
