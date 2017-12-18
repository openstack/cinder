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

from sqlalchemy import Boolean, Column, MetaData, Table


def upgrade(migrate_engine):
    """Add shared_targets column to Volumes."""
    meta = MetaData()
    meta.bind = migrate_engine
    volumes = Table('volumes', meta, autoload=True)

    # NOTE(jdg):  We use a default of True because it's harmless for a device
    # that does NOT use shared_targets to be treated as if it does
    if not hasattr(volumes.c, 'shared_targets'):
        volumes.create_column(Column('shared_targets', Boolean, default=True))
