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

# NOTE(stephenfin): We'd like to set additionalProperties=False but we won't
# because the API is deprecated
create = {
    'type': 'object',
    'properties': {
        'cgsnapshot': {
            'type': 'object',
            'properties': {
                'consistencygroup_id': {
                    'type': 'string',
                },
                'name': {
                    'type': 'string',
                },
                'description': {
                    'type': 'string',
                },
            },
            'required': ['consistencygroup_id'],
            'additionalProperties': True,
        },
    },
    'required': ['cgsnapshot'],
    'additionalProperties': True,
}
