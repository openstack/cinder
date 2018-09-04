# Copyright 2018 SAP SE
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from migrate.changeset.constraint import UniqueConstraint
from sqlalchemy import MetaData, Table
from sqlalchemy import select, join, and_
from oslo_log import log as logging

LOG = logging.getLogger(__name__)
META = MetaData()


def quota_usages_table(migrate_engine):
    global META
    META.bind = migrate_engine

    return Table('quota_usages', META, autoload=True)


def _build_constraint(migrate_engine, quota_usages=None):
    if quota_usages is None:
        quota_usages = quota_usages_table(migrate_engine)
    return UniqueConstraint(
        'project_id', 'resource', 'deleted',
        table=quota_usages,
    )


def upgrade(migrate_engine):
    global META
    quota_usages = quota_usages_table(migrate_engine)

    qu1 = quota_usages.alias('qu1')
    qu2 = quota_usages.alias('qu2')
    duplicates = select([qu1.c.id]).select_from(join(
        qu1, qu2,
        onclause=and_(
            qu1.c.project_id == qu2.c.project_id,
            qu1.c.resource == qu2.c.resource,
            qu1.c.deleted == qu2.c.deleted,
        )
    )).where(
        qu1.c.id > qu2.c.id
    )

    reservations = Table('reservations', META, autoload=True)

    query = reservations.delete(
        whereclause=and_(reservations.c.usage_id.in_(duplicates),
                         reservations.c.deleted)
    )

    migrate_engine.execute(query)

    query = quota_usages.delete(
        whereclause=quota_usages.c.id.in_(duplicates)
    )

    migrate_engine.execute(query)
    cons = _build_constraint(migrate_engine, quota_usages=quota_usages)
    cons.create()


def downgrade(migrate_engine):
    cons = _build_constraint(migrate_engine)
    cons.drop()
