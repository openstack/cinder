# Copyright (c) 2016 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import functools
import unittest

import mock

from cinder import exception
from cinder.tests.unit.volume.drivers.dell_emc.unity \
    import fake_exception as ex
from cinder.tests.unit.volume.drivers.dell_emc.unity import test_client
from cinder.volume.drivers.dell_emc.unity import adapter


########################
#
#   Start of Mocks
#
########################
class MockConfig(object):
    def __init__(self):
        self.config_group = 'test_backend'
        self.unity_storage_pool_names = ['pool1', 'pool2']
        self.unity_io_ports = None
        self.reserved_percentage = 5
        self.max_over_subscription_ratio = 300
        self.volume_backend_name = 'backend'
        self.san_ip = '1.2.3.4'
        self.san_login = 'user'
        self.san_password = 'pass'
        self.driver_ssl_cert_verify = False
        self.driver_ssl_cert_path = None

    def safe_get(self, name):
        return getattr(self, name)


class MockConnector(object):
    @staticmethod
    def disconnect_volume(data, device):
        pass


class MockDriver(object):
    def __init__(self):
        self.configuration = mock.Mock(volume_dd_blocksize='1M')

    @staticmethod
    def _connect_device(conn):
        return {'connector': MockConnector(),
                'device': {'path': 'dev'},
                'conn': {'data': {}}}


class MockClient(object):
    @staticmethod
    def get_pools():
        return test_client.MockResourceList(['pool0', 'pool1'])

    @staticmethod
    def create_lun(name, size, pool, description=None, io_limit_policy=None):
        return test_client.MockResource(_id='lun_3')

    @staticmethod
    def get_lun(name=None, lun_id=None):
        if lun_id is None:
            lun_id = 'lun_4'
        if name == 'not_exists':
            ret = test_client.MockResource(name=lun_id)
            ret.existed = False
        else:
            ret = test_client.MockResource(_id=lun_id)
        return ret

    @staticmethod
    def delete_lun(lun_id):
        if lun_id != 'lun_4':
            raise ex.UnexpectedLunDeletion()

    @staticmethod
    def get_serial():
        return 'CLIENT_SERIAL'

    @staticmethod
    def create_snap(src_lun_id, name=None):
        return test_client.MockResource(name=name, _id=src_lun_id)

    @staticmethod
    def get_snap(name=None):
        snap = test_client.MockResource(name=name, _id=name)
        if name is not None:
            ret = snap
        else:
            ret = [snap]
        return ret

    @staticmethod
    def delete_snap(snap):
        if snap.name in ('abc-def_snap',):
            raise ex.SnapDeleteIsCalled()

    @staticmethod
    def create_host(name, uids):
        return test_client.MockResource(name=name)

    @staticmethod
    def get_host(name):
        return test_client.MockResource(name=name)

    @staticmethod
    def attach(host, lun_or_snap):
        return 10

    @staticmethod
    def detach(host, lun_or_snap):
        error_ids = ['lun_43', 'snap_0']
        if host.name == 'host1' and lun_or_snap.get_id() in error_ids:
            raise ex.DetachIsCalled()

    @staticmethod
    def get_iscsi_target_info(allowed_ports=None):
        return [{'portal': '1.2.3.4:1234', 'iqn': 'iqn.1-1.com.e:c.a.a0'},
                {'portal': '1.2.3.5:1234', 'iqn': 'iqn.1-1.com.e:c.a.a1'}]

    @staticmethod
    def get_fc_target_info(host=None, logged_in_only=False,
                           allowed_ports=None):
        if host and host.name == 'no_target':
            ret = []
        else:
            ret = ['8899AABBCCDDEEFF', '8899AABBCCDDFFEE']
        return ret

    @staticmethod
    def create_lookup_service():
        return {}

    @staticmethod
    def get_io_limit_policy(specs):
        return None

    @staticmethod
    def extend_lun(lun_id, size_gib):
        if size_gib <= 0:
            raise ex.ExtendLunError

    @staticmethod
    def get_fc_ports():
        return test_client.MockResourceList(ids=['spa_iom_0_fc0',
                                                 'spa_iom_0_fc1'])

    @staticmethod
    def get_ethernet_ports():
        return test_client.MockResourceList(ids=['spa_eth0', 'spb_eth0'])


class MockLookupService(object):
    @staticmethod
    def get_device_mapping_from_network(initiator_wwns, target_wwns):
        return {
            'san_1': {
                'initiator_port_wwn_list':
                    ('200000051e55a100', '200000051e55a121'),
                'target_port_wwn_list':
                    ('100000051e55a100', '100000051e55a121')
            }
        }


def mock_adapter(driver_clz):
    ret = driver_clz()
    ret._client = MockClient()
    with mock.patch('cinder.volume.drivers.dell_emc.unity.adapter.'
                    'CommonAdapter.validate_ports'):
        ret.do_setup(MockDriver(), MockConfig())
    ret.lookup_service = MockLookupService()
    return ret


def get_backend_qos_specs(volume):
    return None


def get_connector_properties():
    return {'host': 'host1', 'wwpns': 'abcdefg'}


def copy_volume(from_path, to_path, size_in_m, block_size, sparse=True):
    pass


def get_lun_pl(name):
    return 'id^%s|system^CLIENT_SERIAL|type^lun|version^None' % name


def get_snap_pl(name):
    return 'id^%s|system^CLIENT_SERIAL|type^snapshot|version^None' % name


def get_connector_uids(adapter, connector):
    return []


def get_connection_info(adapter, hlu, host, connector):
    return {}


def patch_for_unity_adapter(func):
    @functools.wraps(func)
    @mock.patch('cinder.volume.drivers.dell_emc.unity.utils.'
                'get_backend_qos_specs',
                new=get_backend_qos_specs)
    @mock.patch('cinder.utils.brick_get_connector_properties',
                new=get_connector_properties)
    @mock.patch('cinder.volume.utils.copy_volume', new=copy_volume)
    def func_wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return func_wrapper


def patch_for_concrete_adapter(clz_str):
    def inner_decorator(func):
        @functools.wraps(func)
        @mock.patch('%s.get_connector_uids' % clz_str,
                    new=get_connector_uids)
        @mock.patch('%s.get_connection_info' % clz_str,
                    new=get_connection_info)
        def func_wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return func_wrapper

    return inner_decorator


patch_for_iscsi_adapter = patch_for_concrete_adapter(
    'cinder.volume.drivers.dell_emc.unity.adapter.ISCSIAdapter')


patch_for_fc_adapter = patch_for_concrete_adapter(
    'cinder.volume.drivers.dell_emc.unity.adapter.FCAdapter')


########################
#
#   Start of Tests
#
########################
class CommonAdapterTest(unittest.TestCase):
    def setUp(self):
        self.adapter = mock_adapter(adapter.CommonAdapter)

    def test_get_managed_pools(self):
        ret = self.adapter.get_managed_pools()
        self.assertIn('pool1', ret)
        self.assertNotIn('pool0', ret)
        self.assertNotIn('pool2', ret)

    @patch_for_unity_adapter
    def test_create_volume(self):
        volume = mock.Mock(size=5, host='unity#pool1')
        ret = self.adapter.create_volume(volume)
        expected = get_lun_pl('lun_3')
        self.assertEqual(expected, ret['provider_location'])

    def test_create_snapshot(self):
        volume = mock.Mock(provider_location='id^lun_43')
        snap = mock.Mock(volume=volume)
        snap.name = 'abc-def_snap'
        result = self.adapter.create_snapshot(snap)
        self.assertEqual(get_snap_pl('lun_43'), result['provider_location'])
        self.assertEqual('lun_43', result['provider_id'])

    def test_delete_snap(self):
        def f():
            snap = mock.Mock()
            snap.name = 'abc-def_snap'

            self.adapter.delete_snapshot(snap)

        self.assertRaises(ex.SnapDeleteIsCalled, f)

    def test_get_lun_id_has_location(self):
        volume = mock.Mock(provider_location='id^lun_43')
        self.assertEqual('lun_43', self.adapter.get_lun_id(volume))

    def test_get_lun_id_no_location(self):
        volume = mock.Mock(provider_location=None)
        self.assertEqual('lun_4', self.adapter.get_lun_id(volume))

    def test_delete_volume(self):
        volume = mock.Mock(provider_location='id^lun_4')
        self.adapter.delete_volume(volume)

    def test_get_pool_stats(self):
        stats_list = self.adapter.get_pools_stats()
        self.assertEqual(1, len(stats_list))

        stats = stats_list[0]
        self.assertEqual('pool1', stats['pool_name'])
        self.assertEqual(5, stats['total_capacity_gb'])
        self.assertEqual('pool1|CLIENT_SERIAL', stats['location_info'])
        self.assertEqual(6, stats['provisioned_capacity_gb'])
        self.assertEqual(2, stats['free_capacity_gb'])
        self.assertEqual(300, stats['max_over_subscription_ratio'])
        self.assertEqual(5, stats['reserved_percentage'])
        self.assertFalse(stats['thick_provisioning_support'])
        self.assertTrue(stats['thin_provisioning_support'])

    def test_update_volume_stats(self):
        stats = self.adapter.update_volume_stats()
        self.assertEqual('backend', stats['volume_backend_name'])
        self.assertEqual('unknown', stats['storage_protocol'])
        self.assertTrue(stats['thin_provisioning_support'])
        self.assertFalse(stats['thick_provisioning_support'])
        self.assertEqual(1, len(stats['pools']))

    def test_serial_number(self):
        self.assertEqual('CLIENT_SERIAL', self.adapter.serial_number)

    def test_do_setup(self):
        self.assertEqual('1.2.3.4', self.adapter.ip)
        self.assertEqual('user', self.adapter.username)
        self.assertEqual('pass', self.adapter.password)
        self.assertFalse(self.adapter.array_cert_verify)
        self.assertIsNone(self.adapter.array_ca_cert_path)

    def test_verify_cert_false_path_none(self):
        self.adapter.array_cert_verify = False
        self.adapter.array_ca_cert_path = None
        self.assertFalse(self.adapter.verify_cert)

    def test_verify_cert_false_path_not_none(self):
        self.adapter.array_cert_verify = False
        self.adapter.array_ca_cert_path = '/tmp/array_ca.crt'
        self.assertFalse(self.adapter.verify_cert)

    def test_verify_cert_true_path_none(self):
        self.adapter.array_cert_verify = True
        self.adapter.array_ca_cert_path = None
        self.assertTrue(self.adapter.verify_cert)

    def test_verify_cert_true_path_valide(self):
        self.adapter.array_cert_verify = True
        self.adapter.array_ca_cert_path = '/tmp/array_ca.crt'
        self.assertEqual(self.adapter.array_ca_cert_path,
                         self.adapter.verify_cert)

    def test_terminate_connection_volume(self):
        def f():
            volume = mock.Mock(provider_location='id^lun_43', id='id_43')
            connector = {'host': 'host1'}
            self.adapter.terminate_connection(volume, connector)

        self.assertRaises(ex.DetachIsCalled, f)

    def test_terminate_connection_snapshot(self):
        def f():
            connector = {'host': 'host1'}
            snap = mock.Mock(id='snap_0', name='snap_0')
            snap.name = 'snap_0'
            self.adapter.terminate_connection_snapshot(snap, connector)

        self.assertRaises(ex.DetachIsCalled, f)

    def test_manage_existing_by_name(self):
        ref = {'source-id': 12}
        volume = mock.Mock(name='lun1')
        ret = self.adapter.manage_existing(volume, ref)
        expected = get_lun_pl('12')
        self.assertEqual(expected, ret['provider_location'])

    def test_manage_existing_by_id(self):
        ref = {'source-name': 'lunx'}
        volume = mock.Mock(name='lun1')
        ret = self.adapter.manage_existing(volume, ref)
        expected = get_lun_pl('lun_4')
        self.assertEqual(expected, ret['provider_location'])

    def test_manage_existing_invalid_ref(self):
        def f():
            ref = {}
            volume = mock.Mock(name='lun1')
            self.adapter.manage_existing(volume, ref)

        self.assertRaises(exception.ManageExistingInvalidReference, f)

    def test_manage_existing_lun_not_found(self):
        def f():
            ref = {'source-name': 'not_exists'}
            volume = mock.Mock(name='lun1')
            self.adapter.manage_existing(volume, ref)

        self.assertRaises(exception.ManageExistingInvalidReference, f)

    @patch_for_unity_adapter
    def test_manage_existing_get_size_invalid_backend(self):
        def f():
            volume = mock.Mock(volume_type_id='thin',
                               host='host@backend#pool1')
            ref = {'source-id': 12}
            self.adapter.manage_existing_get_size(volume, ref)

        self.assertRaises(exception.ManageExistingInvalidReference, f)

    @patch_for_unity_adapter
    def test_manage_existing_get_size_success(self):
        volume = mock.Mock(volume_type_id='thin', host='host@backend#pool0')
        ref = {'source-id': 12}
        volume_size = self.adapter.manage_existing_get_size(volume, ref)
        self.assertEqual(5, volume_size)

    @patch_for_unity_adapter
    def test_create_volume_from_snapshot(self):
        volume = mock.Mock(id='id_44', host='unity#pool1',
                           provider_location=get_lun_pl('12'))
        snap = mock.Mock(name='snap_44')
        ret = self.adapter.create_volume_from_snapshot(volume, snap)
        self.assertEqual(get_lun_pl('lun_3'), ret['provider_location'])

    @patch_for_unity_adapter
    def test_create_cloned_volume(self):
        volume = mock.Mock(id='id_55', host='unity#pool1', size=3,
                           provider_location=get_lun_pl('lun55'))
        src_vref = mock.Mock(id='id_66', name='LUN 66',
                             provider_location=get_lun_pl('lun66'))
        ret = self.adapter.create_cloned_volume(volume, src_vref)
        self.assertEqual(get_lun_pl('lun_3'), ret['provider_location'])

    def test_extend_volume_error(self):
        def f():
            volume = mock.Mock(id='l56', provider_location=get_lun_pl('lun56'))
            self.adapter.extend_volume(volume, -1)

        self.assertRaises(ex.ExtendLunError, f)

    def test_extend_volume_no_id(self):
        def f():
            volume = mock.Mock(provider_location='type^lun')
            self.adapter.extend_volume(volume, 5)

        self.assertRaises(exception.VolumeBackendAPIException, f)

    def test_normalize_config(self):
        config = MockConfig()
        config.unity_storage_pool_names = ['  pool_1  ', '', '    ']
        config.unity_io_ports = ['  spa_eth2  ', '', '   ']
        normalized = self.adapter.normalize_config(config)
        self.assertEqual(['pool_1'], normalized.unity_storage_pool_names)
        self.assertEqual(['spa_eth2'], normalized.unity_io_ports)

    def test_normalize_config_raise(self):
        with self.assertRaisesRegexp(exception.InvalidConfigurationValue,
                                     'unity_storage_pool_names'):
            config = MockConfig()
            config.unity_storage_pool_names = ['', '    ']
            self.adapter.normalize_config(config)
        with self.assertRaisesRegexp(exception.InvalidConfigurationValue,
                                     'unity_io_ports'):
            config = MockConfig()
            config.unity_io_ports = ['', '   ']
            self.adapter.normalize_config(config)


class FCAdapterTest(unittest.TestCase):
    def setUp(self):
        self.adapter = mock_adapter(adapter.FCAdapter)

    def test_setup(self):
        self.assertIsNotNone(self.adapter.lookup_service)

    def test_auto_zone_enabled(self):
        self.assertTrue(self.adapter.auto_zone_enabled)

    def test_fc_protocol(self):
        stats = mock_adapter(adapter.FCAdapter).update_volume_stats()
        self.assertEqual('FC', stats['storage_protocol'])

    def test_get_connector_uids(self):
        connector = {'host': 'fake_host',
                     'wwnns': ['1111111111111111',
                               '2222222222222222'],
                     'wwpns': ['3333333333333333',
                               '4444444444444444']
                     }
        expected = ['11:11:11:11:11:11:11:11:33:33:33:33:33:33:33:33',
                    '22:22:22:22:22:22:22:22:44:44:44:44:44:44:44:44']
        ret = self.adapter.get_connector_uids(connector)
        self.assertListEqual(expected, ret)

    def test_get_connection_info_no_targets(self):
        def f():
            host = test_client.MockResource('no_target')
            self.adapter.get_connection_info(12, host, {})

        self.assertRaises(exception.VolumeBackendAPIException, f)

    def test_get_connection_info_auto_zone_enabled(self):
        host = test_client.MockResource('host1')
        connector = {'wwpns': 'abcdefg'}
        ret = self.adapter.get_connection_info(10, host, connector)
        target_wwns = ['100000051e55a100', '100000051e55a121']
        self.assertListEqual(target_wwns, ret['target_wwn'])
        init_target_map = {
            '200000051e55a100': ('100000051e55a100', '100000051e55a121'),
            '200000051e55a121': ('100000051e55a100', '100000051e55a121')}
        self.assertDictEqual(init_target_map, ret['initiator_target_map'])
        self.assertEqual(10, ret['target_lun'])

    def test_get_connection_info_auto_zone_disabled(self):
        self.adapter.lookup_service = None
        host = test_client.MockResource('host1')
        connector = {'wwpns': 'abcdefg'}
        ret = self.adapter.get_connection_info(10, host, connector)
        self.assertEqual(10, ret['target_lun'])
        wwns = ['8899AABBCCDDEEFF', '8899AABBCCDDFFEE']
        self.assertListEqual(wwns, ret['target_wwn'])

    @patch_for_fc_adapter
    def test_initialize_connection_volume(self):
        volume = mock.Mock(provider_location='id^lun_43', id='id_43')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection(volume, connector)
        self.assertEqual('fibre_channel', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('id_43', conn_info['data']['volume_id'])

    @patch_for_fc_adapter
    def test_initialize_connection_snapshot(self):
        snap = mock.Mock(id='snap_1', name='snap_1')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection_snapshot(
            snap, connector)
        self.assertEqual('fibre_channel', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('snap_1', conn_info['data']['volume_id'])

    def test_terminate_connection_auto_zone_enabled(self):
        connector = {'host': 'host1', 'wwpns': 'abcdefg'}
        volume = mock.Mock(provider_location='id^lun_41', id='id_41')
        ret = self.adapter.terminate_connection(volume, connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        data = ret['data']
        target_map = {
            '200000051e55a100': ('100000051e55a100', '100000051e55a121'),
            '200000051e55a121': ('100000051e55a100', '100000051e55a121')}
        self.assertDictEqual(target_map, data['initiator_target_map'])
        target_wwn = ['100000051e55a100', '100000051e55a121']
        self.assertListEqual(target_wwn, data['target_wwn'])

    def test_validate_ports_whitelist_none(self):
        ports = self.adapter.validate_ports(None)
        self.assertEqual(set(('spa_iom_0_fc0', 'spa_iom_0_fc1')), set(ports))

    def test_validate_ports(self):
        ports = self.adapter.validate_ports(['spa_iom_0_fc0'])
        self.assertEqual(set(('spa_iom_0_fc0',)), set(ports))

    def test_validate_ports_asterisk(self):
        ports = self.adapter.validate_ports(['spa*'])
        self.assertEqual(set(('spa_iom_0_fc0', 'spa_iom_0_fc1')), set(ports))

    def test_validate_ports_question_mark(self):
        ports = self.adapter.validate_ports(['spa_iom_0_fc?'])
        self.assertEqual(set(('spa_iom_0_fc0', 'spa_iom_0_fc1')), set(ports))

    def test_validate_ports_no_matched(self):
        with self.assertRaisesRegexp(exception.InvalidConfigurationValue,
                                     'unity_io_ports'):
            self.adapter.validate_ports(['spc_invalid'])

    def test_validate_ports_unmatched_whitelist(self):
        with self.assertRaisesRegexp(exception.InvalidConfigurationValue,
                                     'unity_io_ports'):
            self.adapter.validate_ports(['spa_iom*', 'spc_invalid'])


class ISCSIAdapterTest(unittest.TestCase):
    def setUp(self):
        self.adapter = mock_adapter(adapter.ISCSIAdapter)

    def test_iscsi_protocol(self):
        stats = self.adapter.update_volume_stats()
        self.assertEqual('iSCSI', stats['storage_protocol'])

    def test_get_connector_uids(self):
        connector = {'host': 'fake_host', 'initiator': 'fake_iqn'}
        ret = self.adapter.get_connector_uids(connector)
        self.assertListEqual(['fake_iqn'], ret)

    def test_get_connection_info(self):
        connector = {'host': 'fake_host', 'initiator': 'fake_iqn'}
        hlu = 10
        info = self.adapter.get_connection_info(hlu, None, connector)
        target_iqns = ['iqn.1-1.com.e:c.a.a0', 'iqn.1-1.com.e:c.a.a1']
        target_portals = ['1.2.3.4:1234', '1.2.3.5:1234']
        self.assertListEqual(target_iqns, info['target_iqns'])
        self.assertListEqual([hlu, hlu], info['target_luns'])
        self.assertListEqual(target_portals, info['target_portals'])
        self.assertEqual(hlu, info['target_lun'])
        self.assertTrue(info['target_portal'] in target_portals)
        self.assertTrue(info['target_iqn'] in target_iqns)

    @patch_for_iscsi_adapter
    def test_initialize_connection_volume(self):
        volume = mock.Mock(provider_location='id^lun_43', id='id_43')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection(volume, connector)
        self.assertEqual('iscsi', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('id_43', conn_info['data']['volume_id'])

    @patch_for_iscsi_adapter
    def test_initialize_connection_snapshot(self):
        snap = mock.Mock(id='snap_1', name='snap_1')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection_snapshot(
            snap, connector)
        self.assertEqual('iscsi', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('snap_1', conn_info['data']['volume_id'])
