#    Copyright 2016 EMC Corp.
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


def fake_db_cgsnapshot(**updates):
    db_values = {
        'id': fake.CGSNAPSHOT_ID,
        'consistencygroup_id': fake.CONSISTENCY_GROUP_ID,
        'user_id': fake.USER_ID,
        'project_id': fake.PROJECT_ID,
    }
    for name, field in objects.CGSnapshot.fields.items():
        if name in db_values:
            continue
        if field.nullable:
            db_values[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_values[name] = field.default
        else:
            raise Exception('fake_db_snapshot needs help with %s' %
                            name)

    if updates:
        db_values.update(updates)

    return db_values


def fake_cgsnapshot_obj(context, **updates):
    expected_attrs = updates.pop('expected_attrs', None)
    return objects.CGSnapshot._from_db_object(context,
                                              objects.CGSnapshot(),
                                              fake_db_cgsnapshot(
                                                  **updates),
                                              expected_attrs=expected_attrs)
