# Copyright (C) 2015 Pure Storage, Inc.
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

from sqlalchemy import Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # New table
    image_volume_cache = Table(
        'image_volume_cache_entries', meta,
        Column('image_updated_at', DateTime(timezone=False)),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255), index=True, nullable=False),
        Column('image_id', String(length=36), index=True, nullable=False),
        Column('volume_id', String(length=36), nullable=False),
        Column('size', Integer, nullable=False),
        Column('last_used', DateTime, nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    image_volume_cache.create()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    table_name = 'image_volume_cache_entries'
    image_volume_cache = Table(table_name, meta, autoload=True)

    image_volume_cache.drop()
