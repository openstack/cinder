# Copyright (c) 2015 HGST Inc
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


import mock

from oslo_concurrency import processutils

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.hgst import HGSTDriver
from cinder.volume import volume_types


class HGSTTestCase(test.TestCase):

    # Need to mock these since we use them on driver creation
    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def setUp(self, mock_ghn, mock_grnam, mock_pwnam):
        """Set up UUT and all the flags required for later fake_executes."""
        super(HGSTTestCase, self).setUp()
        self.stubs.Set(processutils, 'execute', self._fake_execute)
        self._fail_vgc_cluster = False
        self._fail_ip = False
        self._fail_network_list = False
        self._fail_domain_list = False
        self._empty_domain_list = False
        self._fail_host_storage = False
        self._fail_space_list = False
        self._fail_space_delete = False
        self._fail_set_apphosts = False
        self._fail_extend = False
        self._request_cancel = False
        self._return_blocked = 0
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.safe_get = self._fake_safe_get
        self._reset_configuration()
        self.driver = HGSTDriver(configuration=self.configuration,
                                 execute=self._fake_execute)

    def _fake_safe_get(self, value):
        """Don't throw exception on missing parameters, return None."""
        try:
            val = getattr(self.configuration, value)
        except AttributeError:
            val = None
        return val

    def _reset_configuration(self):
        """Set safe and sane values for config params."""
        self.configuration.num_volume_device_scan_tries = 1
        self.configuration.volume_dd_blocksize = '1M'
        self.configuration.volume_backend_name = 'hgst-1'
        self.configuration.hgst_storage_servers = 'stor1:gbd0,stor2:gbd0'
        self.configuration.hgst_net = 'net1'
        self.configuration.hgst_redundancy = '0'
        self.configuration.hgst_space_user = 'kane'
        self.configuration.hgst_space_group = 'xanadu'
        self.configuration.hgst_space_mode = '0777'

    def _parse_space_create(self, *cmd):
        """Eats a vgc-cluster space-create command line to a dict."""
        self.created = {'storageserver': ''}
        cmd = list(*cmd)
        while cmd:
            param = cmd.pop(0)
            if param == "-n":
                self.created['name'] = cmd.pop(0)
            elif param == "-N":
                self.created['net'] = cmd.pop(0)
            elif param == "-s":
                self.created['size'] = cmd.pop(0)
            elif param == "--redundancy":
                self.created['redundancy'] = cmd.pop(0)
            elif param == "--user":
                self.created['user'] = cmd.pop(0)
            elif param == "--user":
                self.created['user'] = cmd.pop(0)
            elif param == "--group":
                self.created['group'] = cmd.pop(0)
            elif param == "--mode":
                self.created['mode'] = cmd.pop(0)
            elif param == "-S":
                self.created['storageserver'] += cmd.pop(0) + ","
            else:
                pass

    def _parse_space_extend(self, *cmd):
        """Eats a vgc-cluster space-extend commandline to a dict."""
        self.extended = {'storageserver': ''}
        cmd = list(*cmd)
        while cmd:
            param = cmd.pop(0)
            if param == "-n":
                self.extended['name'] = cmd.pop(0)
            elif param == "-s":
                self.extended['size'] = cmd.pop(0)
            elif param == "-S":
                self.extended['storageserver'] += cmd.pop(0) + ","
            else:
                pass
        if self._fail_extend:
            raise processutils.ProcessExecutionError(exit_code=1)
        else:
            return '', ''

    def _parse_space_delete(self, *cmd):
        """Eats a vgc-cluster space-delete commandline to a dict."""
        self.deleted = {}
        cmd = list(*cmd)
        while cmd:
            param = cmd.pop(0)
            if param == "-n":
                self.deleted['name'] = cmd.pop(0)
            else:
                pass
        if self._fail_space_delete:
            raise processutils.ProcessExecutionError(exit_code=1)
        else:
            return '', ''

    def _parse_space_list(self, *cmd):
        """Eats a vgc-cluster space-list commandline to a dict."""
        json = False
        nameOnly = False
        cmd = list(*cmd)
        while cmd:
            param = cmd.pop(0)
            if param == "--json":
                json = True
            elif param == "--name-only":
                nameOnly = True
            elif param == "-n":
                pass  # Don't use the name here...
            else:
                pass
        if self._fail_space_list:
            raise processutils.ProcessExecutionError(exit_code=1)
        elif nameOnly:
            return "space1\nspace2\nvolume1\n", ''
        elif json:
            return HGST_SPACE_JSON, ''
        else:
            return '', ''

    def _parse_network_list(self, *cmd):
        """Eat a network-list command and return error or results."""
        if self._fail_network_list:
            raise processutils.ProcessExecutionError(exit_code=1)
        else:
            return NETWORK_LIST, ''

    def _parse_domain_list(self, *cmd):
        """Eat a domain-list command and return error, empty, or results."""
        if self._fail_domain_list:
            raise processutils.ProcessExecutionError(exit_code=1)
        elif self._empty_domain_list:
            return '', ''
        else:
            return "thisserver\nthatserver\nanotherserver\n", ''

    def _fake_execute(self, *cmd, **kwargs):
        """Sudo hook to catch commands to allow running on all hosts."""
        cmdlist = list(cmd)
        exe = cmdlist.pop(0)
        if exe == 'vgc-cluster':
            exe = cmdlist.pop(0)
            if exe == "request-cancel":
                self._request_cancel = True
                if self._return_blocked > 0:
                    return 'Request cancelled', ''
                else:
                    raise processutils.ProcessExecutionError(exit_code=1)
            elif self._fail_vgc_cluster:
                raise processutils.ProcessExecutionError(exit_code=1)
            elif exe == "--version":
                return "HGST Solutions V2.5.0.0.x.x.x.x.x", ''
            elif exe == "space-list":
                return self._parse_space_list(cmdlist)
            elif exe == "space-create":
                self._parse_space_create(cmdlist)
                if self._return_blocked > 0:
                    self._return_blocked = self._return_blocked - 1
                    out = "VGC_CREATE_000002\nBLOCKED\n"
                    raise processutils.ProcessExecutionError(stdout=out,
                                                             exit_code=1)
                return '', ''
            elif exe == "space-delete":
                return self._parse_space_delete(cmdlist)
            elif exe == "space-extend":
                return self._parse_space_extend(cmdlist)
            elif exe == "host-storage":
                if self._fail_host_storage:
                    raise processutils.ProcessExecutionError(exit_code=1)
                return HGST_HOST_STORAGE, ''
            elif exe == "domain-list":
                return self._parse_domain_list()
            elif exe == "network-list":
                return self._parse_network_list()
            elif exe == "space-set-apphosts":
                if self._fail_set_apphosts:
                    raise processutils.ProcessExecutionError(exit_code=1)
                return '', ''
            else:
                raise NotImplementedError
        elif exe == 'ip':
            if self._fail_ip:
                raise processutils.ProcessExecutionError(exit_code=1)
            else:
                return IP_OUTPUT, ''
        elif exe == 'dd':
            self.dd_count = -1
            for p in cmdlist:
                if 'count=' in p:
                    self.dd_count = int(p[6:])
            return DD_OUTPUT, ''
        else:
            return '', ''

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_vgc_cluster_not_present(self, mock_ghn, mock_grnam, mock_pwnam):
        """Test exception when vgc-cluster returns an error."""
        # Should pass
        self._fail_vgc_cluster = False
        self.driver.check_for_setup_error()
        # Should throw exception
        self._fail_vgc_cluster = True
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_parameter_redundancy_invalid(self, mock_ghn, mock_grnam,
                                          mock_pwnam):
        """Test when hgst_redundancy config parameter not 0 or 1."""
        # Should pass
        self.driver.check_for_setup_error()
        # Should throw exceptions
        self.configuration.hgst_redundancy = ''
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        self.configuration.hgst_redundancy = 'Fred'
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_parameter_user_invalid(self, mock_ghn, mock_grnam, mock_pwnam):
        """Test exception when hgst_space_user doesn't map to UNIX user."""
        # Should pass
        self.driver.check_for_setup_error()
        # Should throw exceptions
        mock_pwnam.side_effect = KeyError()
        self.configuration.hgst_space_user = ''
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        self.configuration.hgst_space_user = 'Fred!`'
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_parameter_group_invalid(self, mock_ghn, mock_grnam, mock_pwnam):
        """Test exception when hgst_space_group doesn't map to UNIX group."""
        # Should pass
        self.driver.check_for_setup_error()
        # Should throw exceptions
        mock_grnam.side_effect = KeyError()
        self.configuration.hgst_space_group = ''
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        self.configuration.hgst_space_group = 'Fred!`'
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_parameter_mode_invalid(self, mock_ghn, mock_grnam, mock_pwnam):
        """Test exception when mode for created spaces isn't proper format."""
        # Should pass
        self.driver.check_for_setup_error()
        # Should throw exceptions
        self.configuration.hgst_space_mode = ''
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        self.configuration.hgst_space_mode = 'Fred'
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_parameter_net_invalid(self, mock_ghn, mock_grnam, mock_pwnam):
        """Test exception when hgst_net not in the domain."""
        # Should pass
        self.driver.check_for_setup_error()
        # Should throw exceptions
        self._fail_network_list = True
        self.configuration.hgst_net = 'Fred'
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        self._fail_network_list = False

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_ip_addr_fails(self, mock_ghn, mock_grnam, mock_pwnam):
        """Test exception when IP ADDR command fails."""
        # Should pass
        self.driver.check_for_setup_error()
        # Throw exception, need to clear internal cached host in driver
        self._fail_ip = True
        self.driver._vgc_host = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_domain_list_fails(self, mock_ghn, mock_grnam, mock_pwnam):
        """Test exception when domain-list fails for the domain."""
        # Should pass
        self.driver.check_for_setup_error()
        # Throw exception, need to clear internal cached host in driver
        self._fail_domain_list = True
        self.driver._vgc_host = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_not_in_domain(self, mock_ghn, mock_grnam, mock_pwnam):
        """Test exception when Cinder host not domain member."""
        # Should pass
        self.driver.check_for_setup_error()
        # Throw exception, need to clear internal cached host in driver
        self._empty_domain_list = True
        self.driver._vgc_host = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)

    @mock.patch('pwd.getpwnam', return_value=1)
    @mock.patch('grp.getgrnam', return_value=1)
    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_parameter_storageservers_invalid(self, mock_ghn, mock_grnam,
                                              mock_pwnam):
        """Test exception when the storage servers are invalid/missing."""
        # Should pass
        self.driver.check_for_setup_error()
        # Storage_hosts missing
        self.configuration.hgst_storage_servers = ''
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        # missing a : between host and devnode
        self.configuration.hgst_storage_servers = 'stor1,stor2'
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        # missing a : between host and devnode
        self.configuration.hgst_storage_servers = 'stor1:gbd0,stor2'
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)
        # Host not in cluster
        self.configuration.hgst_storage_servers = 'stor1:gbd0'
        self._fail_host_storage = True
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.check_for_setup_error)

    def test_update_volume_stats(self):
        """Get cluster space available, should pass."""
        actual = self.driver.get_volume_stats(True)
        self.assertEqual('HGST', actual['vendor_name'])
        self.assertEqual('hgst', actual['storage_protocol'])
        self.assertEqual(90, actual['total_capacity_gb'])
        self.assertEqual(87, actual['free_capacity_gb'])
        self.assertEqual(0, actual['reserved_percentage'])

    def test_update_volume_stats_redundancy(self):
        """Get cluster space available, half-sized - 1 for mirrors."""
        self.configuration.hgst_redundancy = '1'
        actual = self.driver.get_volume_stats(True)
        self.assertEqual('HGST', actual['vendor_name'])
        self.assertEqual('hgst', actual['storage_protocol'])
        self.assertEqual(44, actual['total_capacity_gb'])
        self.assertEqual(43, actual['free_capacity_gb'])
        self.assertEqual(0, actual['reserved_percentage'])

    def test_update_volume_stats_cached(self):
        """Get cached cluster space, should not call executable."""
        self._fail_host_storage = True
        actual = self.driver.get_volume_stats(False)
        self.assertEqual('HGST', actual['vendor_name'])
        self.assertEqual('hgst', actual['storage_protocol'])
        self.assertEqual(90, actual['total_capacity_gb'])
        self.assertEqual(87, actual['free_capacity_gb'])
        self.assertEqual(0, actual['reserved_percentage'])

    def test_update_volume_stats_error(self):
        """Test that when host-storage gives an error, return unknown."""
        self._fail_host_storage = True
        actual = self.driver.get_volume_stats(True)
        self.assertEqual('HGST', actual['vendor_name'])
        self.assertEqual('hgst', actual['storage_protocol'])
        self.assertEqual('unknown', actual['total_capacity_gb'])
        self.assertEqual('unknown', actual['free_capacity_gb'])
        self.assertEqual(0, actual['reserved_percentage'])

    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_create_volume(self, mock_ghn):
        """Test volume creation, ensure appropriate size expansion/name."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10}
        ret = self.driver.create_volume(volume)
        expected = {'redundancy': '0', 'group': 'xanadu',
                    'name': 'volume10', 'mode': '0777',
                    'user': 'kane', 'net': 'net1',
                    'storageserver': 'stor1:gbd0,stor2:gbd0,',
                    'size': '12'}
        self.assertDictMatch(expected, self.created)
        # Check the returned provider, note the the provider_id is hashed
        expected_pid = {'provider_id': 'volume10'}
        self.assertDictMatch(expected_pid, ret)

    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_create_volume_name_creation_fail(self, mock_ghn):
        """Test volume creation exception when can't make a hashed name."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10}
        self._fail_space_list = True
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume, volume)

    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_create_snapshot(self, mock_ghn):
        """Test creating a snapshot, ensure full data of original copied."""
        # Now snapshot the volume and check commands
        snapshot = {'volume_name': 'volume10',
                    'volume_id': 'xxx', 'display_name': 'snap10',
                    'name': '123abc', 'volume_size': 10, 'id': '123abc',
                    'volume': {'provider_id': 'space10'}}
        ret = self.driver.create_snapshot(snapshot)
        # We must copy entier underlying storage, ~12GB, not just 10GB
        self.assertEqual(11444, self.dd_count)
        # Check space-create command
        expected = {'redundancy': '0', 'group': 'xanadu',
                    'name': snapshot['display_name'], 'mode': '0777',
                    'user': 'kane', 'net': 'net1',
                    'storageserver': 'stor1:gbd0,stor2:gbd0,',
                    'size': '12'}
        self.assertDictMatch(expected, self.created)
        # Check the returned provider
        expected_pid = {'provider_id': 'snap10'}
        self.assertDictMatch(expected_pid, ret)

    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_create_cloned_volume(self, mock_ghn):
        """Test creating a clone, ensure full size is copied from original."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        orig = {'id': '1', 'name': 'volume1', 'display_name': '',
                'volume_type_id': type_ref['id'], 'size': 10,
                'provider_id': 'space_orig'}
        clone = {'id': '2', 'name': 'clone1', 'display_name': '',
                 'volume_type_id': type_ref['id'], 'size': 10}
        pid = self.driver.create_cloned_volume(clone, orig)
        # We must copy entier underlying storage, ~12GB, not just 10GB
        self.assertEqual(11444, self.dd_count)
        # Check space-create command
        expected = {'redundancy': '0', 'group': 'xanadu',
                    'name': 'clone1', 'mode': '0777',
                    'user': 'kane', 'net': 'net1',
                    'storageserver': 'stor1:gbd0,stor2:gbd0,',
                    'size': '12'}
        self.assertDictMatch(expected, self.created)
        # Check the returned provider
        expected_pid = {'provider_id': 'clone1'}
        self.assertDictMatch(expected_pid, pid)

    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_add_cinder_apphosts_fails(self, mock_ghn):
        """Test exception when set-apphost can't connect volume to host."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        orig = {'id': '1', 'name': 'volume1', 'display_name': '',
                'volume_type_id': type_ref['id'], 'size': 10,
                'provider_id': 'space_orig'}
        clone = {'id': '2', 'name': 'clone1', 'display_name': '',
                 'volume_type_id': type_ref['id'], 'size': 10}
        self._fail_set_apphosts = True
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_cloned_volume, clone, orig)

    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_create_volume_from_snapshot(self, mock_ghn):
        """Test creating volume from snapshot, ensure full space copy."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        snap = {'id': '1', 'name': 'volume1', 'display_name': '',
                'volume_type_id': type_ref['id'], 'size': 10,
                'provider_id': 'space_orig'}
        volume = {'id': '2', 'name': 'volume2', 'display_name': '',
                  'volume_type_id': type_ref['id'], 'size': 10}
        pid = self.driver.create_volume_from_snapshot(volume, snap)
        # We must copy entier underlying storage, ~12GB, not just 10GB
        self.assertEqual(11444, self.dd_count)
        # Check space-create command
        expected = {'redundancy': '0', 'group': 'xanadu',
                    'name': 'volume2', 'mode': '0777',
                    'user': 'kane', 'net': 'net1',
                    'storageserver': 'stor1:gbd0,stor2:gbd0,',
                    'size': '12'}
        self.assertDictMatch(expected, self.created)
        # Check the returned provider
        expected_pid = {'provider_id': 'volume2'}
        self.assertDictMatch(expected_pid, pid)

    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_create_volume_blocked(self, mock_ghn):
        """Test volume creation where only initial space-create is blocked.

        This should actually pass because we are blocked byt return an error
        in request-cancel, meaning that it got unblocked before we could kill
        the space request.
        """
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10}
        self._return_blocked = 1  # Block & fail cancel => create succeeded
        ret = self.driver.create_volume(volume)
        expected = {'redundancy': '0', 'group': 'xanadu',
                    'name': 'volume10', 'mode': '0777',
                    'user': 'kane', 'net': 'net1',
                    'storageserver': 'stor1:gbd0,stor2:gbd0,',
                    'size': '12'}
        self.assertDictMatch(expected, self.created)
        # Check the returned provider
        expected_pid = {'provider_id': 'volume10'}
        self.assertDictMatch(expected_pid, ret)
        self.assertTrue(self._request_cancel)

    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_create_volume_blocked_and_fail(self, mock_ghn):
        """Test volume creation where space-create blocked permanently.

        This should fail because the initial create was blocked and the
        request-cancel succeeded, meaning the create operation never
        completed.
        """
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10}
        self._return_blocked = 2  # Block & pass cancel => create failed. :(
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume, volume)
        self.assertTrue(self._request_cancel)

    def test_delete_volume(self):
        """Test deleting existing volume, ensure proper name used."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10,
                  'provider_id': 'volume10'}
        self.driver.delete_volume(volume)
        expected = {'name': 'volume10'}
        self.assertDictMatch(expected, self.deleted)

    def test_delete_volume_failure_modes(self):
        """Test cases where space-delete fails, but OS delete is still OK."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10,
                  'provider_id': 'volume10'}
        self._fail_space_delete = True
        # This should not throw an exception, space-delete failure not problem
        self.driver.delete_volume(volume)
        self._fail_space_delete = False
        volume['provider_id'] = None
        # This should also not throw an exception
        self.driver.delete_volume(volume)

    def test_delete_snapshot(self):
        """Test deleting a snapshot, ensure proper name is removed."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        snapshot = {'id': '1', 'name': 'volume1',
                    'display_name': '',
                    'volume_type_id': type_ref['id'],
                    'size': 10,
                    'provider_id': 'snap10'}
        self.driver.delete_snapshot(snapshot)
        expected = {'name': 'snap10'}
        self.assertDictMatch(expected, self.deleted)

    def test_extend_volume(self):
        """Test extending a volume, check the size in GB vs. GiB."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10,
                  'provider_id': 'volume10'}
        self.extended = {'name': '', 'size': '0',
                         'storageserver': ''}
        self.driver.extend_volume(volume, 12)
        expected = {'name': 'volume10', 'size': '2',
                    'storageserver': 'stor1:gbd0,stor2:gbd0,'}
        self.assertDictMatch(expected, self.extended)

    def test_extend_volume_noextend(self):
        """Test extending a volume where Space does not need to be enlarged.

        Because Spaces are generated somewhat larger than the requested size
        from OpenStack due to the base10(HGST)/base2(OS) mismatch, they can
        sometimes be larger than requested from OS.  In that case a
        volume_extend may actually be a noop since the volume is already large
        enough to satisfy OS's request.
        """
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10,
                  'provider_id': 'volume10'}
        self.extended = {'name': '', 'size': '0',
                         'storageserver': ''}
        self.driver.extend_volume(volume, 10)
        expected = {'name': '', 'size': '0',
                    'storageserver': ''}
        self.assertDictMatch(expected, self.extended)

    def test_space_list_fails(self):
        """Test exception is thrown when we can't call space-list."""
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10,
                  'provider_id': 'volume10'}
        self.extended = {'name': '', 'size': '0',
                         'storageserver': ''}
        self._fail_space_list = True
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.extend_volume, volume, 12)

    def test_cli_error_not_blocked(self):
        """Test the _blocked handler's handlinf of a non-blocked error.

        The _handle_blocked handler is called on any process errors in the
        code.  If the error was not caused by a blocked command condition
        (syntax error, out of space, etc.) then it should just throw the
        exception and not try and retry the command.
        """
        ctxt = context.get_admin_context()
        extra_specs = {}
        type_ref = volume_types.create(ctxt, 'hgst-1', extra_specs)
        volume = {'id': '1', 'name': 'volume1',
                  'display_name': '',
                  'volume_type_id': type_ref['id'],
                  'size': 10,
                  'provider_id': 'volume10'}
        self.extended = {'name': '', 'size': '0',
                         'storageserver': ''}
        self._fail_extend = True
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.extend_volume, volume, 12)
        self.assertFalse(self._request_cancel)

    @mock.patch('socket.gethostbyname', return_value='123.123.123.123')
    def test_initialize_connection(self, moch_ghn):
        """Test that the connection_info for Nova makes sense."""
        volume = {'name': '123', 'provider_id': 'spacey'}
        conn = self.driver.initialize_connection(volume, None)
        expected = {'name': 'spacey', 'noremovehost': 'thisserver'}
        self.assertDictMatch(expected, conn['data'])

# Below are some command outputs we emulate
IP_OUTPUT = """
3: em2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state
    link/ether 00:25:90:d9:18:09 brd ff:ff:ff:ff:ff:ff
    inet 192.168.0.23/24 brd 192.168.0.255 scope global em2
       valid_lft forever preferred_lft forever
    inet6 fe80::225:90ff:fed9:1809/64 scope link
       valid_lft forever preferred_lft forever
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 123.123.123.123/8 scope host lo
       valid_lft forever preferred_lft forever
    inet 169.254.169.254/32 scope link lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host
       valid_lft forever preferred_lft forever
2: em1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq master
    link/ether 00:25:90:d9:18:08 brd ff:ff:ff:ff:ff:ff
    inet6 fe80::225:90ff:fed9:1808/64 scope link
       valid_lft forever preferred_lft forever
"""

HGST_HOST_STORAGE = """
{
  "hostStatus": [
    {
      "node": "tm33.virident.info",
      "up": true,
      "isManager": true,
      "cardStatus": [
        {
          "cardName": "/dev/sda3",
          "cardSerialNumber": "002f09b4037a9d521c007ee4esda3",
          "cardStatus": "Good",
          "cardStateDetails": "Normal",
          "cardActionRequired": "",
          "cardTemperatureC": 0,
          "deviceType": "Generic",
          "cardTemperatureState": "Safe",
          "partitionStatus": [
            {
              "partName": "/dev/gbd0",
              "partitionState": "READY",
              "usableCapacityBytes": 98213822464,
              "totalReadBytes": 0,
              "totalWriteBytes": 0,
              "remainingLifePCT": 100,
              "flashReservesLeftPCT": 100,
              "fmc": true,
              "vspaceCapacityAvailable": 94947041280,
              "vspaceReducedCapacityAvailable": 87194279936,
              "_partitionID": "002f09b4037a9d521c007ee4esda3:0",
              "_usedSpaceBytes": 3266781184,
              "_enabledSpaceBytes": 3266781184,
              "_disabledSpaceBytes": 0
            }
          ]
        }
      ],
      "driverStatus": {
        "vgcdriveDriverLoaded": true,
        "vhaDriverLoaded": true,
        "vcacheDriverLoaded": true,
        "vlvmDriverLoaded": true,
        "ipDataProviderLoaded": true,
        "ibDataProviderLoaded": false,
        "driverUptimeSecs": 4800,
        "rVersion": "20368.d55ec22.master"
      },
      "totalCapacityBytes": 98213822464,
      "totalUsedBytes": 3266781184,
      "totalEnabledBytes": 3266781184,
      "totalDisabledBytes": 0
    },
    {
      "node": "tm32.virident.info",
      "up": true,
      "isManager": false,
      "cardStatus": [],
      "driverStatus": {
        "vgcdriveDriverLoaded": true,
        "vhaDriverLoaded": true,
        "vcacheDriverLoaded": true,
        "vlvmDriverLoaded": true,
        "ipDataProviderLoaded": true,
        "ibDataProviderLoaded": false,
        "driverUptimeSecs": 0,
        "rVersion": "20368.d55ec22.master"
      },
      "totalCapacityBytes": 0,
      "totalUsedBytes": 0,
      "totalEnabledBytes": 0,
      "totalDisabledBytes": 0
    }
  ],
  "totalCapacityBytes": 98213822464,
  "totalUsedBytes": 3266781184,
  "totalEnabledBytes": 3266781184,
  "totalDisabledBytes": 0
}
"""

HGST_SPACE_JSON = """
{
  "resources": [
    {
      "resourceType": "vLVM-L",
      "resourceID": "vLVM-L:698cdb43-54da-863e-1699-294a080ce4db",
      "state": "OFFLINE",
      "instanceStates": {},
      "redundancy": 0,
      "sizeBytes": 12000000000,
      "name": "volume10",
      "nodes": [],
      "networks": [
        "net1"
      ],
      "components": [
        {
          "resourceType": "vLVM-S",
          "resourceID": "vLVM-S:698cdb43-54da-863e-eb10-6275f47b8ed2",
          "redundancy": 0,
          "order": 0,
          "sizeBytes": 12000000000,
          "numStripes": 1,
          "stripeSizeBytes": null,
          "name": "volume10s00",
          "state": "OFFLINE",
          "instanceStates": {},
          "components": [
            {
              "name": "volume10h00",
              "resourceType": "vHA",
              "resourceID": "vHA:3e86da54-40db-8c69-0300-0000ac10476e",
              "redundancy": 0,
              "sizeBytes": 12000000000,
              "state": "GOOD",
              "components": [
                {
                  "name": "volume10h00",
                  "vspaceType": "vHA",
                  "vspaceRole": "primary",
                  "storageObjectID": "vHA:3e86da54-40db-8c69--18130019e486",
                  "state": "Disconnected (DCS)",
                  "node": "tm33.virident.info",
                  "partName": "/dev/gbd0"
                }
              ],
              "crState": "GOOD"
            },
            {
              "name": "volume10v00",
              "resourceType": "vShare",
              "resourceID": "vShare:3f86da54-41db-8c69-0300-ecf4bbcc14cc",
              "redundancy": 0,
              "order": 0,
              "sizeBytes": 12000000000,
              "state": "GOOD",
              "components": [
                {
                  "name": "volume10v00",
                  "vspaceType": "vShare",
                  "vspaceRole": "target",
                  "storageObjectID": "vShare:3f86da54-41db-8c64bbcc14cc:T",
                  "state": "Started",
                  "node": "tm33.virident.info",
                  "partName": "/dev/gbd0_volume10h00"
                }
              ]
            }
          ]
        }
      ],
      "_size": "12GB",
      "_state": "OFFLINE",
      "_ugm": "",
      "_nets": "net1",
      "_hosts": "tm33.virident.info(12GB,NC)",
      "_ahosts": "",
      "_shosts": "tm33.virident.info(12GB)",
      "_name": "volume10",
      "_node": "",
      "_type": "vLVM-L",
      "_detail": "vLVM-L:698cdb43-54da-863e-1699-294a080ce4db",
      "_device": ""
    }
  ]
}
"""

NETWORK_LIST = """
Network Name Type    Flags          Description
------------ ---- ---------- ------------------------
net1         IPv4 autoConfig 192.168.0.0/24 1Gb/s
net2         IPv4 autoConfig 192.168.10.0/24 10Gb/s
"""

DD_OUTPUT = """
1+0 records in
1+0 records out
1024 bytes (1.0 kB) copied, 0.000427529 s, 2.4 MB/s
"""
