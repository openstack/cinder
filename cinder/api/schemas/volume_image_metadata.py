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
Schema for V3 volume image metadata API.

"""

from cinder.api.validation import parameter_types


set_image_metadata = {
    'type': 'object',
    'properties': {
        'os-set_image_metadata': {
            'type': 'object',
            'properties': {
                'metadata': parameter_types.extra_specs,
            },
            'required': ['metadata'],
            'additionalProperties': False,
        },
    },
    'required': ['os-set_image_metadata'],
    'additionalProperties': False,
}


unset_image_metadata = {
    'type': 'object',
    'properties': {
        'os-unset_image_metadata': {
            'type': 'object',
            'properties': {
                'key': {'type': 'string',
                        'minLength': 1,
                        'maxLength': 255},
            },
            'required': ['key'],
            'additionalProperties': False,
        },
    },
    'required': ['os-unset_image_metadata'],
    'additionalProperties': False,
}
