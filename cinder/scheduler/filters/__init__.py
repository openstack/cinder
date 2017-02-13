# Copyright (c) 2011 OpenStack Foundation.
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
Scheduler host filters
"""

from cinder.scheduler import base_filter


class BaseBackendFilter(base_filter.BaseFilter):
    """Base class for host filters."""
    def _filter_one(self, obj, filter_properties):
        """Return True if the object passes the filter, otherwise False."""
        # For backward compatibility with out of tree filters
        passes_method = getattr(self, 'host_passes', self.backend_passes)
        return passes_method(obj, filter_properties)

    def backend_passes(self, host_state, filter_properties):
        """Return True if the HostState passes the filter, otherwise False.

        Override this in a subclass.
        """
        raise NotImplementedError()


class BackendFilterHandler(base_filter.BaseFilterHandler):
    def __init__(self, namespace):
        super(BackendFilterHandler, self).__init__(BaseHostFilter, namespace)


# NOTE(geguileo): For backward compatibility with external filters that
# inherit from these classes
BaseHostFilter = BaseBackendFilter
HostFilterHandler = BackendFilterHandler
