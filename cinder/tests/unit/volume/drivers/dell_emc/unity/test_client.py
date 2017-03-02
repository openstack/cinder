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

from mock import mock
from oslo_utils import units

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

    @property
    def id(self):
        return self._id

    def get_id(self):
        return self._id

    def delete(self):
        if self.get_id() in ['snap_2']:
            raise ex.SnapDeleteIsCalled()
        elif self.get_id() == 'not_found':
            raise ex.UnityResourceNotFoundError()
        elif self.get_id() == 'snap_in_use':
            raise ex.UnityDeleteAttachedSnapError()

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

    def get_hlu(self, lun):
        return self.alu_hlu_map.get(lun.get_id(), None)

    @staticmethod
    def create_lun(lun_name, size_gb, description=None, io_limit_policy=None):
        if lun_name == 'in_use':
            raise ex.UnityLunNameInUseError()
        ret = MockResource(lun_name, 'lun_2')
        if io_limit_policy is not None:
            ret.max_iops = io_limit_policy.max_iops
            ret.max_kbps = io_limit_policy.max_kbps
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
        return []

    @property
    def storage_resource(self):
        return MockResource(_id='sr_%s' % self._id,
                            name='sr_%s' % self.name)

    def modify(self, name=None):
        self.name = name


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

    @staticmethod
    def get_lun(_id=None, name=None):
        if _id == 'not_found':
            raise ex.UnityResourceNotFoundError()
        return MockResource(name, _id)

    @staticmethod
    def get_pool():
        return MockResourceList(['Pool 1', 'Pool 2'])

    @staticmethod
    def get_snap(name):
        if name == 'not_found':
            raise ex.UnityResourceNotFoundError()
        return MockResource(name)

    @staticmethod
    def create_host(name):
        return MockResource(name)

    @staticmethod
    def get_host(name):
        if name == 'not_found':
            raise ex.UnityResourceNotFoundError()
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

    def test_delete_lun_normal(self):
        self.assertIsNone(self.client.delete_lun('lun3'))

    def test_delete_lun_not_found(self):
        try:
            self.client.delete_lun('not_found')
        except ex.StoropsException:
            self.fail('not found error should be dealt with silently.')

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

    def test_create_host_found(self):
        iqns = ['iqn.1-1.com.e:c.a.a0']
        host = self.client.create_host('host1', iqns)

        self.assertEqual('host1', host.name)
        self.assertLessEqual(['iqn.1-1.com.e:c.a.a0'], host.initiator_id)

    def test_create_host_not_found(self):
        host = self.client.create_host('not_found', [])
        self.assertEqual('not_found', host.name)

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

    def test_get_host(self):
        self.assertEqual('host2', self.client.get_host('host2').name)

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

    def test_get_pool_name(self):
        self.assertEqual('Pool0', self.client.get_pool_name('lun_0'))
