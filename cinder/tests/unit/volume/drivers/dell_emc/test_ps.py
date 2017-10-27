#    Copyright (c) 2013-2017 Dell Inc, or its subsidiaries.
#    Copyright 2013 OpenStack Foundation
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

import time
import unittest

from eventlet import greenthread
import mock
from oslo_concurrency import processutils
import paramiko
import six

from cinder import context
from cinder import exception
from cinder import ssh_utils
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc import ps


class PSSeriesISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(PSSeriesISCSIDriverTestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.san_is_local = False
        self.configuration.san_ip = "10.0.0.1"
        self.configuration.san_login = "foo"
        self.configuration.san_password = "bar"
        self.configuration.san_ssh_port = 16022
        self.configuration.san_thin_provision = True
        self.configuration.san_private_key = 'foo'
        self.configuration.ssh_min_pool_conn = 1
        self.configuration.ssh_max_pool_conn = 5
        self.configuration.ssh_conn_timeout = 30
        self.configuration.eqlx_pool = 'non-default'
        self.configuration.eqlx_group_name = 'group-0'
        self.configuration.eqlx_cli_max_retries = 5

        self.configuration.use_chap_auth = True
        self.configuration.chap_username = 'admin'
        self.configuration.chap_password = 'password'

        self.configuration.max_over_subscription_ratio = 1.0

        self.driver_stats_output = ['TotalCapacity: 111GB',
                                    'FreeSpace: 11GB',
                                    'VolumeReportedSpace: 80GB',
                                    'TotalVolumes: 100']
        self.cmd = 'this is dummy command'
        self._context = context.get_admin_context()
        self.driver = ps.PSSeriesISCSIDriver(
            configuration=self.configuration)
        self.volume_name = "fakevolume"
        self.volid = "fakeid"
        self.volume = {'name': self.volume_name,
                       'display_name': 'fake_display_name'}
        self.connector = {
            'ip': '10.0.0.2',
            'initiator': 'iqn.1993-08.org.debian:01:2227dab76162',
            'host': 'fakehost'}
        self.access_record_output = [
            "ID  Initiator       Ipaddress     AuthMethod UserName   Apply-To",
            "--- --------------- ------------- ---------- ---------- --------",
            "1   iqn.1993-08.org.debian:01:222 *.*.*.*       none        both",
            "       7dab76162"]
        self.fake_access_id = '1'
        self.fake_iqn = 'iqn.2003-10.com.equallogic:group01:25366:fakev'
        self.fake_iqn_return = ['iSCSI target name is %s.' % self.fake_iqn]
        self.fake_volume_output = ["Size: 5GB",
                                   "iSCSI Name: %s" % self.fake_iqn,
                                   "Description: "]
        self.fake_volume_info = {'size': 5.0,
                                 'iSCSI_Name': self.fake_iqn}
        self.driver._group_ip = '10.0.1.6'
        self.properties = {
            'target_discovered': True,
            'target_portal': '%s:3260' % self.driver._group_ip,
            'target_iqn': self.fake_iqn,
            'volume_id': 1,
            'discard': True}
        self._model_update = {
            'provider_location': "%s:3260,1 %s 0" % (self.driver._group_ip,
                                                     self.fake_iqn),
            'provider_auth': 'CHAP %s %s' % (
                self.configuration.chap_username,
                self.configuration.chap_password)
        }

    def _fake_get_iscsi_properties(self, volume):
        return self.properties

    def test_create_volume(self):
        volume = {'name': self.volume_name, 'size': 1}
        mock_attrs = {'args': ['volume', 'create', volume['name'],
                               "%sG" % (volume['size']), 'pool',
                               self.configuration.eqlx_pool,
                               'thin-provision']}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.return_value = self.fake_iqn_return
            model_update = self.driver.create_volume(volume)
            self.assertEqual(self._model_update, model_update)

    def test_delete_volume(self):
        volume = {'name': self.volume_name, 'size': 1}
        show_attrs = {'args': ['volume', 'select', volume['name'], 'show']}
        off_attrs = {'args': ['volume', 'select', volume['name'], 'offline']}
        delete_attrs = {'args': ['volume', 'delete', volume['name']]}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**show_attrs)
            mock_eql_execute.configure_mock(**off_attrs)
            mock_eql_execute.configure_mock(**delete_attrs)
            self.driver.delete_volume(volume)

    def test_delete_absent_volume(self):
        volume = {'name': self.volume_name, 'size': 1, 'id': self.volid}
        mock_attrs = {'args': ['volume', 'select', volume['name'], 'show']}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.side_effect = processutils.ProcessExecutionError(
                stdout='% Error ..... does not exist.\n')
            self.driver.delete_volume(volume)

    def test_ensure_export(self):
        volume = {'name': self.volume_name, 'size': 1}
        mock_attrs = {'args': ['volume', 'select', volume['name'], 'show']}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            self.driver.ensure_export({}, volume)

    def test_create_snapshot(self):
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name'}
        snap_name = 'fake_snap_name'
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.return_value = ['Snapshot name is %s' % snap_name]
            self.driver.create_snapshot(snapshot)

    def test_create_volume_from_snapshot(self):
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name',
                    'volume_size': '1'}
        volume = {'name': self.volume_name, 'size': '1'}
        mock_attrs = {'args': ['volume', 'select', snapshot['volume_name'],
                               'snapshot', 'select', snapshot['name'],
                               'clone', volume['name']]}

        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            with mock.patch.object(self.driver,
                                   'extend_volume') as mock_extend_volume:
                mock_eql_execute.configure_mock(**mock_attrs)
                mock_eql_execute.return_value = self.fake_iqn_return
                mock_extend_volume.return_value = self.fake_iqn_return
                model_update = self.driver.create_volume_from_snapshot(
                    volume, snapshot)
                self.assertEqual(self._model_update, model_update)
                self.assertFalse(self.driver.extend_volume.called)

    def test_create_volume_from_snapshot_extend(self):
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name',
                    'volume_size': '100'}
        volume = {'name': self.volume_name, 'size': '200'}
        mock_attrs = {'args': ['volume', 'select', snapshot['volume_name'],
                               'snapshot', 'select', snapshot['name'],
                               'clone', volume['name']]}

        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            with mock.patch.object(self.driver,
                                   'extend_volume') as mock_extend_volume:
                mock_eql_execute.configure_mock(**mock_attrs)
                mock_eql_execute.return_value = self.fake_iqn_return
                mock_extend_volume.return_value = self.fake_iqn_return
                model_update = self.driver.create_volume_from_snapshot(
                    volume, snapshot)
                self.assertEqual(self._model_update, model_update)
                self.assertTrue(self.driver.extend_volume.called)
                self.driver.extend_volume.assert_called_once_with(
                    volume, volume['size'])

    def test_create_cloned_volume(self):
        src_vref = {'name': 'fake_uuid', 'size': '1'}
        volume = {'name': self.volume_name, 'size': '1'}
        mock_attrs = {'args': ['volume', 'select', volume['name'],
                               'multihost-access', 'enable']}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            with mock.patch.object(self.driver,
                                   'extend_volume') as mock_extend_volume:
                mock_eql_execute.configure_mock(**mock_attrs)
                mock_eql_execute.return_value = self.fake_iqn_return
                mock_extend_volume.return_value = self.fake_iqn_return
                model_update = self.driver.create_cloned_volume(
                    volume, src_vref)
                self.assertEqual(self._model_update, model_update)
                self.assertFalse(self.driver.extend_volume.called)

    def test_create_cloned_volume_extend(self):
        src_vref = {'name': 'fake_uuid', 'size': '100'}
        volume = {'name': self.volume_name, 'size': '200'}
        mock_attrs = {'args': ['volume', 'select', volume['name'],
                               'multihost-access', 'enable']}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            with mock.patch.object(self.driver,
                                   'extend_volume') as mock_extend_volume:
                mock_eql_execute.configure_mock(**mock_attrs)
                mock_eql_execute.return_value = self.fake_iqn_return
                mock_extend_volume.return_value = self.fake_iqn_return
                cloned_vol = self.driver.create_cloned_volume(volume, src_vref)
                self.assertEqual(self._model_update, cloned_vol)
                self.assertTrue(self.driver.extend_volume.called)

    def test_delete_snapshot(self):
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name'}
        mock_attrs = {'args': ['volume', 'select', snapshot['volume_name'],
                               'snapshot', 'delete', snapshot['name']]}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            self.driver.delete_snapshot(snapshot)

    def test_delete_absent_snapshot(self):
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name'}
        mock_attrs = {'args': ['volume', 'select', snapshot['volume_name'],
                               'snapshot', 'delete', snapshot['name']]}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.side_effect = processutils.ProcessExecutionError(
                stdout='% Error ..... does not exist.\n')
            self.driver.delete_snapshot(snapshot)

    def test_extend_volume(self):
        new_size = '200'
        volume = {'name': self.volume_name, 'size': 100}
        mock_attrs = {'args': ['volume', 'select', volume['name'],
                               'size', "%sG" % new_size]}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            self.driver.extend_volume(volume, new_size)

    def test_get_volume_info(self):
        attrs = ('volume', 'select', self.volume, 'show')
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.return_value = self.fake_volume_output
            data = self.driver._get_volume_info(self.volume)
            mock_eql_execute.assert_called_with(*attrs)
            self.assertEqual(self.fake_volume_info, data)

    def test_get_volume_info_negative(self):
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.side_effect = processutils.ProcessExecutionError(
                stdout='% Error ..... does not exist.\n')
            self.assertRaises(exception.ManageExistingInvalidReference,
                              self.driver._get_volume_info, self.volume_name)

    def test_manage_existing(self):
        ref = {'source-name': self.volume_name}
        attrs = ('volume', 'select', self.volume_name,
                 'multihost-access', 'enable')
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            with mock.patch.object(self.driver,
                                   '_get_volume_info') as mock_volume_info:
                mock_volume_info.return_value = self.fake_volume_info
                mock_eql_execute.return_value = self.fake_iqn_return
                model_update = self.driver.manage_existing(self.volume, ref)
                mock_eql_execute.assert_called_with(*attrs)
                self.assertEqual(self._model_update, model_update)

    def test_manage_existing_invalid_ref(self):
        ref = {}
        self.assertRaises(exception.InvalidInput,
                          self.driver.manage_existing, self.volume, ref)

    def test_manage_existing_get_size(self):
        ref = {'source-name': self.volume_name}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.return_value = self.fake_volume_output
            size = self.driver.manage_existing_get_size(self.volume, ref)
            self.assertEqual(float('5.0'), size)

    def test_manage_existing_get_size_invalid_ref(self):
        """Error on manage with invalid reference."""
        ref = {}
        self.assertRaises(exception.InvalidInput,
                          self.driver.manage_existing_get_size,
                          self.volume, ref)

    def test_unmanage(self):
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.return_value = None
            self.driver.unmanage(self.volume)

    def test_initialize_connection(self):
        volume = {'name': self.volume_name}
        mock_attrs = {'args': ['volume', 'select', volume['name'], 'access',
                               'create', 'initiator',
                               self.connector['initiator'],
                               'authmethod', 'chap',
                               'username',
                               self.configuration.chap_username]}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            with mock.patch.object(self.driver,
                                   '_get_iscsi_properties') as mock_iscsi:
                mock_eql_execute.configure_mock(**mock_attrs)
                mock_iscsi.return_value = self.properties
                iscsi_properties = self.driver.initialize_connection(
                    volume, self.connector)
                self.assertEqual(self._fake_get_iscsi_properties(volume),
                                 iscsi_properties['data'])
                self.assertTrue(iscsi_properties['data']['discard'])

    def test_terminate_connection(self):
        def my_side_effect(*args, **kwargs):
            if args[4] == 'show':
                return self.access_record_output
            else:
                return ''
        volume = {'name': self.volume_name}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.side_effect = my_side_effect
            self.driver.terminate_connection(volume, self.connector)

    def test_get_access_record(self):
        attrs = ('volume', 'select', self.volume['name'], 'access', 'show')
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.return_value = self.access_record_output
            data = self.driver._get_access_record(self.volume, self.connector)
            mock_eql_execute.assert_called_with(*attrs)
            self.assertEqual(self.fake_access_id, data)

    def test_get_access_record_negative(self):
        attrs = ('volume', 'select', self.volume['name'], 'access', 'show')
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.return_value = []
            data = self.driver._get_access_record(self.volume, self.connector)
            mock_eql_execute.assert_called_with(*attrs)
            self.assertIsNone(data)

    def test_do_setup(self):
        fake_group_ip = '10.1.2.3'

        def my_side_effect(*args, **kwargs):
            if args[0] == 'grpparams':
                return ['Group-Ipaddress: %s' % fake_group_ip]
            else:
                return ''

        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.side_effect = my_side_effect
            self.driver.do_setup(self._context)
            self.assertEqual(fake_group_ip, self.driver._group_ip)

    def test_update_volume_stats_thin(self):
        mock_attrs = {'args': ['pool', 'select',
                               self.configuration.eqlx_pool, 'show']}
        self.configuration.san_thin_provision = True
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.return_value = self.driver_stats_output
            self.driver._update_volume_stats()
            self.assert_volume_stats(self.driver._stats)

    def test_update_volume_stats_thick(self):
        mock_attrs = {'args': ['pool', 'select',
                               self.configuration.eqlx_pool, 'show']}
        self.configuration.san_thin_provision = False
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.return_value = self.driver_stats_output
            self.driver._update_volume_stats()
            self.assert_volume_stats(self.driver._stats)

    def test_get_volume_stats_thin(self):
        mock_attrs = {'args': ['pool', 'select',
                               self.configuration.eqlx_pool, 'show']}
        self.configuration.san_thin_provision = True
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.return_value = self.driver_stats_output
            stats = self.driver.get_volume_stats(refresh=True)
            self.assert_volume_stats(stats)

    def test_get_volume_stats_thick(self):
        mock_attrs = {'args': ['pool', 'select',
                               self.configuration.eqlx_pool, 'show']}
        self.configuration.san_thin_provision = False
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.return_value = self.driver_stats_output
            stats = self.driver.get_volume_stats(refresh=True)
            self.assert_volume_stats(stats)

    def assert_volume_stats(self, stats):
            thin_enabled = self.configuration.san_thin_provision
            self.assertEqual(float('111.0'), stats['total_capacity_gb'])
            self.assertEqual(float('11.0'), stats['free_capacity_gb'])
            self.assertEqual(100, stats['total_volumes'])

            if thin_enabled:
                self.assertEqual(80.0, stats['provisioned_capacity_gb'])
            else:
                space = stats['total_capacity_gb'] - stats['free_capacity_gb']
                self.assertEqual(space, stats['provisioned_capacity_gb'])

            self.assertEqual(thin_enabled, stats['thin_provisioning_support'])
            self.assertEqual(not thin_enabled,
                             stats['thick_provisioning_support'])
            self.assertEqual('Dell EMC', stats['vendor_name'])
            self.assertFalse(stats['multiattach'])

    def test_get_space_in_gb(self):
        self.assertEqual(123.0, self.driver._get_space_in_gb('123.0GB'))
        self.assertEqual(124.0, self.driver._get_space_in_gb('123.5GB'))
        self.assertEqual(123.0 * 1024, self.driver._get_space_in_gb('123.0TB'))
        self.assertEqual(1.0, self.driver._get_space_in_gb('1024.0MB'))
        self.assertEqual(2.0, self.driver._get_space_in_gb('1536.0MB'))

    def test_get_output(self):

        def _fake_recv(ignore_arg):
            return '%s> ' % self.configuration.eqlx_group_name

        chan = mock.Mock(paramiko.Channel)
        mock_recv = self.mock_object(chan, 'recv')
        mock_recv.return_value = '%s> ' % self.configuration.eqlx_group_name
        self.assertEqual([_fake_recv(None)], self.driver._get_output(chan))

    def test_get_prefixed_value(self):
        lines = ['Line1 passed', 'Line1 failed']
        prefix = ['Line1', 'Line2']
        expected_output = [' passed', None]
        self.assertEqual(expected_output[0],
                         self.driver._get_prefixed_value(lines, prefix[0]))
        self.assertEqual(expected_output[1],
                         self.driver._get_prefixed_value(lines, prefix[1]))

    def test_ssh_execute(self):
        ssh = mock.Mock(paramiko.SSHClient)
        chan = mock.Mock(paramiko.Channel)
        transport = mock.Mock(paramiko.Transport)
        mock_get_output = self.mock_object(self.driver, '_get_output')
        self.mock_object(chan, 'invoke_shell')
        expected_output = ['NoError: test run']
        mock_get_output.return_value = expected_output
        ssh.get_transport.return_value = transport
        transport.open_session.return_value = chan
        chan.invoke_shell()
        chan.send('stty columns 255' + '\r')
        chan.send(self.cmd + '\r')
        chan.close()
        self.assertEqual(expected_output,
                         self.driver._ssh_execute(ssh, self.cmd))

    def test_ssh_execute_error(self):
        self.mock_object(self.driver, '_ssh_execute',
                         side_effect=processutils.ProcessExecutionError)
        ssh = mock.Mock(paramiko.SSHClient)
        chan = mock.Mock(paramiko.Channel)
        transport = mock.Mock(paramiko.Transport)
        mock_get_output = self.mock_object(self.driver, '_get_output')
        self.mock_object(ssh, 'get_transport')
        self.mock_object(chan, 'invoke_shell')
        expected_output = ['Error: test run', '% Error']
        mock_get_output.return_value = expected_output
        ssh.get_transport().return_value = transport
        transport.open_session.return_value = chan
        chan.invoke_shell()
        chan.send('stty columns 255' + '\r')
        chan.send(self.cmd + '\r')
        chan.close()
        self.assertRaises(processutils.ProcessExecutionError,
                          self.driver._ssh_execute, ssh, self.cmd)

    @mock.patch.object(greenthread, 'sleep')
    def test_ensure_retries(self, _gt_sleep):
        num_attempts = 3
        self.driver.configuration.eqlx_cli_max_retries = num_attempts
        self.mock_object(self.driver, '_ssh_execute',
                         side_effect=exception.VolumeBackendAPIException(
                             "some error"))
        # mocks for calls in _run_ssh
        self.mock_object(utils, 'check_ssh_injection')
        self.mock_object(ssh_utils, 'SSHPool')

        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)
        self.driver.sshpool = mock.Mock(return_value=sshpool)
        ssh = mock.Mock(paramiko.SSHClient)
        self.driver.sshpool.item().__enter__ = mock.Mock(return_value=ssh)
        self.driver.sshpool.item().__exit__ = mock.Mock(return_value=False)
        # now call the execute
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._eql_execute, "fake command")
        self.assertEqual(num_attempts + 1,
                         self.driver._ssh_execute.call_count)

    @mock.patch.object(greenthread, 'sleep')
    def test_ensure_connection_retries(self, _gt_sleep):
        num_attempts = 3
        self.driver.configuration.eqlx_cli_max_retries = num_attempts
        self.mock_object(self.driver, '_ssh_execute',
                         side_effect=processutils.ProcessExecutionError(
                             stdout='% Error ... some error.\n'))
        # mocks for calls in _run_ssh
        self.mock_object(utils, 'check_ssh_injection')
        self.mock_object(ssh_utils, 'SSHPool')

        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)
        self.driver.sshpool = mock.Mock(return_value=sshpool)
        ssh = mock.Mock(paramiko.SSHClient)
        self.driver.sshpool.item().__enter__ = mock.Mock(return_value=ssh)
        self.driver.sshpool.item().__exit__ = mock.Mock(return_value=False)
        # now call the execute
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._eql_execute, "fake command")
        self.assertEqual(num_attempts + 1,
                         self.driver._ssh_execute.call_count)

    @unittest.skip("Skip until bug #1578986 is fixed")
    @mock.patch.object(greenthread, 'sleep')
    def test_ensure_retries_on_channel_timeout(self, _gt_sleep):
        num_attempts = 3
        self.driver.configuration.eqlx_cli_max_retries = num_attempts

        # mocks for calls and objects in _run_ssh
        self.mock_object(utils, 'check_ssh_injection')
        self.mock_object(ssh_utils, 'SSHPool')

        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)
        self.driver.sshpool = mock.Mock(return_value=sshpool)
        ssh = mock.Mock(paramiko.SSHClient)
        self.driver.sshpool.item().__enter__ = mock.Mock(return_value=ssh)
        self.driver.sshpool.item().__exit__ = mock.Mock(return_value=False)
        # mocks for _ssh_execute and _get_output
        self.mock_object(self.driver, '_get_output',
                         side_effect=exception.VolumeBackendAPIException(
                             "some error"))
        # now call the execute
        with mock.patch('sys.stderr', new=six.StringIO()):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver._eql_execute, "fake command")

        self.assertEqual(num_attempts + 1, self.driver._get_output.call_count)

    @unittest.skip("Skip until bug #1578986 is fixed")
    def test_with_timeout(self):
        @ps.with_timeout
        def no_timeout(cmd, *args, **kwargs):
            return 'no timeout'

        @ps.with_timeout
        def w_timeout(cmd, *args, **kwargs):
            time.sleep(1)

        self.assertEqual('no timeout', no_timeout('fake cmd'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          w_timeout, 'fake cmd', timeout=0.1)

    def test_local_path(self):
        self.assertRaises(NotImplementedError, self.driver.local_path, '')
