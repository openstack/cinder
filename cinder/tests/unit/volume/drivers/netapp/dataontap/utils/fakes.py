# Copyright (c) 2016 Clinton Knight
# All rights reserved.
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

SSC_VSERVER = 'fake_vserver'
SSC_VOLUMES = ('volume1', 'volume2')
SSC_VOLUME_MAP = {
    SSC_VOLUMES[0]: {
        'pool_name': SSC_VOLUMES[0],
    },
    SSC_VOLUMES[1]: {
        'pool_name': SSC_VOLUMES[1],
    },
}
SSC_AGGREGATES = ('aggr1', 'aggr2')

SSC = {
    'volume1': {
        'thick_provisioning_support': True,
        'thin_provisioning_support': False,
        'netapp_thin_provisioned': 'false',
        'aggregate': 'aggr1',
        'netapp_compression': 'false',
        'netapp_dedup': 'true',
        'netapp_mirrored': 'false',
        'netapp_raid_type': 'raid_dp',
        'netapp_disk_type': 'SSD',
        'pool_name': 'volume1',
    },
    'volume2': {
        'thick_provisioning_support': False,
        'thin_provisioning_support': True,
        'netapp_thin_provisioned': 'true',
        'aggregate': 'aggr2',
        'netapp_compression': 'true',
        'netapp_dedup': 'true',
        'netapp_mirrored': 'true',
        'netapp_raid_type': 'raid_dp',
        'netapp_disk_type': 'FCAL',
        'pool_name': 'volume2',
    },
}

SSC_FLEXVOL_INFO = {
    'volume1': {
        'thick_provisioning_support': True,
        'thin_provisioning_support': False,
        'netapp_thin_provisioned': 'false',
        'aggregate': 'aggr1',
    },
    'volume2': {
        'thick_provisioning_support': False,
        'thin_provisioning_support': True,
        'netapp_thin_provisioned': 'true',
        'aggregate': 'aggr2',
    },
}

SSC_DEDUPE_INFO = {
    'volume1': {
        'netapp_dedup': 'true',
        'netapp_compression': 'false',
    },
    'volume2': {
        'netapp_dedup': 'true',
        'netapp_compression': 'true',
    },
}

SSC_MIRROR_INFO = {
    'volume1': {
        'netapp_mirrored': 'false',
    },
    'volume2': {
        'netapp_mirrored': 'true',
    },
}

SSC_AGGREGATE_INFO = {
    'volume1': {
        'netapp_disk_type': 'SSD',
        'netapp_raid_type': 'raid_dp',
    },
    'volume2': {
        'netapp_disk_type': 'FCAL',
        'netapp_raid_type': 'raid_dp',
    },
}
