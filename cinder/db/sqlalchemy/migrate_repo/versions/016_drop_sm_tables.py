# Copyright 2013 OpenStack Foundation
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

from oslo_log import log as logging
from sqlalchemy import Boolean, Column, DateTime, ForeignKey
from sqlalchemy import Integer, MetaData, String, Table

from cinder.i18n import _

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    sm_backend_config = Table('sm_backend_config', meta, autoload=True)
    sm_flavors = Table('sm_flavors', meta, autoload=True)
    sm_volume = Table('sm_volume', meta, autoload=True)

    tables = [sm_volume, sm_backend_config, sm_flavors]

    for table in tables:
        try:
            table.drop()
        except Exception:
            LOG.exception(_('Exception while dropping table %s.'),
                          repr(table))
            raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    Table('volumes', meta, autoload=True)

    sm_backend_config = Table(
        'sm_backend_config', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('flavor_id', Integer, ForeignKey('sm_flavors.id'),
               nullable=False),
        Column('sr_uuid', String(length=255)),
        Column('sr_type', String(length=255)),
        Column('config_params', String(length=2047)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    sm_flavors = Table(
        'sm_flavors', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('label', String(length=255)),
        Column('description', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    sm_volume = Table(
        'sm_volume', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=36),
               ForeignKey('volumes.id'),
               primary_key=True,
               nullable=False),
        Column('backend_id', Integer, ForeignKey('sm_backend_config.id'),
               nullable=False),
        Column('vdi_uuid', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    tables = [sm_flavors, sm_backend_config, sm_volume]

    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.exception(_('Exception while creating table %s.'),
                          repr(table))
            raise
