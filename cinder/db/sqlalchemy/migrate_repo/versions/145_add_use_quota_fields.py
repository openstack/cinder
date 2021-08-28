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

import sqlalchemy as sa


def upgrade(migrate_engine):
    """Update volumes and snapshots tables with use_quota field.

    Add use_quota field to both volumes and snapshots table to fast and easily
    identify resources that must be counted for quota usages.
    """
    # Existing resources will be left with None value to allow rolling upgrades
    # with the online data migration pattern, since they will identify the
    # resources that don't have the field set/known yet.
    meta = sa.MetaData(bind=migrate_engine)
    for table_name in ('volumes', 'snapshots'):
        table = sa.Table(table_name, meta, autoload=True)

        if not hasattr(table.c, 'use_quota'):
            column = sa.Column('use_quota', sa.Boolean, nullable=True)
            table.create_column(column)
