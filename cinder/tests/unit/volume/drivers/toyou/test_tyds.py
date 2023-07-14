# Copyright 2023 toyou Corp.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import unittest
from unittest import mock

from cinder import exception
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume.drivers.toyou.tyds import tyds as driver

POOLS_NAME = ['pool1', 'pool2']


class TestTydsDriver(unittest.TestCase):
    @mock.patch('cinder.volume.drivers.toyou.tyds.tyds_client.TydsClient',
                autospec=True)
    def setUp(self, mock_tyds_client):
        """Set up the test case.

        - Creates a driver instance.
        - Mocks the TydsClient and its methods.
        - Initializes volumes and snapshots for testing.
        """
        super().setUp()
        self.mock_client = mock_tyds_client.return_value
        self.mock_do_request = mock.MagicMock(
            side_effect=self.mock_client.do_request)
        self.mock_client.do_request = self.mock_do_request

        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.tyds_pools = POOLS_NAME
        self.configuration.san_ip = "23.44.56.78"
        self.configuration.tyds_http_port = 80
        self.configuration.san_login = 'admin'
        self.configuration.san_password = 'admin'
        self.configuration.tyds_stripe_size = '4M'
        self.configuration.tyds_clone_progress_interval = 3
        self.configuration.tyds_copy_progress_interval = 3
        self.driver = driver.TYDSDriver(configuration=self.configuration)
        self.driver.do_setup(context=None)
        self.driver.check_for_setup_error()

        self.volume = fake_volume.fake_volume_obj(None)
        self.volume.host = 'host@backend#pool1'
        self.snapshot = fake_snapshot.fake_snapshot_obj(None)
        self.snapshot.volume = self.volume
        self.snapshot.volume_id = self.volume.id
        self.target_volume = fake_volume.fake_volume_obj(None)
        self.target_volume.host = 'host@backend#pool2'
        self.src_vref = self.volume

    def test_create_volume_success(self):
        """Test case for successful volume creation.

        - Sets mock return value.
        - Calls create_volume method.
        - Verifies if the create_volume method is called with correct
        arguments.
        """
        self.mock_client.create_volume.return_value = self.volume
        self.driver.create_volume(self.volume)
        self.mock_client.create_volume.assert_called_once_with(
            self.volume.name, self.volume.size * 1024, 'pool1', '4M')

    def test_create_volume_failure(self):
        """Test case for volume creation failure.

        - Sets the mock return value to simulate a failure.
        - Calls the create_volume method.
        - Verifies if the create_volume method raises the expected exception.
        """
        # Set the mock return value to simulate a failure
        self.mock_client.create_volume.side_effect = \
            exception.VolumeBackendAPIException('API error')

        # Call the create_volume method and check the result
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume,
            self.volume
        )

    def test_delete_volume_success(self):
        """Test case for successful volume deletion.

        - Mocks the _get_volume_by_name method to return a volume.
        - Calls the delete_volume method.
        - Verifies if the delete_volume method is called with the correct
        volume ID.
        """
        # Mock the _get_volume_by_name method to return a volume
        self.driver._get_volume_by_name = mock.Mock(return_value={'id': '13'})

        # Call the delete_volume method
        self.driver.delete_volume(self.volume)

        # Verify if the delete_volume method is called with the correct
        # volume ID
        self.mock_client.delete_volume.assert_called_once_with('13')

    def test_delete_volume_failure(self):
        """Test case for volume deletion failure.

        - Mocks the _get_volume_by_name method to return a volume.
        - Sets the mock return value for delete_volume method to raise an
        exception.
        - Calls the delete_volume method.
        - Verifies if the delete_volume method raises the expected exception.
        """
        # Mock the _get_volume_by_name method to return a volume
        self.driver._get_volume_by_name = mock.Mock(return_value={'id': '13'})

        # Set the mock return value for delete_volume method to raise an
        # exception
        self.mock_client.delete_volume.side_effect = \
            exception.VolumeBackendAPIException('API error')

        # Call the delete_volume method and verify if it raises the expected
        # exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, self.volume)

    def test_create_snapshot_success(self):
        """Test case for successful snapshot creation.

        - Sets the mock return value for create_snapshot method.
        - Mocks the _get_volume_by_name method to return a volume.
        - Calls the create_snapshot method.
        - Verifies if the create_snapshot method is called with the correct
        arguments.
        """
        # Set the mock return value for create_snapshot method
        self.mock_client.create_snapshot.return_value = self.snapshot

        # Mock the _get_volume_by_name method to return a volume
        self.driver._get_volume_by_name = mock.Mock(return_value={'id': '13'})

        # Call the create_snapshot method
        self.driver.create_snapshot(self.snapshot)

        # Verify if the create_snapshot method is called with the correct
        # arguments
        self.mock_client.create_snapshot.assert_called_once_with(
            self.snapshot.name, '13',
            '%s/%s' % (self.volume.name, self.snapshot.name)
        )

    def test_create_snapshot_failure_with_no_volume(self):
        """Test case for snapshot creation failure when volume is not found.

        - Mocks the _get_volume_by_name method to return None.
        - Calls the create_snapshot method.
        - Verifies if the create_snapshot method is not called.
        """
        # Mock the _get_volume_by_name method to return None
        self.driver._get_volume_by_name = mock.Mock(return_value=None)

        # Call the create_snapshot method and check for exception
        self.assertRaises(driver.TYDSDriverException,
                          self.driver.create_snapshot, self.snapshot)

        # Verify if the create_snapshot method is not called
        self.mock_client.create_snapshot.assert_not_called()

    def test_create_snapshot_failure(self):
        """Test case for snapshot creation failure.

        - Mocks the _get_volume_by_name method to return a volume.
        - Sets the mock return value for create_snapshot to raise an exception.
        - Calls the create_snapshot method.
        - Verifies if the create_snapshot method is called with the correct
        arguments.
        """
        # Mock the _get_volume_by_name method to return a volume
        self.driver._get_volume_by_name = mock.Mock(return_value={'id': '13'})

        # Set the mock return value for create_snapshot to raise an exception
        self.mock_client.create_snapshot.side_effect = \
            exception.VolumeBackendAPIException('API error')

        # Call the create_snapshot method and check for exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, self.snapshot)

        # Verify if the create_snapshot method is called with the correct
        # arguments
        self.mock_client.create_snapshot.assert_called_once_with(
            self.snapshot.name, '13',
            '%s/%s' % (self.volume.name, self.snapshot.name))

    def test_delete_snapshot_success(self):
        """Test case for successful snapshot deletion.

        - Mocks the _get_snapshot_by_name method to return a snapshot.
        - Calls the delete_snapshot method.
        - Verifies if the delete_snapshot method is called with the correct
        arguments.
        """
        # Mock the _get_snapshot_by_name method to return a snapshot
        self.driver._get_snapshot_by_name = mock.Mock(
            return_value={'id': 'volume_id'})

        # Call the delete_snapshot method
        self.driver.delete_snapshot(self.snapshot)

        # Verify if the delete_snapshot method is called with the correct
        # arguments
        self.mock_client.delete_snapshot.assert_called_once_with('volume_id')

    def test_delete_snapshot_failure(self):
        """Test case for snapshot deletion failure.

        - Mocks the _get_snapshot_by_name method to return a snapshot.
        - Sets the mock return value for delete_snapshot to raise an exception.
        - Calls the delete_snapshot method.
        - Verifies if the delete_snapshot method is called with the correct
        arguments.
        """
        # Mock the _get_snapshot_by_name method to return a snapshot
        self.driver._get_snapshot_by_name = mock.Mock(
            return_value={'id': 'volume_id'})

        # Set the mock return value for delete_snapshot to raise an exception
        self.mock_client.delete_snapshot.side_effect = \
            exception.VolumeBackendAPIException('API error')

        # Call the delete_snapshot method and check for exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot,
                          self.snapshot)

        # Verify if the delete_snapshot method is called once
        self.mock_client.delete_snapshot.assert_called_once()

    @mock.patch('time.sleep')
    @mock.patch('cinder.coordination.synchronized', new=mock.MagicMock())
    def test_create_volume_from_snapshot_success(self, mock_sleep):
        """Test case for successful volume creation from snapshot.

        - Mocks the sleep function.
        - Sets the mock return values for create_volume_from_snapshot,
        _get_volume_by_name, and get_clone_progress.
        - Calls the create_volume_from_snapshot method.
        - Verifies if the create_volume_from_snapshot method is called with
        the correct arguments.
        - Verifies if the _get_volume_by_name method is called once.
        """
        # Mock the sleep function
        mock_sleep.return_value = None

        # Set the mock return values for create_volume_from_snapshot,
        # _get_volume_by_name, and get_clone_progress
        self.mock_client.create_volume_from_snapshot.return_value = self.volume
        self.driver._get_volume_by_name = mock.Mock(
            return_value={'poolName': 'pool1',
                          'sizeMB': self.volume.size * 1024})
        self.mock_client.get_clone_progress.return_value = {'progress': '100%'}

        # Call the create_volume_from_snapshot method
        self.driver.create_volume_from_snapshot(self.target_volume,
                                                self.snapshot)

        # Verify if the create_volume_from_snapshot method is called with the
        # correct arguments
        self.mock_client.create_volume_from_snapshot.assert_called_once_with(
            self.target_volume.name, 'pool2', self.snapshot.name,
            self.volume.name, 'pool1')

        # Verify if the _get_volume_by_name method is called once
        self.driver._get_volume_by_name.assert_called_once()

    def test_create_volume_from_snapshot_failure(self):
        """Test case for volume creation from snapshot failure.

        - Sets the mock return value for _get_volume_by_name to return None.
        - Calls the create_volume_from_snapshot method.
        - Verifies if the create_volume_from_snapshot method raises a
        driver.TYDSDriverException.
        """
        # Set the mock return value for _get_volume_by_name to return None
        self.driver._get_volume_by_name = mock.Mock(return_value=None)

        # Call the create_volume_from_snapshot method and check for exception
        self.assertRaises(driver.TYDSDriverException,
                          self.driver.create_volume_from_snapshot,
                          self.volume, self.snapshot)

    @mock.patch('cinder.coordination.synchronized', new=mock.MagicMock())
    def test_create_cloned_volume_success(self):
        """Test case for successful cloned volume creation.

        - Sets the mock return values for get_copy_progress, get_pools,
        get_volumes, and _get_volume_by_name.
        - Calls the create_cloned_volume method.
        - Verifies if the create_clone_volume method is called with the correct
         arguments.
        """
        # Set the mock return values for get_copy_progress, get_pools,
        # get_volumes, and _get_volume_by_name
        self.mock_client.get_copy_progress.return_value = {'progress': '100%'}
        self.driver.client.get_pools.return_value = [
            {'name': 'pool1', 'id': 'pool1_id'},
            {'name': 'pool2', 'id': 'pool2_id'}
        ]
        self.driver.client.get_volumes.return_value = [
            {'blockName': self.volume.name, 'poolName': 'pool1',
             'id': 'source_volume_id'}
        ]
        self.driver._get_volume_by_name = mock.Mock(
            return_value={'name': self.volume.name, 'id': '13'})

        # Call the create_cloned_volume method
        self.driver.create_cloned_volume(self.target_volume, self.src_vref)

        # Verify if the create_clone_volume method is called with the correct
        # arguments
        self.driver.client.create_clone_volume.assert_called_once_with(
            'pool1', self.volume.name, 'source_volume_id', 'pool2', 'pool2_id',
            self.target_volume.name
        )

    @mock.patch('cinder.coordination.synchronized', new=mock.MagicMock())
    def test_create_cloned_volume_failure(self):
        """Test case for cloned volume creation failure.

        - Sets the mock return values for get_pools and get_volumes.
        - Calls the create_cloned_volume method.
        - Verifies if the create_cloned_volume method raises a
        driver.TYDSDriverException.
        """
        # Set the mock return values for get_pools and get_volumes
        self.driver.client.get_pools.return_value = [
            {'name': 'pool1', 'id': 'pool1_id'},
            {'name': 'pool2', 'id': 'pool2_id'}
        ]
        self.driver.client.get_volumes.return_value = [
            {'blockName': self.volume.name, 'poolName': None, 'id': '14'}
        ]

        # Call the create_cloned_volume method and check for exception
        self.assertRaises(driver.TYDSDriverException,
                          self.driver.create_cloned_volume,
                          self.target_volume,
                          self.src_vref)

    def test_extend_volume_success(self):
        """Test case for successful volume extension.

        - Sets the new size.
        - Calls the extend_volume method.
        - Verifies if the extend_volume method is called with the correct
        arguments.
        """
        new_size = 10

        # Call the extend_volume method
        self.driver.extend_volume(self.volume, new_size)

        # Verify if the extend_volume method is called with the correct
        # arguments
        self.mock_client.extend_volume.assert_called_once_with(
            self.volume.name, 'pool1', new_size * 1024)

    def test_extend_volume_failure(self):
        """Test case for volume extension failure.

        - Sets the new size and error message.
        - Sets the mock side effect for extend_volume to raise an Exception.
        - Calls the extend_volume method.
        - Verifies if the extend_volume method raises the expected exception
        and the error message matches.
        - Verifies if the extend_volume method is called with the correct
        arguments.
        """
        new_size = 10

        # Set the mock side effect for extend_volume to raise an Exception
        self.mock_client.extend_volume.side_effect = \
            exception.VolumeBackendAPIException('API Error: Volume extend')

        # Call the extend_volume method and check for exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, self.volume, new_size)

        # Verify if the extend_volume method is called with the correct
        # arguments
        self.mock_client.extend_volume.assert_called_once_with(
            self.volume.name, 'pool1', new_size * 1024)

    def test_get_volume_stats(self):
        """Test case for retrieving volume statistics.

        - Sets the mock side effect for safe_get to return the appropriate
        values.
        - Sets the mock return values for get_pools and get_volumes.
        - Calls the get_volume_stats method.
        - Verifies if the get_pools and get_volumes methods are called once.
        - Verifies if the retrieved statistics match the expected statistics.
        """

        def safe_get_side_effect(param_name):
            if param_name == 'volume_backend_name':
                return 'toyou_backend'

        # Set the mock side effect for safe_get to return the appropriate
        # values
        self.configuration.safe_get.side_effect = safe_get_side_effect

        # Set the mock return values for get_pools and get_volumes
        self.mock_client.get_pools.return_value = [
            {'name': 'pool1',
             'stats': {'max_avail': '107374182400', 'stored': '53687091200'}},
            {'name': 'pool2',
             'stats': {'max_avail': '214748364800', 'stored': '107374182400'}}
        ]
        self.mock_client.get_volumes.return_value = [
            {'poolName': 'pool1', 'sizeMB': '1024'},
            {'poolName': 'pool1', 'sizeMB': '2048'},
            {'poolName': 'pool2', 'sizeMB': '3072'}
        ]

        # Call the get_volume_stats method
        stats = self.driver.get_volume_stats()

        # Verify if the get_pools and get_volumes methods are called once
        self.mock_client.get_pools.assert_called_once()
        self.mock_client.get_volumes.assert_called_once()

        # Define the expected statistics
        expected_stats = {
            'vendor_name': 'TOYOU',
            'driver_version': '1.0.0',
            'volume_backend_name': 'toyou_backend',
            'pools': [
                {
                    'pool_name': 'pool1',
                    'total_capacity_gb': 100.0,
                    'free_capacity_gb': 50.0,
                    'provisioned_capacity_gb': 3.0,
                    'thin_provisioning_support': True,
                    'QoS_support': False,
                    'consistencygroup_support': False,
                    'total_volumes': 2,
                    'multiattach': False
                },
                {
                    'pool_name': 'pool2',
                    'total_capacity_gb': 200.0,
                    'free_capacity_gb': 100.0,
                    'provisioned_capacity_gb': 3.0,
                    'thin_provisioning_support': True,
                    'QoS_support': False,
                    'consistencygroup_support': False,
                    'total_volumes': 1,
                    'multiattach': False
                }
            ],
            'storage_protocol': 'iSCSI',
        }

        # Verify if the retrieved statistics match the expected statistics
        self.assertEqual(stats, expected_stats)

    def test_get_volume_stats_pool_not_found(self):
        """Test case for retrieving volume statistics when pool not found.

        - Sets the mock return value for get_pools to an empty list.
        - Calls the get_volume_stats method.
        - Verifies if the get_pools method is called once.
        - Verifies if the get_volume_stats method raises a
        driver.TYDSDriverException.
        """
        # Set the mock return value for get_pools to an empty list
        self.mock_client.get_pools.return_value = []

        # Call the get_volume_stats method and check for exception
        self.assertRaises(driver.TYDSDriverException,
                          self.driver.get_volume_stats)

        # Verify if the get_pools method is called once
        self.mock_client.get_pools.assert_called_once()

    def test_initialize_connection_success(self):
        """Test case for successful volume initialization.

        - Sets the connector information.
        - Sets the mock return values for get_initiator_list and get_target.
        - Sets the mock return values and assertions for create_initiator_group
        , create_target, modify_target, and generate_config.
        - Calls the initialize_connection method.
        - Verifies the expected return value and method calls.
        """
        # Set the connector information
        connector = {
            'host': 'host1',
            'initiator': 'iqn.1234',
            'ip': '192.168.0.1',
            'uuid': 'uuid1'
        }

        # Set the mock return values for get_initiator_list and get_target
        self.mock_client.get_initiator_list.return_value = []
        self.mock_client.get_target.return_value = [
            {'name': 'iqn.2023-06.com.toyou:uuid1', 'ipAddr': '192.168.0.2'}]

        # Set the mock return values and assertions for create_initiator_group,
        # create_target, modify_target, and generate_config
        self.mock_client.create_initiator_group.return_value = None
        self.mock_client.create_target.return_value = None
        self.mock_client.modify_target.return_value = None
        self.mock_client.generate_config.return_value = None
        self.mock_client.get_initiator_target_connections.side_effect = [
            [],  # First call returns an empty list
            [{'target_name': 'iqn.2023-06.com.toyou:initiator-group-uuid1',
              'target_iqn': 'iqn1',
              'block': [{'name': 'volume1', 'lunid': 0}]}]
            # Second call returns a non-empty dictionary
        ]

        # Call the initialize_connection method
        result = self.driver.initialize_connection(self.volume, connector)

        # Define the expected return value
        expected_return = {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_discovered': False,
                'target_portal': '192.168.0.2:3260',
                'target_lun': 0,
                'target_iqns': ['iqn.2023-06.com.toyou:initiator-group-uuid1'],
                'target_portals': ['192.168.0.2:3260'],
                'target_luns': [0]
            }
        }

        # Verify the method calls and return value
        self.mock_client.get_initiator_list.assert_called_once()
        self.mock_client.create_initiator_group.assert_called_once()
        self.assertEqual(
            self.mock_client.get_initiator_target_connections.call_count, 2)
        self.assertEqual(self.mock_client.get_target.call_count, 2)
        self.mock_client.modify_target.assert_not_called()
        self.mock_client.create_target.assert_called_once()
        self.mock_client.generate_config.assert_called_once()

        self.assertEqual(result, expected_return)

    def test_initialize_connection_failure(self):
        """Test case for failed volume initialization.

        - Sets the connector information.
        - Sets the mock return values for get_initiator_list and get_it.
        - Calls the initialize_connection method.
        - Verifies if the get_initiator_list method is called once.
        - Verifies if the create_initiator_group method is not called.
        - Verifies if the initialize_connection method raises an exception to
        type exception.VolumeBackendAPIException.
        """
        # Set the connector information
        connector = {
            'host': 'host1',
            'initiator': 'iqn.1234',
            'ip': '192.168.0.1',
            'uuid': 'uuid1'
        }

        # Set the mock return values for get_initiator_list and get_it
        self.mock_client.get_initiator_list.return_value = [
            {'group_name': 'initiator-group-uuid1'}]
        self.mock_client.get_initiator_target_connections.return_value = []

        # Call the initialize_connection method and check for exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection, self.volume,
                          connector)

        # Verify if the get_initiator_list method is called once
        self.mock_client.get_initiator_list.assert_called_once()

        # Verify if the create_initiator_group method is not called
        self.mock_client.create_initiator_group.assert_not_called()

    def test_terminate_connection_success(self):
        """Test case for successful termination of volume connection.

        - Sets the connector information.
        - Sets the mock return values for get_it and get_initiator_list.
        - Calls the terminate_connection method with the required mock methods.
        - Verifies the method calls using assertions.
        """
        # Set the connector information
        connector = {
            'host': 'host1',
            'initiator': 'iqn.1234',
            'ip': '192.168.0.1',
            'uuid': 'uuid1'
        }

        # Set the mock return values for get_it and get_initiator_list
        self.mock_client.get_initiator_target_connections.return_value = [
            {'target_iqn': 'target_iqn1',
             'target_name': 'target1',
             'hostName': ['host1'],
             'block': [{'name': 'volume1', 'lunid': 1},
                       {'name': 'volume2', 'lunid': 2}]}
        ]
        self.mock_client.get_initiator_list.return_value = [
            {'group_name': 'initiator-group-uuid1', 'group_id': 'group_id1'}
        ]

        # Call the terminate_connection method with the required mock methods
        self.driver.terminate_connection(
            self.volume,
            connector,
            mock_get_it=self.mock_client.get_initiator_target_connections,
            mock_delete_target=self.mock_client.delete_target,
            mock_get_initiator_list=self.mock_client.get_initiator_list,
            mock_delete_initiator_group=self.mock_client
            .delete_initiator_group,
            mock_restart_service=self.mock_client.restart_service,
        )

        # Verify the method calls using assertions
        self.mock_client.get_initiator_target_connections.assert_called_once()
        self.mock_client.get_initiator_list.assert_not_called()
        self.mock_client.delete_target.assert_not_called()
        self.mock_client.delete_initiator_group.assert_not_called()
        self.mock_client.restart_service.assert_not_called()

    def test_terminate_connection_failure(self):
        """Test case for failed termination of volume connection.

        - Sets the connector information.
        - Sets the mock return values for get_it and get_initiator_list.
        - Sets the delete_target method to raise an exception.
        - Calls the terminate_connection method.
        - Verifies the method calls and assertions.
        """
        # Set the connector information
        connector = {
            'host': 'host1',
            'initiator': 'iqn.1234',
            'ip': '192.168.0.1',
            'uuid': 'uuid1'
        }

        # Set the mock return values for get_it and get_initiator_list
        self.mock_client.get_initiator_target_connections.return_value = [
            {
                'target_iqn': 'target_iqn1',
                'target_name': 'iqn.2023-06.com.toyou:initiator-group-uuid1',
                'hostName': ['host1'],
                'block': [{'name': self.volume.name, 'lunid': 1}]
            }
        ]
        self.mock_client.get_initiator_list.return_value = [
            {'group_name': 'initiator-group-uuid1', 'group_id': 'group_id1'}
        ]

        # Set the delete_target method to raise an exception
        self.mock_client.delete_target.side_effect = \
            exception.VolumeBackendAPIException('API error')

        # Assert that an exception to type exception.VolumeBackendAPIException
        # is raised
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          self.volume,
                          connector)

        # Verify method calls and assertions
        self.mock_client.get_initiator_target_connections.assert_called_once()
        self.mock_client.get_initiator_list.assert_not_called()
        self.mock_client.delete_target.assert_called_once_with('target_iqn1')
        self.mock_client.delete_initiator_group.assert_not_called()
        self.mock_client.restart_service.assert_not_called()
