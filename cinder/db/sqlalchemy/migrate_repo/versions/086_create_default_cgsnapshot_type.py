# Copyright (c) 2016 Dell Inc. or its subsidiaries.
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

import uuid

from oslo_utils import timeutils
import six
from sqlalchemy import MetaData, Table

from cinder.volume import group_types as volume_group_types


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    now = timeutils.utcnow()

    group_types = Table('group_types', meta, autoload=True)
    group_type_specs = Table('group_type_specs', meta, autoload=True)

    # Create a default group_type for migrating cgsnapshots
    results = list(group_types.select().where(
        group_types.c.name == volume_group_types.DEFAULT_CGSNAPSHOT_TYPE and
        group_types.c.deleted is False).
        execute())
    if not results:
        grp_type_id = six.text_type(uuid.uuid4())
        group_type_dicts = {
            'id': grp_type_id,
            'name': volume_group_types.DEFAULT_CGSNAPSHOT_TYPE,
            'description': 'Default group type for migrating cgsnapshot',
            'created_at': now,
            'updated_at': now,
            'deleted': False,
            'is_public': True,
        }
        grp_type = group_types.insert()
        grp_type.execute(group_type_dicts)
    else:
        grp_type_id = results[0]['id']

    results = list(group_type_specs.select().where(
        group_type_specs.c.group_type_id == grp_type_id and
        group_type_specs.c.deleted is False).
        execute())
    if not results:
        group_spec_dicts = {
            'key': 'consistent_group_snapshot_enabled',
            'value': '<is> True',
            'group_type_id': grp_type_id,
            'created_at': now,
            'updated_at': now,
            'deleted': False,
        }
        grp_spec = group_type_specs.insert()
        grp_spec.execute(group_spec_dicts)
