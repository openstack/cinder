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

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import MetaData, String, Table, ForeignKey

from cinder.i18n import _
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    Table('volumes', meta, autoload=True)

    # New table
    transfers = Table(
        'transfers', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('volume_id', String(length=36), ForeignKey('volumes.id'),
               nullable=False),
        Column('display_name', String(length=255)),
        Column('salt', String(length=255)),
        Column('crypt_hash', String(length=255)),
        Column('expires_at', DateTime(timezone=False)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    try:
        transfers.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(transfers))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    transfers = Table('transfers',
                      meta,
                      autoload=True)
    try:
        transfers.drop()
    except Exception:
        LOG.error(_("transfers table not dropped"))
        raise
