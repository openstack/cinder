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

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table, UniqueConstraint


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # New cluster table
    cluster = Table(
        'clusters', meta,
        # Inherited fields from CinderBase
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(), default=False),

        # Cluster specific fields
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(255), nullable=False),
        Column('binary', String(255), nullable=False),
        Column('disabled', Boolean(), default=False),
        Column('disabled_reason', String(255)),
        Column('race_preventer', Integer, nullable=False, default=0),

        # To remove potential races on creation we have a constraint set on
        # name and race_preventer fields, and we set value on creation to 0, so
        # 2 clusters with the same name will fail this constraint.  On deletion
        # we change this field to the same value as the id which will be unique
        # and will not conflict with the creation of another cluster with the
        # same name.
        UniqueConstraint('name', 'binary', 'race_preventer'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    cluster.create()

    # Add the cluster flag to Service, ConsistencyGroup, and Volume tables.
    for table_name in ('services', 'consistencygroups', 'volumes'):
        table = Table(table_name, meta, autoload=True)
        cluster_name = Column('cluster_name', String(255), nullable=True)
        table.create_column(cluster_name)
