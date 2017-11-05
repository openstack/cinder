#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
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
import mock
import six
from xml.etree import ElementTree

from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as testutils
from cinder.tests.unit.volume.drivers.ibm import fake_pyxcli
import cinder.volume.drivers.ibm.ibm_storage as storage
from cinder.volume.drivers.ibm.ibm_storage import cryptish
from cinder.volume.drivers.ibm.ibm_storage.xiv_proxy import XIVProxy
from cinder.volume.drivers.ibm.ibm_storage import xiv_replication
from cinder.volume import group_types

errors = fake_pyxcli.pyxcli_client.errors
mirroring = fake_pyxcli.pyxcli_client.mirroring

test_mock = mock.MagicMock()
module_patcher = mock.MagicMock()

test_mock.cinder.exception = exception


TEST_LOG_PREFIX = storage.XIV_LOG_PREFIX
TEST_VOLUME = {
    'name': 'BLA',
    'id': 23,
    'size': 17,
    'group_id': fake.CONSISTENCY_GROUP_ID,
}

TEST_GROUP_SPECS = {
    'group_replication_enabled': '<is> True',
    'replication_type': 'sync',
}

TEST_EXTRA_SPECS = {
    'replication_enabled': '<is> False',
}
TEST_EXTRA_SPECS_REPL = {
    'replication_enabled': '<is> True',
    'replication_type': 'sync',
}

TEST_WWPNS = ["50017380FE020160", "50017380FE020161", "50017380FE020162"]
TEST_INITIATOR = 'c5507606d5680e05'
TEST_CONNECTOR = {
    'ip': '129.123.123.123',
    'initiator': TEST_INITIATOR,
    'wwpns': [TEST_INITIATOR],
}
TEST_TARGET_MAP = {TEST_INITIATOR: TEST_WWPNS}

TEST_HOST_ID = 11
TEST_HOST_NAME = 'WTF32'
TEST_CHAP_NAME = 'WTF64'
TEST_CHAP_SECRET = 'V1RGNjRfXw=='

FC_TARGETS_OPTIMIZED = [
    "50017380FE020160", "50017380FE020190", "50017380FE020192"]
FC_TARGETS_OPTIMIZED_WITH_HOST = [
    "50017380FE020160", "50017380FE020192"]
FC_TARGETS_BEFORE_SORTING = [
    "50017380FE020160", "50017380FE020161", "50017380FE020162",
    "50017380FE020190", "50017380FE020191", "50017380FE020192"]
FC_TARGETS_AFTER_SORTING = [
    "50017380FE020190", "50017380FE020160", "50017380FE020191",
    "50017380FE020161", "50017380FE020162", "50017380FE020192"]

FC_PORT_LIST_OUTPUT = [
    {'component_id': '1:FC_Port:4:1', 'port_state': 'Online', 'role': 'Target',
     'wwpn': '50017380FE020160'},
    {'component_id': '1:FC_Port:5:1', 'port_state': 'Link Problem',
     'role': 'Target', 'wwpn': '50017380FE020161'},
    {'component_id': '1:FC_Port:6:1', 'port_state': 'Online',
     'role': 'Initiator', 'wwpn': '50017380FE020162'},
    {'component_id': '1:FC_Port:7:1', 'port_state': 'Link Problem',
     'role': 'Initiator', 'wwpn': '50017380FE020163'},
    {'component_id': '1:FC_Port:8:1', 'port_state': 'Online', 'role': 'Target',
     'wwpn': '50017380FE020190'},
    {'component_id': '1:FC_Port:9:1', 'port_state': 'Link Problem',
     'role': 'Target', 'wwpn': '50017380FE020191'},
    {'component_id': '1:FC_Port:4:1', 'port_state': 'Online', 'role': 'Target',
     'wwpn': '50017380FE020192'},
    {'component_id': '1:FC_Port:5:1', 'port_state': 'Link Problem',
     'role': 'Initiator', 'wwpn': '50017380FE020193'}]

HOST_CONNECTIVITY_LIST = [
    {'host': 'nova-compute-c5507606d5680e05', 'host_port': '10000000C97D26DB',
     'local_fc_port': '1:FC_Port:4:1', 'local_iscsi_port': '',
     'module': '1:Module:4', 'type': 'FC'}]

HOST_CONNECTIVITY_LIST_UNKNOWN_HOST = [
    {'host': 'nova-compute-c5507606d5680f115', 'host_port': '10000000C97D26DE',
     'local_fc_port': '1:FC_Port:3:1', 'local_iscsi_port': '',
     'module': '1:Module:3', 'type': 'FC'}]

REPLICA_ID = 'WTF32'
REPLICA_IP = '1.2.3.4'
REPLICA_USER = 'WTF64'
REPLICA_PASSWORD = 'WTFWTF'
REPLICA_POOL = 'WTF64'
REPLICA_PARAMS = {
    'san_ip': REPLICA_IP,
    'san_login': REPLICA_USER,
    'san_password': cryptish.encrypt(REPLICA_PASSWORD),
    'san_clustername': REPLICA_POOL
}


class XIVProxyTest(test.TestCase):

    """Tests the main Proxy driver"""

    def setUp(self):
        """import at setup to ensure module patchers are in place"""
        super(XIVProxyTest, self).setUp()

        self.proxy = XIVProxy
        self.version = "cinder"
        self.proxy.configuration = {}
        self.ctxt = context.get_admin_context()

        self.default_storage_info = {
            'user': "WTF32",
            'password': cryptish.encrypt("WTF32"),
            'address': "WTF32",
            'vol_pool': "WTF32",
            'management_ips': "WTF32",
            'system_id': "WTF32"
        }
        self.proxy.configuration['replication_device'] = {
            'backend_id': REPLICA_ID,
            'san_ip': REPLICA_IP,
            'san_user': REPLICA_USER,
            'san_password': REPLICA_PASSWORD,
        }

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.pyxcli")
    def test_wrong_pyxcli(self, mock_pyxcli):

        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        mock_pyxcli.version = '1.1.4'
        self.assertRaises(test_mock.cinder.exception.CinderException,
                          p.setup, {})

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage"
                ".xiv_proxy.socket.getfqdn", new=mock.MagicMock(
                    return_value='test_hostname'))
    def test_setup_should_fail_if_password_is_not_encrypted(self):
        """Passing an unencrypted password should raise an error"""

        storage_info = self.default_storage_info.copy()

        storage_info['password'] = "WTF32"

        p = self.proxy(storage_info, mock.MagicMock(),
                       test_mock.cinder.exception)

        self.assertRaises(test_mock.cinder.exception.InvalidParameterValue,
                          p.setup, {})

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage.xiv_proxy.client."
                "XCLIClient")
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage.xiv_proxy.socket."
                "getfqdn", new=mock.MagicMock(
                    return_value='test_hostname'))
    def test_setup_should_fail_if_credentials_are_invalid(self, mock_xcli):
        """Passing invalid credentials should raise an error"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        mock_xcli.connect_multiendpoint_ssl = mock.MagicMock(
            side_effect=errors.CredentialsError(
                'bla', 'bla', ElementTree.Element("bla")))

        self.assertRaises(test_mock.cinder.exception.NotAuthorized,
                          p.setup, {})

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.client.XCLIClient")
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.socket.getfqdn", new=mock.MagicMock(
                    return_value='test_hostname'))
    def test_setup_should_fail_if_connection_is_invalid(self, mock_xcli):
        """Passing an invalid host to the setup should raise an error"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        mock_xcli.connect_multiendpoint_ssl = mock.MagicMock(
            side_effect=errors.ConnectionError(
                'bla', 'bla', ElementTree.Element("bla")))

        self.assertRaises(test_mock.cinder.exception.HostNotFound,
                          p.setup, {})

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage.xiv_proxy."
                "client.XCLIClient")
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.storage.get_online_iscsi_ports",
                mock.MagicMock(return_value=['WTF32']))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.socket.getfqdn", new=mock.MagicMock(
                    return_value='test_hostname'))
    def test_setup_should_set_iqn_and_portal(self, mock_xcli):
        """Test setup

        Setup should retrieve values from xcli
        and set the IQN and Portal
        """

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception)

        cmd = mock_xcli.connect_multiendpoint_ssl.return_value.cmd
        item = cmd.config_get.return_value.as_dict.return_value.__getitem__
        item.return_value.value = "BLA"

        p.setup({})

        self.assertEqual("BLA", p.meta.get('ibm_storage_iqn'))
        self.assertEqual("WTF32:3260", p.meta.get('ibm_storage_portal'))

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage.xiv_proxy."
                "client.XCLIClient")
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.storage.get_online_iscsi_ports",
                mock.MagicMock(return_value=['WTF32']))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.socket.getfqdn", new=mock.MagicMock(
                    return_value='test_hostname'))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target_params",
                mock.MagicMock(return_value=REPLICA_PARAMS))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target",
                mock.MagicMock(return_value="BLABLA"))
    def test_setup_should_succeed_if_replica_is_set(self, mock_xcli):
        """Test setup

        Setup should succeed if replica is set
        """
        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception)

        cmd = mock_xcli.connect_multiendpoint_ssl.return_value.cmd
        item = cmd.config_get.return_value.as_dict.return_value.__getitem__
        item.return_value.value = "BLA"

        SCHEDULE_LIST_RESPONSE = {
            '00:01:00': {'interval': 120},
            '00:02:00': {'interval': 300},
            '00:05:00': {'interval': 600},
            '00:10:00': {'interval': 1200},
        }
        cmd = mock_xcli.connect_multiendpoint_ssl.return_value.cmd
        cmd.schedule_list.return_value\
            .as_dict.return_value = SCHEDULE_LIST_RESPONSE

        p.setup({})

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage.xiv_proxy."
                "client.XCLIClient")
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.storage.get_online_iscsi_ports",
                mock.MagicMock(return_value=['WTF32']))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.socket.getfqdn", new=mock.MagicMock(
                    return_value='test_hostname'))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target_params",
                mock.MagicMock(return_value=REPLICA_PARAMS))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target",
                mock.MagicMock(return_value="BLABLA"))
    def test_setup_should_fail_if_schedule_create_fails(self, mock_xcli):
        """Test setup

        Setup should fail if replica is set and schedule_create fails
        """

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception)

        cmd = mock_xcli.connect_multiendpoint_ssl.return_value.cmd
        item = cmd.config_get.return_value.as_dict.return_value.__getitem__
        item.return_value.value = "BLA"
        cmd.schedule_list.return_value.as_dict.return_value = {}
        cmd.schedule_create.side_effect = (
            errors.XCLIError('bla'))

        self.assertRaises(exception.VolumeBackendAPIException, p.setup, {})

    def test_create_volume_should_call_xcli(self):
        """Create volume should call xcli with the correct parameters"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        volume = testutils.create_volume(
            self.ctxt, size=16, display_name='WTF32')
        p.create_volume(volume)

        p.ibm_storage_cli.cmd.vol_create.assert_called_once_with(
            vol=volume.name,
            size_blocks=storage.gigabytes_to_blocks(16),
            pool='WTF32')

    def test_create_volume_from_snapshot(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        volume = testutils.create_volume(
            self.ctxt, size=16, display_name='WTF32')
        snapshot = testutils.create_snapshot(self.ctxt, volume.id)

        p.create_volume_from_snapshot(volume, snapshot)

        p.ibm_storage_cli.cmd.vol_copy.assert_called_once_with(
            vol_src=snapshot.name,
            vol_trg=volume.name)

    def test_create_volume_should_fail_if_no_pool_space(self):
        """Test create volume

        Create volume should raise an error
        if there's no pool space left
        """
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.vol_create.side_effect = (
            errors.PoolOutOfSpaceError(
                'bla', 'bla', ElementTree.Element('bla')))

        volume = testutils.create_volume(
            self.ctxt, size=16, display_name='WTF32',
            volume_type_id='b3fcacb5-fbd8-4394-8c00-06853bc13929')

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_volume, volume)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_replication.VolumeReplication.create_replication",
                mock.MagicMock())
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_replication.GroupReplication.create_replication",
                mock.MagicMock())
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target_params",
                mock.MagicMock(return_value=REPLICA_PARAMS))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target",
                mock.MagicMock(return_value="BLABLA"))
    def test_enable_replication(self):
        """Test enable_replication"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)
        p.ibm_storage_cli = mock.MagicMock()
        p._call_remote_xiv_xcli = mock.MagicMock()
        p._update_consistencygroup = mock.MagicMock()
        p.targets = {'tgt1': 'info1'}

        group = self._create_test_group('WTF')
        vol = testutils.create_volume(self.ctxt)
        ret = p.enable_replication(self.ctxt, group, [vol])

        self.assertEqual((
            {'replication_status': fields.ReplicationStatus.ENABLED},
            [{'id': vol['id'],
              'replication_status': fields.ReplicationStatus.ENABLED}]), ret)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_replication.VolumeReplication.delete_replication",
                mock.MagicMock())
    @mock.patch("cinder.volume.group_types.get_group_type_specs",
                mock.MagicMock(return_value=TEST_GROUP_SPECS))
    def test_disable_replication(self):
        """Test disable_replication"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)
        p.ibm_storage_cli = mock.MagicMock()
        p._call_remote_xiv_xcli = mock.MagicMock()
        p._update_consistencygroup = mock.MagicMock()

        group = self._create_test_group('WTF')
        ret = p.disable_replication(self.ctxt, group, [])

        self.assertEqual((
            {'replication_status': fields.ReplicationStatus.DISABLED}, []),
            ret)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._using_default_backend",
                mock.MagicMock(return_value=False))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target_params",
                mock.MagicMock(return_value={'san_clustername': "master"}))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._init_xcli",
                mock.MagicMock())
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._init_xcli",
                mock.MagicMock())
    @mock.patch("cinder.volume.group_types.get_group_type_specs",
                mock.MagicMock(return_value=TEST_GROUP_SPECS))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_replication.GroupReplication.failover",
                mock.MagicMock(return_value=(True, 'good')))
    def test_failover_replication_with_default(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)
        group = self._create_test_group('WTF')
        group.replication_status = fields.ReplicationStatus.FAILED_OVER
        vol = testutils.create_volume(self.ctxt)
        group_update, vol_update = p.failover_replication(self.ctxt, group,
                                                          [vol], 'default')
        updates = {'status': 'available'}
        self.assertEqual(({'replication_status': 'enabled'},
                          [{'id': vol['id'],
                            'updates': updates}]), (group_update, vol_update))

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._using_default_backend",
                mock.MagicMock(return_value=True))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target_params",
                mock.MagicMock(return_value={'san_clustername': "master"}))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._init_xcli",
                mock.MagicMock())
    @mock.patch("cinder.volume.group_types.get_group_type_specs",
                mock.MagicMock(return_value=TEST_GROUP_SPECS))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_replication.GroupReplication.failover",
                mock.MagicMock(return_value=(True, 'good')))
    def test_failover_replication(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)
        group = self._create_test_group('WTF')
        failed_over = fields.ReplicationStatus.FAILED_OVER
        group.replication_status = failed_over
        vol = testutils.create_volume(self.ctxt)
        group_update, vol_update = p.failover_replication(self.ctxt, group,
                                                          [vol],
                                                          'secondary_id')
        failed_over = fields.ReplicationStatus.FAILED_OVER
        updates = {'status': failed_over}
        self.assertEqual(({'replication_status': failed_over},
                          [{'id': vol['id'],
                            'updates': updates}]), (group_update, vol_update))

    def test_failover_resource_no_mirror(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        recovery_mgr = mock.MagicMock()
        recovery_mgr.is_mirror_active = mock.MagicMock()
        recovery_mgr.is_mirror_active.return_value = False

        group = self._create_test_group('WTF')
        ret = xiv_replication.Replication(p)._failover_resource(
            group, recovery_mgr, mock.MagicMock, 'cg', True)
        msg = ("%(rep_type)s %(res)s: no active mirroring and can not "
               "failback" % {'rep_type': 'cg',
                             'res': group['name']})
        self.assertEqual((False, msg), ret)

    def test_failover_resource_mirror(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)
        recovery_mgr = mock.MagicMock()
        recovery_mgr.is_mirror_active = mock.MagicMock()
        recovery_mgr.is_mirror_active.return_value = True

        group = self._create_test_group('WTF')
        ret = xiv_replication.Replication(p)._failover_resource(
            group, recovery_mgr, mock.MagicMock, 'cg', True)

        self.assertEqual((True, None), ret)

    def test_failover_resource_change_role(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)
        recovery_mgr = mock.MagicMock()
        recovery_mgr.is_mirror_active = mock.MagicMock()
        recovery_mgr.is_mirror_active.return_value = True
        recovery_mgr.switch_roles.side_effect = (
            errors.XCLIError(''))
        failover_rep_mgr = mock.MagicMock()
        failover_rep_mgr.change_role = mock.MagicMock()
        group = self._create_test_group('WTF')

        xiv_replication.Replication(p)._failover_resource(
            group, recovery_mgr, failover_rep_mgr, 'cg', True)

        failover_rep_mgr.change_role.assert_called_once_with(
            resource_id=group['name'],
            new_role='Slave')

    @mock.patch("cinder.volume.utils.is_group_a_cg_snapshot_type",
                mock.MagicMock(return_value=True))
    def test_create_volume_with_consistency_group(self):
        """Test Create volume with consistency_group"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p._cg_name_from_volume = mock.MagicMock(return_value="cg")

        vol_type = testutils.create_volume_type(self.ctxt, name='WTF')
        volume = testutils.create_volume(
            self.ctxt, size=16, volume_type_id=vol_type.id)

        grp = self._create_test_group('WTF')
        volume.group = grp
        p.create_volume(volume)

        p.ibm_storage_cli.cmd.vol_create.assert_called_once_with(
            vol=volume['name'],
            size_blocks=storage.gigabytes_to_blocks(16),
            pool='WTF32')
        p.ibm_storage_cli.cmd.cg_add_vol.assert_called_once_with(
            vol=volume['name'],
            cg='cg')

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_replication.VolumeReplication.create_replication",
                mock.MagicMock())
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_qos_specs",
                mock.MagicMock(return_value=None))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_extra_specs",
                mock.MagicMock(return_value=TEST_EXTRA_SPECS_REPL))
    def test_create_volume_with_replication(self):
        """Test Create volume with replication"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"
        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        volume = testutils.create_volume(
            self.ctxt, size=16, display_name='WTF32',
            volume_type_id='b3fcacb5-fbd8-4394-8c00-06853bc13929')
        volume.group = None
        p.create_volume(volume)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_replication.VolumeReplication.create_replication",
                mock.MagicMock())
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_qos_specs",
                mock.MagicMock(return_value=None))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_extra_specs",
                mock.MagicMock(return_value=TEST_EXTRA_SPECS_REPL))
    def test_create_volume_with_replication_and_cg(self):
        """Test Create volume with replication and CG"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        volume = testutils.create_volume(
            self.ctxt, size=16, display_name='WTF32',
            volume_type_id='b3fcacb5-fbd8-4394-8c00-06853bc13929')
        grp = testutils.create_group(self.ctxt, name='bla', group_type_id='1')
        volume.group = grp
        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_volume, volume)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_qos_specs",
                mock.MagicMock(return_value=None))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_extra_specs",
                mock.MagicMock(return_value=TEST_EXTRA_SPECS_REPL))
    def test_create_volume_with_replication_multiple_targets(self):
        """Test Create volume with replication and multiple targets"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        volume = testutils.create_volume(
            self.ctxt, size=16, display_name='WTF32',
            volume_type_id='b3fcacb5-fbd8-4394-8c00-06853bc13929')
        volume.group = None
        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_volume, volume)

    def test_delete_volume_should_pass_the_correct_parameters(self):
        """Delete volume should call xcli with the correct parameters"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.vol_list.return_value.as_list = ['aa']

        p.delete_volume({'name': 'WTF32'})

        p.ibm_storage_cli.cmd.vol_delete.assert_called_once_with(vol='WTF32')

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_replication.VolumeReplication.delete_replication",
                mock.MagicMock())
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_extra_specs",
                mock.MagicMock(return_value=TEST_EXTRA_SPECS_REPL))
    def test_delete_volume_with_replication(self):
        """Test Delete volume with replication"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        volume = {'size': 16, 'name': 'WTF32', 'volume_type_id': 'WTF'}
        p.delete_volume(volume)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_extra_specs",
                mock.MagicMock(return_value=TEST_EXTRA_SPECS_REPL))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.client.XCLIClient")
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target_params",
                mock.MagicMock(return_value=REPLICA_PARAMS))
    def test_failover_host(self, mock_xcli):
        """Test failover_host with valid target"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock_xcli
        p.ibm_storage_cli.connect_multiendpoint_ssl.return_value
        mock_xcli.connect_multiendpoint_ssl.return_value = mock_xcli

        volume = {'id': 'WTF64', 'size': 16,
                  'name': 'WTF32', 'volume_type_id': 'WTF'}
        target = REPLICA_ID
        p.failover_host({}, [volume], target, [])

    def test_failover_host_invalid_target(self):
        """Test failover_host with invalid target"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        volume = {'id': 'WTF64', 'size': 16,
                  'name': 'WTF32', 'volume_type_id': 'WTF'}
        target = 'Invalid'
        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.failover_host, {}, [volume], target, [])

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.client.XCLIClient")
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target_params",
                mock.MagicMock(return_value=REPLICA_PARAMS))
    def test_failover_host_no_connection_to_target(self, mock_xcli):
        """Test failover_host that fails to connect to target"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock_xcli
        p.ibm_storage_cli.connect_multiendpoint_ssl.return_value
        mock_xcli.connect_multiendpoint_ssl.side_effect = errors.XCLIError('')

        volume = {'id': 'WTF64', 'size': 16,
                  'name': 'WTF32', 'volume_type_id': 'WTF'}
        target = REPLICA_ID
        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.failover_host, {}, [volume], target, [])

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.client.XCLIClient")
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_target_params",
                mock.MagicMock(return_value=REPLICA_PARAMS))
    def test_failback_host(self, mock_xcli):
        """Test failing back after DR"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        volume = {'id': 'WTF64', 'size': 16,
                  'name': 'WTF32', 'volume_type_id': 'WTF'}
        target = 'default'
        p.failover_host(None, [volume], target, [])

    def qos_test_empty_name_if_no_specs(self):
        """Test empty name in case no specs are specified"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        perf_name = p._check_perf_class_on_backend({})
        self.assertEqual('', perf_name)

    def test_qos_class_name_contains_qos_type(self):
        """Test backend naming

        Test if the naming convention is correct
        when getting the right specs with qos type
        """
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.perf_class_list.return_value.as_list = []
        perf_name = p._check_perf_class_on_backend({'bw': '100',
                                                    'type': 'independent'})

        self.assertEqual('cinder-qos_bw_100_type_independent', perf_name)

    def test_qos_called_with_type_parameter(self):
        """Test xcli call for qos creation with type"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.perf_class_list.return_value.as_list = []
        perf_name = p._check_perf_class_on_backend({'bw': '100',
                                                    'type': 'independent'})
        p.ibm_storage_cli.cmd.perf_class_create.assert_called_once_with(
            perf_class=perf_name,
            type='independent')

    def test_qos_called_with_wrong_type_parameter(self):
        """Test xcli call for qos creation with wrong type"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.perf_class_list.return_value.as_list = []
        p.ibm_storage_cli.cmd.perf_class_create.side_effect = (
            errors.XCLIError('llegal value'))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p._check_perf_class_on_backend,
                          {'bw': '100', 'type': 'BAD'})

    def test_qos_class_on_backend_name_correct(self):
        """Test backend naming

        Test if the naming convention is correct
        when getting the right specs
        """
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.perf_class_list.return_value.as_list = []
        perf_name = p._check_perf_class_on_backend({'bw': '100'})

        self.assertEqual('cinder-qos_bw_100', perf_name)

    def test_qos_xcli_exception(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.perf_class_list.side_effect = (
            errors.XCLIError(''))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p._check_perf_class_on_backend, {'bw': '100'})

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._qos_create_kwargs_for_xcli",
                mock.MagicMock(return_value={}))
    def test_regex_from_perf_class_name(self):
        """Test type extraction from perf_class with Regex"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        perf_class_names_list = [
            {'class_name': 'cinder-qos_iops_1000_type_independent_bw_1000',
             'type': 'independent'},
            {'class_name': 'cinder-qos_iops_1000_bw_1000_type_shared',
             'type': 'shared'},
            {'class_name': 'cinder-qos_type_badtype_bw_1000',
             'type': None}]

        for element in perf_class_names_list:
            _type = p._get_type_from_perf_class_name(
                perf_class_name=element['class_name'])
            self.assertEqual(element['type'], _type)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._qos_create_kwargs_for_xcli",
                mock.MagicMock(return_value={}))
    def test_create_qos_class_with_type(self):
        """Test performance class creation with type"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.perf_class_set_rate.return_value = None
        p.ibm_storage_cli.cmd.perf_class_create.return_value = None

        perf_class_name = 'cinder-qos_iops_1000_type_independent_bw_1000'
        p_class_name = p._create_qos_class(perf_class_name=perf_class_name,
                                           specs=None)

        p.ibm_storage_cli.cmd.perf_class_create.assert_called_once_with(
            perf_class=perf_class_name,
            type='independent')
        self.assertEqual('cinder-qos_iops_1000_type_independent_bw_1000',
                         p_class_name)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._check_storage_version_for_qos_support",
                mock.MagicMock(return_value=True))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_qos_specs",
                mock.MagicMock(return_value='specs'))
    def test_qos_specs_exist_if_type_exists(self):
        """Test a case where type was found and qos were found"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        volume = {'name': 'bla', 'volume_type_id': '7'}
        specs = p._qos_specs_from_volume(volume)
        self.assertEqual('specs', specs)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._check_storage_version_for_qos_support",
                mock.MagicMock(return_value=True))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_qos_specs",
                mock.MagicMock(return_value=None))
    def test_no_qos_but_type_exists(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        volume = {'name': 'bla', 'volume_type_id': '7'}
        specs = p._qos_specs_from_volume(volume)
        self.assertIsNone(specs)

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._check_storage_version_for_qos_support",
                mock.MagicMock(return_value=True))
    @mock.patch("cinder.volume.drivers.ibm.ibm_storage."
                "xiv_proxy.XIVProxy._get_qos_specs",
                mock.MagicMock(return_value=None))
    def test_qos_specs_doesnt_exist_if_no_type(self):
        """Test _qos_specs_from_volume

        Test a case where no type was defined
        and therefore no specs exist
        """
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        volume = {'name': 'bla'}
        specs = p._qos_specs_from_volume(volume)
        self.assertIsNone(specs)

    def test_manage_volume_should_call_xcli(self):
        """Manage volume should call xcli with the correct parameters"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.vol_list.return_value.as_list = [
            {'name': 'WTF64', 'size': 34}]
        p.manage_volume(volume={'name': 'WTF32'},
                        reference={'source-name': 'WTF64'})

        p.ibm_storage_cli.cmd.vol_list.assert_called_once_with(
            vol='WTF64')

    def test_manage_volume_should_return_volume_if_exists(self):
        """Manage volume should return with no errors"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.vol_list.return_value.as_list = [
            {'name': 'WTF64', 'size': 34}]
        volume = {'name': 'WTF32'}
        p.manage_volume(volume=volume,
                        reference={'source-name': 'WTF64'})

        self.assertEqual(34, volume['size'])

    def test_manage_volume_should_raise_exception_if_not_exists(self):
        """Test manage_volume

        Manage volume should return with exception
        if volume does not exist
        """
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.vol_list.return_value.as_list = []

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.manage_volume, volume={'name': 'WTF32'},
                          reference={'source-name': 'WTF64'})

    def test_manage_volume_get_size_if_volume_exists(self):
        """Manage volume get size should return size"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.vol_list.return_value.as_list = [
            {'name': 'WTF64', 'size': 34}]
        volume = {'name': 'WTF32'}
        size = p.manage_volume_get_size(volume=volume,
                                        reference={'source-name': 'WTF64'})

        self.assertEqual(34, size)

    def test_retype_false_if_no_location(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        volume = {'display_name': 'vol'}
        new_type = {}
        new_type['name'] = "type1"
        host = {'capabilities': ''}
        diff = {}
        ret = p.retype({}, volume, new_type, diff, host)
        self.assertFalse(ret)

    def test_retype_false_if_dest_not_xiv_backend(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        host = {'capabilities': {'location_info': "IBM-XIV:host:pool"}}
        volume = {'display_name': 'vol', 'host': "origdest_orighost_origpool"}
        new_type = {'name': "type1"}
        diff = {}
        ret = p.retype({}, volume, new_type, diff, host)
        self.assertFalse(ret)

    def test_retype_true_if_dest_is_xiv_backend(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.migrate_volume = mock.MagicMock()
        p.migrate_volume.return_value = (True, None)
        p._qos_specs_from_volume = mock.MagicMock()
        p._get_qos_specs = mock.MagicMock()
        p._qos_specs_from_volume.return_value = {}
        p._get_qos_specs.return_value = {}

        host = {'capabilities': {'location_info': "IBM-XIV:host:pool"}}
        volume = {'display_name': 'vol', 'host': "IBM-XIV_host_pool"}
        new_type = {'name': "type1"}
        diff = {}
        ret = p.retype({}, volume, new_type, diff, host)
        self.assertTrue(ret)

    def test_manage_volume_get_size_should_raise_exception_if_not_exists(self):
        """Test manage_volume

        Manage volume get size should raise exception
        if volume does not exist
        """
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.vol_list.return_value.as_list = []

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.manage_volume_get_size,
                          volume={'name': 'WTF32'},
                          reference={'source-name': 'WTF64'})

    def test_initialize_connection(self):
        """Test initialize_connection

        Ensure that initialize connection returns,
        all the correct connection values
        """

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception)

        p.ibm_storage_iqn = "BLAIQN"
        p.ibm_storage_portal = "BLAPORTAL"

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.vol_list.return_value.as_list = ['aa']
        host = self._get_test_host()
        setattr(
            p, '_get_host_and_fc_targets', mock.MagicMock(return_value=(
                [], host)))
        setattr(
            p, '_vol_map_and_get_lun_id', mock.MagicMock(return_value=100))
        p.volume_exists = mock.MagicMock(return_value=True)

        info = p.initialize_connection(TEST_VOLUME, {})

        self.assertEqual(
            p.meta.get('ibm_storage_portal'),
            info['data']['target_portal'])
        self.assertEqual(
            p.meta.get('ibm_storage_iqn'),
            info['data']['target_iqn'])
        self.assertEqual(100, info['data']['target_lun'])

    def test_initialize_connection_no_initiator(self):
        """Initialize connection raises exception on missing initiator"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        connector = TEST_CONNECTOR.copy()
        connector['initiator'] = None

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.initialize_connection, TEST_VOLUME,
                          connector)

    def test_initialize_connection_bad_iqn(self):
        """Initialize connection raises exception on bad formatted IQN"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        connector = TEST_CONNECTOR.copy()
        # any string would pass for initiator
        connector['initiator'] = 5555

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.initialize_connection, TEST_VOLUME,
                          connector)

    def test_get_fc_targets_returns_optimized_wwpns_list(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.fc_port_list.return_value = FC_PORT_LIST_OUTPUT
        fc_targets = p._get_fc_targets(None)
        six.assertCountEqual(self, FC_TARGETS_OPTIMIZED, fc_targets)

    def test_get_fc_targets_returns_host_optimized_wwpns_list(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        hostname = storage.get_host_or_create_from_iqn(TEST_CONNECTOR)
        host = {'name': hostname}
        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.fc_port_list.return_value = FC_PORT_LIST_OUTPUT
        p.ibm_storage_cli.cmd.host_connectivity_list.return_value = (
            HOST_CONNECTIVITY_LIST)
        fc_targets = p._get_fc_targets(host)
        self.assertEqual(FC_TARGETS_OPTIMIZED_WITH_HOST, fc_targets,
                         "FC targets are different from the expected")

    def test_get_fc_targets_returns_host_all_wwpns_list(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        hostname = storage.get_host_or_create_from_iqn(TEST_CONNECTOR)
        host = {'name': hostname}
        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.fc_port_list.return_value = FC_PORT_LIST_OUTPUT
        p.ibm_storage_cli.cmd.host_connectivity_list.return_value = (
            HOST_CONNECTIVITY_LIST_UNKNOWN_HOST)
        fc_targets = p._get_fc_targets(host)
        self.assertEqual(FC_TARGETS_OPTIMIZED, fc_targets,
                         "FC targets are different from the expected")

    def test_define_ports_returns_sorted_wwpns_list(self):
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p._get_connection_type = mock.MagicMock(
            return_value=storage.XIV_CONNECTION_TYPE_FC)
        p._define_fc = mock.MagicMock(return_value=FC_TARGETS_BEFORE_SORTING)
        fc_targets = p._define_ports(self._get_test_host())
        fc_result = list(map(lambda x: x[-1:], fc_targets))
        expected_result = list(map(lambda x: x[-1:], FC_TARGETS_AFTER_SORTING))
        self.assertEqual(expected_result, fc_result,
                         "FC targets are different from the expected")

    def test_get_host_and_fc_targets_if_host_not_defined(self):
        """Test host and FC targets

        Tests that host and fc targets are provided
        if the host is not defined
        """

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception)

        p.meta = mock.MagicMock()
        p.meta.ibm_storage_iqn = "BLAIQN"
        p.meta.ibm_storage_portal = "BLAPORTAL"
        p.meta.openstack_version = "cinder-2013.2"

        pool = {'name': "WTF32", 'domain': 'pool_domain_bla'}

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.host_list.return_value.as_list = []
        p.ibm_storage_cli.cmd.host_list_ports.return_value = []
        p.ibm_storage_cli.cmd.pool_list.return_value.as_list = [pool]
        p._get_bunch_from_host = mock.MagicMock()
        p._get_bunch_from_host.return_value = {
            'name': "nova-compute-%s" % TEST_INITIATOR,
            'initiator': TEST_INITIATOR,
            'id': 123, 'wwpns': 111, 'chap': 'chap', }

        fc_targets, host = getattr(p, '_get_host_and_fc_targets')(
            TEST_VOLUME, TEST_CONNECTOR)

        hostname = storage.get_host_or_create_from_iqn(TEST_CONNECTOR)
        p.ibm_storage_cli.cmd.host_define.assert_called_once_with(
            host=hostname, domain=pool.get('domain'))
        p.ibm_storage_cli.cmd.host_add_port.assert_called_once_with(
            host=hostname, iscsi_name=TEST_CONNECTOR['initiator'])

    def test_get_lun_id_if_host_already_mapped(self):
        """Test lun id

        Tests that a lun is provided if host is already
        mapped to other volumes
        """
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        vol_mapping_list = p.ibm_storage_cli.cmd.vol_mapping_list
        vol_mapping_list.return_value.as_dict.return_value = {}
        lun1 = {'lun': 1}
        lun2 = {'lun': 2}
        p.ibm_storage_cli.cmd.mapping_list.return_value.as_list = [lun1, lun2]

        host = self._get_test_host()
        self.assertEqual(
            3, getattr(p, '_vol_map_and_get_lun_id')(
                TEST_VOLUME, TEST_CONNECTOR, host))

    def test_terminate_connection_should_call_unmap_vol(self):
        """Terminate connection should call unmap vol"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p._get_connection_type = mock.MagicMock(
            return_value=storage.XIV_CONNECTION_TYPE_FC)
        p._get_fc_targets = mock.MagicMock(return_value=TEST_WWPNS)
        p.ibm_storage_cli = mock.MagicMock()
        vol_mapping_ret = p.ibm_storage_cli.cmd.vol_mapping_list.return_value
        vol_mapping_ret.as_dict.return_value.has_keys.return_value = True

        p.ibm_storage_cli.cmd.vol_list.return_value.as_list = ['aa']

        hostname = storage.get_host_or_create_from_iqn(TEST_CONNECTOR)
        host = {
            'name': hostname,
            'initiator': TEST_CONNECTOR['initiator'],
            'id': 1
        }
        TEST_CONNECTOR['wwpns'] = [TEST_INITIATOR]

        setattr(p, "_get_host", mock.MagicMock(return_value=host))

        meta = p.terminate_connection(TEST_VOLUME, TEST_CONNECTOR)

        self.assertEqual(
            TEST_TARGET_MAP, meta['data']['initiator_target_map'])

        p.ibm_storage_cli.cmd.unmap_vol.assert_called_once_with(
            vol=TEST_VOLUME['name'], host=hostname)

    def test_terminate_connection_multiple_connections(self):
        # Terminate connection should not return meta if host is still
        # connected

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception)

        p.ibm_storage_cli = mock.MagicMock()
        vol_dict = p.ibm_storage_cli.cmd.vol_mapping_list.return_value.as_dict
        vol_dict.return_value.has_keys.return_value = True

        p.ibm_storage_cli.cmd.vol_list.return_value.as_list = ['aa']

        hostname = storage.get_host_or_create_from_iqn(TEST_CONNECTOR)
        host = {
            'name': hostname,
            'initiator': TEST_CONNECTOR['initiator'],
            'id': 1
        }
        TEST_CONNECTOR['wwpns'] = [TEST_INITIATOR]

        map_dict = p.ibm_storage_cli.cmd.mapping_list.return_value.as_dict
        map_dict.return_value.has_keys.return_value = host

        setattr(p, "_get_host", mock.MagicMock(return_value=host))

        meta = p.terminate_connection(TEST_VOLUME, TEST_CONNECTOR)

        self.assertIsNone(meta)

        p.ibm_storage_cli.cmd.unmap_vol.assert_called_once_with(
            vol=TEST_VOLUME['name'], host=hostname)

    def test_attach_deleted_volume_should_fail_with_info_to_log(self):
        """Test attach deleted volume should fail with info to log"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        mock_log = mock.MagicMock()
        setattr(p, "_log", mock_log)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.vol_mapping_list.side_effect = (
            errors.VolumeBadNameError('bla', 'bla',
                                      ElementTree.Element('Bla')))
        p._define_host_according_to_chap = mock.MagicMock()
        p._define_host_according_to_chap.return_value = dict(id=100)
        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.initialize_connection, TEST_VOLUME,
                          TEST_CONNECTOR)

    def _get_test_host(self):
        host = {
            'name': TEST_HOST_NAME,
            'initiator': TEST_INITIATOR,
            'id': TEST_HOST_ID,
            'wwpns': [TEST_INITIATOR],
            'chap': (TEST_CHAP_NAME, TEST_CHAP_SECRET)
        }
        return host

    def _create_test_group(self, g_name='group', is_cg=True):
        extra_specs = {}
        if is_cg:
            extra_specs['consistent_group_snapshot_enabled'] = '<is> True'

        group_type = group_types.create(self.ctxt, g_name, extra_specs)
        return testutils.create_group(self.ctxt,
                                      host=self._get_test_host()['name'],
                                      group_type_id=group_type.id,
                                      volume_type_ids=[])

    def _create_test_cgsnapshot(self, group_id):
        group_type = group_types.create(
            self.ctxt, 'group_snapshot',
            {'consistent_group_snapshot_enabled': '<is> True'})
        return testutils.create_group_snapshot(self.ctxt, group_id=group_id,
                                               group_type_id=group_type.id)

    def test_create_generic_group(self):
        """test create generic group"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group(is_cg=False)

        self.assertRaises(NotImplementedError,
                          p.create_group, {}, group_obj)

    def test_create_consistencygroup(self):
        """test a successful cg create"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group()

        model_update = p.create_group({}, group_obj)

        p.ibm_storage_cli.cmd.cg_create.assert_called_once_with(
            cg=p._cg_name_from_id(group_obj.id),
            pool='WTF32')

        self.assertEqual('available', model_update['status'])

    def test_create_consistencygroup_already_exists(self):
        """test create_consistenygroup when cg already exists"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.cg_create.side_effect = errors.CgNameExistsError(
            'bla', 'bla', ElementTree.Element('bla'))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group, {}, self._create_test_group())

    def test_create_consistencygroup_reached_limit(self):
        """test create_consistenygroup when reached maximum CGs"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.cg_create.side_effect = (
            errors.CgLimitReachedError(
                'bla', 'bla', ElementTree.Element('bla')))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group, {}, self._create_test_group())

    @mock.patch("cinder.volume.drivers.ibm.ibm_storage.xiv_proxy."
                "client.XCLIClient")
    def test_create_consistencygroup_with_replication(self, mock_xcli):
        """test create_consistenygroup when replication is set"""

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception)

        p.ibm_storage_cli = mock.MagicMock()

        group_obj = self._create_test_group()

        vol_type = objects.VolumeType(context=self.ctxt,
                                      name='volume_type_rep',
                                      extra_specs=(
                                          {'replication_enabled': '<is> True',
                                           'replication_type': 'sync'}))
        group_obj.volume_types = objects.VolumeTypeList(context=self.ctxt,
                                                        objects=[vol_type])

        model_update = p.create_group({}, group_obj)
        self.assertEqual('available', model_update['status'])

    def test_create_consistencygroup_from_src_cgsnapshot(self):
        """test a successful cg create from cgsnapshot"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.create_volume_from_snapshot.return_value = []

        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        volume = testutils.create_volume(self.ctxt)
        snapshot = testutils.create_snapshot(self.ctxt, volume.id)

        model_update, vols_model_update = p.create_group_from_src(
            {}, group_obj, [volume],
            cgsnap_group_obj, [snapshot], None, None)

        p.ibm_storage_cli.cmd.cg_create.assert_called_once_with(
            cg=p._cg_name_from_id(group_obj.id), pool='WTF32')

        self.assertEqual('available', model_update['status'])

    def test_create_consistencygroup_from_src_cg(self):
        """test a successful cg create from consistencygroup"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.create_volume_from_snapshot.return_value = []

        group_obj = self._create_test_group()
        src_group_obj = self._create_test_group(g_name='src_group')

        volume = testutils.create_volume(self.ctxt)
        src_volume = testutils.create_volume(self.ctxt)

        model_update, vols_model_update = p.create_group_from_src(
            {}, group_obj, [volume],
            None, None, src_group_obj, [src_volume])

        p.ibm_storage_cli.cmd.cg_create.assert_called_once_with(cg=group_obj,
                                                                pool='WTF32')

        self.assertEqual('available', model_update['status'])

    def test_create_consistencygroup_from_src_fails_cg_create_from_cgsnapshot(
            self):
        """test cg create from cgsnapshot fails on cg_create"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.cg_create.side_effect = errors.XCLIError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        volume = testutils.create_volume(self.ctxt)
        snapshot = testutils.create_snapshot(self.ctxt, volume.id)

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group_from_src, {},
                          group_obj, [volume], cgsnap_group_obj,
                          [snapshot], None, None)

    def test_create_consistencygroup_from_src_fails_cg_create_from_cg(self):
        """test cg create from cg fails on cg_create"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.cg_create.side_effect = errors.XCLIError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()
        src_group_obj = self._create_test_group(g_name='src_group')

        volume = testutils.create_volume(self.ctxt)
        src_volume = testutils.create_volume(self.ctxt)

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group_from_src, {},
                          group_obj, [volume], None, None,
                          src_group_obj, [src_volume])

    def test_create_consistencygroup_from_src_fails_vol_create_from_cgsnapshot(
            self):
        """test cg create from cgsnapshot fails on vol_create"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.vol_create.side_effect = errors.XCLIError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        volume = testutils.create_volume(self.ctxt)
        snapshot = testutils.create_snapshot(self.ctxt, volume.id)

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group_from_src, {},
                          group_obj, [volume], cgsnap_group_obj,
                          [snapshot], None, None)

    def test_create_consistencygroup_from_src_fails_vol_create_from_cg(self):
        """test cg create from cg fails on vol_create"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.vol_create.side_effect = errors.XCLIError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()
        src_group_obj = self._create_test_group(g_name='src_group')

        volume = testutils.create_volume(self.ctxt)
        src_volume = testutils.create_volume(self.ctxt)

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group_from_src, {},
                          group_obj, [volume], None, None,
                          src_group_obj, [src_volume])

    def test_create_consistencygroup_from_src_fails_vol_copy_from_cgsnapshot(
            self):
        """test cg create from cgsnapshot fails on vol_copy"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.vol_copy.side_effect = errors.XCLIError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        volume = testutils.create_volume(self.ctxt)
        snapshot = testutils.create_snapshot(self.ctxt, volume.id)

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group_from_src, {}, group_obj,
                          [volume], cgsnap_group_obj, [snapshot],
                          None, None)

    def test_create_consistencygroup_from_src_fails_vol_copy_from_cg(self):
        """test cg create from cg fails on vol_copy"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.vol_copy.side_effect = errors.XCLIError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()
        src_group_obj = self._create_test_group(g_name='src_group')

        volume = testutils.create_volume(self.ctxt)
        src_volume = testutils.create_volume(self.ctxt)

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group_from_src, {},
                          group_obj, [volume], None, None,
                          src_group_obj, [src_volume])

    def test_delete_consistencygroup_with_no_volumes(self):
        """test a successful cg delete"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        group_obj = self._create_test_group()

        model_update, volumes = p.delete_group({}, group_obj, [])

        p.ibm_storage_cli.cmd.cg_delete.assert_called_once_with(
            cg=p._cg_name_from_id(group_obj.id))

        self.assertEqual('deleted', model_update['status'])

    def test_delete_consistencygroup_not_exists(self):
        """test delete_consistenygroup when CG does not exist"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.cg_delete.side_effect = (
            errors.CgDoesNotExistError(
                'bla', 'bla', ElementTree.Element('bla')))

        group_obj = self._create_test_group()

        model_update, volumes = p.delete_group({}, group_obj, [])

        p.ibm_storage_cli.cmd.cg_delete.assert_called_once_with(
            cg=p._cg_name_from_id(group_obj.id))

        self.assertEqual('deleted', model_update['status'])

    def test_delete_consistencygroup_not_exists_2(self):
        """test delete_consistenygroup when CG does not exist bad name"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.cg_delete.side_effect = (
            errors.CgBadNameError(
                'bla', 'bla', ElementTree.Element('bla')))

        group_obj = self._create_test_group()
        model_update, volumes = p.delete_group({}, group_obj, [])

        p.ibm_storage_cli.cmd.cg_delete.assert_called_once_with(
            cg=p._cg_name_from_id(group_obj.id))

        self.assertEqual('deleted', model_update['status'])

    def test_delete_consistencygroup_not_empty(self):
        """test delete_consistenygroup when CG is not empty"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.cg_delete.side_effect = errors.CgNotEmptyError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.delete_group, {}, group_obj, [])

    def test_delete_consistencygroup_replicated(self):
        """test delete cg when CG is not empty and replicated"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        group_obj = self._create_test_group()
        group_obj['replication_status'] = fields.ReplicationStatus.ENABLED
        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.delete_group, {}, group_obj, [])

    def test_delete_consistencygroup_faildover(self):
        """test delete cg when CG is faildover"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        group_obj = self._create_test_group()
        group_obj['replication_status'] = fields.ReplicationStatus.FAILED_OVER
        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.delete_group, {}, group_obj, [])

    def test_delete_consistencygroup_is_mirrored(self):
        """test delete_consistenygroup when CG is mirroring"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.cg_delete.side_effect = errors.CgHasMirrorError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.delete_group, {}, group_obj, [])

    def test_update_consistencygroup(self):
        """test update_consistencygroup"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        group_obj = self._create_test_group()
        vol_add = testutils.create_volume(self.ctxt, display_name='WTF32')
        vol_remove = testutils.create_volume(self.ctxt, display_name='WTF64')

        model_update, add_model_update, remove_model_update = (
            p.update_group({}, group_obj, [vol_add], [vol_remove]))

        p.ibm_storage_cli.cmd.cg_add_vol.assert_called_once_with(
            vol=vol_add['name'], cg=p._cg_name_from_id(group_obj.id))
        p.ibm_storage_cli.cmd.cg_remove_vol.assert_called_once_with(
            vol=vol_remove['name'])
        self.assertEqual('available', model_update['status'])

    def test_update_consistencygroup_exception_in_add_vol(self):
        """test update_consistencygroup with exception in cg_add_vol"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.cg_add_vol.side_effect = errors.XCLIError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()
        vol_add = testutils.create_volume(self.ctxt, display_name='WTF32')

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.update_group, {}, group_obj, [vol_add], [])

    def test_update_consistencygroup_exception_in_remove_vol(self):
        """test update_consistencygroup with exception in cg_remove_vol"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.cg_remove_vol.side_effect = errors.XCLIError(
            'bla', 'bla', ElementTree.Element('bla'))

        group_obj = self._create_test_group()
        vol_remove = testutils.create_volume(self.ctxt)

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.update_group, {},
                          group_obj, [], [vol_remove])

    def test_update_consistencygroup_remove_non_exist_vol_(self):
        """test update_group with exception in cg_remove_vol"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        p.ibm_storage_cli.cmd.cg_remove_vol.side_effect = (
            errors.VolumeNotInConsGroup(
                'bla', 'bla', ElementTree.Element('bla')))

        group_obj = self._create_test_group()
        vol_remove = testutils.create_volume(self.ctxt)

        model_update, add_model_update, remove_model_update = (
            p.update_group({}, group_obj, [], [vol_remove]))

        p.ibm_storage_cli.cmd.cg_remove_vol.assert_called_once_with(
            vol=vol_remove['name'])
        self.assertEqual('available', model_update['status'])

    def test_create_cgsnapshot(self):
        """test a successful cgsnapshot create"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        model_update, snapshots_model_update = (
            p.create_group_snapshot({}, cgsnap_group_obj, []))

        p.ibm_storage_cli.cmd.cg_snapshots_create.assert_called_once_with(
            cg=p._cg_name_from_cgsnapshot(cgsnap_group_obj),
            snap_group=p._group_name_from_cgsnapshot_id(
                cgsnap_group_obj['id']))

        self.assertEqual('available', model_update['status'])

    def test_create_cgsnapshot_is_empty(self):
        """test create_cgsnapshot when CG is empty"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        p.ibm_storage_cli.cmd.cg_snapshots_create.side_effect = (
            errors.CgEmptyError('bla', 'bla', ElementTree.Element('bla')))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group_snapshot, {},
                          cgsnap_group_obj, [])

    def test_create_cgsnapshot_cg_not_exist(self):
        """test create_cgsnapshot when CG does not exist"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        p.ibm_storage_cli.cmd.cg_snapshots_create.side_effect = (
            errors.CgDoesNotExistError(
                'bla', 'bla', ElementTree.Element('bla')))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group_snapshot, {},
                          cgsnap_group_obj, [])

    def test_create_cgsnapshot_snapshot_limit(self):
        """test create_cgsnapshot when reached snapshot limit"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        p.ibm_storage_cli.cmd.cg_snapshots_create.side_effect = (
            errors.PoolSnapshotLimitReachedError(
                'bla', 'bla', ElementTree.Element('bla')))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.create_group_snapshot, {},
                          cgsnap_group_obj, [])

    def test_delete_cgsnapshot(self):
        """test a successful cgsnapshot delete"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        model_update, snapshots_model_update = p.delete_group_snapshot(
            {}, cgsnap_group_obj, [])

        p.ibm_storage_cli.cmd.snap_group_delete.assert_called_once_with(
            snap_group=p._group_name_from_cgsnapshot_id(
                cgsnap_group_obj['id']))

        self.assertEqual('deleted', model_update['status'])

    def test_delete_cgsnapshot_cg_does_not_exist(self):
        """test delete_cgsnapshot with bad CG name"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        p.ibm_storage_cli.cmd.snap_group_delete.side_effect = (
            errors.CgDoesNotExistError(
                'bla', 'bla', ElementTree.Element('bla')))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.delete_group_snapshot, {},
                          cgsnap_group_obj, [])

    def test_delete_cgsnapshot_no_space_left_for_snapshots(self):
        """test delete_cgsnapshot when no space left for snapshots"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        p.ibm_storage_cli.cmd.snap_group_delete.side_effect = (
            errors.PoolSnapshotLimitReachedError(
                'bla', 'bla', ElementTree.Element('bla')))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.delete_group_snapshot, {},
                          cgsnap_group_obj, [])

    def test_delete_cgsnapshot_with_empty_consistency_group(self):
        """test delete_cgsnapshot with empty consistency group"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()
        group_obj = self._create_test_group()
        cgsnap_group_obj = self._create_test_cgsnapshot(group_obj.id)

        p.ibm_storage_cli.cmd.snap_group_delete.side_effect = (
            errors.CgEmptyError('bla', 'bla', ElementTree.Element('bla')))

        ex = getattr(p, "_get_exception")()
        self.assertRaises(ex, p.delete_group_snapshot, {},
                          cgsnap_group_obj, [])

    def test_silent_delete_volume(self):
        """test _silent_delete_volume fails silently without exception"""
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        p.ibm_storage_cli = mock.MagicMock()

        p.ibm_storage_cli.cmd.vol_delete.side_effect = errors.XCLIError(
            'bla', 'bla', ElementTree.Element('bla'))

        # check no assertion occurs
        p._silent_delete_volume(TEST_VOLUME)

    @mock.patch("cinder.volume.utils.group_get_by_id", mock.MagicMock())
    @mock.patch("cinder.volume.utils.is_group_a_cg_snapshot_type",
                mock.MagicMock(return_value=False))
    def test_create_cloned_volume_calls_vol_create_and_copy(self):
        """test create_cloned_volume

        check if calls the appropriate xiv_backend functions
        are being called
        """
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        vol_src = testutils.create_volume(self.ctxt, display_name='bla',
                                          size=17)
        vol_trg = testutils.create_volume(self.ctxt, display_name='bla',
                                          size=17)

        p.ibm_storage_cli = mock.MagicMock()
        p._cg_name_from_volume = mock.MagicMock(return_value="cg")

        p.create_cloned_volume(vol_trg, vol_src)
        p._create_volume = test_mock.MagicMock()

        p.ibm_storage_cli.cmd.vol_create.assert_called_once_with(
            pool='WTF32',
            size_blocks=storage.gigabytes_to_blocks(17),
            vol=vol_trg['name'])

        p.ibm_storage_cli.cmd.vol_copy.assert_called_once_with(
            vol_src=vol_src['name'],
            vol_trg=vol_trg['name'])

    @mock.patch("cinder.volume.utils.group_get_by_id", mock.MagicMock())
    @mock.patch("cinder.volume.utils.is_group_a_cg_snapshot_type",
                mock.MagicMock(return_value=False))
    def test_handle_created_vol_properties_returns_vol_update(self):
        """test handle_created_vol_props

        returns replication enables if replication info is True
        """
        driver = mock.MagicMock()
        driver.VERSION = "VERSION"

        p = self.proxy(
            self.default_storage_info,
            mock.MagicMock(),
            test_mock.cinder.exception,
            driver)

        xiv_replication.VolumeReplication = mock.MagicMock()
        grp = testutils.create_group(self.ctxt, name='bla', group_type_id='1')
        volume = testutils.create_volume(self.ctxt, display_name='bla')
        volume.group = grp
        ret_val = p.handle_created_vol_properties({'enabled': True}, volume)

        self.assertEqual(ret_val, {'replication_status': 'enabled'})
