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
"""
Tests for the Inspur InStorage volume driver.
"""

import ddt
import mock

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.inspur.instorage import instorage_common

from cinder.tests.unit.volume.drivers.inspur.instorage import fakes


class CLIParserTestCase(test.TestCase):

    def test_empty(self):
        self.assertEqual(0, len(
            instorage_common.CLIParser('')))
        self.assertEqual(0, len(
            instorage_common.CLIParser(('', 'stderr'))))

    def test_header(self):
        raw = r'''id!name
1!node1
2!node2
'''
        resp = instorage_common.CLIParser(raw, with_header=True)
        self.assertEqual(2, len(resp))
        self.assertEqual('1', resp[0]['id'])
        self.assertEqual('2', resp[1]['id'])

    def test_select(self):
        raw = r'''id!123
name!Bill
name!Bill2
age!30
home address!s1
home address!s2

id! 7
name!John
name!John2
age!40
home address!s3
home address!s4
'''
        resp = instorage_common.CLIParser(raw, with_header=False)
        self.assertEqual([('s1', 'Bill', 's1'), ('s2', 'Bill2', 's2'),
                          ('s3', 'John', 's3'), ('s4', 'John2', 's4')],
                         list(resp.select('home address', 'name',
                                          'home address')))

    def test_lsnode_all(self):
        raw = r'''id!name!UPS_serial_number!WWNN!status
1!node1!!500507680200C744!online
2!node2!!500507680200C745!online
'''
        resp = instorage_common.CLIParser(raw)
        self.assertEqual(2, len(resp))
        self.assertEqual('1', resp[0]['id'])
        self.assertEqual('500507680200C744', resp[0]['WWNN'])
        self.assertEqual('2', resp[1]['id'])
        self.assertEqual('500507680200C745', resp[1]['WWNN'])

    def test_lsnode_single(self):
        raw = r'''id!1
port_id!500507680210C744
port_status!active
port_speed!8Gb
port_id!500507680240C744
port_status!inactive
port_speed!8Gb
'''
        resp = instorage_common.CLIParser(raw, with_header=False)
        self.assertEqual(1, len(resp))
        self.assertEqual('1', resp[0]['id'])
        self.assertEqual([('500507680210C744', 'active'),
                          ('500507680240C744', 'inactive')],
                         list(resp.select('port_id', 'port_status')))


class InStorageAssistantTestCase(test.TestCase):

    def setUp(self):
        super(InStorageAssistantTestCase, self).setUp()
        self.instorage_mcs_common = instorage_common.InStorageAssistant(None)
        self.mock_wait_time = mock.patch.object(
            instorage_common.InStorageAssistant, "WAIT_TIME", 0)

    @mock.patch.object(instorage_common.InStorageSSH, 'lslicense')
    @mock.patch.object(instorage_common.InStorageSSH, 'lsguicapabilities')
    def test_compression_enabled(self, lsguicapabilities, lslicense):
        fake_license_without_keys = {}
        fake_license = {
            'license_compression_enclosures': '1',
            'license_compression_capacity': '1'
        }
        fake_license_scheme = {
            'compression': 'yes'
        }
        fake_license_invalid_scheme = {
            'compression': 'no'
        }

        lslicense.side_effect = [fake_license_without_keys,
                                 fake_license_without_keys,
                                 fake_license,
                                 fake_license_without_keys]
        lsguicapabilities.side_effect = [fake_license_without_keys,
                                         fake_license_invalid_scheme,
                                         fake_license_scheme]
        self.assertFalse(self.instorage_mcs_common.compression_enabled())

        self.assertFalse(self.instorage_mcs_common.compression_enabled())

        self.assertTrue(self.instorage_mcs_common.compression_enabled())

        self.assertTrue(self.instorage_mcs_common.compression_enabled())

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_vdisk_count_by_io_group')
    def test_select_io_group(self, get_vdisk_count_by_io_group):
        # given io groups
        opts = {}
        # system io groups
        state = {}

        fake_iog_vdc1 = {0: 100, 1: 50, 2: 50, 3: 300}
        fake_iog_vdc2 = {0: 2, 1: 1, 2: 200}
        fake_iog_vdc3 = {0: 2, 2: 200}
        fake_iog_vdc4 = {0: 100, 1: 100, 2: 100, 3: 100}
        fake_iog_vdc5 = {0: 10, 1: 1, 2: 200, 3: 300}

        get_vdisk_count_by_io_group.side_effect = [fake_iog_vdc1,
                                                   fake_iog_vdc2,
                                                   fake_iog_vdc3,
                                                   fake_iog_vdc4,
                                                   fake_iog_vdc5]
        opts['iogrp'] = '0,2'
        state['available_iogrps'] = [0, 1, 2, 3]

        iog = self.instorage_mcs_common.select_io_group(state, opts)
        self.assertTrue(iog in state['available_iogrps'])
        self.assertEqual(2, iog)

        opts['iogrp'] = '0'
        state['available_iogrps'] = [0, 1, 2]

        iog = self.instorage_mcs_common.select_io_group(state, opts)
        self.assertTrue(iog in state['available_iogrps'])
        self.assertEqual(0, iog)

        opts['iogrp'] = '1,2'
        state['available_iogrps'] = [0, 2]

        iog = self.instorage_mcs_common.select_io_group(state, opts)
        self.assertTrue(iog in state['available_iogrps'])
        self.assertEqual(2, iog)

        opts['iogrp'] = ' 0, 1, 2 '
        state['available_iogrps'] = [0, 1, 2, 3]

        iog = self.instorage_mcs_common.select_io_group(state, opts)
        self.assertTrue(iog in state['available_iogrps'])
        # since vdisk count in all iogroups is same, it will pick the first
        self.assertEqual(0, iog)

        opts['iogrp'] = '0,1,2, 3'
        state['available_iogrps'] = [0, 1, 2, 3]

        iog = self.instorage_mcs_common.select_io_group(state, opts)
        self.assertTrue(iog in state['available_iogrps'])
        self.assertEqual(1, iog)


@ddt.ddt
class InStorageSSHTestCase(test.TestCase):

    def setUp(self):
        super(InStorageSSHTestCase, self).setUp()
        self.fake_driver = fakes.FakeInStorageMCSISCSIDriver(
            configuration=conf.Configuration(None))
        sim = fakes.FakeInStorage(['openstack'])
        self.fake_driver.set_fake_storage(sim)
        self.instorage_ssh = instorage_common.InStorageSSH(
            self.fake_driver._run_ssh)

    def test_mkvdiskhostmap(self):
        # mkvdiskhostmap should not be returning anything
        self.fake_driver.fake_storage._volumes_list['9999'] = {
            'name': ' 9999', 'id': '0', 'uid': '0',
            'IO_group_id': '0', 'IO_group_name': 'fakepool'}
        self.fake_driver.fake_storage._hosts_list['HOST1'] = {
            'name': 'HOST1', 'id': '0', 'host_name': 'HOST1'}
        self.fake_driver.fake_storage._hosts_list['HOST2'] = {
            'name': 'HOST2', 'id': '1', 'host_name': 'HOST2'}
        self.fake_driver.fake_storage._hosts_list['HOST3'] = {
            'name': 'HOST3', 'id': '2', 'host_name': 'HOST3'}

        ret = self.instorage_ssh.mkvdiskhostmap('HOST1', '9999', '511', False)
        self.assertEqual('511', ret)

        ret = self.instorage_ssh.mkvdiskhostmap('HOST2', '9999', '512', True)
        self.assertEqual('512', ret)

        ret = self.instorage_ssh.mkvdiskhostmap('HOST3', '9999', None, True)
        self.assertIsNotNone(ret)

        with mock.patch.object(
                instorage_common.InStorageSSH,
                'run_ssh_check_created') as run_ssh_check_created:
            ex = exception.VolumeBackendAPIException(data='CMMVC6071E')
            run_ssh_check_created.side_effect = ex
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.instorage_ssh.mkvdiskhostmap,
                              'HOST3', '9999', 511, True)

    @ddt.data((exception.VolumeBackendAPIException(data='CMMVC6372W'), None),
              (exception.VolumeBackendAPIException(data='CMMVC6372W'),
               {'name': 'fakevol', 'id': '0', 'uid': '0', 'IO_group_id': '0',
                'IO_group_name': 'fakepool'}),
              (exception.VolumeBackendAPIException(data='error'), None))
    @ddt.unpack
    def test_mkvdisk_with_warning(self, run_ssh_check, lsvol):
        opt = {'iogrp': 0}
        with mock.patch.object(instorage_common.InStorageSSH,
                               'run_ssh_check_created',
                               side_effect=run_ssh_check):
            with mock.patch.object(instorage_common.InStorageSSH, 'lsvdisk',
                                   return_value=lsvol):
                if lsvol:
                    ret = self.instorage_ssh.mkvdisk('fakevol', '1', 'gb',
                                                     'fakepool', opt, [])
                    self.assertEqual('0', ret)
                else:
                    self.assertRaises(exception.VolumeBackendAPIException,
                                      self.instorage_ssh.mkvdisk,
                                      'fakevol', '1', 'gb', 'fakepool',
                                      opt, [])
