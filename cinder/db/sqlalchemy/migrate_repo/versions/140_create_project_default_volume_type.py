# Copyright 2020 Red Hat, Inc.
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
from sqlalchemy import MetaData, String, Table, ForeignKey


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # This is required to establish foreign key dependency between
    # volume_type_id and volume_types.id columns. See L#34-35
    Table('volume_types', meta, autoload=True)

    default_volume_types = Table(
        'default_volume_types', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('volume_type_id', String(36),
               ForeignKey('volume_types.id'), index=True),
        Column('project_id', String(length=255), primary_key=True,
               nullable=False),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    try:
        default_volume_types.create()
    except Exception:
        raise
