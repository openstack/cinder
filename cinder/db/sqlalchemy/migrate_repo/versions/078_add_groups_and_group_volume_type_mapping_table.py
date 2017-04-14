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

import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import ForeignKey, MetaData, String, Table, func, select

# Default number of quota groups. We should not read from config file.
DEFAULT_QUOTA_GROUPS = 10

CLASS_NAME = 'default'
CREATED_AT = datetime.datetime.now()  # noqa


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # New table
    groups = Table(
        'groups',
        meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('cluster_name', String(255)),
        Column('host', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('name', String(length=255)),
        Column('description', String(length=255)),
        Column('group_type_id', String(length=36)),
        Column('status', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    groups.create()

    # Add column to volumes table
    volumes = Table('volumes', meta, autoload=True)
    group_id = Column('group_id', String(36),
                      ForeignKey('groups.id'))
    volumes.create_column(group_id)
    volumes.update().values(group_id=None).execute()

    # New group_volume_type_mapping table
    Table('volume_types', meta, autoload=True)

    grp_vt_mapping = Table(
        'group_volume_type_mapping', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_type_id', String(36), ForeignKey('volume_types.id'),
               nullable=False),
        Column('group_id', String(36),
               ForeignKey('groups.id'), nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    grp_vt_mapping.create()

    # Add group quota data into DB.
    quota_classes = Table('quota_classes', meta, autoload=True)

    rows = select([func.count()]).select_from(quota_classes).where(
        quota_classes.c.resource == 'groups').execute().scalar()

    # Do not add entries if there are already 'groups' entries.
    if rows:
        return

    # Set groups
    qci = quota_classes.insert()
    qci.execute({'created_at': CREATED_AT,
                 'class_name': CLASS_NAME,
                 'resource': 'groups',
                 'hard_limit': DEFAULT_QUOTA_GROUPS,
                 'deleted': False, })
