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

import sqlalchemy as sa


def upgrade(migrate_engine):
    meta = sa.MetaData()
    meta.bind = migrate_engine

    # This is required to establish foreign key dependency between
    # volume_type_id and volume_types.id columns. See L#34-35
    sa.Table('volume_types', meta, autoload=True)

    default_volume_types = sa.Table(
        'default_volume_types', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('deleted_at', sa.DateTime),
        sa.Column(
            'volume_type_id',
            sa.String(36),
            sa.ForeignKey('volume_types.id'),
            index=True),
        sa.Column(
            'project_id',
            sa.String(length=255),
            primary_key=True,
            nullable=False),
        sa.Column('deleted', sa.Boolean(create_constraint=True, name=None)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    try:
        default_volume_types.create()
    except Exception:
        raise
