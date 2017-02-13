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

from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.netapp import options as na_opts

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
        'netapp_aggregate': 'aggr1',
        'netapp_compression': 'false',
        'netapp_dedup': 'true',
        'netapp_mirrored': 'false',
        'netapp_raid_type': 'raid_dp',
        'netapp_disk_type': ['SSD'],
        'netapp_hybrid_aggregate': 'false',
        'netapp_flexvol_encryption': 'true',
        'pool_name': 'volume1',
    },
    'volume2': {
        'thick_provisioning_support': False,
        'thin_provisioning_support': True,
        'netapp_thin_provisioned': 'true',
        'netapp_aggregate': 'aggr2',
        'netapp_compression': 'true',
        'netapp_dedup': 'true',
        'netapp_mirrored': 'true',
        'netapp_raid_type': 'raid_dp',
        'netapp_disk_type': ['FCAL', 'SSD'],
        'netapp_hybrid_aggregate': 'true',
        'netapp_flexvol_encryption': 'false',
        'pool_name': 'volume2',
    },
}

SSC_FLEXVOL_INFO = {
    'volume1': {
        'thick_provisioning_support': True,
        'thin_provisioning_support': False,
        'netapp_thin_provisioned': 'false',
        'netapp_aggregate': 'aggr1',
    },
    'volume2': {
        'thick_provisioning_support': False,
        'thin_provisioning_support': True,
        'netapp_thin_provisioned': 'true',
        'netapp_aggregate': 'aggr2',
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

SSC_ENCRYPTION_INFO = {
    'volume1': {
        'netapp_flexvol_encryption': 'true',
    },
    'volume2': {
        'netapp_flexvol_encryption': 'false',
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
        'netapp_disk_type': ['SSD'],
        'netapp_raid_type': 'raid_dp',
        'netapp_hybrid_aggregate': 'false',
    },
    'volume2': {
        'netapp_disk_type': ['FCAL', 'SSD'],
        'netapp_raid_type': 'raid_dp',
        'netapp_hybrid_aggregate': 'true',
    },
}

PROVISIONING_OPTS = {
    'aggregate': 'fake_aggregate',
    'thin_provisioned': True,
    'snapshot_policy': None,
    'language': 'en_US',
    'dedupe_enabled': False,
    'compression_enabled': False,
    'snapshot_reserve': '12',
    'volume_type': 'rw',
    'size': 20,
}

ENCRYPTED_PROVISIONING_OPTS = {
    'aggregate': 'fake_aggregate',
    'thin_provisioned': True,
    'snapshot_policy': None,
    'language': 'en_US',
    'dedupe_enabled': False,
    'compression_enabled': False,
    'snapshot_reserve': '12',
    'volume_type': 'rw',
    'size': 20,
    'encrypt': 'true',
}


def get_fake_cmode_config(backend_name):

    config = configuration.Configuration(driver.volume_opts,
                                         config_group=backend_name)
    config.append_config_values(na_opts.netapp_proxy_opts)
    config.append_config_values(na_opts.netapp_connection_opts)
    config.append_config_values(na_opts.netapp_transport_opts)
    config.append_config_values(na_opts.netapp_basicauth_opts)
    config.append_config_values(na_opts.netapp_provisioning_opts)
    config.append_config_values(na_opts.netapp_cluster_opts)
    config.append_config_values(na_opts.netapp_san_opts)
    config.append_config_values(na_opts.netapp_replication_opts)

    return config
