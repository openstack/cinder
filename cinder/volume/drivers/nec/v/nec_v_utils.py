# Copyright (C) 2021 NEC corporation
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
#
"""Utility module for NEC Driver."""

VERSION = '1.0.0'
CI_WIKI_NAME = 'NEC_V_Cinder_CI'
PARAM_PREFIX = 'nec_v'
VENDOR_NAME = 'NEC'
DRIVER_PREFIX = 'NEC'
DRIVER_FILE_PREFIX = 'nec'
TARGET_PREFIX = 'NEC-'
HDP_VOL_ATTR = 'DP'
HDT_VOL_ATTR = 'DT'
NVOL_LDEV_TYPE = 'DP-VOL'
TARGET_IQN_SUFFIX = '.nec-target'
PAIR_ATTR = 'SS'

DRIVER_INFO = {
    'version': VERSION,
    'proto': '',
    'hba_id': '',
    'hba_id_type': '',
    'msg_id': {
        'target': '',
    },
    'volume_backend_name': '',
    'volume_type': '',
    'param_prefix': PARAM_PREFIX,
    'vendor_name': VENDOR_NAME,
    'driver_prefix': DRIVER_PREFIX,
    'driver_file_prefix': DRIVER_FILE_PREFIX,
    'target_prefix': TARGET_PREFIX,
    'hdp_vol_attr': HDP_VOL_ATTR,
    'hdt_vol_attr': HDT_VOL_ATTR,
    'nvol_ldev_type': NVOL_LDEV_TYPE,
    'target_iqn_suffix': TARGET_IQN_SUFFIX,
    'pair_attr': PAIR_ATTR,
}
