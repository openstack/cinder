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
Schema for V3 scheduler_hints API.

"""

from cinder.api.validation import parameter_types

create = {
    'type': 'object',
    'properties': {
        'OS-SCH-HNT:scheduler_hints': {
            'type': ['object', 'null'],
            'properties': {
                'local_to_instance': parameter_types.optional_uuid,
                'different_host': {
                    # NOTE: The value of 'different_host' is the set of volume
                    # uuids where a new volume is scheduled on a different
                    # host. A user can specify one volume as string parameter
                    # and should specify multiple volumes as array parameter
                    # instead.
                    'oneOf': [
                        {
                            'type': 'string',
                            'format': 'uuid'
                        },
                        {
                            'type': 'array',
                            'items': parameter_types.uuid,
                            'uniqueItems': True,
                        }
                    ]
                },
                'same_host': {
                    # NOTE: The value of 'same_host' is the set of volume
                    # uuids where a new volume is scheduled on the same host.
                    # A user can specify one volume as string parameter and
                    # should specify multiple volumes as array parameter
                    # instead.
                    'oneOf': [
                        {
                            'type': 'string',
                            'format': 'uuid'
                        },
                        {
                            'type': 'array',
                            'items': parameter_types.uuid,
                            'uniqueItems': True,
                        }
                    ]
                },
                'query': {
                    # NOTE: The value of 'query' is converted to dict data with
                    # jsonutils.loads() and used for filtering hosts.
                    'type': ['string', 'object'],
                },
            },
            # NOTE: As this Mail:
            # http://lists.openstack.org/pipermail/openstack-dev/2015-June/067996.html
            # pointed out the limit the scheduler-hints in the API is
            # problematic. So relax it.
            'additionalProperties': True
        },
    },
}
