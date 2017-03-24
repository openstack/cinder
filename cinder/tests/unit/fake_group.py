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


def fake_db_group(**updates):
    db_group = {
        'id': fake.GROUP_ID,
        'name': 'group-1',
        'status': 'available',
        'user_id': fake.USER_ID,
        'project_id': fake.PROJECT_ID,
        'group_type_id': fake.GROUP_TYPE_ID,
        'group_snapshot_id': None,
        'source_group_id': None,
    }

    for name, field in objects.Group.fields.items():
        if name in db_group:
            continue
        if field.nullable:
            db_group[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_group[name] = field.default
        else:
            raise Exception('fake_db_group needs help with %s.' % name)

    if updates:
        db_group.update(updates)

    return db_group


def fake_db_group_type(**updates):
    db_group_type = {
        'id': fake.GROUP_TYPE_ID,
        'name': 'type-1',
        'description': 'A fake group type',
        'is_public': True,
        'projects': [],
        'group_specs': {},
    }

    for name, field in objects.GroupType.fields.items():
        if name in db_group_type:
            continue
        if field.nullable:
            db_group_type[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_group_type[name] = field.default
        else:
            raise Exception('fake_db_group_type needs help with %s.' % name)

    if updates:
        db_group_type.update(updates)

    return db_group_type


def fake_group_obj(context, **updates):
    return objects.Group._from_db_object(
        context, objects.Group(), fake_db_group(**updates))


def fake_group_type_obj(context, **updates):
    return objects.GroupType._from_db_object(
        context, objects.GroupType(), fake_db_group_type(**updates))
