# Copyright (C) 2013 eBay Inc.
# Copyright (C) 2013 OpenStack Foundation
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
from migrate import ForeignKeyConstraint

from cinder.i18n import _
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    """Add volume_type_rate_limit table."""
    meta = MetaData()
    meta.bind = migrate_engine

    quality_of_service_specs = Table(
        'quality_of_service_specs', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('id', String(36), primary_key=True, nullable=False),
        Column('specs_id', String(36),
               ForeignKey('quality_of_service_specs.id')),
        Column('key', String(255)),
        Column('value', String(255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    try:
        quality_of_service_specs.create()
    except Exception:
        LOG.error(_("Table quality_of_service_specs not created!"))
        raise

    volume_types = Table('volume_types', meta, autoload=True)
    qos_specs_id = Column('qos_specs_id', String(36),
                          ForeignKey('quality_of_service_specs.id'))

    try:
        volume_types.create_column(qos_specs_id)
        volume_types.update().values(qos_specs_id=None).execute()
    except Exception:
        LOG.error(_("Added qos_specs_id column to volume type table failed."))
        raise


def downgrade(migrate_engine):
    """Remove volume_type_rate_limit table."""
    meta = MetaData()
    meta.bind = migrate_engine

    qos_specs = Table('quality_of_service_specs', meta, autoload=True)

    if migrate_engine.name == 'mysql':
        # NOTE(alanmeadows): MySQL Cannot drop column qos_specs_id
        # until the foreign key volumes_types_ibfk_1 is removed.  We
        # remove the foreign key first, and then we drop the column.
        table = Table('volume_types', meta, autoload=True)
        ref_table = Table('volume_types', meta, autoload=True)
        params = {'columns': [table.c['qos_specs_id']],
                  'refcolumns': [ref_table.c['id']],
                  'name': 'volume_types_ibfk_1'}

        try:
            fkey = ForeignKeyConstraint(**params)
            fkey.drop()
        except Exception:
            LOG.error(_("Dropping foreign key volume_types_ibfk_1 failed"))

    volume_types = Table('volume_types', meta, autoload=True)
    qos_specs_id = Column('qos_specs_id', String(36))

    try:
        volume_types.drop_column(qos_specs_id)
    except Exception:
        LOG.error(_("Dropping qos_specs_id column failed."))
        raise

    try:
        qos_specs.drop()

    except Exception:
        LOG.error(_("Dropping quality_of_service_specs table failed."))
        raise
