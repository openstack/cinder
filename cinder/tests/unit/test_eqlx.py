#    Copyright (c) 2013 Dell Inc.
#    Copyright 2013 OpenStack LLC
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

from eventlet import greenthread
import mock
from oslo_concurrency import processutils
from oslo_log import log as logging
import paramiko

from cinder import context
from cinder import exception
from cinder import ssh_utils
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers import eqlx

LOG = logging.getLogger(__name__)


class DellEQLSanISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(DellEQLSanISCSIDriverTestCase, self).setUp()
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
        self.configuration.eqlx_cli_timeout = 30
        self.configuration.eqlx_cli_max_retries = 5

        self.configuration.eqlx_use_chap = False
        self.configuration.use_chap_auth = True
        self.configuration.chap_username = 'admin'
        self.configuration.chap_password = 'password'

        self.cmd = 'this is dummy command'
        self._context = context.get_admin_context()
        self.driver = eqlx.DellEQLSanISCSIDriver(
            configuration=self.configuration)
        self.volume_name = "fakevolume"
        self.volid = "fakeid"
        self.connector = {
            'ip': '10.0.0.2',
            'initiator': 'iqn.1993-08.org.debian:01:2227dab76162',
            'host': 'fakehost'}
        self.access_record_output = [
            "ID  Initiator       Ipaddress     AuthMethod UserName   Apply-To",
            "--- --------------- ------------- ---------- ---------- --------",
            "1   iqn.1993-08.org.debian:01:222 *.*.*.*       none        both",
            "       7dab76162"]

        self.fake_iqn = 'iqn.2003-10.com.equallogic:group01:25366:fakev'
        self.fake_iqn_return = ['iSCSI target name is %s.' % self.fake_iqn]
        self.driver._group_ip = '10.0.1.6'
        self.properties = {
            'target_discoverd': True,
            'target_portal': '%s:3260' % self.driver._group_ip,
            'target_iqn': self.fake_iqn,
            'volume_id': 1}
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
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name'}
        volume = {'name': self.volume_name}
        mock_attrs = {'args': ['volume', 'select', snapshot['volume_name'],
                               'snapshot', 'select', snapshot['name'],
                               'clone', volume['name']]}

        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.return_value = self.fake_iqn_return
            model_update = self.driver.create_volume_from_snapshot(volume,
                                                                   snapshot)
            self.assertEqual(self._model_update, model_update)

    def test_create_cloned_volume(self):
        src_vref = {'name': 'fake_uuid'}
        volume = {'name': self.volume_name}
        mock_attrs = {'args': ['volume', 'select', volume['name'],
                               'multihost-access', 'enable']}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.return_value = self.fake_iqn_return
            model_update = self.driver.create_cloned_volume(volume, src_vref)
            self.assertEqual(self._model_update, model_update)

    def test_delete_snapshot(self):
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name'}
        mock_attrs = {'args': ['volume', 'select', snapshot['volume_name'],
                               'snapshot', 'delete', snapshot['name']]}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
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
            self.assertEqual(self.driver._group_ip, fake_group_ip)

    def test_update_volume_stats(self):
        mock_attrs = {'args': ['pool', 'select',
                               self.configuration.eqlx_pool, 'show']}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.return_value = ['TotalCapacity: 111GB',
                                             'FreeSpace: 11GB']
            self.driver._update_volume_stats()
            self.assertEqual(111.0, self.driver._stats['total_capacity_gb'])
            self.assertEqual(11.0, self.driver._stats['free_capacity_gb'])

    def test_get_volume_stats(self):
        mock_attrs = {'args': ['pool', 'select',
                               self.configuration.eqlx_pool, 'show']}
        with mock.patch.object(self.driver,
                               '_eql_execute') as mock_eql_execute:
            mock_eql_execute.configure_mock(**mock_attrs)
            mock_eql_execute.return_value = ['TotalCapacity: 111GB',
                                             'FreeSpace: 11GB']
            stats = self.driver.get_volume_stats(refresh=True)
            self.assertEqual(float('111.0'), stats['total_capacity_gb'])
            self.assertEqual(float('11.0'), stats['free_capacity_gb'])
            self.assertEqual('Dell', stats['vendor_name'])

    def test_get_space_in_gb(self):
        self.assertEqual(123.0, self.driver._get_space_in_gb('123.0GB'))
        self.assertEqual(123.0 * 1024, self.driver._get_space_in_gb('123.0TB'))
        self.assertEqual(1.0, self.driver._get_space_in_gb('1024.0MB'))

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
                         mock.Mock(side_effect=exception.
                                   VolumeBackendAPIException("some error")))
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
                         mock.Mock(side_effect=exception.
                                   VolumeBackendAPIException("some error")))
        # now call the execute
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._eql_execute, "fake command")
        self.assertEqual(num_attempts + 1, self.driver._get_output.call_count)

    def test_with_timeout(self):
        @eqlx.with_timeout
        def no_timeout(cmd, *args, **kwargs):
            return 'no timeout'

        @eqlx.with_timeout
        def w_timeout(cmd, *args, **kwargs):
            time.sleep(1)

        self.assertEqual(no_timeout('fake cmd'), 'no timeout')
        self.assertRaises(exception.VolumeBackendAPIException,
                          w_timeout, 'fake cmd', timeout=0.1)

    def test_local_path(self):
        self.assertRaises(NotImplementedError, self.driver.local_path, '')
