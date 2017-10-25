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
Schema for V3 Attachments API.

"""

from cinder.api.validation import parameter_types


create = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'attachment': {
            'type': 'object',
            'properties': {
                'instance_uuid': parameter_types.uuid,
                'connector': {'type': ['object', 'null']},
                'volume_uuid': parameter_types.uuid,
            },
            'required': ['instance_uuid', 'volume_uuid'],
            'additionalProperties': False,
        },
    },
    'required': ['attachment'],
    'additionalProperties': False,
}

update = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'attachment': {
            'type': 'object',
            'properties': {
                'connector': {'type': 'object', 'minProperties': 1},
            },
            'required': ['connector'],
            'additionalProperties': False,
        },
    },
    'required': ['attachment'],
    'additionalProperties': False,
}
