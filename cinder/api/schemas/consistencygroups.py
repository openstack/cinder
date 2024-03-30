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

from cinder.api.validation import parameter_types

# NOTE: These schemas are very loose but they won't be fixed as the API itself
# is deprecated.

create = {
    'type': 'object',
    'properties': {
        'consistencygroup': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name_allow_zero_min_length,
                'description': parameter_types.description,
                'volume_types': {},
                'availability_zone': {},
            },
            'required': ['volume_types'],
            'additionalProperties': True,
        },
    },
    'required': ['consistencygroup'],
    'additionalProperties': True,
}

create_from_src = {
    'type': 'object',
    'properties': {
        'consistencygroup-from-src': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name_allow_zero_min_length,
                'description': parameter_types.description,
                'cgsnapshot_id': {
                    'type': 'string',
                },
                'source_cgid': {
                    'type': 'string',
                },
            },
            'required': [],
            'additionalProperties': True,
        },
    },
    'required': ['consistencygroup-from-src'],
    'additionalProperties': True,
}

# NOTE: This one is weird. Effectively, we want to make the body optional but
# because the code is using a false'y check rather than an explict 'is None'
# check, we have allowed empty bodies. As such, the body can either be an
# object with a required key, an empty body, or null.
# TODO: Disallow the empty body case.
delete = {
    'oneOf': [
        {
            'type': 'object',
            'properties': {
                'consistencygroup': {
                    'type': 'object',
                    'properties': {
                        'force': parameter_types.boolean,
                    },
                    'required': [],
                    'additionalProperties': True,
                },
            },
            'required': ['consistencygroup'],
            'additionalProperties': True,
        },
        {
            'type': 'object',
            'properties': {},
            'additionalProperties': False,
        },
        {
            'type': 'null',
        },
    ],
}

update = {
    'type': 'object',
    'properties': {
        'consistencygroup': {
            'type': 'object',
            'properties': {
                'name': parameter_types.name_allow_zero_min_length,
                'description': parameter_types.description,
                'add_volumes': {
                    'type': ['string', 'null'],
                },
                'remove_volumes': {
                    'type': ['string', 'null'],
                },
            },
            'required': [],
            'additionalProperties': True,
        },
    },
    'required': ['consistencygroup'],
    'additionalProperties': True,
}
