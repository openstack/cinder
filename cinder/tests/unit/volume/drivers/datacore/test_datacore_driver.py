# Copyright (c) 2017 DataCore Software Corp. All Rights Reserved.
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

"""Unit tests for the base Driver for DataCore SANsymphony storage array."""

from __future__ import division

import abc
import mock

from oslo_utils import units

from cinder import exception as cinder_exception
from cinder.tests.unit import fake_constants
from cinder.tests.unit import utils as testutils
from cinder.volume import configuration as conf
from cinder.volume.drivers.datacore import driver as datacore_driver
from cinder.volume.drivers.datacore import exception as datacore_exception
from cinder.volume.drivers.san import san


SERVER_GROUPS = [
    mock.Mock(Id='server_group_id1',
              OurGroup=True),
    mock.Mock(Id='server_group_id2',
              OurGroup=False),
]

SERVERS = [
    mock.Mock(Id='server_id1',
              State='Online'),
    mock.Mock(Id='server_id2',
              State='Online'),
]

DISK_POOLS = [
    mock.Mock(Id='disk_pool_id1',
              Caption='disk_pool1',
              ServerId='server_id1',
              PoolStatus='Running'),
    mock.Mock(Id='disk_pool_id2',
              Caption='disk_pool2',
              ServerId='server_id2',
              PoolStatus='Running'),
    mock.Mock(Id='disk_pool_id3',
              Caption='disk_pool3',
              ServerId='server_id1',
              PoolStatus='Offline'),
    mock.Mock(Id='disk_pool_id4',
              Caption='disk_pool4',
              ServerId='server_id2',
              PoolStatus='Unknown'),
]

DISK_POOL_PERFORMANCE = [
    mock.Mock(ObjectId='disk_pool_id1',
              PerformanceData=mock.Mock(BytesTotal=5 * units.Gi,
                                        BytesAllocated=2 * units.Gi,
                                        BytesAvailable=3 * units.Gi,
                                        BytesReserved=0)),
    mock.Mock(ObjectId='disk_pool_id2',
              PerformanceData=mock.Mock(BytesTotal=5 * units.Gi,
                                        BytesAllocated=3 * units.Gi,
                                        BytesAvailable=1 * units.Gi,
                                        BytesReserved=1 * units.Gi)),
    mock.Mock(ObjectId='disk_pool_id3',
              PerformanceData=None),
    mock.Mock(ObjectId='disk_pool_id4',
              PerformanceData=None),
]

STORAGE_PROFILES = [
    mock.Mock(Id='storage_profile_id1',
              Caption='storage_profile1'),
    mock.Mock(Id='storage_profile_id2',
              Caption='storage_profile2'),
    mock.Mock(Id='storage_profile_id3',
              Caption='storage_profile3'),
]

VIRTUAL_DISKS = [
    mock.Mock(Id='virtual_disk_id1',
              DiskStatus='Online',
              IsServed=False,
              FirstHostId='server_id1'),
    mock.Mock(Id='virtual_disk_id2',
              DiskStatus='Failed',
              IsServed=False,
              FirstHostId='server_id2'),
    mock.Mock(Id='virtual_disk_id3',
              DiskStatus='Online',
              IsServed=True,
              FirstHostId='server_id1',
              SecondHostId='server_id2'),
    mock.Mock(Id='virtual_disk_id4',
              DiskStatus='Failed',
              IsServed=False,
              FirstHostId='server_id1',
              SecondHostId='server_id2'),
]

VIRTUAL_DISK_SNAPSHOTS = [
    mock.Mock(Id='snapshot_id1',
              State='Migrated',
              Failure='NoFailure',
              DestinationLogicalDiskId='logical_disk_id1'),
    mock.Mock(Id='snapshot_id2',
              State='Failed',
              Failure='NotAccessible',
              DestinationLogicalDiskId='logical_disk_id2'),
    mock.Mock(Id='snapshot_id3',
              State='Migrated',
              Failure='NoFailure',
              DestinationLogicalDiskId='logical_disk_id2'),
]

LOGICAL_DISKS = [
    mock.Mock(Id='logical_disk_id1',
              VirtualDiskId='virtual_disk_id1',
              ServerHostId='server_id1',
              PoolId='disk_pool_id1',
              Size=mock.Mock(Value=1 * units.Gi)),
    mock.Mock(Id='logical_disk_id2',
              VirtualDiskId='virtual_disk_id2',
              ServerHostId='server_id1',
              PoolId='disk_pool_id3',
              Size=mock.Mock(Value=1 * units.Gi)),
    mock.Mock(Id='logical_disk_id3',
              VirtualDiskId='virtual_disk_id3',
              ServerHostId='server_id1',
              PoolId='disk_pool_id1',
              Size=mock.Mock(Value=1 * units.Gi)),
    mock.Mock(Id='logical_disk_id4',
              VirtualDiskId='virtual_disk_id3',
              ServerHostId='server_id2',
              PoolId='disk_pool_id2',
              Size=mock.Mock(Value=1 * units.Gi)),
    mock.Mock(Id='logical_disk_id5',
              VirtualDiskId='virtual_disk_id4',
              ServerHostId='server_id1',
              PoolId='disk_pool_id3',
              Size=mock.Mock(Value=1 * units.Gi)),
    mock.Mock(Id='logical_disk_id6',
              VirtualDiskId='virtual_disk_id4',
              ServerHostId='server_id2',
              PoolId='disk_pool_id4',
              Size=mock.Mock(Value=1 * units.Gi)),
]

LOGICAL_UNITS = [
    mock.Mock(VirtualTargetDeviceId='target_device_id1',
              LogicalDiskId='logical_disk_id3'),
    mock.Mock(VirtualTargetDeviceId='target_device_id2',
              LogicalDiskId='logical_disk_id4'),
]

TARGET_DEVICES = [
    mock.Mock(Id='target_device_id1',
              InitiatorPortId='initiator_port_id1'),
    mock.Mock(Id='target_device_id2',
              InitiatorPortId='initiator_port_id1'),
]

CLIENTS = [
    mock.Mock(Id='client_id1',
              HostName='client_host_name1'),
    mock.Mock(Id='client_id2',
              HostName='client_host_name2'),
]

VOLUME = {
    'id': fake_constants.VOLUME_ID,
    'display_name': 'volume_1',
    'volume_type_id': None,
    'size': 1,
}

SNAPSHOT = {
    'id': fake_constants.SNAPSHOT_ID,
    'display_name': 'snapshot_1',
}


class DataCoreVolumeDriverTestCase(object):
    """Tests for the base Driver for DataCore SANsymphony storage array."""

    def setUp(self):
        super(DataCoreVolumeDriverTestCase, self).setUp()
        self.override_config('datacore_disk_failed_delay', 0)
        self.mock_client = mock.Mock()
        self.mock_client.get_servers.return_value = SERVERS
        self.mock_client.get_disk_pools.return_value = DISK_POOLS
        (self.mock_client.get_performance_by_type
         .return_value) = DISK_POOL_PERFORMANCE
        self.mock_client.get_virtual_disks.return_value = VIRTUAL_DISKS
        self.mock_client.get_storage_profiles.return_value = STORAGE_PROFILES
        self.mock_client.get_snapshots.return_value = VIRTUAL_DISK_SNAPSHOTS
        self.mock_client.get_logical_disks.return_value = LOGICAL_DISKS
        self.mock_client.get_clients.return_value = CLIENTS
        self.mock_client.get_server_groups.return_value = SERVER_GROUPS
        self.mock_object(datacore_driver.api,
                         'DataCoreClient',
                         return_value=self.mock_client)

    @staticmethod
    @abc.abstractmethod
    def init_driver(config):
        raise NotImplementedError()

    @staticmethod
    def create_configuration():
        config = conf.Configuration(None)
        config.append_config_values(san.san_opts)
        config.append_config_values(datacore_driver.datacore_opts)
        return config

    def setup_default_configuration(self):
        config = self.create_configuration()
        config.volume_backend_name = 'DataCore'
        config.san_ip = '127.0.0.1'
        config.san_login = 'dcsadmin'
        config.san_password = 'password'
        config.datacore_api_timeout = 0
        return config

    def test_do_setup(self):
        config = self.setup_default_configuration()
        self.init_driver(config)

    def test_do_setup_failed(self):
        config = self.setup_default_configuration()
        config.san_ip = None
        self.assertRaises(cinder_exception.InvalidInput,
                          self.init_driver,
                          config)

        config = self.setup_default_configuration()
        config.san_login = None
        self.assertRaises(cinder_exception.InvalidInput,
                          self.init_driver,
                          config)

        config = self.setup_default_configuration()
        config.san_password = None
        self.assertRaises(cinder_exception.InvalidInput,
                          self.init_driver,
                          config)

    def test_get_volume_stats(self):
        aggregation = [(getattr(perf.PerformanceData, 'BytesTotal', 0),
                        getattr(perf.PerformanceData, 'BytesAvailable', 0),
                        getattr(perf.PerformanceData, 'BytesReserved', 0),)
                       for perf in DISK_POOL_PERFORMANCE]

        total, available, reserved = map(sum, zip(*aggregation))
        free = (available + reserved) / units.Gi
        reserved = 100.0 * reserved / total
        total /= units.Gi
        provisioned = sum(disk.Size.Value for disk in LOGICAL_DISKS)
        provisioned /= units.Gi
        ratio = 2.0

        config = self.setup_default_configuration()
        config.max_over_subscription_ratio = ratio
        driver = self.init_driver(config)
        expected_volume_stats = {
            'vendor_name': 'DataCore',
            'QoS_support': False,
            'total_capacity_gb': total,
            'free_capacity_gb': free,
            'provisioned_capacity_gb': provisioned,
            'reserved_percentage': reserved,
            'max_over_subscription_ratio': ratio,
            'thin_provisioning_support': True,
            'thick_provisioning_support': False,
            'volume_backend_name': driver.get_volume_backend_name(),
            'driver_version': driver.get_version(),
            'storage_protocol': driver.get_storage_protocol(),
        }
        volume_stats = driver.get_volume_stats(refresh=True)
        self.assertDictEqual(expected_volume_stats, volume_stats)
        volume_stats_cached = driver.get_volume_stats(refresh=False)
        self.assertEqual(volume_stats, volume_stats_cached)

    def test_create_volume(self):
        virtual_disk = VIRTUAL_DISKS[0]
        self.mock_client.create_virtual_disk_ex2.return_value = virtual_disk

        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        result = driver.create_volume(volume)
        self.assertIn('provider_location', result)
        self.assertEqual(virtual_disk.Id, result['provider_location'])

    def test_create_volume_mirrored_disk_type_specified(self):
        virtual_disk = VIRTUAL_DISKS[2]
        self.mock_client.create_virtual_disk_ex2.return_value = virtual_disk

        config = self.setup_default_configuration()
        config.datacore_disk_type = 'mirrored'
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        result = driver.create_volume(volume)
        self.assertIn('provider_location', result)
        self.assertEqual(virtual_disk.Id, result['provider_location'])

        driver = self.init_driver(self.setup_default_configuration())
        volume_type = {
            'extra_specs': {driver.DATACORE_DISK_TYPE_KEY: 'mirrored'}
        }
        get_volume_type = self.mock_object(datacore_driver.volume_types,
                                           'get_volume_type')
        get_volume_type.return_value = volume_type
        volume = VOLUME.copy()
        volume['volume_type_id'] = 'volume_type_id'
        result = driver.create_volume(volume)
        self.assertIn('provider_location', result)
        self.assertEqual(virtual_disk.Id, result['provider_location'])

    def test_create_volume_profile_specified(self):
        virtual_disk = VIRTUAL_DISKS[0]
        self.mock_client.create_virtual_disk_ex2.return_value = virtual_disk

        config = self.setup_default_configuration()
        config.datacore_storage_profile = 'storage_profile1'
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        result = driver.create_volume(volume)
        self.assertIn('provider_location', result)
        self.assertEqual(virtual_disk.Id, result['provider_location'])

        volume_type = {
            'extra_specs': {
                driver.DATACORE_STORAGE_PROFILE_KEY: 'storage_profile2'
            }
        }
        get_volume_type = self.mock_object(datacore_driver.volume_types,
                                           'get_volume_type')
        get_volume_type.return_value = volume_type
        volume = VOLUME.copy()
        volume['volume_type_id'] = 'volume_type_id'
        result = driver.create_volume(volume)
        self.assertIn('provider_location', result)
        self.assertEqual(virtual_disk.Id, result['provider_location'])

    def test_create_volume_pool_specified(self):
        virtual_disk = VIRTUAL_DISKS[0]
        self.mock_client.create_virtual_disk_ex2.return_value = virtual_disk

        config = self.setup_default_configuration()
        config.datacore_disk_pools = ['disk_pool1']
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        result = driver.create_volume(volume)
        self.assertIn('provider_location', result)
        self.assertEqual(virtual_disk.Id, result['provider_location'])

        volume_type = {
            'extra_specs': {driver.DATACORE_DISK_POOLS_KEY: 'disk_pool2'}
        }
        get_volume_type = self.mock_object(datacore_driver.volume_types,
                                           'get_volume_type')
        get_volume_type.return_value = volume_type
        volume = VOLUME.copy()
        volume['volume_type_id'] = 'volume_type_id'
        result = driver.create_volume(volume)
        self.assertIn('provider_location', result)
        self.assertEqual(virtual_disk.Id, result['provider_location'])

    def test_create_volume_failed(self):
        def fail_with_datacore_fault(*args):
            raise datacore_exception.DataCoreFaultException(
                reason="General error.")

        (self.mock_client.create_virtual_disk_ex2
         .side_effect) = fail_with_datacore_fault

        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        self.assertRaises(datacore_exception.DataCoreFaultException,
                          driver.create_volume,
                          volume)

    def test_create_volume_unknown_disk_type_specified(self):
        config = self.setup_default_configuration()
        config.datacore_disk_type = 'unknown'
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_volume,
                          volume)

        driver = self.init_driver(self.setup_default_configuration())
        volume_type = {
            'extra_specs': {driver.DATACORE_DISK_TYPE_KEY: 'unknown'}
        }
        get_volume_type = self.mock_object(datacore_driver.volume_types,
                                           'get_volume_type')
        get_volume_type.return_value = volume_type
        volume = VOLUME.copy()
        volume['volume_type_id'] = 'volume_type_id'
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_volume,
                          volume)

    def test_create_volume_unknown_profile_specified(self):
        config = self.setup_default_configuration()
        config.datacore_storage_profile = 'unknown'
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_volume,
                          volume)

        driver = self.init_driver(self.setup_default_configuration())
        volume_type = {
            'extra_specs': {driver.DATACORE_STORAGE_PROFILE_KEY: 'unknown'}
        }
        get_volume_type = self.mock_object(datacore_driver.volume_types,
                                           'get_volume_type')
        get_volume_type.return_value = volume_type
        volume = VOLUME.copy()
        volume['volume_type_id'] = 'volume_type_id'
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_volume,
                          volume)

    def test_create_volume_on_failed_pool(self):
        config = self.setup_default_configuration()
        config.datacore_disk_pools = ['disk_pool3', 'disk_pool4']
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_volume,
                          volume)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_volume_await_online_timed_out(self):
        virtual_disk = VIRTUAL_DISKS[1]
        self.mock_client.create_virtual_disk_ex2.return_value = virtual_disk

        config = self.setup_default_configuration()
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_volume,
                          volume)

    def test_extend_volume(self):
        virtual_disk = VIRTUAL_DISKS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        driver.extend_volume(volume, 2147483648)

    def test_extend_volume_failed_not_found(self):
        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        volume['provider_location'] = 'wrong_virtual_disk_id'
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.extend_volume,
                          volume,
                          2147483648)

    def test_delete_volume(self):
        virtual_disk = VIRTUAL_DISKS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        driver.delete_volume(volume)

    def test_delete_volume_assigned(self):
        self.mock_client.get_logical_disks.return_value = LOGICAL_DISKS
        self.mock_client.get_logical_units.return_value = LOGICAL_UNITS
        self.mock_client.get_target_devices.return_value = TARGET_DEVICES

        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        virtual_disk = VIRTUAL_DISKS[2]
        volume['provider_location'] = virtual_disk.Id
        driver.delete_volume(volume)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_snapshot(self):
        virtual_disk = VIRTUAL_DISKS[0]
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[0]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        snapshot = SNAPSHOT.copy()
        snapshot['volume'] = volume
        result = driver.create_snapshot(snapshot)
        self.assertIn('provider_location', result)

    def test_create_snapshot_on_failed_pool(self):
        virtual_disk = VIRTUAL_DISKS[0]
        config = self.setup_default_configuration()
        config.datacore_disk_pools = ['disk_pool3', 'disk_pool4']
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        snapshot = SNAPSHOT.copy()
        snapshot['volume'] = volume
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_snapshot,
                          snapshot)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_snapshot_await_migrated_timed_out(self):
        virtual_disk = VIRTUAL_DISKS[0]
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[1]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        snapshot = SNAPSHOT.copy()
        snapshot['volume'] = volume
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_snapshot,
                          snapshot)

    def test_delete_snapshot(self):
        virtual_disk = VIRTUAL_DISKS[0]
        driver = self.init_driver(self.setup_default_configuration())
        snapshot = SNAPSHOT.copy()
        snapshot['provider_location'] = virtual_disk.Id
        driver.delete_snapshot(snapshot)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_volume_from_snapshot(self):
        virtual_disk = VIRTUAL_DISKS[0]
        self.mock_client.set_virtual_disk_size.return_value = virtual_disk
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[0]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        snapshot = SNAPSHOT.copy()
        snapshot['provider_location'] = virtual_disk.Id
        result = driver.create_volume_from_snapshot(volume, snapshot)
        self.assertIn('provider_location', result)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_volume_from_snapshot_mirrored_disk_type_specified(self):
        virtual_disk = VIRTUAL_DISKS[0]
        self.mock_client.set_virtual_disk_size.return_value = virtual_disk
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[0]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        config = self.setup_default_configuration()
        config.datacore_disk_type = 'mirrored'
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        snapshot = SNAPSHOT.copy()
        snapshot['provider_location'] = virtual_disk.Id
        result = driver.create_volume_from_snapshot(volume, snapshot)
        self.assertIn('provider_location', result)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_volume_from_snapshot_on_failed_pool(self):
        virtual_disk = VIRTUAL_DISKS[0]
        self.mock_client.set_virtual_disk_size.return_value = virtual_disk
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[0]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        config = self.setup_default_configuration()
        config.datacore_disk_type = 'mirrored'
        config.datacore_disk_pools = ['disk_pool1', 'disk_pool4']
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        snapshot = SNAPSHOT.copy()
        snapshot['provider_location'] = virtual_disk.Id
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_volume_from_snapshot,
                          volume,
                          snapshot)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_volume_from_snapshot_await_online_timed_out(self):
        virtual_disk = VIRTUAL_DISKS[0]
        snapshot_virtual_disk = VIRTUAL_DISKS[1]
        (self.mock_client.set_virtual_disk_size
         .return_value) = snapshot_virtual_disk
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[2]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        snapshot = SNAPSHOT.copy()
        snapshot['provider_location'] = virtual_disk.Id
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_volume_from_snapshot,
                          volume,
                          snapshot)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_cloned_volume(self):
        virtual_disk = VIRTUAL_DISKS[0]
        self.mock_client.set_virtual_disk_size.return_value = virtual_disk
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[0]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        src_vref = VOLUME.copy()
        src_vref['provider_location'] = virtual_disk.Id
        result = driver.create_cloned_volume(volume, src_vref)
        self.assertIn('provider_location', result)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_cloned_volume_mirrored_disk_type_specified(self):
        virtual_disk = VIRTUAL_DISKS[0]
        self.mock_client.set_virtual_disk_size.return_value = virtual_disk
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[0]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        config = self.setup_default_configuration()
        config.datacore_disk_type = 'mirrored'
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        src_vref = VOLUME.copy()
        src_vref['provider_location'] = virtual_disk.Id
        result = driver.create_cloned_volume(volume, src_vref)
        self.assertIn('provider_location', result)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_cloned_volume_on_failed_pool(self):
        virtual_disk = VIRTUAL_DISKS[0]
        self.mock_client.set_virtual_disk_size.return_value = virtual_disk
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[0]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        config = self.setup_default_configuration()
        config.datacore_disk_type = 'mirrored'
        config.datacore_disk_pools = ['disk_pool1', 'disk_pool4']
        driver = self.init_driver(config)
        volume = VOLUME.copy()
        src_vref = VOLUME.copy()
        src_vref['provider_location'] = virtual_disk.Id
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_cloned_volume,
                          volume,
                          src_vref)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_create_cloned_volume_await_online_timed_out(self):
        virtual_disk = VIRTUAL_DISKS[0]
        snapshot_virtual_disk = VIRTUAL_DISKS[1]
        (self.mock_client.set_virtual_disk_size
         .return_value) = snapshot_virtual_disk
        virtual_disk_snapshot = VIRTUAL_DISK_SNAPSHOTS[2]
        self.mock_client.create_snapshot.return_value = virtual_disk_snapshot

        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        src_vref = VOLUME.copy()
        src_vref['provider_location'] = virtual_disk.Id
        self.assertRaises(cinder_exception.VolumeDriverException,
                          driver.create_cloned_volume,
                          volume,
                          src_vref)

    def test_terminate_connection(self):
        virtual_disk = VIRTUAL_DISKS[0]
        client = CLIENTS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        connector = {'host': client.HostName}
        driver.terminate_connection(volume, connector)

    def test_terminate_connection_connector_is_none(self):
        virtual_disk = VIRTUAL_DISKS[0]
        driver = self.init_driver(self.setup_default_configuration())
        volume = VOLUME.copy()
        volume['provider_location'] = virtual_disk.Id
        driver.terminate_connection(volume, None)
