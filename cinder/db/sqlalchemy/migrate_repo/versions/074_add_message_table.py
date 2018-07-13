#   Licensed under the Apache License, Version 2.0 (the "License"); you may
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
from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # New table
    messages = Table(
        'messages',
        meta,
        Column('id', String(36), primary_key=True, nullable=False),
        Column('project_id', String(36), nullable=False),
        Column('request_id', String(255), nullable=False),
        Column('resource_type', String(36)),
        Column('resource_uuid', String(255), nullable=True),
        Column('event_id', String(255), nullable=False),
        Column('message_level', String(255), nullable=False),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean),
        Column('expires_at', DateTime(timezone=False)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    messages.create()
