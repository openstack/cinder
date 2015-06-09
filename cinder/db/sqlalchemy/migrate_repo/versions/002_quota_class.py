# Copyright 2012 OpenStack Foundation
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

from migrate import ForeignKeyConstraint
from oslo_log import log as logging
from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import MetaData, Integer, String, Table, ForeignKey

from cinder.i18n import _LE

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # New table
    quota_classes = Table('quota_classes', meta,
                          Column('created_at', DateTime(timezone=False)),
                          Column('updated_at', DateTime(timezone=False)),
                          Column('deleted_at', DateTime(timezone=False)),
                          Column('deleted', Boolean(create_constraint=True,
                                                    name=None)),
                          Column('id', Integer(), primary_key=True),
                          Column('class_name',
                                 String(length=255),
                                 index=True),
                          Column('resource',
                                 String(length=255)),
                          Column('hard_limit', Integer(), nullable=True),
                          mysql_engine='InnoDB',
                          mysql_charset='utf8',
                          )

    try:
        quota_classes.create()
    except Exception:
        LOG.error(_LE("Table |%s| not created!"), repr(quota_classes))
        raise

    quota_usages = Table('quota_usages', meta,
                         Column('created_at', DateTime(timezone=False)),
                         Column('updated_at', DateTime(timezone=False)),
                         Column('deleted_at', DateTime(timezone=False)),
                         Column('deleted', Boolean(create_constraint=True,
                                                   name=None)),
                         Column('id', Integer(), primary_key=True),
                         Column('project_id',
                                String(length=255),
                                index=True),
                         Column('resource',
                                String(length=255)),
                         Column('in_use', Integer(), nullable=False),
                         Column('reserved', Integer(), nullable=False),
                         Column('until_refresh', Integer(), nullable=True),
                         mysql_engine='InnoDB',
                         mysql_charset='utf8',
                         )

    try:
        quota_usages.create()
    except Exception:
        LOG.error(_LE("Table |%s| not created!"), repr(quota_usages))
        raise

    reservations = Table('reservations', meta,
                         Column('created_at', DateTime(timezone=False)),
                         Column('updated_at', DateTime(timezone=False)),
                         Column('deleted_at', DateTime(timezone=False)),
                         Column('deleted', Boolean(create_constraint=True,
                                                   name=None)),
                         Column('id', Integer(), primary_key=True),
                         Column('uuid',
                                String(length=36),
                                nullable=False),
                         Column('usage_id',
                                Integer(),
                                ForeignKey('quota_usages.id'),
                                nullable=False),
                         Column('project_id',
                                String(length=255),
                                index=True),
                         Column('resource',
                                String(length=255)),
                         Column('delta', Integer(), nullable=False),
                         Column('expire', DateTime(timezone=False)),
                         mysql_engine='InnoDB',
                         mysql_charset='utf8',
                         )

    try:
        reservations.create()
    except Exception:
        LOG.error(_LE("Table |%s| not created!"), repr(reservations))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    fk_name = None

    if migrate_engine.name == 'mysql':
        fk_name = 'reservations_ibfk_1'
    elif migrate_engine.name == 'postgresql':
        fk_name = 'reservations_usage_id_fkey'

    # NOTE: MySQL and PostgreSQL Cannot drop the quota_usages table
    # until the foreign key is removed.  We remove the foreign key first,
    # and then we drop the table.
    table = Table('reservations', meta, autoload=True)
    ref_table = Table('reservations', meta, autoload=True)
    params = {'columns': [table.c['usage_id']],
              'refcolumns': [ref_table.c['id']],
              'name': fk_name}

    if fk_name:
        try:
            fkey = ForeignKeyConstraint(**params)
            fkey.drop()
        except Exception:
            LOG.error(_LE("Dropping foreign key %s failed."), fk_name)

    quota_classes = Table('quota_classes', meta, autoload=True)
    try:
        quota_classes.drop()
    except Exception:
        LOG.error(_LE("quota_classes table not dropped"))
        raise

    quota_usages = Table('quota_usages', meta, autoload=True)
    try:
        quota_usages.drop()
    except Exception:
        LOG.error(_LE("quota_usages table not dropped"))
        raise

    reservations = Table('reservations', meta, autoload=True)
    try:
        reservations.drop()
    except Exception:
        LOG.error(_LE("reservations table not dropped"))
        raise
