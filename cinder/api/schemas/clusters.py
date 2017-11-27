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
Schema for V3 Clusters API.

"""


from cinder.api.validation import parameter_types


disable_cluster = {
    'type': 'object',
    'properties': {
        'name': parameter_types.name,
        'binary': parameter_types.nullable_string,
        'disabled_reason': {
            'type': ['string', 'null'], 'format': 'disabled_reason'
        }
    },
    'required': ['name'],
    'additionalProperties': False,
}


enable_cluster = {
    'type': 'object',
    'properties': {
        'name': parameter_types.name,
        'binary': parameter_types.nullable_string
    },
    'required': ['name'],
    'additionalProperties': False,
}
