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

from sqlalchemy import Column, DateTime, Text, Boolean
from sqlalchemy import MetaData, Integer, String, Table, ForeignKey

from cinder.i18n import _
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # Just for the ForeignKey and column creation to succeed, these are not the
    # actual definitions of tables .
    #
    Table('volumes',
          meta,
          Column('id', Integer(), primary_key=True, nullable=False),
          mysql_engine='InnoDB')
    Table('snapshots',
          meta,
          Column('id', Integer(), primary_key=True, nullable=False),
          mysql_engine='InnoDB')
    # Create new table
    volume_glance_metadata = Table(
        'volume_glance_metadata',
        meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('volume_id', String(length=36), ForeignKey('volumes.id')),
        Column('snapshot_id', String(length=36),
               ForeignKey('snapshots.id')),
        Column('key', String(255)),
        Column('value', Text),
        mysql_engine='InnoDB'
    )

    try:
        volume_glance_metadata.create()
    except Exception:
        LOG.exception(_("Exception while creating table "
                        "'volume_glance_metadata'"))
        meta.drop_all(tables=[volume_glance_metadata])
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    volume_glance_metadata = Table('volume_glance_metadata',
                                   meta, autoload=True)
    try:
        volume_glance_metadata.drop()
    except Exception:
        LOG.error(_("volume_glance_metadata table not dropped"))
        raise
