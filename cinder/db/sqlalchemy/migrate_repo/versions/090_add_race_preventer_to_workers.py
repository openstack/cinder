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

from sqlalchemy import Column, Integer, MetaData, Table, text


def upgrade(migrate_engine):
    """Add race preventer field to workers table."""
    meta = MetaData()
    meta.bind = migrate_engine

    workers = Table('workers', meta, autoload=True)
    race_preventer = Column('race_preventer', Integer, nullable=False,
                            default=0, server_default=text('0'))
    race_preventer.create(workers, populate_default=True)
