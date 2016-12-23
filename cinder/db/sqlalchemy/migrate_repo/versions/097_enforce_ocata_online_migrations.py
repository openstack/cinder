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

from sqlalchemy import MetaData, Table, func, select

from cinder import exception
from cinder.i18n import _


WARNING_MSG = _('There are still %(count)i unmigrated records in '
                'the %(table)s table. Migration cannot continue '
                'until all records have been migrated.')


def upgrade(migrate_engine):
    meta = MetaData(migrate_engine)

    # CGs to Generic Volume Groups transition
    consistencygroups = Table('consistencygroups', meta, autoload=True)
    cgsnapshots = Table('cgsnapshots', meta, autoload=True)
    for table in (consistencygroups, cgsnapshots):
        count = select([func.count()]).select_from(table).where(
            table.c.deleted == False).execute().scalar()  # NOQA
        if count > 0:
            msg = WARNING_MSG % {
                'count': count,
                'table': table.name,
            }
            raise exception.ValidationError(detail=msg)

    # VOLUME_ prefix addition in message IDs
    messages = Table('messages', meta, autoload=True)
    count = select([func.count()]).select_from(messages).where(
        (messages.c.deleted == False) &
        (~messages.c.event_id.like('VOLUME_%'))).execute().scalar()  # NOQA
    if count > 0:
        msg = WARNING_MSG % {
            'count': count,
            'table': 'messages',
        }
        raise exception.ValidationError(detail=msg)
