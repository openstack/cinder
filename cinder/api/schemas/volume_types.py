# Copyright 2017 NTT DATA
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from cinder.api.validation import parameter_types


create = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'volume_type': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name,
                'description': parameter_types.description,
                'extra_specs': parameter_types.extra_specs_with_null,
                'os-volume-type-access:is_public': parameter_types.boolean,
            },
            'required': ['name'],
            'additionalProperties': False,
        },
    },
    'required': ['volume_type'],
    'additionalProperties': False,
}


update = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'volume_type': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name_allow_zero_min_length,
                'description': parameter_types.description,
                'is_public': parameter_types.boolean,
            },
            'additionalProperties': False,
        },
    },
    'required': ['volume_type'],
    'additionalProperties': False,
}
