# Copyright 2014, eBay Inc.
# Copyright 2014, OpenStack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from cinder.openstack.common import log as logging
from cinder.openstack.common.scheduler import filters
from cinder.openstack.common import uuidutils
from cinder.volume import api as volume

LOG = logging.getLogger(__name__)


class AffinityFilter(filters.BaseHostFilter):
    def __init__(self):
        self.volume_api = volume.API()


class DifferentBackendFilter(AffinityFilter):
    """Schedule volume on a different back-end from a set of volumes."""

    def host_passes(self, host_state, filter_properties):
        context = filter_properties['context']
        scheduler_hints = filter_properties.get('scheduler_hints') or {}

        affinity_uuids = scheduler_hints.get('different_host', [])

        # scheduler hint verification: affinity_uuids can be a list of uuids
        # or single uuid.  The checks here is to make sure every single string
        # in the list looks like a uuid, otherwise, this filter will fail to
        # pass.  Note that the filter does *NOT* ignore string doesn't look
        # like a uuid, it is better to fail the request than serving it wrong.
        if isinstance(affinity_uuids, list):
            for uuid in affinity_uuids:
                if uuidutils.is_uuid_like(uuid):
                    continue
                else:
                    return False
        elif uuidutils.is_uuid_like(affinity_uuids):
            affinity_uuids = [affinity_uuids]
        else:
            # Not a list, not a string looks like uuid, don't pass it
            # to DB for query to avoid potential risk.
            return False

        if affinity_uuids:
            return not self.volume_api.get_all(
                context, filters={'host': host_state.host,
                                  'id': affinity_uuids,
                                  'deleted': False})

        # With no different_host key
        return True


class SameBackendFilter(AffinityFilter):
    """Schedule volume on the same back-end as another volume."""

    def host_passes(self, host_state, filter_properties):
        context = filter_properties['context']
        scheduler_hints = filter_properties.get('scheduler_hints') or {}

        affinity_uuids = scheduler_hints.get('same_host', [])

        # scheduler hint verification: affinity_uuids can be a list of uuids
        # or single uuid.  The checks here is to make sure every single string
        # in the list looks like a uuid, otherwise, this filter will fail to
        # pass.  Note that the filter does *NOT* ignore string doesn't look
        # like a uuid, it is better to fail the request than serving it wrong.
        if isinstance(affinity_uuids, list):
            for uuid in affinity_uuids:
                if uuidutils.is_uuid_like(uuid):
                    continue
                else:
                    return False
        elif uuidutils.is_uuid_like(affinity_uuids):
            affinity_uuids = [affinity_uuids]
        else:
            # Not a list, not a string looks like uuid, don't pass it
            # to DB for query to avoid potential risk.
            return False

        if affinity_uuids:
            return self.volume_api.get_all(
                context, filters={'host': host_state.host,
                                  'id': affinity_uuids,
                                  'deleted': False})

        # With no same_host key
        return True
