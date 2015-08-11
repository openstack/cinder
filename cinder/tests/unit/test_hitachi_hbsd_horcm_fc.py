# Copyright (C) 2014, 2015, Hitachi, Ltd.
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

"""
Self test for Hitachi Block Storage Driver
"""

import mock

from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.hitachi import hbsd_basiclib
from cinder.volume.drivers.hitachi import hbsd_common
from cinder.volume.drivers.hitachi import hbsd_fc
from cinder.volume.drivers.hitachi import hbsd_horcm


def _exec_raidcom(*args, **kargs):
    return HBSDHORCMFCDriverTest.horcm_vals.get(args)


def _exec_raidcom_get_ldev_no_stdout(*args, **kargs):
    return HBSDHORCMFCDriverTest.horcm_get_ldev_no_stdout.get(args)


def _exec_raidcom_get_ldev_no_nml(*args, **kargs):
    return HBSDHORCMFCDriverTest.horcm_get_ldev_no_nml.get(args)


def _exec_raidcom_get_ldev_no_open_v(*args, **kargs):
    return HBSDHORCMFCDriverTest.horcm_get_ldev_no_open_v.get(args)


def _exec_raidcom_get_ldev_no_hdp(*args, **kargs):
    return HBSDHORCMFCDriverTest.horcm_get_ldev_no_hdp.get(args)


def _exec_raidcom_get_ldev_pair(*args, **kargs):
    return HBSDHORCMFCDriverTest.horcm_get_ldev_pair.get(args)


def _exec_raidcom_get_ldev_permit(*args, **kargs):
    return HBSDHORCMFCDriverTest.horcm_get_ldev_permit.get(args)


def _exec_raidcom_get_ldev_invalid_size(*args, **kargs):
    return HBSDHORCMFCDriverTest.horcm_get_ldev_invalid_size.get(args)


def _exec_raidcom_get_ldev_num_port(*args, **kargs):
    return HBSDHORCMFCDriverTest.horcm_get_ldev_num_port.get(args)


class HBSDHORCMFCDriverTest(test.TestCase):
    """Test HBSDHORCMFCDriver."""

    raidqry_result = "DUMMY\n\
Ver&Rev: 01-31-03/06"

    raidcom_get_host_grp_result = "DUMMY\n\
CL1-A 0 HBSD-127.0.0.1 None -\n\
CL1-A 1 - None -"

    raidcom_get_result = "LDEV : 0\n\
VOL_TYPE : OPEN-V-CVS\n\
LDEV : 1\n\
VOL_TYPE : NOT DEFINED"

    raidcom_get_result2 = "DUMMY\n\
LDEV : 1\n\
DUMMY\n\
DUMMY\n\
VOL_TYPE : OPEN-V-CVS\n\
VOL_ATTR : CVS : HDP\n\
VOL_Capacity(BLK) : 2097152\n\
NUM_PORT : 0\n\
STS : NML"

    raidcom_get_result3 = "Serial#  : 210944\n\
LDEV : 0\n\
SL : 0\n\
CL : 0\n\
VOL_TYPE : NOT DEFINED\n\
VOL_Capacity(BLK) : 2098560\n\
NUM_LDEV : 1\n\
LDEVs : 0\n\
NUM_PORT : 3\n\
PORTs : CL3-A-41 42 R7000001 : CL8-B-20 8 R7000000 : CL6-A-10 25 R7000000\n\
F_POOLID : NONE\n\
VOL_ATTR : CVS\n\
RAID_LEVEL  : RAID5\n\
RAID_TYPE   : 3D+1P\n\
NUM_GROUP : 1\n\
RAID_GROUPs : 01-01\n\
DRIVE_TYPE  : DKR5C-J600SS\n\
DRIVE_Capa : 1143358736\n\
LDEV_NAMING : test\n\
STS : NML\n\
OPE_TYPE : NONE\n\
OPE_RATE : 100\n\
MP# : 0\n\
SSID : 0004"

    raidcom_get_command_status_result = "HANDLE   SSB1    SSB2    ERR_CNT\
        Serial#     Description\n\
00d4        -       -          0         210944     -"

    raidcom_get_result4 = "Serial#  : 210944\n\
LDEV : 0\n\
SL : 0\n\
CL : 0\n\
VOL_TYPE : DEFINED\n\
VOL_Capacity(BLK) : 2098560\n\
NUM_LDEV : 1\n\
LDEVs : 0\n\
NUM_PORT : 3\n\
PORTs : CL3-A-41 42 R7000001 : CL8-B-20 8 R7000000 : CL6-A-10 25 R7000000\n\
F_POOLID : NONE\n\
VOL_ATTR : CVS\n\
RAID_LEVEL  : RAID5\n\
RAID_TYPE   : 3D+1P\n\
NUM_GROUP : 1\n\
RAID_GROUPs : 01-01\n\
DRIVE_TYPE  : DKR5C-J600SS\n\
DRIVE_Capa : 1143358736\n\
LDEV_NAMING : test\n\
STS : NML\n\
OPE_TYPE : NONE\n\
OPE_RATE : 100\n\
MP# : 0\n\
SSID : 0004"

    raidcom_get_copy_grp_result = "DUMMY\n\
HBSD-127.0.0.1None1A31 HBSD-127.0.0.1None1A31P - - None\n\
HBSD-127.0.0.1None1A31 HBSD-127.0.0.1None1A31S - - None"

    raidcom_get_device_grp_result1 = "DUMMY\n\
HBSD-127.0.0.1None1A31P HBSD-ldev-0-2 0 None"

    raidcom_get_device_grp_result2 = "DUMMY\n\
HBSD-127.0.0.1None1A31S HBSD-ldev-0-2 2 None"

    raidcom_get_snapshot_result = "DUMMY\n\
HBSD-sanp P-VOL PSUS None 0 3 3 18 100 G--- 53ee291f\n\
HBSD-sanp P-VOL PSUS None 0 4 4 18 100 G--- 53ee291f"

    raidcom_dp_pool_result = "DUMMY \n\
030  POLN   0        6006        6006   75   80    1 14860    32     167477"

    raidcom_port_result = "DUMMY\n\
CL1-A  FIBRE TAR AUT 01 Y PtoP Y 0 None 50060E801053C2E0 -"

    raidcom_port_result2 = "DUMMY\n\
CL1-A 12345678912345aa None -\n\
CL1-A 12345678912345bb None -"

    raidcom_host_grp_result = "DUMMY\n\
CL1-A 0 HBSD-127.0.0.1 None LINUX/IRIX"

    raidcom_hba_wwn_result = "DUMMY\n\
CL1-A 0 HBSD-127.0.0.1 12345678912345aa None -"

    raidcom_get_lun_result = "DUMMY\n\
CL1-A 0 LINUX/IRIX 254 1 5 - None"

    pairdisplay_result = "DUMMY\n\
HBSD-127.0.0.1None1A31 HBSD-ldev-0-2 L CL1-A-0 0 0 0 None 0 P-VOL PSUS None 2\
 -\n\
HBSD-127.0.0.1None1A31 HBSD-ldev-0-2 R CL1-A-0 0 0 0 None 2 S-VOL SSUS - 0 -"

    pairdisplay_result2 = "DUMMY\n\
HBSD-127.0.0.1None1A30 HBSD-ldev-1-1 L CL1-A-1 0 0 0 None 1 P-VOL PAIR None 1\
 -\n\
HBSD-127.0.0.1None1A30 HBSD-ldev-1-1 R CL1-A-1 0 0 0 None 1 S-VOL PAIR - 1 -"

    horcm_vals = {
        ('raidqry', u'-h'):
        [0, "%s" % raidqry_result, ""],
        ('raidcom', '-login user pasword'):
        [0, "", ""],
        ('raidcom', u'get host_grp -port CL1-A -key host_grp'):
        [0, "%s" % raidcom_get_host_grp_result, ""],
        ('raidcom', u'add host_grp -port CL1-A-1 -host_grp_name HBSD-pair00'):
        [0, "", ""],
        ('raidcom',
         u'add host_grp -port CL1-A-1 -host_grp_name HBSD-127.0.0.2'):
        [0, "", ""],
        ('raidcom', u'delete host_grp -port CL1-A-1 HBSD-127.0.0.2'):
        [1, "", ""],
        ('raidcom', 'get ldev -ldev_id 0 -cnt 2'):
        [0, "%s" % raidcom_get_result, ""],
        ('raidcom',
         'add ldev -pool 30 -ldev_id 1 -capacity 128G -emulation OPEN-V'):
        [0, "", ""],
        ('raidcom',
         'add ldev -pool 30 -ldev_id 1 -capacity 256G -emulation OPEN-V'):
        [1, "", "SSB=0x2E22,0x0001"],
        ('raidcom', 'get command_status'):
        [0, "%s" % raidcom_get_command_status_result, ""],
        ('raidcom', 'get ldev -ldev_id 1'):
        [0, "%s" % raidcom_get_result2, ""],
        ('raidcom', 'get ldev -ldev_id 1 -check_status NML -time 120'):
        [0, "", ""],
        ('raidcom', 'get snapshot -ldev_id 0'):
        [0, "", ""],
        ('raidcom', 'get snapshot -ldev_id 1'):
        [0, "%s" % raidcom_get_snapshot_result, ""],
        ('raidcom', 'get snapshot -ldev_id 2'):
        [0, "", ""],
        ('raidcom', 'get snapshot -ldev_id 3'):
        [0, "", ""],
        ('raidcom', 'get copy_grp'):
        [0, "%s" % raidcom_get_copy_grp_result, ""],
        ('raidcom', 'delete ldev -ldev_id 0'):
        [0, "", ""],
        ('raidcom', 'delete ldev -ldev_id 1'):
        [0, "", ""],
        ('raidcom', 'delete ldev -ldev_id 2'):
        [1, "", "error"],
        ('raidcom', 'delete ldev -ldev_id 3'):
        [1, "", "SSB=0x2E20,0x0000"],
        ('raidcom', 'get device_grp -device_grp_name HBSD-127.0.0.1None1A30P'):
        [0, "", ""],
        ('raidcom', 'get device_grp -device_grp_name HBSD-127.0.0.1None1A30S'):
        [0, "", ""],
        ('raidcom', 'get device_grp -device_grp_name HBSD-127.0.0.1None1A31P'):
        [0, "%s" % raidcom_get_device_grp_result1, ""],
        ('raidcom', 'get device_grp -device_grp_name HBSD-127.0.0.1None1A31S'):
        [0, "%s" % raidcom_get_device_grp_result2, ""],
        ('pairdisplay', '-g HBSD-127.0.0.1None1A30 -CLI'):
        [0, "", ""],
        ('pairdisplay', '-g HBSD-127.0.0.1None1A30 -d HBSD-ldev-0-1 -CLI'):
        [0, "", ""],
        ('pairdisplay', '-g HBSD-127.0.0.1None1A31 -CLI'):
        [0, "%s" % pairdisplay_result, ""],
        ('pairdisplay', '-g HBSD-127.0.0.1None1A31 -d HBSD-ldev-0-2 -CLI'):
        [0, "%s" % pairdisplay_result, ""],
        ('pairdisplay', '-g HBSD-127.0.0.1None1A30 -d HBSD-ldev-1-1 -CLI'):
        [0, "%s" % pairdisplay_result2, ""],
        ('raidcom',
         'add device_grp -device_grp_name HBSD-127.0.0.1None1A30P \
HBSD-ldev-0-1 -ldev_id 0'):
        [0, "", ""],
        ('raidcom',
         'add device_grp -device_grp_name HBSD-127.0.0.1None1A30S \
HBSD-ldev-0-1 -ldev_id 1'):
        [0, "", ""],
        ('raidcom',
         'add device_grp -device_grp_name HBSD-127.0.0.1None1A30P \
HBSD-ldev-1-1 -ldev_id 1'):
        [0, "", ""],
        ('raidcom',
         'add device_grp -device_grp_name HBSD-127.0.0.1None1A30S \
HBSD-ldev-1-1 -ldev_id 1'):
        [0, "", ""],
        ('raidcom',
         'add copy_grp -copy_grp_name HBSD-127.0.0.1None1A30 \
HBSD-127.0.0.1None1A30P HBSD-127.0.0.1None1A30S -mirror_id 0'):
        [0, "", ""],
        ('paircreate', '-g HBSD-127.0.0.1None1A30 -d HBSD-ldev-0-1 \
-split -fq quick -c 3 -vl'):
        [0, "", ""],
        ('paircreate', '-g HBSD-127.0.0.1None1A30 -d HBSD-ldev-1-1 \
-split -fq quick -c 3 -vl'):
        [0, "", ""],
        ('pairevtwait', '-g HBSD-127.0.0.1None1A30 -d HBSD-ldev-0-1 -nowait'):
        [4, "", ""],
        ('pairevtwait', '-g HBSD-127.0.0.1None1A30 -d HBSD-ldev-0-1 -nowaits'):
        [4, "", ""],
        ('pairevtwait', '-g HBSD-127.0.0.1None1A31 -d HBSD-ldev-0-2 -nowait'):
        [1, "", ""],
        ('pairevtwait', '-g HBSD-127.0.0.1None1A31 -d HBSD-ldev-0-2 -nowaits'):
        [1, "", ""],
        ('pairevtwait', '-g HBSD-127.0.0.1None1A30 -d HBSD-ldev-1-1 -nowait'):
        [4, "", ""],
        ('pairevtwait', '-g HBSD-127.0.0.1None1A30 -d HBSD-ldev-1-1 -nowaits'):
        [200, "", ""],
        ('pairsplit', '-g HBSD-127.0.0.1None1A31 -d HBSD-ldev-0-2 -S'):
        [0, "", ""],
        ('raidcom', 'extend ldev -ldev_id 0 -capacity 128G'):
        [0, "", ""],
        ('raidcom', 'get dp_pool'):
        [0, "%s" % raidcom_dp_pool_result, ""],
        ('raidcom', 'get port'):
        [0, "%s" % raidcom_port_result, ""],
        ('raidcom', 'get port -port CL1-A'):
        [0, "%s" % raidcom_port_result2, ""],
        ('raidcom', 'get host_grp -port CL1-A'):
        [0, "%s" % raidcom_host_grp_result, ""],
        ('raidcom', 'get hba_wwn -port CL1-A-0'):
        [0, "%s" % raidcom_hba_wwn_result, ""],
        ('raidcom', 'get hba_wwn -port CL1-A-1'):
        [0, "", ""],
        ('raidcom', 'add hba_wwn -port CL1-A-0 -hba_wwn 12345678912345bb'):
        [0, "", ""],
        ('raidcom', 'add hba_wwn -port CL1-A-1 -hba_wwn 12345678912345bb'):
        [1, "", ""],
        ('raidcom', u'get lun -port CL1-A-0'):
        [0, "%s" % raidcom_get_lun_result, ""],
        ('raidcom', u'get lun -port CL1-A-1'):
        [0, "", ""],
        ('raidcom', u'add lun -port CL1-A-0 -ldev_id 0 -lun_id 0'):
        [0, "", ""],
        ('raidcom', u'add lun -port CL1-A-0 -ldev_id 1 -lun_id 0'):
        [0, "", ""],
        ('raidcom', u'add lun -port CL1-A-1 -ldev_id 0 -lun_id 0'):
        [0, "", ""],
        ('raidcom', u'add lun -port CL1-A-1 -ldev_id 1 -lun_id 0'):
        [0, "", ""],
        ('raidcom', u'delete lun -port CL1-A-0 -ldev_id 0'):
        [0, "", ""],
        ('raidcom', u'delete lun -port CL1-A-0 -ldev_id 1'):
        [0, "", ""],
        ('raidcom', u'delete lun -port CL1-A-1 -ldev_id 0'):
        [0, "", ""],
        ('raidcom', u'delete lun -port CL1-A-1 -ldev_id 2'):
        [0, "", ""],
        ('raidcom', u'delete lun -port CL1-A-1 -ldev_id 1'):
        [1, "", ""]}

    horcm_get_ldev_no_stdout = {
        ('raidcom', 'get ldev -ldev_id 1'):
        [0, "", ""]}

    raidcom_get_ldev_no_nml = "DUMMY\n\
LDEV : 1\n\
DUMMY\n\
DUMMY\n\
VOL_TYPE : OPEN-V-CVS\n\
VOL_ATTR : CVS : HDP\n\
VOL_Capacity(BLK) : 2097152\n\
NUM_PORT : 0\n\
STS :"

    horcm_get_ldev_no_nml = {
        ('raidcom', 'get ldev -ldev_id 1'):
        [0, "%s" % raidcom_get_ldev_no_nml, ""]}

    raidcom_get_ldev_no_open_v = "DUMMY\n\
LDEV : 1\n\
DUMMY\n\
DUMMY\n\
VOL_TYPE : CVS\n\
VOL_ATTR : CVS : HDP\n\
VOL_Capacity(BLK) : 2097152\n\
NUM_PORT : 0\n\
STS : NML"

    horcm_get_ldev_no_open_v = {
        ('raidcom', 'get ldev -ldev_id 1'):
        [0, "%s" % raidcom_get_ldev_no_open_v, ""]}

    raidcom_get_ldev_no_hdp = "DUMMY\n\
LDEV : 1\n\
DUMMY\n\
DUMMY\n\
VOL_TYPE : OPEN-V-CVS\n\
VOL_ATTR : CVS :\n\
VOL_Capacity(BLK) : 2097152\n\
NUM_PORT : 0\n\
STS : NML"

    horcm_get_ldev_no_hdp = {
        ('raidcom', 'get ldev -ldev_id 1'):
        [0, "%s" % raidcom_get_ldev_no_hdp, ""]}

    raidcom_get_ldev_pair = "DUMMY\n\
LDEV : 1\n\
DUMMY\n\
DUMMY\n\
VOL_TYPE : OPEN-V-CVS\n\
VOL_ATTR : HORC : HDP\n\
VOL_Capacity(BLK) : 2097152\n\
NUM_PORT : 0\n\
STS : NML"

    horcm_get_ldev_pair = {
        ('raidcom', 'get ldev -ldev_id 1'):
        [0, "%s" % raidcom_get_ldev_pair, ""]}

    raidcom_get_ldev_permit = "DUMMY\n\
LDEV : 1\n\
DUMMY\n\
DUMMY\n\
VOL_TYPE : OPEN-V-CVS\n\
VOL_ATTR : XXX : HDP\n\
VOL_Capacity(BLK) : 2097152\n\
NUM_PORT : 0\n\
STS : NML"

    horcm_get_ldev_permit = {
        ('raidcom', 'get ldev -ldev_id 1'):
        [0, "%s" % raidcom_get_ldev_permit, ""]}

    raidcom_get_ldev_invalid_size = "DUMMY\n\
LDEV : 1\n\
DUMMY\n\
DUMMY\n\
VOL_TYPE : OPEN-V-CVS\n\
VOL_ATTR : CVS : HDP\n\
VOL_Capacity(BLK) : 2097151\n\
NUM_PORT : 0\n\
STS : NML"

    horcm_get_ldev_invalid_size = {
        ('raidcom', 'get ldev -ldev_id 1'):
        [0, "%s" % raidcom_get_ldev_invalid_size, ""]}

    raidcom_get_ldev_num_port = "DUMMY\n\
LDEV : 1\n\
DUMMY\n\
DUMMY\n\
VOL_TYPE : OPEN-V-CVS\n\
VOL_ATTR : CVS : HDP\n\
VOL_Capacity(BLK) : 2097152\n\
NUM_PORT : 1\n\
STS : NML"

    horcm_get_ldev_num_port = {
        ('raidcom', 'get ldev -ldev_id 1'):
        [0, "%s" % raidcom_get_ldev_num_port, ""]}

# The following information is passed on to tests, when creating a volume

    _VOLUME = {'size': 128, 'volume_type': None, 'source_volid': '0',
               'provider_location': '0', 'name': 'test',
               'id': 'abcdefg', 'snapshot_id': '0', 'status': 'available'}

    test_volume = {'name': 'test_volume', 'size': 128,
                   'id': 'test-volume',
                   'provider_location': '1', 'status': 'available'}

    test_volume_error = {'name': 'test_volume', 'size': 256,
                         'id': 'test-volume',
                         'status': 'creating'}

    test_volume_error2 = {'name': 'test_volume2', 'size': 128,
                          'id': 'test-volume2',
                          'provider_location': '1', 'status': 'available'}

    test_volume_error3 = {'name': 'test_volume3', 'size': 128,
                          'id': 'test-volume3',
                          'volume_metadata': [{'key': 'type',
                                               'value': 'V-VOL'}],
                          'provider_location': '1', 'status': 'available'}

    test_volume_error4 = {'name': 'test_volume4', 'size': 128,
                          'id': 'test-volume2',
                          'provider_location': '3', 'status': 'available'}

    test_volume_error5 = {'name': 'test_volume', 'size': 256,
                          'id': 'test-volume',
                          'provider_location': '1', 'status': 'available'}

    test_snapshot = {'volume_name': 'test', 'size': 128,
                     'volume_size': 128, 'name': 'test-snap',
                     'volume_id': 0, 'id': 'test-snap-0', 'volume': _VOLUME,
                     'provider_location': '0', 'status': 'available'}

    test_snapshot_error = {'volume_name': 'test', 'size': 128,
                           'volume_size': 128, 'name': 'test-snap',
                           'volume_id': 0, 'id': 'test-snap-0',
                           'volume': _VOLUME,
                           'provider_location': '2', 'status': 'available'}

    test_snapshot_error2 = {'volume_name': 'test', 'size': 128,
                            'volume_size': 128, 'name': 'test-snap',
                            'volume_id': 0, 'id': 'test-snap-0',
                            'volume': _VOLUME,
                            'provider_location': '1', 'status': 'available'}

    SERIAL_NUM = '210944'
    test_existing_ref = {'ldev': '1', 'serial_number': SERIAL_NUM}
    test_existing_none_ldev_ref = {'ldev': None,
                                   'serial_number': SERIAL_NUM}
    test_existing_invalid_ldev_ref = {'ldev': 'AAA',
                                      'serial_number': SERIAL_NUM}
    test_existing_no_ldev_ref = {'serial_number': SERIAL_NUM}
    test_existing_none_serial_ref = {'ldev': '1', 'serial_number': None}
    test_existing_invalid_serial_ref = {'ldev': '1', 'serial_number': '999999'}
    test_existing_no_serial_ref = {'ldev': '1'}

    def __init__(self, *args, **kwargs):
        super(HBSDHORCMFCDriverTest, self).__init__(*args, **kwargs)

    @mock.patch.object(utils, 'brick_get_connector_properties',
                       return_value={'ip': '127.0.0.1',
                                     'wwpns': ['12345678912345aa']})
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(utils, 'execute',
                       return_value=['%s' % raidqry_result, ''])
    def setUp(self, arg1, arg2, arg3, arg4):
        super(HBSDHORCMFCDriverTest, self).setUp()
        self._setup_config()
        self._setup_driver()
        self.driver.check_param()
        self.driver.common.pair_flock = hbsd_basiclib.NopLock()
        self.driver.common.command = hbsd_horcm.HBSDHORCM(self.configuration)
        self.driver.common.command.horcmgr_flock = hbsd_basiclib.NopLock()
        self.driver.common.create_lock_file()
        self.driver.common.command.connect_storage()
        self.driver.max_hostgroups = \
            self.driver.common.command.get_max_hostgroups()
        self.driver.add_hostgroup()
        self.driver.output_param_to_log()
        self.driver.do_setup_status.set()

    def _setup_config(self):
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.hitachi_pool_id = 30
        self.configuration.hitachi_thin_pool_id = 31
        self.configuration.hitachi_target_ports = "CL1-A"
        self.configuration.hitachi_debug_level = 0
        self.configuration.hitachi_serial_number = "None"
        self.configuration.hitachi_unit_name = None
        self.configuration.hitachi_group_request = True
        self.configuration.hitachi_group_range = None
        self.configuration.hitachi_zoning_request = False
        self.configuration.config_group = "None"
        self.configuration.hitachi_ldev_range = "0-1"
        self.configuration.hitachi_default_copy_method = 'FULL'
        self.configuration.hitachi_copy_check_interval = 1
        self.configuration.hitachi_async_copy_check_interval = 1
        self.configuration.hitachi_copy_speed = 3
        self.configuration.hitachi_horcm_add_conf = True
        self.configuration.hitachi_horcm_numbers = "409,419"
        self.configuration.hitachi_horcm_user = "user"
        self.configuration.hitachi_horcm_password = "pasword"
        self.configuration.hitachi_horcm_resource_lock_timeout = 600

    def _setup_driver(self):
        self.driver = hbsd_fc.HBSDFCDriver(
            configuration=self.configuration)
        context = None
        db = None
        self.driver.common = hbsd_common.HBSDCommon(
            self.configuration, self.driver, context, db)

# API test cases
    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_create_volume(self, arg1, arg2, arg3):
        """test create_volume."""
        ret = self.driver.create_volume(self._VOLUME)
        vol = self._VOLUME.copy()
        vol['provider_location'] = ret['provider_location']
        self.assertEqual('1', vol['provider_location'])

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_create_volume_error(self, arg1, arg2, arg3):
        """test create_volume."""
        self.assertRaises(exception.HBSDError, self.driver.create_volume,
                          self.test_volume_error)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_get_volume_stats(self, arg1, arg2):
        """test get_volume_stats."""
        stats = self.driver.get_volume_stats(True)
        self.assertEqual('Hitachi', stats['vendor_name'])

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_get_volume_stats_error(self, arg1, arg2):
        """test get_volume_stats."""
        self.configuration.hitachi_pool_id = 29
        stats = self.driver.get_volume_stats(True)
        self.assertEqual({}, stats)
        self.configuration.hitachi_pool_id = 30

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_extend_volume(self, arg1, arg2, arg3, arg4):
        """test extend_volume."""
        self.driver.extend_volume(self._VOLUME, 256)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_extend_volume_error(self, arg1, arg2, arg3, arg4):
        """test extend_volume."""
        self.assertRaises(exception.HBSDError, self.driver.extend_volume,
                          self.test_volume_error3, 256)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_delete_volume(self, arg1, arg2, arg3, arg4):
        """test delete_volume."""
        self.driver.delete_volume(self._VOLUME)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_delete_volume_error(self, arg1, arg2, arg3, arg4):
        """test delete_volume."""
        self.driver.delete_volume(self.test_volume_error4)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_snapshot_metadata',
                       return_value={'dummy_snapshot_meta': 'snapshot_meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume',
                       return_value=_VOLUME)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_create_snapshot(self, arg1, arg2, arg3, arg4, arg5, arg6, arg7):
        """test create_snapshot."""
        ret = self.driver.create_volume(self._VOLUME)
        ret = self.driver.create_snapshot(self.test_snapshot)
        self.assertEqual('1', ret['provider_location'])

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_snapshot_metadata',
                       return_value={'dummy_snapshot_meta': 'snapshot_meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume',
                       return_value=_VOLUME)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_create_snapshot_error(self, arg1, arg2, arg3, arg4, arg5, arg6,
                                   arg7):
        """test create_snapshot."""
        ret = self.driver.create_volume(self.test_volume)
        ret = self.driver.create_snapshot(self.test_snapshot_error)
        self.assertEqual('1', ret['provider_location'])

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_delete_snapshot(self, arg1, arg2, arg3, arg4):
        """test delete_snapshot."""
        self.driver.delete_snapshot(self.test_snapshot)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_delete_snapshot_error(self, arg1, arg2, arg3, arg4):
        """test delete_snapshot."""
        self.assertRaises(exception.HBSDCmdError,
                          self.driver.delete_snapshot,
                          self.test_snapshot_error)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_create_volume_from_snapshot(self, arg1, arg2, arg3, arg4, arg5):
        """test create_volume_from_snapshot."""
        vol = self.driver.create_volume_from_snapshot(self.test_volume,
                                                      self.test_snapshot)
        self.assertIsNotNone(vol)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_create_volume_from_snapshot_error(self, arg1, arg2, arg3, arg4,
                                               arg5):
        """test create_volume_from_snapshot."""
        self.assertRaises(exception.HBSDError,
                          self.driver.create_volume_from_snapshot,
                          self.test_volume_error5, self.test_snapshot_error2)
        return

    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume',
                       return_value=_VOLUME)
    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_create_cloned_volume(self, arg1, arg2, arg3, arg4, arg5, arg6):
        """test create_cloned_volume."""
        vol = self.driver.create_cloned_volume(self.test_volume,
                                               self._VOLUME)
        self.assertEqual('1', vol['provider_location'])
        return

    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume',
                       return_value=_VOLUME)
    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    def test_create_cloned_volume_error(self, arg1, arg2, arg3, arg4, arg5,
                                        arg6):
        """test create_cloned_volume."""
        self.assertRaises(exception.HBSDCmdError,
                          self.driver.create_cloned_volume,
                          self.test_volume, self.test_volume_error2)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_initialize_connection(self, arg1, arg2):
        """test initialize connection."""
        connector = {'wwpns': ['12345678912345aa', '12345678912345bb'],
                     'ip': '127.0.0.1'}
        rc = self.driver.initialize_connection(self._VOLUME, connector)
        self.assertEqual('fibre_channel', rc['driver_volume_type'])
        self.assertEqual(['50060E801053C2E0'], rc['data']['target_wwn'])
        self.assertEqual(0, rc['data']['target_lun'])
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_initialize_connection_error(self, arg1, arg2):
        """test initialize connection."""
        connector = {'wwpns': ['12345678912345bb'], 'ip': '127.0.0.2'}
        self.assertRaises(exception.HBSDError,
                          self.driver.initialize_connection,
                          self._VOLUME, connector)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_terminate_connection(self, arg1, arg2):
        """test terminate connection."""
        connector = {'wwpns': ['12345678912345aa', '12345678912345bb'],
                     'ip': '127.0.0.1'}
        rc = self.driver.terminate_connection(self._VOLUME, connector)
        self.assertEqual('fibre_channel', rc['driver_volume_type'])
        self.assertEqual(['50060E801053C2E0'], rc['data']['target_wwn'])
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_terminate_connection_error(self, arg1, arg2):
        """test terminate connection."""
        connector = {'ip': '127.0.0.1'}
        self.assertRaises(exception.HBSDError,
                          self.driver.terminate_connection,
                          self._VOLUME, connector)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_manage_existing(self, arg1, arg2):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        rc = self.driver.manage_existing(self._VOLUME, self.test_existing_ref)
        self.assertEqual(1, rc['provider_location'])

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size(self, arg1, arg2, arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        size = self.driver.manage_existing_get_size(self._VOLUME,
                                                    self.test_existing_ref)
        self.assertEqual(1, size)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_none_ldev_ref(self, arg1, arg2, arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_none_ldev_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_invalid_ldev_ref(self, arg1, arg2, arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_invalid_ldev_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_no_ldev_ref(self, arg1, arg2, arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_no_ldev_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_none_serial_ref(self, arg1, arg2,
                                                      arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_none_serial_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_invalid_serial_ref(self, arg1, arg2,
                                                         arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_invalid_serial_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_no_serial_ref(self, arg1, arg2, arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_no_serial_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'start_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'check_horcm',
                       return_value=[0, "", ""])
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_unmanage(self, arg1, arg2, arg3, arg4):
        self.driver.unmanage(self._VOLUME)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom)
    def test_unmanage_busy(self, arg1, arg2):
        self.assertRaises(exception.HBSDVolumeIsBusy,
                          self.driver.unmanage, self.test_volume_error3)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom_get_ldev_no_stdout)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_get_ldev_no_stdout(self, arg1, arg2,
                                                         arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom_get_ldev_no_nml)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_get_ldev_no_nml(self, arg1, arg2, arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom_get_ldev_no_open_v)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_get_ldev_no_open_v(self, arg1, arg2,
                                                         arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom_get_ldev_no_hdp)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_get_ldev_no_hdp(self, arg1, arg2, arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom_get_ldev_pair)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_get_ldev_pair(self, arg1, arg2, arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom_get_ldev_permit)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_get_ldev_permit(self, arg1, arg2, arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom_get_ldev_invalid_size)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_get_ldev_invalid_size(self, arg1, arg2,
                                                            arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_horcm.HBSDHORCM, 'exec_raidcom',
                       side_effect=_exec_raidcom_get_ldev_num_port)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_get_ldev_num_port(self, arg1, arg2,
                                                        arg3):
        self.configuration.hitachi_serial_number = self.SERIAL_NUM
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    def test_invalid_resource_lock_timeout_below_limit(self):
        self.configuration.hitachi_horcm_resource_lock_timeout = -1
        self.assertRaises(exception.HBSDError, self.driver.check_param)

    def test_invalid_resource_lock_timeout_over_limit(self):
        self.configuration.hitachi_horcm_resource_lock_timeout = 7201
        self.assertRaises(exception.HBSDError, self.driver.check_param)
