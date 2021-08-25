# Copyright 2021 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from migrate.changeset import constraint
import sqlalchemy as sa


def upgrade(migrate_engine):
    """Update quota_usages table to prevent races on creation.

    Add race_preventer field and a unique constraint to prevent quota usage
    duplicates and races that mess the quota system when first creating rows.
    """
    # There's no need to set the race_preventer field for existing DB entries,
    # since the race we want to prevent is only on creation.
    meta = sa.MetaData(bind=migrate_engine)
    quota_usages = sa.Table('quota_usages', meta, autoload=True)

    if not hasattr(quota_usages.c, 'race_preventer'):
        quota_usages.create_column(
            sa.Column('race_preventer', sa.Boolean, nullable=True))

    unique = constraint.UniqueConstraint(
        'project_id', 'resource', 'race_preventer',
        table=quota_usages)
    unique.create(engine=migrate_engine)
