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
from sqlalchemy import Boolean, MetaData, String, Table


def upgrade(migrate_engine):
    """Add replication info to services table."""
    meta = MetaData()
    meta.bind = migrate_engine

    services = Table('services', meta, autoload=True)
    replication_status = Column('replication_status', String(length=36),
                                default="not-capable")
    active_backend_id = Column('active_backend_id', String(length=255))
    frozen = Column('frozen', Boolean, default=False)

    services.create_column(replication_status)
    services.create_column(frozen)
    services.create_column(active_backend_id)
