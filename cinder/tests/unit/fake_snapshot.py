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

from cinder.objects import fields as c_fields
from cinder.objects import snapshot
from cinder.tests.unit import fake_constants as fake


def fake_db_snapshot(**updates):
    db_snapshot = {
        'id': fake.SNAPSHOT_ID,
        'volume_id': fake.VOLUME_ID,
        'status': c_fields.SnapshotStatus.CREATING,
        'progress': '0%',
        'volume_size': 1,
        'display_name': 'fake_name',
        'display_description': 'fake_description',
        'metadata': {},
        'snapshot_metadata': [],
    }

    for name, field in snapshot.Snapshot.fields.items():
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
    expected_attrs = updates.pop('expected_attrs', None) or []
    if 'volume' in updates and 'volume' not in expected_attrs:
        expected_attrs.append('volume')
    if 'context' in updates and 'context' not in expected_attrs:
        expected_attrs.append('context')
    return snapshot.Snapshot._from_db_object(context, snapshot.Snapshot(),
                                             fake_db_snapshot(**updates),
                                             expected_attrs=expected_attrs)
