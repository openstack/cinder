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
        'status': 'fakestatus',
        'migration_status': None,
        'attach_status': 'attached',
        'bootable': 'false',
        'name': 'vol name',
        'display_name': 'displayname',
        'display_description': 'displaydesc',
        'updated_at': datetime.datetime(1900, 1, 1, 1, 1, 1),
        'created_at': datetime.datetime(1900, 1, 1, 1, 1, 1),
        'snapshot_id': None,
        'source_volid': None,
        'volume_type_id': '3e196c20-3c06-11e2-81c1-0800200c9a66',
        'encryption_key_id': None,
        'volume_admin_metadata': [{'key': 'attached_mode', 'value': 'rw'},
                                  {'key': 'readonly', 'value': 'False'}],
        'bootable': False,
        'launched_at': datetime.datetime(1900, 1, 1, 1, 1, 1),
        'volume_type': {'name': 'vol_type_name'},
        'replication_status': 'disabled',
        'replication_extended_status': None,
        'replication_driver_data': None,
        'volume_attachment': [],
        'multiattach': False,
    }

    volume.update(kwargs)
    if kwargs.get('volume_glance_metadata', None):
        volume['bootable'] = True
    if kwargs.get('attach_status') == 'detached':
        del volume['volume_admin_metadata'][0]
    return volume


def stub_volume_create(self, context, size, name, description, snapshot,
                       **param):
    vol = stub_volume('1')
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    vol['source_volid'] = None
    vol['bootable'] = False
    try:
        vol['snapshot_id'] = snapshot['id']
    except (KeyError, TypeError):
        vol['snapshot_id'] = None
    vol['availability_zone'] = param.get('availability_zone', 'fakeaz')
    return vol


def stub_image_service_detail(self, context, **kwargs):
    filters = kwargs.get('filters', {'name': ''})
    if filters['name'] == "Fedora-x86_64-20-20140618-sda":
        return [{'id': "c905cedb-7281-47e4-8a62-f26bc5fc4c77"}]
    elif filters['name'] == "multi":
        return [{'id': "c905cedb-7281-47e4-8a62-f26bc5fc4c77"},
                {'id': "c905cedb-abcd-47e4-8a62-f26bc5fc4c77"}]
    return []


def stub_volume_create_from_image(self, context, size, name, description,
                                  snapshot, volume_type, metadata,
                                  availability_zone):
    vol = stub_volume('1')
    vol['status'] = 'creating'
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    vol['availability_zone'] = 'cinder'
    vol['bootable'] = False
    return vol


def stub_volume_update(self, context, *args, **param):
    pass


def stub_volume_delete(self, context, *args, **param):
    pass


def stub_volume_get(self, context, volume_id, viewable_admin_meta=False):
    return stub_volume(volume_id)


def stub_volume_get_notfound(self, context,
                             volume_id, viewable_admin_meta=False):
    raise exc.NotFound


def stub_volume_get_db(context, volume_id):
    return stub_volume(volume_id)


def stub_volume_get_all(context, search_opts=None, marker=None, limit=None,
                        sort_keys=None, sort_dirs=None, filters=None,
                        viewable_admin_meta=False):
    return [stub_volume(100, project_id='fake'),
            stub_volume(101, project_id='superfake'),
            stub_volume(102, project_id='superduperfake')]


def stub_volume_get_all_by_project(self, context, marker, limit,
                                   sort_keys=None, sort_dirs=None,
                                   filters=None,
                                   viewable_admin_meta=False):
    filters = filters or {}
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
