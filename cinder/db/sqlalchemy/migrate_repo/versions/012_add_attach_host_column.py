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

from sqlalchemy import Column
from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    """Add attach host column to volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    attached_host = Column('attached_host', String(255))
    volumes.create_column(attached_host)
    volumes.update().values(attached_host=None).execute()


def downgrade(migrate_engine):
    """Remove attach host column from volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    attached_host = Column('attached_host', String(255))
    volumes.drop_column(attached_host)
