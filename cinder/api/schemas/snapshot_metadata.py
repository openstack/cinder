# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy

_metadata_properties = {
    'type': 'object',
    'patternProperties': {
        '^[a-zA-Z0-9-_:. ]{1,255}$': {
            'type': 'string',
            'maxLength': 255,
            'description': 'The snapshot metadata value.',
        },
    },
    'additionalProperties': False,
}
_metadata_property = copy.deepcopy(_metadata_properties)
_metadata_property.update(
    {
        'minProperties': 1,
        'maxProperties': 1,
    },
)

create = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'metadata': _metadata_properties,
    },
    'required': ['metadata'],
    'additionalProperties': True,
}

update = {
    'type': 'object',
    'properties': {
        'meta': _metadata_property,
    },
    'required': ['meta'],
    'additionalProperties': True,
}

update_all = create
