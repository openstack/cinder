# Copyright 2014 TrilioData, Inc
# Copyright (c) 2015 EMC Corporation
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

from oslo_log import log as logging
from sqlalchemy import Column, MetaData, String, Table

from cinder.i18n import _LE

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    backups = Table('backups', meta, autoload=True)
    time_stamp = Column('time_stamp', String(length=255))

    try:
        backups.create_column(time_stamp)
        backups.update().values(time_stamp=None).execute()
    except Exception:
        LOG.error(_LE("Adding time_stamp column to backups table failed."))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    backups = Table('backups', meta, autoload=True)
    time_stamp = backups.columns.time_stamp

    try:
        backups.drop_column(time_stamp)
    except Exception:
        LOG.error(_LE("Dropping time_stamp column from backups table failed."))
        raise
