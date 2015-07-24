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
from sqlalchemy import Integer, MetaData, String, Table, ForeignKey


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    Table('volumes', meta, autoload=True)

    # New table
    volume_admin_metadata = Table(
        'volume_admin_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_id', String(length=36), ForeignKey('volumes.id'),
               nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_admin_metadata.create()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    volume_admin_metadata = Table('volume_admin_metadata',
                                  meta,
                                  autoload=True)
    volume_admin_metadata.drop()
