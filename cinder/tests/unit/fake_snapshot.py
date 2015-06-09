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

from oslo_versionedobjects import fields

from cinder import objects


def fake_db_volume(**updates):
    db_volume = {
        'id': 1,
        'size': 1,
        'name': 'fake',
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


def fake_db_snapshot(**updates):
    db_snapshot = {
        'id': 1,
        'volume_id': 'fake_id',
        'status': "creating",
        'progress': '0%',
        'volume_size': 1,
        'display_name': 'fake_name',
        'display_description': 'fake_description',
        'metadata': {},
        'snapshot_metadata': {},
    }

    for name, field in objects.Snapshot.fields.items():
        if name in db_snapshot:
            continue
        if field.nullable:
            db_snapshot[name] = None
        elif field.default != fields.UnspecifiedDefault:
            db_snapshot[name] = field.default
        else:
            raise Exception('fake_db_snapshot needs help with %s' % name)

    if updates:
        db_snapshot.update(updates)

    return db_snapshot


def fake_snapshot_obj(context, **updates):
    expected_attrs = updates.pop('expected_attrs', None)
    return objects.Snapshot._from_db_object(context, objects.Snapshot(),
                                            fake_db_snapshot(**updates),
                                            expected_attrs=expected_attrs)


def fake_volume_obj(context, **updates):
    expected_attrs = updates.pop('expected_attrs', None)
    return objects.Volume._from_db_object(context, objects.Volume(),
                                          fake_db_volume(**updates),
                                          expected_attrs=expected_attrs)
