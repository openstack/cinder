# Copyright 2010 OpenStack Foundation
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

import datetime

from cinder import exception as exc

FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FAKE_UUIDS = {}


def stub_volume(id, **kwargs):
    volume = {
        'id': id,
        'user_id': 'fakeuser',
        'project_id': 'fakeproject',
        'host': 'fakehost',
        'size': 1,
        'availability_zone': 'fakeaz',
        'attached_mode': 'rw',
        'status': 'fakestatus',
        'migration_status': None,
        'attach_status': 'attached',
        'bootable': 'false',
        'name': 'vol name',
        'display_name': 'displayname',
        'display_description': 'displaydesc',
        'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
        'snapshot_id': None,
        'source_volid': None,
        'volume_type_id': '3e196c20-3c06-11e2-81c1-0800200c9a66',
        'volume_metadata': [],
        'volume_type': {'name': 'vol_type_name'},
        'volume_attachment': [],
        'multiattach': False,
        'readonly': 'False'}

    volume.update(kwargs)
    return volume


def stub_volume_create(self, context, size, name, description, snapshot,
                       **param):
    vol = stub_volume('1')
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    vol['source_volid'] = None
    try:
        vol['snapshot_id'] = snapshot['id']
    except (KeyError, TypeError):
        vol['snapshot_id'] = None
    vol['availability_zone'] = param.get('availability_zone', 'fakeaz')
    return vol


def stub_volume_create_from_image(self, context, size, name, description,
                                  snapshot, volume_type, metadata,
                                  availability_zone):
    vol = stub_volume('1')
    vol['status'] = 'creating'
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    vol['availability_zone'] = 'cinder'
    return vol


def stub_volume_update(self, context, *args, **param):
    pass


def stub_volume_delete(self, context, *args, **param):
    pass


def stub_volume_get(self, context, volume_id):
    return stub_volume(volume_id)


def stub_volume_get_notfound(self, context, volume_id):
    raise exc.NotFound


def stub_volume_get_all(context, search_opts=None):
    return [stub_volume(100, project_id='fake'),
            stub_volume(101, project_id='superfake'),
            stub_volume(102, project_id='superduperfake')]


def stub_volume_get_all_by_project(self, context, search_opts=None):
    return [stub_volume_get(self, context, '1')]


def stub_snapshot(id, **kwargs):
    snapshot = {'id': id,
                'volume_id': 12,
                'status': 'available',
                'volume_size': 100,
                'created_at': None,
                'display_name': 'Default name',
                'display_description': 'Default description',
                'project_id': 'fake'}

    snapshot.update(kwargs)
    return snapshot


def stub_snapshot_get_all(self):
    return [stub_snapshot(100, project_id='fake'),
            stub_snapshot(101, project_id='superfake'),
            stub_snapshot(102, project_id='superduperfake')]


def stub_snapshot_get_all_by_project(self, context):
    return [stub_snapshot(1)]


def stub_snapshot_update(self, context, *args, **param):
    pass


def stub_service_get_all_by_topic(context, topic):
    return [{'availability_zone': "zone1:host1", "disabled": 0}]
