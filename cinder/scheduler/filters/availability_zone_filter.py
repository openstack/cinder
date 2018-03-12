# Copyright (c) 2011-2012 OpenStack Foundation.
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

from cinder.scheduler import filters


class AvailabilityZoneFilter(filters.BaseBackendFilter):
    """Filters Backends by availability zone."""

    # Availability zones do not change within a request
    run_filter_once_per_request = True

    def backend_passes(self, backend_state, filter_properties):
        spec = filter_properties.get('request_spec', {})
        availability_zones = spec.get('availability_zones')

        if availability_zones:
            return (backend_state.service['availability_zone']
                    in availability_zones)

        props = spec.get('resource_properties', {})
        availability_zone = props.get('availability_zone')

        if availability_zone:
            return (availability_zone ==
                    backend_state.service['availability_zone'])
        return True
