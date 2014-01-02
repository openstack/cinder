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

from cinder.openstack.common.gettextutils import _  # noqa
from cinder.openstack.common import log as logging
from cinder.openstack.common.scheduler import filters

LOG = logging.getLogger(__name__)


class IgnoreAttemptedHostsFilter(filters.BaseHostFilter):
    """Filter out previously attempted hosts

    A host passes this filter if it has not already been attempted for
    scheduling. The scheduler needs to add previously attempted hosts
    to the 'retry' key of filter_properties in order for this to work
    correctly.  For example:
    {
        'retry': {
                'hosts': ['host1', 'host2'],
                'num_attempts': 3,
            }
    }
    """

    def host_passes(self, host_state, filter_properties):
        """Skip nodes that have already been attempted."""
        attempted = filter_properties.get('retry', None)
        if not attempted:
            # Re-scheduling is disabled
            LOG.debug(_("Re-scheduling is disabled."))
            return True

        hosts = attempted.get('hosts', [])
        host = host_state.host

        passes = host not in hosts
        pass_msg = "passes" if passes else "fails"

        LOG.debug(_("Host %(host)s %(pass_msg)s.  Previously tried hosts: "
                    "%(hosts)s") % {'host': host,
                                    'pass_msg': pass_msg,
                                    'hosts': hosts})
        return passes
