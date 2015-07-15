# Copyright (c) 2015 Huawei Technologies Co., Ltd.
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

STATUS_HEALTH = '1'
STATUS_RUNNING = '10'
STATUS_VOLUME_READY = '27'
STATUS_LUNCOPY_READY = '40'
STATUS_QOS_ACTIVE = '2'

BLOCK_STORAGE_POOL_TYPE = '1'
FILE_SYSTEM_POOL_TYPE = '2'

HOSTGROUP_PREFIX = 'OpenStack_HostGroup_'
LUNGROUP_PREFIX = 'OpenStack_LunGroup_'
MAPPING_VIEW_PREFIX = 'OpenStack_Mapping_View_'
QOS_NAME_PREFIX = 'OpenStack_'
ARRAY_VERSION = 'V300R003C00'
FC_PORT_CONNECTED = '10'
FC_INIT_ONLINE = '27'
CAPACITY_UNIT = 1024.0 * 1024.0 * 2
DEFAULT_WAIT_TIMEOUT = 3600 * 24 * 30
DEFAULT_WAIT_INTERVAL = 5

MIGRATION_WAIT_INTERVAL = 5
MIGRATION_FAULT = '74'
MIGRATION_COMPLETE = '76'

ERROR_CONNECT_TO_SERVER = -403
ERROR_UNAUTHORIZED_TO_SERVER = -401
SOCKET_TIMEOUT = 52
ERROR_VOLUME_ALREADY_EXIST = 1077948993
LOGIN_SOCKET_TIMEOUT = 4
ERROR_VOLUME_NOT_EXIST = 1077939726
RELOGIN_ERROR_PASS = [ERROR_VOLUME_NOT_EXIST]
HYPERMETRO_RUNNSTATUS_STOP = 41
HYPERMETRO_RUNNSTATUS_NORMAL = 1

THICK_LUNTYPE = 0
THIN_LUNTYPE = 1
MAX_HOSTNAME_LENGTH = 31

OS_TYPE = {'Linux': '0',
           'Windows': '1',
           'Solaris': '2',
           'HP-UX': '3',
           'AIX': '4',
           'XenServer': '5',
           'Mac OS X': '6',
           'VMware ESX': '7'}

CONTROLLER_LIST = ['A', 'B', 'C', 'D']
HUAWEI_VALID_KEYS = ['maxIOPS', 'minIOPS', 'minBandWidth',
                     'maxBandWidth', 'latency', 'IOType']
QOS_KEYS = ['MAXIOPS', 'MINIOPS', 'MINBANDWidth',
            'MAXBANDWidth', 'LATENCY', 'IOTYPE']
MAX_LUN_NUM_IN_QOS = 64
HYPERMETRO_CLASS = "cinder.volume.drivers.huawei.hypermetro.HuaweiHyperMetro"
