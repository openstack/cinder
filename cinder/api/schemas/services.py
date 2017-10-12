# Copyright 2018 NTT DATA
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

import copy

from cinder.api.validation import parameter_types


enable_and_disable = {
    'type': 'object',
    'properties': {
        'binary': {'type': 'string', 'minLength': 1, 'maxLength': 255},
        'host': parameter_types.hostname,
        'cluster': parameter_types.nullable_string,
        'service': {'type': 'string', 'minLength': 1, 'maxLength': 255},
    },
    'anyOf': [
        {'required': ['binary']},
        {'required': ['service']}
    ],
    'additionalProperties': False,
}


disable_log_reason = copy.deepcopy(enable_and_disable)
disable_log_reason['properties'][
    'disabled_reason'] = {'type': 'string', 'minLength': 1, 'maxLength': 255,
                          'format': 'disabled_reason'}


set_log = {
    'type': 'object',
    'properties': {
        'binary': parameter_types.binary,
        'server': parameter_types.nullable_string,
        'prefix': parameter_types.nullable_string,
        'level': {'type': ['string', 'null'], 'format': 'level'}
    },
    'additionalProperties': False,
}


get_log = {
    'type': 'object',
    'properties': {
        'binary': parameter_types.binary,
        'server': parameter_types.nullable_string,
        'prefix': parameter_types.nullable_string,
    },
    'additionalProperties': False,
}


freeze_and_thaw = {
    'type': 'object',
    'properties': {
        'cluster': parameter_types.nullable_string,
        'host': parameter_types.hostname,
    },
    'additionalProperties': False,
}


failover_host = {
    'type': 'object',
    'properties': {
        'host': parameter_types.hostname,
        'backend_id': parameter_types.nullable_string,
        'cluster': parameter_types.nullable_string,
    },
    'additionalProperties': False,
}
