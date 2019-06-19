# Copyright (c) 2016 Clinton Knight.  All rights reserved.
# Copyright (c) 2017 Jose Porrua.  All rights reserved.
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
Storage service catalog (SSC) functions and classes for NetApp cDOT systems.
"""

import copy
import re

from oslo_log import log as logging
import six

from cinder import exception
from cinder.i18n import _


LOG = logging.getLogger(__name__)

# NOTE(cknight): The keys in this map are tuples that contain arguments needed
# for efficient use of the system-user-capability-get-iter cDOT API.  The
# values are SSC extra specs associated with the APIs listed in the keys.
SSC_API_MAP = {
    ('storage.aggregate', 'show', 'aggr-options-list-info'): [
        'netapp_raid_type',
    ],
    ('storage.disk', 'show', 'storage-disk-get-iter'): [
        'netapp_disk_type',
    ],
    ('snapmirror', 'show', 'snapmirror-get-iter'): [
        'netapp_mirrored',
    ],
    ('volume.efficiency', 'show', 'sis-get-iter'): [
        'netapp_dedup',
        'netapp_compression',
    ],
    ('volume', '*show', 'volume-get-iter'): [
        'netapp_flexvol_encryption',
    ],
}


class CapabilitiesLibrary(object):

    def __init__(self, protocol, vserver_name, zapi_client, configuration):

        self.protocol = protocol.lower()
        self.vserver_name = vserver_name
        self.zapi_client = zapi_client
        self.configuration = configuration
        self.backend_name = self.configuration.safe_get('volume_backend_name')
        self.ssc = {}
        self.invalid_extra_specs = []

    def check_api_permissions(self):
        """Check which APIs that support SSC functionality are available."""

        inaccessible_apis = []
        invalid_extra_specs = []

        for api_tuple, extra_specs in SSC_API_MAP.items():
            object_name, operation_name, api = api_tuple
            if not self.zapi_client.check_cluster_api(object_name,
                                                      operation_name,
                                                      api):
                inaccessible_apis.append(api)
                invalid_extra_specs.extend(extra_specs)

        if inaccessible_apis:
            if 'volume-get-iter' in inaccessible_apis:
                msg = _('User not permitted to query Data ONTAP volumes.')
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                LOG.warning('The configured user account does not have '
                            'sufficient privileges to use all needed '
                            'APIs. The following extra specs will fail '
                            'or be ignored: %s.', invalid_extra_specs)

        self.invalid_extra_specs = invalid_extra_specs

    def cluster_user_supported(self):
        return not self.invalid_extra_specs

    def get_ssc(self):
        """Get a copy of the Storage Service Catalog."""

        return copy.deepcopy(self.ssc)

    def get_ssc_flexvol_names(self):
        """Get the names of the FlexVols in the Storage Service Catalog."""

        ssc = self.get_ssc()
        return list(ssc.keys())

    def get_ssc_for_flexvol(self, flexvol_name):
        """Get map of Storage Service Catalog entries for a single flexvol."""

        return copy.deepcopy(self.ssc.get(flexvol_name, {}))

    def get_ssc_aggregates(self):
        """Get a list of aggregates for all SSC flexvols."""

        aggregates = set()
        for __, flexvol_info in self.ssc.items():
            if 'netapp_aggregate' in flexvol_info:
                aggregates.add(flexvol_info['netapp_aggregate'])
        return list(aggregates)

    def update_ssc(self, flexvol_map):
        """Periodically runs to update Storage Service Catalog data.

        The self.ssc attribute is updated with the following format.
        {<flexvol_name> : {<ssc_key>: <ssc_value>}}
        """
        LOG.info("Updating storage service catalog information for "
                 "backend '%s'", self.backend_name)

        ssc = {}

        for flexvol_name, flexvol_info in flexvol_map.items():

            ssc_volume = {}

            # Add metadata passed from the driver, including pool name
            ssc_volume.update(flexvol_info)

            # Get volume info
            ssc_volume.update(self._get_ssc_flexvol_info(flexvol_name))
            ssc_volume.update(self._get_ssc_dedupe_info(flexvol_name))
            ssc_volume.update(self._get_ssc_mirror_info(flexvol_name))
            ssc_volume.update(self._get_ssc_encryption_info(flexvol_name))

            # Get aggregate info
            aggregate_name = ssc_volume.get('netapp_aggregate')
            ssc_volume.update(self._get_ssc_aggregate_info(aggregate_name))

            ssc[flexvol_name] = ssc_volume

        self.ssc = ssc

    def _update_for_failover(self, zapi_client, flexvol_map):

        self.zapi_client = zapi_client
        self.update_ssc(flexvol_map)

    def _get_ssc_flexvol_info(self, flexvol_name):
        """Gather flexvol info and recast into SSC-style volume stats."""

        volume_info = self.zapi_client.get_flexvol(flexvol_name=flexvol_name)

        netapp_thick = (volume_info.get('space-guarantee-enabled') and
                        (volume_info.get('space-guarantee') == 'file' or
                         volume_info.get('space-guarantee') == 'volume'))
        thick = self._get_thick_provisioning_support(netapp_thick)

        return {
            'netapp_thin_provisioned': six.text_type(not netapp_thick).lower(),
            'thick_provisioning_support': thick,
            'thin_provisioning_support': not thick,
            'netapp_aggregate': volume_info.get('aggregate'),
        }

    def _get_thick_provisioning_support(self, netapp_thick):
        """Get standard thick/thin values for a flexvol.

        The values reported for the standard thick_provisioning_support and
        thin_provisioning_support flags depend on both the flexvol state as
        well as protocol-specific configuration values.
        """

        if self.protocol == 'nfs':
            return (netapp_thick and
                    not self.configuration.nfs_sparsed_volumes)
        else:
            return (netapp_thick and
                    (self.configuration.netapp_lun_space_reservation ==
                     'enabled'))

    def _get_ssc_dedupe_info(self, flexvol_name):
        """Gather dedupe info and recast into SSC-style volume stats."""

        if ('netapp_dedup' in self.invalid_extra_specs or
                'netapp_compression' in self.invalid_extra_specs):
            dedupe = False
            compression = False
        else:
            dedupe_info = self.zapi_client.get_flexvol_dedupe_info(
                flexvol_name)
            dedupe = dedupe_info.get('dedupe')
            compression = dedupe_info.get('compression')

        return {
            'netapp_dedup': six.text_type(dedupe).lower(),
            'netapp_compression': six.text_type(compression).lower(),
        }

    def _get_ssc_encryption_info(self, flexvol_name):
        """Gather flexvol encryption info and recast into SSC-style stats."""
        encrypted = self.zapi_client.is_flexvol_encrypted(
            flexvol_name, self.vserver_name)

        return {'netapp_flexvol_encryption': six.text_type(encrypted).lower()}

    def _get_ssc_mirror_info(self, flexvol_name):
        """Gather SnapMirror info and recast into SSC-style volume stats."""

        mirrored = self.zapi_client.is_flexvol_mirrored(
            flexvol_name, self.vserver_name)

        return {'netapp_mirrored': six.text_type(mirrored).lower()}

    def _get_ssc_aggregate_info(self, aggregate_name):
        """Gather aggregate info and recast into SSC-style volume stats."""

        if 'netapp_raid_type' in self.invalid_extra_specs:
            raid_type = None
            hybrid = None
            disk_types = None
        else:
            aggregate = self.zapi_client.get_aggregate(aggregate_name)
            raid_type = aggregate.get('raid-type')
            hybrid = (six.text_type(aggregate.get('is-hybrid')).lower()
                      if 'is-hybrid' in aggregate else None)
            disk_types = self.zapi_client.get_aggregate_disk_types(
                aggregate_name)

        return {
            'netapp_raid_type': raid_type,
            'netapp_hybrid_aggregate': hybrid,
            'netapp_disk_type': disk_types,
        }

    def get_matching_flexvols_for_extra_specs(self, extra_specs):
        """Return a list of flexvol names that match a set of extra specs."""

        extra_specs = self._modify_extra_specs_for_comparison(extra_specs)
        matching_flexvols = []

        for flexvol_name, flexvol_info in self.get_ssc().items():

            if self._flexvol_matches_extra_specs(flexvol_info, extra_specs):
                matching_flexvols.append(flexvol_name)

        return matching_flexvols

    def _flexvol_matches_extra_specs(self, flexvol_info, extra_specs):
        """Check whether the SSC data for a FlexVol matches extra specs.

        A set of extra specs is considered a match for a FlexVol if, for each
        extra spec, the value matches what is in SSC or the key is unknown to
        SSC.
        """

        for extra_spec_key, extra_spec_value in extra_specs.items():

            if extra_spec_key in flexvol_info:
                if not self._extra_spec_matches(extra_spec_value,
                                                flexvol_info[extra_spec_key]):
                    return False

        return True

    def _extra_spec_matches(self, extra_spec_value, ssc_flexvol_value):
        """Check whether an extra spec value matches something in the SSC.

        The SSC values may be scalars or lists, so the extra spec value must be
        compared to the SSC value if it is a scalar, or it must be sought in
        the list.
        """

        if isinstance(ssc_flexvol_value, list):
            return extra_spec_value in ssc_flexvol_value
        else:
            return extra_spec_value == ssc_flexvol_value

    def _modify_extra_specs_for_comparison(self, extra_specs):
        """Adjust extra spec values for simple comparison to SSC values.

        Most extra-spec key-value tuples may be directly compared. But the
        boolean values that take the form '<is> True' or '<is> False' must be
        modified to allow comparison with the values we keep in the SSC and
        report to the scheduler.
        """

        modified_extra_specs = copy.deepcopy(extra_specs)

        for key, value in extra_specs.items():

            if isinstance(value, six.string_types):
                if re.match(r'<is>\s+True', value, re.I):
                    modified_extra_specs[key] = True
                elif re.match(r'<is>\s+False', value, re.I):
                    modified_extra_specs[key] = False

        return modified_extra_specs
