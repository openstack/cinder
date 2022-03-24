# Copyright 2022, SAP SE
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

from oslo_log import log as logging
from oslo_utils import uuidutils

from cinder.scheduler import filters
from cinder.volume import api as volume
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)


class SAPBackendFilter(filters.BaseBackendFilter):

    run_filter_once_per_request = False

    def __init__(self):
        super().__init__()
        self.volume_api = volume.API()
        self.backend_fqdn_lookup = {}

    def _get_volumes(self, context, affinity_uuids, backend_state):
        # We don't filter here on host.
        filters = {'id': affinity_uuids, 'deleted': False}
        return self.volume_api.get_all(context, filters=filters)

    def _affinity_volumes(self, backend_state, filter_properties):
        context = filter_properties['context']
        scheduler_hints = filter_properties.get('scheduler_hints') or {}
        affinity_uuids = scheduler_hints.get(self.hint_key, [])

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
            return self._get_volumes(context, affinity_uuids, backend_state)

    def filter_all(self, filter_obj_list, filter_properties):
        """Yield objects that pass the filter.

        Can be overridden in a subclass, if you need to base filtering
        decisions on all objects.  Otherwise, one can just override
        _filter_one() to filter a single object.

        We override this so we can build a datastore -> backend fqdn lookup
        for all the datastores.  The filter will use it to test if the
        volume's backend fqdn matches the passed in pool's fqdn.
        """
        # reset the lookup for this request.  It can change between requests.
        self.backend_fqdn_lookup = {}

        # First we need to get all of the pools and populate a lookup for
        # the datastore backend fqdn custom attributes, if any.
        scheduler_hints = filter_properties.get('scheduler_hints') or {}
        affinity_uuids = scheduler_hints.get(self.hint_key, [])
        # filter_obj_list is a generator, so we need to copy
        # each entry for looping again.
        obj_list = []
        if affinity_uuids:
            # Build the backend_fqdn_lookup, since we will need it this request
            objs = list(filter_obj_list)
            for obj in objs:
                obj_list.append(obj)
                caps = obj.capabilities
                if ('custom_attributes' in caps and
                        'netapp_fqdn' in caps['custom_attributes']):
                    datastore = volume_utils.extract_host(obj.host,
                                                          level='pool')
                    fqdn = caps['custom_attributes']['netapp_fqdn']
                    self.backend_fqdn_lookup[datastore] = fqdn
        else:
            obj_list = filter_obj_list

        for obj in obj_list:
            if self._filter_one(obj, filter_properties):
                yield obj

    def _get_backend_fqdn(self, pool_name):
        if pool_name in self.backend_fqdn_lookup:
            return self.backend_fqdn_lookup[pool_name]
        else:
            return None


class SAPDifferentBackendFilter(SAPBackendFilter):
    """Schedule volume on a different back-end from a set of volumes."""

    hint_key = "different_host"

    def backend_passes(self, backend_state, filter_properties):
        volumes = self._affinity_volumes(backend_state, filter_properties)

        # If we got no volumes, then no reason to check
        if not volumes:
            return True

        # Get the backend fqdn custom attribute for the volume
        backend_datastore = volume_utils.extract_host(backend_state.host,
                                                      level='pool')
        backend_fqdn = self._get_backend_fqdn(backend_datastore)
        if not backend_fqdn:
            # The datastore being filtered doesn't have a custom fqdn set
            # Don't filter it out.
            LOG.debug("Datastore {} has no fqdn".format(
                backend_datastore
            ))
            return True

        # extract the datastore from the host entries from
        # the volumes (from affinity_uuids), then find the backend associated
        # with each of those and then only allow the same netapp to pass
        for vol in volumes:
            volume_datastore = volume_utils.extract_host(vol.host,
                                                         level='pool')
            volume_fqdn = self._get_backend_fqdn(volume_datastore)
            if volume_fqdn:
                if volume_fqdn == backend_fqdn:
                    LOG.debug("Volume FQDN matches {}".format(
                        backend_fqdn
                    ), resource=vol)
                    return False

        return True


class SAPSameBackendFilter(SAPBackendFilter):
    """Schedule volume on the same back-end as another volume.

    This also ensures that if a backend has a custom attribute
    that specifies the actual Netapp fqdn, then passes when the
    datastore matches that fqdn.

    """
    hint_key = "same_host"

    def backend_passes(self, backend_state, filter_properties):
        volumes = self._affinity_volumes(backend_state, filter_properties)

        if not volumes:
            return True

        # Get the backend fqdn custom attribute for the volume
        backend_datastore = volume_utils.extract_host(backend_state.host,
                                                      level='pool')
        backend_fqdn = self._get_backend_fqdn(backend_datastore)
        if not backend_fqdn:
            # The datastore being filtered doesn't have a custom fqdn set
            # Don't filter it out.
            LOG.debug("Datastore {} has no fqdn".format(
                backend_datastore
            ))
            return True

        # If the result is a list of volumes, then we have to
        # extract the datastore from the host entries from
        # those volumes, then find the netapp associated with
        # each of those and then only allow the same netapp to pass
        for vol in volumes:
            volume_datastore = volume_utils.extract_host(vol.host,
                                                         level='pool')
            volume_fqdn = self._get_backend_fqdn(volume_datastore)
            if volume_fqdn:
                if volume_fqdn == backend_fqdn:
                    LOG.debug("Volume FQDN matches {}".format(
                        backend_fqdn
                    ), resource=vol)
                    return True

        return False
