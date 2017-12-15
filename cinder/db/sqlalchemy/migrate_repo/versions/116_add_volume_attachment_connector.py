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

from sqlalchemy import Text, Column, MetaData, Table


def upgrade(migrate_engine):
    """Add the connector column to the volume_attachment table."""
    meta = MetaData(bind=migrate_engine)
    volume_attachment = Table('volume_attachment', meta, autoload=True)
    if not hasattr(volume_attachment.c, 'connector'):
        volume_attachment.create_column(Column('connector', Text))
