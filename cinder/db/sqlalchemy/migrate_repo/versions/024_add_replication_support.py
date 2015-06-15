# Copyright 2014 IBM Corp.
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

from sqlalchemy import Column
from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    """Add replication columns to volumes."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    replication_status = Column('replication_status', String(255))
    replication_extended_status = Column('replication_extended_status',
                                         String(255))
    replication_driver_data = Column('replication_driver_data', String(255))
    volumes.create_column(replication_status)
    volumes.create_column(replication_extended_status)
    volumes.create_column(replication_driver_data)
    volumes.update().values(replication_status='disabled',
                            replication_extended_status=None,
                            replication_driver_data=None).execute()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    replication_status = volumes.columns.replication_status
    replication_extended_status = volumes.columns.replication_extended_status
    replication_driver_data = volumes.columns.replication_driver_data
    volumes.drop_column(replication_status)
    volumes.drop_column(replication_extended_status)
    volumes.drop_column(replication_driver_data)
