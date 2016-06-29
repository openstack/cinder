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
import mock

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder import utils
from cinder.volume import configuration
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
        self.ntype = kwargs.get('ntype')
        self.ip_address = '10.0.0.1'
        self.iscsi_qualified_target_name = "xyztlnxyz"
        self.snapshot = FakeK2Obj()
        self.name = 'test'
        self.pwwn = '50024f4053300300'

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
    hits = [FakeSaveObject()]
    total = 1

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


class TestKaminarioISCSI(test.TestCase):
    driver = None
    conf = None

    def setUp(self):
        self._setup_config()
        self._setup_driver()
        super(TestKaminarioISCSI, self).setUp()
        self.context = context.get_admin_context()
        self.vol = fake_volume.fake_volume_obj(self.context)
        self.vol.volume_type = fake_volume.fake_volume_type_obj(self.context)
        self.snap = fake_snapshot.fake_snapshot_obj(self.context)
        self.snap.volume = self.vol

    def _setup_config(self):
        self.conf = mock.Mock(spec=configuration.Configuration)
        self.conf.kaminario_dedup_type_name = "dedup"
        self.conf.volume_dd_blocksize = 2

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
        result = self.driver.create_snapshot(self.snap)
        self.assertIsNone(result)

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

    def test_initialize_connection(self):
        """Test initialize_connection."""
        conn_info = self.driver.initialize_connection(self.vol, CONNECTOR)
        self.assertIn('data', conn_info)
        self.assertIn('target_iqn', conn_info['data'])

    def test_initialize_connection_with_exception(self):
        """Test initialize_connection_with_exception."""
        self.driver.client = FakeKrestException()
        self.assertRaises(exception.KaminarioCinderDriverException,
                          self.driver.initialize_connection, self.vol,
                          CONNECTOR)

    def test_terminate_connection(self):
        """Test terminate_connection."""
        result = self.driver.terminate_connection(self.vol, CONNECTOR)
        self.assertIsNone(result)

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
        self.assertEqual(1, host_rs.total)
        self.assertEqual('test-k2', host_name)

    def test_get_target_info(self):
        """Test get_target_info."""
        iscsi_portal, target_iqn = self.driver.get_target_info()
        self.assertEqual('10.0.0.1:3260', iscsi_portal)
        self.assertEqual('xyztlnxyz', target_iqn)

    def test_k2_initialize_connection(self):
        """Test k2_initialize_connection."""
        result = self.driver.k2_initialize_connection(self.vol, CONNECTOR)
        self.assertEqual(548, result)


class TestKaminarioFC(TestKaminarioISCSI):

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
        target_wwpn = self.driver.get_target_info()
        self.assertEqual(['50024f4053300300'], target_wwpn)

    def test_terminate_connection(self):
        """Test terminate_connection."""
        result = self.driver.terminate_connection(self.vol, CONNECTOR)
        self.assertIn('data', result)
