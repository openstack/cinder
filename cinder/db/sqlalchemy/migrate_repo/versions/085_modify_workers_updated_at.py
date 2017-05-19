# Copyright (c) 2016 Red Hat, Inc.
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

from oslo_utils import timeutils
from sqlalchemy.dialects import mysql
from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    """Add microseconds precision on updated_at field in MySQL databases.

    PostgreSQL, SQLite, and MSSQL have sub-second precision by default, but
    MySQL defaults to second precision in DateTime fields, which creates
    problems for the resource cleanup mechanism.
    """
    meta = MetaData()
    meta.bind = migrate_engine
    workers = Table('workers', meta, autoload=True)

    # This is only necessary for mysql, and since the table is not in use this
    # will only be an schema update.
    if migrate_engine.name.startswith('mysql'):
        try:
            workers.c.updated_at.alter(mysql.DATETIME(fsp=6))
        except Exception:
            # MySQL v5.5 or earlier don't support sub-second resolution so we
            # may have cleanup races in Active-Active configurations, that's
            # why upgrading is recommended in that case.
            # Code in Cinder is capable of working with 5.5, so for 5.5 there's
            # no problem
            pass

    # TODO(geguileo): Once we remove support for MySQL 5.5 we have to create
    # an upgrade migration to remove this row.
    # Set workers table sub-second support sentinel
    wi = workers.insert()
    now = timeutils.utcnow().replace(microsecond=123)
    wi.execute({'created_at': now,
                'updated_at': now,
                'deleted': False,
                'resource_type': 'SENTINEL',
                'resource_id': 'SUB-SECOND',
                'status': 'OK'})
