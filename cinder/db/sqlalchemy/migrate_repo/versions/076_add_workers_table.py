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
from migrate.changeset.constraint import ForeignKeyConstraint


def upgrade(migrate_engine):
    """Add workers table."""
    meta = MetaData()
    meta.bind = migrate_engine

    workers = Table(
        'workers', meta,
        # Inherited fields from CinderBase
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(), default=False),

        # Workers table specific fields
        Column('id', Integer, primary_key=True),
        Column('resource_type', String(40), nullable=False),
        Column('resource_id', String(36), nullable=False),
        Column('status', String(255), nullable=False),
        Column('service_id', Integer, nullable=True),
        UniqueConstraint('resource_type', 'resource_id'),

        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    workers.create()

    services = Table('services', meta, autoload=True)

    ForeignKeyConstraint(
        columns=[workers.c.service_id],
        refcolumns=[services.c.id]).create()
