# Copyright (c) 2020 SAP SE
#
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


class SAPPoolDownFilter(filters.BaseBackendFilter):
    """Filter out pools that are not marked 'up'."""

    def backend_passes(self, backend_state, filter_properties):

        if backend_state.pool_state == 'up':
            return True
        else:
            LOG.debug("%(id)s pool state is not 'up'. state='%(state)s'",
                      {'id': backend_state.backend_id,
                       'state': backend_state.pool_state})
            return False
