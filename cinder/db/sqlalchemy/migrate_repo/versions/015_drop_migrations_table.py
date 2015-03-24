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
from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table

from cinder.i18n import _LE

LOG = logging.getLogger(__name__)


TABLE_NAME = 'migrations'


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    table = Table(TABLE_NAME, meta, autoload=True)
    try:
        table.drop()
    except Exception:
        LOG.error(_LE("migrations table not dropped"))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    table = Table(
        TABLE_NAME, meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),

        Column('source_compute', String(length=255)),
        Column('dest_compute', String(length=255)),
        Column('dest_host', String(length=255)),
        Column('old_instance_type_id', Integer),
        Column('new_instance_type_id', Integer),
        Column('instance_uuid', String(length=255), nullable=True),
        Column('status', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    try:
        table.create()
    except Exception:
        LOG.error(_LE("Table |%s| not created"), repr(table))
        raise
