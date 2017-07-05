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

from oslo_log import log as logging

from cinder.scheduler import filters

LOG = logging.getLogger(__name__)


class IgnoreAttemptedHostsFilter(filters.BaseBackendFilter):
    """Filter out previously attempted hosts

    A host passes this filter if it has not already been attempted for
    scheduling. The scheduler needs to add previously attempted hosts
    to the 'retry' key of filter_properties in order for this to work
    correctly. For example::

     {
      'retry': {
                'backends': ['backend1', 'backend2'],
                'num_attempts': 3,
               }
     }
    """

    def backend_passes(self, backend_state, filter_properties):
        """Skip nodes that have already been attempted."""
        attempted = filter_properties.get('retry')
        if not attempted:
            # Re-scheduling is disabled
            LOG.debug("Re-scheduling is disabled.")
            return True

        # TODO(geguileo): In P - Just use backends
        backends = attempted.get('backends', attempted.get('hosts', []))
        backend = backend_state.backend_id

        passes = backend not in backends
        pass_msg = "passes" if passes else "fails"

        LOG.debug("Backend %(backend)s %(pass_msg)s.  Previously tried "
                  "backends: %(backends)s", {'backend': backend,
                                             'pass_msg': pass_msg,
                                             'backends': backends})
        return passes
