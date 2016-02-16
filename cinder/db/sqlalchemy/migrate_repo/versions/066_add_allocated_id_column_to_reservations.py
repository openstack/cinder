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
from sqlalchemy import MetaData, Integer, Table, ForeignKey


def upgrade(migrate_engine):
    """Add allocated_id to the reservations table."""
    meta = MetaData()
    meta.bind = migrate_engine

    reservations = Table('reservations', meta, autoload=True)
    Table('quotas', meta, autoload=True)
    allocated_id = Column('allocated_id', Integer, ForeignKey('quotas.id'),
                          nullable=True)
    reservations.create_column(allocated_id)
    usage_id = reservations.c.usage_id
    usage_id.alter(nullable=True)
