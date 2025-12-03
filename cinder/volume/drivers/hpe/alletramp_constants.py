#    (c) Copyright 2026 Hewlett Packard Enterprise Development LP
#    All Rights Reserved.
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
THIN = 2
DEDUP = 6
CONVERT_TO_THIN = 1
CONVERT_TO_DEDUP = 4

SYNC = 1
PERIODIC = 2
EXTRA_SPEC_REP_MODE = "replication:mode"
EXTRA_SPEC_REP_SYNC_PERIOD = "replication:sync_period"
RC_ACTION_CHANGE_TO_PRIMARY = 7
DEFAULT_REP_MODE = 'periodic'
DEFAULT_SYNC_PERIOD = 900
RC_GROUP_STARTED = 3
SYNC_STATUS_COMPLETED = 3
FAILBACK_VALUE = 'default'
ACTIVE_PP_REP_POLICY = 'active-active'
PROXIMITY_ALL = 'all'

API_VERSION_R5 = 100500000
COMPRESSION_API_VERSION = 30301215

valid_prov_values = ['thin', 'dedup']
valid_persona_values = ['2 - Generic-ALUA',
                        '1 - Generic',
                        '3 - Generic-legacy',
                        '4 - HPUX-legacy',
                        '5 - AIX-legacy',
                        '6 - EGENERA',
                        '7 - ONTAP-legacy',
                        '8 - VMware',
                        '9 - OpenVMS',
                        '10 - HPUX',
                        '11 - WindowsServer']

hpe_qos_keys = ['minIOPS', 'maxIOPS', 'minBWS', 'maxBWS', 'latency',
                'priority']
qos_priority_level = {'low': 1, 'normal': 2, 'high': 3}
hpe3par_valid_keys = ['cpg', 'snap_cpg', 'provisioning', 'persona', 'vvs',
                      'flash_cache', 'compression', 'group_replication',
                      'convert_to_base']

TASK_DONE = 1
TASK_ACTIVE = 2

PORT_MODE_TARGET = 2
PORT_PROTO_FC = 1
PORT_PROTO_ISCSI = 2
PORT_STATE_READY = 4

HOST_EDIT_ADD = 1
HOST_EDIT_REMOVE = 2
CHAP_INITIATOR = 1

EXISTENT_PATH = 73

API_ERROR_150 = 150
API_ERROR_187 = 187
API_ERROR_102 = 102
API_ERROR_23 = 23
API_ERROR_215 = 215
API_ERROR_29 = 29
API_ERROR_40 = 40
API_ERROR_34 = 34
API_ERROR_151 = 151
API_ERROR_32 = 32

DEFAULT_ISCSI_PORT = 3260
CHAP_USER_KEY = "HPQ-cinder-CHAP-name"
CHAP_PASS_KEY = "HPQ-cinder-CHAP-secret"

THROUGHPUT = 'throughput'
BANDWIDTH = 'bandwidth'
LATENCY = 'latency'
IO_SIZE = 'io_size'
QUEUE_LENGTH = 'queue_length'
AVG_BUSY_PERC = 'avg_busy_perc'

HOST_DOES_NOT_EXISTS = "host does not exist"
