# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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

from sqlalchemy import Column, ForeignKey, MetaData, Table
from sqlalchemy import Boolean, DateTime, Integer, String

from cinder.i18n import _
from cinder.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    # encryption key UUID -- must be stored per volume
    volumes = Table('volumes', meta, autoload=True)
    encryption_key = Column('encryption_key_id', String(36))
    try:
        volumes.create_column(encryption_key)
    except Exception:
        LOG.error(_("Column |%s| not created!"), repr(encryption_key))
        raise

    # encryption key UUID and volume type id -- must be stored per snapshot
    snapshots = Table('snapshots', meta, autoload=True)
    encryption_key = Column('encryption_key_id', String(36))
    try:
        snapshots.create_column(encryption_key)
    except Exception:
        LOG.error(_("Column |%s| not created!"), repr(encryption_key))
        raise
    volume_type = Column('volume_type_id', String(36))
    try:
        snapshots.create_column(volume_type)
    except Exception:
        LOG.error(_("Column |%s| not created!"), repr(volume_type))
        raise

    volume_types = Table('volume_types', meta, autoload=True)

    # encryption types associated with particular volume type
    encryption = Table(
        'encryption', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('cipher', String(length=255)),
        Column('control_location', String(length=255), nullable=False),
        Column('key_size', Integer),
        Column('provider', String(length=255), nullable=False),
        # NOTE(joel-coffman): The volume_type_id must be unique or else the
        # referenced volume type becomes ambiguous. That is, specifying the
        # volume type is not sufficient to identify a particular encryption
        # scheme unless each volume type is associated with at most one
        # encryption scheme.
        Column('volume_type_id', String(length=36),
               ForeignKey(volume_types.c.id),
               primary_key=True, nullable=False),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    try:
        encryption.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(encryption))
        raise


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    # drop encryption key UUID for volumes
    volumes = Table('volumes', meta, autoload=True)
    try:
        volumes.c.encryption_key_id.drop()
    except Exception:
        LOG.error(_("encryption_key_id column not dropped from volumes"))
        raise

    # drop encryption key UUID and volume type id for snapshots
    snapshots = Table('snapshots', meta, autoload=True)
    try:
        snapshots.c.encryption_key_id.drop()
    except Exception:
        LOG.error(_("encryption_key_id column not dropped from snapshots"))
        raise
    try:
        snapshots.c.volume_type_id.drop()
    except Exception:
        LOG.error(_("volume_type_id column not dropped from snapshots"))
        raise

    # drop encryption types table
    encryption = Table('encryption', meta, autoload=True)
    try:
        encryption.drop()
    except Exception:
        LOG.error(_("encryption table not dropped"))
        raise
