#    Copyright 2015 SimpliVity Corp.
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

from cinder import objects
from cinder.objects import fields


def fake_db_volume(**updates):
    db_volume = {
        'id': '1',
        'size': 1,
        'name': 'volume-1',
        'availability_zone': 'fake_availability_zone',
        'status': 'available',
        'attach_status': 'detached',
    }

    for name, field in objects.Volume.fields.items():
        if name in db_volume:
            continue
        if field.nullable:
            db_volume[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_volume[name] = field.default
        else:
            raise Exception('fake_db_volume needs help with %s' % name)

    if updates:
        db_volume.update(updates)

    return db_volume


def fake_volume_obj(context, **updates):
    return objects.Volume._from_db_object(context, objects.Volume(),
                                          fake_db_volume(**updates))
