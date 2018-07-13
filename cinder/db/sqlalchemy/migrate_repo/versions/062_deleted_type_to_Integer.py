#   Licensed under the Apache License, Version 2.0 (the "License"); you may
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

from sqlalchemy import Integer
from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    """Deleted col of volume_type_projects converted(tinyint->Int)."""
    meta = MetaData()
    meta.bind = migrate_engine

    volume_type_projects = Table('volume_type_projects', meta, autoload=True)

    if migrate_engine.name == 'postgresql':
        # NOTE: PostgreSQL can't cast Boolean to int automatically
        sql = 'ALTER TABLE volume_type_projects ALTER COLUMN deleted ' + \
              'TYPE INTEGER USING deleted::integer'
        migrate_engine.execute(sql)
    else:
        volume_type_projects.c.deleted.alter(Integer)
