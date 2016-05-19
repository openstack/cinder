# Copyright (C) 2016 EMC Corporation.
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
from sqlalchemy import ForeignKey, MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    groups = Table('groups', meta, autoload=True)

    # New table
    group_snapshots = Table(
        'group_snapshots', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', String(36), primary_key=True),
        Column('group_id', String(36),
               ForeignKey('groups.id'),
               nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('name', String(length=255)),
        Column('description', String(length=255)),
        Column('status', String(length=255)),
        Column('group_type_id', String(length=36)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_snapshots.create()

    # Add group_snapshot_id column to snapshots table
    snapshots = Table('snapshots', meta, autoload=True)
    group_snapshot_id = Column('group_snapshot_id', String(36),
                               ForeignKey('group_snapshots.id'))

    snapshots.create_column(group_snapshot_id)
    snapshots.update().values(group_snapshot_id=None).execute()

    # Add group_snapshot_id column to groups table
    group_snapshot_id = Column('group_snapshot_id', String(36))
    groups.create_column(group_snapshot_id)

    # Add source_group_id column to groups table
    source_group_id = Column('source_group_id', String(36))
    groups.create_column(source_group_id)
