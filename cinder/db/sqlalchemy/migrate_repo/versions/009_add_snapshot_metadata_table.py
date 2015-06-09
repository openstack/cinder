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
from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import Integer, MetaData, String, Table, ForeignKey

from cinder.i18n import _LE

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    Table('snapshots', meta, autoload=True)

    # New table
    snapshot_metadata = Table(
        'snapshot_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('snapshot_id', String(length=36), ForeignKey('snapshots.id'),
               nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        mysql_engine='InnoDB'
    )

    try:
        snapshot_metadata.create()
    except Exception:
        LOG.error(_LE("Table |%s| not created!"), repr(snapshot_metadata))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    snapshot_metadata = Table('snapshot_metadata',
                              meta,
                              autoload=True)
    try:
        snapshot_metadata.drop()
    except Exception:
        LOG.error(_LE("snapshot_metadata table not dropped"))
        raise
