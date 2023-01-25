#    (c)  Copyright 2022 Fungible, Inc. All rights reserved.
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
Define all constants required for fungible driver
"""
# API constants
VERSION = '1.0.0'
STATIC_URL = '/FunCC/v1'

# Volume type constants
VOLUME_TYPE_EC = 'VOL_TYPE_BLK_EC'
VOLUME_TYPE_REPLICA = 'VOL_TYPE_BLK_REPLICA'
VOLUME_TYPE_RAW = 'VOL_TYPE_BLK_LOCAL_THIN'
VOLUME_TYPE_RF1 = 'VOL_TYPE_BLK_RF1'

# General constants
FALSE = 'false'
TRUE = 'true'
BOOLEAN = [TRUE, FALSE]
BYTES_PER_GIB = 1073741824
FSC_IOPS_IMG_MIG = "iops_for_image_migration"

# Extra specs constants
FSC_QOS_BAND = 'fungible:qos_band'
FSC_SPACE_ALLOCATION_POLICY = 'fungible:space_allocation_policy'
FSC_COMPRESSION = 'fungible:compression'
FSC_EC_SCHEME = 'fungible:ec_scheme'
FSC_SNAPSHOTS = "fungible:snapshots"
FSC_KMIP_SECRET_KEY = 'fungible:kmip_secret_key'
FSC_VOL_TYPE = 'fungible:vol_type'
FSC_BLK_SIZE = "fungible:block_size"
FSC_FD_IDS = 'fungible:fault_domain_ids'
FSC_FD_OP = 'fungible:fd_op'
BLOCK_SIZE_4K = '4096'
BLOCK_SIZE_8K = '8192'
BLOCK_SIZE_16K = '16384'
BLOCK_SIZE = [BLOCK_SIZE_4K, BLOCK_SIZE_8K, BLOCK_SIZE_16K]
FSC_FD_OPS = ['SUGGESTED_FD_IDS', 'EXCLUDE_FD_IDS', 'ASSIGNED_FD_ID']
SPACE_ALLOCATION_POLICY = ['balanced', 'write_optimized', 'capacity_optimized']
EC_8_2 = '8_2'
EC_4_2 = '4_2'
EC_2_1 = '2_1'
QOS_BAND = {
    'gold': 0,
    'silver': 1,
    'bronze': 2
}
