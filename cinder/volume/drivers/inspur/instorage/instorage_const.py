# Copyright 2017 Inspur Corp.
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

DEV_MODEL_INSTORAGE = '1813'
DEV_MODEL_INSTORAGE_AS5X00 = '2076'


REP_CAP_DEVS = (DEV_MODEL_INSTORAGE, DEV_MODEL_INSTORAGE_AS5X00)

# constants used for replication
ASYNC = 'async'
SYNC = 'sync'
VALID_REP_TYPES = (ASYNC, SYNC)
FAILBACK_VALUE = 'default'

DEFAULT_RC_TIMEOUT = 3600 * 24 * 7
DEFAULT_RC_INTERVAL = 5

REPLICA_AUX_VOL_PREFIX = 'aux_'

# remote mirror copy status
REP_CONSIS_SYNC = 'consistent_synchronized'
REP_CONSIS_STOP = 'consistent_stopped'
REP_SYNC = 'synchronized'
REP_IDL = 'idling'
REP_IDL_DISC = 'idling_disconnected'
REP_STATUS_ON_LINE = 'online'
