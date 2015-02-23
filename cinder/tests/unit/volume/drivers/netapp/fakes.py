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


from cinder.volume import configuration as conf
import cinder.volume.drivers.netapp.options as na_opts


ISCSI_FAKE_LUN_ID = 1

ISCSI_FAKE_IQN = 'iqn.1993-08.org.debian:01:10'

ISCSI_FAKE_ADDRESS = '10.63.165.216'

ISCSI_FAKE_PORT = '2232'

ISCSI_FAKE_VOLUME = {'id': 'fake_id'}

ISCSI_FAKE_TARGET = {}
ISCSI_FAKE_TARGET['address'] = ISCSI_FAKE_ADDRESS
ISCSI_FAKE_TARGET['port'] = ISCSI_FAKE_PORT

ISCSI_FAKE_VOLUME = {'id': 'fake_id', 'provider_auth': 'None stack password'}

FC_ISCSI_TARGET_INFO_DICT = {'target_discovered': False,
                             'target_portal': '10.63.165.216:2232',
                             'target_iqn': ISCSI_FAKE_IQN,
                             'target_lun': ISCSI_FAKE_LUN_ID,
                             'volume_id': ISCSI_FAKE_VOLUME['id'],
                             'auth_method': 'None', 'auth_username': 'stack',
                             'auth_password': 'password'}

VOLUME_NAME = 'fake_volume_name'
VOLUME_ID = 'fake_volume_id'
VOLUME_TYPE_ID = 'fake_volume_type_id'

VOLUME = {
    'name': VOLUME_NAME,
    'size': 42,
    'id': VOLUME_ID,
    'host': 'fake_host@fake_backend#fake_pool',
    'volume_type_id': VOLUME_TYPE_ID,
}


QOS_SPECS = {}

EXTRA_SPECS = {}

MAX_THROUGHPUT = '21734278B/s'
QOS_POLICY_GROUP_NAME = 'fake_qos_policy_group_name'
LEGACY_EXTRA_SPECS = {'netapp:qos_policy_group': QOS_POLICY_GROUP_NAME}

LEGACY_QOS = {
    'policy_name': QOS_POLICY_GROUP_NAME,
}

QOS_POLICY_GROUP_SPEC = {
    'max_throughput': MAX_THROUGHPUT,
    'policy_name': 'openstack-%s' % VOLUME_ID,
}

QOS_POLICY_GROUP_INFO_NONE = {'legacy': None, 'spec': None}

QOS_POLICY_GROUP_INFO = {'legacy': None, 'spec': QOS_POLICY_GROUP_SPEC}

LEGACY_QOS_POLICY_GROUP_INFO = {
    'legacy': LEGACY_QOS,
    'spec': None,
}

INVALID_QOS_POLICY_GROUP_INFO = {
    'legacy': LEGACY_QOS,
    'spec': QOS_POLICY_GROUP_SPEC,
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


def create_configuration_7mode():
    config = create_configuration()
    config.append_config_values(na_opts.netapp_7mode_opts)
    return config


def create_configuration_cmode():
    config = create_configuration()
    config.append_config_values(na_opts.netapp_cluster_opts)
    return config
