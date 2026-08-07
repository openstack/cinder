# Copyright 2016 IBM Corp.
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
#

# product id is 2145 for SVC 6.1.0+. no product id for older version.
DEV_MODEL_SVC = '2145'
DEV_MODEL_STORWIZE = '2076'
DEV_MODEL_STORWIZE_V3500 = '2071'
DEV_MODEL_STORWIZE_V5000E = '2072'
DEV_MODEL_STORWIZE_V7000 = '2076'
DEV_MODEL_STORWIZE_V5000 = '2078'
DEV_MODEL_STORWIZE_V5000_1YR = '2077'
DEV_MODEL_FLASH_V9000 = '9846'
DEV_MODEL_FLEX = '4939'

REP_CAP_DEVS = (DEV_MODEL_SVC, DEV_MODEL_STORWIZE, DEV_MODEL_STORWIZE_V5000,
                DEV_MODEL_STORWIZE_V5000_1YR, DEV_MODEL_FLASH_V9000,
                DEV_MODEL_FLEX, DEV_MODEL_STORWIZE_V5000E)

# constants used for replication
GLOBAL = 'global'
METRO = 'metro'
GMCV = 'gmcv'
GMCV_MULTI = 'multi'
VALID_REP_TYPES = (GLOBAL, METRO, GMCV)
FAILBACK_VALUE = 'default'

DEFAULT_RC_TIMEOUT = 3600 * 24 * 7
DEFAULT_RC_INTERVAL = 5

DEFAULT_RCCG_TIMEOUT = 60 * 30
DEFAULT_RCCG_INTERVAL = 2

REPLICA_AUX_VOL_PREFIX = 'aux_'
REPLICA_CHG_VOL_PREFIX = 'chg_'

RCCG_PREFIX = 'rccg-'
HYPERCG_PREFIX = 'hycg-'

VG_PREFIX = 'vg-'
VG_SNAPSHOT_PREFIX = 'vg_snap-'

# remote mirror copy status
REP_CONSIS_SYNC = 'consistent_synchronized'
REP_CONSIS_COPYING = 'consistent_copying'
REP_CONSIS_STOP = 'consistent_stopped'
REP_SYNC = 'synchronized'
REP_IDL = 'idling'
REP_IDL_DISC = 'idling_disconnected'
REP_STATUS_ON_LINE = 'online'

# IOThrottling types
MBPS = 'mbps'
IOPS = 'iops'
IOPS_PER_GB = 'iops_per_gb'

# Error codes SVC mappings
ERR_INVALID_OBJECT_OR_UNSUITABLE_CANDIDATE = 'CMMVC5753E'
ERR_OBJECT_ALREADY_EXISTS = 'CMMVC6035E'
ERR_NONEMPTY_VOLUME_GROUP = 'CMMVC8749E'
ERR_INVALID_OBJECT_AND_NAME = 'CMMVC5754E'
ERR_HOST_ALREADY_MAPPED = 'CMMVC6071E'
ERR_HOST_ALREADY_MAPPED_SCSI = 'CMMVC5879E'
ERR_NAME_ASSIGNED_OR_INVALID = 'CMMVC6578E'
ERR_RELATIONSHIP_EXISTS = 'CMMVC5959E'

# warning codes for svc mappings
WARN_APPROACHING_LICENSED_STORAGE_CAPACITY = 'CMMVC6372W'

# SVC Code level version number mappings
SVC_CODE_LEVEL_8420 = (8, 4, 2, 0)
SVC_CODE_LEVEL_7700 = (7, 7, 0, 0)
SVC_CODE_LEVEL_8500 = (8, 5, 0, 0)
SVC_CODE_LEVEL_7810 = (7, 8, 1, 0)
SVC_CODE_LEVEL_8510 = (8, 5, 1, 0)
SVC_CODE_LEVEL_8620 = (8, 6, 2, 0)

# Register plugin constants
CINDER = 'CINDER'
COMMUNITY = 'Community'
POWERVC = 'PowerVC'
DEFAULT_RP_TIMEOUT = 3600 * 24
