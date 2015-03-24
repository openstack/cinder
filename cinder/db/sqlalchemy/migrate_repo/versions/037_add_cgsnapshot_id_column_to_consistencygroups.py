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
from sqlalchemy import Column
from sqlalchemy import MetaData, String, Table

from cinder.i18n import _LE

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    """Add cgsnapshot_id column to consistencygroups."""
    meta = MetaData()
    meta.bind = migrate_engine

    consistencygroups = Table('consistencygroups', meta, autoload=True)
    cgsnapshot_id = Column('cgsnapshot_id', String(36))

    try:
        consistencygroups.create_column(cgsnapshot_id)
        consistencygroups.update().values(cgsnapshot_id=None).execute()
    except Exception:
        LOG.error(_LE("Adding cgsnapshot_id column to consistencygroups "
                      "table failed."))
        raise


def downgrade(migrate_engine):
    """Remove cgsnapshot_id column from consistencygroups."""
    meta = MetaData()
    meta.bind = migrate_engine

    consistencygroups = Table('consistencygroups', meta, autoload=True)
    cgsnapshot_id = consistencygroups.columns.cgsnapshot_id

    try:
        consistencygroups.drop_column(cgsnapshot_id)
    except Exception:
        LOG.error(_LE("Dropping cgsnapshot_id column from consistencygroups "
                      "table failed."))
        raise
