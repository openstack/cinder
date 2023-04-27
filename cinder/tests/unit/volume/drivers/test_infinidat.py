# Copyright 2022 Infinidat Ltd.
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
"""Unit tests for INFINIDAT InfiniBox volume driver."""

import collections
import copy
import functools
import itertools
import platform
import socket
from unittest import mock
import uuid

import ddt
from oslo_utils import units

from cinder import exception
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test
from cinder import version
from cinder.volume import configuration
from cinder.volume.drivers import infinidat


TEST_LUN = 1
TEST_WWN_1 = '00:11:22:33:44:55:66:77'
TEST_WWN_2 = '11:11:22:33:44:55:66:77'
TEST_IP_ADDRESS1 = '1.1.1.1'
TEST_IP_ADDRESS2 = '2.2.2.2'
TEST_IP_ADDRESS3 = '3.3.3.3'
TEST_IP_ADDRESS4 = '4.4.4.4'
TEST_INITIATOR_IQN = 'iqn.2012-07.org.initiator:01'
TEST_INITIATOR_IQN2 = 'iqn.2012-07.org.initiator:02'
TEST_TARGET_IQN = 'iqn.2012-07.org.target:01'
TEST_ISCSI_TCP_PORT1 = 3261
TEST_ISCSI_TCP_PORT2 = 3262
TEST_ISCSI_NAMESPACE1 = 'netspace1'
TEST_ISCSI_NAMESPACE2 = 'netspace2'
TEST_TARGET_PORTAL1 = '{}:{}'.format(TEST_IP_ADDRESS1, TEST_ISCSI_TCP_PORT1)
TEST_TARGET_PORTAL2 = '{}:{}'.format(TEST_IP_ADDRESS2, TEST_ISCSI_TCP_PORT1)
TEST_TARGET_PORTAL3 = '{}:{}'.format(TEST_IP_ADDRESS3, TEST_ISCSI_TCP_PORT2)
TEST_TARGET_PORTAL4 = '{}:{}'.format(TEST_IP_ADDRESS4, TEST_ISCSI_TCP_PORT2)
TEST_FC_PROTOCOL = 'fc'
TEST_ISCSI_PROTOCOL = 'iscsi'
TEST_VOLUME_SOURCE_NAME = 'test-volume'
TEST_VOLUME_TYPE = 'MASTER'
TEST_VOLUME_SOURCE_ID = 12345
TEST_VOLUME_METADATA = {'cinder_id': fake.VOLUME_ID}
TEST_SNAPSHOT_SOURCE_NAME = 'test-snapshot'
TEST_SNAPSHOT_SOURCE_ID = 67890
TEST_SNAPSHOT_METADATA = {'cinder_id': fake.SNAPSHOT_ID}
TEST_POOL_NAME = 'pool'
TEST_POOL_NAME2 = 'pool2'
TEST_SYSTEM_SERIAL = 123
TEST_SYSTEM_SERIAL2 = 456

test_volume = mock.Mock(id=fake.VOLUME_ID, name_id=fake.VOLUME_ID, size=1,
                        volume_type_id=fake.VOLUME_TYPE_ID, group_id=None,
                        multiattach=False, volume_attachment=None)
test_volume2 = mock.Mock(id=fake.VOLUME2_ID, name_id=fake.VOLUME2_ID, size=1,
                         volume_type_id=None, group_id=None,
                         multiattach=False, volume_attachment=None)
test_volume3 = mock.Mock(id=fake.VOLUME3_ID, name_id=fake.VOLUME3_ID, size=1,
                         volume_type_id=fake.VOLUME_TYPE_ID,
                         group_id=fake.GROUP_ID, multiattach=True,
                         volume_attachment=None)
test_snapshot = mock.Mock(id=fake.SNAPSHOT_ID, volume=test_volume)
test_clone = mock.Mock(id=fake.VOLUME4_ID, name_id=fake.VOLUME4_ID, size=1,
                       volume_type_id=fake.VOLUME_TYPE_ID, group_id=None,
                       multiattach=False, volume_attachment=None)
test_group = mock.Mock(id=fake.GROUP_ID)
test_snapgroup = mock.Mock(id=fake.GROUP_SNAPSHOT_ID, group=test_group)
test_connector = dict(wwpns=[TEST_WWN_1],
                      initiator=TEST_INITIATOR_IQN)
test_connector2 = dict(wwpns=[TEST_WWN_2],
                       initiator=TEST_INITIATOR_IQN2)
test_connector3 = dict(wwpns=None, initiator=None)
test_attachment1 = mock.Mock(connector=test_connector)
test_attachment2 = mock.Mock(connector=test_connector2)
test_attachment3 = mock.Mock(connector=None)


def skip_driver_setup(func):
    @functools.wraps(func)
    def f(*args, **kwargs):
        return func(*args, **kwargs)
    f.__skip_driver_setup = True
    return f


class FakeInfinisdkException(Exception):
    pass


class InfiniboxDriverTestCaseBase(test.TestCase):
    def _test_skips_driver_setup(self):
        test_method_name = self.id().split('.')[-1]
        test_method = getattr(self, test_method_name)
        return getattr(test_method, '__skip_driver_setup', False)

    def setUp(self):
        super(InfiniboxDriverTestCaseBase, self).setUp()

        self.configuration = configuration.Configuration(None)
        self.configuration.append_config_values(infinidat.infinidat_opts)
        self.override_config('san_ip', 'infinibox',
                             configuration.SHARED_CONF_GROUP)
        self.override_config('san_login', 'user',
                             configuration.SHARED_CONF_GROUP)
        self.override_config('san_password', 'password',
                             configuration.SHARED_CONF_GROUP)
        self.override_config('infinidat_pool_name', TEST_POOL_NAME)
        self.driver = infinidat.InfiniboxVolumeDriver(
            configuration=self.configuration)
        self._system = self._infinibox_mock()
        # mock external library dependencies
        infinisdk = self.patch("cinder.volume.drivers.infinidat.infinisdk")
        capacity = self.patch("cinder.volume.drivers.infinidat.capacity")
        self._log = self.patch("cinder.volume.drivers.infinidat.LOG")
        self._iqn = self.patch("cinder.volume.drivers.infinidat.iqn")
        self._wwn = self.patch("cinder.volume.drivers.infinidat.wwn")
        self._wwn.WWN = mock.Mock
        self._iqn.IQN = mock.Mock
        capacity.byte = 1
        capacity.GiB = units.Gi
        infinisdk.core.exceptions.InfiniSDKException = FakeInfinisdkException
        infinisdk.InfiniBox.return_value = self._system

        if not self._test_skips_driver_setup():
            self.driver.do_setup(None)

    def _infinibox_mock(self):
        result = mock.Mock()
        self._mock_volume = mock.Mock()
        self._mock_new_volume = mock.Mock()
        self._mock_volume.get_id.return_value = TEST_VOLUME_SOURCE_ID
        self._mock_volume.get_name.return_value = TEST_VOLUME_SOURCE_NAME
        self._mock_volume.get_type.return_value = TEST_VOLUME_TYPE
        self._mock_volume.get_pool_name.return_value = TEST_POOL_NAME
        self._mock_volume.get_size.return_value = 1 * units.Gi
        self._mock_volume.has_children.return_value = False
        self._mock_volume.get_qos_policy.return_value = None
        self._mock_volume.get_logical_units.return_value = []
        self._mock_volume.get_all_metadata.return_value = {}
        self._mock_volume.create_snapshot.return_value = self._mock_volume
        self._mock_snapshot = mock.Mock()
        self._mock_snapshot.get_parent.return_value = self._mock_volume
        self._mock_host = mock.Mock()
        self._mock_host.get_luns.return_value = []
        self._mock_host.map_volume().get_lun.return_value = TEST_LUN
        self._mock_pool = mock.Mock()
        self._mock_pool.get_free_physical_capacity.return_value = units.Gi
        self._mock_pool.get_physical_capacity.return_value = units.Gi
        self._mock_pool.get_volumes.return_value = [self._mock_volume]
        self._mock_name_space1 = mock.Mock()
        self._mock_name_space2 = mock.Mock()
        self._mock_name_space1.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS1, enabled=True)]
        self._mock_name_space2.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS3, enabled=True)]
        self._mock_name_space1.get_properties.return_value = mock.Mock(
            iscsi_iqn=TEST_TARGET_IQN, iscsi_tcp_port=TEST_ISCSI_TCP_PORT1)
        self._mock_name_space2.get_properties.return_value = mock.Mock(
            iscsi_iqn=TEST_TARGET_IQN, iscsi_tcp_port=TEST_ISCSI_TCP_PORT2)
        self._mock_group = mock.Mock()
        self._mock_qos_policy = mock.Mock()
        result.volumes.safe_get.return_value = self._mock_volume
        result.volumes.create.return_value = self._mock_volume
        result.pools.safe_get.return_value = self._mock_pool
        result.hosts.safe_get.return_value = self._mock_host
        result.cons_groups.safe_get.return_value = self._mock_group
        result.cons_groups.create.return_value = self._mock_group
        result.hosts.create.return_value = self._mock_host
        result.network_spaces.safe_get.return_value = self._mock_name_space1
        result.components.nodes.get_all.return_value = []
        result.qos_policies.create.return_value = self._mock_qos_policy
        result.qos_policies.safe_get.return_value = None
        result.get_serial.return_value = TEST_SYSTEM_SERIAL
        return result

    def _raise_infinisdk(self, *args, **kwargs):
        raise FakeInfinisdkException()


@ddt.ddt
class InfiniboxDriverTestCase(InfiniboxDriverTestCaseBase):
    def _generate_mock_object_metadata(self, cinder_object):
        return {"system": "openstack",
                "openstack_version": version.version_info.release_string(),
                "cinder_id": cinder_object.id,
                "cinder_name": cinder_object.name,
                "host.created_by": infinidat._INFINIDAT_CINDER_IDENTIFIER}

    def _validate_object_metadata(self, infinidat_object, cinder_object):
        infinidat_object.set_metadata_from_dict.assert_called_once_with(
            self._generate_mock_object_metadata(cinder_object))

    def _generate_mock_host_metadata(self):
        return {"system": "openstack",
                "openstack_version": version.version_info.release_string(),
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "host.created_by": infinidat._INFINIDAT_CINDER_IDENTIFIER}

    def _validate_host_metadata(self):
        self._mock_host.set_metadata_from_dict.assert_called_once_with(
            self._generate_mock_host_metadata())

    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_get_oslo_driver_opts')
    def test_get_driver_options(self, _get_oslo_driver_opts):
        _get_oslo_driver_opts.return_value = []
        result = self.driver.get_driver_options()
        actual = (infinidat.infinidat_opts)
        self.assertEqual(actual, result)

    @skip_driver_setup
    def test__setup_and_get_system_object(self):
        # This test should skip the driver setup, as it generates more calls to
        # the add_auto_retry, set_source_identifier and login methods:
        auth = (self.configuration.san_login,
                self.configuration.san_password)

        self.driver._setup_and_get_system_object(
            self.configuration.san_ip, auth)

        self._system.api.add_auto_retry.assert_called_once()
        self._system.api.set_source_identifier.assert_called_once_with(
            infinidat._INFINIDAT_CINDER_IDENTIFIER)
        self._system.login.assert_called_once()

    @skip_driver_setup
    @mock.patch('cinder.volume.drivers.infinidat.infinisdk', None)
    def test_do_setup_no_infinisdk(self):
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.do_setup, None)

    @mock.patch('cinder.volume.drivers.infinidat.infinisdk.InfiniBox')
    @ddt.data(True, False)
    def test_ssl_options(self, use_ssl, infinibox):
        auth = (self.configuration.san_login,
                self.configuration.san_password)
        self.override_config('driver_use_ssl', use_ssl)
        self.driver.do_setup(None)
        infinibox.assert_called_once_with(self.configuration.san_ip,
                                          auth=auth, use_ssl=use_ssl)

    def test_create_export_snapshot(self):
        self.assertIsNone(self.driver.create_export_snapshot(
            None, test_snapshot, test_connector))

    def test_remove_export_snapshot(self):
        self.assertIsNone(self.driver.remove_export_snapshot(
            None, test_snapshot))

    def test_backup_use_temp_snapshot(self):
        self.assertTrue(self.driver.backup_use_temp_snapshot())

    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_get_infinidat_snapshot')
    def test_initialize_connection_snapshot(self, get_snapshot):
        result = self.driver.initialize_connection_snapshot(
            test_snapshot, test_connector)
        get_snapshot.assert_called_once_with(test_snapshot)
        self.assertEqual(1, result["data"]["target_lun"])

    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_get_infinidat_volume')
    def test_initialize_connection(self, get_volume):
        self._system.hosts.safe_get.return_value = None
        result = self.driver.initialize_connection(test_volume, test_connector)
        get_volume.assert_called_once_with(test_volume)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_host_exists(self):
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_mapping_exists(self):
        mock_mapping = mock.Mock()
        mock_mapping.get_volume.return_value = self._mock_volume
        mock_mapping.get_lun.return_value = 888
        self._mock_host.get_luns.return_value = [mock_mapping]
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(888, result["data"]["target_lun"])

    def test_initialize_connection_mapping_not_found(self):
        mock_mapping = mock.Mock()
        mock_mapping.get_volume.return_value = None
        self._mock_host.get_luns.return_value = [mock_mapping]
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(TEST_LUN, result["data"]["target_lun"])

    def test_initialize_connection_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_create_fails(self):
        self._system.hosts.safe_get.return_value = None
        self._system.hosts.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_map_fails(self):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_metadata(self):
        self._system.hosts.safe_get.return_value = None
        self.driver.initialize_connection(test_volume, test_connector)
        self._validate_host_metadata()

    @ddt.data({'connector': None, 'multiattach': True,
               'attachment': [test_attachment1, test_attachment1]},
              {'connector': test_connector3, 'multiattach': True,
               'attachment': [test_attachment1, test_attachment1]},
              {'connector': test_connector, 'multiattach': False,
               'attachment': [test_attachment1]},
              {'connector': test_connector, 'multiattach': True,
               'attachment': None},
              {'connector': test_connector, 'multiattach': True,
               'attachment': [test_attachment2, test_attachment3]})
    @ddt.unpack
    def test__is_volume_multiattached_negative(self, connector,
                                               multiattach, attachment):
        volume = copy.deepcopy(test_volume)
        volume.multiattach = multiattach
        volume.volume_attachment = attachment
        self.assertFalse(self.driver._is_volume_multiattached(volume,
                                                              connector))

    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_terminate_connection')
    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_get_infinidat_volume')
    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_is_volume_multiattached')
    def test_terminate_connection(self, volume_multiattached, get_volume,
                                  terminate_connection):
        volume = copy.deepcopy(test_volume)
        volume.volume_attachment = [test_attachment1]
        volume_multiattached.return_value = False
        get_volume.return_value = self._mock_volume
        self.assertFalse(self.driver.terminate_connection(volume,
                                                          test_connector))
        volume_multiattached.assert_called_once_with(volume, test_connector)
        get_volume.assert_called_once_with(volume)
        terminate_connection.assert_called_once_with(self._mock_volume,
                                                     test_connector)

    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_terminate_connection')
    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_get_infinidat_snapshot')
    def test_terminate_connection_snapshot(self, get_snapshot,
                                           terminate_connection):
        get_snapshot.return_value = self._mock_snapshot
        self.assertIsNone(self.driver.terminate_connection_snapshot(
            test_snapshot, test_connector))
        get_snapshot.assert_called_once_with(test_snapshot)
        terminate_connection.assert_called_once_with(self._mock_snapshot,
                                                     test_connector)

    def test_terminate_connection_delete_host(self):
        self._mock_host.get_luns.return_value = [object()]
        volume = copy.deepcopy(test_volume)
        volume.volume_attachment = [test_attachment1]
        self.assertFalse(self.driver.terminate_connection(volume,
                                                          test_connector))
        self.assertEqual(0, self._mock_host.safe_delete.call_count)
        self._mock_host.get_luns.return_value = []
        self.assertFalse(self.driver.terminate_connection(volume,
                                                          test_connector))
        self.assertEqual(1, self._mock_host.safe_delete.call_count)

    def test_terminate_connection_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.terminate_connection,
                          test_volume, test_connector)

    def test_terminate_connection_api_fail(self):
        self._mock_host.unmap_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          test_volume, test_connector)

    def test_get_volume_stats_refreshes(self):
        result = self.driver.get_volume_stats()
        self.assertEqual(1, result["free_capacity_gb"])
        # change the "free space" in the pool
        self._mock_pool.get_free_physical_capacity.return_value = 0
        # no refresh - free capacity should stay the same
        result = self.driver.get_volume_stats(refresh=False)
        self.assertEqual(1, result["free_capacity_gb"])
        # refresh - free capacity should change to 0
        result = self.driver.get_volume_stats(refresh=True)
        self.assertEqual(0, result["free_capacity_gb"])

    def test_get_volume_stats_pool_not_found(self):
        self._system.pools.safe_get.return_value = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.get_volume_stats)

    def test_get_volume_stats_max_over_subscription_ratio(self):
        self.override_config('san_thin_provision', True)
        self.override_config('max_over_subscription_ratio', 10.0)
        result = self.driver.get_volume_stats()
        self.assertEqual('10.0', result['max_over_subscription_ratio'])
        self.assertTrue(result['thin_provisioning_support'])
        self.assertFalse(result['thick_provisioning_support'])

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume(self, *mocks):
        self.driver.create_volume(test_volume)

    def test_create_volume_pool_not_found(self):
        self._system.pools.safe_get.return_value = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume, test_volume)

    def test_create_volume_api_fail(self):
        self._system.pools.safe_get.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, test_volume)

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_metadata(self, *mocks):
        self.driver.create_volume(test_volume)
        self._validate_object_metadata(self._mock_volume, test_volume)

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_compression_enabled(self, *mocks):
        self.override_config('infinidat_use_compression', True)
        self.driver.create_volume(test_volume)
        self.assertTrue(
            self._system.volumes.create.call_args[1]["compression_enabled"]
        )

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_compression_disabled(self, *mocks):
        self.override_config('infinidat_use_compression', False)
        self.driver.create_volume(test_volume)
        self.assertFalse(
            self._system.volumes.create.call_args[1]["compression_enabled"]
        )

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_compression_default(self, *mocks):
        self.driver.create_volume(test_volume)
        self.assertNotIn(
            "compression_enabled",
            self._system.volumes.create.call_args[1]
        )

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    @mock.patch('cinder.volume.volume_utils.group_get_by_id')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_volume_within_group(self, *mocks):
        self.driver.create_volume(test_volume3)
        self._mock_group.add_member.assert_called_once()

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    @mock.patch('cinder.volume.volume_utils.group_get_by_id')
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_volume_within_no_cg_group(self, *mocks):
        self.driver.create_volume(test_volume3)
        self._mock_group.add_member.assert_not_called()

    def test_delete_volume(self):
        self.driver.delete_volume(test_volume)

    def test_delete_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        # should not raise an exception
        self.driver.delete_volume(test_volume)

    def test_delete_volume_with_children(self):
        self._mock_volume.has_children.return_value = True
        self.assertRaises(exception.VolumeIsBusy,
                          self.driver.delete_volume, test_volume)

    def test_extend_volume(self):
        self.driver.extend_volume(test_volume, 2)
        self._mock_volume.resize.assert_called_with(1 * units.Gi)

    def test_extend_volume_api_fail(self):
        self._mock_volume.resize.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, test_volume, 2)

    def test_create_snapshot(self):
        self.driver.create_snapshot(test_snapshot)

    def test_create_snapshot_metadata(self):
        self._mock_volume.create_snapshot.return_value = self._mock_volume
        self.driver.create_snapshot(test_snapshot)
        self._validate_object_metadata(self._mock_volume, test_snapshot)

    def test_create_snapshot_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.create_snapshot, test_snapshot)

    def test_create_snapshot_api_fail(self):
        self._mock_volume.create_snapshot.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, test_snapshot)

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_from_snapshot(self, *mocks):
        self.driver.create_volume_from_snapshot(test_clone, test_snapshot)

    def test_create_volume_from_snapshot_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.SnapshotNotFound,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    def test_create_volume_from_snapshot_create_fails(self):
        self._system.volumes.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_from_snapshot_map_fails(self, *mocks):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    @mock.patch('cinder.volume.volume_utils.brick_get_connector')
    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    @mock.patch('cinder.volume.volume_utils.brick_get_connector_properties')
    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_connect_device')
    def test_create_volume_from_snapshot_connect_fails(self, connect_device,
                                                       connector_properties,
                                                       *mocks):
        connector_properties.return_value = test_connector
        connect_device.side_effect = exception.DeviceUnavailable(
            path='/dev/sdb', reason='Block device required')
        self.assertRaises(exception.DeviceUnavailable,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    def test_delete_snapshot(self):
        self.driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        # should not raise an exception
        self.driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_api_fail(self):
        self._mock_volume.safe_delete.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, test_snapshot)

    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                'delete_snapshot')
    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                'create_volume_from_snapshot')
    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                'create_snapshot')
    @mock.patch('uuid.uuid4')
    def test_create_cloned_volume(self, mock_uuid, create_snapshot,
                                  create_volume_from_snapshot,
                                  delete_snapshot):
        mock_uuid.return_value = uuid.UUID(test_snapshot.id)
        snapshot_attributes = ('id', 'name', 'volume')
        Snapshot = collections.namedtuple('Snapshot', snapshot_attributes)
        snapshot_id = test_snapshot.id
        snapshot_name = self.configuration.snapshot_name_template % snapshot_id
        snapshot = Snapshot(id=snapshot_id, name=snapshot_name,
                            volume=test_volume)
        self.driver.create_cloned_volume(test_clone, test_volume)
        create_snapshot.assert_called_once_with(snapshot)
        create_volume_from_snapshot.assert_called_once_with(test_clone,
                                                            snapshot)
        delete_snapshot.assert_called_once_with(snapshot)

    def test_create_cloned_volume_create_fails(self):
        self._system.volumes.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_clone, test_volume)

    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_cloned_volume_map_fails(self, *mocks):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_clone, test_volume)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group(self, *mocks):
        self.driver.create_group(None, test_group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_generic_group(self, *mocks):
        self.assertRaises(NotImplementedError,
                          self.driver.create_group,
                          None, test_group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_metadata(self, *mocks):
        self.driver.create_group(None, test_group)
        self._validate_object_metadata(self._mock_group, test_group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_twice(self, *mocks):
        self.driver.create_group(None, test_group)
        self.driver.create_group(None, test_group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_api_fail(self, *mocks):
        self._system.cons_groups.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_group,
                          None, test_group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group(self, *mocks):
        self.driver.delete_group(None, test_group, [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_delete_generic_group(self, *mocks):
        self.assertRaises(NotImplementedError,
                          self.driver.delete_group,
                          None, test_group, [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_doesnt_exist(self, *mocks):
        self._system.cons_groups.safe_get.return_value = None
        self.driver.delete_group(None, test_group, [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_api_fail(self, *mocks):
        self._mock_group.safe_delete.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_group,
                          None, test_group, [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_update_group_add_and_remove(self, *mocks):
        self.driver.update_group(None, test_group,
                                 [test_volume], [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_update_generic_group_add_and_remove(self, *mocks):
        self.assertRaises(NotImplementedError,
                          self.driver.update_group,
                          None, test_group, [test_volume], [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_update_group_api_fail(self, *mocks):
        self._mock_group.add_member.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.update_group,
                          None, test_group,
                          [test_volume], [test_volume])

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_group_from_src_snaps(self, *mocks):
        self.driver.create_group_from_src(None, test_group, [test_volume],
                                          test_snapgroup, [test_snapshot],
                                          None, None)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_genericgroup_from_src_snaps(self, *mocks):
        self.assertRaises(NotImplementedError,
                          self.driver.create_group_from_src,
                          None, test_group, [test_volume],
                          test_snapgroup, [test_snapshot],
                          None, None)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_from_empty_sources(self, *mocks):
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_group_from_src,
                          None, test_group, [test_volume],
                          None, None, None, None)

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_group_from_src_vols(self, *mocks):
        self.driver.create_group_from_src(None, test_group, [test_volume],
                                          None, None,
                                          test_group, [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_snap(self, *mocks):
        mock_snapgroup = mock.Mock()
        mock_snapgroup.get_members.return_value = [self._mock_snapshot,
                                                   self._mock_snapshot]
        self._mock_volume.get_name.side_effect = [fake.VOLUME_NAME,
                                                  fake.VOLUME2_NAME]
        self._mock_group.create_snapshot.return_value = mock_snapgroup
        self.driver.create_group_snapshot(None, test_snapgroup,
                                          [test_snapshot, test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_generic_group_snap(self, *mocks):
        self.assertRaises(NotImplementedError,
                          self.driver.create_group_snapshot,
                          None, test_snapgroup, [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_snap_api_fail(self, *mocks):
        self._mock_group.create_snapshot.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_group_snapshot, None,
                          test_snapgroup, [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snap(self, *mocks):
        self.driver.delete_group_snapshot(None,
                                          test_snapgroup,
                                          [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_delete_generic_group_snap(self, *mocks):
        self.assertRaises(NotImplementedError,
                          self.driver.delete_group_snapshot,
                          None, test_snapgroup, [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snap_does_not_exist(self, *mocks):
        self._system.cons_groups.safe_get.return_value = None
        self.driver.delete_group_snapshot(None,
                                          test_snapgroup,
                                          [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snap_invalid_group(self, *mocks):
        self._mock_group.is_snapgroup.return_value = False
        self.assertRaises(exception.InvalidGroupSnapshot,
                          self.driver.delete_group_snapshot,
                          None, test_snapgroup, [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snap_api_fail(self, *mocks):
        self._mock_group.safe_delete.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_group_snapshot,
                          None, test_snapgroup, [test_snapshot])

    def test_snapshot_revert_use_temp_snapshot(self):
        result = self.driver.snapshot_revert_use_temp_snapshot()
        self.assertFalse(result)

    @ddt.data((1, 1), (1, 2))
    @ddt.unpack
    def test_revert_to_snapshot_resize(self, volume_size, snapshot_size):
        volume = copy.deepcopy(test_volume)
        snapshot = copy.deepcopy(test_snapshot)
        snapshot.volume.size = snapshot_size
        self._system.volumes.safe_get.side_effect = [self._mock_snapshot,
                                                     self._mock_volume,
                                                     self._mock_volume]
        self._mock_volume.get_size.side_effect = [volume_size * units.Gi,
                                                  volume_size * units.Gi]
        self.driver.revert_to_snapshot(None, volume, snapshot)
        self._mock_volume.restore.assert_called_once_with(self._mock_snapshot)
        if volume_size == snapshot_size:
            self._mock_volume.resize.assert_not_called()
        else:
            delta = (snapshot_size - volume_size) * units.Gi
            self._mock_volume.resize.assert_called_with(delta)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_by_source_name(self, *mocks):
        existing_ref = {'source-name': TEST_VOLUME_SOURCE_NAME}
        self.driver.manage_existing(test_volume, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_by_source_id(self, *mocks):
        existing_ref = {'source-id': TEST_VOLUME_SOURCE_ID}
        self.driver.manage_existing(test_volume, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_by_invalid_source(self, *mocks):
        existing_ref = {'source-path': None}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing,
                          test_volume, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    @mock.patch('cinder.volume.volume_utils.check_already_managed_volume',
                return_value=False)
    def test_manage_existing_not_managed(self, *mocks):
        self._mock_volume.get_all_metadata.return_value = (
            TEST_VOLUME_METADATA)
        existing_ref = {'source-name': TEST_VOLUME_SOURCE_NAME}
        self.driver.manage_existing(test_volume, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    @mock.patch('cinder.volume.volume_utils.check_already_managed_volume',
                return_value=True)
    def test_manage_existing_already_managed(self, *mocks):
        self._mock_volume.get_all_metadata.return_value = (
            TEST_VOLUME_METADATA)
        existing_ref = {'source-name': TEST_VOLUME_SOURCE_NAME}
        self.assertRaises(exception.ManageExistingAlreadyManaged,
                          self.driver.manage_existing,
                          test_volume, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_invalid_pool(self, *mocks):
        existing_ref = {'source-name': TEST_VOLUME_SOURCE_NAME}
        self._mock_volume.get_pool_name.return_value = TEST_POOL_NAME2
        self.assertRaises(exception.InvalidConfigurationValue,
                          self.driver.manage_existing,
                          test_volume, existing_ref)

    def test_manage_existing_get_size(self):
        existing_ref = {'source-name': TEST_VOLUME_SOURCE_NAME}
        size = self.driver.manage_existing_get_size(test_volume, existing_ref)
        self.assertEqual(test_volume.size, size)

    def test_get_manageable_volumes(self):
        cinder_volumes = [test_volume]
        self._mock_volume.is_snapshot.return_value = False
        self._mock_volume.get_all_metadata.return_value = {
            'cinder_id': fake.VOLUME2_ID
        }
        self.driver.get_manageable_volumes(cinder_volumes, None,
                                           1, 0, [], [])

    def test_get_manageable_volumes_already_managed(self):
        cinder_volumes = [test_volume]
        self._mock_volume.get_id.return_value = TEST_VOLUME_SOURCE_ID
        self._mock_volume.get_all_metadata.return_value = (
            TEST_VOLUME_METADATA)
        self._mock_volume.is_snapshot.return_value = False
        self.driver.get_manageable_volumes(cinder_volumes, None,
                                           1, 0, [], [])

    def test_get_manageable_volumes_but_snapshots(self):
        cinder_volumes = [test_volume]
        self._mock_volume.is_snapshot.return_value = True
        self.driver.get_manageable_volumes(cinder_volumes, None,
                                           1, 0, [], [])

    def test_get_manageable_volumes_has_mappings(self):
        cinder_volumes = [test_volume]
        self._mock_volume.is_snapshot.return_value = False
        self._mock_volume.get_all_metadata.return_value = {
            'cinder_id': fake.VOLUME2_ID
        }
        lun = mock.Mock()
        self._mock_volume.get_logical_units.return_value = [lun]
        self.driver.get_manageable_volumes(cinder_volumes, None,
                                           1, 0, [], [])

    def test_get_manageable_volumes_has_snapshots(self):
        cinder_volumes = [test_volume]
        self._mock_volume.is_snapshot.return_value = False
        self._mock_volume.has_children.return_value = True
        self._mock_volume.get_all_metadata.return_value = {
            'cinder_id': fake.VOLUME2_ID
        }
        self.driver.get_manageable_volumes(cinder_volumes, None,
                                           1, 0, [], [])

    def test_unmanage(self):
        self.driver.unmanage(test_volume)

    @mock.patch('cinder.objects.Snapshot.exists', return_value=True)
    def test__check_already_managed_snapshot(self, *mocks):
        self.driver._check_already_managed_snapshot(test_snapshot.id)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_snapshot_by_source_name(self, *mocks):
        existing_ref = {'source-name': TEST_SNAPSHOT_SOURCE_NAME}
        self.driver.manage_existing_snapshot(test_snapshot, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_snapshot_by_source_id(self, *mocks):
        existing_ref = {'source-id': TEST_SNAPSHOT_SOURCE_ID}
        self.driver.manage_existing_snapshot(test_snapshot, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_snapshot_but_volume(self, *mocks):
        existing_ref = {'source-id': TEST_SNAPSHOT_SOURCE_ID}
        self._mock_volume.is_snapshot.return_value = False
        self.assertRaises(exception.InvalidSnapshot,
                          self.driver.manage_existing_snapshot,
                          test_snapshot, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_snapshot_by_invalid_source(self, *mocks):
        existing_ref = {'source-path': None}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          test_snapshot, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_snapshot_by_non_cinder_id(self, *mocks):
        self._mock_volume.get_all_metadata.return_value = {'cinder_id': 'x'}
        existing_ref = {'source-id': TEST_SNAPSHOT_SOURCE_ID}
        self.driver.manage_existing_snapshot(test_snapshot, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_check_already_managed_snapshot', return_value=False)
    def test_manage_existing_snapshot_not_managed(self, *mocks):
        self._mock_volume.get_all_metadata.return_value = (
            TEST_SNAPSHOT_METADATA)
        existing_ref = {'source-name': TEST_SNAPSHOT_SOURCE_NAME}
        self.driver.manage_existing(test_snapshot, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_check_already_managed_snapshot', return_value=True)
    def test_manage_existing_snapshot_already_managed(self, *mocks):
        self._mock_volume.get_all_metadata.return_value = (
            TEST_SNAPSHOT_METADATA)
        existing_ref = {'source-name': TEST_SNAPSHOT_SOURCE_NAME}
        self.assertRaises(exception.ManageExistingAlreadyManaged,
                          self.driver.manage_existing_snapshot,
                          test_snapshot, existing_ref)

    @mock.patch('cinder.volume.volume_types.get_volume_type_qos_specs')
    def test_manage_existing_snapshot_invalid_pool(self, *mocks):
        existing_ref = {'source-name': TEST_SNAPSHOT_SOURCE_NAME}
        self._mock_volume.get_pool_name.return_value = TEST_POOL_NAME2
        self.assertRaises(exception.InvalidConfigurationValue,
                          self.driver.manage_existing_snapshot,
                          test_snapshot, existing_ref)

    def test_manage_existing_snapshot_get_size(self):
        existing_ref = {'source-name': TEST_SNAPSHOT_SOURCE_NAME}
        size = self.driver.manage_existing_snapshot_get_size(test_volume,
                                                             existing_ref)
        self.assertEqual(test_snapshot.volume.size, size)

    def test_get_manageable_snapshots(self):
        cinder_snapshots = [test_snapshot]
        self._mock_volume.is_snapshot.return_value = True
        self._mock_volume.get_all_metadata.return_value = {
            'cinder_id': fake.SNAPSHOT2_ID
        }
        self.driver.get_manageable_snapshots(cinder_snapshots,
                                             None, 1, 0, [], [])

    def test_get_manageable_snapshots_already_managed(self):
        cinder_snapshots = [test_snapshot]
        self._mock_volume.get_id.return_value = TEST_SNAPSHOT_SOURCE_ID
        self._mock_volume.get_all_metadata.return_value = (
            TEST_SNAPSHOT_METADATA)
        self._mock_volume.is_snapshot.return_value = True
        self.driver.get_manageable_snapshots(cinder_snapshots,
                                             None, 1, 0, [], [])

    def test_get_manageable_snapshots_but_volumes(self):
        cinder_snapshots = [test_snapshot]
        self._mock_volume.is_snapshot.return_value = False
        self.driver.get_manageable_snapshots(cinder_snapshots,
                                             None, 1, 0, [], [])

    def test_get_manageable_snapshots_has_mappings(self):
        cinder_snapshots = [test_snapshot]
        self._mock_volume.is_snapshot.return_value = True
        self._mock_volume.get_all_metadata.return_value = {
            'cinder_id': fake.SNAPSHOT2_ID
        }
        lun = mock.Mock()
        self._mock_volume.get_logical_units.return_value = [lun]
        self.driver.get_manageable_snapshots(cinder_snapshots,
                                             None, 1, 0, [], [])

    def test_get_manageable_snapshots_has_clones(self):
        cinder_snapshots = [test_snapshot]
        self._mock_volume.is_snapshot.return_value = True
        self._mock_volume.has_children.return_value = True
        self._mock_volume.get_all_metadata.return_value = {
            'cinder_id': fake.SNAPSHOT2_ID
        }
        self.driver.get_manageable_snapshots(cinder_snapshots,
                                             None, 1, 0, [], [])

    def test_unmanage_snapshot(self):
        self.driver.unmanage_snapshot(test_snapshot)

    def test_terminate_connection_no_attachment_connector(self):
        volume = copy.deepcopy(test_volume)
        volume.multiattach = True
        volume.volume_attachment = [test_attachment3]
        self.assertFalse(self.driver.terminate_connection(volume,
                                                          test_connector))

    def test_terminate_connection_no_host(self):
        self._system.hosts.safe_get.return_value = None
        volume = copy.deepcopy(test_volume)
        volume.volume_attachment = [test_attachment1]
        self.assertFalse(self.driver.terminate_connection(volume,
                                                          test_connector))

    def test_terminate_connection_no_mapping(self):
        self._mock_host.unmap_volume.side_effect = KeyError
        volume = copy.deepcopy(test_volume)
        volume.volume_attachment = [test_attachment1]
        self.assertFalse(self.driver.terminate_connection(volume,
                                                          test_connector))

    def test_update_migrated_volume_new_volume_not_found(self):
        self._system.volumes.safe_get.side_effect = [
            None, self._mock_volume]
        self.assertRaises(exception.VolumeNotFound,
                          self.driver.update_migrated_volume,
                          None, test_volume, test_volume2,
                          'available')

    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_set_cinder_object_metadata')
    def test_update_migrated_volume_volume_not_found(self, set_metadata):
        self._system.volumes.safe_get.side_effect = [
            self._mock_new_volume, None]
        update = self.driver.update_migrated_volume(None,
                                                    test_volume,
                                                    test_volume2,
                                                    'available')
        expected = {'_name_id': None, 'provider_location': None}
        self.assertEqual(expected, update)
        set_metadata.assert_called_once_with(self._mock_new_volume,
                                             test_volume)

    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_set_cinder_object_metadata')
    def test_update_migrated_new_volume_rename_error(self, set_metadata):
        self._system.volumes.safe_get.side_effect = [
            self._mock_new_volume, None]
        self._mock_new_volume.update_name.side_effect = [
            FakeInfinisdkException]
        update = self.driver.update_migrated_volume(None,
                                                    test_volume,
                                                    test_volume2,
                                                    'available')
        expected = {'_name_id': test_volume2.name_id,
                    'provider_location': None}
        self.assertEqual(expected, update)
        set_metadata.assert_called_once_with(self._mock_new_volume,
                                             test_volume)

    @mock.patch('cinder.volume.drivers.infinidat.InfiniboxVolumeDriver.'
                '_set_cinder_object_metadata')
    def test_update_migrated(self, set_metadata):
        self._system.volumes.safe_get.side_effect = [
            self._mock_new_volume, self._mock_volume]
        self._mock_new_volume.update_name.side_effect = None
        update = self.driver.update_migrated_volume(None,
                                                    test_volume,
                                                    test_volume2,
                                                    'available')
        expected = {'_name_id': test_volume2.name_id,
                    'provider_location': None}
        self.assertEqual(expected, update)
        set_metadata.assert_called_once_with(self._mock_new_volume,
                                             test_volume)
        self.assertEqual(0, self._log.error.call_count)

    @ddt.data(None, {})
    def test_migrate_volume_no_host(self, host):
        expected = False, None
        update = self.driver.migrate_volume(None, test_volume, host)
        self.assertEqual(expected, update)

    @ddt.data(None, {})
    def test_migrate_volume_no_capabilities(self, capabilities):
        expected = False, None
        host = {'capabilities': capabilities}
        update = self.driver.migrate_volume(None, test_volume, host)
        self.assertEqual(expected, update)

    @ddt.data(None, 123, 'location')
    def test_migrate_volume_invalid_location_info(self, location_info):
        expected = False, None
        capabilities = {'location_info': location_info}
        host = {'capabilities': capabilities}
        update = self.driver.migrate_volume(None, test_volume, host)
        self.assertEqual(expected, update)

    def test_migrate_volume_invalid_driver(self):
        expected = False, None
        location_info = 'vendor:0:/path'
        capabilities = {'location_info': location_info}
        host = {'capabilities': capabilities}
        update = self.driver.migrate_volume(None, test_volume, host)
        self.assertEqual(expected, update)

    def test_migrate_volume_invalid_serial(self):
        expected = False, None
        location_info = '%s:%s:%s' % (self.driver.__class__.__name__,
                                      TEST_SYSTEM_SERIAL2, TEST_POOL_NAME2)
        capabilities = {'location_info': location_info}
        host = {'capabilities': capabilities}
        update = self.driver.migrate_volume(None, test_volume, host)
        self.assertEqual(expected, update)

    def test_migrate_volume_same_pool(self):
        expected = True, None
        location_info = '%s:%s:%s' % (self.driver.__class__.__name__,
                                      TEST_SYSTEM_SERIAL, TEST_POOL_NAME)
        capabilities = {'location_info': location_info}
        host = {'capabilities': capabilities}
        update = self.driver.migrate_volume(None, test_volume, host)
        self.assertEqual(expected, update)

    def test_migrate_volume_no_pool(self):
        expected = False, None
        self._system.pools.safe_get.return_value = None
        location_info = '%s:%s:%s' % (self.driver.__class__.__name__,
                                      TEST_SYSTEM_SERIAL, TEST_POOL_NAME2)
        capabilities = {'location_info': location_info}
        host = {'capabilities': capabilities}
        update = self.driver.migrate_volume(None, test_volume, host)
        self.assertEqual(expected, update)

    def test_migrate_volume(self):
        expected = True, None
        location_info = '%s:%s:%s' % (self.driver.__class__.__name__,
                                      TEST_SYSTEM_SERIAL, TEST_POOL_NAME2)
        capabilities = {'location_info': location_info}
        host = {'capabilities': capabilities}
        update = self.driver.migrate_volume(None, test_volume, host)
        self.assertEqual(expected, update)


@ddt.ddt
class InfiniboxDriverTestCaseFC(InfiniboxDriverTestCaseBase):
    @ddt.data(*itertools.product(('UP', 'DOWN'), ('OK', 'ERROR')))
    @ddt.unpack
    def test_initialize_connection_nodes_ports(self, link_state, port_state):
        node = mock.Mock()
        port = mock.Mock()
        port.get_link_state.return_value = link_state
        port.get_state.return_value = port_state
        node.get_fc_ports.return_value = [port]
        self._system.components.nodes.get_all.return_value = [node]
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_multiple_wwpns(self):
        connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        result = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_validate_connector(self):
        fc_connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        iscsi_connector = {'initiator': TEST_INITIATOR_IQN}
        self.driver.validate_connector(fc_connector)
        self.assertRaises(exception.InvalidConnectorException,
                          self.driver.validate_connector, iscsi_connector)

    @ddt.data({'connector': test_connector,
               'attachment': [test_attachment1, test_attachment1]},
              {'connector': test_connector2,
               'attachment': [test_attachment2, test_attachment2]})
    @ddt.unpack
    def test__is_volume_multiattached_positive(self, connector, attachment):
        volume = copy.deepcopy(test_volume)
        volume.multiattach = True
        volume.volume_attachment = attachment
        self.assertTrue(self.driver._is_volume_multiattached(volume,
                                                             connector))

    def test_terminate_connection_multiattached_volume(self):
        volume = copy.deepcopy(test_volume)
        volume.multiattach = True
        volume.volume_attachment = [test_attachment1, test_attachment1]
        self.assertTrue(self.driver.terminate_connection(volume,
                                                         test_connector))

    def test_terminate_connection_force_detach(self):
        mock_infinidat_host = mock.Mock()
        mock_infinidat_host.get_ports.return_value = [
            self._wwn.WWN(TEST_WWN_1)]
        mock_mapping = mock.Mock()
        mock_mapping.get_host.return_value = mock_infinidat_host
        self._mock_volume.get_logical_units.return_value = [mock_mapping]
        volume = copy.deepcopy(test_volume)
        volume.volume_attachment = [test_attachment1, test_attachment2]
        self.assertTrue(self.driver.terminate_connection(volume, None))
        self._mock_host.unmap_volume.assert_called_once()
        self._mock_host.safe_delete.assert_called_once()


@ddt.ddt
class InfiniboxDriverTestCaseISCSI(InfiniboxDriverTestCaseBase):
    def setUp(self):
        super(InfiniboxDriverTestCaseISCSI, self).setUp()
        self.override_config('infinidat_storage_protocol',
                             TEST_ISCSI_PROTOCOL)
        self.override_config('infinidat_iscsi_netspaces',
                             [TEST_ISCSI_NAMESPACE1])
        self.override_config('use_chap_auth', False)
        self.driver.do_setup(None)

    def test_setup_without_netspaces_configured(self):
        self.override_config('infinidat_iscsi_netspaces', [])
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.do_setup, None)

    def test_initialize_connection(self):
        result = self.driver.initialize_connection(test_volume, test_connector)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL1,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL1
                ],
                'target_iqns': [
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    def test_initialize_netspace_does_not_exist(self):
        self._system.network_spaces.safe_get.return_value = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_netspace_has_no_ips(self):
        self._mock_name_space1.get_ips.return_value = []
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_with_chap(self):
        self.override_config('use_chap_auth', True)
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result['data']['target_lun'])
        self.assertEqual('CHAP', result['data']['auth_method'])
        self.assertIn('auth_username', result['data'])
        self.assertIn('auth_password', result['data'])

    def test_initialize_connection_multiple_netspaces(self):
        self.override_config('infinidat_iscsi_netspaces',
                             [TEST_ISCSI_NAMESPACE1, TEST_ISCSI_NAMESPACE2])
        self._system.network_spaces.safe_get.side_effect = [
            self._mock_name_space1, self._mock_name_space2]
        result = self.driver.initialize_connection(test_volume, test_connector)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL1,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL1,
                    TEST_TARGET_PORTAL3
                ],
                'target_iqns': [
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN,
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    def test_initialize_connection_multiple_netspaces_multipath(self):
        self.override_config('infinidat_iscsi_netspaces',
                             [TEST_ISCSI_NAMESPACE1, TEST_ISCSI_NAMESPACE2])
        self._system.network_spaces.safe_get.side_effect = [
            self._mock_name_space1, self._mock_name_space2]
        self._mock_name_space1.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS1, enabled=True),
            mock.Mock(ip_address=TEST_IP_ADDRESS2, enabled=True)]
        self._mock_name_space2.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS3, enabled=True),
            mock.Mock(ip_address=TEST_IP_ADDRESS4, enabled=True)]
        result = self.driver.initialize_connection(test_volume, test_connector)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL1,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL1,
                    TEST_TARGET_PORTAL2,
                    TEST_TARGET_PORTAL3,
                    TEST_TARGET_PORTAL4
                ],
                'target_iqns': [
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN,
                    TEST_LUN,
                    TEST_LUN,
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    def test_initialize_connection_disabled_interface(self):
        self._mock_name_space1.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS1, enabled=False),
            mock.Mock(ip_address=TEST_IP_ADDRESS2, enabled=True)]
        result = self.driver.initialize_connection(test_volume, test_connector)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL2,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL2
                ],
                'target_iqns': [
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    def test_initialize_connection_multiple_interfaces(self):
        self._mock_name_space1.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS1, enabled=True),
            mock.Mock(ip_address=TEST_IP_ADDRESS2, enabled=True)]
        self._mock_name_space1.get_properties.return_value = mock.Mock(
            iscsi_iqn=TEST_TARGET_IQN, iscsi_tcp_port=TEST_ISCSI_TCP_PORT1)
        result = self.driver.initialize_connection(test_volume, test_connector)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL1,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL1,
                    TEST_TARGET_PORTAL2
                ],
                'target_iqns': [
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN,
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    @ddt.data({'connector': test_connector,
               'attachment': [test_attachment1, test_attachment1]},
              {'connector': test_connector2,
               'attachment': [test_attachment2, test_attachment2]})
    @ddt.unpack
    def test__is_volume_multiattached_positive(self, connector, attachment):
        volume = copy.deepcopy(test_volume)
        volume.multiattach = True
        volume.volume_attachment = attachment
        self.assertTrue(self.driver._is_volume_multiattached(volume,
                                                             connector))

    def test_terminate_connection(self):
        volume = copy.deepcopy(test_volume)
        volume.volume_attachment = [test_attachment1]
        self.assertFalse(self.driver.terminate_connection(volume,
                                                          test_connector))

    def test_terminate_connection_force_detach(self):
        mock_infinidat_host = mock.Mock()
        mock_infinidat_host.get_ports.return_value = [
            self._iqn.IQN(TEST_TARGET_IQN)]
        mock_mapping = mock.Mock()
        mock_mapping.get_host.return_value = mock_infinidat_host
        self._mock_volume.get_logical_units.return_value = [mock_mapping]
        volume = copy.deepcopy(test_volume)
        volume.volume_attachment = [test_attachment1, test_attachment2]
        self.assertTrue(self.driver.terminate_connection(volume, None))
        self._mock_host.unmap_volume.assert_called_once()
        self._mock_host.safe_delete.assert_called_once()

    def test_validate_connector(self):
        fc_connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        iscsi_connector = {'initiator': TEST_INITIATOR_IQN}
        self.driver.validate_connector(iscsi_connector)
        self.assertRaises(exception.InvalidConnectorException,
                          self.driver.validate_connector, fc_connector)


class InfiniboxDriverTestCaseQoS(InfiniboxDriverTestCaseBase):
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_no_qos(self, qos_specs):
        qos_specs.return_value = None
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_max_ipos(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': None}}}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_called_once()
        self._mock_qos_policy.assign_entity.assert_called_once()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_max_bws(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': None,
                                                          'maxBWS': 10000}}}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_called_once()
        self._mock_qos_policy.assign_entity.assert_called_once()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_no_compat(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': 10000}}}
        self._system.compat.has_qos.return_value = False
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_volume_type_id_none(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': 10000}}}
        self.driver.create_volume(test_volume2)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_no_specs(self, qos_specs):
        qos_specs.return_value = {'qos_specs': None}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_front_end(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'front-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': 10000}}}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_specs_empty(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': None,
                                                          'maxBWS': None}}}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_policy_exists(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': 10000}}}
        self._system.qos_policies.safe_get.return_value = self._mock_qos_policy
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_called()
