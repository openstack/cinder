# Copyright (C) 2015 SimpliVity Corp.
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

from sqlalchemy import Column
from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    services = Table('services', meta, autoload=True)
    rpc_current_version = Column('rpc_current_version', String(36))
    rpc_available_version = Column('rpc_available_version', String(36))
    object_current_version = Column('object_current_version', String(36))
    object_available_version = Column('object_available_version', String(36))
    services.create_column(rpc_current_version)
    services.create_column(rpc_available_version)
    services.create_column(object_current_version)
    services.create_column(object_available_version)
    services.update().values(rpc_current_version=None).execute()
    services.update().values(rpc_available_version=None).execute()
    services.update().values(object_current_version=None).execute()
    services.update().values(object_available_version=None).execute()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    services = Table('services', meta, autoload=True)
    rpc_current_version = services.columns.rpc_current_version
    rpc_available_version = services.columns.rpc_available_version
    object_current_version = services.columns.object_current_version
    object_available_version = services.columns.object_available_version
    services.drop_column(rpc_current_version)
    services.drop_column(rpc_available_version)
    services.drop_column(object_current_version)
    services.drop_column(object_available_version)
