# Copyright (c) 2016 by Kaminario Technologies, Ltd.
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
"""Unit tests for kaminario driver."""
import re

import ddt
import mock
from oslo_utils import units
import time

from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers.kaminario import kaminario_common
from cinder.volume.drivers.kaminario import kaminario_fc
from cinder.volume.drivers.kaminario import kaminario_iscsi
from cinder.volume import utils as vol_utils

CONNECTOR = {'initiator': 'iqn.1993-08.org.debian:01:12aa12aa12aa',
             'ip': '192.168.2.5', 'platform': 'x86_64', 'host': 'test-k2',
             'wwpns': ['12341a2a00001234', '12341a2a00001235'],
             'wwnns': ['12351a2a00001234', '12361a2a00001234'],
             'os_type': 'linux2', 'multipath': False}


class FakeK2Obj(object):
    id = 548
    lun = 548


class FakeSaveObject(FakeK2Obj):
    def __init__(self, *args, **kwargs):
        item = kwargs.pop('item', 1)
        self.ntype = kwargs.get('ntype')
        self.ip_address = '10.0.0.%s' % item
        self.iscsi_qualified_target_name = "xyztlnxyz"
        self.snapshot = FakeK2Obj()
        self.name = 'test'
        self.pwwn = '50024f405330030%s' % item
        self.volume_group = self
        self.is_dedup = True
        self.size = units.Mi
        self.replication_status = None
        self.state = 'in_sync'
        self.generation_number = 548
        self.current_role = 'target'
        self.current_snapshot_progress = 100
        self.current_snapshot_id = None
        self.wan_port = None

    def refresh(self):
        return

    def save(self):
        return FakeSaveObject()

    def delete(self):
        return None


class FakeSaveObjectExp(FakeSaveObject):
    def save(self):
        raise exception.KaminarioCinderDriverException("test")

    def delete(self):
        raise exception.KaminarioCinderDriverException("test")


class FakeSearchObject(object):
    hits = [FakeSaveObject(item=1), FakeSaveObject(item=2)]
    total = 2

    def __init__(self, *args):
        if args and "mappings" in args[0]:
            self.total = 0


class FakeSearchObjectExp(object):
    hits = [FakeSaveObjectExp()]
    total = 1


class FakeKrest(object):
    def search(self, *args, **argv):
        return FakeSearchObject(*args)

    def new(self, *args, **argv):
        return FakeSaveObject()


class FakeKrestException(object):
    def search(self, *args, **argv):
        return FakeSearchObjectExp()

    def new(self, *args, **argv):
        return FakeSaveObjectExp()


class Replication(object):
    backend_id = '10.0.0.1'
    login = 'login'
    password = 'password'
    rpo = 500


class TestKaminarioCommon(test.TestCase):
    driver = None
    conf = None

    def setUp(self):
        self._setup_config()
        self._setup_driver()
        super(TestKaminarioCommon, self).setUp()
        self.context = context.get_admin_context()
        self.vol = fake_volume.fake_volume_obj(self.context)
        self.vol.volume_type = fake_volume.fake_volume_type_obj(self.context)
        self.vol.volume_type.extra_specs = {'foo': None}
        self.snap = fake_snapshot.fake_snapshot_obj(self.context)
        self.snap.volume = self.vol
        self.patch('eventlet.sleep')

    def _setup_config(self):
        self.conf = mock.Mock(spec=configuration.Configuration)
        self.conf.kaminario_dedup_type_name = "dedup"
        self.conf.volume_dd_blocksize = 2
        self.conf.unique_fqdn_network = True
        self.conf.disable_discovery = False

    def _setup_driver(self):
        self.driver = (kaminario_iscsi.
                       KaminarioISCSIDriver(configuration=self.conf))
        device = mock.Mock(return_value={'device': {'path': '/dev'}})
        self.driver._connect_device = device
        self.driver.client = FakeKrest()

    def test_create_volume(self):
        """Test create_volume."""
        result = self.driver.create_volume(self.vol)
        self.assertIsNone(result)

    def test_create_volume_with_exception(self):
        """Test create_volume_with_exception."""
        self.driver.client = FakeKrestException()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver.create_volume, self.vol)

    def test_delete_volume(self):
        """Test delete_volume."""
        result = self.driver.delete_volume(self.vol)
        self.assertIsNone(result)

    def test_delete_volume_with_exception(self):
        """Test delete_volume_with_exception."""
        self.driver.client = FakeKrestException()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver.delete_volume, self.vol)

    def test_create_snapshot(self):
        """Test create_snapshot."""
        self.snap.id = "253b2878-ec60-4793-ad19-e65496ec7aab"
        self.driver.client.new = mock.Mock()
        result = self.driver.create_snapshot(self.snap)
        self.assertIsNone(result)
        fake_object = self.driver.client.search().hits[0]
        self.driver.client.new.assert_called_once_with(
            "snapshots",
            short_name='cs-253b2878-ec60-4793-ad19-e65496ec7aab',
            source=fake_object, retention_policy=fake_object,
            is_auto_deleteable=False)

    def test_create_snapshot_with_exception(self):
        """Test create_snapshot_with_exception."""
        self.driver.client = FakeKrestException()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver.create_snapshot, self.snap)

    def test_delete_snapshot(self):
        """Test delete_snapshot."""
        result = self.driver.delete_snapshot(self.snap)
        self.assertIsNone(result)

    def test_delete_snapshot_with_exception(self):
        """Test delete_snapshot_with_exception."""
        self.driver.client = FakeKrestException()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver.delete_snapshot, self.snap)

    @mock.patch.object(utils, 'brick_get_connector_properties')
    @mock.patch.object(vol_utils, 'copy_volume')
    def test_create_volume_from_snapshot(self, mock_copy_volume,
                                         mock_brick_get):
        """Test create_volume_from_snapshot."""
        mock_brick_get.return_value = CONNECTOR
        mock_copy_volume.return_value = None
        self.driver._kaminario_disconnect_volume = mock.Mock()
        result = self.driver.create_volume_from_snapshot(self.vol, self.snap)
        self.assertIsNone(result)

    @mock.patch.object(utils, 'brick_get_connector_properties')
    @mock.patch.object(vol_utils, 'copy_volume')
    def test_create_volume_from_snapshot_with_exception(self, mock_copy_volume,
                                                        mock_brick_get):
        """Test create_volume_from_snapshot_with_exception."""
        mock_brick_get.return_value = CONNECTOR
        mock_copy_volume.return_value = None
        self.driver.client = FakeKrestException()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver.create_volume_from_snapshot, self.vol,
                          self.snap)

    @mock.patch.object(utils, 'brick_get_connector_properties')
    @mock.patch.object(vol_utils, 'copy_volume')
    def test_create_cloned_volume(self, mock_copy_volume, mock_brick_get):
        """Test create_cloned_volume."""
        mock_brick_get.return_value = CONNECTOR
        mock_copy_volume.return_value = None
        self.driver._kaminario_disconnect_volume = mock.Mock()
        result = self.driver.create_cloned_volume(self.vol, self.vol)
        self.assertIsNone(result)

    @mock.patch.object(utils, 'brick_get_connector_properties')
    @mock.patch.object(vol_utils, 'copy_volume')
    def test_create_cloned_volume_with_exception(self, mock_copy_volume,
                                                 mock_brick_get):
        """Test create_cloned_volume_with_exception."""
        mock_brick_get.return_value = CONNECTOR
        mock_copy_volume.return_value = None
        self.driver.terminate_connection = mock.Mock()
        self.driver.client = FakeKrestException()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver.create_cloned_volume, self.vol, self.vol)

    def test_extend_volume(self):
        """Test extend_volume."""
        new_size = 256
        result = self.driver.extend_volume(self.vol, new_size)
        self.assertIsNone(result)

    def test_extend_volume_with_exception(self):
        """Test extend_volume_with_exception."""
        self.driver.client = FakeKrestException()
        new_size = 256
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver.extend_volume, self.vol, new_size)

    def test_initialize_connection_with_exception(self):
        """Test initialize_connection_with_exception."""
        self.driver.client = FakeKrestException()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver.initialize_connection, self.vol,
                          CONNECTOR)

    def test_get_lun_number(self):
        """Test _get_lun_number."""
        host, host_rs, host_name = self.driver._get_host_object(CONNECTOR)
        result = self.driver._get_lun_number(self.vol, host)
        self.assertEqual(548, result)

    def test_get_volume_object(self):
        """Test _get_volume_object."""
        result = self.driver._get_volume_object(self.vol)
        self.assertEqual(548, result.id)

    def test_get_host_object(self):
        """Test _get_host_object."""
        host, host_rs, host_name = self.driver._get_host_object(CONNECTOR)
        self.assertEqual(548, host.id)
        self.assertEqual(2, host_rs.total)
        self.assertEqual('test-k2', host_name)

    def test_k2_initialize_connection(self):
        """Test k2_initialize_connection."""
        result = self.driver.k2_initialize_connection(self.vol, CONNECTOR)
        self.assertEqual(548, result)

    @mock.patch.object(FakeSearchObject, 'total', 1)
    def test_manage_existing(self):
        """Test manage_existing."""
        self.driver._get_replica_status = mock.Mock(return_value=False)
        result = self.driver.manage_existing(self.vol, {'source-name': 'test'})
        self.assertIsNone(result)

    def test_manage_existing_exp(self):
        self.driver._get_replica_status = mock.Mock(return_value=True)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, self.vol,
                          {'source-name': 'test'})

    def test_manage_vg_volumes(self):
        self.driver.nvol = 2
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, self.vol,
                          {'source-name': 'test'})

    def test_manage_existing_get_size(self):
        """Test manage_existing_get_size."""
        self.driver.client.search().hits[0].size = units.Mi
        result = self.driver.manage_existing_get_size(self.vol,
                                                      {'source-name': 'test'})
        self.assertEqual(1, result)

    def test_get_is_dedup(self):
        """Test _get_is_dedup."""
        result = self.driver._get_is_dedup(self.vol.volume_type)
        self.assertTrue(result)

    def test_get_is_dedup_false(self):
        """Test _get_is_dedup_false."""
        specs = {'kaminario:thin_prov_type': 'nodedup'}
        self.vol.volume_type.extra_specs = specs
        result = self.driver._get_is_dedup(self.vol.volume_type)
        self.assertFalse(result)

    def test_get_replica_status(self):
        """Test _get_replica_status."""
        result = self.driver._get_replica_status(self.vol)
        self.assertTrue(result)

    def test_create_volume_replica(self):
        """Test _create_volume_replica."""
        vg = FakeSaveObject()
        rep = Replication()
        self.driver.replica = rep
        session_name = self.driver.get_session_name('1234567890987654321')
        self.assertEqual('ssn-1234567890987654321', session_name)
        rsession_name = self.driver.get_rep_name(session_name)
        self.assertEqual('rssn-1234567890987654321', rsession_name)
        src_ssn = self.driver.client.new("replication/sessions").save()
        self.assertEqual('in_sync', src_ssn.state)
        result = self.driver._create_volume_replica(self.vol, vg, vg, rep.rpo)
        self.assertIsNone(result)

    def test_create_volume_replica_exp(self):
        """Test _create_volume_replica_exp."""
        vg = FakeSaveObject()
        rep = Replication()
        self.driver.replica = rep
        self.driver.client = FakeKrestException()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver._create_volume_replica, self.vol,
                          vg, vg, rep.rpo)

    def test_delete_by_ref(self):
        """Test _delete_by_ref."""
        result = self.driver._delete_by_ref(self.driver.client, 'volume',
                                            'name', 'message')
        self.assertIsNone(result)

    def test_failover_volume(self):
        """Test _failover_volume."""
        self.driver.target = FakeKrest()
        session_name = self.driver.get_session_name('1234567890987654321')
        self.assertEqual('ssn-1234567890987654321', session_name)
        rsession_name = self.driver.get_rep_name(session_name)
        self.assertEqual('rssn-1234567890987654321', rsession_name)
        result = self.driver._failover_volume(self.vol)
        self.assertIsNone(result)

    @mock.patch.object(kaminario_common.KaminarioCinderDriver,
                       '_check_for_status')
    @mock.patch.object(objects.service.Service, 'get_by_args')
    def test_failover_host(self, get_by_args, check_stauts):
        """Test failover_host."""
        mock_args = mock.Mock()
        mock_args.active_backend_id = '10.0.0.1'
        self.vol.replication_status = 'failed-over'
        self.driver.configuration.san_ip = '10.0.0.1'
        get_by_args.side_effect = [mock_args, mock_args]
        self.driver.host = 'host'
        volumes = [self.vol, self.vol]
        self.driver.replica = Replication()
        self.driver.target = FakeKrest()
        self.driver.target.search().total = 1
        self.driver.client.search().total = 1
        backend_ip, res_volumes, __ = self.driver.failover_host(
            None, volumes, [])
        self.assertEqual('10.0.0.1', backend_ip)
        status = res_volumes[0]['updates']['replication_status']
        self.assertEqual(fields.ReplicationStatus.FAILED_OVER, status)
        # different backend ip
        self.driver.configuration.san_ip = '10.0.0.2'
        self.driver.client.search().hits[0].state = 'in_sync'
        backend_ip, res_volumes, __ = self.driver.failover_host(
            None, volumes, [])
        self.assertEqual('10.0.0.2', backend_ip)
        status = res_volumes[0]['updates']['replication_status']
        self.assertEqual(fields.ReplicationStatus.DISABLED, status)

    def test_delete_volume_replica(self):
        """Test _delete_volume_replica."""
        self.driver.replica = Replication()
        self.driver.target = FakeKrest()
        session_name = self.driver.get_session_name('1234567890987654321')
        self.assertEqual('ssn-1234567890987654321', session_name)
        rsession_name = self.driver.get_rep_name(session_name)
        self.assertEqual('rssn-1234567890987654321', rsession_name)
        res = self.driver._delete_by_ref(self.driver.client, 'volumes',
                                         'test', 'test')
        self.assertIsNone(res)
        result = self.driver._delete_volume_replica(self.vol, 'test', 'test')
        self.assertIsNone(result)
        src_ssn = self.driver.client.search("replication/sessions").hits[0]
        self.assertEqual('idle', src_ssn.state)

    def test_delete_volume_replica_exp(self):
        """Test _delete_volume_replica_exp."""
        self.driver.replica = Replication()
        self.driver.target = FakeKrestException()
        self.driver._check_for_status = mock.Mock()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver._delete_volume_replica, self.vol,
                          'test', 'test')

    def test_get_is_replica(self):
        """Test get_is_replica."""
        result = self.driver._get_is_replica(self.vol.volume_type)
        self.assertFalse(result)

    def test_get_is_replica_true(self):
        """Test get_is_replica_true."""
        self.driver.replica = Replication()
        self.vol.volume_type.extra_specs = {'kaminario:replication': 'enabled'}
        result = self.driver._get_is_replica(self.vol.volume_type)
        self.assertTrue(result)

    def test_after_volume_copy(self):
        """Test after_volume_copy."""
        result = self.driver.after_volume_copy(None, self.vol,
                                               self.vol.volume_type)
        self.assertIsNone(result)

    def test_retype(self):
        """Test retype."""
        replica_status = self.driver._get_replica_status('test')
        self.assertTrue(replica_status)
        replica = self.driver._get_is_replica(self.vol.volume_type)
        self.assertFalse(replica)
        self.driver.replica = Replication()
        result = self.driver._add_replication(self.vol)
        self.assertIsNone(result)
        self.driver.target = FakeKrest()
        self.driver._check_for_status = mock.Mock()
        result = self.driver._delete_replication(self.vol)
        self.assertIsNone(result)
        self.driver._delete_volume_replica = mock.Mock()
        result = self.driver.retype(None, self.vol,
                                    self.vol.volume_type, None, None)
        self.assertTrue(result)
        new_vol_type = fake_volume.fake_volume_type_obj(self.context)
        new_vol_type.extra_specs = {'kaminario:thin_prov_type': 'nodedup'}
        result2 = self.driver.retype(None, self.vol,
                                     new_vol_type, None, None)
        self.assertFalse(result2)

    def test_add_replication(self):
        """"Test _add_replication."""
        self.driver.replica = Replication()
        result = self.driver._add_replication(self.vol)
        self.assertIsNone(result)

    def test_delete_replication(self):
        """Test _delete_replication."""
        self.driver.replica = Replication()
        self.driver.target = FakeKrest()
        self.driver._check_for_status = mock.Mock()
        result = self.driver._delete_replication(self.vol)
        self.assertIsNone(result)

    def test_create_failover_volume_replica(self):
        """Test _create_failover_volume_replica."""
        self.driver.replica = Replication()
        self.driver.target = FakeKrest()
        self.driver.configuration.san_ip = '10.0.0.1'
        result = self.driver._create_failover_volume_replica(self.vol,
                                                             'test', 'test')
        self.assertIsNone(result)

    def test_create_volume_replica_user_snap(self):
        """Test create_volume_replica_user_snap."""
        result = self.driver._create_volume_replica_user_snap(FakeKrest(),
                                                              'sess')
        self.assertEqual(548, result)

    def test_is_user_snap_sync_finished(self):
        """Test _is_user_snap_sync_finished."""
        sess_mock = mock.Mock()
        sess_mock.refresh = mock.Mock()
        sess_mock.generation_number = 548
        sess_mock.current_snapshot_id = None
        sess_mock.current_snapshot_progress = 100
        sess_mock.current_snapshot_id = None
        self.driver.snap_updates = [{'tgt_ssn': sess_mock, 'gno': 548,
                                     'stime': time.time()}]
        result = self.driver._is_user_snap_sync_finished()
        self.assertIsNone(result)

    def test_delete_failover_volume_replica(self):
        """Test _delete_failover_volume_replica."""
        self.driver.target = FakeKrest()
        result = self.driver._delete_failover_volume_replica(self.vol, 'test',
                                                             'test')
        self.assertIsNone(result)

    def test_get_initiator_host_name(self):
        result = self.driver.get_initiator_host_name(CONNECTOR)
        self.assertEqual(CONNECTOR['host'], result)

    def test_get_initiator_host_name_unique(self):
        self.driver.configuration.unique_fqdn_network = False
        result = self.driver.get_initiator_host_name(CONNECTOR)
        expected = re.sub('[:.]', '_', CONNECTOR['initiator'][::-1][:32])
        self.assertEqual(expected, result)


@ddt.ddt
class TestKaminarioISCSI(TestKaminarioCommon):
    def test_get_target_info(self):
        """Test get_target_info."""
        iscsi_portals, target_iqns = self.driver.get_target_info(self.vol)
        self.assertEqual(['10.0.0.1:3260', '10.0.0.2:3260'],
                         iscsi_portals)
        self.assertEqual(['xyztlnxyz', 'xyztlnxyz'],
                         target_iqns)

    @ddt.data(True, False)
    def test_initialize_connection(self, multipath):
        """Test initialize_connection."""
        connector = CONNECTOR.copy()
        connector['multipath'] = multipath
        self.driver.configuration.disable_discovery = False

        conn_info = self.driver.initialize_connection(self.vol, CONNECTOR)
        expected = {
            'data': {
                'target_discovered': True,
                'target_iqn': 'xyztlnxyz',
                'target_lun': 548,
                'target_portal': '10.0.0.1:3260',
            },
            'driver_volume_type': 'iscsi',
        }
        self.assertEqual(expected, conn_info)

    def test_initialize_connection_multipath(self):
        """Test initialize_connection with multipath."""
        connector = CONNECTOR.copy()
        connector['multipath'] = True
        self.driver.configuration.disable_discovery = True

        conn_info = self.driver.initialize_connection(self.vol, connector)

        expected = {
            'data': {
                'target_discovered': True,
                'target_iqn': 'xyztlnxyz',
                'target_iqns': ['xyztlnxyz', 'xyztlnxyz'],
                'target_lun': 548,
                'target_luns': [548, 548],
                'target_portal': '10.0.0.1:3260',
                'target_portals': ['10.0.0.1:3260', '10.0.0.2:3260'],
            },
            'driver_volume_type': 'iscsi',
        }
        self.assertEqual(expected, conn_info)

    def test_terminate_connection(self):
        """Test terminate_connection."""
        result = self.driver.terminate_connection(self.vol, CONNECTOR)
        self.assertIsNone(result)

    def test_terminate_connection_without_connector(self):
        """Test terminate_connection_without_connector."""
        result = self.driver.terminate_connection(self.vol, None)
        self.assertIsNone(result)


class TestKaminarioFC(TestKaminarioCommon):

    def _setup_driver(self):
        self.driver = (kaminario_fc.
                       KaminarioFCDriver(configuration=self.conf))
        device = mock.Mock(return_value={'device': {'path': '/dev'}})
        self.driver._connect_device = device
        self.driver.client = FakeKrest()
        self.driver._lookup_service = mock.Mock()

    def test_initialize_connection(self):
        """Test initialize_connection."""
        conn_info = self.driver.initialize_connection(self.vol, CONNECTOR)
        self.assertIn('data', conn_info)
        self.assertIn('target_wwn', conn_info['data'])

    def test_get_target_info(self):
        """Test get_target_info."""
        target_wwpn = self.driver.get_target_info(self.vol)
        self.assertEqual(['50024f4053300301', '50024f4053300302'],
                         target_wwpn)

    def test_terminate_connection(self):
        """Test terminate_connection."""
        result = self.driver.terminate_connection(self.vol, CONNECTOR)
        self.assertIn('data', result)

    def test_terminate_connection_without_connector(self):
        """Test terminate_connection_without_connector."""
        result = self.driver.terminate_connection(self.vol, None)
        self.assertIn('data', result)

    def test_get_initiator_host_name_unique(self):
        connector = CONNECTOR.copy()
        del connector['initiator']
        self.driver.configuration.unique_fqdn_network = False
        result = self.driver.get_initiator_host_name(connector)
        expected = re.sub('[:.]', '_', connector['wwnns'][0][::-1][:32])
        self.assertEqual(expected, result)
