# Copyright (C) 2016, Hitachi, Ltd.
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
"""Unit tests for Hitachi VSP Driver."""

import copy
import os

import mock
from os_brick.initiator import connector as brick_connector
from oslo_concurrency import processutils
from oslo_config import cfg
from six.moves import range

from cinder import context as cinder_context
from cinder import db
from cinder.db.sqlalchemy import api as sqlalchemy_api
from cinder import exception
from cinder.objects import snapshot as obj_snap
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume.drivers.hitachi import vsp_fc
from cinder.volume.drivers.hitachi import vsp_horcm
from cinder.volume.drivers.hitachi import vsp_utils
from cinder.volume import utils as volume_utils

# Dummy return values
SUCCEED = 0
STDOUT = ""
STDERR = ""
CMD_SUCCEED = (SUCCEED, STDOUT, STDERR)

# Configuration parameter values
CONFIG_MAP = {
    'serial': '492015',
    'my_ip': '127.0.0.1',
}

# CCI instance numbers
INST_NUMS = (200, 201)

# Shadow Image copy group names
CG_MAP = {'cg%s' % x: vsp_horcm._COPY_GROUP % (
    CONFIG_MAP['my_ip'], CONFIG_MAP['serial'], INST_NUMS[1], x)
    for x in range(3)
}

# Map containing all maps for dummy response creation
DUMMY_RESPONSE_MAP = CONFIG_MAP.copy()
DUMMY_RESPONSE_MAP.update(CG_MAP)

# Dummy response for FC zoning device mapping
DEVICE_MAP = {
    'fabric_name': {
        'initiator_port_wwn_list': ['123456789abcdee', '123456789abcdef'],
        'target_port_wwn_list': ['111111112345678']}}

# cmd: raidcom get copy_grp
GET_COPY_GRP_RESULT = (
    "COPY_GROUP        LDEV_GROUP        MU# JID#  Serial#\n"
    "%(cg0)s           %(cg0)sP            0    -  %(serial)s\n"
    "%(cg1)s           %(cg1)sP            0    -  %(serial)s\n"
    "%(cg1)s           %(cg1)sS            -    -  %(serial)s\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get copy_grp
GET_COPY_GRP_RESULT2 = "COPY_GROUP        LDEV_GROUP        MU# JID# Serial#\n"

# cmd: raidcom get copy_grp
GET_COPY_GRP_RESULT3 = (
    "COPY_GROUP        LDEV_GROUP        MU# JID#  Serial#\n"
    "%(cg0)s           %(cg0)sP            0    -  %(serial)s\n"
    "%(cg0)s           %(cg0)sS            0    -  %(serial)s\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get device_grp -device_grp_name VSP-127.0.0.14920150C91P
GET_DEVICE_GRP_MU1P_RESULT = (
    "LDEV_GROUP      LDEV_NAME        LDEV#    Serial#\n"
    "%(cg1)sP        VSP-LDEV-0-2         0    %(serial)s\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get device_grp -device_grp_name VSP-127.0.0.14920150C91S
GET_DEVICE_GRP_MU1S_RESULT = (
    "LDEV_GROUP      LDEV_NAME        LDEV#    Serial#\n"
    "%(cg1)sS        VSP-LDEV-0-2         2    %(serial)s\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get hba_wwn -port CL1-A HBSD-0123456789abcdef
GET_HBA_WWN_CL1A_HOSTGRP_RESULT = (
    "PORT  GID GROUP_NAME            HWWN             Serial#  NICK_NAME\n"
    "CL1-A   0 HBSD-0123456789abcdef 0123456789abcdef %(serial)s -\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get dp_pool
GET_DP_POOL_RESULT = (
    "PID POLS U(%) AV_CAP(MB) TP_CAP(MB) W(%) H(%) Num LDEV# LCNT "
    "TL_CAP(MB) BM TR_CAP(MB) RCNT\n"
    "030 POLN 0 6006 6006 75 80 1 14860 32 167477 NB 0 0\n"
)

# cmd: raidcom get dp_pool
GET_DP_POOL_ERROR_RESULT = (
    "PID POLS U(%) POOL_NAME Seq#     Num LDEV# H(%) VCAP(%) TYPE PM PT\n"
)

# cmd: raidcom get pool -key opt
GET_POOL_KEYOPT_RESULT = (
    "PID POLS U(%%) POOL_NAME Seq#     Num LDEV# H(%%) VCAP(%%) TYPE PM PT\n"
    "030 POLM 30   VSPPOOL %(serial)s   1 10000  80       -  OPEN N  HDP\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get hba_wwn -port CL1-B-0
GET_HBA_WWN_CL1B0_RESULT = (
    "PORT  GID GROUP_NAME            HWWN             Serial#  NICK_NAME\n"
    "CL1-B   0 HBSD-0123456789abcdef 0123456789abcdef %(serial)s -\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get host_grp -port CL1-A
GET_HOST_GRP_CL1A_RESULT = (
    "PORT   GID  GROUP_NAME               Serial# HMD        HMO_BITs\n"
    "CL1-A    0  HBSD-0123456789abcdef %(serial)s LINUX/IRIX 91\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get host_grp -port CL1-B
GET_HOST_GRP_CL1B_RESULT = (
    "PORT   GID  GROUP_NAME               Serial# HMD        HMO_BITs\n"
    "CL1-B    0  HBSD-0123456789abcdef %(serial)s LINUX/IRIX 91\n"
) % DUMMY_RESPONSE_MAP

# raidcom add host_grp -port CLx-y -host_grp_name HBSD-0123456789abcdef
ADD_HOSTGRP_RESULT = "raidcom: Host group ID 0(0x0) will be used for adding.\n"

# raidcom add host_grp -port CLx-y -host_grp_name HBSD-pair00
ADD_HOSTGRP_PAIR_RESULT = (
    "raidcom: Host group ID 2(0x2) will be used for adding.\n"
)

# raidcom add lun -port CL1-A-0 -ldev_id x
ADD_LUN_LUN0_RESULT = "raidcom: LUN 0(0x0) will be used for adding.\n"

# cmd: raidcom get ldev -ldev_list undefined -cnt 1
GET_LDEV_LDEV_LIST_UNDEFINED = (
    "LDEV : 1 VIR_LDEV : 65534\n"
    "VOL_TYPE : NOT DEFINED\n"
)

# cmd: raidcom get ldev -ldev_id 0 -cnt 2 -key front_end (LDEV)
GET_LDEV_LDEV0_CNT2_FRONTEND_RESULT2 = (
    " Serial# LDEV# SL CL VOL_TYPE VOL_Cap(BLK) PID ATTRIBUTE"
    " Ports PORT_No:LU#:GRPNAME\n"
    " %(serial)s     0  0  0 OPEN-V-CVS      2097152   - CVS       0\n"
    " %(serial)s     1  -  - NOT DEFINED           -   - -         -\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get ldev -ldev_id 0 -cnt 10 -key front_end (LDEV)
GET_LDEV_LDEV0_CNT10_FRONTEND_RESULT = (
    " Serial# LDEV# SL CL VOL_TYPE VOL_Cap(BLK) PID ATTRIBUTE"
    " Ports PORT_No:LU#:GRPNAME\n"
    " %(serial)s     0  0  0 OPEN-V-CVS      2097152   - CVS       0\n"
    " %(serial)s     1  0  0 OPEN-V-CVS      2097152   - CVS       0\n"
    " %(serial)s     2  0  0 OPEN-V-CVS      2097152   - CVS       0\n"
    " %(serial)s     3  0  0 OPEN-V-CVS      2097152   - CVS       0\n"
    " %(serial)s     4  0  0 OPEN-V-CVS      2097152   - CVS       0\n"
    " %(serial)s     5  0  0 OPEN-V-CVS      2097152   - CVS       0\n"
    " %(serial)s     6  0  0 OPEN-V-CVS      2097152   - CVS       0\n"
    " %(serial)s     7  0  0 OPEN-V-CVS      2097152   - CVS       0\n"
    " %(serial)s     8  -  - NOT DEFINED           -   - -         -\n"
    " %(serial)s     9  -  - NOT DEFINED           -   - -         -\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get ldev -ldev_id x -check_status NOT DEFINED
GET_LDEV_CHECKSTATUS_ERR = (
    "raidcom: testing condition has failed with exit(1).\n"
)

# cmd: raidcom get ldev -ldev_id 0
GET_LDEV_LDEV0_RESULT = """
LDEV : 0
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : HDP
VOL_Capacity(BLK) : 2097152
NUM_PORT : 0
STS : NML
"""

# cmd: raidcom get ldev -ldev_id 1
GET_LDEV_LDEV1_RESULT = """
LDEV : 1
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : HDP
VOL_Capacity(BLK) : 268435456
NUM_PORT : 0
STS : NML
"""

# cmd: raidcom get ldev -ldev_id 3
GET_LDEV_LDEV3_RESULT = """
LDEV : 3
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : HDP
VOL_Capacity(BLK) : 2097152
NUM_PORT : 0
STS :
"""

# cmd: raidcom get ldev -ldev_id 4
GET_LDEV_LDEV4_RESULT = """
LDEV : 4
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : QS : HDP : HDT
VOL_Capacity(BLK) : 2097152
NUM_PORT : 0
STS : NML
"""

# cmd: raidcom get ldev -ldev_id 5
GET_LDEV_LDEV5_RESULT = """
LDEV : 5
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : HDP : VVOL
VOL_Capacity(BLK) : 2097152
NUM_PORT : 0
STS : NML
"""

# cmd: raidcom get ldev -ldev_id 6
GET_LDEV_LDEV6_RESULT = """
LDEV : 6
VOL_TYPE : OPEN-V-CVS
PORTs : CL1-A-0 0 HBSD-0123456789abcdef
VOL_ATTR : CVS : HDP
VOL_Capacity(BLK) : 2097152
NUM_PORT : 1
STS : NML
"""

# cmd: raidcom get ldev -ldev_id 7
GET_LDEV_LDEV7_RESULT = """
LDEV : 7
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : QS : HDP : HDT
VOL_Capacity(BLK) : 2097152
NUM_PORT : 0
STS : NML
"""

# cmd: raidcom get ldev -ldev_id 10
GET_LDEV_LDEV10_RESULT = """
LDEV : 10
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : MRCF : HDP : HDT
VOL_Capacity(BLK) : 2097152
NUM_PORT : 1
STS : NML
"""

# cmd: raidcom get ldev -ldev_id 11
GET_LDEV_LDEV11_RESULT = """
LDEV : 11
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : QS : HDP : HDT
VOL_Capacity(BLK) : 2097152
NUM_PORT : 1
STS : NML
"""

# cmd: raidcom get ldev -ldev_id 12
GET_LDEV_LDEV12_RESULT = """
LDEV : 12
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : MRCF : HDP : HDT
VOL_Capacity(BLK) : 2097152
NUM_PORT : 1
STS : NML
"""

# cmd: raidcom get ldev -ldev_id 13
GET_LDEV_LDEV13_RESULT = """
LDEV : 13
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : MRCF : HDP : HDT
VOL_Capacity(BLK) : 2097152
NUM_PORT : 1
STS : BLK
"""

# cmd: raidcom get ldev -ldev_id 14
GET_LDEV_LDEV14_RESULT = """
LDEV : 14
VOL_TYPE : OPEN-V-CVS
VOL_ATTR : CVS : HDP : HDT
VOL_Capacity(BLK) : 9999999
NUM_PORT : 1
STS : NML
"""

# cmd: raidcom get lun -port CL1-A-0
GET_LUN_CL1A0_RESULT = (
    "PORT   GID  HMD            LUN  NUM     LDEV  CM    Serial#  HMO_BITs\n"
    "CL1-A    0  LINUX/IRIX       4    1        4   -     %(serial)s\n"
    "CL1-A    0  LINUX/IRIX     254    1        5   -     %(serial)s\n"
    "CL1-A    0  LINUX/IRIX     255    1        6   -     %(serial)s\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get port
GET_PORT_RESULT = (
    "PORT  TYPE  ATTR SPD LPID FAB CONN SSW SL Serial# WWN      PHY_PORT\n"
    "CL1-A FIBRE TAR  AUT   01 Y  PtoP Y 0 %(serial)s 0123456789abcdef -\n"
    "CL1-B FIBRE TAR  AUT   01 Y  PtoP Y 0 %(serial)s 0123456789abcdef -\n"
    "CL3-A FIBRE TAR  AUT   01 Y  PtoP Y 0 %(serial)s 0123456789abcdef -\n"
    "CL3-B FIBRE TAR  AUT   01 Y  PtoP Y 0 %(serial)s 0123456789abcdef -\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get snapshot -ldev_id 4
GET_SNAPSHOT_LDEV4_RESULT = (
    "SnapShot_name P/S   STAT  Serial# LDEV#  MU# P-LDEV#  PID    %% MODE "
    "SPLT-TIME\n"
    "VSP-SNAP0     P-VOL PSUS   %(serial)s     4  3 8 31 100 ---- 57db5cb0\n"
    "VSP-SNAP0     P-VOL PSUS   %(serial)s     4  4 9 31 100 ---- 57db5cb0\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get snapshot -ldev_id 7
GET_SNAPSHOT_LDEV7_RESULT = (
    "SnapShot_name P/S   STAT  Serial# LDEV#  MU# P-LDEV#  PID    %% MODE "
    "SPLT-TIME\n"
    "VSP-SNAP0     P-VOL PSUS   %(serial)s     7  3 8 31 100 ---- 57db5cb0\n"
    "VSP-SNAP0     P-VOL PSUS   %(serial)s     7  4 9 31 100 ---- 57db5cb0\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get snapshot -ldev_id 8
GET_SNAPSHOT_LDEV8_RESULT = (
    "SnapShot_name P/S   STAT  Serial# LDEV#  MU# P-LDEV#  PID    %% MODE "
    "SPLT-TIME\n"
    "VSP-SNAP0     S-VOL SSUS   %(serial)s     8    3 7 31 100 ---- 57db5cb0\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidcom get snapshot -ldev_id 11
GET_SNAPSHOT_LDEV11_RESULT = (
    "SnapShot_name P/S   STAT  Serial# LDEV#  MU# P-LDEV#  PID    %% MODE "
    "SPLT-TIME\n"
    "VSP-SNAP0     S-VOL SSUS   %(serial)s    11    3 7 31 100 ---- 57db5cb0\n"
) % DUMMY_RESPONSE_MAP

# cmd: pairdisplay -CLI -d 492015 1 0 -IM201
PAIRDISPLAY_LDEV0_1_RESULT = (
    "Group   PairVol       L/R Port#    TID LU-M Seq#       LDEV# "
    "P/S   Status  Seq#       P-LDEV# M\n"
    "%(cg0)s VSP-LDEV-0-1  L   CL1-A-0    0 0  0 %(serial)s     0 "
    "P-VOL PSUS    %(serial)s       1 W\n"
    "%(cg0)s VSP-LDEV-0-1  R   CL1-A-0    0 1  0 %(serial)s     1 "
    "S-VOL SSUS    -                0 -\n"
) % DUMMY_RESPONSE_MAP

# cmd: pairdisplay -CLI -d 492015 10 0 -IM201
PAIRDISPLAY_LDEV7_10_RESULT = (
    "Group   PairVol        L/R Port#    TID LU-M Seq#       LDEV# "
    "P/S   Status  Seq#       P-LDEV# M\n"
    "%(cg0)s VSP-LDEV-7-10  L   CL1-A-1    0 0  0 %(serial)s     7 "
    "P-VOL PSUS    %(serial)s      10 W\n"
    "%(cg0)s VSP-LDEV-7-10  R   CL1-A-1    0 1  0 %(serial)s    10 "
    "S-VOL SSUS    -                7 -\n"
) % DUMMY_RESPONSE_MAP

# cmd: pairdisplay -CLI -d 492015 12 0 -IM201
PAIRDISPLAY_LDEV7_12_RESULT = (
    "Group   PairVol        L/R Port#    TID LU-M Seq#       LDEV# "
    "P/S   Status  Seq#       P-LDEV# M\n"
    "%(cg0)s VSP-LDEV-7-12  L   CL1-A-1    0 0  0 %(serial)s     7 "
    "P-VOL PSUS    %(serial)s      12 W\n"
    "%(cg0)s VSP-LDEV-7-12  R   CL1-A-1    0 1  0 %(serial)s    12 "
    "S-VOL SSUS    -                7 -\n"
) % DUMMY_RESPONSE_MAP

# cmd: raidqry -h
RAIDQRY_RESULT = (
    "Model  : RAID-Manager/Linux/x64\n"
    "Ver&Rev: 01-39-03/03\n"
    "Usage  : raidqry [options] for HORC[200]\n"
    " -h     Help/Usage\n"
    " -I[#]  Set to HORCMINST#\n"
    " -IH[#] or -ITC[#] Set to HORC mode [and HORCMINST#]\n"
    " -IM[#] or -ISI[#] Set to MRCF mode [and HORCMINST#]\n"
    " -z     Set to the interactive mode\n"
    " -zx    Set to the interactive mode and HORCM monitoring\n"
    " -q     Quit(Return to main())\n"
    " -g            Specify for getting all group name on local\n"
    " -l            Specify the local query\n"
    " -lm           Specify the local query with full micro version\n"
    " -r <group>    Specify the remote query\n"
    " -f            Specify display for floatable host\n"
)

EXECUTE_TABLE = {
    ('add', 'hba_wwn', '-port', 'CL3-A-0', '-hba_wwn', '0123456789abcdef'): (
        vsp_horcm.EX_INVARG, STDOUT, STDERR),
    ('add', 'host_grp', '-port', 'CL1-A', '-host_grp_name',
     'HBSD-pair00'): (SUCCEED, ADD_HOSTGRP_PAIR_RESULT, STDERR),
    ('add', 'host_grp', '-port', 'CL1-B', '-host_grp_name',
     'HBSD-pair00'): (SUCCEED, ADD_HOSTGRP_PAIR_RESULT, STDERR),
    ('add', 'host_grp', '-port', 'CL3-A', '-host_grp_name',
     'HBSD-0123456789abcdef'): (SUCCEED, ADD_HOSTGRP_RESULT, STDERR),
    ('add', 'host_grp', '-port', 'CL3-B', '-host_grp_name',
     'HBSD-0123456789abcdef'): (SUCCEED, ADD_HOSTGRP_RESULT, STDERR),
    ('add', 'host_grp', '-port', 'CL3-B', '-host_grp_name',
     'HBSD-pair00'): (SUCCEED, ADD_HOSTGRP_PAIR_RESULT, STDERR),
    ('add', 'lun', '-port', 'CL1-A-0', '-ldev_id', 0): (
        SUCCEED, ADD_LUN_LUN0_RESULT, STDERR),
    ('add', 'lun', '-port', 'CL1-A-0', '-ldev_id', 1): (
        SUCCEED, ADD_LUN_LUN0_RESULT, STDERR),
    ('add', 'lun', '-port', 'CL1-A-0', '-ldev_id', 5): (
        SUCCEED, ADD_LUN_LUN0_RESULT, STDERR),
    ('add', 'lun', '-port', 'CL1-A-0', '-ldev_id', 6): (
        vsp_horcm.EX_CMDRJE, STDOUT, vsp_horcm._LU_PATH_DEFINED),
    ('add', 'lun', '-port', 'CL1-B-0', '-ldev_id', 0, '-lun_id', 0): (
        SUCCEED, ADD_LUN_LUN0_RESULT, STDERR),
    ('extend', 'ldev', '-ldev_id', 3, '-capacity', '128G'): (
        vsp_horcm.EX_CMDIOE, STDOUT,
        "raidcom: [EX_CMDIOE] Control command I/O error"),
    ('get', 'hba_wwn', '-port', 'CL1-A', 'HBSD-0123456789abcdef'): (
        SUCCEED, GET_HBA_WWN_CL1A_HOSTGRP_RESULT, STDERR),
    ('get', 'copy_grp'): (SUCCEED, GET_COPY_GRP_RESULT, STDERR),
    ('get', 'device_grp', '-device_grp_name', CG_MAP['cg1'] + 'P'): (
        SUCCEED, GET_DEVICE_GRP_MU1P_RESULT, STDERR),
    ('get', 'device_grp', '-device_grp_name', CG_MAP['cg1'] + 'S'): (
        SUCCEED, GET_DEVICE_GRP_MU1S_RESULT, STDERR),
    ('get', 'dp_pool'): (SUCCEED, GET_DP_POOL_RESULT, STDERR),
    ('get', 'pool', '-key', 'opt'): (SUCCEED, GET_POOL_KEYOPT_RESULT, STDERR),
    ('get', 'hba_wwn', '-port', 'CL1-B-0'): (
        SUCCEED, GET_HBA_WWN_CL1B0_RESULT, STDERR),
    ('get', 'host_grp', '-port', 'CL1-A'): (
        SUCCEED, GET_HOST_GRP_CL1A_RESULT, STDERR),
    ('get', 'host_grp', '-port', 'CL1-B'): (
        SUCCEED, GET_HOST_GRP_CL1B_RESULT, STDERR),
    ('get', 'ldev', '-ldev_list', 'undefined', '-cnt', '1'): (
        SUCCEED, GET_LDEV_LDEV_LIST_UNDEFINED, STDERR),
    ('get', 'ldev', '-ldev_id', 0, '-cnt', 2, '-key', 'front_end'): (
        SUCCEED, GET_LDEV_LDEV0_CNT2_FRONTEND_RESULT2, STDERR),
    ('get', 'ldev', '-ldev_id', 0, '-cnt', 10, '-key', 'front_end'): (
        SUCCEED, GET_LDEV_LDEV0_CNT10_FRONTEND_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 0, '-check_status', 'NOT', 'DEFINED'): (
        1, STDOUT, GET_LDEV_CHECKSTATUS_ERR),
    ('get', 'ldev', '-ldev_id', 0): (SUCCEED, GET_LDEV_LDEV0_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 1): (SUCCEED, GET_LDEV_LDEV1_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 3): (SUCCEED, GET_LDEV_LDEV3_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 4): (SUCCEED, GET_LDEV_LDEV4_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 5): (SUCCEED, GET_LDEV_LDEV5_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 6): (SUCCEED, GET_LDEV_LDEV6_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 7): (SUCCEED, GET_LDEV_LDEV7_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 10): (SUCCEED, GET_LDEV_LDEV10_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 11): (SUCCEED, GET_LDEV_LDEV11_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 12): (SUCCEED, GET_LDEV_LDEV12_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 13): (SUCCEED, GET_LDEV_LDEV13_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 14): (SUCCEED, GET_LDEV_LDEV14_RESULT, STDERR),
    ('get', 'ldev', '-ldev_id', 15): (vsp_horcm.EX_COMERR, "", STDERR),
    ('get', 'lun', '-port', 'CL1-A-0'): (
        SUCCEED, GET_LUN_CL1A0_RESULT, STDERR),
    ('get', 'port'): (SUCCEED, GET_PORT_RESULT, STDERR),
    ('get', 'snapshot', '-ldev_id', 4): (
        SUCCEED, GET_SNAPSHOT_LDEV4_RESULT, STDERR),
    ('get', 'snapshot', '-ldev_id', 7): (
        SUCCEED, GET_SNAPSHOT_LDEV7_RESULT, STDERR),
    ('get', 'snapshot', '-ldev_id', 8): (
        SUCCEED, GET_SNAPSHOT_LDEV8_RESULT, STDERR),
    ('get', 'snapshot', '-ldev_id', 11): (
        SUCCEED, GET_SNAPSHOT_LDEV11_RESULT, STDERR),
    ('modify', 'ldev', '-ldev_id', 3, '-status', 'discard_zero_page'): (
        vsp_horcm.EX_CMDIOE, STDOUT, STDERR),
    ('pairdisplay', '-CLI', '-d', '%s' % CONFIG_MAP['serial'], 10, 0,
     '-IM%s' % INST_NUMS[1]): (
         SUCCEED, PAIRDISPLAY_LDEV7_10_RESULT, STDERR),
    ('pairdisplay', '-CLI', '-d', '%s' % CONFIG_MAP['serial'], 12, 0,
     '-IM%s' % INST_NUMS[1]): (
         SUCCEED, PAIRDISPLAY_LDEV7_12_RESULT, STDERR),
    ('pairevtwait', '-d', CONFIG_MAP['serial'], 1, '-nowaits',
     '-IM%s' % INST_NUMS[1]): (vsp_horcm.COPY, STDOUT, STDERR),
    ('pairevtwait', '-d', CONFIG_MAP['serial'], 8, '-nowaits',
     '-IM%s' % INST_NUMS[1]): (vsp_horcm.COPY, STDOUT, STDERR),
    ('pairevtwait', '-d', CONFIG_MAP['serial'], 10, '-nowaits',
     '-IM%s' % INST_NUMS[1]): (vsp_horcm.SMPL, STDOUT, STDERR),
    ('pairevtwait', '-d', CONFIG_MAP['serial'], 12, '-nowaits',
     '-IM%s' % INST_NUMS[1]): (vsp_horcm.SMPL, STDOUT, STDERR),
    ('raidqry', '-h'): (SUCCEED, RAIDQRY_RESULT, STDERR),
    ('tee', '/etc/horcm501.conf'): (1, STDOUT, STDERR),
    ('-login', 'user', 'pasword'): (SUCCEED, STDOUT, STDERR),
    ('-login', 'userX', 'paswordX'): (vsp_horcm.EX_ENAUTH, STDOUT, STDERR),
    ('-login', 'userY', 'paswordY'): (vsp_horcm.EX_COMERR, STDOUT, STDERR),
}

EXECUTE_TABLE2 = EXECUTE_TABLE.copy()
EXECUTE_TABLE2.update({
    ('get', 'copy_grp'): (SUCCEED, GET_COPY_GRP_RESULT2, STDERR),
    ('pairevtwait', '-d', CONFIG_MAP['serial'], 1, '-nowaits',
     '-IM%s' % INST_NUMS[1]): (vsp_horcm.PSUS, STDOUT, STDERR),
})

EXECUTE_TABLE3 = EXECUTE_TABLE2.copy()

EXECUTE_TABLE4 = EXECUTE_TABLE.copy()
EXECUTE_TABLE4.update({
    ('get', 'copy_grp'): (SUCCEED, GET_COPY_GRP_RESULT3, STDERR),
    ('pairevtwait', '-d', CONFIG_MAP['serial'], 1, '-nowaits',
     '-IM%s' % INST_NUMS[1]): (vsp_horcm.PSUE, STDOUT, STDERR),
})

EXECUTE_TABLE5 = EXECUTE_TABLE.copy()
EXECUTE_TABLE5.update({
    ('get', 'copy_grp'): (SUCCEED, GET_COPY_GRP_RESULT3, STDERR),
    ('get', 'ldev', '-ldev_id', 1, '-check_status', 'NOT', 'DEFINED'): (
        1, STDOUT, GET_LDEV_CHECKSTATUS_ERR),
    ('pairdisplay', '-CLI', '-d', '%s' % CONFIG_MAP['serial'], 1, 0,
     '-IM%s' % INST_NUMS[1]): (
         SUCCEED, PAIRDISPLAY_LDEV0_1_RESULT, STDERR),
    ('pairevtwait', '-d', CONFIG_MAP['serial'], 1, '-nowaits',
     '-IM%s' % INST_NUMS[1]): (vsp_horcm.SMPL, STDOUT, STDERR),
})

ERROR_EXECUTE_TABLE = {
    ('get', 'dp_pool'): (SUCCEED, GET_DP_POOL_ERROR_RESULT, STDERR),
}

DEFAULT_CONNECTOR = {
    'host': 'host',
    'ip': CONFIG_MAP['my_ip'],
    'wwpns': ['0123456789abcdef'],
    'multipath': False,
}

CTXT = cinder_context.get_admin_context()

TEST_VOLUME = []
for i in range(14):
    volume = {}
    volume['id'] = '00000000-0000-0000-0000-{0:012d}'.format(i)
    volume['name'] = 'test-volume{0:d}'.format(i)
    volume['provider_location'] = None if i == 2 else '{0:d}'.format(i)
    volume['size'] = 256 if i == 1 else 128
    if i == 2:
        volume['status'] = 'creating'
    elif i == 5:
        volume['status'] = 'in-use'
    else:
        volume['status'] = 'available'
    volume = fake_volume.fake_volume_obj(CTXT, **volume)
    TEST_VOLUME.append(volume)


def _volume_get(context, volume_id):
    """Return predefined volume info."""
    return TEST_VOLUME[int(volume_id.replace("-", ""))]

TEST_SNAPSHOT = []
for i in range(8):
    snapshot = {}
    snapshot['id'] = '10000000-0000-0000-0000-{0:012d}'.format(i)
    snapshot['name'] = 'TEST_SNAPSHOT{0:d}'.format(i)
    snapshot['provider_location'] = None if i == 2 else '{0:d}'.format(
        i if i < 5 else i + 5)
    snapshot['status'] = 'creating' if i == 2 else 'available'
    snapshot['volume_id'] = '00000000-0000-0000-0000-{0:012d}'.format(
        i if i < 5 else 7)
    snapshot['volume'] = _volume_get(None, snapshot['volume_id'])
    snapshot['volume_name'] = 'test-volume{0:d}'.format(i if i < 5 else 7)
    snapshot['volume_size'] = 256 if i == 1 else 128
    snapshot = obj_snap.Snapshot._from_db_object(
        CTXT, obj_snap.Snapshot(),
        fake_snapshot.fake_db_snapshot(**snapshot))
    TEST_SNAPSHOT.append(snapshot)

# Flags that determine _fake_run_horcmstart() return values
run_horcmstart_returns_error = False
run_horcmstart_returns_error2 = False
run_horcmstart3_cnt = 0


def _access(*args, **kargs):
    """Assume access to the path is allowed."""
    return True


def _execute(*args, **kargs):
    """Return predefined results for command execution."""
    cmd = args[1:-3] if args[0] == 'raidcom' else args
    result = EXECUTE_TABLE.get(cmd, CMD_SUCCEED)
    return result


def _execute2(*args, **kargs):
    """Return predefined results based on EXECUTE_TABLE2."""
    cmd = args[1:-3] if args[0] == 'raidcom' else args
    result = EXECUTE_TABLE2.get(cmd, CMD_SUCCEED)
    return result


def _execute3(*args, **kargs):
    """Change pairevtwait's dummy return value after it is called."""
    cmd = args[1:-3] if args[0] == 'raidcom' else args
    result = EXECUTE_TABLE3.get(cmd, CMD_SUCCEED)
    if cmd == ('pairevtwait', '-d', CONFIG_MAP['serial'], 1, '-nowaits',
               '-IM%s' % INST_NUMS[1]):
        EXECUTE_TABLE3.update({
            ('pairevtwait', '-d', CONFIG_MAP['serial'], 1, '-nowaits',
             '-IM%s' % INST_NUMS[1]): (vsp_horcm.PSUE, STDOUT, STDERR),
        })
    return result


def _execute4(*args, **kargs):
    """Return predefined results based on EXECUTE_TABLE4."""
    cmd = args[1:-3] if args[0] == 'raidcom' else args
    result = EXECUTE_TABLE4.get(cmd, CMD_SUCCEED)
    return result


def _execute5(*args, **kargs):
    """Return predefined results based on EXECUTE_TABLE5."""
    cmd = args[1:-3] if args[0] == 'raidcom' else args
    result = EXECUTE_TABLE5.get(cmd, CMD_SUCCEED)
    return result


def _cinder_execute(*args, **kargs):
    """Return predefined results or raise an exception."""
    cmd = args[1:-3] if args[0] == 'raidcom' else args
    ret, stdout, stderr = EXECUTE_TABLE.get(cmd, CMD_SUCCEED)
    if ret == SUCCEED:
        return stdout, stderr
    else:
        pee = processutils.ProcessExecutionError(exit_code=ret,
                                                 stdout=stdout,
                                                 stderr=stderr)
        raise pee


def _error_execute(*args, **kargs):
    """Return predefined error results."""
    cmd = args[1:-3] if args[0] == 'raidcom' else args
    result = _execute(*args, **kargs)
    ret = ERROR_EXECUTE_TABLE.get(cmd)
    return ret if ret else result


def _brick_get_connector_properties(multipath=False, enforce_multipath=False):
    """Return a predefined connector object."""
    return DEFAULT_CONNECTOR


def _brick_get_connector_properties_error(multipath=False,
                                          enforce_multipath=False):
    """Return an incomplete connector object."""
    connector = dict(DEFAULT_CONNECTOR)
    del connector['wwpns']
    return connector


def _connect_volume(*args, **kwargs):
    """Return predefined volume info."""
    return {'path': u'/dev/disk/by-path/xxxx', 'type': 'block'}


def _disconnect_volume(*args, **kwargs):
    """Return without doing anything."""
    pass


def _copy_volume(*args, **kwargs):
    """Return without doing anything."""
    pass


def _volume_admin_metadata_get(context, volume_id):
    """Return dummy admin metadata."""
    return {'fake_key': 'fake_value'}


def _snapshot_metadata_update(context, snapshot_id, metadata, delete):
    """Return without doing anything."""
    pass


def _fake_is_smpl(*args):
    """Assume the Shadow Image pair status is SMPL."""
    return True


def _fake_run_horcmgr(*args):
    """Assume CCI is running."""
    return vsp_horcm._HORCM_RUNNING


def _fake_run_horcmstart(*args):
    """Return a value based on a flag value."""
    return 0 if not run_horcmstart_returns_error else 3


def _fake_run_horcmstart2(*args):
    """Return a value based on a flag value."""
    return 0 if not run_horcmstart_returns_error2 else 3


def _fake_run_horcmstart3(*args):
    """Update a counter and return a value based on it."""
    global run_horcmstart3_cnt
    run_horcmstart3_cnt = run_horcmstart3_cnt + 1
    return 0 if run_horcmstart3_cnt <= 1 else 3


def _fake_check_ldev_status(*args, **kwargs):
    """Assume LDEV status has changed as desired."""
    return None


def _fake_exists(path):
    """Assume the path does not exist."""
    return False


class FakeLookupService(object):
    """Dummy FC zoning mapping lookup service class."""

    def get_device_mapping_from_network(self, initiator_wwns, target_wwns):
        """Return predefined FC zoning mapping."""
        return DEVICE_MAP


class VSPHORCMFCDriverTest(test.TestCase):
    """Unit test class for VSP HORCM interface fibre channel module."""

    test_existing_ref = {'source-id': '0'}
    test_existing_none_ldev_ref = {'source-id': '2'}
    test_existing_invalid_ldev_ref = {'source-id': 'AAA'}
    test_existing_value_error_ref = {'source-id': 'XX:XX:XX'}
    test_existing_no_ldev_ref = {}
    test_existing_invalid_sts_ldev = {'source-id': '13'}
    test_existing_invalid_vol_attr = {'source-id': '12'}
    test_existing_invalid_size = {'source-id': '14'}
    test_existing_invalid_port_cnt = {'source-id': '6'}
    test_existing_failed_to_start_horcmgr = {'source-id': '15'}

    def setUp(self):
        """Set up the test environment."""
        super(VSPHORCMFCDriverTest, self).setUp()

        self.configuration = mock.Mock(conf.Configuration)
        self.ctxt = cinder_context.get_admin_context()
        self._setup_config()
        self._setup_driver()

    def _setup_config(self):
        """Set configuration parameter values."""
        self.configuration.config_group = "HORCM"

        self.configuration.volume_backend_name = "HORCMFC"
        self.configuration.volume_driver = (
            "cinder.volume.drivers.hitachi.vsp_fc.VSPFCDriver")
        self.configuration.reserved_percentage = "0"
        self.configuration.use_multipath_for_image_xfer = False
        self.configuration.enforce_multipath_for_image_xfer = False
        self.configuration.num_volume_device_scan_tries = 3
        self.configuration.volume_dd_blocksize = "1000"

        self.configuration.vsp_storage_id = CONFIG_MAP['serial']
        self.configuration.vsp_pool = "30"
        self.configuration.vsp_thin_pool = None
        self.configuration.vsp_ldev_range = "0-1"
        self.configuration.vsp_default_copy_method = 'FULL'
        self.configuration.vsp_copy_speed = 3
        self.configuration.vsp_copy_check_interval = 1
        self.configuration.vsp_async_copy_check_interval = 1
        self.configuration.vsp_target_ports = "CL1-A"
        self.configuration.vsp_compute_target_ports = "CL1-A"
        self.configuration.vsp_horcm_pair_target_ports = "CL1-A"
        self.configuration.vsp_group_request = True

        self.configuration.vsp_zoning_request = False

        self.configuration.vsp_horcm_numbers = INST_NUMS
        self.configuration.vsp_horcm_user = "user"
        self.configuration.vsp_horcm_password = "pasword"
        self.configuration.vsp_horcm_add_conf = False

        self.configuration.safe_get = self._fake_safe_get

        CONF = cfg.CONF
        CONF.my_ip = CONFIG_MAP['my_ip']

    def _fake_safe_get(self, value):
        """Retrieve a configuration value avoiding throwing an exception."""
        try:
            val = getattr(self.configuration, value)
        except AttributeError:
            val = None
        return val

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def _setup_driver(self, execute, brick_get_connector_properties):
        """Set up the driver environment."""
        self.driver = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self.driver.do_setup(None)
        self.driver.check_for_setup_error()
        self.driver.create_export(None, None, None)
        self.driver.ensure_export(None, None)
        self.driver.remove_export(None, None)

    # API test cases
    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(utils, 'execute', side_effect=_cinder_execute)
    def test_do_setup(self, execute, brick_get_connector_properties):
        """Normal case: The host group exists beforehand."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()

        drv.do_setup(None)
        self.assertEqual(
            {'CL1-A': '0123456789abcdef'},
            drv.common.storage_info['wwns'])

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_raidqry_h_invalid(
            self, execute, brick_get_connector_properties):
        """Error case: 'raidqry -h' returns nothing. This error is ignored."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()

        raidqry_h_original = EXECUTE_TABLE[('raidqry', '-h')]
        EXECUTE_TABLE[('raidqry', '-h')] = (SUCCEED, "", STDERR)
        drv.do_setup(None)
        self.assertEqual(
            {'CL1-A': '0123456789abcdef'},
            drv.common.storage_info['wwns'])
        EXECUTE_TABLE[('raidqry', '-h')] = raidqry_h_original

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_specify_pool_name(
            self, execute, brick_get_connector_properties):
        """Normal case: Specify pool name rather than pool number."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_pool = "VSPPOOL"

        drv.do_setup(None)

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_create_hostgrp(
            self, execute, brick_get_connector_properties):
        """Normal case: The host groups does not exist beforehand."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = "CL3-B"

        drv.do_setup(None)

    @mock.patch.object(vsp_horcm, '_EXEC_MAX_WAITTIME', 5)
    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_create_hostgrp_error(
            self, execute, brick_get_connector_properties):
        """Error case: 'add hba_wwn' fails(MSGID0614-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = "CL3-A"

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_thin_pool_not_specified(self, execute):
        """Error case: Parameter error(vsp_thin_pool).(MSGID0601-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_default_copy_method = 'THIN'

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_ldev_range_not_specified(
            self, execute, brick_get_connector_properties):
        """Normal case: Not specify LDEV range."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_ldev_range = None

        drv.do_setup(None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_storage_id_not_specified(self, execute):
        """Error case: Parameter error(vsp_storage_id).(MSGID0601-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_storage_id = None

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_horcm_numbers_invalid(self, execute):
        """Error case: Parameter error(vsp_horcm_numbers).(MSGID0601-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_horcm_numbers = (200, 200)

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_horcm_user_not_specified(self, execute):
        """Error case: Parameter error(vsp_horcm_user).(MSGID0601-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_horcm_user = None

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_only_target_ports_not_specified(
            self, execute, brick_get_connector_properties):
        """Normal case: Only target_ports is not specified."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = None

        drv.do_setup(None)

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_only_compute_target_ports_not_specified(
            self, execute, brick_get_connector_properties):
        """Normal case: Only compute_target_ports is not specified."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_compute_target_ports = None

        drv.do_setup(None)

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_only_pair_target_ports_not_specified(
            self, execute, brick_get_connector_properties):
        """Normal case: Only pair_target_ports is not specified."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_horcm_pair_target_ports = None

        drv.do_setup(None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_compute_target_ports_not_specified(self, execute):
        """Error case: Parameter error(compute_target_ports).(MSGID0601-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = None
        self.configuration.vsp_compute_target_ports = None

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_pair_target_ports_not_specified(self, execute):
        """Error case: Parameter error(pair_target_ports).(MSGID0601-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = None
        self.configuration.vsp_horcm_pair_target_ports = None

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_horcm, '_EXEC_MAX_WAITTIME', 5)
    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(processutils, 'execute', side_effect=_execute)
    @mock.patch.object(os.path, 'exists', side_effect=_fake_exists)
    @mock.patch.object(os, 'access', side_effect=_access)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_failed_to_create_conf(
            self, vsp_utils_execute, access, exists, processutils_execute,
            brick_get_connector_properties):
        """Error case: Writing into horcmxxx.conf fails.(MSGID0632-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_horcm_numbers = (500, 501)
        self.configuration.vsp_horcm_add_conf = True

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_horcm, '_EXEC_RETRY_INTERVAL', 1)
    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_failed_to_login(
            self, execute, brick_get_connector_properties):
        """Error case: 'raidcom -login' fails with EX_ENAUTH(MSGID0600-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_horcm_user = "userX"
        self.configuration.vsp_horcm_password = "paswordX"

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_horcm, '_EXEC_MAX_WAITTIME', 2)
    @mock.patch.object(vsp_horcm, '_EXEC_RETRY_INTERVAL', 1)
    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_failed_to_command(
            self, execute, brick_get_connector_properties):
        """Error case: 'raidcom -login' fails with EX_COMERR(MSGID0600-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_horcm_user = "userY"
        self.configuration.vsp_horcm_password = "paswordY"

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_utils, 'DEFAULT_PROCESS_WAITTIME', 2)
    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        vsp_horcm, '_run_horcmgr', side_effect=_fake_run_horcmgr)
    def test_do_setup_failed_to_horcmshutdown(
            self, _run_horcmgr, execute, brick_get_connector_properties):
        """Error case: CCI's status is always RUNNING(MSGID0608-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        vsp_horcm, '_run_horcmstart', side_effect=_fake_run_horcmstart)
    def test_do_setup_failed_to_horcmstart(
            self, _run_horcmstart, execute, brick_get_connector_properties):
        """Error case: _run_horcmstart() returns an error(MSGID0609-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()

        global run_horcmstart_returns_error
        run_horcmstart_returns_error = True
        self.assertRaises(exception.VSPError, drv.do_setup, None)
        run_horcmstart_returns_error = False

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties_error)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_wwn_not_found(
            self, execute, brick_get_connector_properties):
        """Error case: The connector does not have 'wwpns'(MSGID0650-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_port_not_found(self, execute):
        """Error case: The target port does not exist(MSGID0650-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = ["CL4-A"]

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_compute_target_ports_not_found(self, execute):
        """Error case: Compute target port does not exist(MSGID0650-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = None
        self.configuration.vsp_compute_target_ports = ["CL4-A"]

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_do_setup_pair_target_ports_not_found(self, execute):
        """Error case: Pair target port does not exist(MSGID0650-E)."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = None
        self.configuration.vsp_horcm_pair_target_ports = ["CL5-A"]

        self.assertRaises(exception.VSPError, drv.do_setup, None)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_extend_volume(self, execute):
        """Normal case: Extend volume succeeds."""
        self.driver.extend_volume(TEST_VOLUME[0], 256)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_extend_volume_volume_provider_location_is_none(self, execute):
        """Error case: The volume's provider_location is None(MSGID0613-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.extend_volume, TEST_VOLUME[2], 256)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_extend_volume_volume_ldev_is_vvol(self, execute):
        """Error case: The volume is a V-VOL(MSGID0618-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.extend_volume, TEST_VOLUME[5], 256)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_extend_volume_volume_is_busy(self, execute):
        """Error case: The volume is in a THIN volume pair(MSGID0616-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.extend_volume, TEST_VOLUME[4], 256)

    @mock.patch.object(utils, 'execute', side_effect=_cinder_execute)
    @mock.patch.object(vsp_horcm, '_EXTEND_WAITTIME', 1)
    @mock.patch.object(vsp_horcm, '_EXEC_RETRY_INTERVAL', 1)
    def test_extend_volume_raidcom_error(self, execute,):
        """Error case: 'extend ldev' returns an error(MSGID0600-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.extend_volume, TEST_VOLUME[3], 256)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_get_volume_stats(self, execute):
        """Normal case: Refreshing data required."""
        stats = self.driver.get_volume_stats(True)
        self.assertEqual('Hitachi', stats['vendor_name'])
        self.assertFalse(stats['multiattach'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_get_volume_stats_no_refresh(self, execute):
        """Normal case: Refreshing data not required."""
        stats = self.driver.get_volume_stats()
        self.assertEqual({}, stats)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_error_execute)
    def test_get_volume_stats_failed_to_get_dp_pool(self, execute):
        """Error case: The pool does not exist(MSGID0640-E, MSGID0620-E)."""
        self.driver.common.storage_info['pool_id'] = 29

        stats = self.driver.get_volume_stats(True)
        self.assertEqual({}, stats)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_volume(self, execute):
        """Normal case: Available LDEV range is 0-1."""
        ret = self.driver.create_volume(fake_volume.fake_volume_obj(self.ctxt))
        self.assertEqual('1', ret['provider_location'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_volume_free_ldev_not_found_on_storage(self, execute):
        """Error case: No unused LDEV exists(MSGID0648-E)."""
        self.driver.common.storage_info['ldev_range'] = [0, 0]

        self.assertRaises(
            exception.VSPError, self.driver.create_volume, TEST_VOLUME[0])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_volume_no_setting_ldev_range(self, execute):
        """Normal case: Available LDEV range is unlimited."""
        self.driver.common.storage_info['ldev_range'] = None

        ret = self.driver.create_volume(fake_volume.fake_volume_obj(self.ctxt))
        self.assertEqual('1', ret['provider_location'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        vsp_horcm.VSPHORCM,
        '_check_ldev_status', side_effect=_fake_check_ldev_status)
    def test_delete_volume(self, _check_ldev_status, execute):
        """Normal case: Delete a volume."""
        self.driver.delete_volume(TEST_VOLUME[0])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_delete_volume_provider_location_is_none(self, execute):
        """Error case: The volume's provider_location is None(MSGID0304-W)."""
        self.driver.delete_volume(TEST_VOLUME[2])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_delete_volume_ldev_not_found_on_storage(self, execute):
        """Unusual case: The volume's LDEV does not exist.(MSGID0319-W)."""
        self.driver.delete_volume(TEST_VOLUME[3])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_delete_volume_volume_is_busy(self, execute):
        """Error case: The volume is a P-VOL of a THIN pair(MSGID0616-E)."""
        self.assertRaises(
            exception.VolumeIsBusy, self.driver.delete_volume, TEST_VOLUME[4])

    @mock.patch.object(vsp_horcm, 'PAIR', vsp_horcm.PSUS)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        db, 'snapshot_metadata_update', side_effect=_snapshot_metadata_update)
    @mock.patch.object(sqlalchemy_api, 'volume_get', side_effect=_volume_get)
    def test_create_snapshot_full(
            self, volume_get, snapshot_metadata_update, execute):
        """Normal case: copy_method=FULL."""
        self.driver.common.storage_info['ldev_range'] = [0, 9]

        ret = self.driver.create_snapshot(TEST_SNAPSHOT[7])
        self.assertEqual('8', ret['provider_location'])

    @mock.patch.object(vsp_horcm, 'PAIR', vsp_horcm.PSUS)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        db, 'snapshot_metadata_update', side_effect=_snapshot_metadata_update)
    @mock.patch.object(sqlalchemy_api, 'volume_get', side_effect=_volume_get)
    def test_create_snapshot_thin(
            self, volume_get, snapshot_metadata_update, execute):
        """Normal case: copy_method=THIN."""
        self.driver.common.storage_info['ldev_range'] = [0, 9]
        self.configuration.vsp_thin_pool = 31
        self.configuration.vsp_default_copy_method = "THIN"

        ret = self.driver.create_snapshot(TEST_SNAPSHOT[7])
        self.assertEqual('8', ret['provider_location'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(sqlalchemy_api, 'volume_get', side_effect=_volume_get)
    def test_create_snapshot_provider_location_is_none(
            self, volume_get, execute):
        """Error case: Source vol's provider_location is None(MSGID0624-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.create_snapshot, TEST_SNAPSHOT[2])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(sqlalchemy_api, 'volume_get', side_effect=_volume_get)
    def test_create_snapshot_ldev_not_found_on_storage(
            self, volume_get, execute):
        """Error case: The src-vol's LDEV does not exist.(MSGID0612-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.create_snapshot, TEST_SNAPSHOT[3])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_delete_snapshot_full(self, execute):
        """Normal case: Delete a snapshot."""
        self.driver.delete_snapshot(TEST_SNAPSHOT[5])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        vsp_horcm.VSPHORCM, '_is_smpl', side_effect=_fake_is_smpl)
    def test_delete_snapshot_full_smpl(self, _is_smpl, execute):
        """Normal case: The LDEV in an SI volume pair becomes SMPL."""
        self.driver.delete_snapshot(TEST_SNAPSHOT[7])

    @mock.patch.object(vsp_utils, 'DEFAULT_PROCESS_WAITTIME', 1)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_delete_snapshot_vvol_timeout(self, execute):
        """Error case: V-VOL is not deleted from a snapshot(MSGID0611-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.delete_snapshot, TEST_SNAPSHOT[6])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_delete_snapshot_provider_location_is_none(self, execute):
        """Error case: Snapshot's provider_location is None(MSGID0304-W)."""
        self.driver.delete_snapshot(TEST_SNAPSHOT[2])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_delete_snapshot_ldev_not_found_on_storage(self, execute):
        """Unusual case: The snapshot's LDEV does not exist.(MSGID0319-W)."""
        self.driver.delete_snapshot(TEST_SNAPSHOT[3])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_delete_snapshot_snapshot_is_busy(self, execute):
        """Error case: The snapshot is a P-VOL of a THIN pair(MSGID0616-E)."""
        self.assertRaises(
            exception.SnapshotIsBusy, self.driver.delete_snapshot,
            TEST_SNAPSHOT[4])

    @mock.patch.object(volume_utils, 'copy_volume', side_effect=_copy_volume)
    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(
        utils, 'brick_get_connector',
        side_effect=mock.MagicMock())
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        brick_connector.FibreChannelConnector,
        'connect_volume', _connect_volume)
    @mock.patch.object(
        brick_connector.FibreChannelConnector,
        'disconnect_volume', _disconnect_volume)
    def test_create_cloned_volume_with_dd_same_size(
            self, execute, brick_get_connector, brick_get_connector_properties,
            copy_volume):
        """Normal case: The source volume is a V-VOL and copied by dd."""
        vol = self.driver.create_cloned_volume(TEST_VOLUME[0], TEST_VOLUME[5])
        self.assertEqual('1', vol['provider_location'])

    @mock.patch.object(volume_utils, 'copy_volume', side_effect=_copy_volume)
    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(
        utils, 'brick_get_connector',
        side_effect=mock.MagicMock())
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        brick_connector.FibreChannelConnector,
        'connect_volume', _connect_volume)
    @mock.patch.object(
        brick_connector.FibreChannelConnector,
        'disconnect_volume', _disconnect_volume)
    def test_create_cloned_volume_with_dd_extend_size(
            self, execute, brick_get_connector, brick_get_connector_properties,
            copy_volume):
        """Normal case: Copy with dd and extend the size afterward."""
        vol = self.driver.create_cloned_volume(TEST_VOLUME[1], TEST_VOLUME[5])
        self.assertEqual('1', vol['provider_location'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_cloned_volume_provider_location_is_none(self, execute):
        """Error case: Source vol's provider_location is None(MSGID0624-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.create_cloned_volume,
            TEST_VOLUME[0], TEST_VOLUME[2])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_cloned_volume_invalid_size(self, execute):
        """Error case: src-size > clone-size(MSGID0617-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.create_cloned_volume,
            TEST_VOLUME[0], TEST_VOLUME[1])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_cloned_volume_extend_size_thin(self, execute):
        """Error case: clone > src and copy_method=THIN(MSGID0621-E)."""
        self.configuration.vsp_thin_pool = 31
        test_vol_obj = copy.copy(TEST_VOLUME[1])
        test_vol_obj.metadata.update({'copy_method': 'THIN'})
        self.assertRaises(
            exception.VSPError, self.driver.create_cloned_volume,
            test_vol_obj, TEST_VOLUME[0])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_volume_from_snapshot_same_size(self, execute):
        """Normal case: Copy with Shadow Image."""
        vol = self.driver.create_volume_from_snapshot(
            TEST_VOLUME[0], TEST_SNAPSHOT[0])
        self.assertEqual('1', vol['provider_location'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute2)
    def test_create_volume_from_snapshot_full_extend_normal(self, execute):
        """Normal case: Copy with Shadow Image and extend the size."""
        test_vol_obj = copy.copy(TEST_VOLUME[1])
        test_vol_obj.metadata.update({'copy_method': 'FULL'})
        vol = self.driver.create_volume_from_snapshot(
            test_vol_obj, TEST_SNAPSHOT[0])
        self.assertEqual('1', vol['provider_location'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute3)
    def test_create_volume_from_snapshot_full_extend_PSUE(self, execute):
        """Error case: SI copy -> pair status: PSUS -> PSUE(MSGID0722-E)."""
        test_vol_obj = copy.copy(TEST_VOLUME[1])
        test_vol_obj.metadata.update({'copy_method': 'FULL'})
        self.assertRaises(
            exception.VSPError, self.driver.create_volume_from_snapshot,
            test_vol_obj, TEST_SNAPSHOT[0])

    @mock.patch.object(vsp_utils, 'DEFAULT_PROCESS_WAITTIME', 1)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute4)
    def test_create_volume_from_snapshot_full_PSUE(self, execute):
        """Error case: SI copy -> pair status becomes PSUE(MSGID0610-E)."""
        test_vol_obj = copy.copy(TEST_VOLUME[0])
        test_vol_obj.metadata.update({'copy_method': 'FULL'})
        self.assertRaises(
            exception.VSPError, self.driver.create_volume_from_snapshot,
            test_vol_obj, TEST_SNAPSHOT[0])

    @mock.patch.object(
        vsp_horcm, '_run_horcmstart', side_effect=_fake_run_horcmstart3)
    @mock.patch.object(vsp_horcm, '_LDEV_STATUS_WAITTIME', 1)
    @mock.patch.object(vsp_utils, 'DEFAULT_PROCESS_WAITTIME', 1)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute5)
    def test_create_volume_from_snapshot_full_SMPL(
            self, execute, _run_horcmstart):
        """Error case: SI copy -> pair status becomes SMPL(MSGID0610-E)."""
        test_vol_obj = copy.copy(TEST_VOLUME[0])
        test_vol_obj.metadata.update({'copy_method': 'FULL'})
        self.assertRaises(
            exception.VSPError, self.driver.create_volume_from_snapshot,
            test_vol_obj, TEST_SNAPSHOT[0])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_volume_from_snapshot_invalid_size(self, execute):
        """Error case: volume-size < snapshot-size(MSGID0617-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.create_volume_from_snapshot,
            TEST_VOLUME[0], TEST_SNAPSHOT[1])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_volume_from_snapshot_thin_extend(self, execute):
        """Error case: volume > snapshot and copy_method=THIN(MSGID0621-E)."""
        self.configuration.vsp_thin_pool = 31
        test_vol_obj = copy.copy(TEST_VOLUME[1])
        test_vol_obj.metadata.update({'copy_method': 'THIN'})
        self.assertRaises(
            exception.VSPError, self.driver.create_volume_from_snapshot,
            test_vol_obj, TEST_SNAPSHOT[0])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_create_volume_from_snapshot_provider_location_is_none(
            self, execute):
        """Error case: Snapshot's provider_location is None(MSGID0624-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.create_volume_from_snapshot,
            TEST_VOLUME[0], TEST_SNAPSHOT[2])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        db, 'volume_admin_metadata_get',
        side_effect=_volume_admin_metadata_get)
    def test_initialize_connection(self, volume_admin_metadata_get, execute):
        """Normal case: Initialize connection."""
        self.configuration.vsp_zoning_request = True
        self.driver.common._lookup_service = FakeLookupService()

        ret = self.driver.initialize_connection(
            TEST_VOLUME[0], DEFAULT_CONNECTOR)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        self.assertEqual(['0123456789abcdef'], ret['data']['target_wwn'])
        self.assertEqual(0, ret['data']['target_lun'])

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        db, 'volume_admin_metadata_get',
        side_effect=_volume_admin_metadata_get)
    def test_initialize_connection_multipath(
            self, volume_admin_metadata_get, execute,
            brick_get_connector_properties):
        """Normal case: Initialize connection in multipath environment."""
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = ["CL1-A", "CL1-B"]
        drv.do_setup(None)
        multipath_connector = copy.copy(DEFAULT_CONNECTOR)
        multipath_connector['multipath'] = True
        ret = drv.initialize_connection(TEST_VOLUME[0], multipath_connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        self.assertEqual(['0123456789abcdef', '0123456789abcdef'],
                         ret['data']['target_wwn'])
        self.assertEqual(0, ret['data']['target_lun'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_initialize_connection_provider_location_is_none(self, execute):
        """Error case: The volume's provider_location is None(MSGID0619-E)."""
        self.assertRaises(
            exception.VSPError, self.driver.initialize_connection,
            TEST_VOLUME[2], DEFAULT_CONNECTOR)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        db, 'volume_admin_metadata_get',
        side_effect=_volume_admin_metadata_get)
    def test_initialize_connection_already_attached(
            self, volume_admin_metadata_get, execute):
        """Unusual case: 'add lun' returns 'already defined' error."""
        ret = self.driver.initialize_connection(
            TEST_VOLUME[6], DEFAULT_CONNECTOR)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        self.assertEqual(['0123456789abcdef'], ret['data']['target_wwn'])
        self.assertEqual(255, ret['data']['target_lun'])

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        db, 'volume_admin_metadata_get',
        side_effect=_volume_admin_metadata_get)
    def test_initialize_connection_target_port_not_specified(
            self, volume_admin_metadata_get, execute,
            brick_get_connector_properties):
        """Normal case: target_port is not specified."""
        compute_connector = DEFAULT_CONNECTOR.copy()
        compute_connector['ip'] = '127.0.0.2'
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_target_ports = None
        drv.do_setup(None)
        ret = drv.initialize_connection(TEST_VOLUME[0], compute_connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        self.assertEqual(['0123456789abcdef'], ret['data']['target_wwn'])
        self.assertEqual(0, ret['data']['target_lun'])

    @mock.patch.object(
        utils, 'brick_get_connector_properties',
        side_effect=_brick_get_connector_properties)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        db, 'volume_admin_metadata_get',
        side_effect=_volume_admin_metadata_get)
    def test_initialize_connection_compute_port_not_specified(
            self, volume_admin_metadata_get, execute,
            brick_get_connector_properties):
        """Normal case: compute_target_port is not specified."""
        compute_connector = DEFAULT_CONNECTOR.copy()
        compute_connector['ip'] = '127.0.0.2'
        drv = vsp_fc.VSPFCDriver(
            configuration=self.configuration, db=db)
        self._setup_config()
        self.configuration.vsp_compute_target_ports = None
        drv.do_setup(None)
        ret = drv.initialize_connection(TEST_VOLUME[0], compute_connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        self.assertEqual(['0123456789abcdef'], ret['data']['target_wwn'])
        self.assertEqual(0, ret['data']['target_lun'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_terminate_connection(self, execute):
        """Normal case: Terminate connection."""
        self.driver.terminate_connection(TEST_VOLUME[6], DEFAULT_CONNECTOR)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_terminate_connection_provider_location_is_none(self, execute):
        """Unusual case: Volume's provider_location is None(MSGID0302-W)."""
        self.driver.terminate_connection(TEST_VOLUME[2], DEFAULT_CONNECTOR)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_terminate_connection_no_port_mapped_to_ldev(self, execute):
        """Unusual case: No port is mapped to the LDEV."""
        self.driver.terminate_connection(TEST_VOLUME[3], DEFAULT_CONNECTOR)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_terminate_connection_initiator_iqn_not_found(self, execute):
        """Error case: The connector does not have 'wwpns'(MSGID0650-E)."""
        connector = dict(DEFAULT_CONNECTOR)
        del connector['wwpns']

        self.assertRaises(
            exception.VSPError, self.driver.terminate_connection,
            TEST_VOLUME[0], connector)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_copy_volume_to_image(self, execute):
        """Normal case: Copy a volume to an image."""
        image_service = 'fake_image_service'
        image_meta = 'fake_image_meta'

        with mock.patch.object(driver.VolumeDriver, 'copy_volume_to_image') \
                as mock_copy_volume_to_image:
            self.driver.copy_volume_to_image(
                self.ctxt, TEST_VOLUME[0], image_service, image_meta)

        mock_copy_volume_to_image.assert_called_with(
            self.ctxt, TEST_VOLUME[0], image_service, image_meta)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing(self, execute):
        """Normal case: Bring an existing volume under Cinder's control."""
        ret = self.driver.manage_existing(
            TEST_VOLUME[0], self.test_existing_ref)
        self.assertEqual('0', ret['provider_location'])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing_get_size_normal(self, execute):
        """Normal case: Return an existing LDEV's size."""
        self.driver.manage_existing_get_size(
            TEST_VOLUME[0], self.test_existing_ref)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing_get_size_none_ldev_ref(self, execute):
        """Error case: Source LDEV's properties do not exist(MSGID0707-E)."""
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size, TEST_VOLUME[0],
            self.test_existing_none_ldev_ref)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing_get_size_invalid_ldev_ref(self, execute):
        """Error case: Source LDEV's ID is an invalid decimal(MSGID0707-E)."""
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size, TEST_VOLUME[0],
            self.test_existing_invalid_ldev_ref)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing_get_size_value_error_ref(self, execute):
        """Error case: Source LDEV's ID is an invalid hex(MSGID0707-E)."""
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size, TEST_VOLUME[0],
            self.test_existing_value_error_ref)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing_get_size_no_ldev_ref(self, execute):
        """Error case: Source LDEV's ID is not specified(MSGID0707-E)."""
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size, TEST_VOLUME[0],
            self.test_existing_no_ldev_ref)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing_get_size_invalid_sts_ldev(self, execute):
        """Error case: Source LDEV's STS is invalid(MSGID0707-E)."""
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size, TEST_VOLUME[0],
            self.test_existing_invalid_sts_ldev)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing_get_size_invalid_vol_attr(self, execute):
        """Error case: Source LDEV's VOL_ATTR is invalid(MSGID0702-E)."""
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size, TEST_VOLUME[0],
            self.test_existing_invalid_vol_attr)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing_get_size_invalid_size_ref(self, execute):
        """Error case: Source LDEV's VOL_Capacity is invalid(MSGID0703-E)."""
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size, TEST_VOLUME[0],
            self.test_existing_invalid_size)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_manage_existing_get_size_invalid_port_cnt(self, execute):
        """Error case: Source LDEV's NUM_PORT is invalid(MSGID0704-E)."""
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size, TEST_VOLUME[0],
            self.test_existing_invalid_port_cnt)

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    @mock.patch.object(
        vsp_horcm, '_run_horcmstart', side_effect=_fake_run_horcmstart2)
    def test_manage_existing_get_size_failed_to_start_horcmgr(
            self, _run_horcmstart, execute):
        """Error case: _start_horcmgr() returns an error(MSGID0320-W)."""
        global run_horcmstart_returns_error2
        run_horcmstart_returns_error2 = True
        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size, TEST_VOLUME[0],
            self.test_existing_failed_to_start_horcmgr)
        run_horcmstart_returns_error2 = False

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_unmanage(self, execute):
        """Normal case: Take out a volume from Cinder's control."""
        self.driver.unmanage(TEST_VOLUME[0])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_unmanage_provider_location_is_none(self, execute):
        """Error case: The volume's provider_location is None(MSGID0304-W)."""
        self.driver.unmanage(TEST_VOLUME[2])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_unmanage_volume_invalid_sts_ldev(self, execute):
        """Unusual case: The volume's STS is BLK."""
        self.driver.unmanage(TEST_VOLUME[13])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_unmanage_volume_is_busy(self, execute):
        """Error case: The volume is in a THIN volume pair(MSGID0616-E)."""
        self.assertRaises(
            exception.VolumeIsBusy, self.driver.unmanage, TEST_VOLUME[4])

    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_copy_image_to_volume(self, execute):
        """Normal case: Copy an image to a volume."""
        image_service = 'fake_image_service'
        image_id = 'fake_image_id'
        self.configuration.vsp_horcm_numbers = (400, 401)

        with mock.patch.object(driver.VolumeDriver, 'copy_image_to_volume') \
                as mock_copy_image:
            self.driver.copy_image_to_volume(
                self.ctxt, TEST_VOLUME[0], image_service, image_id)

        mock_copy_image.assert_called_with(
            self.ctxt, TEST_VOLUME[0], image_service, image_id)

    @mock.patch.object(utils, 'execute', side_effect=_cinder_execute)
    def test_update_migrated_volume_success(self, execute):
        """Normal case: 'modify ldev -status discard_zero_page' succeeds."""
        self.assertRaises(
            NotImplementedError,
            self.driver.update_migrated_volume,
            self.ctxt,
            TEST_VOLUME[0],
            TEST_VOLUME[2],
            "available")

    @mock.patch.object(vsp_horcm, '_EXEC_RETRY_INTERVAL', 1)
    @mock.patch.object(vsp_horcm, '_EXEC_MAX_WAITTIME', 1)
    @mock.patch.object(vsp_utils, 'execute', side_effect=_execute)
    def test_update_migrated_volume_error(self, execute):
        """Error case: 'modify ldev' fails(MSGID0315-W)."""
        self.assertRaises(
            NotImplementedError,
            self.driver.update_migrated_volume,
            self.ctxt,
            TEST_VOLUME[0],
            TEST_VOLUME[3],
            "available")

    def test_get_ldev_volume_is_none(self):
        """Error case: The volume is None."""
        self.assertIsNone(vsp_utils.get_ldev(None))

    def test_check_ignore_error_string(self):
        """Normal case: ignore_error is a string."""
        ignore_error = 'SSB=0xB980,0xB902'
        stderr = ('raidcom: [EX_CMDRJE] An order to the control/command device'
                  ' was rejected\nIt was rejected due to SKEY=0x05, ASC=0x26, '
                  'ASCQ=0x00, SSB=0xB980,0xB902 on Serial#(400003)\nCAUSE : '
                  'The specified port can not be operated.')
        self.assertTrue(vsp_utils.check_ignore_error(ignore_error, stderr))

    def test_check_opts_parameter_specified(self):
        """Normal case: A valid parameter is specified."""
        cfg.CONF.paramAAA = 'aaa'
        vsp_utils.check_opts(conf.Configuration(None),
                             [cfg.StrOpt('paramAAA')])

    def test_check_opt_value_parameter_not_set(self):
        """Error case: A parameter is not set(MSGID0601-E)."""
        self.assertRaises(cfg.NoSuchOptError,
                          vsp_utils.check_opt_value,
                          conf.Configuration(None),
                          ['paramCCC'])

    def test_build_initiator_target_map_no_lookup_service(self):
        """Normal case: None is specified for lookup_service."""
        connector = {'wwpns': ['0000000000000000', '1111111111111111']}
        target_wwns = ['2222222222222222', '3333333333333333']
        init_target_map = vsp_utils.build_initiator_target_map(connector,
                                                               target_wwns,
                                                               None)
        self.assertEqual(
            {'0000000000000000': ['2222222222222222', '3333333333333333'],
             '1111111111111111': ['2222222222222222', '3333333333333333']},
            init_target_map)

    def test_update_conn_info_not_update_conn_info(self):
        """Normal case: Not update connection info."""
        vsp_utils.update_conn_info(dict({'data': dict({'target_wwn': []})}),
                                   dict({'wwpns': []}),
                                   None)
