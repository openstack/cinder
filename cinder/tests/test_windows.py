# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Pedro Navarro Perez
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

"""
Unit tests for Windows Server 2012 OpenStack Cinder volume driver
"""
import sys

import cinder.flags
from cinder.tests.windows import basetestcase
from cinder.tests.windows import db_fakes
from cinder.tests.windows import windowsutils
from cinder.volume.drivers import windows

FLAGS = cinder.flags.FLAGS


class TestWindowsDriver(basetestcase.BaseTestCase):

    def __init__(self, method):
        super(TestWindowsDriver, self).__init__(method)

    def setUp(self):
        super(TestWindowsDriver, self).setUp()
        self.flags(
            windows_iscsi_lun_path='C:\iSCSIVirtualDisks',
        )
        self._volume_data = None
        self._volume_data_2 = None
        self._snapshot_data = None
        self._connector_data = None
        self._volume_id = '10958016-e196-42e3-9e7f-5d8927ae3099'
        self._volume_id_2 = '20958016-e196-42e3-9e7f-5d8927ae3098'
        self._snapshot_id = '30958016-e196-42e3-9e7f-5d8927ae3097'
        self._iqn = "iqn.1991-05.com.microsoft:dell1160dsy"

        self._setup_stubs()

        self._drv = windows.WindowsDriver()
        self._drv.do_setup({})
        self._wutils = windowsutils.WindowsUtils()

    def _setup_stubs(self):

        # Modules to mock
        modules_to_mock = [
            'wmi',
            'os',
            'subprocess',
            'multiprocessing'
        ]

        modules_to_test = [
            windows,
            windowsutils,
            sys.modules[__name__]
        ]

        self._inject_mocks_in_modules(modules_to_mock, modules_to_test)

    def tearDown(self):
        try:
            if (self._volume_data_2 and
                    self._wutils.volume_exists(self._volume_data_2['name'])):
                self._wutils.delete_volume(self._volume_data_2['name'])

            if (self._volume_data and
                    self._wutils.volume_exists(
                        self._volume_data['name'])):
                self._wutils.delete_volume(self._volume_data['name'])
            if (self._snapshot_data and
                    self._wutils.snapshot_exists(
                        self._snapshot_data['name'])):
                self._wutils.delete_snapshot(self._snapshot_data['name'])
            if (self._connector_data and
                    self._wutils.initiator_id_exists(
                        "%s%s" % (FLAGS.iscsi_target_prefix,
                                  self._volume_data['name']),
                        self._connector_data['initiator'])):
                target_name = "%s%s" % (FLAGS.iscsi_target_prefix,
                                        self._volume_data['name'])
                initiator_name = self._connector_data['initiator']
                self._wutils.delete_initiator_id(target_name, initiator_name)
            if (self._volume_data and
                    self._wutils.export_exists("%s%s" %
                                               (FLAGS.iscsi_target_prefix,
                                                self._volume_data['name']))):
                self._wutils.delete_export(
                    "%s%s" % (FLAGS.iscsi_target_prefix,
                              self._volume_data['name']))

        finally:
            super(TestWindowsDriver, self).tearDown()

    def test_check_for_setup_errors(self):
        self._drv.check_for_setup_error()

    def test_create_volume(self):
        self._create_volume()

        wt_disks = self._wutils.find_vhd_by_name(self._volume_data['name'])
        self.assertEquals(len(wt_disks), 1)

    def _create_volume(self):
        self._volume_data = db_fakes.get_fake_volume_info(self._volume_id)
        self._drv.create_volume(self._volume_data)

    def test_delete_volume(self):
        self._create_volume()

        self._drv.delete_volume(self._volume_data)

        wt_disks = self._wutils.find_vhd_by_name(self._volume_data['name'])
        self.assertEquals(len(wt_disks), 0)

    def test_create_snapshot(self):
        #Create a volume
        self._create_volume()

        wt_disks = self._wutils.find_vhd_by_name(self._volume_data['name'])
        self.assertEquals(len(wt_disks), 1)
        #Create a snapshot from the previous volume
        self._create_snapshot()

        snapshot_name = self._snapshot_data['name']
        wt_snapshots = self._wutils.find_snapshot_by_name(snapshot_name)
        self.assertEquals(len(wt_snapshots), 1)

    def _create_snapshot(self):
        volume_name = self._volume_data['name']
        snapshot_id = self._snapshot_id
        self._snapshot_data = db_fakes.get_fake_snapshot_info(volume_name,
                                                              snapshot_id)
        self._drv.create_snapshot(self._snapshot_data)

    def test_create_volume_from_snapshot(self):
        #Create a volume
        self._create_volume()
        #Create a snapshot from the previous volume
        self._create_snapshot()

        self._volume_data_2 = db_fakes.get_fake_volume_info(self._volume_id_2)

        self._drv.create_volume_from_snapshot(self._volume_data_2,
                                              self._snapshot_data)

        wt_disks = self._wutils.find_vhd_by_name(self._volume_data_2['name'])
        self.assertEquals(len(wt_disks), 1)

    def test_delete_snapshot(self):
        #Create a volume
        self._create_volume()
        #Create a snapshot from the previous volume
        self._create_snapshot()

        self._drv.delete_snapshot(self._snapshot_data)

        snapshot_name = self._snapshot_data['name']
        wt_snapshots = self._wutils.find_snapshot_by_name(snapshot_name)
        self.assertEquals(len(wt_snapshots), 0)

    def test_create_export(self):
        #Create a volume
        self._create_volume()

        retval = self._drv.create_export({}, self._volume_data)

        volume_name = self._volume_data['name']
        self.assertEquals(
            retval,
            {'provider_location': "%s%s" % (FLAGS.iscsi_target_prefix,
                                            volume_name)})

    def test_initialize_connection(self):
        #Create a volume
        self._create_volume()

        self._drv.create_export({}, self._volume_data)

        self._connector_data = db_fakes.get_fake_connector_info(self._iqn)

        init_data = self._drv.initialize_connection(self._volume_data,
                                                    self._connector_data)
        target_name = self._volume_data['provider_location']
        initiator_name = self._connector_data['initiator']

        wt_initiator_ids = self._wutils.find_initiator_ids(target_name,
                                                           initiator_name)
        self.assertEquals(len(wt_initiator_ids), 1)

        properties = init_data['data']
        self.assertNotEqual(properties['target_iqn'], None)

    def test_ensure_export(self):
        #Create a volume
        self._create_volume()

        self._drv.ensure_export({}, self._volume_data)

    def test_remove_export(self):
        #Create a volume
        self._create_volume()

        self._drv.create_export({}, self._volume_data)

        self._drv.remove_export({}, self._volume_data)
