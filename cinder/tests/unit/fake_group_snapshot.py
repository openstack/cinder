#    Copyright 2016 EMC Corporation
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

from oslo_versionedobjects import fields

from cinder import objects
from cinder.tests.unit import fake_constants as fake


def fake_db_group_snapshot(**updates):
    db_group_snapshot = {
        'id': fake.GROUP_SNAPSHOT_ID,
        'name': 'group-1',
        'status': 'available',
        'user_id': fake.USER_ID,
        'project_id': fake.PROJECT_ID,
        'group_type_id': fake.GROUP_TYPE_ID,
        'group_id': fake.GROUP_ID,
    }

    for name, field in objects.GroupSnapshot.fields.items():
        if name in db_group_snapshot:
            continue
        if field.nullable:
            db_group_snapshot[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_group_snapshot[name] = field.default
        else:
            raise Exception('fake_db_group_snapshot needs help with %s.'
                            % name)

    if updates:
        db_group_snapshot.update(updates)

    return db_group_snapshot


def fake_group_snapshot_obj(context, **updates):
    return objects.GroupSnapshot._from_db_object(
        context, objects.GroupSnapshot(), fake_db_group_snapshot(**updates))
