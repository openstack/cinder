# Copyright (c) 2016 - 2018 Dell Inc. or its subsidiaries.
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

import contextlib
import functools
from unittest import mock

import ddt
from oslo_utils import units

from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.unity \
    import fake_enum as enums
from cinder.tests.unit.volume.drivers.dell_emc.unity \
    import fake_exception as ex
from cinder.tests.unit.volume.drivers.dell_emc.unity import test_client
from cinder.volume.drivers.dell_emc.unity import adapter
from cinder.volume.drivers.dell_emc.unity import client
from cinder.volume.drivers.dell_emc.unity import replication


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
        self.driver_ssl_cert_verify = True
        self.driver_ssl_cert_path = None
        self.remove_empty_host = False

    def safe_get(self, name):
        return getattr(self, name)


class MockConnector(object):
    @staticmethod
    def disconnect_volume(data, device):
        pass


class MockDriver(object):
    def __init__(self):
        self.configuration = mock.Mock(volume_dd_blocksize='1M')
        self.replication_manager = MockReplicationManager()
        self.protocol = 'iSCSI'

    @staticmethod
    def _connect_device(conn):
        return {'connector': MockConnector(),
                'device': {'path': 'dev'},
                'conn': {'data': {}}}

    def get_version(self):
        return '1.0.0'


class MockReplicationManager(object):
    def __init__(self):
        self.is_replication_configured = False
        self.replication_devices = {}
        self.active_backend_id = None
        self.is_service_failed_over = None
        self.default_device = None
        self.active_adapter = None

    def failover_service(self, backend_id):
        if backend_id == 'default':
            self.is_service_failed_over = False
        elif backend_id == 'secondary_unity':
            self.is_service_failed_over = True
        else:
            raise exception.VolumeBackendAPIException()


class MockClient(object):
    def __init__(self):
        self._system = test_client.MockSystem()
        self.host = '10.10.10.10'  # fake unity IP

    @staticmethod
    def get_pools():
        return test_client.MockResourceList(['pool0', 'pool1'])

    @staticmethod
    def create_lun(name, size, pool, description=None, io_limit_policy=None,
                   is_thin=None, is_compressed=None, tiering_policy=None):
        lun_id = name
        if is_thin is not None and not is_thin:
            lun_id += '_thick'
        if tiering_policy:
            if tiering_policy is enums.TieringPolicyEnum.AUTOTIER:
                lun_id += '_auto'
            elif tiering_policy is enums.TieringPolicyEnum.LOWEST:
                lun_id += '_low'
        return test_client.MockResource(_id=lun_id, name=name)

    @staticmethod
    def lun_has_snapshot(lun):
        return lun.name == 'volume_has_snapshot'

    @staticmethod
    def get_lun(name=None, lun_id=None):
        if lun_id is None:
            lun_id = 'lun_4'
        if lun_id in ('lun_43',):  # for thin clone cases
            return test_client.MockResource(_id=lun_id, name=name)
        if name == 'not_exists':
            ret = test_client.MockResource(name=lun_id)
            ret.existed = False
        else:
            if name is None:
                name = lun_id
            ret = test_client.MockResource(_id=lun_id, name=name)
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
        if src_lun_id in ('lun_53', 'lun_55'):  # for thin clone cases
            return test_client.MockResource(
                _id='snap_clone_{}'.format(src_lun_id))
        return test_client.MockResource(name=name, _id=src_lun_id)

    @staticmethod
    def get_snap(name=None):
        if name in ('snap_50',):  # for thin clone cases
            return name
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
    def create_host(name):
        return test_client.MockResource(name=name)

    @staticmethod
    def create_host_wo_lock(name):
        return test_client.MockResource(name=name)

    @staticmethod
    def delete_host_wo_lock(host):
        if host.name == 'empty-host':
            raise ex.HostDeleteIsCalled()

    @staticmethod
    def attach(host, lun_or_snap):
        return 10

    @staticmethod
    def detach(host, lun_or_snap):
        error_ids = ['lun_43', 'snap_0']
        if host.name == 'host1' and lun_or_snap.get_id() in error_ids:
            raise ex.DetachIsCalled()

    @staticmethod
    def detach_all(lun):
        error_ids = ['lun_44']
        if lun.get_id() in error_ids:
            raise ex.DetachAllIsCalled()

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
        mock_io_policy = (test_client.MockResource(name=specs.get('id'))
                          if specs else None)
        return mock_io_policy

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

    @staticmethod
    def thin_clone(obj, name, io_limit_policy, description, new_size_gb):
        if (obj.name, name) in (
                ('snap_61', 'lun_60'), ('lun_63', 'lun_60')):
            return test_client.MockResource(_id=name)
        elif (obj.name, name) in (('snap_71', 'lun_70'), ('lun_72', 'lun_70')):
            raise ex.UnityThinCloneNotAllowedError()
        else:
            raise ex.UnityThinCloneLimitExceededError

    @staticmethod
    def update_host_initiators(host, wwns):
        return None

    @property
    def system(self):
        return self._system

    def restore_snapshot(self, snap_name):
        return test_client.MockResource(name="back_snap")

    def get_pool_id_by_name(self, name):
        pools = {'PoolA': 'pool_1',
                 'PoolB': 'pool_2',
                 'PoolC': 'pool_3'}
        return pools.get(name, None)

    def migrate_lun(self, lun_id, dest_pool_id, provision=None):
        if dest_pool_id == 'pool_2':
            return True
        if dest_pool_id == 'pool_3':
            return False

    def get_remote_system(self, name=None):
        if name == 'not-found-remote-system':
            return None

        return test_client.MockResource(_id='RS_1')

    def get_replication_session(self, name=None):
        if name == 'not-found-rep-session':
            raise client.ClientReplicationError()

        rep_session = test_client.MockResource(_id='rep_session_id_1')
        rep_session.name = name
        rep_session.src_resource_id = 'sv_1'
        rep_session.dst_resource_id = 'sv_99'
        return rep_session

    def create_replication(self, src_lun, max_time_out_of_sync,
                           dst_pool_id, remote_system):
        if (src_lun.get_id() == 'sv_1' and max_time_out_of_sync == 60
                and dst_pool_id == 'pool_1'
                and remote_system.get_id() == 'RS_1'):
            rep_session = test_client.MockResource(_id='rep_session_id_1')
            rep_session.name = 'rep_session_name_1'
            return rep_session
        return None

    def failover_replication(self, rep_session):
        if rep_session.name != 'rep_session_name_1':
            raise client.ClientReplicationError()

    def failback_replication(self, rep_session):
        if rep_session.name != 'rep_session_name_1':
            raise client.ClientReplicationError()

    def is_cg_replicated(self, cg_id):
        return cg_id and 'is_replicated' in cg_id

    def get_cg(self, name):
        return test_client.MockResource(_id=name)

    def create_cg_replication(self, group_id, pool_id, remote_system,
                              max_time):
        if group_id and 'error' in group_id:
            raise Exception('has issue when creating cg replication session.')

    def delete_cg_rep_session(self, group_id):
        if group_id and 'error' in group_id:
            raise Exception('has issue when deleting cg replication session.')

    def failover_cg_rep_session(self, group_id, need_sync):
        if group_id and 'error' in group_id:
            raise Exception('has issue when failover cg replication session.')

    def failback_cg_rep_session(self, group_id):
        if group_id and 'error' in group_id:
            raise Exception('has issue when failback cg replication session.')


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


class MockOSResource(mock.Mock):
    def __init__(self, *args, **kwargs):
        super(MockOSResource, self).__init__(*args, **kwargs)
        if 'name' in kwargs:
            self.name = kwargs['name']
        self.kwargs = kwargs

    def __getitem__(self, key):
        return self.kwargs[key]


def mock_replication_device(device_conf=None, serial_number=None,
                            max_time_out_of_sync=None,
                            destination_pool_id=None):
    if device_conf is None:
        device_conf = {
            'backend_id': 'secondary_unity',
            'san_ip': '2.2.2.2'
        }

    if serial_number is None:
        serial_number = 'SECONDARY_UNITY_SN'

    if max_time_out_of_sync is None:
        max_time_out_of_sync = 60

    if destination_pool_id is None:
        destination_pool_id = 'pool_1'

    rep_device = replication.ReplicationDevice(device_conf, MockDriver())
    rep_device._adapter = mock_adapter(adapter.CommonAdapter)
    rep_device._adapter._serial_number = serial_number
    rep_device.max_time_out_of_sync = max_time_out_of_sync
    rep_device._dst_pool = test_client.MockResource(_id=destination_pool_id)
    return rep_device


def mock_adapter(driver_clz):
    ret = driver_clz()
    ret._client = MockClient()
    with mock.patch('cinder.volume.drivers.dell_emc.unity.adapter.'
                    'CommonAdapter.validate_ports'), patch_storops():
        ret.do_setup(MockDriver(), MockConfig())
    ret.lookup_service = MockLookupService()
    return ret


def get_backend_qos_specs(volume):
    return None


def get_connector_properties():
    return {'host': 'host1', 'wwpns': 'abcdefg'}


def get_lun_pl(name):
    return 'id^%s|system^CLIENT_SERIAL|type^lun|version^None' % name


def get_snap_lun_pl(name):
    return 'id^%s|system^CLIENT_SERIAL|type^snap_lun|version^None' % name


def get_snap_pl(name):
    return 'id^%s|system^CLIENT_SERIAL|type^snapshot|version^None' % name


def get_connector_uids(adapter, connector):
    return []


def get_connection_info(adapter, hlu, host, connector):
    return {}


def get_volume_type_qos_specs(qos_id):
    if qos_id == 'qos':
        return {'qos_specs': {'id': u'qos_type_id_1',
                              'consumer': u'back-end',
                              u'maxBWS': u'102400',
                              u'maxIOPS': u'500'}}
    if qos_id == 'qos_2':
        return {'qos_specs': {'id': u'qos_type_id_2',
                              'consumer': u'back-end',
                              u'maxBWS': u'102402',
                              u'maxIOPS': u'502'}}
    return {'qos_specs': {}}


def get_volume_type_extra_specs(type_id):
    if type_id == 'thick':
        return {'provisioning:type': 'thick',
                'thick_provisioning_support': '<is> True'}
    if type_id == 'tier_auto':
        return {'storagetype:tiering': 'Auto',
                'fast_support': '<is> True'}
    if type_id == 'tier_lowest':
        return {'storagetype:tiering': 'LowestAvailable',
                'fast_support': '<is> True'}
    if type_id == 'compressed':
        return {'provisioning:type': 'compressed',
                'compression_support': '<is> True'}
    return {}


def get_group_type_specs(group_type_id):
    if group_type_id == '':
        return {'consistent_group_snapshot_enabled': '<is> True',
                'group_type_id': group_type_id}
    return {}


def group_is_cg(group):
    return group.id != 'not_cg'


def patch_for_unity_adapter(func):
    @functools.wraps(func)
    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs',
                new=get_volume_type_extra_specs)
    @mock.patch('cinder.volume.group_types.get_group_type_specs',
                new=get_group_type_specs)
    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs',
                new=get_volume_type_qos_specs)
    @mock.patch('cinder.volume.drivers.dell_emc.unity.utils.'
                'get_backend_qos_specs',
                new=get_backend_qos_specs)
    @mock.patch('cinder.volume.drivers.dell_emc.unity.utils.'
                'group_is_cg',
                new=group_is_cg)
    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties',
                new=get_connector_properties)
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


@contextlib.contextmanager
def patch_thin_clone(cloned_lun):
    with mock.patch.object(adapter.CommonAdapter, '_thin_clone') as tc:
        tc.return_value = cloned_lun
        yield tc


@contextlib.contextmanager
def patch_dd_copy(copied_lun):
    with mock.patch.object(adapter.CommonAdapter, '_dd_copy') as dd:
        dd.return_value = copied_lun
        yield dd


@contextlib.contextmanager
def patch_copy_volume():
    with mock.patch('cinder.volume.volume_utils.copy_volume') as mocked:
        yield mocked


@contextlib.contextmanager
def patch_storops():
    with mock.patch.object(adapter, 'storops') as storops:
        storops.ThinCloneActionEnum = mock.Mock(DD_COPY='DD_COPY')
        yield storops


class IdMatcher(object):
    def __init__(self, obj):
        self._obj = obj

    def __eq__(self, other):
        return self._obj._id == other._id


########################
#
#   Start of Tests
#
########################

@ddt.ddt
@mock.patch.object(adapter, 'storops_ex', new=ex)
@mock.patch.object(adapter, 'enums', new=enums)
@mock.patch.object(adapter.volume_utils, 'is_group_a_cg_snapshot_type',
                   new=lambda x: True)
class CommonAdapterTest(test.TestCase):
    def setUp(self):
        super(CommonAdapterTest, self).setUp()
        self.adapter = mock_adapter(adapter.CommonAdapter)

    def test_get_managed_pools(self):
        ret = self.adapter.get_managed_pools()
        self.assertIn('pool1', ret)
        self.assertNotIn('pool0', ret)
        self.assertNotIn('pool2', ret)

    @patch_for_unity_adapter
    def test_create_volume(self):
        volume = MockOSResource(name='lun_3', size=5, host='unity#pool1',
                                group=None)
        ret = self.adapter.create_volume(volume)
        expected = get_lun_pl('lun_3')
        self.assertEqual(expected, ret['provider_location'])

    @patch_for_unity_adapter
    def test_create_volume_thick(self):
        volume = MockOSResource(name='lun_3', size=5, host='unity#pool1',
                                group=None, volume_type_id='thick')
        ret = self.adapter.create_volume(volume)

        expected = get_lun_pl('lun_3_thick')
        self.assertEqual(expected, ret['provider_location'])

    @patch_for_unity_adapter
    def test_create_compressed_volume(self):
        volume_type = MockOSResource(
            extra_specs={'compression_support': '<is> True'})
        volume = MockOSResource(name='lun_3', size=5, host='unity#pool1',
                                group=None, volume_type=volume_type)
        ret = self.adapter.create_volume(volume)
        expected = get_lun_pl('lun_3')
        self.assertEqual(expected, ret['provider_location'])

    @patch_for_unity_adapter
    def test_create_auto_tiering_volume(self):
        volume = MockOSResource(name='lun_3', size=5, host='unity#pool1',
                                group=None, volume_type_id='tier_auto')
        ret = self.adapter.create_volume(volume)
        expected = get_lun_pl('lun_3_auto')
        self.assertEqual(expected, ret['provider_location'])

    @patch_for_unity_adapter
    def test_create_lowest_tiering_volume(self):
        volume = MockOSResource(name='lun_3', size=5, host='unity#pool1',
                                group=None, volume_type_id='tier_lowest')
        ret = self.adapter.create_volume(volume)
        expected = get_lun_pl('lun_3_low')
        self.assertEqual(expected, ret['provider_location'])

    def test_create_snapshot(self):
        volume = MockOSResource(provider_location='id^lun_43')
        snap = MockOSResource(volume=volume, name='abc-def_snap')
        result = self.adapter.create_snapshot(snap)
        self.assertEqual(get_snap_pl('lun_43'), result['provider_location'])
        self.assertEqual('lun_43', result['provider_id'])

    def test_delete_snap(self):
        def f():
            snap = MockOSResource(name='abc-def_snap')
            self.adapter.delete_snapshot(snap)

        self.assertRaises(ex.SnapDeleteIsCalled, f)

    def test_get_lun_id_has_location(self):
        volume = MockOSResource(provider_location='id^lun_43')
        self.assertEqual('lun_43', self.adapter.get_lun_id(volume))

    def test_get_lun_id_no_location(self):
        volume = MockOSResource(provider_location=None)
        self.assertEqual('lun_4', self.adapter.get_lun_id(volume))

    def test_delete_volume(self):
        volume = MockOSResource(provider_location='id^lun_4')
        self.adapter.delete_volume(volume)

    @patch_for_unity_adapter
    def test_retype_volume_has_snapshot(self):
        volume = MockOSResource(name='volume_has_snapshot', size=5,
                                host='HostA@BackendB#PoolB')
        ctxt = None
        diff = None
        new_type = {'name': u'type01', 'id': 'compressed'}
        host = {'host': 'HostA@BackendB#PoolB'}
        result = self.adapter.retype(ctxt, volume, new_type, diff, host)
        self.assertFalse(result)

    @patch_for_unity_adapter
    def test_retype_volume_thick_to_compressed(self):
        volume = MockOSResource(name='thick_volume', size=5,
                                host='HostA@BackendB#PoolA',
                                provider_location='id^lun_33')
        ctxt = None
        diff = None
        new_type = {'name': u'compressed_type', 'id': 'compressed'}
        host = {'host': 'HostA@BackendB#PoolB'}
        result = self.adapter.retype(ctxt, volume, new_type, diff, host)
        self.assertEqual((True, {}), result)

    @patch_for_unity_adapter
    def test_retype_volume_to_compressed(self):
        volume = MockOSResource(name='thin_volume', size=5,
                                host='HostA@BackendB#PoolB')
        ctxt = None
        diff = None
        new_type = {'name': u'compressed_type', 'id': 'compressed'}
        host = {'host': 'HostA@BackendB#PoolB'}
        result = self.adapter.retype(ctxt, volume, new_type, diff, host)
        self.assertTrue(result)

    @patch_for_unity_adapter
    def test_retype_volume_to_qos(self):
        volume = MockOSResource(name='thin_volume', size=5,
                                host='HostA@BackendB#PoolB')
        ctxt = None
        diff = None
        new_type = {'name': u'qos_type', 'id': 'qos'}
        host = {'host': 'HostA@BackendB#PoolB'}
        result = self.adapter.retype(ctxt, volume, new_type,
                                     diff, host)
        self.assertTrue(result)

    @patch_for_unity_adapter
    def test_retype_volume_revert_qos(self):
        volume = MockOSResource(name='qos_volume', size=5,
                                host='HostA@BackendB#PoolB',
                                volume_type_id='qos_2')
        ctxt = None
        diff = None
        new_type = {'name': u'no_qos_type', 'id': ''}
        host = {'host': 'HostA@BackendB#PoolB'}
        result = self.adapter.retype(ctxt, volume, new_type,
                                     diff, host)
        self.assertTrue(result)

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
        self.assertTrue(stats['thick_provisioning_support'])
        self.assertTrue(stats['thin_provisioning_support'])
        self.assertTrue(stats['compression_support'])
        self.assertTrue(stats['consistent_group_snapshot_enabled'])
        self.assertFalse(stats['replication_enabled'])
        self.assertEqual(0, len(stats['replication_targets']))
        self.assertTrue(stats['fast_support'])

    def test_update_volume_stats(self):
        stats = self.adapter.update_volume_stats()
        self.assertEqual('backend', stats['volume_backend_name'])
        self.assertEqual('unknown', stats['storage_protocol'])
        self.assertTrue(stats['thin_provisioning_support'])
        self.assertTrue(stats['thick_provisioning_support'])
        self.assertTrue(stats['consistent_group_snapshot_enabled'])
        self.assertFalse(stats['replication_enabled'])
        self.assertEqual(0, len(stats['replication_targets']))
        self.assertTrue(stats['fast_support'])
        self.assertEqual(1, len(stats['pools']))

    def test_get_replication_stats(self):
        self.adapter.replication_manager.is_replication_configured = True
        self.adapter.replication_manager.replication_devices = {
            'secondary_unity': None
        }

        stats = self.adapter.update_volume_stats()
        self.assertTrue(stats['replication_enabled'])
        self.assertEqual(['secondary_unity'], stats['replication_targets'])

        self.assertEqual(1, len(stats['pools']))
        pool_stats = stats['pools'][0]
        self.assertTrue(pool_stats['replication_enabled'])
        self.assertEqual(['secondary_unity'],
                         pool_stats['replication_targets'])

    def test_serial_number(self):
        self.assertEqual('CLIENT_SERIAL', self.adapter.serial_number)

    def test_do_setup(self):
        self.assertEqual('1.2.3.4', self.adapter.ip)
        self.assertEqual('user', self.adapter.username)
        self.assertEqual('pass', self.adapter.password)
        self.assertTrue(self.adapter.array_cert_verify)
        self.assertIsNone(self.adapter.array_ca_cert_path)

    def test_do_setup_version_before_4_1(self):
        def f():
            with mock.patch('cinder.volume.drivers.dell_emc.unity.adapter.'
                            'CommonAdapter.validate_ports'):
                self.adapter._client.system.system_version = '4.0.0'
                self.adapter.do_setup(self.adapter.driver, MockConfig())

        self.assertRaises(exception.VolumeBackendAPIException, f)

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
            volume = MockOSResource(provider_location='id^lun_43', id='id_43',
                                    volume_attachment=None)
            connector = {'host': 'host1'}
            self.adapter.terminate_connection(volume, connector)

        self.assertRaises(ex.DetachIsCalled, f)

    def test_terminate_connection_force_detach(self):
        def f():
            volume = MockOSResource(provider_location='id^lun_44', id='id_44',
                                    volume_attachment=None)
            self.adapter.terminate_connection(volume, None)

        self.assertRaises(ex.DetachAllIsCalled, f)

    def test_terminate_connection_snapshot(self):
        def f():
            connector = {'host': 'host1'}
            snap = MockOSResource(name='snap_0', id='snap_0',
                                  volume_attachment=None)
            self.adapter.terminate_connection_snapshot(snap, connector)

        self.assertRaises(ex.DetachIsCalled, f)

    def test_terminate_connection_remove_empty_host(self):
        self.adapter.remove_empty_host = True

        def f():
            connector = {'host': 'empty-host'}
            vol = MockOSResource(provider_location='id^lun_45', id='id_45',
                                 volume_attachment=None)
            self.adapter.terminate_connection(vol, connector)

        self.assertRaises(ex.HostDeleteIsCalled, f)

    def test_terminate_connection_multiattached_volume(self):
        def f():
            connector = {'host': 'host1'}
            attachments = [MockOSResource(id='id-1',
                                          attach_status='attached',
                                          attached_host='host1'),
                           MockOSResource(id='id-2',
                                          attach_status='attached',
                                          attached_host='host1')]
            vol = MockOSResource(provider_location='id^lun_45', id='id_45',
                                 volume_attachment=attachments)
            self.adapter.terminate_connection(vol, connector)

        self.assertIsNone(f())

    def test_manage_existing_by_name(self):
        ref = {'source-id': 12}
        volume = MockOSResource(name='lun1')
        ret = self.adapter.manage_existing(volume, ref)
        expected = get_lun_pl('12')
        self.assertEqual(expected, ret['provider_location'])

    def test_manage_existing_by_id(self):
        ref = {'source-name': 'lunx'}
        volume = MockOSResource(name='lun1')
        ret = self.adapter.manage_existing(volume, ref)
        expected = get_lun_pl('lun_4')
        self.assertEqual(expected, ret['provider_location'])

    def test_manage_existing_invalid_ref(self):
        def f():
            ref = {}
            volume = MockOSResource(name='lun1')
            self.adapter.manage_existing(volume, ref)

        self.assertRaises(exception.ManageExistingInvalidReference, f)

    def test_manage_existing_lun_not_found(self):
        def f():
            ref = {'source-name': 'not_exists'}
            volume = MockOSResource(name='lun1')
            self.adapter.manage_existing(volume, ref)

        self.assertRaises(exception.ManageExistingInvalidReference, f)

    @patch_for_unity_adapter
    def test_manage_existing_get_size_invalid_backend(self):
        def f():
            volume = MockOSResource(volume_type_id='thin',
                                    host='host@backend#pool1')
            ref = {'source-id': 12}
            self.adapter.manage_existing_get_size(volume, ref)

        self.assertRaises(exception.ManageExistingInvalidReference, f)

    @patch_for_unity_adapter
    def test_manage_existing_get_size_success(self):
        volume = MockOSResource(volume_type_id='thin',
                                host='host@backend#pool0')
        ref = {'source-id': 12}
        volume_size = self.adapter.manage_existing_get_size(volume, ref)
        self.assertEqual(5, volume_size)

    @patch_for_unity_adapter
    def test_create_volume_from_snapshot(self):
        lun_id = 'lun_50'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1')
        snap_id = 'snap_50'
        snap = MockOSResource(name=snap_id)
        with patch_thin_clone(test_client.MockResource(_id=lun_id)) as tc:
            ret = self.adapter.create_volume_from_snapshot(volume, snap)
            self.assertEqual(get_snap_lun_pl(lun_id),
                             ret['provider_location'])
            tc.assert_called_with(adapter.VolumeParams(self.adapter, volume),
                                  snap_id)

    @patch_for_unity_adapter
    def test_create_cloned_volume_attached(self):
        lun_id = 'lun_51'
        src_lun_id = 'lun_53'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1')
        src_vref = MockOSResource(id=src_lun_id, name=src_lun_id,
                                  provider_location=get_lun_pl(src_lun_id),
                                  volume_attachment=['not_care'])
        with patch_dd_copy(test_client.MockResource(_id=lun_id)) as dd:
            ret = self.adapter.create_cloned_volume(volume, src_vref)
            dd.assert_called_with(
                adapter.VolumeParams(self.adapter, volume),
                IdMatcher(test_client.MockResource(
                    _id='snap_clone_{}'.format(src_lun_id))),
                src_lun=IdMatcher(test_client.MockResource(_id=src_lun_id)))
            self.assertEqual(get_lun_pl(lun_id), ret['provider_location'])

    @patch_for_unity_adapter
    def test_create_cloned_volume_available(self):
        lun_id = 'lun_54'
        src_lun_id = 'lun_55'
        volume = MockOSResource(id=lun_id, host='unity#pool1', size=3,
                                provider_location=get_lun_pl(lun_id))
        src_vref = MockOSResource(id=src_lun_id, name=src_lun_id,
                                  provider_location=get_lun_pl(src_lun_id),
                                  volume_attachment=None)
        with patch_thin_clone(test_client.MockResource(_id=lun_id)) as tc:
            ret = self.adapter.create_cloned_volume(volume, src_vref)
            tc.assert_called_with(
                adapter.VolumeParams(self.adapter, volume),
                IdMatcher(test_client.MockResource(
                    _id='snap_clone_{}'.format(src_lun_id))),
                src_lun=IdMatcher(test_client.MockResource(_id=src_lun_id)))
            self.assertEqual(get_snap_lun_pl(lun_id), ret['provider_location'])

    @patch_for_unity_adapter
    def test_dd_copy_with_src_lun(self):
        lun_id = 'lun_56'
        src_lun_id = 'lun_57'
        src_snap_id = 'snap_57'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1',
                                provider_location=get_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        src_lun = test_client.MockResource(name=src_lun_id, _id=src_lun_id)
        src_lun.size_total = 6 * units.Gi
        with patch_copy_volume() as copy_volume:
            ret = self.adapter._dd_copy(
                adapter.VolumeParams(self.adapter, volume), src_snap,
                src_lun=src_lun)
            copy_volume.assert_called_with('dev', 'dev', 6144, '1M',
                                           sparse=True)
            self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)),
                             ret)

    @patch_for_unity_adapter
    def test_dd_copy_wo_src_lun(self):
        lun_id = 'lun_58'
        src_lun_id = 'lun_59'
        src_snap_id = 'snap_59'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1',
                                provider_location=get_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        src_snap.size = 5 * units.Gi
        src_snap.storage_resource = test_client.MockResource(name=src_lun_id,
                                                             _id=src_lun_id)
        with patch_copy_volume() as copy_volume:
            ret = self.adapter._dd_copy(
                adapter.VolumeParams(self.adapter, volume), src_snap)
            copy_volume.assert_called_with('dev', 'dev', 5120, '1M',
                                           sparse=True)
            self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)),
                             ret)

    @patch_for_unity_adapter
    def test_dd_copy_raise(self):
        lun_id = 'lun_58'
        src_snap_id = 'snap_59'
        volume = MockOSResource(name=lun_id, id=lun_id, host='unity#pool1',
                                provider_location=get_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        with patch_copy_volume() as copy_volume:
            copy_volume.side_effect = AttributeError
            self.assertRaises(AttributeError,
                              self.adapter._dd_copy, volume, src_snap)

    @patch_for_unity_adapter
    def test_thin_clone(self):
        lun_id = 'lun_60'
        src_snap_id = 'snap_61'
        volume = MockOSResource(name=lun_id, id=lun_id, size=1,
                                provider_location=get_snap_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        ret = self.adapter._thin_clone(volume, src_snap)
        self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)), ret)

    @patch_for_unity_adapter
    def test_thin_clone_downgraded_with_src_lun(self):
        lun_id = 'lun_60'
        src_snap_id = 'snap_62'
        src_lun_id = 'lun_62'
        volume = MockOSResource(name=lun_id, id=lun_id, size=1,
                                provider_location=get_snap_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        src_lun = test_client.MockResource(name=src_lun_id, _id=src_lun_id)
        new_dd_lun = test_client.MockResource(name='lun_63')
        with patch_storops() as mocked_storops, \
                patch_dd_copy(new_dd_lun) as dd:
            ret = self.adapter._thin_clone(
                adapter.VolumeParams(self.adapter, volume),
                src_snap, src_lun=src_lun)
            vol_params = adapter.VolumeParams(self.adapter, volume)
            vol_params.name = 'hidden-{}'.format(volume.name)
            vol_params.description = 'hidden-{}'.format(volume.description)
            dd.assert_called_with(vol_params, src_snap, src_lun=src_lun)
            mocked_storops.TCHelper.notify.assert_called_with(src_lun,
                                                              'DD_COPY',
                                                              new_dd_lun)
        self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)), ret)

    @patch_for_unity_adapter
    def test_thin_clone_downgraded_wo_src_lun(self):
        lun_id = 'lun_60'
        src_snap_id = 'snap_62'
        volume = MockOSResource(name=lun_id, id=lun_id, size=1,
                                provider_location=get_snap_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        new_dd_lun = test_client.MockResource(name='lun_63')
        with patch_storops() as mocked_storops, \
                patch_dd_copy(new_dd_lun) as dd:
            ret = self.adapter._thin_clone(
                adapter.VolumeParams(self.adapter, volume), src_snap)
            vol_params = adapter.VolumeParams(self.adapter, volume)
            vol_params.name = 'hidden-{}'.format(volume.name)
            vol_params.description = 'hidden-{}'.format(volume.description)
            dd.assert_called_with(vol_params, src_snap, src_lun=None)
            mocked_storops.TCHelper.notify.assert_called_with(src_snap,
                                                              'DD_COPY',
                                                              new_dd_lun)
        self.assertEqual(IdMatcher(test_client.MockResource(_id=lun_id)), ret)

    @patch_for_unity_adapter
    def test_thin_clone_thick(self):
        lun_id = 'lun_70'
        src_snap_id = 'snap_71'
        volume = MockOSResource(name=lun_id, id=lun_id, size=1,
                                provider_location=get_snap_lun_pl(lun_id))
        src_snap = test_client.MockResource(name=src_snap_id, _id=src_snap_id)
        new_dd_lun = test_client.MockResource(name='lun_73')
        with patch_storops(), patch_dd_copy(new_dd_lun) as dd:
            vol_params = adapter.VolumeParams(self.adapter, volume)
            ret = self.adapter._thin_clone(vol_params, src_snap)
            dd.assert_called_with(vol_params, src_snap, src_lun=None)
        self.assertEqual(ret, new_dd_lun)

    def test_extend_volume_error(self):
        def f():
            volume = MockOSResource(id='l56',
                                    provider_location=get_lun_pl('lun56'))
            self.adapter.extend_volume(volume, -1)

        self.assertRaises(ex.ExtendLunError, f)

    def test_extend_volume_no_id(self):
        def f():
            volume = MockOSResource(provider_location='type^lun')
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
        with self.assertRaisesRegex(exception.InvalidConfigurationValue,
                                    'unity_storage_pool_names'):
            config = MockConfig()
            config.unity_storage_pool_names = ['', '    ']
            self.adapter.normalize_config(config)
        with self.assertRaisesRegex(exception.InvalidConfigurationValue,
                                    'unity_io_ports'):
            config = MockConfig()
            config.unity_io_ports = ['', '   ']
            self.adapter.normalize_config(config)

    def test_restore_snapshot(self):
        volume = MockOSResource(id='1', name='vol_1')
        snapshot = MockOSResource(id='2', name='snap_1')
        self.adapter.restore_snapshot(volume, snapshot)

    def test_get_pool_id_by_name(self):
        pool_name = 'PoolA'
        pool_id = self.adapter.get_pool_id_by_name(pool_name)
        self.assertEqual('pool_1', pool_id)

    def test_migrate_volume(self):
        provider_location = 'id^1|system^FNM001|type^lun|version^05.00'
        volume = MockOSResource(id='1', name='vol_1',
                                host='HostA@BackendB#PoolA',
                                provider_location=provider_location)
        host = {'host': 'HostA@BackendB#PoolB'}
        ret = self.adapter.migrate_volume(volume, host)
        self.assertEqual((True, {}), ret)

    def test_migrate_volume_failed(self):
        provider_location = 'id^1|system^FNM001|type^lun|version^05.00'
        volume = MockOSResource(id='1', name='vol_1',
                                host='HostA@BackendB#PoolA',
                                provider_location=provider_location)
        host = {'host': 'HostA@BackendB#PoolC'}
        ret = self.adapter.migrate_volume(volume, host)
        self.assertEqual((False, None), ret)

    def test_migrate_volume_cross_backends(self):
        provider_location = 'id^1|system^FNM001|type^lun|version^05.00'
        volume = MockOSResource(id='1', name='vol_1',
                                host='HostA@BackendA#PoolA',
                                provider_location=provider_location)
        host = {'host': 'HostA@BackendB#PoolB'}
        ret = self.adapter.migrate_volume(volume, host)
        self.assertEqual((False, None), ret)

    @ddt.unpack
    @ddt.data((('group-1', 'group-1_name', 'group-1_description'),
               ('group-1', 'group-1_description')),
              (('group-2', 'group-2_name', None), ('group-2', 'group-2_name')),
              (('group-3', 'group-3_name', ''), ('group-3', 'group-3_name')))
    def test_create_group(self, inputs, expected):
        cg_id, cg_name, cg_description = inputs
        cg = MockOSResource(id=cg_id, name=cg_name, description=cg_description)
        with mock.patch.object(self.adapter.client, 'create_cg',
                               create=True) as mocked:
            model_update = self.adapter.create_group(cg)
            self.assertEqual('available', model_update['status'])
            mocked.assert_called_once_with(expected[0],
                                           description=expected[1])

    def test_delete_group(self):
        cg = MockOSResource(id='group-1')
        with mock.patch.object(self.adapter.client, 'delete_cg',
                               create=True) as mocked:
            ret = self.adapter.delete_group(cg)
            self.assertIsNone(ret[0])
            self.assertIsNone(ret[1])
            mocked.assert_called_once_with('group-1')

    def test_update_group(self):
        cg = MockOSResource(id='group-1')
        add_volumes = [MockOSResource(id=vol_id,
                                      provider_location=get_lun_pl(lun_id))
                       for vol_id, lun_id in (('volume-1', 'sv_1'),
                                              ('volume-2', 'sv_2'))]
        remove_volumes = [MockOSResource(
            id='volume-3', provider_location=get_lun_pl('sv_3'))]
        with mock.patch.object(self.adapter.client, 'update_cg',
                               create=True) as mocked:
            ret = self.adapter.update_group(cg, add_volumes, remove_volumes)
            self.assertEqual('available', ret[0]['status'])
            self.assertIsNone(ret[1])
            self.assertIsNone(ret[2])
            mocked.assert_called_once_with('group-1', {'sv_1', 'sv_2'},
                                           {'sv_3'})

    def test_update_group_add_volumes_none(self):
        cg = MockOSResource(id='group-1')
        remove_volumes = [MockOSResource(
            id='volume-3', provider_location=get_lun_pl('sv_3'))]
        with mock.patch.object(self.adapter.client, 'update_cg',
                               create=True) as mocked:
            ret = self.adapter.update_group(cg, None, remove_volumes)
            self.assertEqual('available', ret[0]['status'])
            self.assertIsNone(ret[1])
            self.assertIsNone(ret[2])
            mocked.assert_called_once_with('group-1', set(), {'sv_3'})

    def test_update_group_remove_volumes_none(self):
        cg = MockOSResource(id='group-1')
        add_volumes = [MockOSResource(id=vol_id,
                                      provider_location=get_lun_pl(lun_id))
                       for vol_id, lun_id in (('volume-1', 'sv_1'),
                                              ('volume-2', 'sv_2'))]
        with mock.patch.object(self.adapter.client, 'update_cg',
                               create=True) as mocked:
            ret = self.adapter.update_group(cg, add_volumes, None)
            self.assertEqual('available', ret[0]['status'])
            self.assertIsNone(ret[1])
            self.assertIsNone(ret[2])
            mocked.assert_called_once_with('group-1', {'sv_1', 'sv_2'}, set())

    def test_update_group_add_remove_volumes_none(self):
        cg = MockOSResource(id='group-1')
        with mock.patch.object(self.adapter.client, 'update_cg',
                               create=True) as mocked:
            ret = self.adapter.update_group(cg, None, None)
            self.assertEqual('available', ret[0]['status'])
            self.assertIsNone(ret[1])
            self.assertIsNone(ret[2])
            mocked.assert_called_once_with('group-1', set(), set())

    @patch_for_unity_adapter
    def test_copy_luns_in_group(self):
        cg = MockOSResource(id='group-1')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        src_cg_snap = test_client.MockResource(_id='id_src_cg_snap')
        src_volumes = [MockOSResource(id=vol_id,
                                      provider_location=get_lun_pl(lun_id))
                       for vol_id, lun_id in (('volume-1', 'sv_1'),
                                              ('volume-2', 'sv_2'))]
        copied_luns = [test_client.MockResource(_id=lun_id)
                       for lun_id in ('sv_3', 'sv_4')]

        def _prepare_lun_snaps(lun_id):
            lun_snap = test_client.MockResource(_id='snap_{}'.format(lun_id))
            lun_snap.lun = test_client.MockResource(_id=lun_id)
            return lun_snap

        lun_snaps = list(map(_prepare_lun_snaps, ('sv_1', 'sv_2')))
        with mock.patch.object(self.adapter.client, 'filter_snaps_in_cg_snap',
                               create=True) as mocked_filter, \
                mock.patch.object(self.adapter.client, 'create_cg',
                                  create=True) as mocked_create_cg, \
                patch_dd_copy(None) as mocked_dd:
            mocked_filter.return_value = lun_snaps
            mocked_dd.side_effect = copied_luns

            ret = self.adapter.copy_luns_in_group(cg, volumes, src_cg_snap,
                                                  src_volumes)

            mocked_filter.assert_called_once_with('id_src_cg_snap')
            dd_args = zip([adapter.VolumeParams(self.adapter, vol)
                           for vol in volumes],
                          lun_snaps)
            mocked_dd.assert_has_calls([mock.call(*args) for args in dd_args])
            mocked_create_cg.assert_called_once_with('group-1',
                                                     lun_add=copied_luns)
            self.assertEqual('available', ret[0]['status'])
            self.assertEqual(2, len(ret[1]))
            for vol_id in ('volume-3', 'volume-4'):
                self.assertIn({'id': vol_id, 'status': 'available'}, ret[1])

    def test_create_group_from_snap(self):
        cg = MockOSResource(id='group-2')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        cg_snap = MockOSResource(id='snap-group-1')
        vol_1 = MockOSResource(id='volume-1')
        vol_2 = MockOSResource(id='volume-2')
        vol_snaps = [MockOSResource(id='snap-volume-1', volume=vol_1),
                     MockOSResource(id='snap-volume-2', volume=vol_2)]

        src_cg_snap = test_client.MockResource(_id='id_src_cg_snap')
        with mock.patch.object(self.adapter.client, 'get_snap',
                               create=True, return_value=src_cg_snap), \
                mock.patch.object(self.adapter, 'copy_luns_in_group',
                                  create=True) as mocked_copy:
            mocked_copy.return_value = ({'status': 'available'},
                                        [{'id': 'volume-3',
                                          'status': 'available'},
                                         {'id': 'volume-4',
                                          'status': 'available'}])
            ret = self.adapter.create_group_from_snap(cg, volumes, cg_snap,
                                                      vol_snaps)

            mocked_copy.assert_called_once_with(cg, volumes, src_cg_snap,
                                                [vol_1, vol_2])
            self.assertEqual('available', ret[0]['status'])
            self.assertEqual(2, len(ret[1]))
            for vol_id in ('volume-3', 'volume-4'):
                self.assertIn({'id': vol_id, 'status': 'available'}, ret[1])

    def test_create_group_from_snap_none_snapshots(self):
        cg = MockOSResource(id='group-2')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        cg_snap = MockOSResource(id='snap-group-1')

        src_cg_snap = test_client.MockResource(_id='id_src_cg_snap')
        with mock.patch.object(self.adapter.client, 'get_snap',
                               create=True, return_value=src_cg_snap), \
                mock.patch.object(self.adapter, 'copy_luns_in_group',
                                  create=True) as mocked_copy:
            mocked_copy.return_value = ({'status': 'available'},
                                        [{'id': 'volume-3',
                                          'status': 'available'},
                                         {'id': 'volume-4',
                                          'status': 'available'}])
            ret = self.adapter.create_group_from_snap(cg, volumes, cg_snap,
                                                      None)

            mocked_copy.assert_called_once_with(cg, volumes, src_cg_snap, [])
            self.assertEqual('available', ret[0]['status'])
            self.assertEqual(2, len(ret[1]))
            for vol_id in ('volume-3', 'volume-4'):
                self.assertIn({'id': vol_id, 'status': 'available'}, ret[1])

    def test_create_cloned_group(self):
        cg = MockOSResource(id='group-2')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        src_cg = MockOSResource(id='group-1')
        vol_1 = MockOSResource(id='volume-1')
        vol_2 = MockOSResource(id='volume-2')
        src_vols = [vol_1, vol_2]

        src_cg_snap = test_client.MockResource(_id='id_src_cg_snap')
        with mock.patch.object(self.adapter.client, 'create_cg_snap',
                               create=True,
                               return_value=src_cg_snap) as mocked_create, \
                mock.patch.object(self.adapter, 'copy_luns_in_group',
                                  create=True) as mocked_copy:
            mocked_create.__name__ = 'create_cg_snap'
            mocked_copy.return_value = ({'status': 'available'},
                                        [{'id': 'volume-3',
                                          'status': 'available'},
                                         {'id': 'volume-4',
                                          'status': 'available'}])
            ret = self.adapter.create_cloned_group(cg, volumes, src_cg,
                                                   src_vols)

            mocked_create.assert_called_once_with('group-1',
                                                  'snap_clone_group_group-1')

            mocked_copy.assert_called_once_with(cg, volumes, src_cg_snap,
                                                [vol_1, vol_2])
            self.assertEqual('available', ret[0]['status'])
            self.assertEqual(2, len(ret[1]))
            for vol_id in ('volume-3', 'volume-4'):
                self.assertIn({'id': vol_id, 'status': 'available'}, ret[1])

    def test_create_cloned_group_none_source_vols(self):
        cg = MockOSResource(id='group-2')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        src_cg = MockOSResource(id='group-1')

        src_cg_snap = test_client.MockResource(_id='id_src_cg_snap')
        with mock.patch.object(self.adapter.client, 'create_cg_snap',
                               create=True,
                               return_value=src_cg_snap) as mocked_create, \
                mock.patch.object(self.adapter, 'copy_luns_in_group',
                                  create=True) as mocked_copy:
            mocked_create.__name__ = 'create_cg_snap'
            mocked_copy.return_value = ({'status': 'available'},
                                        [{'id': 'volume-3',
                                          'status': 'available'},
                                         {'id': 'volume-4',
                                          'status': 'available'}])
            ret = self.adapter.create_cloned_group(cg, volumes, src_cg,
                                                   None)

            mocked_create.assert_called_once_with('group-1',
                                                  'snap_clone_group_group-1')

            mocked_copy.assert_called_once_with(cg, volumes, src_cg_snap, [])
            self.assertEqual('available', ret[0]['status'])
            self.assertEqual(2, len(ret[1]))
            for vol_id in ('volume-3', 'volume-4'):
                self.assertIn({'id': vol_id, 'status': 'available'}, ret[1])

    def test_create_group_snapshot(self):
        cg_snap = MockOSResource(id='snap-group-1', group_id='group-1')
        vol_1 = MockOSResource(id='volume-1')
        vol_2 = MockOSResource(id='volume-2')
        vol_snaps = [MockOSResource(id='snap-volume-1', volume=vol_1),
                     MockOSResource(id='snap-volume-2', volume=vol_2)]
        with mock.patch.object(self.adapter.client, 'create_cg_snap',
                               create=True) as mocked_create:
            mocked_create.return_value = ({'status': 'available'},
                                          [{'id': 'snap-volume-1',
                                            'status': 'available'},
                                           {'id': 'snap-volume-2',
                                            'status': 'available'}])
            ret = self.adapter.create_group_snapshot(cg_snap, vol_snaps)

            mocked_create.assert_called_once_with('group-1',
                                                  snap_name='snap-group-1')
            self.assertEqual({'status': 'available'}, ret[0])
            self.assertEqual(2, len(ret[1]))
            for snap_id in ('snap-volume-1', 'snap-volume-2'):
                self.assertIn({'id': snap_id, 'status': 'available'}, ret[1])

    def test_delete_group_snapshot(self):
        group_snap = MockOSResource(id='snap-group-1')
        cg_snap = test_client.MockResource(_id='snap_cg_1')
        with mock.patch.object(self.adapter.client, 'get_snap',
                               create=True,
                               return_value=cg_snap) as mocked_get, \
                mock.patch.object(self.adapter.client, 'delete_snap',
                                  create=True) as mocked_delete:
            ret = self.adapter.delete_group_snapshot(group_snap)
            mocked_get.assert_called_once_with('snap-group-1')
            mocked_delete.assert_called_once_with(cg_snap)
            self.assertEqual((None, None), ret)

    def test_setup_replications(self):
        secondary_device = mock_replication_device()

        self.adapter.replication_manager.is_replication_configured = True
        self.adapter.replication_manager.replication_devices = {
            'secondary_unity': secondary_device
        }
        model_update = self.adapter.setup_replications(
            test_client.MockResource(_id='sv_1'), {})

        self.assertIn('replication_status', model_update)
        self.assertEqual('enabled', model_update['replication_status'])

        self.assertIn('replication_driver_data', model_update)
        self.assertEqual('{"secondary_unity": "rep_session_name_1"}',
                         model_update['replication_driver_data'])

    def test_setup_replications_not_configured_replication(self):
        model_update = self.adapter.setup_replications(
            test_client.MockResource(_id='sv_1'), {})
        self.assertEqual(0, len(model_update))

    def test_setup_replications_raise(self):
        secondary_device = mock_replication_device(
            serial_number='not-found-remote-system')

        self.adapter.replication_manager.is_replication_configured = True
        self.adapter.replication_manager.replication_devices = {
            'secondary_unity': secondary_device
        }

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.adapter.setup_replications,
                          test_client.MockResource(_id='sv_1'),
                          {})

    @ddt.data({'failover_to': 'secondary_unity'},
              {'failover_to': None})
    @ddt.unpack
    def test_failover(self, failover_to):
        secondary_id = 'secondary_unity'
        secondary_device = mock_replication_device()
        self.adapter.replication_manager.is_replication_configured = True
        self.adapter.replication_manager.replication_devices = {
            secondary_id: secondary_device
        }

        volume = MockOSResource(
            id='volume-id-1',
            name='volume-name-1',
            replication_driver_data='{"secondary_unity":"rep_session_name_1"}')
        model_update = self.adapter.failover([volume],
                                             secondary_id=failover_to)
        self.assertEqual(3, len(model_update))
        active_backend_id, volumes_update, groups_update = model_update
        self.assertEqual(secondary_id, active_backend_id)
        self.assertEqual([], groups_update)

        self.assertEqual(1, len(volumes_update))
        model_update = volumes_update[0]
        self.assertIn('volume_id', model_update)
        self.assertEqual('volume-id-1', model_update['volume_id'])
        self.assertIn('updates', model_update)
        self.assertEqual(
            {'provider_id': 'sv_99',
             'provider_location':
                 'id^sv_99|system^SECONDARY_UNITY_SN|type^lun|version^None'},
            model_update['updates'])
        self.assertTrue(
            self.adapter.replication_manager.is_service_failed_over)

    def test_failover_raise(self):
        secondary_id = 'secondary_unity'
        secondary_device = mock_replication_device()
        self.adapter.replication_manager.is_replication_configured = True
        self.adapter.replication_manager.replication_devices = {
            secondary_id: secondary_device
        }

        vol1 = MockOSResource(
            id='volume-id-1',
            name='volume-name-1',
            replication_driver_data='{"secondary_unity":"rep_session_name_1"}')
        vol2 = MockOSResource(
            id='volume-id-2',
            name='volume-name-2',
            replication_driver_data='{"secondary_unity":"rep_session_name_2"}')
        model_update = self.adapter.failover([vol1, vol2],
                                             secondary_id=secondary_id)
        active_backend_id, volumes_update, groups_update = model_update
        self.assertEqual(secondary_id, active_backend_id)
        self.assertEqual([], groups_update)

        self.assertEqual(2, len(volumes_update))
        m = volumes_update[0]
        self.assertIn('volume_id', m)
        self.assertEqual('volume-id-1', m['volume_id'])
        self.assertIn('updates', m)
        self.assertEqual(
            {'provider_id': 'sv_99',
             'provider_location':
                 'id^sv_99|system^SECONDARY_UNITY_SN|type^lun|version^None'},
            m['updates'])

        m = volumes_update[1]
        self.assertIn('volume_id', m)
        self.assertEqual('volume-id-2', m['volume_id'])
        self.assertIn('updates', m)
        self.assertEqual({'replication_status': 'failover-error'},
                         m['updates'])

        self.assertTrue(
            self.adapter.replication_manager.is_service_failed_over)

    def test_failover_failback(self):
        secondary_id = 'secondary_unity'
        secondary_device = mock_replication_device()
        self.adapter.replication_manager.is_replication_configured = True
        self.adapter.replication_manager.replication_devices = {
            secondary_id: secondary_device
        }
        default_device = mock_replication_device(
            device_conf={
                'backend_id': 'default',
                'san_ip': '10.10.10.10'
            }, serial_number='PRIMARY_UNITY_SN'
        )
        self.adapter.replication_manager.default_device = default_device
        self.adapter.replication_manager.active_adapter = (
            self.adapter.replication_manager.replication_devices[
                secondary_id].adapter)
        self.adapter.replication_manager.active_backend_id = secondary_id

        volume = MockOSResource(
            id='volume-id-1',
            name='volume-name-1',
            replication_driver_data='{"secondary_unity":"rep_session_name_1"}')
        model_update = self.adapter.failover([volume],
                                             secondary_id='default')
        active_backend_id, volumes_update, groups_update = model_update
        self.assertEqual('default', active_backend_id)
        self.assertEqual([], groups_update)

        self.assertEqual(1, len(volumes_update))
        model_update = volumes_update[0]
        self.assertIn('volume_id', model_update)
        self.assertEqual('volume-id-1', model_update['volume_id'])
        self.assertIn('updates', model_update)
        self.assertEqual(
            {'provider_id': 'sv_1',
             'provider_location':
                 'id^sv_1|system^PRIMARY_UNITY_SN|type^lun|version^None'},
            model_update['updates'])
        self.assertFalse(
            self.adapter.replication_manager.is_service_failed_over)

    @patch_for_unity_adapter
    def test_failed_enable_replication(self):
        cg = MockOSResource(id='not_cg', name='cg_name',
                            description='cg_description')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        self.assertRaises(exception.InvalidGroupType,
                          self.adapter.enable_replication, None,
                          cg, volumes)

    @patch_for_unity_adapter
    def test_enable_replication(self):
        cg = MockOSResource(id='test_cg_1', name='cg_name',
                            description='cg_description')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        secondary_device = mock_replication_device()
        self.adapter.replication_manager.replication_devices = {
            'secondary_unity': secondary_device
        }
        result = self.adapter.enable_replication(None, cg, volumes)
        self.assertEqual(({'replication_status': 'enabled'}, None), result)

    @patch_for_unity_adapter
    def test_cannot_disable_replication_on_generic_group(self):
        cg = MockOSResource(id='not_cg', name='cg_name',
                            description='cg_description')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        self.assertRaises(exception.InvalidGroupType,
                          self.adapter.disable_replication, None,
                          cg, volumes)

    @patch_for_unity_adapter
    def test_disable_replication(self):
        cg = MockOSResource(id='cg_is_replicated', name='cg_name',
                            description='cg_description')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        result = self.adapter.disable_replication(None, cg, volumes)
        self.assertEqual(({'replication_status': 'disabled'}, None), result)

    @patch_for_unity_adapter
    def test_failover_replication(self):
        cg = MockOSResource(id='cg_is_replicated', name='cg_name',
                            description='cg_description')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        real_secondary_id = 'secondary_unity'
        secondary_device = mock_replication_device()
        self.adapter.replication_manager.replication_devices = {
            real_secondary_id: secondary_device
        }
        result = self.adapter.failover_replication(None, cg, volumes,
                                                   real_secondary_id)
        self.assertEqual(({'replication_status': 'failed-over'},
                          [{'id': 'volume-3',
                            'replication_status': 'failed-over'},
                           {'id': 'volume-4',
                            'replication_status': 'failed-over'}]), result)

    @patch_for_unity_adapter
    def test_failback_replication(self):
        cg = MockOSResource(id='cg_is_replicated', name='cg_name',
                            description='cg_description')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        input_secondary_id = 'default'
        real_secondary_id = 'secondary_unity'
        secondary_device = mock_replication_device()
        self.adapter.replication_manager.replication_devices = {
            real_secondary_id: secondary_device
        }
        result = self.adapter.failover_replication(None, cg, volumes,
                                                   input_secondary_id)
        self.assertEqual(({'replication_status': 'enabled'},
                          [{'id': 'volume-3',
                            'replication_status': 'enabled'},
                           {'id': 'volume-4',
                            'replication_status': 'enabled'}]),
                         result)

        failed_cg = MockOSResource(id='cg_is_replicated_but_has_error',
                                   name='cg_name',
                                   description='cg_description')
        failed_result = self.adapter.failover_replication(
            None, failed_cg, volumes, real_secondary_id)
        self.assertEqual(({'replication_status': 'error'},
                          [{'id': 'volume-3',
                            'replication_status': 'error'},
                           {'id': 'volume-4',
                            'replication_status': 'error'}]), failed_result)

    @patch_for_unity_adapter
    def test_failover_replication_error(self):
        cg = MockOSResource(id='cg_is_replicated_but_has_error',
                            name='cg_name',
                            description='cg_description')
        volumes = [MockOSResource(id=vol_id,
                                  provider_location=get_lun_pl(lun_id))
                   for vol_id, lun_id in (('volume-3', 'sv_3'),
                                          ('volume-4', 'sv_4'))]
        real_secondary_id = 'default'
        secondary_device = mock_replication_device()
        self.adapter.replication_manager.replication_devices = {
            real_secondary_id: secondary_device
        }
        result = self.adapter.failover_replication(
            None, cg, volumes, real_secondary_id)
        self.assertEqual(({'replication_status': 'error'},
                          [{'id': 'volume-3',
                            'replication_status': 'error'},
                           {'id': 'volume-4',
                            'replication_status': 'error'}]), result)


class FCAdapterTest(test.TestCase):
    def setUp(self):
        super(FCAdapterTest, self).setUp()
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
        volume = MockOSResource(provider_location='id^lun_43', id='id_43')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection(volume, connector)
        self.assertEqual('fibre_channel', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('id_43', conn_info['data']['volume_id'])

    @patch_for_fc_adapter
    def test_initialize_connection_snapshot(self):
        snap = MockOSResource(id='snap_1', name='snap_1')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection_snapshot(
            snap, connector)
        self.assertEqual('fibre_channel', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('snap_1', conn_info['data']['volume_id'])

    def test_terminate_connection_auto_zone_enabled(self):
        connector = {'host': 'host1', 'wwpns': 'abcdefg'}
        volume = MockOSResource(provider_location='id^lun_41', id='id_41',
                                volume_attachment=None)
        ret = self.adapter.terminate_connection(volume, connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        data = ret['data']
        target_map = {
            '200000051e55a100': ('100000051e55a100', '100000051e55a121'),
            '200000051e55a121': ('100000051e55a100', '100000051e55a121')}
        self.assertDictEqual(target_map, data['initiator_target_map'])
        target_wwn = ['100000051e55a100', '100000051e55a121']
        self.assertListEqual(target_wwn, data['target_wwn'])

    def test_terminate_connection_auto_zone_enabled_none_host_luns(self):
        connector = {'host': 'host-no-host_luns', 'wwpns': 'abcdefg'}
        volume = MockOSResource(provider_location='id^lun_41', id='id_41',
                                volume_attachment=None)
        ret = self.adapter.terminate_connection(volume, connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        data = ret['data']
        target_map = {
            '200000051e55a100': ('100000051e55a100', '100000051e55a121'),
            '200000051e55a121': ('100000051e55a100', '100000051e55a121')}
        self.assertDictEqual(target_map, data['initiator_target_map'])
        target_wwn = ['100000051e55a100', '100000051e55a121']
        self.assertListEqual(target_wwn, data['target_wwn'])

    def test_terminate_connection_remove_empty_host_return_data(self):
        self.adapter.remove_empty_host = True
        connector = {'host': 'empty-host-return-data', 'wwpns': 'abcdefg'}
        volume = MockOSResource(provider_location='id^lun_41', id='id_41',
                                volume_attachment=None)
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
        with self.assertRaisesRegex(exception.InvalidConfigurationValue,
                                    'unity_io_ports'):
            self.adapter.validate_ports(['spc_invalid'])

    def test_validate_ports_unmatched_whitelist(self):
        with self.assertRaisesRegex(exception.InvalidConfigurationValue,
                                    'unity_io_ports'):
            self.adapter.validate_ports(['spa_iom*', 'spc_invalid'])


class ISCSIAdapterTest(test.TestCase):
    def setUp(self):
        super(ISCSIAdapterTest, self).setUp()
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
        self.assertIn(info['target_portal'], target_portals)
        self.assertIn(info['target_iqn'], target_iqns)

    @patch_for_iscsi_adapter
    def test_initialize_connection_volume(self):
        volume = MockOSResource(provider_location='id^lun_43', id='id_43')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection(volume, connector)
        self.assertEqual('iscsi', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('id_43', conn_info['data']['volume_id'])

    @patch_for_iscsi_adapter
    def test_initialize_connection_snapshot(self):
        snap = MockOSResource(id='snap_1', name='snap_1')
        connector = {'host': 'host1'}
        conn_info = self.adapter.initialize_connection_snapshot(
            snap, connector)
        self.assertEqual('iscsi', conn_info['driver_volume_type'])
        self.assertTrue(conn_info['data']['target_discovered'])
        self.assertEqual('snap_1', conn_info['data']['volume_id'])
