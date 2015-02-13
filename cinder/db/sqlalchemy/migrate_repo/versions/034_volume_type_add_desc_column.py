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


from sqlalchemy import Column, MetaData, Table, String


def upgrade(migrate_engine):
    """Add description column to volume_types."""
    meta = MetaData()
    meta.bind = migrate_engine

    volume_types = Table('volume_types', meta, autoload=True)
    description = Column('description', String(255))
    volume_types.create_column(description)
    volume_types.update().values(description=None).execute()


def downgrade(migrate_engine):
    """Remove description column to volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volume_types = Table('volume_types', meta, autoload=True)
    description = volume_types.columns.description
    volume_types.drop_column(description)
