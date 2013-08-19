#    Copyright 2013 IBM Corp.
#
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


from sqlalchemy import String, Column, MetaData, Table


def upgrade(migrate_engine):
    """Add migration_status column to volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    migration_status = Column('migration_status', String(255))
    volumes.create_column(migration_status)


def downgrade(migrate_engine):
    """Remove migration_status column from volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    migration_status = volumes.columns.migration_status
    volumes.drop_column(migration_status)
