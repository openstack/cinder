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

from sqlalchemy import Boolean, Column, MetaData, Table


def upgrade(migrate_engine):
    """Add the no_snapshots column to the transfers table."""
    meta = MetaData(bind=migrate_engine)
    transfers = Table('transfers', meta, autoload=True)
    if not hasattr(transfers.c, 'no_snapshots'):
        transfers.create_column(Column('no_snapshots', Boolean, default=False))
