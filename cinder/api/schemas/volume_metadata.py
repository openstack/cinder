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
Schema for V3 Volume metadata API.

"""

import copy

from cinder.api.validation import parameter_types

metadata_restricted_properties = copy.deepcopy(parameter_types.extra_specs)
metadata_restricted_properties.update({
    'minProperties': 1,
    'maxProperties': 1
})

create = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'metadata': parameter_types.extra_specs,
    },
    'required': ['metadata'],
    'additionalProperties': False,
}

update = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'meta': metadata_restricted_properties,
    },
    'required': ['meta'],
    'additionalProperties': False,
}
