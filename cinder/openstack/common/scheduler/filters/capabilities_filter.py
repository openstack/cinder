# Copyright (c) 2011 OpenStack, LLC.
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

from cinder.openstack.common import log as logging
from cinder.openstack.common.scheduler import filters
from cinder.openstack.common.scheduler.filters import extra_specs_ops


LOG = logging.getLogger(__name__)


class CapabilitiesFilter(filters.BaseHostFilter):
    """HostFilter to work with resource (instance & volume) type records."""

    def _satisfies_extra_specs(self, capabilities, resource_type):
        """Check that the capabilities provided by the services
        satisfy the extra specs associated with the instance type"""
        extra_specs = resource_type.get('extra_specs', [])
        if not extra_specs:
            return True

        for key, req in extra_specs.iteritems():
            # Either not scope format, or in capabilities scope
            scope = key.split(':')
            if len(scope) > 1 and scope[0] != "capabilities":
                continue
            elif scope[0] == "capabilities":
                del scope[0]

            cap = capabilities
            for index in range(0, len(scope)):
                try:
                    cap = cap.get(scope[index], None)
                except AttributeError:
                    return False
                if cap is None:
                    return False
            if not extra_specs_ops.match(cap, req):
                return False
        return True

    def host_passes(self, host_state, filter_properties):
        """Return a list of hosts that can create instance_type."""
        # Note(zhiteng) Currently only Cinder and Nova are using
        # this filter, so the resource type is either instance or
        # volume.
        resource_type = filter_properties.get('resource_type')
        if not self._satisfies_extra_specs(host_state.capabilities,
                                           resource_type):
            return False
        return True
