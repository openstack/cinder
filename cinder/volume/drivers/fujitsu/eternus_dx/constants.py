# Copyright (c) 2019 FUJITSU LIMITED
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

RAIDGROUP = 2
TPPOOL = 5
SNAPOPC = 4
OPC = 5
RETURN_TO_RESOURCEPOOL = 19
DETACH = 8
BROKEN = 5

JOB_RETRIES = 60
JOB_INTERVAL_SEC = 10
TIMES_MIN = 3
EC_REC = 3
RETRY_INTERVAL = 5
# Error code keyword.
VOLUME_IS_BUSY = 32786
DEVICE_IS_BUSY = 32787
VOLUMENAME_IN_USE = 32788
COPYSESSION_NOT_EXIST = 32793
LUNAME_IN_USE = 4102
LUNAME_NOT_EXIST = 4097  # Only for InvokeMethod(HidePaths).
VOL_PREFIX = "FJosv_"
REPL = "FUJITSU_ReplicationService"
STOR_CONF = "FUJITSU_StorageConfigurationService"
CTRL_CONF = "FUJITSU_ControllerConfigurationService"
UNDEF_MSG = 'Undefined Error!!'

POOL_TYPE_dic = {
    RAIDGROUP: 'RAID_GROUP',
    TPPOOL: 'Thinporvisioning_POOL',
}
POOL_TYPE_list = [
    'RAID',
    'TPP'
]
OPERATION_dic = {
    SNAPOPC: RETURN_TO_RESOURCEPOOL,
    OPC: DETACH,
    EC_REC: DETACH,
}

RETCODE_dic = {
    '0': 'Success',
    '1': 'Method Not Supported',
    '4': 'Failed',
    '5': 'Invalid Parameter',
    '4096': 'Method Parameters Checked - Job Started',
    '4097': 'Size Not Supported',
    '4101': 'Target/initiator combination already exposed',
    '4102': 'Requested logical unit number in use',
    '32769': 'Maximum number of Logical Volume in a RAID group '
             'has been reached',
    '32770': 'Maximum number of Logical Volume in the storage device '
             'has been reached',
    '32771': 'Maximum number of registered Host WWN '
             'has been reached',
    '32772': 'Maximum number of affinity group has been reached',
    '32773': 'Maximum number of host affinity has been reached',
    '32781': 'Not available under current system configuration',
    '32782': 'Controller firmware update in process',
    '32785': 'The RAID group is in busy state',
    '32786': 'The Logical Volume is in busy state',
    '32787': 'The device is in busy state',
    '32788': 'Element Name is in use',
    '32791': 'Maximum number of copy session has been reached',
    '32792': 'No Copy License',
    '32793': 'Session does not exist',
    '32794': 'Phase is not correct',
    '32796': 'Quick Format Error',
    '32801': 'The CA port is in invalid setting',
    '32802': 'The Logical Volume is Mainframe volume',
    '32803': 'The RAID group is not operative',
    '32804': 'The Logical Volume is not operative',
    '32805': 'The Logical Element is Thin provisioning Pool Volume',
    '32806': 'The Logical Volume is pool for copy volume',
    '32807': 'The Logical Volume is unknown volume',
    '32808': 'No Thin Provisioning License',
    '32809': 'The Logical Element is ODX volume',
    '32810': 'The specified volume is under use as NAS volume',
    '32811': 'This operation cannot be performed to the NAS resources',
    '32812': 'This operation cannot be performed to the '
             'Transparent Failover resources',
    '32813': 'This operation cannot be performed to the '
             'VVOL resources',
    '32816': 'Generic fatal error',
    '32817': 'Inconsistent State with 1Step Restore '
             'operation',
    '32818': 'REC Path failure during copy',
    '32819': 'RAID failure during EC/REC copy',
    '32820': 'Previous command in process',
    '32821': 'Cascade local copy session exist',
    '32822': 'Cascade EC/REC session is not suspended',
    '35302': 'Invalid LogicalElement',
    '35304': 'LogicalElement state error',
    '35316': 'Multi-hop error',
    '35318': 'Maximum number of multi-hop has been reached',
    '35324': 'RAID is broken',
    '35331': 'Maximum number of session has been reached(per device)',
    '35333': 'Maximum number of session has been reached(per SourceElement)',
    '35334': 'Maximum number of session has been reached(per TargetElement)',
    '35335': 'Maximum number of Snapshot generation has been reached '
             '(per SourceElement)',
    '35346': 'Copy table size is not setup',
    '35347': 'Copy table size is not enough',
}
