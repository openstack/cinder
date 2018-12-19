#    Copyright (c) 2015 Intel Corporation
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
from cinder.objects import fields as c_fields
from cinder.tests.unit import fake_constants as fake


def fake_db_backup(**updates):
    db_backup = {
        'id': fake.BACKUP_ID,
        'user_id': fake.USER_ID,
        'project_id': fake.PROJECT_ID,
        'volume_id': fake.VOLUME_ID,
        'status': c_fields.BackupStatus.CREATING,
        'host': 'fake_host',
        'display_name': 'fake_name',
        'size': 5,
        'display_description': 'fake_description',
        'service_metadata': 'fake_metadata',
        'service': 'fake_service',
        'object_count': 5,
        'num_dependent_backups': 0,
        'backup_metadata': [
            {'key': 'key1', 'value': 'value1'},
            {'key': 'key2', 'value': 'value2'}
        ],
    }

    for name, field in objects.Backup.fields.items():
        if name in db_backup:
            continue
        if field.nullable:
            db_backup[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_backup[name] = field.default
        else:
            raise Exception('fake_db_backup needs help with %s' % name)

    if updates:
        db_backup.update(updates)

    return db_backup


def fake_backup_obj(context, **updates):
    return objects.Backup._from_db_object(context, objects.Backup(),
                                          fake_db_backup(**updates),
                                          expected_attrs=['metadata'])
