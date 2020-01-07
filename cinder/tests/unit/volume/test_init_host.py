# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""Tests for volume init host method cases."""

from unittest import mock

from oslo_config import cfg
from oslo_utils import importutils

from cinder import context
from cinder import exception
from cinder import objects
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit import volume as base
from cinder.volume import driver
from cinder.volume import volume_migration as volume_migration
from cinder.volume import volume_utils


CONF = cfg.CONF


class VolumeInitHostTestCase(base.BaseVolumeTestCase):

    def setUp(self):
        super(VolumeInitHostTestCase, self).setUp()
        self.service_id = 1

    @mock.patch('cinder.manager.CleanableManager.init_host')
    def test_init_host_count_allocated_capacity(self, init_host_mock):
        vol0 = tests_utils.create_volume(
            self.context, size=100, host=CONF.host)
        vol1 = tests_utils.create_volume(
            self.context, size=128,
            host=volume_utils.append_host(CONF.host, 'pool0'))
        vol2 = tests_utils.create_volume(
            self.context, size=256,
            host=volume_utils.append_host(CONF.host, 'pool0'))
        vol3 = tests_utils.create_volume(
            self.context, size=512,
            host=volume_utils.append_host(CONF.host, 'pool1'))
        vol4 = tests_utils.create_volume(
            self.context, size=1024,
            host=volume_utils.append_host(CONF.host, 'pool2'))
        self.volume.init_host(service_id=self.service_id)
        init_host_mock.assert_called_once_with(
            service_id=self.service_id, added_to_cluster=None)
        stats = self.volume.stats
        self.assertEqual(2020, stats['allocated_capacity_gb'])
        self.assertEqual(
            384, stats['pools']['pool0']['allocated_capacity_gb'])
        self.assertEqual(
            512, stats['pools']['pool1']['allocated_capacity_gb'])
        self.assertEqual(
            1024, stats['pools']['pool2']['allocated_capacity_gb'])

        # NOTE(jdg): On the create we have host='xyz', BUT
        # here we do a db.volume_get, and now the host has
        # been updated to xyz#pool-name.  Note this is
        # done via the managers init, which calls the drivers
        # get_pool method, which in the legacy case is going
        # to be volume_backend_name or None

        vol0.refresh()
        expected_host = volume_utils.append_host(CONF.host, 'fake')
        self.assertEqual(expected_host, vol0.host)
        self.volume.delete_volume(self.context, vol0)
        self.volume.delete_volume(self.context, vol1)
        self.volume.delete_volume(self.context, vol2)
        self.volume.delete_volume(self.context, vol3)
        self.volume.delete_volume(self.context, vol4)

    def test_init_host_count_allocated_capacity_batch_retrieval(self):
        old_val = CONF.init_host_max_objects_retrieval
        CONF.init_host_max_objects_retrieval = 1
        try:
            self.test_init_host_count_allocated_capacity()
        finally:
            CONF.init_host_max_objects_retrieval = old_val

    @mock.patch('cinder.manager.CleanableManager.init_host')
    def test_init_host_count_allocated_capacity_cluster(self, init_host_mock):
        cluster_name = 'mycluster'
        self.volume.cluster = cluster_name
        # All these volumes belong to the same cluster, so we will calculate
        # the capacity of them all because we query the DB by cluster_name.
        tests_utils.create_volume(self.context, size=100, host=CONF.host,
                                  cluster_name=cluster_name)
        tests_utils.create_volume(
            self.context, size=128, cluster_name=cluster_name,
            host=volume_utils.append_host(CONF.host, 'pool0'))
        tests_utils.create_volume(
            self.context, size=256, cluster_name=cluster_name,
            host=volume_utils.append_host(CONF.host + '2', 'pool0'))
        tests_utils.create_volume(
            self.context, size=512, cluster_name=cluster_name,
            host=volume_utils.append_host(CONF.host + '2', 'pool1'))
        tests_utils.create_volume(
            self.context, size=1024, cluster_name=cluster_name,
            host=volume_utils.append_host(CONF.host + '3', 'pool2'))

        # These don't belong to the cluster so they will be ignored
        tests_utils.create_volume(
            self.context, size=1024,
            host=volume_utils.append_host(CONF.host, 'pool2'))
        tests_utils.create_volume(
            self.context, size=1024, cluster_name=cluster_name + '1',
            host=volume_utils.append_host(CONF.host + '3', 'pool2'))

        self.volume.init_host(service_id=self.service_id)
        init_host_mock.assert_called_once_with(
            service_id=self.service_id, added_to_cluster=None)
        stats = self.volume.stats
        self.assertEqual(2020, stats['allocated_capacity_gb'])
        self.assertEqual(
            384, stats['pools']['pool0']['allocated_capacity_gb'])
        self.assertEqual(
            512, stats['pools']['pool1']['allocated_capacity_gb'])
        self.assertEqual(
            1024, stats['pools']['pool2']['allocated_capacity_gb'])

    @mock.patch.object(driver.BaseVD, "update_provider_info")
    def test_init_host_sync_provider_info(self, mock_update):
        vol0 = tests_utils.create_volume(
            self.context, size=1, host=CONF.host)
        vol1 = tests_utils.create_volume(
            self.context, size=1, host=CONF.host)
        vol2 = tests_utils.create_volume(
            self.context, size=1, host=CONF.host, status='creating')
        snap0 = tests_utils.create_snapshot(self.context, vol0.id)
        snap1 = tests_utils.create_snapshot(self.context, vol1.id)
        # Return values for update_provider_info
        volumes = [{'id': vol0.id, 'provider_id': '1 2 xxxx'},
                   {'id': vol1.id, 'provider_id': '3 4 yyyy'}]
        snapshots = [{'id': snap0.id, 'provider_id': '5 6 xxxx'},
                     {'id': snap1.id, 'provider_id': '7 8 yyyy'}]
        mock_update.return_value = (volumes, snapshots)
        # initialize
        self.volume.init_host(service_id=self.service_id)
        # Grab volume and snapshot objects
        vol0_obj = objects.Volume.get_by_id(context.get_admin_context(),
                                            vol0.id)
        vol1_obj = objects.Volume.get_by_id(context.get_admin_context(),
                                            vol1.id)
        vol2_obj = objects.Volume.get_by_id(context.get_admin_context(),
                                            vol2.id)
        snap0_obj = objects.Snapshot.get_by_id(self.context, snap0.id)
        snap1_obj = objects.Snapshot.get_by_id(self.context, snap1.id)
        # Check updated provider ids
        self.assertEqual('1 2 xxxx', vol0_obj.provider_id)
        self.assertEqual('3 4 yyyy', vol1_obj.provider_id)
        self.assertIsNone(vol2_obj.provider_id)
        self.assertEqual('5 6 xxxx', snap0_obj.provider_id)
        self.assertEqual('7 8 yyyy', snap1_obj.provider_id)
        # Clean up
        self.volume.delete_snapshot(self.context, snap0_obj)
        self.volume.delete_snapshot(self.context, snap1_obj)
        self.volume.delete_volume(self.context, vol0)
        self.volume.delete_volume(self.context, vol1)

    def test_init_host_sync_provider_info_batch_retrieval(self):
        old_val = CONF.init_host_max_objects_retrieval
        CONF.init_host_max_objects_retrieval = 1
        try:
            self.test_init_host_sync_provider_info()
        finally:
            CONF.init_host_max_objects_retrieval = old_val

    @mock.patch.object(driver.BaseVD, "update_provider_info")
    def test_init_host_sync_provider_info_no_update(self, mock_update):
        vol0 = tests_utils.create_volume(
            self.context, size=1, host=CONF.host)
        vol1 = tests_utils.create_volume(
            self.context, size=1, host=CONF.host)
        snap0 = tests_utils.create_snapshot(self.context, vol0.id)
        snap1 = tests_utils.create_snapshot(self.context, vol1.id)
        mock_update.return_value = ([], [])
        # initialize
        self.volume.init_host(service_id=self.service_id)
        # Grab volume and snapshot objects
        vol0_obj = objects.Volume.get_by_id(context.get_admin_context(),
                                            vol0.id)
        vol1_obj = objects.Volume.get_by_id(context.get_admin_context(),
                                            vol1.id)
        snap0_obj = objects.Snapshot.get_by_id(self.context, snap0.id)
        snap1_obj = objects.Snapshot.get_by_id(self.context, snap1.id)
        # Check provider ids are not changed
        self.assertIsNone(vol0_obj.provider_id)
        self.assertIsNone(vol1_obj.provider_id)
        self.assertIsNone(snap0_obj.provider_id)
        self.assertIsNone(snap1_obj.provider_id)
        # Clean up
        self.volume.delete_snapshot(self.context, snap0_obj)
        self.volume.delete_snapshot(self.context, snap1_obj)
        self.volume.delete_volume(self.context, vol0)
        self.volume.delete_volume(self.context, vol1)

    @mock.patch.object(driver.BaseVD, "update_provider_info")
    def test_init_host_sync_provider_info_no_update_cluster(self, mock_update):
        cluster_name = 'mycluster'
        self.volume.cluster = cluster_name
        vol0 = tests_utils.create_volume(
            self.context, size=1, host=CONF.host, cluster_name=cluster_name)
        vol1 = tests_utils.create_volume(
            self.context, size=1, host=CONF.host + '2',
            cluster_name=cluster_name)
        vol2 = tests_utils.create_volume(
            self.context, size=1, host=CONF.host)
        vol3 = tests_utils.create_volume(
            self.context, size=1, host=CONF.host,
            cluster_name=cluster_name + '2')
        snap0 = tests_utils.create_snapshot(self.context, vol0.id)
        snap1 = tests_utils.create_snapshot(self.context, vol1.id)
        tests_utils.create_snapshot(self.context, vol2.id)
        tests_utils.create_snapshot(self.context, vol3.id)
        mock_update.return_value = ([], [])
        # initialize
        self.volume.init_host(service_id=self.service_id)
        # Grab volume and snapshot objects
        vol0_obj = objects.Volume.get_by_id(context.get_admin_context(),
                                            vol0.id)
        vol1_obj = objects.Volume.get_by_id(context.get_admin_context(),
                                            vol1.id)
        snap0_obj = objects.Snapshot.get_by_id(self.context, snap0.id)
        snap1_obj = objects.Snapshot.get_by_id(self.context, snap1.id)

        self.assertSetEqual({vol0.id, vol1.id},
                            {vol.id for vol in mock_update.call_args[0][0]})
        self.assertSetEqual({snap0.id, snap1.id},
                            {snap.id for snap in mock_update.call_args[0][1]})
        # Check provider ids are not changed
        self.assertIsNone(vol0_obj.provider_id)
        self.assertIsNone(vol1_obj.provider_id)
        self.assertIsNone(snap0_obj.provider_id)
        self.assertIsNone(snap1_obj.provider_id)
        # Clean up
        self.volume.delete_snapshot(self.context, snap0_obj)
        self.volume.delete_snapshot(self.context, snap1_obj)
        self.volume.delete_volume(self.context, vol0)
        self.volume.delete_volume(self.context, vol1)

    @mock.patch('cinder.volume.manager.VolumeManager.'
                '_include_resources_in_cluster')
    def test_init_host_cluster_not_changed(self, include_in_cluster_mock):
        self.volume.init_host(added_to_cluster=False,
                              service_id=self.service_id)
        include_in_cluster_mock.assert_not_called()

    @mock.patch('cinder.objects.group.GroupList.include_in_cluster')
    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all',
                return_value=[])
    @mock.patch('cinder.objects.volume.VolumeList.get_all', return_value=[])
    @mock.patch('cinder.objects.volume.VolumeList.include_in_cluster')
    @mock.patch('cinder.objects.consistencygroup.ConsistencyGroupList.'
                'include_in_cluster')
    @mock.patch('cinder.db.image_volume_cache_include_in_cluster')
    def test_init_host_added_to_cluster(self, image_cache_include_mock,
                                        cg_include_mock,
                                        vol_include_mock, vol_get_all_mock,
                                        snap_get_all_mock, group_include_mock):
        cluster = str(mock.sentinel.cluster)
        self.mock_object(self.volume, 'cluster', cluster)
        self.volume.init_host(added_to_cluster=True,
                              service_id=self.service_id)

        vol_include_mock.assert_called_once_with(mock.ANY, cluster,
                                                 host=self.volume.host)
        cg_include_mock.assert_called_once_with(mock.ANY, cluster,
                                                host=self.volume.host)
        image_cache_include_mock.assert_called_once_with(mock.ANY, cluster,
                                                         host=self.volume.host)
        group_include_mock.assert_called_once_with(mock.ANY, cluster,
                                                   host=self.volume.host)
        vol_get_all_mock.assert_called_once_with(
            mock.ANY, filters={'cluster_name': cluster},
            limit=None, offset=None)
        snap_get_all_mock.assert_called_once_with(
            mock.ANY, filters={'cluster_name': cluster},
            limit=None, offset=None)

    @mock.patch('cinder.keymgr.migration.migrate_fixed_key')
    @mock.patch('cinder.volume.manager.VolumeManager._get_my_volumes')
    @mock.patch('cinder.manager.ThreadPoolManager._add_to_threadpool')
    def test_init_host_key_migration(self,
                                     mock_add_threadpool,
                                     mock_get_my_volumes,
                                     mock_migrate_fixed_key):

        self.volume.init_host(service_id=self.service_id)

        volumes = mock_get_my_volumes()
        volumes_to_migrate = volume_migration.VolumeMigrationList()
        volumes_to_migrate.append(volumes, self.context)
        mock_add_threadpool.assert_called_once_with(
            mock_migrate_fixed_key,
            volumes=volumes_to_migrate)

    @mock.patch('time.sleep')
    def test_init_host_retry(self, mock_sleep):
        kwargs = {'service_id': 2}
        self.volume = importutils.import_object(CONF.volume_manager)
        self.volume.driver.do_setup = mock.MagicMock()
        self.volume.driver.do_setup.side_effect = [
            exception.CinderException("Test driver error."),
            exception.InvalidConfigurationValue('Test config error.'),
            ImportError]

        self.volume.init_host(added_to_cluster=False, **kwargs)

        self.assertEqual(4, self.volume.driver.do_setup.call_count)
        self.assertFalse(self.volume.is_working())

    @mock.patch('time.sleep')
    def test_init_host_retry_once(self, mock_sleep):
        kwargs = {'service_id': 2}
        self.volume = importutils.import_object(CONF.volume_manager)
        self.volume.driver.do_setup = mock.MagicMock()
        self.volume.driver.do_setup.side_effect = [ImportError, None]

        self.volume.init_host(added_to_cluster=False, **kwargs)

        self.assertEqual(2, self.volume.driver.do_setup.call_count)
        self.assertTrue(self.volume.is_working())
