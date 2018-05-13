# Copyright (C) 2018 NTT DATA
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
Schema for V3 Generic Volume Groups API.

"""

from cinder.api.validation import parameter_types


create = {
    'type': 'object',
    'properties': {
        'group': {
            'type': 'object',
            'properties': {
                'description': parameter_types.description,
                'group_type': {
                    'type': 'string', 'format': 'group_type'
                },
                'name': parameter_types.name_allow_zero_min_length,
                'volume_types': {
                    'type': 'array', 'minItems': 1,
                    'items': {
                        'type': 'string', 'maxLength': 255,
                    },
                    'uniqueItems': True
                },
                'availability_zone': {
                    'type': ['string', 'null'], 'format': 'availability_zone'
                },
            },
            'required': ['group_type', 'volume_types'],
            'additionalProperties': False,
        },
    },
    'required': ['group'],
    'additionalProperties': False,
}

create_from_source = {
    'type': 'object',
    'properties': {
        'create-from-src': {
            'type': 'object',
            'properties': {
                'description': parameter_types.description,
                'name': parameter_types.name_allow_zero_min_length,
                'source_group_id': parameter_types.uuid,
                'group_snapshot_id': parameter_types.uuid,
            },
            'oneOf': [
                {'required': ['group_snapshot_id']},
                {'required': ['source_group_id']}
            ],
            'additionalProperties': False,
        },
    },
    'required': ['create-from-src'],
    'additionalProperties': False,
}

delete = {
    'type': 'object',
    'properties': {
        'delete': {
            'type': 'object',
            'properties': {
                'delete-volumes': parameter_types.boolean,
            },
            'additionalProperties': False,
        },
    },
    'required': ['delete'],
    'additionalProperties': False,
}

reset_status = {
    'type': 'object',
    'properties': {
        'reset_status': {
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string', 'format': 'group_status'
                },
            },
            'required': ['status'],
            'additionalProperties': False,
        },
    },
    'required': ['reset_status'],
    'additionalProperties': False,
}

update = {
    'type': 'object',
    'properties': {
        'group': {
            'type': 'object',
            'properties': {
                'description': parameter_types.description,
                'name': parameter_types.name_allow_zero_min_length,
                'add_volumes': parameter_types.description,
                'remove_volumes': parameter_types.description,
            },
            'anyOf': [
                {'required': ['name']},
                {'required': ['description']},
                {'required': ['add_volumes']},
                {'required': ['remove_volumes']},
            ],
            'additionalProperties': False,
        },
    },
    'required': ['group'],
    'additionalProperties': False,
}

failover_replication = {
    'type': 'object',
    'properties': {
        'failover_replication': {
            'type': 'object',
            'properties': {
                'allow_attached_volume': parameter_types.boolean,
                'secondary_backend_id': parameter_types.nullable_string,
            },
            'additionalProperties': False,
        },
    },
    'required': ['failover_replication'],
    'additionalProperties': False,
}

list_replication = {
    'type': 'object',
    'properties': {
        'list_replication_targets': {'type': 'object'}
    },
    'required': ['list_replication_targets'],
    'additionalProperties': False,
}

enable_replication = {
    'type': 'object',
    'properties': {
        'enable_replication': {'type': 'object'}
    },
    'required': ['enable_replication'],
    'additionalProperties': False,
}

disable_replication = {
    'type': 'object',
    'properties': {
        'disable_replication': {'type': 'object'}
    },
    'required': ['disable_replication'],
    'additionalProperties': False,
}
