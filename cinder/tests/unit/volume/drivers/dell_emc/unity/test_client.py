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
import unittest
from unittest import mock

import ddt
from oslo_utils import units

from cinder import coordination
from cinder.tests.unit.volume.drivers.dell_emc.unity \
    import fake_enum as enums
from cinder.tests.unit.volume.drivers.dell_emc.unity \
    import fake_exception as ex
from cinder.volume.drivers.dell_emc.unity import client


########################
#
#   Start of Mocks
#
########################


class MockResource(object):
    def __init__(self, name=None, _id=None):
        self.name = name
        self._id = _id
        self.existed = True
        self.size_total = 5 * units.Gi
        self.size_subscribed = 6 * units.Gi
        self.size_free = 2 * units.Gi
        self.is_auto_delete = None
        self.initiator_id = []
        self.alu_hlu_map = {'already_attached': 99}
        self.ip_address = None
        self.is_logged_in = None
        self.wwn = None
        self.max_iops = None
        self.max_kbps = None
        self.pool_name = 'Pool0'
        self._storage_resource = None
        self.host_cache = []
        self.is_thin = None
        self.is_all_flash = True
        self.description = None
        self.luns = None
        self.lun = None
        self.tiering_policy = None
        self.pool_fast_vp = None
        self.snap = True

    @property
    def id(self):
        return self._id

    def get_id(self):
        return self._id

    def delete(self, force_snap_delete=None):
        if self.get_id() in ['snap_2']:
            raise ex.SnapDeleteIsCalled()
        elif self.get_id() == 'not_found':
            raise ex.UnityResourceNotFoundError()
        elif self.get_id() == 'snap_in_use':
            raise ex.UnityDeleteAttachedSnapError()
        elif self.name == 'empty-host':
            raise ex.HostDeleteIsCalled()
        elif self.get_id() == 'lun_in_replication':
            if not force_snap_delete:
                raise ex.UnityDeleteLunInReplicationError()
        elif self.get_id() == 'lun_rep_session_1':
            raise ex.UnityResourceNotFoundError()

    @property
    def pool(self):
        return MockResource('pool0')

    @property
    def iscsi_host_initiators(self):
        iscsi_initiator = MockResource('iscsi_initiator')
        iscsi_initiator.initiator_id = ['iqn.1-1.com.e:c.host.0',
                                        'iqn.1-1.com.e:c.host.1']
        return iscsi_initiator

    @property
    def total_size_gb(self):
        return self.size_total / units.Gi

    @total_size_gb.setter
    def total_size_gb(self, value):
        if value == self.total_size_gb:
            raise ex.UnityNothingToModifyError()
        else:
            self.size_total = value * units.Gi

    def add_initiator(self, uid, force_create=None):
        self.initiator_id.append(uid)

    def attach(self, lun_or_snap, skip_hlu_0=True):
        if lun_or_snap.get_id() == 'already_attached':
            raise ex.UnityResourceAlreadyAttachedError()
        self.alu_hlu_map[lun_or_snap.get_id()] = len(self.alu_hlu_map)
        return self.get_hlu(lun_or_snap)

    @staticmethod
    def detach(lun_or_snap):
        if lun_or_snap.name == 'detach_failure':
            raise ex.DetachIsCalled()

    @staticmethod
    def detach_from(host):
        if host is None:
            raise ex.DetachFromIsCalled()

    def get_hlu(self, lun):
        return self.alu_hlu_map.get(lun.get_id(), None)

    @staticmethod
    def create_lun(lun_name, size_gb, description=None, io_limit_policy=None,
                   is_thin=None, is_compression=None, tiering_policy=None):
        if lun_name == 'in_use':
            raise ex.UnityLunNameInUseError()
        ret = MockResource(lun_name, 'lun_2')
        if io_limit_policy is not None:
            ret.max_iops = io_limit_policy.max_iops
            ret.max_kbps = io_limit_policy.max_kbps
        if is_thin is not None:
            ret.is_thin = is_thin
        if tiering_policy is not None:
            ret.tiering_policy = tiering_policy
        return ret

    @staticmethod
    def create_snap(name, is_auto_delete=False):
        if name == 'in_use':
            raise ex.UnitySnapNameInUseError()
        ret = MockResource(name)
        ret.is_auto_delete = is_auto_delete
        return ret

    @staticmethod
    def update(data=None):
        pass

    @property
    def iscsi_node(self):
        name = 'iqn.1-1.com.e:c.%s.0' % self.name
        return MockResource(name)

    @property
    def fc_host_initiators(self):
        init0 = MockResource('fhi_0')
        init0.initiator_id = '00:11:22:33:44:55:66:77:88:99:AA:BB:CC:CD:EE:FF'
        init1 = MockResource('fhi_1')
        init1.initiator_id = '00:11:22:33:44:55:66:77:88:99:AA:BB:BC:CD:EE:FF'
        return MockResourceList.create(init0, init1)

    @property
    def paths(self):
        path0 = MockResource('%s_path_0' % self.name)
        path0.is_logged_in = True
        path1 = MockResource('%s_path_1' % self.name)
        path1.is_logged_in = False
        path2 = MockResource('%s_path_2' % self.name)
        path2.is_logged_in = True
        return MockResourceList.create(path0, path1)

    @property
    def fc_port(self):
        ret = MockResource(_id='spa_iom_0_fc0')
        ret.wwn = '00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF'
        return ret

    @property
    def host_luns(self):
        if self.name == 'host-no-host_luns':
            return None
        return []

    @property
    def storage_resource(self):
        if self._storage_resource is None:
            self._storage_resource = MockResource(_id='sr_%s' % self._id,
                                                  name='sr_%s' % self.name)
        return self._storage_resource

    @storage_resource.setter
    def storage_resource(self, value):
        self._storage_resource = value

    def modify(self, name=None, is_compression=None, io_limit_policy=None):
        self.name = name

    def remove_from_storage(self, lun):
        pass

    def thin_clone(self, name, io_limit_policy=None, description=None):
        if name == 'thin_clone_name_in_use':
            raise ex.UnityLunNameInUseError
        return MockResource(_id=name, name=name)

    def get_snap(self, name):
        return MockResource(_id=name, name=name)

    def restore(self, delete_backup):
        return MockResource(_id='snap_1', name="internal_snap")

    def migrate(self, dest_pool, **kwargs):
        if dest_pool.id == 'fail_migration_pool':
            return False
        return True

    def replicate_cg_with_dst_resource_provisioning(self,
                                                    max_time_out_of_sync,
                                                    source_luns,
                                                    dst_pool_id,
                                                    remote_system=None,
                                                    dst_cg_name=None):
        return {'max_time_out_of_sync': max_time_out_of_sync,
                'dst_pool_id': dst_pool_id,
                'remote_system': remote_system,
                'dst_cg_name': dst_cg_name}

    def replicate_with_dst_resource_provisioning(self, max_time_out_of_sync,
                                                 dst_pool_id,
                                                 remote_system=None,
                                                 dst_lun_name=None):
        return {'max_time_out_of_sync': max_time_out_of_sync,
                'dst_pool_id': dst_pool_id,
                'remote_system': remote_system,
                'dst_lun_name': dst_lun_name}

    def failover(self, sync=None):
        return {'sync': sync}

    def failback(self, force_full_copy=None):
        return {'force_full_copy': force_full_copy}

    def check_cg_is_replicated(self):
        if self.name == 'replicated_cg':
            return True
        return False


class MockResourceList(object):
    def __init__(self, names=None, ids=None):
        if names is not None:
            self.resources = [MockResource(name=name) for name in names]
        elif ids is not None:
            self.resources = [MockResource(_id=_id) for _id in ids]

    @staticmethod
    def create(*rsc_list):
        ret = MockResourceList([])
        ret.resources = rsc_list
        return ret

    @property
    def name(self):
        return map(lambda i: i.name, self.resources)

    @property
    def list(self):
        return self.resources

    @list.setter
    def list(self, value):
        self.resources = []

    def __iter__(self):
        return self.resources.__iter__()

    def __len__(self):
        return len(self.resources)

    def __getattr__(self, item):
        return [getattr(i, item) for i in self.resources]

    def shadow_copy(self, **kwargs):
        if list(filter(None, kwargs.values())):
            return MockResourceList.create(self.resources[0])
        else:
            return self


class MockSystem(object):
    def __init__(self):
        self.serial_number = 'SYSTEM_SERIAL'
        self.system_version = '4.1.0'

    @property
    def info(self):
        mocked_info = mock.Mock()
        mocked_info.name = self.serial_number
        return mocked_info

    @staticmethod
    def get_lun(_id=None, name=None):
        if _id == 'not_found':
            raise ex.UnityResourceNotFoundError()
        if _id == 'tc_80':  # for thin clone with extending size
            lun = MockResource(name=_id, _id=_id)
            lun.total_size_gb = 7
            return lun
        return MockResource(name, _id)

    @staticmethod
    def get_pool(_id=None, name=None):
        if name == 'Pool 3':
            return MockResource(name, 'pool_3')
        if name or _id:
            return MockResource(name, _id)
        return MockResourceList(['Pool 1', 'Pool 2'])

    @staticmethod
    def get_snap(name):
        if name == 'not_found':
            raise ex.UnityResourceNotFoundError()
        return MockResource(name)

    @staticmethod
    def get_cg(name):
        if not name:
            raise ex.UnityResourceNotFoundError()
        return MockResource(name, _id=name)

    @staticmethod
    def create_host(name):
        return MockResource(name)

    @staticmethod
    def get_host(name):
        if name == 'not_found':
            raise ex.UnityResourceNotFoundError()
        if name == 'host1':
            ret = MockResource(name)
            ret.initiator_id = ['old-iqn']
            return ret
        return MockResource(name)

    @staticmethod
    def get_iscsi_portal():
        portal0 = MockResource('p0')
        portal0.ip_address = '1.1.1.1'
        portal1 = MockResource('p1')
        portal1.ip_address = '1.1.1.2'
        return MockResourceList.create(portal0, portal1)

    @staticmethod
    def get_fc_port():
        port0 = MockResource('fcp0')
        port0.wwn = '00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF'
        port1 = MockResource('fcp1')
        port1.wwn = '00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:FF:EE'
        return MockResourceList.create(port0, port1)

    @staticmethod
    def create_io_limit_policy(name, max_iops=None, max_kbps=None):
        if name == 'in_use':
            raise ex.UnityPolicyNameInUseError()
        ret = MockResource(name)
        ret.max_iops = max_iops
        ret.max_kbps = max_kbps
        return ret

    @staticmethod
    def get_io_limit_policy(name):
        return MockResource(name=name)

    def get_remote_system(self, name=None):
        if name == 'not-exist':
            raise ex.UnityResourceNotFoundError()
        else:
            return {'name': name}

    def get_replication_session(self, name=None,
                                src_resource_id=None, dst_resource_id=None):
        if name == 'not-exist':
            raise ex.UnityResourceNotFoundError()
        elif src_resource_id == 'lun_in_replication':
            return [MockResource(name='rep_session')]
        elif src_resource_id == 'lun_not_in_replication':
            raise ex.UnityResourceNotFoundError()
        elif src_resource_id == 'lun_in_multiple_replications':
            return [MockResource(_id='lun_rep_session_1'),
                    MockResource(_id='lun_rep_session_2')]
        elif src_resource_id and ('is_in_replication'
                                  in src_resource_id):
            return [MockResource(name='rep_session')]
        elif dst_resource_id and ('is_in_replication'
                                  in dst_resource_id):
            return [MockResource(name='rep_session')]
        else:
            return {'name': name,
                    'src_resource_id': src_resource_id,
                    'dst_resource_id': dst_resource_id}


@mock.patch.object(client, 'storops', new='True')
def get_client():
    ret = client.UnityClient('1.2.3.4', 'user', 'pass')
    ret._system = MockSystem()
    return ret


########################
#
#   Start of Tests
#
########################
@ddt.ddt
@mock.patch.object(client, 'storops_ex', new=ex)
class ClientTest(unittest.TestCase):
    def setUp(self):
        self.client = get_client()

    def test_get_serial(self):
        self.assertEqual('SYSTEM_SERIAL', self.client.get_serial())

    def test_create_lun_success(self):
        name = 'LUN 3'
        pool = MockResource('Pool 0')
        lun = self.client.create_lun(name, 5, pool)
        self.assertEqual(name, lun.name)

    def test_create_lun_name_in_use(self):
        name = 'in_use'
        pool = MockResource('Pool 0')
        lun = self.client.create_lun(name, 6, pool)
        self.assertEqual('in_use', lun.name)

    def test_create_lun_with_io_limit(self):
        pool = MockResource('Pool 0')
        limit = MockResource('limit')
        limit.max_kbps = 100
        lun = self.client.create_lun('LUN 4', 6, pool, io_limit_policy=limit)
        self.assertEqual(100, lun.max_kbps)

    def test_create_lun_thick(self):
        name = 'thick_lun'
        pool = MockResource('Pool 0')
        lun = self.client.create_lun(name, 6, pool, is_thin=False)
        self.assertIsNotNone(lun.is_thin)
        self.assertFalse(lun.is_thin)
        self.assertIsNone(lun.tiering_policy)

    def test_create_auto_tier_lun(self):
        name = 'auto_tier_lun'
        tiering_policy = enums.TieringPolicyEnum.AUTOTIER
        pool = MockResource('Pool 0')
        lun = self.client.create_lun(name, 6, pool,
                                     tiering_policy=tiering_policy)
        self.assertIsNotNone(lun.tiering_policy)
        self.assertEqual(enums.TieringPolicyEnum.AUTOTIER, lun.tiering_policy)

    def test_create_high_tier_lun(self):
        name = 'high_tier_lun'
        tiering_policy = enums.TieringPolicyEnum.HIGHEST
        pool = MockResource('Pool 0')
        lun = self.client.create_lun(name, 6, pool,
                                     tiering_policy=tiering_policy)
        self.assertIsNotNone(lun.tiering_policy)
        self.assertEqual(enums.TieringPolicyEnum.HIGHEST, lun.tiering_policy)

    def test_thin_clone_success(self):
        name = 'tc_77'
        src_lun = MockResource(_id='id_77')
        lun = self.client.thin_clone(src_lun, name)
        self.assertEqual(name, lun.name)

    def test_thin_clone_name_in_used(self):
        name = 'thin_clone_name_in_use'
        src_lun = MockResource(_id='id_79')
        lun = self.client.thin_clone(src_lun, name)
        self.assertEqual(name, lun.name)

    def test_thin_clone_extend_size(self):
        name = 'tc_80'
        src_lun = MockResource(_id='id_80')
        lun = self.client.thin_clone(src_lun, name, io_limit_policy=None,
                                     new_size_gb=7)
        self.assertEqual(name, lun.name)
        self.assertEqual(7, lun.total_size_gb)

    def test_delete_lun_normal(self):
        self.assertIsNone(self.client.delete_lun('lun3'))

    def test_delete_lun_not_found(self):
        try:
            self.client.delete_lun('not_found')
        except ex.StoropsException:
            self.fail('not found error should be dealt with silently.')

    def test_delete_lun_in_replication(self):
        self.client.delete_lun('lun_in_replication')

    @ddt.data({'lun_id': 'lun_not_in_replication'},
              {'lun_id': 'lun_in_multiple_replications'})
    @ddt.unpack
    def test_delete_lun_replications(self, lun_id):
        self.client.delete_lun_replications(lun_id)

    def test_get_lun_with_id(self):
        lun = self.client.get_lun('lun4')
        self.assertEqual('lun4', lun.get_id())

    def test_get_lun_with_name(self):
        lun = self.client.get_lun(name='LUN 4')
        self.assertEqual('LUN 4', lun.name)

    def test_get_lun_not_found(self):
        ret = self.client.get_lun(lun_id='not_found')
        self.assertIsNone(ret)

    def test_get_pools(self):
        pools = self.client.get_pools()
        self.assertEqual(2, len(pools))

    def test_create_snap_normal(self):
        snap = self.client.create_snap('lun_1', 'snap_1')
        self.assertEqual('snap_1', snap.name)

    def test_create_snap_in_use(self):
        snap = self.client.create_snap('lun_1', 'in_use')
        self.assertEqual('in_use', snap.name)

    def test_delete_snap_error(self):
        def f():
            snap = MockResource(_id='snap_2')
            self.client.delete_snap(snap)

        self.assertRaises(ex.SnapDeleteIsCalled, f)

    def test_delete_snap_not_found(self):
        try:
            snap = MockResource(_id='not_found')
            self.client.delete_snap(snap)
        except ex.StoropsException:
            self.fail('snap not found should not raise exception.')

    def test_delete_snap_none(self):
        try:
            ret = self.client.delete_snap(None)
            self.assertIsNone(ret)
        except ex.StoropsException:
            self.fail('delete none should not raise exception.')

    def test_delete_snap_in_use(self):
        def f():
            snap = MockResource(_id='snap_in_use')
            self.client.delete_snap(snap)

        self.assertRaises(ex.UnityDeleteAttachedSnapError, f)

    def test_get_snap_found(self):
        snap = self.client.get_snap('snap_2')
        self.assertEqual('snap_2', snap.name)

    def test_get_snap_not_found(self):
        ret = self.client.get_snap('not_found')
        self.assertIsNone(ret)

    @mock.patch.object(coordination.Coordinator, 'get_lock')
    def test_create_host_found(self, fake_coordination):
        host = self.client.create_host('host1')

        self.assertEqual('host1', host.name)
        self.assertLessEqual(['iqn.1-1.com.e:c.a.a0'], host.initiator_id)

    @mock.patch.object(coordination.Coordinator, 'get_lock')
    def test_create_host_not_found(self, fake):
        host = self.client.create_host('not_found')
        self.assertEqual('not_found', host.name)
        self.assertIn('not_found', self.client.host_cache)

    def test_attach_lun(self):
        lun = MockResource(_id='lun1', name='l1')
        host = MockResource('host1')
        self.assertEqual(1, self.client.attach(host, lun))

    def test_attach_already_attached(self):
        lun = MockResource(_id='already_attached')
        host = MockResource('host1')
        hlu = self.client.attach(host, lun)
        self.assertEqual(99, hlu)

    def test_detach_lun(self):
        def f():
            lun = MockResource('detach_failure')
            host = MockResource('host1')
            self.client.detach(host, lun)

        self.assertRaises(ex.DetachIsCalled, f)

    def test_detach_all(self):
        def f():
            lun = MockResource('lun_44')
            self.client.detach_all(lun)

        self.assertRaises(ex.DetachFromIsCalled, f)

    @mock.patch.object(coordination.Coordinator, 'get_lock')
    def test_create_host(self, fake):
        self.assertEqual('host2', self.client.create_host('host2').name)

    @mock.patch.object(coordination.Coordinator, 'get_lock')
    def test_create_host_in_cache(self, fake):
        self.client.host_cache['already_in'] = MockResource(name='already_in')
        host = self.client.create_host('already_in')
        self.assertIn('already_in', self.client.host_cache)
        self.assertEqual('already_in', host.name)

    def test_update_host_initiators(self):
        host = MockResource(name='host_init')
        host = self.client.update_host_initiators(host, 'fake-iqn-1')

    def test_get_iscsi_target_info(self):
        ret = self.client.get_iscsi_target_info()
        expected = [{'iqn': 'iqn.1-1.com.e:c.p0.0', 'portal': '1.1.1.1:3260'},
                    {'iqn': 'iqn.1-1.com.e:c.p1.0', 'portal': '1.1.1.2:3260'}]
        self.assertListEqual(expected, ret)

    def test_get_iscsi_target_info_allowed_ports(self):
        ret = self.client.get_iscsi_target_info(allowed_ports=['spa_eth0'])
        expected = [{'iqn': 'iqn.1-1.com.e:c.p0.0', 'portal': '1.1.1.1:3260'}]
        self.assertListEqual(expected, ret)

    def test_get_fc_target_info_without_host(self):
        ret = self.client.get_fc_target_info()
        self.assertListEqual(['8899AABBCCDDEEFF', '8899AABBCCDDFFEE'],
                             sorted(ret))

    def test_get_fc_target_info_without_host_but_allowed_ports(self):
        ret = self.client.get_fc_target_info(allowed_ports=['spa_fc0'])
        self.assertListEqual(['8899AABBCCDDEEFF'], ret)

    def test_get_fc_target_info_with_host(self):
        host = MockResource('host0')
        ret = self.client.get_fc_target_info(host, True)
        self.assertListEqual(['8899AABBCCDDEEFF'], ret)

    def test_get_fc_target_info_with_host_and_allowed_ports(self):
        host = MockResource('host0')
        ret = self.client.get_fc_target_info(host, True,
                                             allowed_ports=['spb_iom_0_fc0'])
        self.assertListEqual([], ret)

    def test_get_io_limit_policy_none(self):
        ret = self.client.get_io_limit_policy(None)
        self.assertIsNone(ret)

    def test_get_io_limit_policy_create_new(self):
        specs = {'maxBWS': 2, 'id': 'max_2_mbps', 'maxIOPS': None}
        limit = self.client.get_io_limit_policy(specs)
        self.assertEqual('max_2_mbps', limit.name)
        self.assertEqual(2, limit.max_kbps)

    def test_create_io_limit_policy_success(self):
        limit = self.client.create_io_limit_policy('3kiops', max_iops=3000)
        self.assertEqual('3kiops', limit.name)
        self.assertEqual(3000, limit.max_iops)

    def test_create_io_limit_policy_in_use(self):
        limit = self.client.create_io_limit_policy('in_use', max_iops=100)
        self.assertEqual('in_use', limit.name)

    def test_expand_lun_success(self):
        lun = self.client.extend_lun('ev_3', 6)
        self.assertEqual(6, lun.total_size_gb)

    def test_expand_lun_nothing_to_modify(self):
        lun = self.client.extend_lun('ev_4', 5)
        self.assertEqual(5, lun.total_size_gb)

    def test_migrate_lun_success(self):
        ret = self.client.migrate_lun('lun_0', 'pool_1')
        self.assertTrue(ret)

    def test_migrate_lun_failed(self):
        ret = self.client.migrate_lun('lun_0', 'fail_migration_pool')
        self.assertFalse(ret)

    def test_migrate_lun_thick(self):
        ret = self.client.migrate_lun('lun_thick', 'pool_2', 'thick')
        self.assertTrue(ret)

    def test_migrate_lun_compressed(self):
        ret = self.client.migrate_lun('lun_compressed', 'pool_2', 'compressed')
        self.assertTrue(ret)

    def test_get_pool_id_by_name(self):
        self.assertEqual('pool_3', self.client.get_pool_id_by_name('Pool 3'))

    def test_get_pool_name(self):
        self.assertEqual('Pool0', self.client.get_pool_name('lun_0'))

    def test_restore_snapshot(self):
        back_snap = self.client.restore_snapshot('snap1')
        self.assertEqual("internal_snap", back_snap.name)

    def test_delete_host_wo_lock(self):
        host = MockResource(name='empty-host')
        self.client.host_cache['empty-host'] = host
        self.assertRaises(ex.HostDeleteIsCalled,
                          self.client.delete_host_wo_lock,
                          host)

    def test_delete_host_wo_lock_remove_from_cache(self):
        host = MockResource(name='empty-host-in-cache')
        self.client.host_cache['empty-host-in-cache'] = host
        self.client.delete_host_wo_lock(host)
        self.assertNotIn(host.name, self.client.host_cache)

    @ddt.data(('cg_1', 'cg_1_description', [MockResource(_id='sv_1')]),
              ('cg_2', None, None),
              ('cg_3', None, [MockResource(_id='sv_2')]),
              ('cg_4', 'cg_4_description', None))
    @ddt.unpack
    def test_create_cg(self, cg_name, cg_description, lun_add):
        created_cg = MockResource(_id='cg_1')
        with mock.patch.object(self.client.system, 'create_cg',
                               create=True, return_value=created_cg
                               ) as mocked_create:
            ret = self.client.create_cg(cg_name, description=cg_description,
                                        lun_add=lun_add)
            mocked_create.assert_called_once_with(cg_name,
                                                  description=cg_description,
                                                  lun_add=lun_add)
            self.assertEqual(created_cg, ret)

    def test_create_cg_existing_name(self):
        existing_cg = MockResource(_id='cg_1')
        with mock.patch.object(
                self.client.system, 'create_cg',
                side_effect=ex.UnityConsistencyGroupNameInUseError,
                create=True) as mocked_create, \
                mock.patch.object(self.client.system, 'get_cg',
                                  create=True,
                                  return_value=existing_cg) as mocked_get:
            ret = self.client.create_cg('existing_name')
            mocked_create.assert_called_once_with('existing_name',
                                                  description=None,
                                                  lun_add=None)
            mocked_get.assert_called_once_with(name='existing_name')
            self.assertEqual(existing_cg, ret)

    def test_get_cg(self):
        existing_cg = MockResource(_id='cg_1')
        with mock.patch.object(self.client.system, 'get_cg',
                               create=True,
                               return_value=existing_cg) as mocked_get:
            ret = self.client.get_cg('existing_name')
            mocked_get.assert_called_once_with(name='existing_name')
            self.assertEqual(existing_cg, ret)

    def test_get_cg_not_found(self):
        with mock.patch.object(self.client.system, 'get_cg',
                               create=True,
                               side_effect=ex.UnityResourceNotFoundError
                               ) as mocked_get:
            ret = self.client.get_cg('not_found_name')
            mocked_get.assert_called_once_with(name='not_found_name')
            self.assertIsNone(ret)

    def test_delete_cg(self):
        existing_cg = MockResource(_id='cg_1')
        with mock.patch.object(existing_cg, 'delete', create=True
                               ) as mocked_delete, \
                mock.patch.object(self.client, 'get_cg',
                                  create=True,
                                  return_value=existing_cg) as mocked_get:
            ret = self.client.delete_cg('cg_1_name')
            mocked_get.assert_called_once_with('cg_1_name')
            mocked_delete.assert_called_once()
            self.assertIsNone(ret)

    def test_update_cg(self):
        existing_cg = MockResource(_id='cg_1')
        lun_1 = MockResource(_id='sv_1')
        lun_2 = MockResource(_id='sv_2')
        lun_3 = MockResource(_id='sv_3')

        def _mocked_get_lun(lun_id):
            if lun_id == 'sv_1':
                return lun_1
            if lun_id == 'sv_2':
                return lun_2
            if lun_id == 'sv_3':
                return lun_3

        with mock.patch.object(existing_cg, 'update_lun', create=True
                               ) as mocked_update, \
                mock.patch.object(self.client, 'get_cg',
                                  create=True,
                                  return_value=existing_cg) as mocked_get, \
                mock.patch.object(self.client, 'get_lun',
                                  side_effect=_mocked_get_lun):
            ret = self.client.update_cg('cg_1_name', ['sv_1', 'sv_2'],
                                        ['sv_3'])
            mocked_get.assert_called_once_with('cg_1_name')
            mocked_update.assert_called_once_with(add_luns=[lun_1, lun_2],
                                                  remove_luns=[lun_3])
            self.assertIsNone(ret)

    def test_update_cg_empty_lun_ids(self):
        existing_cg = MockResource(_id='cg_1')
        with mock.patch.object(existing_cg, 'update_lun', create=True
                               ) as mocked_update, \
                mock.patch.object(self.client, 'get_cg',
                                  create=True,
                                  return_value=existing_cg) as mocked_get:
            ret = self.client.update_cg('cg_1_name', set(), set())
            mocked_get.assert_called_once_with('cg_1_name')
            mocked_update.assert_called_once_with(add_luns=[], remove_luns=[])
            self.assertIsNone(ret)

    def test_create_cg_group(self):
        existing_cg = MockResource(_id='cg_1')
        created_snap = MockResource(_id='snap_cg_1', name='snap_name_cg_1')
        with mock.patch.object(existing_cg, 'create_snap', create=True,
                               return_value=created_snap) as mocked_create, \
                mock.patch.object(self.client, 'get_cg',
                                  create=True,
                                  return_value=existing_cg) as mocked_get:
            ret = self.client.create_cg_snap('cg_1_name',
                                             snap_name='snap_name_cg_1')
            mocked_get.assert_called_once_with('cg_1_name')
            mocked_create.assert_called_once_with(name='snap_name_cg_1',
                                                  is_auto_delete=False)
            self.assertEqual(created_snap, ret)

    def test_create_cg_group_none_name(self):
        existing_cg = MockResource(_id='cg_1')
        created_snap = MockResource(_id='snap_cg_1')
        with mock.patch.object(existing_cg, 'create_snap', create=True,
                               return_value=created_snap) as mocked_create, \
                mock.patch.object(self.client, 'get_cg',
                                  create=True,
                                  return_value=existing_cg) as mocked_get:
            ret = self.client.create_cg_snap('cg_1_name')
            mocked_get.assert_called_once_with('cg_1_name')
            mocked_create.assert_called_once_with(name=None,
                                                  is_auto_delete=False)
            self.assertEqual(created_snap, ret)

    def test_filter_snaps_in_cg_snap(self):
        snaps = [MockResource(_id='snap_{}'.format(n)) for n in (1, 2)]
        snap_list = mock.MagicMock()
        snap_list.list = snaps
        with mock.patch.object(self.client.system, 'get_snap',
                               create=True,
                               return_value=snap_list) as mocked_get:
            ret = self.client.filter_snaps_in_cg_snap('snap_cg_1')
            mocked_get.assert_called_once_with(snap_group='snap_cg_1')
            self.assertEqual(snaps, ret)

    def test_create_replication(self):
        remote_system = MockResource(_id='RS_1')
        lun = MockResource(_id='sv_1')
        called = self.client.create_replication(lun, 60, 'pool_1',
                                                remote_system)
        self.assertEqual(called['max_time_out_of_sync'], 60)
        self.assertEqual(called['dst_pool_id'], 'pool_1')
        self.assertIs(called['remote_system'], remote_system)

    def test_get_remote_system(self):
        called = self.client.get_remote_system(name='remote-unity')
        self.assertEqual(called['name'], 'remote-unity')

    def test_get_remote_system_not_exist(self):
        called = self.client.get_remote_system(name='not-exist')
        self.assertIsNone(called)

    def test_get_replication_session(self):
        called = self.client.get_replication_session(name='rep-name')
        self.assertEqual(called['name'], 'rep-name')

    def test_get_replication_session_not_exist(self):
        self.assertRaises(client.ClientReplicationError,
                          self.client.get_replication_session,
                          name='not-exist')

    def test_failover_replication(self):
        rep_session = MockResource(_id='rep_id_1')
        called = self.client.failover_replication(rep_session)
        self.assertFalse(called['sync'])

    def test_failover_replication_raise(self):
        rep_session = MockResource(_id='rep_id_1')

        def mock_failover(sync=None):
            raise ex.UnityResourceNotFoundError()

        rep_session.failover = mock_failover
        self.assertRaises(client.ClientReplicationError,
                          self.client.failover_replication,
                          rep_session)

    def test_failback_replication(self):
        rep_session = MockResource(_id='rep_id_1')
        called = self.client.failback_replication(rep_session)
        self.assertTrue(called['force_full_copy'])

    def test_failback_replication_raise(self):
        rep_session = MockResource(_id='rep_id_1')

        def mock_failback(force_full_copy=None):
            raise ex.UnityResourceNotFoundError()

        rep_session.failback = mock_failback
        self.assertRaises(client.ClientReplicationError,
                          self.client.failback_replication,
                          rep_session)

    def test_create_cg_replication(self):
        remote_system = MockResource(_id='RS_2')
        cg_name = 'test_cg'
        called = self.client.create_cg_replication(
            cg_name, 'pool_1', remote_system, 60)
        self.assertEqual(60, called['max_time_out_of_sync'])
        self.assertEqual('pool_1', called['dst_pool_id'])
        self.assertEqual('test_cg', called['dst_cg_name'])
        self.assertIs(remote_system, called['remote_system'])

    def test_cg_in_replciation(self):
        existing_cg = MockResource(_id='replicated_cg')
        result = self.client.is_cg_replicated(existing_cg.id)
        self.assertTrue(result)

    def test_cg_not_in_replciation(self):
        existing_cg = MockResource(_id='test_cg')
        result = self.client.is_cg_replicated(existing_cg.id)
        self.assertFalse(result)

    def test_delete_cg_rep_session(self):
        src_cg = MockResource(_id='cg_is_in_replication')
        result = self.client.delete_cg_rep_session(src_cg.id)
        self.assertIsNone(result)

    def test_failover_cg_rep_session(self):
        src_cg = MockResource(_id='failover_cg_is_in_replication')
        result = self.client.failover_cg_rep_session(src_cg.id, True)
        self.assertIsNone(result)

    def test_failback_cg_rep_session(self):
        src_cg = MockResource(_id='failback_cg_is_in_replication')
        result = self.client.failback_cg_rep_session(src_cg.id)
        self.assertIsNone(result)
