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

import mock
import paramiko
import uuid

from cinder import exception
from cinder import ssh_utils
from cinder import test


class FakeSock(object):
    def settimeout(self, timeout):
        pass


class FakeTransport(object):

    def __init__(self):
        self.active = True
        self.sock = FakeSock()

    def set_keepalive(self, timeout):
        pass

    def is_active(self):
        return self.active


class FakeSSHClient(object):

    def __init__(self):
        self.id = uuid.uuid4()
        self.transport = FakeTransport()

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def load_system_host_keys(self):
        self.system_host_keys = 'system_host_keys'

    def load_host_keys(self, hosts_key_file):
        self.hosts_key_file = hosts_key_file

    def connect(self, ip, port=22, username=None, password=None,
                pkey=None, timeout=10):
        pass

    def get_transport(self):
        return self.transport

    def get_policy(self):
        return self.policy

    def get_host_keys(self):
        return '127.0.0.1 ssh-rsa deadbeef'

    def close(self):
        pass

    def __call__(self, *args, **kwargs):
        pass


class SSHPoolTestCase(test.TestCase):
    """Unit test for SSH Connection Pool."""
    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_sshpool_remove(self, mock_isfile, mock_sshclient, mock_open):
        ssh_to_remove = mock.MagicMock()
        mock_sshclient.side_effect = [mock.MagicMock(),
                                      ssh_to_remove, mock.MagicMock()]
        self.override_config('ssh_hosts_key_file', 'dummy')
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=3,
                                    max_size=3)
        self.assertIn(ssh_to_remove, list(sshpool.free_items))
        sshpool.remove(ssh_to_remove)
        self.assertNotIn(ssh_to_remove, list(sshpool.free_items))

    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_sshpool_remove_object_not_in_pool(self, mock_isfile,
                                               mock_sshclient, mock_open):
        # create an SSH Client that is not a part of sshpool.
        ssh_to_remove = mock.MagicMock()
        mock_sshclient.side_effect = [mock.MagicMock(), mock.MagicMock()]

        self.override_config('ssh_hosts_key_file', 'dummy')
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=2,
                                    max_size=2)
        listBefore = list(sshpool.free_items)
        self.assertNotIn(ssh_to_remove, listBefore)
        sshpool.remove(ssh_to_remove)
        self.assertEqual(listBefore, list(sshpool.free_items))

    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_ssh_default_hosts_key_file(self, mock_isfile, mock_sshclient,
                                        mock_open):
        mock_ssh = mock.MagicMock()
        mock_sshclient.return_value = mock_ssh
        self.override_config('ssh_hosts_key_file',
                             '/var/lib/cinder/ssh_known_hosts')

        # create with customized setting
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)

        host_key_files = sshpool.hosts_key_file

        self.assertEqual('/var/lib/cinder/ssh_known_hosts', host_key_files)

        mock_ssh.load_host_keys.assert_called_once_with(
            '/var/lib/cinder/ssh_known_hosts')

    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_ssh_host_key_file_kwargs(self, mock_isfile, mock_sshclient,
                                      mock_open):
        mock_ssh = mock.MagicMock()
        mock_sshclient.return_value = mock_ssh
        self.override_config('ssh_hosts_key_file',
                             '/var/lib/cinder/ssh_known_hosts')

        # create with customized setting
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1,
                                    hosts_key_file='dummy_host_keyfile')

        host_key_files = sshpool.hosts_key_file

        self.assertIn('dummy_host_keyfile', host_key_files)
        self.assertIn('/var/lib/cinder/ssh_known_hosts', host_key_files)

        expected = [
            mock.call.load_host_keys('dummy_host_keyfile'),
            mock.call.load_host_keys('/var/lib/cinder/ssh_known_hosts')]

        mock_ssh.assert_has_calls(expected, any_order=True)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('paramiko.RSAKey.from_private_key_file')
    @mock.patch('paramiko.SSHClient')
    def test_single_ssh_connect(self, mock_sshclient, mock_pkey, mock_isfile,
                                mock_open):
        self.override_config(
            'ssh_hosts_key_file', '/var/lib/cinder/ssh_known_hosts')

        # create with password
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)
        with sshpool.item() as ssh:
            first_id = ssh.id

        with sshpool.item() as ssh:
            second_id = ssh.id

        self.assertEqual(first_id, second_id)
        self.assertEqual(1, mock_sshclient.return_value.connect.call_count)

        # create with private key
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    privatekey="test",
                                    min_size=1,
                                    max_size=1)
        self.assertEqual(2, mock_sshclient.return_value.connect.call_count)

        # attempt to create with no password or private key
        self.assertRaises(paramiko.SSHException,
                          ssh_utils.SSHPool,
                          "127.0.0.1", 22, 10,
                          "test",
                          min_size=1,
                          max_size=1)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    def test_closed_reopened_ssh_connections(self, mock_sshclient, mock_open):
        mock_sshclient.return_value = FakeSSHClient()
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=4)
        with sshpool.item() as ssh:
            mock_sshclient.reset_mock()
            first_id = ssh.id

        with sshpool.item() as ssh:
            second_id = ssh.id
            ssh.get_transport().active = False
            sshpool.remove(ssh)

        self.assertEqual(first_id, second_id)

        # create a new client
        mock_sshclient.return_value = FakeSSHClient()
        with sshpool.item() as ssh:
            third_id = ssh.id

        self.assertNotEqual(first_id, third_id)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    def test_missing_ssh_hosts_key_config(self, mock_sshclient, mock_open):
        mock_sshclient.return_value = FakeSSHClient()
        self.override_config('ssh_hosts_key_file', None)
        # create with password
        self.assertRaises(exception.ParameterNotFound,
                          ssh_utils.SSHPool,
                          "127.0.0.1", 22, 10,
                          "test",
                          password="test",
                          min_size=1,
                          max_size=1)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    def test_create_default_known_hosts_file(self, mock_sshclient,
                                             mock_open):
        mock_sshclient.return_value = FakeSSHClient()

        self.flags(state_path='/var/lib/cinder',
                   ssh_hosts_key_file='/var/lib/cinder/ssh_known_hosts')

        default_file = '/var/lib/cinder/ssh_known_hosts'

        ssh_pool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                     "test",
                                     password="test",
                                     min_size=1,
                                     max_size=1)

        with ssh_pool.item() as ssh:
            mock_open.assert_called_once_with(default_file, 'a')
            ssh_pool.remove(ssh)

    @mock.patch('os.path.isfile', return_value=False)
    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    def test_ssh_missing_hosts_key_file(self, mock_sshclient, mock_open,
                                        mock_isfile):
        mock_sshclient.return_value = FakeSSHClient()

        self.flags(state_path='/var/lib/cinder',
                   ssh_hosts_key_file='/tmp/blah')

        self.assertRaises(exception.InvalidInput,
                          ssh_utils.SSHPool,
                          "127.0.0.1", 22, 10,
                          "test",
                          password="test",
                          min_size=1,
                          max_size=1)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_ssh_strict_host_key_policy(self, mock_isfile, mock_sshclient,
                                        mock_open):
        mock_sshclient.return_value = FakeSSHClient()

        self.flags(strict_ssh_host_key_policy=True,
                   ssh_hosts_key_file='/var/lib/cinder/ssh_known_hosts')

        # create with customized setting
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)

        with sshpool.item() as ssh:
            self.assertIsInstance(ssh.get_policy(),
                                  paramiko.RejectPolicy)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('paramiko.SSHClient')
    @mock.patch('os.path.isfile', return_value=True)
    def test_ssh_not_strict_host_key_policy(self, mock_isfile, mock_sshclient,
                                            mock_open):
        mock_sshclient.return_value = FakeSSHClient()

        self.override_config('strict_ssh_host_key_policy', False)

        # create with customized setting
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)

        with sshpool.item() as ssh:
            self.assertIsInstance(ssh.get_policy(),
                                  paramiko.AutoAddPolicy)

    @mock.patch('paramiko.SSHClient')
    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.path.isfile', return_value=False)
    def test_ssh_timeout(self, mock_isfile, mock_open, mock_sshclient):
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=1,
                                    max_size=1)
        self.assertEqual(1, sshpool.current_size)
        conn = sshpool.get()
        conn.connect = mock.MagicMock()
        # create failed due to time out
        conn.connect.side_effect = paramiko.SSHException("time out")
        mock_transport = mock.MagicMock()
        conn.get_transport.return_value = mock_transport
        # connection is down
        mock_transport.is_active.return_value = False
        sshpool.put(conn)
        self.assertRaises(paramiko.SSHException,
                          sshpool.get)
        self.assertEqual(0, sshpool.current_size)

    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('paramiko.RSAKey.from_private_key_file')
    @mock.patch('paramiko.SSHClient')
    def test_ssh_put(self, mock_sshclient, mock_pkey, mock_isfile,
                     mock_open):
        self.override_config(
            'ssh_hosts_key_file', '/var/lib/cinder/ssh_known_hosts')

        fake_close = mock.MagicMock()
        fake = FakeSSHClient()
        fake.close = fake_close
        mock_sshclient.return_value = fake

        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=5,
                                    max_size=5)
        self.assertEqual(5, sshpool.current_size)
        with sshpool.item():
            pass
        self.assertEqual(5, sshpool.current_size)
        sshpool.resize(4)
        with sshpool.item():
            pass
        self.assertEqual(4, sshpool.current_size)
        fake_close.asssert_called_once_with(mock.call())
        fake_close.reset_mock()
        sshpool.resize(3)
        with sshpool.item():
            pass
        self.assertEqual(3, sshpool.current_size)
        fake_close.asssert_called_once_with(mock.call())

    @mock.patch('six.moves.builtins.open')
    @mock.patch('os.path.isfile', return_value=True)
    @mock.patch('paramiko.RSAKey.from_private_key_file')
    @mock.patch('paramiko.SSHClient')
    def test_ssh_destructor(self, mock_sshclient, mock_pkey, mock_isfile,
                            mock_open):
        self.override_config(
            'ssh_hosts_key_file', '/var/lib/cinder/ssh_known_hosts')

        fake_close = mock.MagicMock()
        fake = FakeSSHClient()
        fake.close = fake_close
        mock_sshclient.return_value = fake

        # create with password
        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=5,
                                    max_size=5)
        self.assertEqual(5, sshpool.current_size)
        close_expect_calls = [mock.call(), mock.call(), mock.call(),
                              mock.call(), mock.call()]

        sshpool = ssh_utils.SSHPool("127.0.0.1", 22, 10,
                                    "test",
                                    password="test",
                                    min_size=5,
                                    max_size=5)
        self.assertEqual(fake_close.mock_calls, close_expect_calls)
        sshpool = None
        self.assertEqual(fake_close.mock_calls, close_expect_calls +
                         close_expect_calls)
