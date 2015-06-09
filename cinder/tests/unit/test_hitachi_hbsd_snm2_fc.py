# Copyright (C) 2014, Hitachi, Ltd.
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
from cinder.volume import configuration as conf
from cinder.volume.drivers.hitachi import hbsd_basiclib
from cinder.volume.drivers.hitachi import hbsd_common
from cinder.volume.drivers.hitachi import hbsd_fc
from cinder.volume.drivers.hitachi import hbsd_snm2


def _exec_hsnm(*args, **kargs):
    return HBSDSNM2FCDriverTest.hsnm_vals.get(args)


def _exec_hsnm_get_lu_ret_err(*args, **kargs):
    return HBSDSNM2FCDriverTest.hsnm_get_lu_ret_err.get(args)


def _exec_hsnm_get_lu_vol_type_err(*args, **kargs):
    return HBSDSNM2FCDriverTest.hsnm_get_lu_vol_type_err.get(args)


def _exec_hsnm_get_lu_dppool_err(*args, **kargs):
    return HBSDSNM2FCDriverTest.hsnm_get_lu_dppool_err.get(args)


def _exec_hsnm_get_lu_size_err(*args, **kargs):
    return HBSDSNM2FCDriverTest.hsnm_get_lu_size_err.get(args)


def _exec_hsnm_get_lu_num_port_err(*args, **kargs):
    return HBSDSNM2FCDriverTest.hsnm_get_lu_num_port_err.get(args)


class HBSDSNM2FCDriverTest(test.TestCase):
    """Test HBSDSNM2FCDriver."""

    audppool_result = "  DP                RAID                               \
                        Current Utilization  Current Over          Replication\
 Available        Current Replication                    Rotational \
                                                                              \
                                                                       Stripe \
 Needing Preparation\n\
  Pool  Tier Mode   Level         Total Capacity        Consumed Capacity     \
   Percent              Provisioning Percent  Capacity                     \
Utilization Percent  Type                   Speed  Encryption  Status         \
                                                                        \
Reconstruction Progress                          Size    Capacity\n\
     30  Disable       1( 1D+1D)           532.0 GB                   2.0 GB  \
                     1%                24835%                 532.0 GB        \
               1%  SAS                 10000rpm  N/A         Normal           \
                                                                      N/A     \
                                          256KB                 0.0 GB"

    aureplicationlocal_result = "Pair Name                          LUN  Pair \
LUN  Status                                              Copy Type    Group   \
    Point-in-Time  MU Number\n\
                                     0         10  0 Split( 99%)             \
                        ShadowImage   ---:Ungrouped                        N/A\
                   "

    auluref_result = "                            Stripe  RAID     DP    Tier \
  RAID                           Rotational  Number\n\
   LU       Capacity        Size    Group    Pool  Mode     Level        Type\
                   Speed  of Paths  Status\n\
    0       2097152 blocks   256KB      0       0  Enable     0  Normal"

    auluref_result1 = "                           Stripe  RAID     DP    Tier \
  RAID                           Rotational  Number\n\
   LU       Capacity        Size    Group    Pool  Mode     Level        Type\
                   Speed  of Paths  Status\n\
    0       2097152 blocks   256KB      0       0  Enable     0  DUMMY"

    auhgwwn_result = "Port 00 Host Group Security  ON\n  Detected WWN\n    \
Name                              Port Name         Host Group\n\
HBSD-00                              10000000C97BCE7A  001:HBSD-01\n\
  Assigned WWN\n    Name                              Port Name         \
Host Group\n    abcdefg                           10000000C97BCE7A  \
001:HBSD-01"

    aufibre1_result = "Port Information\n\
                                                    Port Address\n  CTL  Port\
   Node Name          Port Name          Setting Current\n    0     0   \
50060E801053C2E0   50060E801053C2E0   0000EF  272700"

    auhgmap_result = "Mapping Mode = ON\nPort  Group                          \
    H-LUN    LUN\n  00  001:HBSD-00                               0   1000"

    hsnm_vals = {
        ('audppool', '-unit None -refer -g'): [0, "%s" % audppool_result, ""],
        ('aureplicationlocal',
         '-unit None -create -si -pvol 1 -svol 1 -compsplit -pace normal'):
        [0, "", ""],
        ('aureplicationlocal',
         '-unit None -create -si -pvol 3 -svol 1 -compsplit -pace normal'):
        [1, "", ""],
        ('aureplicationlocal', '-unit None -refer -pvol 1'):
        [0, "%s" % aureplicationlocal_result, ""],
        ('aureplicationlocal', '-unit None -refer -pvol 3'):
        [1, "", "DMEC002015"],
        ('aureplicationlocal', '-unit None -refer -svol 3'):
        [1, "", "DMEC002015"],
        ('aureplicationlocal', '-unit None -simplex -si -pvol 1 -svol 0'):
        [0, "", ""],
        ('auluchgsize', '-unit None -lu 1 -size 256g'):
        [0, "", ""],
        ('auludel', '-unit None -lu 1 -f'): [0, 0, ""],
        ('auludel', '-unit None -lu 3 -f'): [1, 0, ""],
        ('auluadd', '-unit None -lu 1 -dppoolno 30 -size 128g'): [0, 0, ""],
        ('auluadd', '-unit None -lu 1 -dppoolno 30 -size 256g'): [1, "", ""],
        ('auluref', '-unit None'): [0, "%s" % auluref_result, ""],
        ('auluref', '-unit None -lu 0'): [0, "%s" % auluref_result, ""],
        ('auhgmap', '-unit None -add 0 0 1 1 1'): [0, 0, ""],
        ('auhgwwn', '-unit None -refer'): [0, "%s" % auhgwwn_result, ""],
        ('aufibre1', '-unit None -refer'): [0, "%s" % aufibre1_result, ""],
        ('auhgmap', '-unit None -refer'): [0, "%s" % auhgmap_result, ""]}

    auluref_ret_err = "Stripe  RAID     DP    Tier \
  RAID                           Rotational  Number\n\
   LU       Capacity        Size    Group    Pool  Mode     Level        Type\
                   Speed  of Paths  Status\n\
    0       2097152 blocks   256KB      0       0  Enable     0  Normal"

    hsnm_get_lu_ret_err = {
        ('auluref', '-unit None -lu 0'): [1, "%s" % auluref_ret_err, ""],
    }

    auluref_vol_type_err = "Stripe  RAID     DP    Tier \
  RAID                           Rotational  Number\n\
   LU       Capacity        Size    Group    Pool  Mode     Level        Type\
                   Speed  of Paths  Status\n\
    0       2097152 blocks   256KB      0       0  Enable     0  DUMMY"

    hsnm_get_lu_vol_type_err = {
        ('auluref', '-unit None -lu 0'):
        [0, "%s" % auluref_vol_type_err, ""],
    }

    auluref_dppool_err = "Stripe  RAID     DP    Tier \
  RAID                           Rotational  Number\n\
   LU       Capacity        Size    Group    Pool  Mode     Level        Type\
                   Speed  of Paths  Status\n\
    0       2097152 blocks   256KB      0       N/A  Enable     0  Normal"

    hsnm_get_lu_dppool_err = {
        ('auluref', '-unit None -lu 0'):
        [0, "%s" % auluref_dppool_err, ""],
    }

    auluref_size_err = "Stripe  RAID     DP    Tier \
  RAID                           Rotational  Number\n\
   LU       Capacity        Size    Group    Pool  Mode     Level        Type\
                   Speed  of Paths  Status\n\
    0       2097151 blocks   256KB      N/A       0  Enable     0  Normal"
    hsnm_get_lu_size_err = {
        ('auluref', '-unit None -lu 0'): [0, "%s" % auluref_size_err, ""],
    }

    auluref_num_port_err = "Stripe  RAID     DP    Tier \
  RAID                           Rotational  Number\n\
   LU       Capacity        Size    Group    Pool  Mode     Level        Type\
                   Speed  of Paths  Status\n\
    0       2097152 blocks   256KB      0       0  Enable     1  Normal"

    hsnm_get_lu_num_port_err = {
        ('auluref', '-unit None -lu 0'): [0, "%s" % auluref_num_port_err, ""],
    }

# The following information is passed on to tests, when creating a volume

    _VOLUME = {'size': 128, 'volume_type': None, 'source_volid': '0',
               'provider_location': '1', 'name': 'test',
               'id': 'abcdefg', 'snapshot_id': '0', 'status': 'available'}

    test_volume = {'name': 'test_volume', 'size': 128,
                   'id': 'test-volume-0',
                   'provider_location': '1', 'status': 'available'}

    test_volume_error = {'name': 'test_volume_error', 'size': 256,
                         'id': 'test-volume-error',
                         'provider_location': '3', 'status': 'available'}

    test_volume_error1 = {'name': 'test_volume_error', 'size': 128,
                          'id': 'test-volume-error',
                          'provider_location': None, 'status': 'available'}

    test_volume_error2 = {'name': 'test_volume_error', 'size': 256,
                          'id': 'test-volume-error',
                          'provider_location': '1', 'status': 'available'}

    test_volume_error3 = {'name': 'test_volume3', 'size': 128,
                          'id': 'test-volume3',
                          'volume_metadata': [{'key': 'type',
                                               'value': 'V-VOL'}],
                          'provider_location': '1', 'status': 'available'}

    test_volume_error4 = {'name': 'test_volume4', 'size': 128,
                          'id': 'test-volume2',
                          'provider_location': '3', 'status': 'available'}

    test_snapshot = {'volume_name': 'test', 'size': 128,
                     'volume_size': 128, 'name': 'test-snap',
                     'volume_id': 0, 'id': 'test-snap-0', 'volume': _VOLUME,
                     'provider_location': '1', 'status': 'available'}

    test_snapshot_error2 = {'volume_name': 'test', 'size': 128,
                            'volume_size': 128, 'name': 'test-snap',
                            'volume_id': 0, 'id': 'test-snap-0',
                            'volume': test_volume_error,
                            'provider_location': None, 'status': 'available'}

    UNIT_NAME = 'HUS110_91122819'
    test_existing_ref = {'ldev': '0', 'unit_name': UNIT_NAME}
    test_existing_none_ldev_ref = {'ldev': None, 'unit_name': UNIT_NAME}
    test_existing_invalid_ldev_ref = {'ldev': 'AAA', 'unit_name': UNIT_NAME}
    test_existing_no_ldev_ref = {'unit_name': UNIT_NAME}
    test_existing_none_unit_ref = {'ldev': '0', 'unit_name': None}
    test_existing_invalid_unit_ref = {'ldev': '0', 'unit_name': 'Dummy'}
    test_existing_no_unit_ref = {'ldev': '0'}

    def __init__(self, *args, **kwargs):
        super(HBSDSNM2FCDriverTest, self).__init__(*args, **kwargs)

    def setUp(self):
        super(HBSDSNM2FCDriverTest, self).setUp()
        self._setup_config()
        self._setup_driver()

    def _setup_config(self):
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.hitachi_pool_id = 30
        self.configuration.hitachi_target_ports = "00"
        self.configuration.hitachi_debug_level = 0
        self.configuration.hitachi_serial_number = "None"
        self.configuration.hitachi_unit_name = "None"
        self.configuration.hitachi_group_request = False
        self.configuration.hitachi_zoning_request = False
        self.configuration.config_group = "None"
        self.configuration.hitachi_ldev_range = [0, 100]
        self.configuration.hitachi_default_copy_method = 'SI'
        self.configuration.hitachi_copy_check_interval = 1
        self.configuration.hitachi_copy_speed = 3

    def _setup_driver(self):
        self.driver = hbsd_fc.HBSDFCDriver(
            configuration=self.configuration)
        context = None
        db = None
        self.driver.common = hbsd_common.HBSDCommon(
            self.configuration, self.driver, context, db)
        self.driver.common.command = hbsd_snm2.HBSDSNM2(self.configuration)
        self.driver.common.pair_flock = \
            self.driver.common.command.set_pair_flock()
        self.driver.common.horcmgr_flock = \
            self.driver.common.command.set_horcmgr_flock()
        self.driver.do_setup_status.set()

# API test cases
    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_create_volume(self, arg1, arg2, arg3):
        """test create_volume."""
        ret = self.driver.create_volume(self._VOLUME)
        vol = self._VOLUME.copy()
        vol['provider_location'] = ret['provider_location']
        self.assertEqual(vol['provider_location'], '1')

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_create_volume_error(self, arg1, arg2, arg3):
        """test create_volume."""
        self.assertRaises(exception.HBSDCmdError,
                          self.driver.create_volume,
                          self.test_volume_error)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_get_volume_stats(self, arg1, arg2):
        """test get_volume_stats."""
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(stats['vendor_name'], 'Hitachi')

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_get_volume_stats_error(self, arg1, arg2):
        """test get_volume_stats."""
        self.configuration.hitachi_pool_id = 29
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(stats, {})
        self.configuration.hitachi_pool_id = 30

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_extend_volume(self, arg1, arg2):
        """test extend_volume."""
        self.driver.extend_volume(self._VOLUME, 256)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_extend_volume_error(self, arg1, arg2):
        """test extend_volume."""
        self.assertRaises(exception.HBSDError, self.driver.extend_volume,
                          self.test_volume_error3, 256)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_delete_volume(self, arg1, arg2):
        """test delete_volume."""
        self.driver.delete_volume(self._VOLUME)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_delete_volume_error(self, arg1, arg2):
        """test delete_volume."""
        self.assertRaises(exception.HBSDCmdError,
                          self.driver.delete_volume,
                          self.test_volume_error4)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_snapshot_metadata',
                       return_value={'dummy_snapshot_meta': 'snapshot_meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume',
                       return_value=_VOLUME)
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_create_snapshot(self, arg1, arg2, arg3, arg4, arg5):
        """test create_snapshot."""
        ret = self.driver.create_volume(self._VOLUME)
        ret = self.driver.create_snapshot(self.test_snapshot)
        self.assertEqual(ret['provider_location'], '1')

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_snapshot_metadata',
                       return_value={'dummy_snapshot_meta': 'snapshot_meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume',
                       return_value=test_volume_error)
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_create_snapshot_error(self, arg1, arg2, arg3, arg4, arg5):
        """test create_snapshot."""
        self.assertRaises(exception.HBSDCmdError,
                          self.driver.create_snapshot,
                          self.test_snapshot_error2)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_delete_snapshot(self, arg1, arg2):
        """test delete_snapshot."""
        self.driver.delete_snapshot(self.test_snapshot)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_delete_snapshot_error(self, arg1, arg2):
        """test delete_snapshot."""
        self.driver.delete_snapshot(self.test_snapshot_error2)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_create_volume_from_snapshot(self, arg1, arg2, arg3):
        """test create_volume_from_snapshot."""
        vol = self.driver.create_volume_from_snapshot(self._VOLUME,
                                                      self.test_snapshot)
        self.assertIsNotNone(vol)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_create_volume_from_snapshot_error(self, arg1, arg2, arg3):
        """test create_volume_from_snapshot."""
        self.assertRaises(exception.HBSDError,
                          self.driver.create_volume_from_snapshot,
                          self.test_volume_error2, self.test_snapshot)
        return

    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume',
                       return_value=_VOLUME)
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    def test_create_cloned_volume(self, arg1, arg2, arg3, arg4):
        """test create_cloned_volume."""
        vol = self.driver.create_cloned_volume(self._VOLUME,
                                               self.test_volume)
        self.assertIsNotNone(vol)
        return

    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume_metadata',
                       return_value={'dummy_volume_meta': 'meta'})
    @mock.patch.object(hbsd_common.HBSDCommon, 'get_volume',
                       return_value=test_volume_error1)
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    def test_create_cloned_volume_error(self, arg1, arg2, arg3, arg4):
        """test create_cloned_volume."""
        self.assertRaises(exception.HBSDError,
                          self.driver.create_cloned_volume,
                          self._VOLUME, self.test_volume_error1)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_initialize_connection(self, arg1, arg2):
        """test initialize connection."""
        connector = {'wwpns': '0x100000', 'ip': '0xc0a80100'}
        rc = self.driver.initialize_connection(self._VOLUME, connector)
        self.assertEqual(rc['driver_volume_type'], 'fibre_channel')
        self.assertEqual(rc['data']['target_wwn'], ['50060E801053C2E0'])
        self.assertEqual(rc['data']['target_lun'], 1)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_initialize_connection_error(self, arg1, arg2):
        """test initialize connection."""
        connector = {'wwpns': 'x', 'ip': '0xc0a80100'}
        self.assertRaises(exception.HBSDError,
                          self.driver.initialize_connection,
                          self._VOLUME, connector)
        return

    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_terminate_connection(self, arg1):
        """test terminate connection."""
        connector = {'wwpns': '0x100000', 'ip': '0xc0a80100'}
        rc = self.driver.terminate_connection(self._VOLUME, connector)
        self.assertEqual(rc['driver_volume_type'], 'fibre_channel')
        self.assertEqual(rc['data']['target_wwn'], ['50060E801053C2E0'])
        return

    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_terminate_connection_error(self, arg1):
        """test terminate connection."""
        connector = {'ip': '0xc0a80100'}
        self.assertRaises(exception.HBSDError,
                          self.driver.terminate_connection,
                          self._VOLUME, connector)
        return

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_manage_existing(self, arg1, arg2):
        rc = self.driver.manage_existing(self._VOLUME, self.test_existing_ref)
        self.assertEqual(0, rc['provider_location'])

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        size = self.driver.manage_existing_get_size(self._VOLUME,
                                                    self.test_existing_ref)
        self.assertEqual(1, size)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_none_ldev(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_none_ldev_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_invalid_ldev_ref(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_invalid_ldev_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_no_ldev_ref(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_no_ldev_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_none_unit_ref(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_none_unit_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_invalid_unit_ref(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_invalid_unit_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_no_unit_ref(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_no_unit_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm',
                       side_effect=_exec_hsnm_get_lu_ret_err)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_size_ret_err(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm',
                       side_effect=_exec_hsnm_get_lu_vol_type_err)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_lu_vol_type_err(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm',
                       side_effect=_exec_hsnm_get_lu_dppool_err)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_lu_dppool_err(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm',
                       side_effect=_exec_hsnm_get_lu_size_err)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_lu_size_err(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm',
                       side_effect=_exec_hsnm_get_lu_num_port_err)
    @mock.patch.object(hbsd_common.HBSDCommon, '_update_volume_metadata')
    def test_manage_existing_get_lu_num_port_err(self, arg1, arg2, arg3):
        self.configuration.hitachi_unit_name = self.UNIT_NAME
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self._VOLUME,
                          self.test_existing_ref)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_unmanage(self, arg1, arg2):
        self.driver.unmanage(self._VOLUME)

    @mock.patch.object(hbsd_basiclib, 'get_process_lock')
    @mock.patch.object(hbsd_snm2.HBSDSNM2, 'exec_hsnm', side_effect=_exec_hsnm)
    def test_unmanage_busy(self, arg1, arg2):
        self.assertRaises(exception.HBSDVolumeIsBusy,
                          self.driver.unmanage, self.test_volume_error3)
