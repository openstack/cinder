# Copyright (c) 2015 Tom Barron.  All rights reserved.
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
"""
Unit tests for the NetApp 7mode NFS storage driver
"""

import ddt
import mock
from os_brick.remotefs import remotefs as remotefs_brick
from oslo_utils import units

from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
from cinder.tests.unit.volume.drivers.netapp import fakes as na_fakes
from cinder import utils
from cinder.volume.drivers.netapp.dataontap import nfs_7mode
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp.dataontap.utils import utils as dot_utils
from cinder.volume.drivers.netapp import utils as na_utils


@ddt.ddt
class NetApp7modeNfsDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetApp7modeNfsDriverTestCase, self).setUp()

        kwargs = {
            'configuration': self.get_config_7mode(),
            'host': 'openstack@7modenfs',
        }

        with mock.patch.object(utils, 'get_root_helper',
                               return_value=mock.Mock()):
            with mock.patch.object(remotefs_brick, 'RemoteFsClient',
                                   return_value=mock.Mock()):
                self.driver = nfs_7mode.NetApp7modeNfsDriver(**kwargs)
                self.driver._mounted_shares = [fake.NFS_SHARE]
                self.driver.ssc_vols = True
                self.driver.zapi_client = mock.Mock()
                self.driver.perf_library = mock.Mock()

    def get_config_7mode(self):
        config = na_fakes.create_configuration_cmode()
        config.netapp_storage_protocol = 'nfs'
        config.netapp_login = 'root'
        config.netapp_password = 'pass'
        config.netapp_server_hostname = '127.0.0.1'
        config.netapp_transport_type = 'http'
        config.netapp_server_port = '80'
        return config

    @ddt.data({'share': None, 'is_snapshot': False},
              {'share': None, 'is_snapshot': True},
              {'share': 'fake_share', 'is_snapshot': False},
              {'share': 'fake_share', 'is_snapshot': True})
    @ddt.unpack
    def test_clone_backing_file_for_volume(self, share, is_snapshot):

        mock_get_export_ip_path = self.mock_object(
            self.driver, '_get_export_ip_path',
            return_value=(fake.SHARE_IP, fake.EXPORT_PATH))
        mock_get_actual_path_for_export = self.mock_object(
            self.driver.zapi_client, 'get_actual_path_for_export',
            return_value='fake_path')

        self.driver._clone_backing_file_for_volume(
            fake.FLEXVOL, 'fake_clone', fake.VOLUME_ID, share=share,
            is_snapshot=is_snapshot)

        mock_get_export_ip_path.assert_called_once_with(
            fake.VOLUME_ID, share)
        mock_get_actual_path_for_export.assert_called_once_with(
            fake.EXPORT_PATH)
        self.driver.zapi_client.clone_file.assert_called_once_with(
            'fake_path/' + fake.FLEXVOL, 'fake_path/fake_clone',
            None)

    @ddt.data({'nfs_sparsed_volumes': True},
              {'nfs_sparsed_volumes': False})
    @ddt.unpack
    def test_get_pool_stats(self, nfs_sparsed_volumes):

        self.driver.configuration.nfs_sparsed_volumes = nfs_sparsed_volumes
        thick = not nfs_sparsed_volumes

        total_capacity_gb = na_utils.round_down(
            fake.TOTAL_BYTES // units.Gi, '0.01')
        free_capacity_gb = na_utils.round_down(
            fake.AVAILABLE_BYTES // units.Gi, '0.01')
        capacity = {
            'reserved_percentage': fake.RESERVED_PERCENTAGE,
            'max_over_subscription_ratio': fake.MAX_OVER_SUBSCRIPTION_RATIO,
            'total_capacity_gb': total_capacity_gb,
            'free_capacity_gb': free_capacity_gb,
        }
        self.mock_object(self.driver,
                         '_get_share_capacity_info',
                         return_value=capacity)
        self.mock_object(self.driver.perf_library,
                         'get_node_utilization',
                         return_value=30.0)

        result = self.driver._get_pool_stats(filter_function='filter',
                                             goodness_function='goodness')

        expected = [{'pool_name': '192.168.99.24:/fake/export/path',
                     'QoS_support': False,
                     'consistencygroup_support': True,
                     'thick_provisioning_support': thick,
                     'thin_provisioning_support': not thick,
                     'free_capacity_gb': 12.0,
                     'total_capacity_gb': 4468.0,
                     'reserved_percentage': 7,
                     'max_over_subscription_ratio': 19.0,
                     'multiattach': False,
                     'utilization': 30.0,
                     'filter_function': 'filter',
                     'goodness_function': 'goodness'}]

        self.assertEqual(expected, result)

    def test_shortlist_del_eligible_files(self):
        mock_get_path_for_export = self.mock_object(
            self.driver.zapi_client, 'get_actual_path_for_export')
        mock_get_path_for_export.return_value = fake.FLEXVOL

        mock_get_file_usage = self.mock_object(
            self.driver.zapi_client, 'get_file_usage')
        mock_get_file_usage.return_value = fake.CAPACITY_VALUES[0]

        expected = [(old_file, fake.CAPACITY_VALUES[0]) for old_file
                    in fake.FILE_LIST]

        result = self.driver._shortlist_del_eligible_files(
            fake.NFS_SHARE, fake.FILE_LIST)

        self.assertEqual(expected, result)

    def test_shortlist_del_eligible_files_empty_list(self):
        mock_get_export_ip_path = self.mock_object(
            self.driver, '_get_export_ip_path')
        mock_get_export_ip_path.return_value = ('', '/export_path')

        mock_get_path_for_export = self.mock_object(
            self.driver.zapi_client, 'get_actual_path_for_export')
        mock_get_path_for_export.return_value = fake.FLEXVOL

        result = self.driver._shortlist_del_eligible_files(
            fake.NFS_SHARE, [])

        self.assertEqual([], result)

    @ddt.data({'has_space': True, 'expected': True},
              {'has_space': False, 'expected': False})
    @ddt.unpack
    def test_is_share_clone_compatible(self, has_space, expected):
        mock_share_has_space_for_clone = self.mock_object(
            self.driver, '_share_has_space_for_clone')
        mock_share_has_space_for_clone.return_value = has_space

        result = self.driver._is_share_clone_compatible(fake.VOLUME,
                                                        fake.NFS_SHARE)

        self.assertEqual(expected, result)

    def test__get_volume_model_update(self):
        """Driver is not expected to return a model update."""
        self.assertIsNone(
            self.driver._get_volume_model_update(fake.VOLUME_REF))

    def test_delete_cgsnapshot(self):
        mock_delete_file = self.mock_object(self.driver, '_delete_file')

        model_update, snapshots_model_update = (
            self.driver.delete_cgsnapshot(
                fake.CG_CONTEXT, fake.CG_SNAPSHOT, [fake.SNAPSHOT]))

        mock_delete_file.assert_called_once_with(
            fake.SNAPSHOT['volume_id'], fake.SNAPSHOT['name'])
        self.assertIsNone(model_update)
        self.assertIsNone(snapshots_model_update)

    def test_get_snapshot_backing_flexvol_names(self):
        snapshots = [
            {'volume': {'host': 'hostA@192.168.99.25#/fake/volume1'}},
            {'volume': {'host': 'hostA@192.168.1.01#/fake/volume2'}},
            {'volume': {'host': 'hostA@192.168.99.25#/fake/volume3'}},
            {'volume': {'host': 'hostA@192.168.99.25#/fake/volume1'}},
        ]

        hosts = [snap['volume']['host'] for snap in snapshots]
        flexvols = self.driver._get_flexvol_names_from_hosts(hosts)

        self.assertEqual(3, len(flexvols))
        self.assertIn('volume1', flexvols)
        self.assertIn('volume2', flexvols)
        self.assertIn('volume3', flexvols)

    def test_check_for_setup_error(self):
        mock_get_ontapi_version = self.mock_object(
            self.driver.zapi_client, 'get_ontapi_version')
        mock_get_ontapi_version.return_value = ['1', '10']
        mock_add_looping_tasks = self.mock_object(
            self.driver, '_add_looping_tasks')
        mock_super_check_for_setup_error = self.mock_object(
            nfs_base.NetAppNfsDriver, 'check_for_setup_error')

        self.driver.check_for_setup_error()

        mock_get_ontapi_version.assert_called_once_with()
        mock_add_looping_tasks.assert_called_once_with()
        mock_super_check_for_setup_error.assert_called_once_with()

    def test_add_looping_tasks(self):
        mock_super_add_looping_tasks = self.mock_object(
            nfs_base.NetAppNfsDriver, '_add_looping_tasks')

        self.driver._add_looping_tasks()
        mock_super_add_looping_tasks.assert_called_once_with()

    def test_handle_ems_logging(self):

        volume_list = ['vol0', 'vol1', 'vol2']
        self.mock_object(
            self.driver, '_get_backing_flexvol_names',
            return_value=volume_list)
        self.mock_object(
            dot_utils, 'build_ems_log_message_0',
            return_value='fake_base_ems_log_message')
        self.mock_object(
            dot_utils, 'build_ems_log_message_1',
            return_value='fake_pool_ems_log_message')
        mock_send_ems_log_message = self.mock_object(
            self.driver.zapi_client, 'send_ems_log_message')

        self.driver._handle_ems_logging()

        mock_send_ems_log_message.assert_has_calls([
            mock.call('fake_base_ems_log_message'),
            mock.call('fake_pool_ems_log_message'),
        ])
        dot_utils.build_ems_log_message_0.assert_called_once_with(
            self.driver.driver_name, self.driver.app_version,
            self.driver.driver_mode)
        dot_utils.build_ems_log_message_1.assert_called_once_with(
            self.driver.driver_name, self.driver.app_version, None,
            volume_list, [])

    def test_get_backing_flexvol_names(self):

        result = self.driver._get_backing_flexvol_names()

        self.assertEqual('path', result[0])

    def test_create_consistency_group(self):
        model_update = self.driver.create_consistencygroup(
            fake.CG_CONTEXT, fake.CONSISTENCY_GROUP)
        self.assertEqual('available', model_update['status'])

    def test_update_consistencygroup(self):
        model_update, add_volumes_update, remove_volumes_update = (
            self.driver.update_consistencygroup(fake.CG_CONTEXT, "foo"))
        self.assertIsNone(add_volumes_update)
        self.assertIsNone(remove_volumes_update)

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_create_consistencygroup_from_src(self, volume_model_update):
        volume_model_update = volume_model_update or {}
        volume_model_update.update(
            {'provider_location': fake.PROVIDER_LOCATION})
        mock_create_volume_from_snapshot = self.mock_object(
            self.driver, 'create_volume_from_snapshot',
            return_value=volume_model_update)

        model_update, volumes_model_update = (
            self.driver.create_consistencygroup_from_src(
                fake.CG_CONTEXT, fake.CONSISTENCY_GROUP, [fake.VOLUME],
                cgsnapshot=fake.CG_SNAPSHOT, snapshots=[fake.SNAPSHOT]))

        expected_volumes_model_updates = [{'id': fake.VOLUME['id']}]
        expected_volumes_model_updates[0].update(volume_model_update)
        mock_create_volume_from_snapshot.assert_called_once_with(
            fake.VOLUME, fake.SNAPSHOT)
        self.assertIsNone(model_update)
        self.assertEqual(expected_volumes_model_updates, volumes_model_update)

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_create_consistencygroup_from_src_source_vols(
            self, volume_model_update):
        mock_get_snapshot_flexvols = self.mock_object(
            self.driver, '_get_flexvol_names_from_hosts')
        mock_get_snapshot_flexvols.return_value = (set([fake.CG_POOL_NAME]))
        mock_clone_backing_file = self.mock_object(
            self.driver, '_clone_backing_file_for_volume')
        fake_snapshot_name = 'snapshot-temp-' + fake.CONSISTENCY_GROUP['id']
        mock_busy = self.mock_object(
            self.driver.zapi_client, 'wait_for_busy_snapshot')
        self.mock_object(self.driver, '_get_volume_model_update',
                         return_value=volume_model_update)

        model_update, volumes_model_update = (
            self.driver.create_consistencygroup_from_src(
                fake.CG_CONTEXT, fake.CONSISTENCY_GROUP, [fake.VOLUME],
                source_cg=fake.CONSISTENCY_GROUP,
                source_vols=[fake.NFS_VOLUME]))

        expected_volumes_model_updates = [{
            'id': fake.NFS_VOLUME['id'],
            'provider_location': fake.PROVIDER_LOCATION,
        }]
        if volume_model_update:
            expected_volumes_model_updates[0].update(volume_model_update)
        mock_get_snapshot_flexvols.assert_called_once_with(
            [fake.NFS_VOLUME['host']])
        self.driver.zapi_client.create_cg_snapshot.assert_called_once_with(
            set([fake.CG_POOL_NAME]), fake_snapshot_name)
        mock_clone_backing_file.assert_called_once_with(
            fake.NFS_VOLUME['name'], fake.VOLUME['name'],
            fake.NFS_VOLUME['id'], source_snapshot=fake_snapshot_name)
        mock_busy.assert_called_once_with(
            fake.CG_POOL_NAME, fake_snapshot_name)
        self.driver.zapi_client.delete_snapshot.assert_called_once_with(
            fake.CG_POOL_NAME, fake_snapshot_name)
        self.assertIsNone(model_update)
        self.assertEqual(expected_volumes_model_updates, volumes_model_update)

    def test_create_consistencygroup_from_src_invalid_parms(self):

        model_update, volumes_model_update = (
            self.driver.create_consistencygroup_from_src(
                fake.CG_CONTEXT, fake.CONSISTENCY_GROUP, [fake.VOLUME]))

        self.assertIn('error', model_update['status'])

    def test_create_cgsnapshot(self):
        snapshot = fake.CG_SNAPSHOT
        snapshot['volume'] = fake.CG_VOLUME
        mock_get_snapshot_flexvols = self.mock_object(
            self.driver, '_get_flexvol_names_from_hosts')
        mock_get_snapshot_flexvols.return_value = (set([fake.CG_POOL_NAME]))
        mock_clone_backing_file = self.mock_object(
            self.driver, '_clone_backing_file_for_volume')
        mock_busy = self.mock_object(
            self.driver.zapi_client, 'wait_for_busy_snapshot')

        self.driver.create_cgsnapshot(
            fake.CG_CONTEXT, fake.CG_SNAPSHOT, [snapshot])

        mock_get_snapshot_flexvols.assert_called_once_with(
            [snapshot['volume']['host']])
        self.driver.zapi_client.create_cg_snapshot.assert_called_once_with(
            set([fake.CG_POOL_NAME]), fake.CG_SNAPSHOT_ID)
        mock_clone_backing_file.assert_called_once_with(
            snapshot['volume']['name'], snapshot['name'],
            snapshot['volume']['id'], source_snapshot=fake.CG_SNAPSHOT_ID)
        mock_busy.assert_called_once_with(
            fake.CG_POOL_NAME, fake.CG_SNAPSHOT_ID)
        self.driver.zapi_client.delete_snapshot.assert_called_once_with(
            fake.CG_POOL_NAME, fake.CG_SNAPSHOT_ID)

    def test_create_cgsnapshot_busy_snapshot(self):
        snapshot = fake.CG_SNAPSHOT
        snapshot['volume'] = fake.CG_VOLUME
        mock_get_snapshot_flexvols = self.mock_object(
            self.driver, '_get_flexvol_names_from_hosts')
        mock_get_snapshot_flexvols.return_value = (set([fake.CG_POOL_NAME]))
        mock_clone_backing_file = self.mock_object(
            self.driver, '_clone_backing_file_for_volume')
        mock_busy = self.mock_object(
            self.driver.zapi_client, 'wait_for_busy_snapshot')
        mock_busy.side_effect = exception.SnapshotIsBusy(snapshot['name'])
        mock_mark_snapshot_for_deletion = self.mock_object(
            self.driver.zapi_client, 'mark_snapshot_for_deletion')

        self.driver.create_cgsnapshot(
            fake.CG_CONTEXT, fake.CG_SNAPSHOT, [snapshot])

        mock_get_snapshot_flexvols.assert_called_once_with(
            [snapshot['volume']['host']])
        self.driver.zapi_client.create_cg_snapshot.assert_called_once_with(
            set([fake.CG_POOL_NAME]), fake.CG_SNAPSHOT_ID)
        mock_clone_backing_file.assert_called_once_with(
            snapshot['volume']['name'], snapshot['name'],
            snapshot['volume']['id'], source_snapshot=fake.CG_SNAPSHOT_ID)
        mock_busy.assert_called_once_with(
            fake.CG_POOL_NAME, fake.CG_SNAPSHOT_ID)
        self.driver.zapi_client.delete_snapshot.assert_not_called()
        mock_mark_snapshot_for_deletion.assert_called_once_with(
            fake.CG_POOL_NAME, fake.CG_SNAPSHOT_ID)

    def test_delete_consistencygroup_volume_delete_failure(self):
        self.mock_object(self.driver, '_delete_file', side_effect=Exception)

        model_update, volumes = self.driver.delete_consistencygroup(
            fake.CG_CONTEXT, fake.CONSISTENCY_GROUP, [fake.CG_VOLUME])

        self.assertEqual('deleted', model_update['status'])
        self.assertEqual('error_deleting', volumes[0]['status'])

    def test_delete_consistencygroup(self):
        mock_delete_file = self.mock_object(
            self.driver, '_delete_file')

        model_update, volumes = self.driver.delete_consistencygroup(
            fake.CG_CONTEXT, fake.CONSISTENCY_GROUP, [fake.CG_VOLUME])

        self.assertEqual('deleted', model_update['status'])
        self.assertEqual('deleted', volumes[0]['status'])
        mock_delete_file.assert_called_once_with(
            fake.CG_VOLUME_ID, fake.CG_VOLUME_NAME)
