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
Schema for V3 Workers API.

"""

from cinder.api.validation import parameter_types

cleanup = {
    'type': 'object',
    'properties': {
        'cluster_name': parameter_types.hostname,
        'disabled': parameter_types.boolean,
        'host': parameter_types.hostname,
        'is_up': parameter_types.boolean,
        'binary': {'enum': ['cinder-volume', 'cinder-scheduler']},
        'resource_id': parameter_types.optional_uuid,
        'resource_type': parameter_types.resource_type,
        'service_id': parameter_types.service_id,
    },
    'additionalProperties': False,
}
