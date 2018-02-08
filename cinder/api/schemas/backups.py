# Copyright (C) 2017 NTT DATA
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
"""
Schema for V3 Backups API.

"""

import copy

from cinder.api.validation import parameter_types


create = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'backup': {
            'type': 'object',
            'properties': {
                'volume_id': parameter_types.uuid,
                'container': parameter_types.container,
                'description': parameter_types.description,
                'incremental': parameter_types.boolean,
                'force': parameter_types.boolean,
                'name': parameter_types.name_allow_zero_min_length,
                'snapshot_id': parameter_types.uuid_allow_null,
            },
            'required': ['volume_id'],
            'additionalProperties': False,
        },
    },
    'required': ['backup'],
    'additionalProperties': False,
}


create_backup_v343 = copy.deepcopy(create)
create_backup_v343['properties']['backup']['properties'][
    'metadata'] = parameter_types.metadata_allows_null


create_backup_v351 = copy.deepcopy(create_backup_v343)
create_backup_v351['properties']['backup']['properties'][
    'availability_zone'] = parameter_types.nullable_string


update = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'backup': {
            'type': ['object', 'null'],
            'properties': {
                'name': parameter_types.name_allow_zero_min_length,
                'description': parameter_types.description,
            },
            'additionalProperties': False,
        },
    },
    'required': ['backup'],
    'additionalProperties': False,
}

update_backup_v343 = copy.deepcopy(update)
update_backup_v343['properties']['backup']['properties'][
    'metadata'] = parameter_types.extra_specs

restore = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'restore': {
            'type': ['object', 'null'],
            'properties': {
                'name': parameter_types.name_allow_zero_min_length,
                'volume_id': parameter_types.uuid_allow_null
            },
            'additionalProperties': False,
        },
    },
    'required': ['restore'],
    'additionalProperties': False,
}

import_record = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'backup-record': {
            'type': 'object',
            'properties': {
                'backup_service': parameter_types.backup_service,
                'backup_url': parameter_types.backup_url
            },
            'required': ['backup_service', 'backup_url'],
            'additionalProperties': False,
        },
    },
    'required': ['backup-record'],
    'additionalProperties': False,
}
