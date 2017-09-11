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

import datetime
import iso8601

from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder import utils

FAKE_UUID = fake.OBJECT_ID
DEFAULT_VOL_NAME = "displayname"
DEFAULT_VOL_DESCRIPTION = "displaydesc"
DEFAULT_VOL_SIZE = 1
DEFAULT_VOL_TYPE = "vol_type_name"
DEFAULT_VOL_STATUS = "fakestatus"
DEFAULT_VOL_ID = fake.VOLUME_ID
DEFAULT_AZ = "fakeaz"


def fake_message(id, **kwargs):
    message = {
        'id': id,
        'action_id': "002",
        'detail_id': "001",
        'event_id': "VOLUME_VOLUME_002_001",
        'message_level': "ERROR",
        'request_id': FAKE_UUID,
        'updated_at': datetime.datetime(1900, 1, 1, 1, 1, 1,
                                        tzinfo=iso8601.UTC),
        'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1,
                                        tzinfo=iso8601.UTC),
        'expires_at': datetime.datetime(1900, 1, 1, 1, 1, 1,
                                        tzinfo=iso8601.UTC),
    }

    message.update(kwargs)
    return message


def fake_message_get(self, context, message_id):
    return fake_message(message_id)


def create_volume(id, **kwargs):
    volume = {
        'id': id,
        'user_id': fake.USER_ID,
        'project_id': fake.PROJECT_ID,
        'host': 'fakehost',
        'size': DEFAULT_VOL_SIZE,
        'availability_zone': DEFAULT_AZ,
        'status': DEFAULT_VOL_STATUS,
        'migration_status': None,
        'attach_status': 'attached',
        'name': 'vol name',
        'display_name': DEFAULT_VOL_NAME,
        'display_description': DEFAULT_VOL_DESCRIPTION,
        'updated_at': datetime.datetime(1900, 1, 1, 1, 1, 1,
                                        tzinfo=iso8601.UTC),
        'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1,
                                        tzinfo=iso8601.UTC),
        'snapshot_id': None,
        'source_volid': None,
        'volume_type_id': '3e196c20-3c06-11e2-81c1-0800200c9a66',
        'encryption_key_id': None,
        'volume_admin_metadata': [{'key': 'attached_mode', 'value': 'rw'},
                                  {'key': 'readonly', 'value': 'False'}],
        'bootable': False,
        'launched_at': datetime.datetime(1900, 1, 1, 1, 1, 1,
                                         tzinfo=iso8601.UTC),
        'volume_type': fake_volume.fake_db_volume_type(name=DEFAULT_VOL_TYPE),
        'replication_status': 'disabled',
        'replication_extended_status': None,
        'replication_driver_data': None,
        'volume_attachment': [],
        'multiattach': False,
        'group_id': fake.GROUP_ID,
    }

    volume.update(kwargs)
    if kwargs.get('volume_glance_metadata', None):
        volume['bootable'] = True
    if kwargs.get('attach_status') == 'detached':
        del volume['volume_admin_metadata'][0]
    return volume


def fake_volume_create(self, context, size, name, description, snapshot=None,
                       group_id=None, **param):
    vol = create_volume(DEFAULT_VOL_ID)
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    source_volume = param.get('source_volume') or {}
    vol['source_volid'] = source_volume.get('id')
    vol['bootable'] = False
    vol['volume_attachment'] = []
    vol['multiattach'] = utils.get_bool_param('multiattach', param)
    try:
        vol['snapshot_id'] = snapshot['id']
    except (KeyError, TypeError):
        vol['snapshot_id'] = None
    vol['availability_zone'] = param.get('availability_zone', 'fakeaz')
    if group_id:
        vol['group_id'] = group_id
    return vol
