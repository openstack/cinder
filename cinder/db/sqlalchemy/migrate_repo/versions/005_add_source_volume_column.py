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

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    """Add source volume id column to volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    source_volid = Column('source_volid', String(36))
    volumes.create_column(source_volid)
    volumes.update().values(source_volid=None).execute()


def downgrade(migrate_engine):
    """Remove source volume id column to volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    source_volid = Column('source_volid', String(36))
    volumes.drop_column(source_volid)
