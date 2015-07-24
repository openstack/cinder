# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
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

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import MetaData, Integer, String, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # New table
    backups = Table(
        'backups', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('volume_id', String(36), nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('host', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('container', String(length=255)),
        Column('status', String(length=255)),
        Column('fail_reason', String(length=255)),
        Column('service_metadata', String(length=255)),
        Column('service', String(length=255)),
        Column('size', Integer()),
        Column('object_count', Integer()),
        mysql_engine='InnoDB'
    )

    backups.create()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    backups = Table('backups', meta, autoload=True)
    backups.drop()
