#
# Copyright (c) 2016 NEC Corporation.
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

import ddt
import mock
import unittest

from cinder import exception
from cinder.tests.unit.volume.drivers.nec import volume_common_test
from cinder.volume.drivers.nec import volume_helper


@ddt.ddt
class VolumeIDConvertTest(volume_helper.MStorageDriver, unittest.TestCase):

    def setUp(self):
        self._common = volume_common_test.MStorageVolCommDummy(1, 2, 3)
        self.do_setup(None)
        self.vol = {}
        self._properties = self._common.get_conf_properties()
        self._cli = self._properties['cli']
        self.xml = self._cli.view_all(self._properties['ismview_path'])
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self._common.configs(self.xml)

    def tearDown(self):
        pass

    @ddt.data(("AAAAAAAA", "LX:37mA82"), ("BBBBBBBB", "LX:3R9ZwR"))
    @ddt.unpack
    def test_volumeid_should_change_62scale(self, volid, ldname):
        self.vol['id'] = volid
        actual = self._convert_id2name(self.vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s should be change to %(ldname)s" %
                         {'volid': volid, 'ldname': ldname})

    @ddt.data(("AAAAAAAA", "LX:37mA82_back"), ("BBBBBBBB", "LX:3R9ZwR_back"))
    @ddt.unpack
    def test_snap_volumeid_should_change_62scale_andpostfix(self,
                                                            volid,
                                                            ldname):
        self.vol['id'] = volid
        actual = self._convert_id2snapname(self.vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s should be change to %(ldname)s" %
                         {'volid': volid, 'ldname': ldname})

    @ddt.data(("AAAAAAAA", "LX:37mA82_m"), ("BBBBBBBB", "LX:3R9ZwR_m"))
    @ddt.unpack
    def test_ddrsnap_volumeid_should_change_62scale_and_m(self,
                                                          volid,
                                                          ldname):
        self.vol['id'] = volid
        actual = self._convert_id2migratename(self.vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s should be change to %(ldname)s" %
                         {'volid': volid, 'ldname': ldname})

    @ddt.data(("AAAAAAAA", "LX:3R9ZwR", "target:BBBBBBBB"))
    @ddt.unpack
    def test_migrate_volumeid_should_change_62scale_andpostfix(self,
                                                               volid,
                                                               ldname,
                                                               status):
        self.vol['id'] = volid
        self.vol['migration_status'] = status
        actual = self._convert_id2name_in_migrate(self.vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s/%(status)s should be "
                         "change to %(ldname)s" %
                         {'volid': volid,
                          'status': status,
                          'ldname': ldname})

    @ddt.data(("AAAAAAAA", "LX:37mA82", "deleting:BBBBBBBB"),
              ("AAAAAAAA", "LX:37mA82", ""),
              ("AAAAAAAA", "LX:37mA82", "success"))
    @ddt.unpack
    def test_NOTmigrate_volumeid_should_change_62scale(self,
                                                       volid,
                                                       ldname,
                                                       status):
        self.vol['id'] = volid
        self.vol['migration_status'] = status
        actual = self._convert_id2name_in_migrate(self.vol)
        self.assertEqual(ldname, actual,
                         "ID:%(volid)s/%(status)s should be "
                         "change to %(ldname)s" %
                         {'volid': volid,
                          'status': status,
                          'ldname': ldname})


class NominatePoolLDTest(volume_helper.MStorageDriver, unittest.TestCase):

    def setUp(self):
        self._common = volume_common_test.MStorageVolCommDummy(1, 2, 3)
        self.do_setup(None)
        self.vol = {}
        self._properties = self._common.get_conf_properties()
        self._cli = self._properties['cli']
        self.xml = self._cli.view_all(self._properties['ismview_path'])
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self._common.configs(self.xml)
        self._numofld_per_pool = 1024

    def tearDown(self):
        pass

    def test_getxml(self):
        self.assertIsNotNone(self.xml, "iSMview xml should not be None")

    def test_selectldn_for_normalvolume(self):
        ldn = self._select_ldnumber(self.used_ldns, self.max_ld_count)
        self.assertEqual(2, ldn, "selected ldn should be XXX")

    def test_selectpool_for_normalvolume(self):
        self.vol['size'] = 10
        pool = self._select_leastused_poolnumber(self.vol,
                                                 self.pools,
                                                 self.xml)
        self.assertEqual(1, pool, "selected pool should be 1")
        # config:pool_pools=[1]
        self.vol['size'] = 999999999999
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'No available pools found.'):
            pool = self._select_leastused_poolnumber(self.vol,
                                                     self.pools,
                                                     self.xml)

    def test_selectpool_for_migratevolume(self):
        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        self.vol['size'] = 10
        self.vol['pool_num'] = 0
        pool = self._select_migrate_poolnumber(self.vol,
                                               self.pools,
                                               self.xml,
                                               [1])
        self.assertEqual(1, pool, "selected pool should be 1")
        self.vol['id'] = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        self.vol['size'] = 10
        self.vol['pool_num'] = 1
        pool = self._select_migrate_poolnumber(self.vol,
                                               self.pools,
                                               self.xml,
                                               [1])
        self.assertEqual(-1, pool, "selected pool is the same pool(return -1)")
        self.vol['size'] = 999999999999
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'No available pools found.'):
            pool = self._select_migrate_poolnumber(self.vol,
                                                   self.pools,
                                                   self.xml,
                                                   [1])

    def test_selectpool_for_snapvolume(self):
        self.vol['size'] = 10
        savePool1 = self.pools[1]['free']
        self.pools[1]['free'] = 0
        pool = self._select_dsv_poolnumber(self.vol, self.pools)
        self.assertEqual(2, pool, "selected pool should be 2")
        # config:pool_backup_pools=[2]
        self.pools[1]['free'] = savePool1

        if len(self.pools[0]['ld_list']) is 1024:
            savePool2 = self.pools[2]['free']
            savePool3 = self.pools[3]['free']
            self.pools[2]['free'] = 0
            self.pools[3]['free'] = 0
            with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                         'No available pools found.'):
                pool = self._select_dsv_poolnumber(self.vol, self.pools)
            self.pools[2]['free'] = savePool2
            self.pools[3]['free'] = savePool3

        self.vol['size'] = 999999999999
        pool = self._select_dsv_poolnumber(self.vol, self.pools)
        self.assertEqual(2, pool, "selected pool should be 2")
        # config:pool_backup_pools=[2]

    def test_selectpool_for_ddrvolume(self):
        self.vol['size'] = 10
        pool = self._select_ddr_poolnumber(self.vol,
                                           self.pools,
                                           self.xml,
                                           10)
        self.assertEqual(2, pool, "selected pool should be 2")
        # config:pool_backup_pools=[2]

        savePool2 = self.pools[2]['free']
        savePool3 = self.pools[3]['free']
        self.pools[2]['free'] = 0
        self.pools[3]['free'] = 0
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'No available pools found.'):
            pool = self._select_ddr_poolnumber(self.vol,
                                               self.pools,
                                               self.xml,
                                               10)
        self.pools[2]['free'] = savePool2
        self.pools[3]['free'] = savePool3

        self.vol['size'] = 999999999999
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'No available pools found.'):
            pool = self._select_ddr_poolnumber(self.vol,
                                               self.pools,
                                               self.xml,
                                               999999999999)

    def test_selectpool_for_volddrvolume(self):
        self.vol['size'] = 10
        pool = self._select_volddr_poolnumber(self.vol,
                                              self.pools,
                                              self.xml,
                                              10)
        self.assertEqual(1, pool, "selected pool should be 1")
        # config:pool_backup_pools=[2]

        savePool0 = self.pools[0]['free']
        savePool1 = self.pools[1]['free']
        self.pools[0]['free'] = 0
        self.pools[1]['free'] = 0
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'No available pools found.'):
            pool = self._select_volddr_poolnumber(self.vol,
                                                  self.pools,
                                                  self.xml,
                                                  10)
        self.pools[0]['free'] = savePool0
        self.pools[1]['free'] = savePool1

        self.vol['size'] = 999999999999
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'No available pools found.'):
            pool = self._select_volddr_poolnumber(self.vol,
                                                  self.pools,
                                                  self.xml,
                                                  999999999999)


class VolumeCreateTest(volume_helper.MStorageDriver, unittest.TestCase):

    def setUp(self):
        self._common = volume_common_test.MStorageVolCommDummy(1, 2, 3)
        self.do_setup(None)
        self.vol = {}
        self._properties = self._common.get_conf_properties()
        self._cli = self._properties['cli']
        self.xml = self._cli.view_all(self._properties['ismview_path'])
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self._common.configs(self.xml)

    def tearDown(self):
        pass

    def test_validate_migrate_volume(self):
        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        self.vol['size'] = 10
        self.vol['status'] = 'available'
        self._validate_migrate_volume(self.vol, self.xml)

        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        self.vol['size'] = 10
        self.vol['status'] = 'creating'
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'Specified Logical Disk'
                                     ' LX:287RbQoP7VdwR1WsPC2fZT'
                                     ' is not available.'):
            self._validate_migrate_volume(self.vol, self.xml)

        self.vol['id'] = "AAAAAAAA"
        self.vol['size'] = 10
        self.vol['status'] = 'available'
        with self.assertRaisesRegexp(exception.NotFound,
                                     'Logical Disk `LX:37mA82`'
                                     ' does not exist.'):
            self._validate_migrate_volume(self.vol, self.xml)

    def test_extend_volume(self):
        mv = self.lds["LX:287RbQoP7VdwR1WsPC2fZT"]    # MV-LDN:0 RV-LDN:4
        rvs = self._can_extend_capacity(10, self.pools, self.lds, mv)
        self.assertEqual("LX:287RbQoP7VdwR1WsPC2fZT_back", rvs[4]['ldname'])
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'Not enough pool capacity.'
                                     ' pool_number=0,'
                                     ' size_increase=1073741822926258176'):
            self._can_extend_capacity(1000000000,
                                      self.pools,
                                      self.lds, mv)

        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"  # MV
        self.vol['size'] = 1
        self.vol['status'] = 'available'
        self.extend_volume(self.vol, 10)

        self.vol['id'] = "00046058-d38e-7f60-67b7-59ed65e54225"  # RV
        self.vol['size'] = 1
        self.vol['status'] = 'available'
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'RPL Attribute Error.'
                                     ' RPL Attribute = RV'):
            self.extend_volume(self.vol, 10)


class BindLDTest(volume_helper.MStorageDriver, unittest.TestCase):

    def setUp(self):
        self._common = volume_common_test.MStorageVolCommDummy(1, 2, 3)
        self.do_setup(None)
        self.vol = {}
        self._properties = self._common.get_conf_properties()
        self._cli = self._properties['cli']
        self.xml = self._cli.view_all(self._properties['ismview_path'])
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self._common.configs(self.xml)
        self.src = {}
        mock_bindld = mock.Mock()
        self._bind_ld = mock_bindld
        self._bind_ld.return_value = (0, 0, 0)

    def test_bindld_CreateVolume(self):
        self.vol['id'] = "AAAAAAAA"
        self.vol['size'] = 1
        self.vol['migration_status'] = "success"
        self.create_volume(self.vol)
        self._bind_ld.assert_called_once_with(
            self.vol, self.vol['size'], None,
            self._convert_id2name_in_migrate,
            self._select_leastused_poolnumber)

    def test_bindld_CreateCloneVolume(self):
        self.vol['id'] = "AAAAAAAA"
        self.vol['size'] = 1
        self.vol['migration_status'] = "success"
        self.src['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        self.src['size'] = 1
        self.create_cloned_volume(self.vol, self.src)
        self._bind_ld.assert_called_once_with(
            self.vol, self.vol['size'], None,
            self._convert_id2name,
            self._select_leastused_poolnumber)


class BindLDTest_iSCSISnap(volume_helper.MStorageDriver,
                           unittest.TestCase):

    def setUp(self):
        self._common = volume_common_test.MStorageVolCommDummy(1, 2, 3)
        self.do_setup(None)
        self.vol = {}
        self._properties = self._common.get_conf_properties()
        self._cli = self._properties['cli']
        self.xml = self._cli.view_all(self._properties['ismview_path'])
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self._common.configs(self.xml)
        self.snap = {}
        mock_bindld = mock.Mock()
        self._bind_ld = mock_bindld
        self._bind_ld.return_value = (0, 0, 0)

    def test_bindld_CreateSnapshot(self):
        self.snap['id'] = "AAAAAAAA"
        self.snap['volume_id'] = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        self.snap['size'] = 10
        self.create_snapshot(self.snap)
        self._bind_ld.assert_called_once_with(
            self.snap, 10, None,
            self._convert_id2snapname,
            self._select_ddr_poolnumber, 10)

    def test_bindld_CreateFromSnapshot(self):
        self.vol['id'] = "AAAAAAAA"
        self.vol['size'] = 1
        self.vol['migration_status'] = "success"
        self.snap['id'] = "63410c76-2f12-4473-873d-74a63dfcd3e2"
        self.snap['volume_id'] = "92dbc7f4-dbc3-4a87-aef4-d5a2ada3a9af"
        self.create_volume_from_snapshot(self.vol, self.snap)
        self._bind_ld.assert_called_once_with(
            self.vol, 10, None,
            self._convert_id2name,
            self._select_volddr_poolnumber, 10)


class BindLDTest_Snap(volume_helper.MStorageDSVDriver, unittest.TestCase):

    def setUp(self):
        self._common = volume_common_test.MStorageVolCommDummy(1, 2, 3)
        self.do_setup(None)
        self.vol = {}
        self._properties = self._common.get_conf_properties()
        self._cli = self._properties['cli']
        self.xml = self._cli.view_all(self._properties['ismview_path'])
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self._common.configs(self.xml)
        self.snap = {}
        mock_bindld = mock.Mock()
        self._bind_ld = mock_bindld
        self._bind_ld.return_value = (0, 0, 0)

    def test_bindld_CreateFromSnapshot(self):
        self.vol['id'] = "AAAAAAAA"
        self.vol['size'] = 1
        self.vol['migration_status'] = "success"
        self.snap['id'] = "63410c76-2f12-4473-873d-74a63dfcd3e2"
        self.snap['volume_id'] = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        self.create_volume_from_snapshot(self.vol, self.snap)
        self._bind_ld.assert_called_once_with(
            self.vol, 1, None,
            self._convert_id2name,
            self._select_volddr_poolnumber, 1)


class ExportTest(volume_helper.MStorageDriver, unittest.TestCase):

    def setUp(self):
        self._common = volume_common_test.MStorageVolCommDummy(1, 2, 3)
        self.do_setup(None)
        self.vol = {}
        self._properties = self._common.get_conf_properties()
        self._cli = self._properties['cli']
        self.xml = self._cli.view_all(self._properties['ismview_path'])
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self._common.configs(self.xml)
        mock_getldset = mock.Mock()
        self._common.get_ldset = mock_getldset
        self._common.get_ldset.return_value = self.ldsets["LX:OpenStack0"]

    def tearDown(self):
        pass

    def test_iscsi_portal(self):
        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        self.vol['size'] = 10
        self.vol['status'] = None
        self.vol['migration_status'] = None
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255"}
        self.iscsi_do_export(None, self.vol, connector)

    def test_fc_do_export(self):
        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        self.vol['size'] = 10
        self.vol['status'] = None
        self.vol['migration_status'] = None
        connector = {'wwpns': ["1000-0090-FAA0-723A", "1000-0090-FAA0-723B"]}
        self.fc_do_export(None, self.vol, connector)

    def test_remove_export(self):
        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        self.vol['size'] = 10
        self.vol['status'] = 'uploading'
        self.vol['attach_status'] = 'attached'
        self.vol['migration_status'] = None
        context = mock.Mock()
        ret = self.remove_export(context, self.vol)
        self.assertIsNone(ret)

        self.vol['attach_status'] = None

        self.vol['status'] = 'downloading'
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'Failed to unregister Logical Disk from'
                                     ' Logical Disk Set \(iSM31064\)'):
            self.remove_export(context, self.vol)

        self.vol['status'] = None
        migstat = 'target:1febb976-86d0-42ed-9bc0-4aa3e158f27d'
        self.vol['migration_status'] = migstat
        ret = self.remove_export(context, self.vol)
        self.assertIsNone(ret)

    def test_iscsi_initialize_connection(self):
        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        loc = "127.0.0.1:3260:1 iqn.2010-10.org.openstack:volume-00000001 88"
        self.vol['provider_location'] = loc
        connector = {'initiator': "iqn.1994-05.com.redhat:d1d8e8f23255",
                     'multipath': True}
        info = self._iscsi_initialize_connection(self.vol, connector)
        self.assertEqual('iscsi', info['driver_volume_type'])
        self.assertEqual('iqn.2010-10.org.openstack:volume-00000001',
                         info['data']['target_iqn'])
        self.assertEqual('127.0.0.1:3260', info['data']['target_portal'])
        self.assertEqual(88, info['data']['target_lun'])
        self.assertEqual('iqn.2010-10.org.openstack:volume-00000001',
                         info['data']['target_iqns'][0])
        self.assertEqual('127.0.0.1:3260', info['data']['target_portals'][0])
        self.assertEqual(88, info['data']['target_luns'][0])

    def test_fc_initialize_connection(self):
        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        self.vol['migration_status'] = None
        connector = {'wwpns': ["1000-0090-FAA0-723A", "1000-0090-FAA0-723B"]}
        info = self._fc_initialize_connection(self.vol, connector)
        self.assertEqual('fibre_channel', info['driver_volume_type'])
        self.assertEqual('2100000991020012', info['data']['target_wwn'][0])
        self.assertEqual('2200000991020012', info['data']['target_wwn'][1])
        self.assertEqual('2900000991020012', info['data']['target_wwn'][2])
        self.assertEqual('2A00000991020012', info['data']['target_wwn'][3])
        self.assertEqual(
            '2100000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723A'][0])
        self.assertEqual(
            '2100000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723B'][0])
        self.assertEqual(
            '2200000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723A'][1])
        self.assertEqual(
            '2200000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723B'][1])
        self.assertEqual(
            '2900000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723A'][2])
        self.assertEqual(
            '2900000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723B'][2])
        self.assertEqual(
            '2A00000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723A'][3])
        self.assertEqual(
            '2A00000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723B'][3])

    def test_fc_terminate_connection(self):
        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        connector = {'wwpns': ["1000-0090-FAA0-723A", "1000-0090-FAA0-723B"]}
        info = self._fc_terminate_connection(self.vol, connector)
        self.assertEqual('fibre_channel', info['driver_volume_type'])
        self.assertEqual('2100000991020012', info['data']['target_wwn'][0])
        self.assertEqual('2200000991020012', info['data']['target_wwn'][1])
        self.assertEqual('2900000991020012', info['data']['target_wwn'][2])
        self.assertEqual('2A00000991020012', info['data']['target_wwn'][3])
        self.assertEqual(
            '2100000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723A'][0])
        self.assertEqual(
            '2100000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723B'][0])
        self.assertEqual(
            '2200000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723A'][1])
        self.assertEqual(
            '2200000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723B'][1])
        self.assertEqual(
            '2900000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723A'][2])
        self.assertEqual(
            '2900000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723B'][2])
        self.assertEqual(
            '2A00000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723A'][3])
        self.assertEqual(
            '2A00000991020012',
            info['data']['initiator_target_map']['1000-0090-FAA0-723B'][3])


class DeleteDSVVolume_test(volume_helper.MStorageDSVDriver,
                           unittest.TestCase):

    def setUp(self):
        self._common = volume_common_test.MStorageVolCommDummy(1, 2, 3)
        self.do_setup(None)
        self.vol = {}
        self._properties = self._common.get_conf_properties()
        self._cli = self._properties['cli']
        self.xml = self._cli.view_all(self._properties['ismview_path'])
        (self.pools,
         self.lds,
         self.ldsets,
         self.used_ldns,
         self.hostports,
         self.max_ld_count) = self._common.configs(self.xml)

    def patch_query_MV_RV_status(self, ldname, rpltype):
        return 'replicated'

    @mock.patch('cinder.tests.unit.volume.drivers.nec.cli_test.'
                'MStorageISMCLI.query_MV_RV_status', patch_query_MV_RV_status)
    def test_delete_volume(self):
        # MV not separated
        self.vol['id'] = "46045673-41e7-44a7-9333-02f07feab04b"
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'Specified Logical Disk'
                                     ' LX:287RbQoP7VdwR1WsPC2fZT'
                                     ' has been copied.'):
            self.delete_volume(self.vol)
        # RV not separated
        self.vol['id'] = "00046058-d38e-7f60-67b7-59ed65e54225"
        with self.assertRaisesRegexp(exception.VolumeBackendAPIException,
                                     'Specified Logical Disk'
                                     ' LX:20000009910200140005'
                                     ' has been copied.'):
            self.delete_volume(self.vol)

    def test_delete_snapshot(self):
        self.vol['id'] = "63410c76-2f12-4473-873d-74a63dfcd3e2"
        self.vol['volume_id'] = "1febb976-86d0-42ed-9bc0-4aa3e158f27d"
        ret = self.delete_snapshot(self.vol)
        self.assertIsNone(ret)
