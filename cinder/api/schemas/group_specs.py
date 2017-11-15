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

import copy


group_specs_with_no_spaces_key_and_value_null = {
    'type': 'object',
    'patternProperties': {
        '^[a-zA-Z0-9-_:.]{1,255}$': {
            'type': ['string', 'null'], 'maxLength': 255
        }
    },
    'additionalProperties': False
}

create = {
    'type': 'object',
    'properties': {
        'type': 'object',
        'group_specs': group_specs_with_no_spaces_key_and_value_null,
    },
    'required': ['group_specs'],
    'additionalProperties': False,
}

update = copy.deepcopy(group_specs_with_no_spaces_key_and_value_null)
update.update({
    'minProperties': 1,
    'maxProperties': 1
})
