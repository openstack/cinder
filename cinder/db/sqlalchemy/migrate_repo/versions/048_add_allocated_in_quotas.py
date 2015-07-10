# Copyright 2015 Yahoo Inc.
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

from sqlalchemy import Column, Integer, MetaData, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    quotas = Table('quotas', meta, autoload=True)

    # Add a new column allocated to save allocated quota
    allocated = Column('allocated', Integer, default=0)
    quotas.create_column(allocated)


def downgrade(migrate_engine):
    """Remove allocated column from quotas."""
    meta = MetaData()
    meta.bind = migrate_engine

    quotas = Table('quotas', meta, autoload=True)
    quotas.drop_column('allocated')
