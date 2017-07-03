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
DEV_MODEL_STORWIZE_V3700 = '2072'
DEV_MODEL_STORWIZE_V7000 = '2076'
DEV_MODEL_STORWIZE_V5000 = '2078'
DEV_MODEL_STORWIZE_V5000_1YR = '2077'
DEV_MODEL_FLASH_V9000 = '9846'
DEV_MODEL_FLEX = '4939'

REP_CAP_DEVS = (DEV_MODEL_SVC, DEV_MODEL_STORWIZE, DEV_MODEL_STORWIZE_V5000,
                DEV_MODEL_STORWIZE_V5000_1YR, DEV_MODEL_FLASH_V9000,
                DEV_MODEL_FLEX)

# constants used for replication
GLOBAL = 'global'
METRO = 'metro'
GMCV = 'gmcv'
GMCV_MULTI = 'multi'
VALID_REP_TYPES = (GLOBAL, METRO, GMCV)
FAILBACK_VALUE = 'default'

DEFAULT_RC_TIMEOUT = 3600 * 24 * 7
DEFAULT_RC_INTERVAL = 5

REPLICA_AUX_VOL_PREFIX = 'aux_'
REPLICA_CHG_VOL_PREFIX = 'chg_'

# remote mirror copy status
REP_CONSIS_SYNC = 'consistent_synchronized'
REP_CONSIS_COPYING = 'consistent_copying'
REP_CONSIS_STOP = 'consistent_stopped'
REP_SYNC = 'synchronized'
REP_IDL = 'idling'
REP_IDL_DISC = 'idling_disconnected'
REP_STATUS_ON_LINE = 'online'
