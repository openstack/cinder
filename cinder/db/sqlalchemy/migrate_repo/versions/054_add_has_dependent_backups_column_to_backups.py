# Copyright (c) 2015 Huawei Technologies Co., Ltd.
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

from sqlalchemy import Column, Integer, MetaData, Table


def upgrade(migrate_engine):
    """Add num_dependent_backups column to backups."""
    meta = MetaData()
    meta.bind = migrate_engine

    backups = Table('backups', meta, autoload=True)
    num_dependent_backups = Column('num_dependent_backups', Integer, default=0)
    backups.create_column(num_dependent_backups)
    backups_list = list(backups.select().execute())
    for backup in backups_list:
        dep_bks_list = list(backups.select().where(backups.columns.parent_id ==
                                                   backup.id).execute())
        if dep_bks_list:
            backups.update().where(backups.columns.id == backup.id).values(
                num_dependent_backups=len(dep_bks_list)).execute()


def downgrade(migrate_engine):
    """Remove num_dependent_backups column to backups."""
    meta = MetaData()
    meta.bind = migrate_engine

    backups = Table('backups', meta, autoload=True)
    num_dependent_backups = backups.columns.num_dependent_backups

    backups.drop_column(num_dependent_backups)
