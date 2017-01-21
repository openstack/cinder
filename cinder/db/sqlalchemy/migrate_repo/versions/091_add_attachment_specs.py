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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    """Add attachment_specs table."""

    meta = MetaData()
    meta.bind = migrate_engine
    Table('volume_attachment', meta, autoload=True)

    attachment_specs = Table(
        'attachment_specs', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(), default=False),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('attachment_id', String(36),
               ForeignKey('volume_attachment.id'),
               nullable=False),
        Column('key', String(255)),
        Column('value', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    attachment_specs.create()
