# Copyright (c) - 2014, Clinton Knight  All rights reserved.
# Copyright (c) - 2015, Alex Meade.  All Rights Reserved.
# Copyright (c) - 2015, Rushil Chugh.  All Rights Reserved.
# Copyright (c) - 2015, Tom Barron.  All Rights Reserved.
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


from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
import cinder.volume.drivers.netapp.options as na_opts


ISCSI_FAKE_LUN_ID = 1

ISCSI_FAKE_IQN = 'iqn.1993-08.org.debian:01:10'
ISCSI_FAKE_IQN2 = 'iqn.1993-08.org.debian:01:11'

ISCSI_FAKE_ADDRESS_IPV4 = '10.63.165.216'
ISCSI_FAKE_ADDRESS2_IPV4 = '10.63.165.217'
ISCSI_FAKE_ADDRESS_IPV6 = 'fe80::72a4:a152:aad9:30d9'

ISCSI_FAKE_PORT = '2232'

ISCSI_FAKE_VOLUME = {'id': 'fake_id'}

ISCSI_FAKE_TARGET = {}
ISCSI_FAKE_TARGET['address'] = ISCSI_FAKE_ADDRESS_IPV4
ISCSI_FAKE_TARGET['port'] = ISCSI_FAKE_PORT

ISCSI_FAKE_VOLUME = {'id': 'fake_id', 'provider_auth': 'None stack password'}
ISCSI_FAKE_VOLUME_NO_AUTH = {'id': 'fake_id', 'provider_auth': ''}

ISCSI_MP_TARGET_INFO_DICT = {'target_discovered': False,
                             'target_portal': '10.63.165.216:2232',
                             'target_portals': ['10.63.165.216:2232',
                                                '10.63.165.217:2232'],
                             'target_iqn': ISCSI_FAKE_IQN,
                             'target_iqns': [ISCSI_FAKE_IQN, ISCSI_FAKE_IQN2],
                             'target_lun': ISCSI_FAKE_LUN_ID,
                             'target_luns': [ISCSI_FAKE_LUN_ID] * 2,
                             'volume_id': ISCSI_FAKE_VOLUME['id'],
                             'auth_method': 'None', 'auth_username': 'stack',
                             'auth_password': 'password'}

FC_ISCSI_TARGET_INFO_DICT = {'target_discovered': False,
                             'target_portal': '10.63.165.216:2232',
                             'target_iqn': ISCSI_FAKE_IQN,
                             'target_lun': ISCSI_FAKE_LUN_ID,
                             'volume_id': ISCSI_FAKE_VOLUME['id'],
                             'auth_method': 'None', 'auth_username': 'stack',
                             'auth_password': 'password'}

FC_ISCSI_TARGET_INFO_DICT_IPV6 = {'target_discovered': False,
                                  'target_portal':
                                      '[fe80::72a4:a152:aad9:30d9]:2232',
                                  'target_iqn': ISCSI_FAKE_IQN,
                                  'target_lun': ISCSI_FAKE_LUN_ID,
                                  'volume_id': ISCSI_FAKE_VOLUME['id']}

VOLUME_NAME = 'fake_volume_name'
VOLUME_ID = '80113942-01fd-4114-aaee-9d73ecb536d5'
VOLUME_TYPE_ID = '20c9718a-9256-4bf8-9f94-1c6f4e7f0c84'

VOLUME = fake_volume.fake_volume_obj(None,
                                     name=VOLUME_NAME,
                                     size=42,
                                     id=VOLUME_ID,
                                     host='fake_host@fake_backend#fake_pool',
                                     volume_type_id=VOLUME_TYPE_ID)

SNAPSHOT_NAME = 'fake_snapshot_name'
SNAPSHOT_ID = 'fake_snapshot_id'

SNAPSHOT = {
    'name': SNAPSHOT_NAME,
    'id': SNAPSHOT_ID,
    'volume_id': VOLUME_ID,
    'volume_name': VOLUME_NAME,
    'volume_size': 42,
}

QOS_SPECS = {}

EXTRA_SPECS = {}

MAX_THROUGHPUT_BPS = '21734278B/s'
QOS_POLICY_GROUP_NAME = 'fake_qos_policy_group_name'
LEGACY_EXTRA_SPECS = {'netapp:qos_policy_group': QOS_POLICY_GROUP_NAME}

EXPECTED_IOPS_PER_GB = '128'
PEAK_IOPS_PER_GB = '512'
EXPECTED_IOPS_ALLOCATION = 'used-space'
PEAK_IOPS_ALLOCATION = 'used-space'
ABSOLUTE_MIN_IOPS = '75'
BLOCK_SIZE = 'ANY'
ADAPTIVE_QOS_SPEC = {
    'expectedIOPSperGiB': EXPECTED_IOPS_PER_GB,
    'peakIOPSperGiB': PEAK_IOPS_PER_GB,
    'expectedIOPSAllocation': EXPECTED_IOPS_ALLOCATION,
    'peakIOPSAllocation': PEAK_IOPS_ALLOCATION,
    'absoluteMinIOPS': ABSOLUTE_MIN_IOPS,
    'blockSize': BLOCK_SIZE,
}

LEGACY_QOS = {
    'policy_name': QOS_POLICY_GROUP_NAME,
}

QOS_POLICY_GROUP_SPEC = {
    'max_throughput': MAX_THROUGHPUT_BPS,
    'policy_name': 'openstack-%s' % VOLUME_ID,
}

QOS_POLICY_GROUP_INFO_NONE = {'legacy': None, 'spec': None}

QOS_POLICY_GROUP_INFO = {'legacy': None, 'spec': QOS_POLICY_GROUP_SPEC}

ADAPTIVE_QOS_POLICY_GROUP_SPEC = {
    'expected_iops': '128IOPS/GB',
    'peak_iops': '512IOPS/GB',
    'expected_iops_allocation': 'used-space',
    'peak_iops_allocation': 'used-space',
    'absolute_min_iops': '75IOPS',
    'block_size': 'ANY',
    'policy_name': 'openstack-%s' % VOLUME_ID,
}

LEGACY_QOS_POLICY_GROUP_INFO = {
    'legacy': LEGACY_QOS,
    'spec': None,
}

INVALID_QOS_POLICY_GROUP_INFO_LEGACY_AND_SPEC = {
    'legacy': LEGACY_QOS,
    'spec': QOS_POLICY_GROUP_SPEC,
}

INVALID_QOS_POLICY_GROUP_INFO_STANDARD_AND_ADAPTIVE = {
    'legacy': None,
    'spec': {**QOS_POLICY_GROUP_SPEC, **ADAPTIVE_QOS_SPEC},
}

QOS_SPECS_ID = 'fake_qos_specs_id'
QOS_SPEC = {'maxBPS': 21734278}
OUTER_BACKEND_QOS_SPEC = {
    'id': QOS_SPECS_ID,
    'specs': QOS_SPEC,
    'consumer': 'back-end',
}
OUTER_FRONTEND_QOS_SPEC = {
    'id': QOS_SPECS_ID,
    'specs': QOS_SPEC,
    'consumer': 'front-end',
}
OUTER_BOTH_QOS_SPEC = {
    'id': QOS_SPECS_ID,
    'specs': QOS_SPEC,
    'consumer': 'both',
}
VOLUME_TYPE = {'id': VOLUME_TYPE_ID, 'qos_specs_id': QOS_SPECS_ID}


def create_configuration():
    config = conf.Configuration(None)
    config.append_config_values(na_opts.netapp_connection_opts)
    config.append_config_values(na_opts.netapp_transport_opts)
    config.append_config_values(na_opts.netapp_basicauth_opts)
    config.append_config_values(na_opts.netapp_provisioning_opts)
    return config


def create_configuration_cmode():
    config = create_configuration()
    config.append_config_values(na_opts.netapp_cluster_opts)
    return config
