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

DX_S2 = 2
DX_S3 = 3
JOB_RETRIES = 60
JOB_INTERVAL_SEC = 10
TIMES_MIN = 3
EC_REC = 3
RETRY_INTERVAL = 5
# Error code keyword.
RG_VOLNUM_MAX = 32769
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

MAX_IOPS = 4294967295
MAX_THROUGHPUT = 2097151
MIN_IOPS = 1
MIN_THROUGHPUT = 1

RC_OK = 0
RC_FAILED = 4

QOS_VERSION = 'V11L30-0000'
# Here is a misspelling, and the right value should be "Thinprovisioning_POOL".
# It would not be compatible with the metadata of the legacy volumes,
# so this spelling mistake needs to be retained.
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
FJ_QOS_KEY_list = [
    'maxBWS'
]
FJ_QOS_KEY_BYTES_list = [
    'read_bytes_sec',
    'write_bytes_sec',
    'total_bytes_sec'
]
FJ_QOS_KEY_IOPS_list = [
    'read_iops_sec',
    'write_iops_sec',
    'total_iops_sec'
]

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

CLIRETCODE_dic = {
    'E0001': 'Bad value',
    'E0002': 'Value out of range',
    'E0003': 'Too many parameters',
    'E0004': 'Missing parameter',
    'E0005': 'Incorrect parameter combination',
    'E0006': 'Inconsistent status',
    'E0007': 'Inconsistent usage',
    'E0008': 'Inconsistent size',
    'E0009': 'Inconsistent RAID level',
    'E0010': 'Inconsistent model type of device',
    'E0011': 'Inconsistent network setup',
    'E0012': 'Inconsistent e-mail setup',
    'E0014': 'Inconsistent disk status',
    'E0015': 'Inconsistent enclosure status',
    'E0019': 'Inconsistent parameter',
    'E0020': 'Internal error',
    'E0021': 'The requested operation has failed',
    'E0030': 'Command not supported',
    'E0031': 'Reserved keyword is used',
    'E0032': 'Controller firmware cannot be downgraded',
    'E0033': 'Not applicable to this target',
    'E0034': 'Mainframe resources',
    'E0035': 'Disk firmware can only be upgraded',
    'E0041': 'Incorrect password syntax',
    'E0042': 'Incorrect password',
    'E0050': 'Incorrect file',
    'E0051': 'Incorrect license key',
    'E0052': 'File access failure',
    'E0053': 'Remote server access failure',
    'E0060': 'Resource locked',
    'E0061': 'Lock was relinquished to another user',
    'E0070': 'Resource busy',
    'E0071': 'Resource is linked to the other resource',
    'E0072': 'Resource is temporarily insufficient',
    'E0073': 'Drive is currently busy. Wait a while, and then retry',
    'E0080': 'Resource limited',
    'E0081': 'Number of active disks has reached the system limit',
    'E0089': 'Not available under current Advanced Copy usable'
             ' mode conditions',
    'E0090': 'Not available under current system status conditions',
    'E0091': 'Not available under current SNMP settings',
    'E0092': 'Not available under current operation mode conditions',
    'E0093': 'Not available under current host affinity mode conditions',
    'E0094': 'Not available under current encryption status conditions',
    'E0095': 'Not available under current e-mailing conditions',
    'E0097': 'Not available under master controller module',
    'E0098': 'Not available under slave controller module',
    'E0099': 'Not available under current system configuration',
    'E0100': 'No space',
    'E0101': 'No memory',
    'E0102': 'Not available under system disk status',
    'E0110': 'Resource does not exist',
    'E0111': 'Resource is not reserved',
    'E0113': 'No SNMP trap information',
    'E0114': 'No volumes in the RAID group / Thin Provisioning Pool',
    'E0115': 'Performance monitor has not started',
    'E0116': 'The system disks are included in the RAID group',
    'E0117': 'No target disks',
    'E0118': 'Remote Copy target is not supported model',
    'E0120': 'Already registered',
    'E0122': 'Closure of all CLI and GUI ports requires confirmation',
    'E0123': 'Closure of all CLI ports requires confirmation',
    'E0131': 'Already unmapped',
    'E0132': 'Already stopped',
    'E0133': 'Already running for expanding others',
    'E0140': 'One or more components have failed',
    'E0141': 'At least one resource is required',
    'E0142': 'One or more encrypted volumes exist',
    'E0143': 'Unexpected error occurred during operator intervention',
    'E0145': 'Advanced Copy table exists',
    'E0146': 'RAID group contains a temporary volume',
    'E0150': 'Collecting performance data',
    'E0151': 'Power-off or power-on in process',
    'E0152': 'Volumes formatting in process',
    'E0153': 'Encryption or decryption of volumes in process',
    'E0154': 'Advanced Copy session active',
    'E0155': 'Volumes migration in process',
    'E0156': 'RAID group expansion in process',
    'E0157': 'Remote Copy session active',
    'E0158': 'Controller firmware update in process',
    'E0159': 'Remote maintenance in process',
    'E0160': 'Competing with background process',
    'E0161': 'Competing with disk diagnosis running in background process',
    'E0162': 'Competing with RAID group diagnosis running in '
             'background process',
    'E0163': 'Competing with hot update of firmware in background process',
    'E0164': 'Competing with cold update of firmware in background process',
    'E0165': 'Competing with update of disk firmware in background process',
    'E0166': 'Competing with quick formatting of volume in '
             'background process',
    'E0167': 'Competing with changing Advanced Copy parameters in '
             'background process',
    'E0168': 'Competing with allocating remote copy buffer in '
             'background process',
    'E0169': 'Competing with preparing firmware update in background process',
    'E0170': 'Competing with setting cache control in background process',
    'E0171': 'Competing with reassigning RAID group controller in '
             'background process',
    'E0172': 'Competing with initializing volume in background process',
    'E0173': 'Competing with encrypting or decrypting volume in '
             'background process',
    'E0174': 'Competing with registering RAID group in background process',
    'E0175': 'Competing with deleting RAID group in background process',
    'E0176': 'Competing with registering volume in background process',
    'E0177': 'Competing with deleting volume in background process',
    'E0178': 'Competing with registering global hot spare in '
             'background process',
    'E0179': 'Competing with changing maintenance mode in background process',
    'E0180': 'Competing with moving volume in background process',
    'E0181': 'Competing with expanding RAID group in background process',
    'E0182': 'Competing with collecting G-List information in '
             'background process',
    'E0183': 'Competing with setting Eco-mode in background process',
    'E0184': 'Competing with assigning Eco-mode schedule in '
             'background process',
    'E0185': 'Competing with setting Eco-mode schedule in background process',
    'E0186': 'Competing with setting date and time in background process',
    'E0187': 'Competing with expanding volume in background process',
    'E0188': 'Competing with deleting Advanced Copy session in '
             'background process',
    'E0190': 'Competing with registering dedicated hot spare in '
             'background process',
    'E0191': 'Competing with releasing dedicated hot spare in '
             'background process',
    'E0192': 'Competing with collecting event information in '
             'background process',
    'E0193': 'Competing with deleting snap data volume in '
             'background process',
    'E0194': 'Reclamation of Thin Provisioning Volume is in progress',
    'E0195': 'Rebuild or Copyback in process',
    'E0196': 'Competing with storage migration in background process',
    'E0197': 'Quick UNMAP in process',
    'E0198': 'Flexible tier migration in process',
    'E0200': 'Competing with setting Flexible tier mode in background process',
    'E0201': 'Competing with deleting Flexible tier pool in '
             'background process',
    'E0202': 'Competing with formatting Flexible tier pool in '
             'background process',
    'E0203': 'Competing with registering Flexible tier volume in '
             'background process',
    'E0204': 'Competing with setting Flexible tier sub pool priority in '
             'background process',
    'E0205': 'Competing with setting Flexible tier pool parameters in '
             'background process',
    'E0206': 'Competing with Flexible tier migration in background process',
    'E0207': 'Competing with registering Thin Provisioning Pool in '
             'background process',
    'E0208': 'Competing with deleting Thin Provisioning Volume in '
             'background process',
    'E0209': 'Competing with formatting Thin Provisioning Volume in '
             'background process',
    'E0210': 'Competing with setting Thin Provisioning Volume parameters in '
             'background process',
    'E0211': 'Competing with registering REC Disk Buffer Volume in '
             'background process',
    'E0212': 'Competing with deleting REC Disk Buffer Volume in '
             'background process',
    'E0213': 'Competing with inhibiting copy destination volume in '
             'background process',
    'E0214': 'Competing with Thin Provisioning Pool migration in '
             'background process',
    'E0215': 'Competing with setting cache size limit to volume in '
             'background process',
    'E0216': 'Competing with setting Offloaded Data Transfer Mode in '
             'background process',
    'E0217': 'Competing with setting Key management group ID in '
             'background process',
    'E0218': 'Competing with changing Key in background process',
    'E0300': 'Syntax error in REC path information. (Incorrect file header)',
    'E0301': 'Syntax error in REC path information. (Version mismatch)',
    'E0302': 'Syntax error in REC path information. (Incorrect label)',
    'E0303': 'Syntax error in REC path information. (Incorrect operand)',
    'E0304': 'Syntax error in REC path information. (Duplicate definition)',
    'E0305': 'Syntax error in REC path information. (Missing label)',
    'E0306': 'Syntax error in REC path information. (Too many labels)',
    'E0307': 'Syntax error in REC path information. (Missing double quotes)',
    'E0308': 'Syntax error in REC path information. (Unexpected label)',
    'E0309': 'Syntax error in REC path information. (Undefined information)',
    'E0311': 'Syntax error in REC path information. (Too many lines)',
    'E0312': 'Syntax error in REC path information. (Overlong line)',
    'E0313': 'Syntax error in REC path information. '
             '(WWN does not match actual)',
    'E0314': 'Syntax error in REC path information. '
             '(Host port mode does not match actual)',
    'E0315': 'Syntax error in REC path information. (Number of storage-links '
             'for one storage system over upper limit)',
    'E0316': 'Syntax error in REC path information. (Number of storage-links '
             'between one pair of storage systems over upper limit)',
    'E0317': 'Syntax error in REC path information. (Number of port-links for '
             'one host interface port over upper limit)',
    'E0318': 'Syntax error in REC path information. (Number of host interface '
             'ports for one storage system over upper limit)',
    'E0319': 'Syntax error in REC path information. (Total number of '
             'storage systems over upper limit)',
    'E0320': 'Syntax error in REC path information. (Total number of '
             'links over upper limit)',
    'E0321': 'Syntax error in REC path information. (CA type or IP version '
             'do not match)',
    'E0330': 'Flexible tier mode is valid',
    'E0331': 'Flexible tier mode is not valid',
    'E0332': 'One or more Flexible Tier Pools exist',
    'E0333': 'Cannot format Flexible Tier Pool',
    'E0334': 'RAID Migration cannot be set to the specified volume',
    'E0335': 'RAID Migration cannot be set to the specified '
             'Flexible Tier Pool',
    'E0336': 'Migration failed because of insufficient free space of '
             'the destination pool',
    'E0337': 'The specified Flexible Tier Pool does not have a '
             'Flexible Tier Sub Pool',
    'E0342': 'The time out occurred',
    'E0343': 'The network is not normal',
    'E0344': 'The time out occurred in the network',
    'E0345': 'The network of IDM server is unreachable',
    'E0346': 'The IDM server is unreachable',
    'E0347': 'The IDM server refused the connection',
    'E0348': 'The IDM server reset the connection',
    'E0349': 'The SSL communication fault occurred',
    'E0350': 'The name resolution of the host name failed',
    'E0351': 'It failed in the HTTP authentication',
    'E0352': 'The HTTP authentic method does not correspond',
    'E0353': 'It failed in the SOCKS authentication',
    'E0354': 'The SOCKS authentic method does not correspond',
    'E0355': 'Export log in process',
    'E0356': 'AIS Connect or AIS Connect server authentication is enabled',
    'E0357': 'AIS Connect is disabled',
    'E0358': 'REMCS is enabled',
    'E0359': 'Log Transmission of E-Mail notification is enabled',
    'E0360': 'AIS SSL certificate is not registered',
    'E0361': 'AIS SSL certificate is invalid',
    'E0362': 'Log transmission of E-Mail notification and AIS connect '
             'cannot be enabled simultaneously',
    'E0390': 'Backup REC path information does not exist',
    'E0391': 'Round trip time measurement has failed',
    'E0392': 'Unsupported path type',
    'E0393': 'Syntax error in REC path information. (iSCSI parameter(s) '
             'do not match actual)',
    'E0394': 'Failed to access the server',
    'E0395': 'The object cannot be operated',
    'E0396': 'A part of SpinUp/Down failed',
    'E0397': 'All SpinUp/Down failed',
    'E0399': 'Syntax error in REC path information',
    'E5000': 'Parameter not supported',
    'E5001': 'User authority to use the parameter is improper',
    'E5002': 'Authority of security is necessary for data decryption',
    'E5003': 'The user authority to use the command is improper',
    'E5010': 'The volume encryption is specified for SED disk',
    'E5081': 'Abnormal pinned CBE error',
    'E5084': 'System not ready',
    'E5100': 'Thin Provisioning mode is invalid',
    'E5033': 'Cannot Warm Boot CFL',
    'E5034': 'Cannot Hard Boot CFL',
    'E5101': 'Check thin-pro-pool Status',
    'E5102': 'Migration session count is limit',
    'E5104': 'Thin Provisioning Pool capacity is limit',
    'E5105': 'Existing unused disks are not enough',
    'E5106': 'RAID or Volume is insufficient',
    'E5107': 'RAID type is temporary',
    'E5108': 'Volume type is not Thin Provisioning Volume',
    'E5109': 'RAID group belong to thin-provisioning-pool/flexible-tier-pool',
    'E5110': 'Thin Provisioning Volume count is limit',
    'E5200': 'No copy license',
    'E5201': 'Invalid copy phase',
    'E5202': 'Exist SDV / SDPV',
    'E5203': 'Exist REC disk buffer',
    'E5204': 'Exist REC buffer',
    'E5205': 'Exist REC path setting',
    'E5206': 'Exist any of copy session(s)',
    'E5207': 'Exist volume(s) of protection from copy destination',
    'E5208': 'Copy license information updating due to trial license expired',
    'E5209': 'Not support E6K to target of REC',
    'E5210': 'Data in disk buffer',
    'E5211': 'The RAID group is for REC disk buffer',
    'E5212': 'Source and destination RA type is not match',
    'E5213': 'The times registering trial license has been reached '
             'the system limit',
    'E5214': 'Exist RA',
    'E5215': 'Result string is too long',
    'E5216': 'Compete for the affinity path',
    'E5217': 'The specified multiplicity or priority level mismatch connect '
             'mode (Direct/Switched) of the REC path',
    'E5300': 'An error occurred in the copy path connection',
    'E5301': 'An unsupported command was issued by the remote storage',
    'E5302': 'The specified volume number is not correct (exceeding '
             'the maximum volume number)',
    'E5303': 'The specified volume is not supported',
    'E5304': 'Advanced copy cannot be set to the specified volume',
    'E5305': 'There is "Bad Sector" in the copy source volume',
    'E5306': 'Encryption settings of copy source volume and copy '
             'destination volume are different',
    'E5307': 'The copy source volume and copy destination volume don\'t '
             'belong to the same resource domain',
    'E5308': 'The specified volume is a "Temporary"',
    'E5309': 'Disk failure occurred while the relevant copy session is in '
             '"Suspend" state. The copy session turns into "Error" state',
    'E5310': 'Parameter error occurred',
    'E5311': 'Source volume whose capacity is larger than destination '
             'volume\'s cannot be specified',
    'E5312': 'It failed to reverse the copy session',
    'E5313': 'Copy range conflicts with the existing RAID migration session',
    'E5314': 'The specified copy range of the copy source volume is '
             'overlap with the copy range in an existing session '
             '(excluding cascade and restore)',
    'E5315': 'The specified copy range of the copy destination volume is '
             'overlap with the copy range in an existing session '
             '(excluding cascade and restore copy)',
    'E5316': 'The specified cascade copy cannot be done',
    'E5317': 'The copy session which is in progress of restoring was '
             'specified',
    'E5318': 'The number of cascades exceeds the maximum',
    'E5319': 'An "Error Suspend" session was specified',
    'E5320': 'Multiple copy sessions in REC Consistency mode cannot operate '
             'in a single storage',
    'E5321': 'The state of the specified session is not correct',
    'E5322': 'A command was issued while processing '
             'CONCURRENT SUSPEND command',
    'E5323': 'The specified operation is not a "Force specify"',
    'E5324': 'There is no path to access to the copy source volume or '
             'copy destination volume',
    'E5325': 'The specified volume is an Advanced Copy read-only volume. '
             'It cannot be set as copy destination volume',
    'E5326': 'The STOP command was issued to a SnapOPC/SnapOPC+ session '
             'which is in progress of restoring',
    'E5327': 'REC buffer transfer is not complete in time or '
             'buffer recovery is processing under SUSPEND command process. '
             'SUSPEND command cannot be done',
    'E5328': 'REC buffer data transfer is under monitoring. The specified '
             'session cannot be reversed',
    'E5329': 'It will lead to EC/REC cascade copy session that is not in '
             '"Suspend" state but has cascade source volume',
    'E5330': 'The copy session has already been reversed',
    'E5331': 'The number of copy sessions exceeds the allowable maximum '
             'copy sessions for this storage',
    'E5332': 'The copy license is not valid',
    'E5333': 'The number of copy sessions exceeds the allowable maximum '
             'copy sessions for each copy source volume',
    'E5334': 'The number of copy sessions exceeds the allowable maximum '
             'copy sessions for each copy destination volume',
    'E5335': 'The number of SnapOPC+ copy session generations exceeds '
             'the maximum for a copy source volume',
    'E5336': 'Copy area of copy source volumes in monitoring copy sessions is '
             'overlap',
    'E5337': 'The new copy session settings are the same with an existing '
             'one\'s. The new copy session cannot be started',
    'E5338': 'Copy destination volume and cascade copy destination volume '
             'in the copy session is overlap',
    'E5339': 'It will lead to copy destination volumes overlap. EC/REC '
             'cascade copy session cannot be reversed',
    'E5340': 'SDV is being initialized',
    'E5341': 'There is already a copy session where the specified SDV '
             'was set as copy destination',
    'E5342': 'The copy session has already been set',
    'E5343': 'The copy session has already been deleted',
    'E5344': 'The copy session is in progress of transition to "Suspend" '
             'state asynchronously or has already been in "Suspend" state',
    'E5345': 'The state of the session is already Active',
    'E5346': 'The copy table has not been set yet',
    'E5347': 'Copy table size is not sufficient',
    'E5348': 'REC buffer is not in "Active" state',
    'E5349': 'Copy source and copy destination, usage (sending or receiving) '
             'of REC buffer settings after resuming copy sessions don\'t '
             'match the original settings',
    'E5350': 'REC buffer setting is being changed or REC buffer related '
             'functions are in progress',
    'E5351': 'Copy source and copy destination, usage (sending or receiving) '
             'of REC buffer settings after reversing copy sessions don\'t '
             'match the original settings',
    'E5352': 'The disk configured the RAID group of the specified volume is '
             'in motor OFF state due to ECO-mode',
    'E5353': 'The specified BoxID cannot be found',
    'E5354': 'The copy path is not in "Normal" state. Copy sessions in '
             'this storage were deleted but copy sessions in the remote '
             'storage still exist',
    'E5355': 'Firmware update is in progress. The specified operation '
             'cannot be done',
    'E5356': 'Advanced copy resolution settings of the local storage and '
             'remote storage are different',
    'E5357': 'SDV was specified as a copy destination volume where '
             'the copy session is not SnapOPC+',
    'E5358': 'SDV was specified as a copy source volume in SnapOPC+',
    'E5359': 'A standard volume was specified as copy destination volume '
             'in SnapOPC+',
    'E5360': 'An error, which can be recovered by retry, occurred',
    'E5361': 'The storage is in "Not Ready" or internal error state',
    'E5362': 'The specified volume is currently configured with '
             'Bind-in-Cache extent. RAID Migration cannot apply '
             'to this volume',
    'E5363': 'The previous generation session is Readying',
    'E5364': 'The restore OPC cannot start by using concurrent OPC',
    'E5365': 'The restore OPC of readying session cannot start',
    'E5366': 'The specified copy range is overlap with the copy range in '
             'an existing xcopy session',
    'E5367': 'The specified copy range is overlap with the copy range in '
             'an existing Readying or Copying OPC session',
    'E5368': 'The specified session cannot restart because it is '
             'under restore',
    'E5369': 'The specified remote Box ID is not support the out of band copy',
    'E5370': 'In the remote old model storage, the specified volume '
             'is invalid',
    'E5371': 'In the remote old model storage, parameter error occurred',
    'E5372': 'In the remote old model storage, the specified copy range '
             'is overlap with the copy range in an existing session',
    'E5373': 'In the remote old model storage, status of session or status of '
             'volume is error',
    'E5374': 'In the remote old model storage, the number of copy sessions '
             'exceeds the allowable maximum copy sessions',
    'E5375': 'In the remote old model storage, the new copy session overlap '
             'with the existing one\'s. The new copy session cannot '
             'be started',
    'E5376': 'In the remote old model storage, error occurred about setting '
             'of the copy table or status of REC Buffer',
    'E5377': 'In the remote old model storage, the specified copy volume is '
             'a "SDV"',
    'E5378': 'In the remote old model storage, an error occurred in the copy '
             'path connection',
    'E5379': 'An unsupported command was issued by the remote old '
             'model storage',
    'E5380': 'In the remote old model storage, copy session has been '
             'already set',
    'E5381': 'In the remote old model storage, copy session has been '
             'already deleted',
    'E5382': 'In the remote old model storage, copy session is already '
             'in "Suspend" status or changing to be "Suspend" status',
    'E5383': 'In the remote old model storage, copy session status is '
             'already in "Active" status',
    'E5384': 'In the remote old model storage, no copy license',
    'E5385': 'In the remote old model storage configuration, '
             'the specified BoxID cannot be found',
    'E5386': 'The copy path is not in "Normal" state. Copy sessions in '
             'this storage were deleted but copy sessions in the remote '
             'old model storage still exist',
    'E5387': 'In the remote old model storage, firmware update is in '
             'progress. The specified operation cannot be done',
    'E5388': 'Copy resolution settings of the local storage and remote '
             'old model storage are different',
    'E5389': 'In the remote old model storage, an error, which can be '
             'recovered by retry, occurred',
    'E5390': 'The remote old model storage is in "Not Ready" or '
             'internal error state',
    'E5391': 'There is not the certification of consistency',
    'E5392': 'Multiple copy source storage exists',
    'E5393': 'The certification of consistency is unknown',
    'E5394': 'The copy source storage is not support this command',
    'E5395': 'Controller Module failed',
    'E5396': 'The remote storage is not support this function',
    'E5400': 'The same command that was issued by specifying by '
             'start has already been processed',
    'E5401': 'The same command that was issued by specifying by '
             'restart has already been processed',
    'E5402': 'REC transfer mode which specified by Start or '
             'Resume command is invalid at all RA ports which configure path',
    'E5501': 'iSNS server cannot be connected from the specified '
             'iSCSI CA port',
    'E5502': 'CLI cannot change the host or port parameter '
             'setting created by GUI',
    'E5503': 'The Multiple VLAN setting of a specified port is invalid',
    'E5504': 'The specified Additional IP Information setting is invalid',
    'E5601': 'The automatic setup of IPv6 address cannot be performed',
    'E5701': 'The factory setup is not done',
    'E5900': 'Command error',
    'E6000': 'Advanced Copy session that covers the entire volume is active',
    'E6001': 'The specified volume is ODX Buffer Volume',
    'E6002': 'The specified volume is volume during Zero Reclamation '
             'execution',
    'E6003': 'Offloaded Data Transfer Mode is valid',
    'E6004': 'Offloaded Data Transfer Mode is not valid',
    'E6005': 'ODX Buffer Volume exist',
    'E6006': 'The specified volume is not ODX Buffer Volume',
    'E6007': 'Offloaded Data Transfer in process',
    'E6008': 'The specified volume is not volume during Zero Reclamation '
             'execution',
    'E6009': 'Not available under operating Bind-in-Cache',
    'E6010': 'Current cache page size is over specified cache limit size',
    'E6011': 'Not available under cache limit settings',
    'E6012': 'The RAID migration from which a security level differs requires '
             'security authority',
    'E6201': 'The specified RAID group does not consist of SED',
    'E7001': 'SED authentication key is not registered',
    'E7002': 'The master server is not registered in the key management group',
    'E7003': 'Rejected by the server. Please try again to be '
             'accepted on the server',
    'E7004': 'The key which can be changed is not in the server',
    'E7005': 'Abnormal state of the key',
    'E7006': 'The key is not acquired',
    'E7007': 'The key management group is not registered',
    'E7100': 'The specified Flexible Tier Pool has Flexible Tier Volume(s) '
             'which is balancing',
    'E7101': 'There is no free OLU or SLU to create destination LUN',
    'E7102': 'It is in the process of deleting source Thin Provisioning '
             'Volume internally which is done after migration',
    'E7103': 'Number of migration sessions has reached the system limit',
    'E7104': 'The source LUN has already using for migrated',
    'E7105': 'The source LUN has already been used at other session',
    'E7106': 'The resource in the internal is depleted',
    'E7107': 'State of source volume or destination volume is error',
    'E7108': 'The specified volume doesn\'t have migration session '
             'during startup',
    'E7109': 'The specified volume is currently configured with '
             'Bind-in-Cache extent',
    'E7110': 'Logical capacity which can be migrate is over',
    'E7111': 'Physical capacity of destination pool is error',
    'E7112': 'There is not enough free space to create the pool in the device',
    'E7113': 'Balancing cannot be executed because there is not '
             'enough free space in the pool',
    'E7114': 'Balancing cannot be executed because the device is in '
             'error state',
    'E8000': 'Undefined command',
    'E8001': 'Undefined parameter',
    'E8002': 'Another user is performing an operation',
    'E8003': 'The lock session ID cannot be obtained',
    'E8004': 'The value cannot be specified under current user authority',
    'E8005': 'The specified user account does not exist',
    'E8006': 'Because there will be no user account that can configure '
             'user account or role, the specified operation cannot be done',
    'E8007': 'Your password has expired. You must change your password and '
             'log in again',
    'E8008': 'Password policy and Lockout policy cannot be enforced on '
             'a user account with the Software role',
    'E8100': 'The syntax is incorrect',
    'E8101': 'An unusable character is specified',
    'E8102': 'The parameter is out of the allowed range',
    'E8103': 'An unnecessary parameter is specified',
    'E8104': 'The required parameter is not specified',
    'E8105': 'The number of specified values is too many',
    'E8106': 'The number of specified values is not enough',
    'E8107': 'The number of specified characters is too many',
    'E8108': 'The number of specified characters is not enough',
    'E8109': 'The combination of the parameters or values is incorrect',
    'E810A': 'A value that is not a multiple of 100GB is specified for '
             'the Extreme Cache capacity',
    'E810B': 'The specified value does not match the current setting value',
    'E810C': 'The specified value is not supported by the device model',
    'E810D': 'No values are specified',
    'E810E': 'The format of the value is incorrect',
    'E810F': 'The password is incorrect',
    'E8110': 'The file is incorrect',
    'E8111': 'The update interval needs to be a multiple of 30 seconds',
    'E8800': 'Unable to resolve destination address',
    'E8801': 'The route addition failed. Check the network address of '
             'the destination and the source port',
    'E8802': 'Cannot connect to the server',
    'E8803': 'Login incorrect',
    'E8804': 'The processing status of packet capture is invalid',
    'E8805': 'Detected an error during FTP command establishment. Maybe an '
             'incorrect file path is the cause of the error',
    'E8806': 'Detected an error during FTP command execution. Maybe '
             'the incorrect file name or permission settings are '
             'the cause of the error',
    'E8807': 'Detect FTP Connection Failure',
    'E8808': 'Reading data from the FTP server failed',
    'E8809': 'Writing data to the FTP server failed',
    'E8900': 'IP setting is required for at least one port',
    'E8901': 'The master IP address is not configured',
    'E8902': 'The specified allow IP or allow netmask is 0',
    'E8903': 'Netmask is not configured',
    'E8904': 'The same IP address cannot be specified',
    'E8905': 'Master IP and slave IP addresses must be in '
             'the same network address',
    'E8906': 'The master connect IP is not configured',
    'E8907': 'The slave link local IP is not configured',
    'E8908': 'The specified IPv6 prefix length is out of range',
    'E8909': 'Allow IP address is in the same network address '
             'with the master IP address',
    'E890A': 'Allow IP address is in the same network address '
             'with the master connect IP address',
    'E890B': 'Same network address with other port\'s master IP address',
    'E890C': 'Same network address with other port\'s allow IP address',
    'E890D': 'Same network address with other port\'s connect IP address',
    'E890E': 'Bad subnet mask for IP address',
    'E890F': 'Bad prefix length for IP address',
    'E8910': 'Invalid IP address',
    'E8911': 'The specified IPv6 link local address is incorrect',
    'E8912': 'The specified IPv6 global address is incorrect',
    'E8913': 'The subnet mask setting is incorrect',
    'E8914': 'The primary DNS IP address is not configured',
    'E8915': 'The gateway setting is incorrect',
    'E8916': 'The master link local IP is not configured',
    'E8917': 'Gateway and master IP addresses must be in '
             'the same network address',
    'E8918': 'Master and slave connect IP addresses must be in '
             'the same network address',
    'E8919': 'Gateway and connect IP addresses must be in '
             'the same network address',
    'E891A': 'Same network address with other port\'s DNS IP address',
    'E891B': 'The specified address is broadcast address',
    'E9000': 'The device model does not support the command',
    'E9001': 'The command cannot be executed because the device is in '
             '"Not Ready" status',
    'E9002': 'The storage cluster license is not registered',
    'E9003': 'The storage cluster license is already registered',
    'E9004': 'The copy license and storage cluster license is not registered',
    'E9005': 'The dedup license is not registered',
    'E9006': 'The command cannot be executed because the device is not in '
             '"Normal" status',
    'E9007': 'The GS license is registered',
    'E9008': 'The Advanced Copy license is not registered',
    'E9009': 'The Non-disruptive Storage Migration license is not registered',
    'E900A': 'The Non-disruptive Storage Migration license is '
             'already registered',
    'E9200': 'The Extreme Cache function is not enabled',
    'E9201': 'The Flexible Tier mode is enabled',
    'E9202': 'The Thin Provisioning allocation mode is TPV balancing',
    'E9203': 'Disk Patrol is disabled',
    'E9204': 'The device contains pinned data',
    'E9205': 'The command cannot be executed because the network setting is '
             'the factory default setting',
    'E9206': 'The Extreme Cache function is enabled',
    'E9207': 'The operation mode is not "Maintenance Mode"',
    'E9208': 'SMI-S server is enabled',
    'E9209': 'SMI-S server is disabled',
    'E920A': 'SMI-S server startup or shutdown is in progress',
    'E920B': 'The VVOL function is not enabled',
    'E920C': 'The Extreme Cache Pool function is not enabled',
    'E920D': 'The Extreme Cache function and Extreme Cache Pool function is '
             'not enabled',
    'E920E': 'The encryption mode is disabled',
    'E920F': 'It is necessary to disable the EXC or EXC Pool function before '
             'enable the EXC or EXC Pool function',
    'E9210': 'Collecting performance data is already running',
    'E9211': 'Collecting performance data has been started by Storage Cruiser',
    'E9212': 'The Deduplication/Compression mode is not enabled',
    'E9213': 'The NAS audit log is enabled',
    'E9214': 'The NAS audit log is disabled',
    'E9215': 'The Deduplication/Compression mode is enabled',
    'E9217': 'Collecting performance data is not started',
    'E9218': 'Performance data is being collected',
    'E9219': 'The current default chunk size of the device is different from '
             'one or more existing Flexible Tier Pools',
    'E9220': 'SSL certificate used for SMI-S HTTPS connection can be changed '
             'only when enabling SMI-S function',
    'E9221': 'SSL certificate for Web GUI is not registered',
    'E9222': 'The Veeam B&R storage integration function is not enabled',
    'E9223': 'Thin provisioning is not enabled',
    'E9224': 'One or more specified objects are used for Veeam B&R',
    'E9225': 'One or more specified objects are not used for Veeam B&R',
    'E9300': 'Competing with cold update of firmware in background process',
    'E9301': 'Competing with hot update of firmware in background process',
    'E9302': 'Competing with update of disk firmware in background process',
    'E9303': 'Competing with diagnosing RAID groups',
    'E9304': 'Competing with diagnosing Disks',
    'E9305': 'Competing with quick formatting of volume in background process',
    'E9306': 'Competing with changing Advanced Copy parameters in '
             'background process',
    'E9307': 'Competing with allocating remote copy buffer in '
             'background process',
    'E9308': 'Competing with preparing firmware update in background process',
    'E9309': 'Competing with setting cache control in background process',
    'E930A': 'Competing with reassigning RAID group controller in '
             'background process',
    'E930B': 'Competing with initializing volume in background process',
    'E930C': 'Competing with encrypting or decrypting volume in '
             'background process',
    'E930D': 'Competing with registering RAID group in background process',
    'E930E': 'Competing with deleting RAID group in background process',
    'E930F': 'Competing with registering volume in background process',
    'E9310': 'Competing with deleting volume in background process',
    'E9311': 'Competing with registering global hot spare in '
             'background process',
    'E9312': 'Competing with changing maintenance mode in background process',
    'E9313': 'Competing with expanding RAID group in background process',
    'E9314': 'Competing with collecting G-List information in '
             'background process',
    'E9315': 'Competing with setting Eco-mode in background process',
    'E9316': 'Competing with assigning Eco-mode schedule in '
             'background process',
    'E9317': 'Competing with setting Eco-mode schedule in background process',
    'E9318': 'Competing with setting date and time in background process',
    'E9319': 'Competing with expanding volume in background process',
    'E931A': 'Competing with deleting Advanced Copy session in '
             'background process',
    'E931B': 'Competing with deleting Advanced Copy session in '
             'background process',
    'E931C': 'Competing with storage migration in background process',
    'E931D': 'Competing with storage migration in background process',
    'E931E': 'Competing with deleting snap data volume in background process',
    'E931F': 'Competing with changing Advanced Copy parameters in '
             'background process',
    'E9320': 'Competing with searching target WWNs',
    'E9321': 'Competing with collecting disk performance information',
    'E9322': 'Competing with checking file of storage migration '
             'path information',
    'E9323': 'Competing with checking file of storage migration '
             'path information',
    'E9324': 'Competing with registering Thin Provisioning Pool in '
             'background process',
    'E9325': 'Competing with deleting Thin Provisioning Pool in '
             'background process',
    'E9326': 'Competing with formatting Thin Provisioning Pool in '
             'background process',
    'E9327': 'Competing with registering Thin Provisioning Volume in '
             'background process',
    'E9328': 'Competing with deleting Thin Provisioning Volume in '
             'background process',
    'E9329': 'Competing with formatting Thin Provisioning Volume in '
             'background process',
    'E932A': 'Competing with setting Thin Provisioning Pool parameters in '
             'background process',
    'E932B': 'Competing with setting Thin Provisioning Volume parameters in '
             'background process',
    'E932C': 'Competing with setting Thin Provisioning mode in '
             'background process',
    'E932D': 'Competing with assigning Eco-mode schedule in '
             'background process',
    'E932E': 'Competing with registering REC Disk Buffer Volume in '
             'background process',
    'E932F': 'Competing with deleting REC Disk Buffer Volume in '
             'background process',
    'E9330': 'Competing with inhibiting copy destination volume in '
             'background process',
    'E9331': 'Competing with moving volume in background process',
    'E9332': 'Competing with balancing Thin Provisioning Pool or '
             'Flexible Tier Pool data in background process',
    'E9333': 'Competing with registering dedicated hot spare in '
             'background process',
    'E9334': 'Competing with releasing dedicated hot spare in '
             'background process',
    'E9335': 'Competing with collecting event information in '
             'background process',
    'E9336': 'Competing with controlling advanced copy session',
    'E9337': 'Competing with controlling advanced copy session',
    'E9338': 'Competing with controlling advanced copy session',
    'E9339': 'Competing with controlling advanced copy session',
    'E933A': 'Competing with setting Flexible tier mode in background process',
    'E933B': 'Competing with deleting Flexible Tier Pool in '
             'background process',
    'E933C': 'Competing with formatting Flexible Tier Pool in '
             'background process',
    'E933D': 'Competing with registering Flexible Tier Volume in '
             'background process',
    'E933E': 'Competing with setting Flexible Tier Sub Pool priority in '
             'background process',
    'E933F': 'Competing with setting Flexible Tier Pool parameters in '
             'background process',
    'E9340': 'Flexible Tier Migration in process',
    'E9341': 'Competing with setting cache size limit to volume in '
             'background process',
    'E9342': 'Competing with setting Offloaded Data Transfer Mode in '
             'background process',
    'E9343': 'Competing with setting Key management group ID in '
             'background process',
    'E9344': 'Competing with changing Key in background process',
    'E9345': 'NAS configuration process is in progress',
    'E9346': 'Storage cluster license configuration process is in progress',
    'E9347': 'TFO group configuration process is in progress',
    'E9348': 'TFOV configuration process is in progress',
    'E9349': 'TFO group activate process is in progress',
    'E934A': 'TFO pair configuration process is in progress',
    'E934B': 'VVOL mode setting process is in progress',
    'E934D': 'System cache function setting process is in progress',
    'E934E': 'Starting SSD sanitization process is in progress',
    'E9380': 'The Storage migration is in progress',
    'E9400': 'No memory',
    'E9401': 'No message queue',
    'E9402': 'No semaphore',
    'E9403': 'CLI session limit reached',
    'EA000': 'The CM status is not normal',
    'EA001': 'The specifed CE does not exist',
    'EA002': 'The specified CM does not exist',
    'EA003': 'One or more CMs are not normal',
    'EA004': 'One or more CEs are not normal',
    'EA200': 'The CA port type is incorrect',
    'EA201': 'The specified CA port does not exist',
    'EA202': 'The relevant operation cannot be executed because all of '
             'the CAs are NAS CAs',
    'EA203': 'Host port mode of the CA port is incorrect',
    'EA204': 'The WWPN/WWNN has not been changed',
    'EA205': 'The CA Port status is not normal',
    'EA400': 'The number of maximum disk slots is exceeded',
    'EA401': 'Cannot add Drive Enclosure any more',
    'EA402': 'The Drive Enclosure type does not support',
    'EA600': 'No PFM is installed in the device',
    'EA601': 'A PFM is not installed in some of the CMs in the device',
    'EA602': 'The PFM status is not normal',
    'EA603': 'The number of PFMs is different between the CMs',
    'EA604': 'The specified disk does not exist',
    'EA605': 'The disk type is incorrect',
    'EA606': 'The capacity of the specified disk is insufficient',
    'EA607': 'The specified disk is not available as a member disk',
    'EA608': 'One or more specified disks are installed in '
             'the CE different from the specified assigned CM',
    'EA609': 'SED and non-SED cannot be specified at the same time',
    'EA60A': 'The drive is being used',
    'EA60B': 'The drive status is incorrect',
    'EA60C': 'The specified PFM does not exist',
    'EA60D': 'The specified PFMs are not available as Extreme Cache',
    'EA800': 'The maintenance target is inconsistent status',
    'EA801': 'Not available under current system status conditions',
    'EB000': 'The specified Flexible Tier Sub Pool does not exist',
    'EB001': 'One or more TPP or FTSP exists in the device',
    'EB002': 'The Fast Recovery RAID group cannot be specified',
    'EB003': 'The specified RAID group does not exist',
    'EB004': 'The specified RAID group status is not normal',
    'EB005': 'The specified RAID group are already used',
    'EB006': 'The number of volumes exceeds the maximum number of '
             'registrations in the RAID group',
    'EB007': 'The free capacity of the RAID group is insufficient',
    'EB008': 'One or more VVOLs exist in the specified Flexible Tier Pool',
    'EB009': 'The RAID group used for the Extreme Cache Pool '
             'cannot be specified',
    'EB00A': 'The Extreme Cache Pool already exists for the specified CM',
    'EB00B': 'The Extreme Cache Pool does not exist for the specified CM',
    'EB00C': 'The specified disk is already used',
    'EB00D': 'One or more Deduplication/Compression volumes exist '
             'in the specified pool',
    'EB00E': 'Deduplication and/or Compression is not enabled on '
             'the specified pool',
    'EB00F': 'Extreme Cache Pool exists',
    'EB010': 'Not allowed to configure this RAID Level with the '
             'specified disks',
    'EB011': 'The free capacity of the pool is insufficient',
    'EB012': 'The pool status is not normal',
    'EB013': 'The Flexible Tier Pool status is not normal',
    'EB014': 'A volume for VVOL metadata exists in the specified pool',
    'EB015': 'There are one or more Thin provisioning pools with '
             'Compression enabled',
    'EB016': 'Encryption option cannot be used for Extreme Cache Pool '
             'composed of SED-SSDs',
    'EB017': 'Eco-mode schedule is assigned to the specified pool',
    'EB018': 'Deduplication and/or Compression is enabled on '
             'the specified pool',
    'EB019': 'The specified RAID Group is in use for Thin Provisioning Pool '
             'or Flexible Tier Pool',
    'EB01A': 'The specified RAID Group is in use for REC disk buffer',
    'EB01B': 'The specified RAID Group is in use for Mainframe system '
             '(DVCF mode is on)',
    'EB01C': 'The specified RAID Group is in use for Mainframe system '
             '(Mainframe volume exists)',
    'EB01D': 'The type of volume that configures the specified RAID Group '
             'is inapplicable',
    'EB01E': 'The disk kind of the RAID Groups must be the same',
    'EB01F': 'The RAID level must be the same',
    'EB020': 'The number of member disks must be the same',
    'EB021': 'The stripe depth must be the same',
    'EB022': 'Physical free capacity of the destination pool is insufficient',
    'EB023': 'RAID group expansion is running',
    'EB024': 'The total logical capacity of the pool volumes exceeds '
             'the maximum value',
    'EB025': 'The specified Thin provisioning pool does not exist',
    'EB026': 'The specified Flexible tier pool does not exist',
    'EB027': 'Raid group\'s stripe depth is expanded',
    'EB028': 'Encryption option cannot be used for RAID Group or '
             'Thin Provisioning Pool composed of SED',
    'EB029': 'The specified Thin Provisioning Pool is in use for '
             'Flexible Tier Pool',
    'EB02A': 'The specified RAID group is not in use for Flexible Tier Pool',
    'EB02B': 'The specified Thin Provisioning Pool is not applicable for '
             'Deduplication or Compression',
    'EB02C': 'The specified chunk size exceeds the current default chunk '
             'size of the device',
    'EB02D': 'The specified PFM has already been used as Extreme Cache',
    'EB02E': 'There are no PFMs which can be used as Extreme Cache',
    'EB02F': 'One or more PFMs being currently used as Extreme Cache exist',
    'EB030': 'The specified CE is not using Extreme Cache',
    'EB031': 'There are no PFMs being used as Extreme Cache',
    'EB032': 'There are one or more PFMs which cannot be used as '
             'Extreme Cache',
    'EB033': 'Chunk size cannot be specified under the current '
             'maximum pool capacity',
    'EB034': 'Neither Thin provisioning pool nor Flexible Tier Pool exists',
    'EB300': 'The volume type is incorrect',
    'EB301': 'The volume status is not normal',
    'EB302': 'The type of drive that configures the RLU or the TPP that '
             'the volume belongs to is incorrect',
    'EB303': 'The specified volume does not exist',
    'EB304': 'An incorrect UID is specified',
    'EB305': 'The cache size limit is set',
    'EB306': 'The volume in Fast Recovery RAID group cannot be specified',
    'EB307': 'One or more VVOLs exist in the device',
    'EB308': 'The number of volumes exceeds the maximum number of '
             'registrations',
    'EB309': 'The specified volume is being used as a VVOL',
    'EB30A': 'The specified volume\'s data integrity is T10-DIF',
    'EB30B': 'The specified volume is thick provisioning volume',
    'EB30C': 'One or more Deduplication/Compression volumes exist',
    'EB30D': 'Zero Reclamation is running',
    'EB30E': 'The VVOL cannot be specified with the other resources',
    'EB30F': 'Data migration is running',
    'EB31A': 'Balancing process is running',
    'EB31B': 'The specified volume has no error data',
    'EB31C': 'The specified volume has too many error data',
    'EB31D': 'The volume for VVOL metadata already exists',
    'EB31E': 'The specified volume is being used as a volume for '
             'VVOL metadata',
    'EB31F': 'The Deduplication/Compression System volume status is '
             'not normal',
    'EB320': 'One or more NAS volumes exist',
    'EB321': 'An encryption process is running at the specified volume',
    'EB322': 'Volume formatting is running',
    'EB323': 'New volume size must be equal or greater than the original one',
    'EB324': 'The number of migration sessions exceeds the maximum value',
    'EB325': 'Total migration capacity exceeds the maximum value',
    'EB326': 'The destination RAID Group must be different from the one of '
             'the specified volume',
    'EB327': 'The total capacity of Deduplication/Compression volumes in '
             'the specified pool must be equal or less than ten times '
             'the capacity of the Deduplication/Compression System volume',
    'EB328': 'Since the specified volume is configured by SED, encryption '
             'option is not applicable',
    'EB329': 'The size of the specified volume is not enough',
    'EB32A': 'The specified size exceeds the maximum size under '
             'the current NAS configuration',
    'EB32B': 'The concatenation count of the specified volume exceeds '
             'the maximum value',
    'EB32D': 'The specified volume name is already registered',
    'EB32E': 'The specified volume name is reserved keyword',
    'EB32F': 'The specified volume is already encrypted',
    'EB330': 'The specified volume is already decrypted',
    'EB331': 'The specified Snap Data Pool Volume capacity is not '
             'a multiple of Snap Data Pool Volume Resolution',
    'EB332': 'The specified volume is already registered',
    'EB333': 'The total capacity of the Snap Data Pool Volume '
             'exceeds the maximum value',
    'EB334': 'The resource, which can be used only in '
             'expand volume mode, exists',
    'EB335': 'Advanced Copy session is active',
    'EB336': 'Advanced Copy (ODX) session is active',
    'EB337': 'Volume(s) is used in LUN mapping',
    'EB338': 'Volume(s) is used in Storage Cluster',
    'EB339': 'The Deduplication/Compression volume is being used',
    'EB33A': 'Non-disruptive Storage Migration is in process',
    'EB33B': 'External LU information cannot be deleted or does not '
             'exist for the specified volumes',
    'EB33C': 'Data migration is not running for the specified volume(s)',
    'EB33D': 'The migration status of the specified volume(s) is not normal',
    'EB33E': 'Data synchronization cannot be stopped manually for '
             'the specified volume(s) because it is not running in '
             'manual-stop mode',
    'EB33F': 'No target volumes to stop data synchronization',
    'EB340': 'Compression is not applicable for the specified volume. '
             'For migration to the compression enabled pool, '
             '"-data-reduction-disable yes" needs to be specified',
    'EB341': 'The specified volume is used for Snapshot. TPP or FTRP needs to '
             'be specified for the destination',
    'EB342': 'The specified operation is not applicable because compression '
             'is enabled for the specified Thin provisioning pool or volume',
    'EB343': 'The specified volume is used for Data Container',
    'EB344': 'No target volumes exist',
    'EB345': 'One or more Data Container Volumes are not normal',
    'EB346': 'The specified volume is not enabled for Compression',
    'EB347': 'Migrating within the same pool is not applicable except for '
             'changing compression function of the specified volume',
    'EB348': 'Only Data Container Volume can be specified',
    'EB349': 'One or more target volumes are being used for LUN mapping',
    'EB34A': 'Snapshot Volume for Veeam B&R cannot be created for '
             'the specified volume',
    'EB34B': 'Snapshot cannot be created due to internal resource shortage',
    'EB500': 'Number of iSNS server has reached the iSCSI CA port limit',
    'EB501': 'The specified port belongs to a port group',
    'EB502': 'The LUN group, which is set in specified host affinity and '
             'port, specify volume does not exist',
    'EB503': 'Host Response resource does not exist',
    'EB504': 'Host I/F resource limited',
    'EB505': 'Host affinity mode is inconsistent',
    'EB506': 'The host specified does not exist',
    'EB507': 'There is no host affinity setting including the specified port '
             'and host',
    'EB508': 'The specified port is affinity setting',
    'EB509': 'The specified LUN group has already been used in '
             'the host affinity',
    'EB50A': 'The specified LUN group has already been used in the TFO group',
    'EB50B': 'The specified volume has already been used in the host affinity',
    'EB50C': 'The specified volume has already been used in the TFO group',
    'EB50D': 'The specified volume is already used in other TFO group',
    'EB50E': 'Host I/F already registered',
    'EB50F': 'Host Group resource does not exist',
    'EB510': 'TFO pair does not exist in the volume of all of '
             'the LUN group that has been set affinity in the specified host '
             'and port specified',
    'EB511': 'The specified host is already used in the host affinity that '
             'includes the LUN mask group',
    'EB512': 'The specified host belongs to a host group',
    'EB513': 'The specified LUN mask group has already been used in '
             'the host affinity',
    'EB514': 'The LUN mask group which can be affinity setting does not exist',
    'EB515': 'The source port is already used in the host affinity '
             'that includes the LUN mask group',
    'EB516': 'The destination port is already used in the host affinity that '
             'includes the LUN mask group',
    'EB517': 'Host number or LUN group number, which can be used only in '
             'expand host mode, exists',
    'EB518': 'The number of hosts exceeds the maximum number of hosts which '
             'can be registered if expand host mode is disabled',
    'EB519': 'The iSCSI hosts, which have the same iSCSI name but one of '
             'them has no IP address configuration, cannot be used for '
             'the same CA port in host affinity setting',
    'EB51A': 'The iSCSI hosts, which have the same iSCSI name but one of '
             'them has no IP address configuration, cannot be used for '
             'the same host group',
    'EB51B': 'The specified iSCSI Name cannot be used because it causes a '
             'conflict in host affinity setting at a CA port in which a '
             'host with the same iSCSI Name has already been used',
    'EB51C': 'The specified iSCSI Name cannot be used because it causes a '
             'conflict in host group setting in which a host with the same '
             'iSCSI Name has already been used',
    'EB51D': 'The LUN group cannot be used for Veeam B&R',
    'EB900': 'REC path is not set',
    'EB901': 'REC path is not normal',
    'EB902': 'REC Buffer is mirror recovery status',
    'EB903': 'CFL is canceled because REC session is not continuable state',
    'EB904': 'REC path is set in this device',
    'EB905': 'REC path using iSCSI interface exists',
    'EB906': 'There is CA port whose port mode is CA/RA or RA',
    'EB907': 'The resource, which can be used only in expand volume mode, '
             'exists',
    'EB908': 'There is no REC path information connected to the specified '
             'remote storage',
    'EB909': 'The specified RA path does not exist',
    'EB90A': 'REC Line Speed cannot be changed since the Connection Type of '
             'the REC path connected to the specified remote storage is '
             '"Direct"',
    'EBD00': 'Does not meet a requirement for downgrading',
    'EBD01': 'The specified firmware version is older than the '
             'current firmware version. If firmware downgrade is required, '
             'specify the "-cm-downgrade" option',
    'EBD02': 'The controller firmware is being received from the REMCS center',
    'EBD03': 'The specified generation is not in valid status',
    'EBD04': 'The specified controller firmware is already registered',
    'EBD05': 'The specified generation is already registered on the '
             'Flash memory',
    'EBD06': 'Not available under current system status conditions',
    'EBD07': 'The "hot-auto" application type cannot be executed in '
             'current configuration',
    'EBD08': 'The "hot-manual" application type cannot be executed in '
             'current configuration',
    'EBD09': 'One or more components have failed when applying the firmware',
    'EBD0A': 'An internal process failed',
    'EBD0B': 'The rebooting process has finished, but an error has been '
             'detected in the Master CM',
    'EBD0C': 'The status of the Master CM is not normal. The rebooting '
             'process cannot be executed',
    'EBD0D': 'The hot firmware application failed because the system is '
             'under heavy I/O load',
    'EBD0E': 'The hot firmware application failed because the pinned data '
             'exists',
    'EBD0F': 'The Data migration is in progress',
    'EBD10': 'The hot firmware application cannot be executed under '
             'the current condition of the Advanced Copy function',
    'EBD11': 'There is no redundant path available for accessing '
             'the external storage device(s)',
    'EBD12': 'External storage access path redundancy error',
    'EBD13': 'The specified firmware version is newer than or equal to '
             'the current firmware version',
    'EBD14': 'An error has been detected. The controller firmware '
             'application has failed',
    'EBD15': 'The controller firmware application has finished, '
             'but has failed for one or more components',
    'EBD16': 'The status of the Master CM is not normal. The firmware '
             'application cannot be executed',
    'EBD17': 'An error has been detected. The rebooting process has failed',
    'EBD18': 'The rebooting process has finished, but has failed for '
             'one or more components',
    'EBD19': 'The hot firmware application has been cancelled',
    'EBD1A': 'The rebooting process has finished, but one or '
             'more access paths, by which external LUs are not accessible, '
             'have been detected. There is a possibility that '
             'an error occurs on the access paths or the external LUs',
    'EBD1B': 'An error has been detected. The firmware application for '
             'the PFMs has failed',
    'EBD1C': 'The firmware application for the PFMs has finished, but '
             'has failed for one or more PFMs',
    'EBD1D': 'Switching firmware has failed',
    'EBE00': 'The specified volume is being used as a NAS volume',
    'EBE01': 'This operation is not applicable to the specified object',
    'EBE02': 'The NAS function is not available',
    'EBE03': 'The number of NAS-TPVs exceeds the maximum number of '
             'registrations',
    'EBE04': 'The number of NAS-TPVs (Backup) exceeds the maximum number of '
             'registrations',
    'EBE05': 'Number of NAS System Volume has reached the system limit',
    'EBE06': 'Capacity of NAS System Volume has reached the system limit',
    'EBE07': 'An error was detected in NAS Engine',
    'EBE08': 'NAS system volume does not exist',
    'EBE09': 'NAS system volume is not writable',
    'EBE0A': 'The firmware does not support NAS',
    'EBE0B': 'This operation is not applicable to the Unified Storage',
    'EBE20': 'Specified NAS share does not exist',
    'EBE21': 'The number of NAS share exceeds the maximum number of '
             'registrations',
    'EBE22': 'Specified NAS share name already exists',
    'EBE23': 'Insufficient NAS share resources',
    'EBE24': '[-force] option is only used for the NAS Volume whose '
             'status is "Readying"',
    'EBE25': 'R and RW cannot be set to the same user or group',
    'EBE26': 'Specified host is not registered in the Allow NFS Hosts',
    'EBE27': 'Specified NAS share does not support CIFS service',
    'EBE28': 'Home directory function is already enabled',
    'EBE29': 'The specified NAS share is used for home directory function',
    'EBE30': 'Specified NAS interface does not exist',
    'EBE31': 'The number of NAS interfaces exceeds the maximum '
             'number of registrations',
    'EBE32': 'Another non-VLAN IP address has been registered with this port',
    'EBE33': 'The specified IPv4 address is already registered',
    'EBE34': 'The specified IPv6 link local address is already registered',
    'EBE35': 'The specified IPv6 address is already registered',
    'EBE36': 'No valid IP address exists',
    'EBE37': 'The VLAN ID setting is incorrect',
    'EBE38': 'The IPv4 address is incorrect',
    'EBE39': 'The subnet mask setting is incorrect',
    'EBE3A': 'The gateway address is incorrect',
    'EBE3B': 'The IPv4 host address bits should be non-all-0 and non-all-1',
    'EBE3C': 'The specified IPv6 link local address is incorrect',
    'EBE3D': 'The specified IPv6 global address is incorrect',
    'EBE3E': 'The IPv6 prefix length should be 3-128',
    'EBE3F': 'The IPv6 gateway address should be same subnet or '
             'have other interface ID',
    'EBE40': 'The specified IPv6 address is not a link local address or '
             'a global address',
    'EBE41': 'The specified IP address already exists',
    'EBE42': 'The primary DNS server information is not set',
    'EBE43': 'Specified NAS interface is not assigned to port',
    'EBE44': 'The same VLAN ID has been registered to this port',
    'EBE45': 'The specified NAS interface is used by multi-path',
    'EBE70': 'The specified port is the master port for the bonding',
    'EBE71': 'The specified port is the member port for the bonding',
    'EBE72': 'The specified port is not the master port for the bonding',
    'EBE73': 'The specified port is not the member port for the bonding',
    'EBE74': 'The specified port is on a different CM',
    'EBE75': 'The number of member ports exceeds the maximum number of '
             'registrations',
    'EBE76': 'Cannot delete the bond because the multi-path is enabled',
    'EBE80': 'The specified port belong to the multi-path',
    'EBE81': 'The specified port is not multi-path pair',
    'EBE82': 'The specified port is installed in the same CM',
    'EBE83': 'The IP address of the NAS interface under the multi-path ports '
             'has to have the same network address',
    'EBE90': 'The server settings conflicted',
    'EBE91': 'NAS AD/LDAP server setting is not complete. Some more '
             'parameters need to be specified',
    'EBE92': 'Available NAS interface not exist',
    'EBE93': 'One or more NAS AD/LDAP servers are registered',
    'EBE94': 'The same local group cannot be set to both Primary and '
             'Secondary groups',
    'EBE95': 'The specified local user name or ID is already registered',
    'EBE96': 'The specified local group does not exist',
    'EBE97': 'The specified local user does not exist',
    'EBE98': 'The specified local group name or ID is already registered',
    'EBE99': 'The specified local group is used as Primary group',
    'EBE9A': 'One or more local users or groups are registered',
    'EBE9B': 'The number of local users exceeds the maximum number of '
             'registrations',
    'EBE9C': 'The number of local groups exceeds the maximum number of '
             'registrations',
    'EBE9D': 'BUILTIN group can be used only for Secondary group',
    'EBE9E': 'Specified group name is incorrect',
    'EBE9F': 'LDAP server is not configured',
    'EBEA0': 'The specified route is already registered',
    'EBEA1': 'The specified route is not registered',
    'EBEA2': 'The specified gateway cannot be accessed',
    'EBEA3': 'The host address or the interface ID portion of the IP address '
             'should be zero',
    'EBEA4': 'The destination address is the same as the interface address',
    'EBEA5': 'The gateway address is the same as the interface address',
    'EBEA6': 'The specified destination address is incorrect',
    'EBEB0': 'The number of NAS snapshot volumes exceeds '
             'the maximum number of registrations',
    'EBEB1': 'The specified NAS snapshot configurations not exist',
    'EBEB2': 'The NAS snapshot configurations is set to specified volume',
    'EBEB3': 'The Snap Data Pool Volume which is match '
             'the encryption status of the specified volume, does not exist',
    'EBEB4': 'The NAS snapshot configurations is the manual collecting mode',
    'EBEC0': 'The number of NAS quota settings exceeds the maximum number of '
             'registrations',
    'EBEC1': 'A NAS quota setting already exists',
    'EBEC2': 'Warning value larger than limit value is specified',
    'EBEC3': 'Specified NAS quota setting does not exist',
    'EBEC4': 'Deletion of the quota setting associated with '
             'specified volume failed',
    'EBEC5': 'All of quota setting failed.',
    'EBEC6': 'Deletion of the quota setting associated with '
             'specified NAS share failed',
    'EBEE0': 'The specified NAS share has already been configured for '
             'FTP service',
    'EBEE1': 'The number of NAS share folders for FTP service exceeds '
             'the allowable maximum',
    'EBEE2': 'The specified NAS share has not been configured for FTP service',
    'EBF00': 'The number of registered TFO group has exceeded maximum '
             'in this device',
    'EBF01': 'TFO group is exist',
    'EBF02': 'TFO group does not exist',
    'EBF03': 'The specified TFO group name is already registered',
    'EBF04': 'The specified CA Port is not in the specified TFO group',
    'EBF05': 'The specified TFO group is primary',
    'EBF06': 'The specified port is not TFO port',
    'EBF07': 'The specified port is already TFO pair port configured',
    'EBF08': 'Different types of CA ports cannot be used in TFO group',
    'EBF09': 'The maximum TFO capacity cannot be decreased when '
             'TFO pair exists',
    'EBF0A': 'The specified volume is not in process of TFO pair',
    'EBF0B': 'The TFO group is primary',
    'EBF0C': 'The specified volume is in process of TFO pair',
    'EBF0D': 'There is a volume what is in process of TFO pair',
    'EBF0E': 'The specified volume is configured TFOV',
    'EBF10': 'Change of size was specified volume is TFOV',
    'EBF11': 'The parameter needs storage cluster license',
    'EBF12': 'The destination port belongs to TFO group',
    'EBF13': 'The source port belongs to TFO group',
    'EBF15': 'The specified port has been changed WWPN/WWNN',
    'EBF16': 'TFO group is set to manual failover',
    'EC000': 'VVOL Fault : ActivateProviderFailed',
    'EC001': 'VVOL Fault : InactiveProvider',
    'EC002': 'VVOL Fault : IncompatibleVolume',
    'EC003': 'VVOL Fault : IncorrectSite',
    'EC004': 'VVOL Fault : InvalidArgument',
    'EC005': 'VVOL Fault : InvalidCertificate',
    'EC006': 'VVOL Fault : InvalidLogin',
    'EC007': 'VVOL Fault : InvalidProfile',
    'EC008': 'VVOL Fault : InvalidSession',
    'EC009': 'VVOL Fault : InvalidStatisticsContext',
    'EC00A': 'The specified VVOL copy session does not exist',
    'EC010': 'VVOL Fault : LostAlarm',
    'EC011': 'VVOL Fault : LostEvent',
    'EC012': 'VVOL Fault : NotCancellable',
    'EC013': 'VVOL Fault : NotFound',
    'EC014': 'VVOL Fault : NotImplemented',
    'EC015': 'VVOL Fault : NotSupported',
    'EC016': 'VVOL Fault : OutOfResource',
    'EC017': 'VVOL Fault : PermissionDenied',
    'EC018': 'VVOL Fault : ResourceInUse',
    'EC020': 'VVOL Fault : StorageFault',
    'EC021': 'VVOL Fault : Timeout',
    'EC022': 'VVOL Fault : TooMany',
    'EC100': 'One or more external drives exist',
    'EC101': 'The specified external storage devices do not exist',
    'EC102': 'The number of external drives exceeds the maximum number of '
             'registrations',
    'EC103': 'External LUs do not exist',
    'EC104': 'External drives do not exist',
    'EC105': 'External drives are already used',
    'EC106': 'The status of external drives is not normal',
    'EC107': 'The specified external RAID group does not exist',
    'EC108': 'External RAID groups are already used',
    'EC109': 'The specified external RAID group is not in "Broken" state',
    'EC10A': 'The number of external RAID groups exceeds '
             'the maximum number of registrations',
    'EC10B': 'The status of external RAID groups is not normal',
    'EC10C': 'The specified external RAID group name has already been used',
    'EC10D': 'External LUs are not accessible',
    'ED000': 'Send failed internal command',
    'ED001': 'Receive failed internal command response',
    'ED002': 'Internal command retry timeout',
    'ED003': 'Internal command progress retry timeout',
    'ED180': 'Flexible Tier Migration is running',
    'ED181': 'Quick UNMAP is being performed',
    'ED182': 'The cache LUN size limit is being set',
    'ED183': 'Because EC is being executed, the processing was discontinued',
    'ED184': 'Because OPC is being executed, the processing was discontinued',
    'ED185': 'Because REC is being executed, the processing was discontinued',
    'ED186': 'Offloaded Data Transfer is being performed',
    'ED187': 'The REC disk buffer volume is associated',
    'ED190': 'The internal resources are insufficient',
    'ED191': 'The internal resources are insufficient',
    'ED192': 'The internal resources are insufficient',
    'ED193': 'A non-master-CM component received a command',
    'ED194': 'The internal resources are insufficient',
    'ED195': 'Internal processes are running. Wait for a while and try again',
    'ED196': 'The internal resources are insufficient',
    'ED197': 'Number of the processing request is reached the limit',
    'ED198': 'Process is timeout',
    'ED199': 'The process terminated with an error because pinned '
             'data existed',
    'ED19A': 'The key management server responded with an error',
    'ED19B': 'An error occurred during communication with the key '
             'management server',
    'ED19C': 'The key management server contains no keys that can be changed',
    'ED19F': 'The command process is being canceled',
    'ED1A0': 'Another process is running',
    'ED1A1': 'EC is running',
    'ED1A2': 'OPC is running',
    'ED1A3': 'REC is running',
    'ED1A4': 'ROPC is running',
    'ED1A5': 'CCP is running',
    'ED1A6': 'Quick Format is running',
    'ED1A7': 'Rebuild operation is running',
    'ED1A8': 'There is no redundancy',
    'ED1A9': 'A DE is being rebooted',
    'ED1AA': 'CFL is running',
    'ED1AB': 'CFD is running',
    'ED1AC': 'Operations associated with Log file, Panic Dump or '
             'Event information are being processed',
    'ED1AD': 'The hot spare is in use',
    'ED1AE': 'Upgrade Dirty Recovery is running',
    'ED1AF': 'Degrade Dirty Recovery is running',
    'ED1B0': 'Remote Maintenance is running',
    'ED1B1': 'Command Lock is being processed',
    'ED1B2': 'The configuration is being changed',
    'ED1B3': 'Bind In Cache (Extent) is set',
    'ED1B4': 'Data Migration is running',
    'ED1B5': 'Logical Device Expansion is running',
    'ED1B6': 'Write Through is running',
    'ED1B7': 'An encryption process or a decryption process is running',
    'ED1B8': 'Bind In Cache is set',
    'ED1B9': 'Some of the spinup or spindown operations failed',
    'ED1BA': 'Eco-mode schedule suspension timeout occurred',
    'ED1BB': 'All of the spinup and spindown operations failed',
    'ED1BC': 'There is an encryption volume',
    'ED1BD': 'Operation Mode is not in "Maintenance Mode"',
    'ED1BE': 'A Storage Migration path is set or Storage Migration is running',
    'ED1BF': 'Extended Copy is running',
    'ED1C0': 'An error occurred in the module',
    'ED1C1': 'An error occurred in the CM',
    'ED1C2': 'An error occurred in the CA',
    'ED1C3': 'An error occurred in the BRT',
    'ED1C4': 'An error occurred in the SVC',
    'ED1C5': 'An error occurred in the RSP',
    'ED1C6': 'An error occurred in the FRT',
    'ED1C7': 'An error occurred in the PBC',
    'ED1C8': 'An error occurred in the battery',
    'ED1C9': 'An error occurred in the DE',
    'ED1CA': 'An error occurred in the DE path',
    'ED1CB': 'An error occurred in the user drive',
    'ED1CC': 'An error occurred in the system drive',
    'ED1CD': 'An error occurred in the Flash-ROM',
    'ED1CE': 'An error occurred in the FE Expander',
    'ED1CF': 'An error occurred in the BE Expander',
    'ED1D0': 'An error occurred in the EXP',
    'ED1D1': 'An error occurred in the drive path',
    'ED1D2': 'An error occurred in the drive',
    'ED1D3': 'Unable to retrieve data from NAS Engine. '
             'Please check the status of the NAS Engine',
    'ED1E0': 'Power-on has not been performed yet or power-off is being '
             'performed',
    'ED1E1': 'Zero is specified for the module ID in the transmitter',
    'ED1E2': 'The lock has been acquired',
    'ED1E3': 'Locking has not been performed',
    'ED1E4': 'An unsupported command was specified',
    'ED1E5': 'The parameter length is incorrect',
    'ED1E6': 'The specified parameter is incorrect.',
    'ED1E7': 'The data length is incorrect',
    'ED1E8': 'The specified data is incorrect',
    'ED1E9': 'The execution of the command is requested while this command is '
             'already being performed',
    'ED1EA': 'The target object cannot be operated',
    'ED1EB': 'An internal process failed',
    'ED1EC': 'Because Storage Cluster is being executed, the processing was '
             'discontinued',
    'ED1ED': 'The Flexible Tier Pool shrinking is in process',
    'ED200': 'The user name or password is incorrect',
    'ED201': 'The user name is duplicated',
    'ED202': 'The number of registered users has reached the limit',
    'ED203': 'This user has already registered the User Key. The process was '
             'aborted',
    'ED204': 'The specified role name is not registered',
    'ED205': 'An internal process failed',
    'ED206': 'The login request exceeds the allowable maximum number of '
             'login process',
    'ED207': 'The specified process cannot be performed because a process '
             'that the Virtual Disk Service issued is already running',
    'ED208': 'The specified RAID group is not in "Available" state',
    'ED209': 'An error has occurred in a communication path',
    'ED20A': 'No writable generation exists',
    'ED20B': 'The source volume of migration is being deleted by internal '
             'process after completed migration',
    'ED20C': 'The cache memory size is insufficient for Bind-in-Cache',
    'ED20D': 'No response is received',
    'ED20E': 'iSNS server is not set',
    'ED20F': 'The installation type information for the DE that is '
             'to be added is insufficient',
    'ED210': 'Maintenance mode start or maintenance mode end is being '
             'executed by operation',
    'ED211': 'The license information is being updated because '
             'the trial license expired',
    'ED212': 'The Bitmap is being acquired',
    'ED213': 'The storage is not in "Not Ready" state',
    'ED214': 'The Not Ready factor is not Machine Down Recovery failed',
    'ED215': '(if processing mode is 0x00) CM with the following status '
             'exists among defined CM: Status other than Online - This CM is '
             'not included in the Cyclic composition',
    'ED216': 'The device is a busy state. Please wait for a while',
    'ED217': 'Storage Cruiser is being used. The process was aborted',
    'ED218': 'Command executed from except Storage Cruiser. The process was '
             'aborted',
    'ED219': 'Reading all BUDs failed',
    'ED21A': 'No BUDs are accessible',
    'ED21B': 'Writing all BUDs failed',
    'ED21C': 'All of the BUD capacity is used',
    'ED21D': 'A timeout occurred during firmware registration',
    'ED220': 'The disk where the archive that tries to be registered '
             'can be applied doesn\'t exist in the device',
    'ED221': 'The archive that tries to be registered is unsupported firmware',
    'ED222': 'Reading the history data failed',
    'ED223': 'Reading the composition data failed',
    'ED224': 'Writing the history data failed',
    'ED225': 'Keeping the composition data failed',
    'ED226': 'Keeping the newest composition data failed',
    'ED227': 'The configuration is internally being updated',
    'ED228': 'Reading from a BUD failed',
    'ED229': 'The BUD doesn\'t exist',
    'ED22A': 'The target module does not exist',
    'ED22B': 'The process cannot be performed because another function is '
             'being executed',
    'ED22C': 'The revision that changes the Advanced Copy version cannot be '
             'performed because an EC, an OPC, or a REC is running',
    'ED22D': 'The execution was canceled because an error occurred during '
             'communication with the CM',
    'ED22E': 'The firmware application or EC switch has not executed',
    'ED22F': 'The free capacity of the Flexible Tier Pool is insufficient',
    'ED230': 'The EC switching operation that changes '
             'the Advanced Copy version is attempted while an EC, an OPC, '
             'or a REC is running',
    'ED231': 'Distribution of the control domain failed',
    'ED232': 'The storage is not in "Normal" state',
    'ED233': 'The version is not normal',
    'ED234': 'A remote copy is running',
    'ED235': 'Reclamation of Thin Provisioning Volume is in progress',
    'ED236': 'Not all batteries are in "Full Charge" state',
    'ED237': 'Controller Firmware is not registered',
    'ED238': 'CFL is not executed yet',
    'ED239': 'Because the numbers of connections to the specified device '
             'reached the maximum number, it is not possible to connect it. '
             'Please wait for a while',
    'ED23A': 'The firmware distribution function between devices of '
             'the specified device doesn\'t have interchangeability with '
             'this device',
    'ED23B': 'The firmware types do not match',
    'ED23C': 'The error occurred by the communication with '
             'the specified device',
    'ED23D': 'Powering off is being performed',
    'ED23E': 'CFL is running',
    'ED23F': 'The firmware is being downloaded',
    'ED240': 'Gateway is not set though the specified device is set '
             'outside the subnet',
    'ED241': 'Duplicated IP address between the specified device and '
             'used LAN port',
    'ED242': 'The specified device is in the subnet of unused LAN port',
    'ED243': 'Duplicated IP address between the specified device and '
             'allowed IP of unused LAN port',
    'ED244': 'Group IDs of the specified storage and '
             'the current storage are different',
    'ED245': 'IP address of DNS is not valid',
    'ED246': 'Acceptable IP addresses from other subnet have been specified '
             'but Gateway has not been set',
    'ED247': 'The port specified for used LAN port of a remote support is '
             'not set',
    'ED248': 'Gateway is not set though DNS is set outside of the subnet',
    'ED249': 'Gateway is not set though the PROXY server is set outside of '
             'the subnet',
    'ED24A': 'Gateway is not set though the HTTP server is set outside of '
             'the subnet',
    'ED24B': 'Gateway is not set though the SMTP server is set outside of '
             'the subnet',
    'ED24C': 'Gateway is not set though the POP server is set outside of '
             'the subnet',
    'ED24D': 'Gateway is not set though the NTP server is set outside of '
             'the subnet',
    'ED24E': 'DNS server to resolve server name is not specified',
    'ED24F': 'Please export the log, and contact the person in charge of '
             'maintenance',
    'ED250': 'The name resolution of the PROXY server failed',
    'ED251': 'The name resolution of the HTTP server failed',
    'ED252': 'The name resolution of the SMTP server failed',
    'ED253': 'The name resolution of the POP server failed',
    'ED254': 'The name resolution of the NTP server failed',
    'ED255': 'Even though the command terminated successfully, '
             'the name resolution of the primary DNS failed. The secondary '
             'DNS is used instead',
    'ED256': 'The name resolution succeeded by the IPv6 Primary DNS server',
    'ED257': 'The name resolution succeeded by the IPv6 Secondary DNS server',
    'ED258': 'The name resolution succeeded by the IPv4 Primary DNS server',
    'ED259': 'The name resolution succeeded by the IPv4 Secondary DNS server',
    'ED25A': 'Login to the POP server is impossible because the user name or '
             'password is incorrect',
    'ED25B': 'Error occurred in authentication with AUTH',
    'ED25C': 'Error occurred in communication with SMTP server',
    'ED25D': 'Error occurred in communication with HTTP server',
    'ED25E': 'Error occurred in communication with PROXY server',
    'ED25F': 'Error occurred in communication with POP server',
    'ED260': 'Time out occurred in communication with SMTP server',
    'ED261': 'Time out occurred in communication with HTTP server',
    'ED262': 'Time out occurred in communication with PROXY server',
    'ED263': 'Time out occurred in communication with POP server',
    'ED264': 'Error occurred in sending data to SMTP server',
    'ED265': 'Error occurred in sending data to HTTP server',
    'ED266': 'Error occurred in sending data to PROXY server',
    'ED267': 'Error occurred in sending data to POP server',
    'ED268': 'Error occurred in receiving data from SMTP server',
    'ED269': 'Error occurred in receiving data from HTTP server',
    'ED26A': 'Error occurred in receiving data from PROXY server',
    'ED26B': 'Error occurred in receiving data from POP server',
    'ED26C': 'Duplicated IP address between DNS server and used LAN port',
    'ED26D': 'The IP address for DNS server is in the subnet of unused '
             'LAN port',
    'ED26E': 'Duplicated IP address between DNS server and allowed IP of '
             'unused LAN port',
    'ED26F': 'Duplicated IP address between PROXY server and used LAN port',
    'ED270': 'Duplicated IP address between HTTP server and used LAN port',
    'ED271': 'Duplicated IP address between SMTP server and used LAN port',
    'ED272': 'Duplicated IP address between POP server and used LAN port',
    'ED273': 'Duplicated IP address between NTP server and used LAN port',
    'ED274': 'The IP address for the PROXY server is in the subnet of '
             'unused LAN port',
    'ED275': 'The IP address for the HTTP server is in the subnet of '
             'unused LAN port',
    'ED276': 'The IP address for the SMTP server is in the subnet of '
             'unused LAN port',
    'ED277': 'The IP address for the POP server is in the subnet of '
             'unused LAN port',
    'ED278': 'The IP address for the NTP server is in the subnet of '
             'unused LAN port',
    'ED279': 'Duplicated IP address between PROXY server and '
             'allowed IP of unused LAN port',
    'ED27A': 'The Flexible Tier Pool is in "Broken" state',
    'ED27B': 'The ODX Buffer volume exists.',
    'ED27C': 'The Flexible Tier Pool balancing is in process',
    'ED27D': 'Online Storage Migration is in process',
    'ED27E': 'Freeing up space in the Flexible Tier Pool is in process',
    'ED27F': 'The last RAID group in the Flexible Tier Pool cannot be deleted',
    'ED280': 'The RAID group is being deleted by internal process after '
             'Flexible Tier Pool shrinking',
    'ED281': 'Duplicated IP address between HTTP server and allowed IP of '
             'unused LAN port',
    'ED282': 'Duplicated IP address between SMTP server and allowed IP of '
             'unused LAN port',
    'ED283': 'Duplicated IP address between POP server and allowed IP of '
             'unused LAN port',
    'ED284': 'Duplicated IP address between NTP server and allowed IP of '
             'unused LAN port',
    'ED285': 'The Flexible Tier Pool shrinking is in process',
    'ED286': 'Failed to start SSD sanitization',
    'ED287': 'The Flexible Tier Pool shrinking is in process',
    'ED288': 'The Flexible Tier Pool shrinking is not in process',
    'ED289': 'The password cannot be set. (Minimum password age '
             'policy violation',
    'ED28A': 'The device is not registered',
    'ED28B': 'The password cannot be set. (Password history policy violation',
    'ED28C': 'No BUDs are available',
    'ED28D': 'The password cannot be set. (Minimum password length '
             'policy violation',
    'ED28E': 'The remote support center is busy',
    'ED28F': 'The network information is being set',
    'ED290': 'No controller firmware can be downloaded',
    'ED291': 'The information of the device is being sent again '
             'because outdated information is registered in the remote '
             'support center. Wait approximately ten minutes and try again',
    'ED292': 'An error occurred during HTTP communication',
    'ED293': 'An error occurred during SMTP communication',
    'ED294': 'A communication error occurred',
    'ED295': 'No log files exist',
    'ED296': 'The specified SLU does not exist',
    'ED297': 'Data cannot be obtained because of a cache miss',
    'ED298': 'The cache data cannot be obtained because the specified mirror '
             'cache does not exist',
    'ED299': 'The cache data cannot be obtained because the cache of '
             'the drive that is specified contains dirty data',
    'ED29A': 'Even though the CCHH mode is specified, the relevant volume is '
             'not a Mainframe volume or a MVV volume',
    'ED29B': 'Specified Head Number is invalid',
    'ED29C': 'Specified CCHH or SLBA is out of range',
    'ED29D': 'The LU type of the specified SLU is TPPC, FTV, or TMP FTV',
    'ED29E': 'The storage is in "Machine Down" state',
    'ED29F': 'Status of target RAID group is not Broken',
    'ED2A0': 'The access path to the specified RAID group is not normal',
    'ED2A1': 'There is no access path to the target RAID group',
    'ED2A2': 'The password cannot be set. (Password complexity policy '
             'violation',
    'ED2A3': 'Invalid firmware file',
    'ED2A4': 'The specified Role name has already been used',
    'ED2A5': 'The number of roles has reached the maximum number of '
             'registrations',
    'ED2A6': 'Deletion of a role that is assigned to a user is attempted',
    'ED2A8': 'The specified Snap Data Pool Volume does not exist',
    'ED2A9': 'The Copy Bitmap is insufficient',
    'ED2AA': 'Processing was interrupted because it reached max copy session '
             'count or copy function is not enable',
    'ED2AB': 'The specified volume is in process of copy session or '
             'RAID Migration',
    'ED2AC': 'An invalid LU is specified',
    'ED2AD': 'Because specified session is not the oldest one, '
             'the processing was not performed',
    'ED2AE': 'The specified volume is being initialized',
    'ED2AF': 'The encryption settings of the copy source and the copy '
             'destination are different',
    'ED2B0': 'The drive motor is stopped for either the copy source or '
             'the copy destination due to an Eco-mode schedule',
    'ED2B1': 'The specified destination volume is being used by '
             'another session',
    'ED2B2': 'The Thin Provisioning function is disabled',
    'ED2B3': 'Slave CM: Execution was discontinued for the other '
             'command accepted',
    'ED2B4': 'Slave CM: Error occurred in receiving data from Master CM',
    'ED2B5': 'Master CM: Error occurred in sending data from Slave CM',
    'ED2B6': 'Master CM: Error occurred in receiving data from Slave CM',
    'ED2B7': 'Bind-in-Cache Memory Size has already been set. '
             'Cache Parameters cannot be changed',
    'ED2B8': 'The specified resource number exceeds the maximum value for '
             'the allowed range',
    'ED2B9': 'Incorrect parameter combination',
    'ED2BA': 'The specified license key is incorrect',
    'ED2BB': 'The specified User Public Key file is not correct',
    'ED2BC': 'The specified SSL Server Key file does not match the SSL Server '
             'Certificate file',
    'ED2BD': 'No session is running',
    'ED2BE': 'Access to the BUD is being suppressed',
    'ED2BF': 'The pool capacity that can be created in the device exceeds '
             'the maximum pool capacity',
    'ED2C0': 'The number of unused disks is insufficient',
    'ED2C1': 'RLU/DLU/SLU are insufficient',
    'ED2C2': 'The Flexible Tier function is disabled',
    'ED2C6': 'The SSL/KMIP certificate file is not normal',
    'ED2C7': 'The process has failed. It failed in some CA port(s)',
    'ED2C8': 'The process has failed. It failed in all CA ports',
    'ED2C9': 'The specified TPPE ID does not exist',
    'ED2CA': 'The trial license key is incorrect',
    'ED2CB': 'The trial license key has reached the registration '
             'limit number of times',
    'ED2CC': 'Competing with AIS connect operation in background process',
    'ED2CD': 'Competing with AIS connect send log operation in '
             'background process',
    'ED2CE': 'Volume Type which is the Migration destination is different',
    'ED2CF': 'Another Deduplication/Compression check already in progress',
    'ED2D0': 'Displaying Snap OPC restore size is not supported',
    'ED2D1': 'Recovery process is running. Wait for a while and try again',
    'ED2D2': 'The installed memory is insufficient',
    'ED2D3': 'The VVOL function is not disabled',
    'ED2D4': 'Drives are not installed on the required slots for using the '
             'specified maximum pool capacity',
    'ED2D5': 'The total volume capacity which can be created or expanded by '
             'one operation is up to 2PB',
    'ED2D6': 'There are one or more PFMs which can be downgraded',
    'ED500': 'An error occurred in the Deduplication/Compression Process',
    'ED501': 'Master link local IP conflicted',
    'ED502': 'Slave link local IP conflicted',
    'ED503': 'Global/gateway IP cannot be obtained',
    'ED504': 'Duplication check of link local IP failed',
    'ED505': 'Prefix length is incorrect',
    'ED506': 'The usable capacity of the Deduplication/Compression Map volume '
             'is insufficient temporarily. Please wait for a while and retry',
    'ED507': 'The system is in high-load state. Please wait for a while',
    'ED508': 'The specified external LU has already been registered',
    'ED509': 'The access path of the external storage device is not normal',
    'ED50A': 'The number of drives that is used exceeds the maximum number',
    'ED50B': 'The target mapping table number exceeds the maximum number in '
             'the allowed range',
    'ED50C': 'The target OLU already exists in the same mapping table',
    'ED50D': 'Incorrect parameter combination',
    'ED50E': 'The specified host number exceeds the maximum number in '
             'the allowed range',
    'ED50F': 'The WWN that is to be registered is duplicated',
    'ED510': 'The specified external RAID group cannot be recovered',
    'ED511': 'CA port is overlapping in group',
    'ED512': 'The external LU information is not consistent. Please '
             'refer to ETERNUS CLI User\'s Guide for more details',
    'ED513': 'The specified LCU number exceeds the maximum number in '
             'the allowed range',
    'ED514': 'The specified host response number exceeds the maximum number '
             'in the allowed range',
    'ED515': 'The external storage device responded with an error',
    'ED516': 'An error occurred in accessing the external storage device',
    'ED517': 'A copy session is running',
    'ED518': 'The connected device does not support this function',
    'ED519': 'The forwarding interval cannot be specified when the '
             'ETERNUS6000 is connected',
    'ED51A': 'The buffer size exceeds the maximum size for the device',
    'ED51B': 'REC Buffer has already been configured. The process was aborted',
    'ED51C': 'The storage is in "Not Ready" state. The process was aborted',
    'ED51D': 'The REC disk buffer contains some data',
    'ED51E': 'Some REC Consistency sessions are not in Suspend status',
    'ED51F': 'There is no Pinned Data or Bad Data in the specified volume',
    'ED520': 'The specified volume has too many Pinned Data or '
             'Bad Data for checking',
    'ED523': 'The number of migration sessions has reached '
             'the maximum number for operations in the device',
    'ED524': 'The migration source LUN is being used by '
             'another migration process',
    'ED525': 'The migration source LUN is being used by another copy session',
    'ED526': 'All of the internal resources have already been used',
    'ED527': 'The status of the volume in the migration source or '
             'the migration destination is not normal',
    'ED528': 'Migration session(s) are not running for '
             'the specified volume(s)',
    'ED529': 'Bind-in-Cache is set for the specified OLU',
    'ED52A': 'The migration capacity exceeds the maximum logical '
             'capacity that can be migrated',
    'ED52B': 'There is not enough free space in the specified destination '
             'pool',
    'ED52C': 'The total capacity of pool is not enough in the storage system. '
             'The process was aborted',
    'ED52D': 'There are one or more volumes whose migration status is '
             'not normal',
    'ED52F': 'Enough work capacity for Balancing Thin Provisioning Volume or '
             'Balancing Flexible Tier Pool does not exist. This function '
             'cannot be executed',
    'ED531': 'The necessary LU resources are insufficient',
    'ED53A': 'Communication to other device is failure',
    'ED53B': 'TFO group status is inconsistent',
    'ED53C': 'TFO group phase is inconsistent',
    'ED53D': 'The specified TFO group has no volume',
    'ED53E': 'Capacity of volume differs with in the secondary and primary',
    'ED53F': 'The volume has already been used in the TFO group',
    'ED540': 'Firmware of the other storage does not support '
             'the Storage Cluster',
    'ED541': 'The specified type of TFO group is already registered',
    'ED542': 'Box ID is inconsistent',
    'ED543': 'The TFO group is inconsistent of pair port configuration '
             'between primary and secondary',
    'ED544': 'Volume that cannot be used in TFO pair port exists',
    'ED545': 'Failover mode or Split mode does not match between '
             'the secondary and primary',
    'ED546': 'Copy session exists in the volume',
    'ED548': 'Volume UID differs with in the secondary and primary',
    'ED549': 'Cannot delete the specified TFO group because the specified '
             'port WWN mode is incorrect',
    'ED54A': 'Volume of primary paired with specified volume is not exist',
    'ED54B': 'TFO group activation was specified for incorrect device',
    'ED54C': 'Port of primary paired is not affinity setting',
    'ED54D': 'Storage Cluster data transfer feature is disabled in all RA '
             'ports constituting the copy path',
    'ED54E': 'TFO pair is active',
    'ED54F': 'Incorrect TFO group condition',
    'ED550': 'The volume cannot be set the copy',
    'ED551': 'There is "Bad Sector" in the copy source volume',
    'ED552': 'The number of copy sessions exceeds the allowable maximum '
             'copy sessions for this storage',
    'ED553': 'The number of copy sessions exceeds the allowable maximum '
             'copy sessions for each copy source volume',
    'ED554': 'The number of copy sessions exceeds the allowable maximum '
             'copy sessions for each copy destination volume',
    'ED555': 'Firmware update is in progress. The specified operation '
             'cannot be done',
    'ED556': 'VVOL session is active',
    'ED557': 'The free capacity of the pool is insufficient',
    'ED558': 'Process to free up space in the TPP from a host is running',
    'ED700': 'The free capacity of the NAS volumes is insufficient',
    'ED701': 'The free capacity of the NAS system volumes is insufficient',
    'ED702': 'Filesystem check is required',
    'ED703': 'Full filesystem check is required',
    'ED704': 'The mounting status of the NAS file system is incorrect',
    'ED705': 'Maintenance of the filesystem is required',
    'ED706': 'DNS lookup failure',
    'ED707': 'The VLAN setting for the NAS is incorrect',
    'ED708': 'The NAS bonding setting is incorrect',
    'ED709': 'The network setting for the NAS is incorrect',
    'ED70A': 'An I/O error occurs in the NAS system',
    'ED70B': 'The authentication process via the authentication server failed',
    'ED70C': 'Updating file system version is required',
    'ED70D': 'NAS interface failover is currently active',
    'ED70E': 'Updating file system version is required',
    'ED710': 'An internal error occurs in the NAS system',
    'ED711 ': 'NAS internal error',
    'ED712 ': 'NAS internal error',
    'ED713 ': 'NAS internal error',
    'ED714 ': 'NAS internal error',
    'ED715 ': 'NAS internal error',
    'ED716 ': 'NAS internal error',
    'ED717 ': 'NAS internal error',
    'ED718 ': 'NAS internal error',
    'ED719 ': 'NAS internal error',
    'ED71A ': 'NAS internal error',
    'ED71B ': 'NAS internal error',
    'ED71C ': 'NAS internal error',
    'ED71D ': 'NAS internal error',
    'ED71E ': 'NAS internal error',
    'ED71F ': 'NAS internal error',
    'ED720': 'Filesystem check is already running',
    'ED721': 'Invalid operation',
    'ED722': 'NAS engine is not started',
    'ED723': 'The Volume not mounted',
    'ED724': 'Failed to connect to the other CM',
    'ED725': 'The NAS Snapshot is currently busy',
    'ED726': 'The free capacity of the storage pool is insufficient',
    'ED727': 'Domain join error',
    'ED728': 'Server connection error',
    'ED729': 'Clock skew too great',
    'ED72A': 'Improper user or group',
    'ED72B': 'User or group does not exists',
    'ED72C': 'Improper allow host address',
    'ED72D': 'Authority error',
    'ED72E': 'Filesystem is being accessed',
    'ED72F': 'NAS quota setting failed partially',
    'ED730': 'LDAPS certificate is not registered',
    'ED731': 'LDAPS certificate is invalid',
    'ED732': 'The specified domain name is incorrect',
    'ED733': 'The shared folder is not empty. Before deleting '
             'the share folder, delete all files/folders inside the folder. '
             'Please refer to "clear nas-data"',
    'ED734': 'NAS data deletion process is running',
    'ED735': 'NAS extension system volume does not exist',
    'ED736': 'The snap data volume is being used',
    'ED737': 'Consistency check of NAS extension system volume is in progress',
    'ED738': 'NAS extension system volume is not normal',
    'ED739': 'One or more clients have connected to this shared folder. '
             'Please disconnect it first.',
    'ED73A': 'Improper path',
    'ED73B': 'Path does not exist',
    'ED73C': 'Packet capture is in progress at the specified NAS interface',
    'ED73D': 'Specified user name is incorrect',
    'ED73E': 'FTP connection session exists',
    'ED73F': 'The Access Control List is being initialized',
    'ED740': 'The free file system space is insufficient',
    'ED741': 'The specified file has non-empty data. Overwriting is required',
    'ED742': 'The file inflating process is running',
    'ED743': 'Specified group name is incorrect',
    'ED744': 'Snapshot or NAS cache distribution process is running',
    'ED745': 'The user is already registered',
    'ED746': 'The group is already registered',
    'ED747': 'The provisioned file size is too small to inflate',
    'ED748': 'The user cannot be deleted because it is currently being '
             'used to access to a shared folder',
    'ED749': 'User home directory deletion process is running',
    'ED74A': 'Cannot start to inflate the specified file because it is in use',
    'ED74B': 'Firewall setting for secure connection to change local user '
             'password is configured as "open" for some NAS ports. '
             'Please change the setting of these ports to "close"',
    'ED74C': 'Initializing NAS cache distribution failed. '
             'The storage system might be in high-load temporarily. '
             'Please wait for a while and retry',
    'ED800': 'Stack suspend timeout',
    'ED801': 'Cascade copy session exist',
    'ED802': 'Cascade local copy session exist',
    'ED803': 'Cascade EC/REC session is not suspended',
    'ED805': 'Advanced copy operations for TFOV are not supported',
    'ED806': 'Copy of an illegal combination with TFO pair',
    'ED807': 'Copy of an illegal combination with storage cluster continuous '
             'copy session',
    'ED808': 'Illegal copy session has been specified for the TFO port',
    'ED809': 'Illegal combination with Online Storage Migration',
}
