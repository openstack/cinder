# Copyright (c) 2024 SAP SE
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


class SAPFCDFilter(filters.BaseBackendFilter):
    """Filter out pools that are not the same as the original pool.

    For the FCD driver only, we want to ensure that a cross vcenter
    migration lands on the same pool as the the source vcenter.  This
    ensures that a cross vcenter migration results in no data movement.
    """

    def _is_vmware_fcd(self, backend_state):
        if backend_state.storage_protocol != 'vstorageobject':
            return False
        return True

    def backend_passes(self, backend_state, filter_properties):

        if not self._is_vmware_fcd(backend_state):
            LOG.info("Backend is not a VMware FCD backend")
            return True

        spec = filter_properties.get('request_spec', {})
        vol = spec.get('volume_properties', {})

        if spec.get('operation') != 'migrate_volume':
            LOG.info("Operation is not a migrate_volume")
            return True

        # We are migrating a volume.  If we are migrating to a different
        # backend, we want to ensure that the pool is the same as the
        # original backend.

        #   name@backend#pool
        orig_host = vol.get('host')
        orig_backend = orig_host.split('#')[0]
        orig_pool = orig_host.split('#')[1]
        destination_host = spec.get('destination_host')

        dest_backend = destination_host.split('#')[0]
        dest_pool = destination_host.split('#')[1]

        if orig_backend != dest_backend:
            LOG.info("Destination backend is different from original backend")
            # We only want to pass if the pool is the same as the original pool
            if dest_pool == orig_pool:
                return True
            else:
                return False
        else:
            return True
