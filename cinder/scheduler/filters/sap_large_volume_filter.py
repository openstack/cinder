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

from oslo_config import cfg
from oslo_log import log as logging

from cinder.scheduler import filters


LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class SAPLargeVolumeFilter(filters.BaseBackendFilter):
    """Filter out volumes from landing on vvol datastores for > 2TB"""

    def backend_passes(self, backend_state, filter_properties):
        host = backend_state.host

        # if the request is against a non vvol host, we pass.
        if 'vvol' not in host.lower():
            return True

        if filter_properties.get('new_size'):
            requested_size = int(filter_properties.get('new_size'))
        else:
            requested_size = int(filter_properties.get('size'))

        # requested_size is 0 means that it's a manage request.
        if requested_size == 0:
            return True

        if requested_size > 2048:
            LOG.info("Cannot allow volumes larger than 2048 GiB on vVol.")
            return False
        else:
            return True
