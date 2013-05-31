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

import mox
import paramiko

from cinder import context
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers import eqlx


LOG = logging.getLogger(__name__)


class DellEQLSanISCSIDriverTestCase(test.TestCase):

    def setUp(self):
        super(DellEQLSanISCSIDriverTestCase, self).setUp()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.append_config_values(mox.IgnoreArg())
        self.configuration.san_is_local = False
        self.configuration.san_ip = "10.0.0.1"
        self.configuration.san_login = "foo"
        self.configuration.san_password = "bar"
        self.configuration.san_ssh_port = 16022
        self.configuration.san_thin_provision = True
        self.configuration.eqlx_pool = 'non-default'
        self.configuration.eqlx_use_chap = True
        self.configuration.eqlx_group_name = 'group-0'
        self.configuration.eqlx_cli_timeout = 30
        self.configuration.eqlx_cli_max_retries = 5
        self.configuration.eqlx_chap_login = 'admin'
        self.configuration.eqlx_chap_password = 'password'
        self.configuration.volume_name_template = 'volume_%s'
        self._context = context.get_admin_context()
        self.driver = eqlx.DellEQLSanISCSIDriver(
            configuration=self.configuration)
        self.volume_name = "fakevolume"
        self.volid = "fakeid"
        self.connector = {'ip': '10.0.0.2',
                          'initiator': 'iqn.1993-08.org.debian:01:222',
                          'host': 'fakehost'}
        self.fake_iqn = 'iqn.2003-10.com.equallogic:group01:25366:fakev'
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
                self.configuration.eqlx_chap_login,
                self.configuration.eqlx_chap_password)
        }

    def _fake_get_iscsi_properties(self, volume):
        return self.properties

    def test_create_volume(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        volume = {'name': self.volume_name, 'size': 1}
        self.driver._eql_execute('volume', 'create', volume['name'],
                                 "%sG" % (volume['size']), 'pool',
                                 self.configuration.eqlx_pool,
                                 'thin-provision').\
            AndReturn(['iSCSI target name is %s.' % self.fake_iqn])
        self.mox.ReplayAll()
        model_update = self.driver.create_volume(volume)
        self.assertEqual(model_update, self._model_update)

    def test_delete_volume(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        volume = {'name': self.volume_name, 'size': 1}
        self.driver._eql_execute('volume', 'select', volume['name'], 'show')
        self.driver._eql_execute('volume', 'select', volume['name'], 'offline')
        self.driver._eql_execute('volume', 'delete', volume['name'])
        self.mox.ReplayAll()
        self.driver.delete_volume(volume)

    def test_delete_absent_volume(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        volume = {'name': self.volume_name, 'size': 1, 'id': self.volid}
        self.driver._eql_execute('volume', 'select', volume['name'], 'show').\
            AndRaise(processutils.ProcessExecutionError(
                stdout='% Error ..... does not exist.\n'))
        self.mox.ReplayAll()
        self.driver.delete_volume(volume)

    def test_ensure_export(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        volume = {'name': self.volume_name, 'size': 1}
        self.driver._eql_execute('volume', 'select', volume['name'], 'show')
        self.mox.ReplayAll()
        self.driver.ensure_export({}, volume)

    def test_create_snapshot(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name'}
        snap_name = 'fake_snap_name'
        self.driver._eql_execute('volume', 'select', snapshot['volume_name'],
                                 'snapshot', 'create-now').\
            AndReturn(['Snapshot name is %s' % snap_name])
        self.driver._eql_execute('volume', 'select', snapshot['volume_name'],
                                 'snapshot', 'rename', snap_name,
                                 snapshot['name'])
        self.mox.ReplayAll()
        self.driver.create_snapshot(snapshot)

    def test_create_volume_from_snapshot(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name'}
        volume = {'name': self.volume_name}
        self.driver._eql_execute('volume', 'select', snapshot['volume_name'],
                                 'snapshot', 'select', snapshot['name'],
                                 'clone', volume['name']).\
            AndReturn(['iSCSI target name is %s.' % self.fake_iqn])
        self.mox.ReplayAll()
        model_update = self.driver.create_volume_from_snapshot(volume,
                                                               snapshot)
        self.assertEqual(model_update, self._model_update)

    def test_create_cloned_volume(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        src_vref = {'id': 'fake_uuid'}
        volume = {'name': self.volume_name}
        src_volume_name = self.configuration.\
            volume_name_template % src_vref['id']
        self.driver._eql_execute('volume', 'select', src_volume_name, 'clone',
                                 volume['name']).\
            AndReturn(['iSCSI target name is %s.' % self.fake_iqn])
        self.mox.ReplayAll()
        model_update = self.driver.create_cloned_volume(volume, src_vref)
        self.assertEqual(model_update, self._model_update)

    def test_delete_snapshot(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        snapshot = {'name': 'fakesnap', 'volume_name': 'fakevolume_name'}
        self.driver._eql_execute('volume', 'select', snapshot['volume_name'],
                                 'snapshot', 'delete', snapshot['name'])
        self.mox.ReplayAll()
        self.driver.delete_snapshot(snapshot)

    def test_initialize_connection(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        volume = {'name': self.volume_name}
        self.stubs.Set(self.driver, "_get_iscsi_properties",
                       self._fake_get_iscsi_properties)
        self.driver._eql_execute('volume', 'select', volume['name'], 'access',
                                 'create', 'initiator',
                                 self.connector['initiator'],
                                 'authmethod chap',
                                 'username',
                                 self.configuration.eqlx_chap_login)
        self.mox.ReplayAll()
        iscsi_properties = self.driver.initialize_connection(volume,
                                                             self.connector)
        self.assertEqual(iscsi_properties['data'],
                         self._fake_get_iscsi_properties(volume))

    def test_terminate_connection(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        volume = {'name': self.volume_name}
        self.driver._eql_execute('volume', 'select', volume['name'], 'access',
                                 'delete', '1')
        self.mox.ReplayAll()
        self.driver.terminate_connection(volume, self.connector)

    def test_do_setup(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        fake_group_ip = '10.1.2.3'
        for feature in ('confirmation', 'paging', 'events', 'formatoutput'):
            self.driver._eql_execute('cli-settings', feature, 'off')
        self.driver._eql_execute('grpparams', 'show').\
            AndReturn(['Group-Ipaddress: %s' % fake_group_ip])
        self.mox.ReplayAll()
        self.driver.do_setup(self._context)
        self.assertEqual(fake_group_ip, self.driver._group_ip)

    def test_update_volume_status(self):
        self.driver._eql_execute = self.mox.\
            CreateMock(self.driver._eql_execute)
        self.driver._eql_execute('pool', 'select',
                                 self.configuration.eqlx_pool, 'show').\
            AndReturn(['TotalCapacity: 111GB', 'FreeSpace: 11GB'])
        self.mox.ReplayAll()
        self.driver._update_volume_status()
        self.assertEqual(self.driver._stats['total_capacity_gb'], 111.0)
        self.assertEqual(self.driver._stats['free_capacity_gb'], 11.0)

    def test_get_space_in_gb(self):
        self.assertEqual(self.driver._get_space_in_gb('123.0GB'), 123.0)
        self.assertEqual(self.driver._get_space_in_gb('123.0TB'), 123.0 * 1024)
        self.assertEqual(self.driver._get_space_in_gb('1024.0MB'), 1.0)

    def test_get_output(self):

        def _fake_recv(ignore_arg):
            return '%s> ' % self.configuration.eqlx_group_name

        chan = self.mox.CreateMock(paramiko.Channel)
        self.stubs.Set(chan, "recv", _fake_recv)
        self.assertEqual(self.driver._get_output(chan), [_fake_recv(None)])

    def test_get_prefixed_value(self):
        lines = ['Line1 passed', 'Line1 failed']
        prefix = ['Line1', 'Line2']
        expected_output = [' passed', None]
        self.assertEqual(self.driver._get_prefixed_value(lines, prefix[0]),
                         expected_output[0])
        self.assertEqual(self.driver._get_prefixed_value(lines, prefix[1]),
                         expected_output[1])

    def test_ssh_execute(self):
        ssh = self.mox.CreateMock(paramiko.SSHClient)
        chan = self.mox.CreateMock(paramiko.Channel)
        transport = self.mox.CreateMock(paramiko.Transport)
        self.mox.StubOutWithMock(self.driver, '_get_output')
        self.mox.StubOutWithMock(chan, 'invoke_shell')
        expected_output = ['NoError: test run']
        ssh.get_transport().AndReturn(transport)
        transport.open_session().AndReturn(chan)
        chan.invoke_shell()
        self.driver._get_output(chan).AndReturn(expected_output)
        cmd = 'this is dummy command'
        chan.send('stty columns 255' + '\r')
        self.driver._get_output(chan).AndReturn(expected_output)
        chan.send(cmd + '\r')
        self.driver._get_output(chan).AndReturn(expected_output)
        chan.close()
        self.mox.ReplayAll()
        self.assertEqual(self.driver._ssh_execute(ssh, cmd), expected_output)

    def test_ssh_execute_error(self):
        ssh = self.mox.CreateMock(paramiko.SSHClient)
        chan = self.mox.CreateMock(paramiko.Channel)
        transport = self.mox.CreateMock(paramiko.Transport)
        self.mox.StubOutWithMock(self.driver, '_get_output')
        self.mox.StubOutWithMock(ssh, 'get_transport')
        self.mox.StubOutWithMock(chan, 'invoke_shell')
        expected_output = ['Error: test run', '% Error']
        ssh.get_transport().AndReturn(transport)
        transport.open_session().AndReturn(chan)
        chan.invoke_shell()
        self.driver._get_output(chan).AndReturn(expected_output)
        cmd = 'this is dummy command'
        chan.send('stty columns 255' + '\r')
        self.driver._get_output(chan).AndReturn(expected_output)
        chan.send(cmd + '\r')
        self.driver._get_output(chan).AndReturn(expected_output)
        chan.close()
        self.mox.ReplayAll()
        self.assertRaises(processutils.ProcessExecutionError,
                          self.driver._ssh_execute, ssh, cmd)

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
