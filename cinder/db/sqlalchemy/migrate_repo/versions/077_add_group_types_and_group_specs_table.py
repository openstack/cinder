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

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import ForeignKey, MetaData, String, Table, UniqueConstraint


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # New table
    group_types = Table(
        'group_types',
        meta,
        Column('id', String(36), primary_key=True, nullable=False),
        Column('name', String(255), nullable=False),
        Column('description', String(255)),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean),
        Column('is_public', Boolean),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_types.create()

    # New table
    group_type_specs = Table(
        'group_type_specs',
        meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('key', String(255)),
        Column('value', String(255)),
        Column('group_type_id', String(36),
               ForeignKey('group_types.id'),
               nullable=False),
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_type_specs.create()

    # New table
    group_type_projects = Table(
        'group_type_projects', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('group_type_id', String(36),
               ForeignKey('group_types.id')),
        Column('project_id', String(length=255)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        UniqueConstraint('group_type_id', 'project_id', 'deleted'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_type_projects.create()
