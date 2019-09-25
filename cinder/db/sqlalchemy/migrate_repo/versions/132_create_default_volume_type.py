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

import uuid

from oslo_utils import timeutils
import six
from sqlalchemy import MetaData, Table

from cinder.volume import volume_types


def upgrade(migrate_engine):
    """Create default volume type"""

    meta = MetaData(bind=migrate_engine)
    now = timeutils.utcnow()

    # create a default volume type during cinder DB migration
    vtypes = Table("volume_types", meta, autoload=True)
    results = list(vtypes.select().where(
        vtypes.c.name == volume_types.DEFAULT_VOLUME_TYPE and
        vtypes.c.deleted is False).execute())
    if not results:
        vtype_id = six.text_type(uuid.uuid4())
        volume_type_dict = {
            'id': vtype_id,
            'name': volume_types.DEFAULT_VOLUME_TYPE,
            'description': 'Default Volume Type',
            'created_at': now,
            'updated_at': now,
            'deleted': False,
            'is_public': True,
        }
        vtype = vtypes.insert()
        vtype.execute(volume_type_dict)
