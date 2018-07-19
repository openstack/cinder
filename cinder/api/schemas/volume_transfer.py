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
Schema for V3 volume transfer API.

"""

from cinder.api.validation import parameter_types

create = {
    'type': 'object',
    'properties': {
        'transfer': {
            'type': 'object',
            'properties': {
                'volume_id': parameter_types.uuid,
                'name': {'oneOf': [{'type': 'string',
                                    'format':
                                        "name_skip_leading_trailing_spaces"},
                                   {'type': 'null'}]},
            },
            'required': ['volume_id'],
            'additionalProperties': False,
        },
    },
    'required': ['transfer'],
    'additionalProperties': False,
}


accept = {
    'type': 'object',
    'properties': {
        'accept': {
            'type': 'object',
            'properties': {
                'auth_key': {'type': ['string', 'integer']},
            },
            'required': ['auth_key'],
            'additionalProperties': False,
        },
    },
    'required': ['accept'],
    'additionalProperties': False,
}


create_v355 = {
    'type': 'object',
    'properties': {
        'transfer': {
            'type': 'object',
            'properties': {
                'volume_id': parameter_types.uuid,
                'name': {'oneOf': [{'type': 'string',
                                    'format':
                                        "name_skip_leading_trailing_spaces"},
                                   {'type': 'null'}]},
                'no_snapshots': parameter_types.boolean
            },
            'required': ['volume_id'],
            'additionalProperties': False,
        },
    },
    'required': ['transfer'],
    'additionalProperties': False,
}
