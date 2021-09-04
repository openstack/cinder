# Copyright (c) 2014 Andrew Kerr.  All rights reserved.
# Copyright (c) 2015 Tom Barron.  All rights reserved.
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
"""Unit tests for the NetApp NFS storage driver."""
import copy
import os
import threading
import time
from unittest import mock

import ddt
from os_brick.remotefs import remotefs as remotefs_brick
from oslo_concurrency import processutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.netapp.dataontap import fakes as fake
from cinder import utils
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap import nfs_base
from cinder.volume.drivers.netapp.dataontap.utils import loopingcalls
from cinder.volume.drivers.netapp import utils as na_utils
from cinder.volume.drivers import nfs
from cinder.volume.drivers import remotefs
from cinder.volume import volume_utils


@ddt.ddt
class NetAppNfsDriverTestCase(test.TestCase):
    def setUp(self):
        super(NetAppNfsDriverTestCase, self).setUp()
        configuration = mock.Mock()
        configuration.reserved_percentage = 0
        configuration.nfs_mount_point_base = '/mnt/test'
        configuration.reserved_percentage = 0
        configuration.max_over_subscription_ratio = 1.1
        self.fake_nfs_export_1 = fake.NFS_EXPORT_1
        self.fake_nfs_export_2 = fake.NFS_EXPORT_2
        self.fake_mount_point = fake.MOUNT_POINT
        self.ctxt = context.RequestContext('fake', 'fake', auth_token=True)

        kwargs = {
            'configuration': configuration,
            'host': 'openstack@netappnfs',
        }

        with mock.patch.object(utils, 'get_root_helper',
                               return_value=mock.Mock()):
            with mock.patch.object(remotefs_brick, 'RemoteFsClient',
                                   return_value=mock.Mock()):
                self.driver = nfs_base.NetAppNfsDriver(**kwargs)
                self.driver.db = mock.Mock()

        self.driver.zapi_client = mock.Mock()
        self.zapi_client = self.driver.zapi_client

    @mock.patch.object(nfs.NfsDriver, 'do_setup')
    @mock.patch.object(na_utils, 'check_flags')
    def test_do_setup(self, mock_check_flags, mock_super_do_setup):
        self.driver.do_setup(mock.Mock())

        self.assertTrue(mock_check_flags.called)
        self.assertTrue(mock_super_do_setup.called)

    def test_get_share_capacity_info(self):
        mock_get_capacity = self.mock_object(self.driver, '_get_capacity_info')
        mock_get_capacity.return_value = fake.CAPACITY_VALUES
        expected_total_capacity_gb = na_utils.round_down(
            fake.TOTAL_BYTES / units.Gi, '0.01')
        expected_free_capacity_gb = (na_utils.round_down(
            fake.AVAILABLE_BYTES / units.Gi, '0.01'))
        expected_reserved_percentage = round(
            self.driver.configuration.reserved_percentage)

        result = self.driver._get_share_capacity_info(fake.NFS_SHARE)

        self.assertEqual(expected_total_capacity_gb,
                         result['total_capacity_gb'])
        self.assertEqual(expected_free_capacity_gb,
                         result['free_capacity_gb'])
        self.assertEqual(expected_reserved_percentage,
                         round(result['reserved_percentage']))

    def test_get_capacity_info_ipv4_share(self):
        expected = fake.CAPACITY_VALUES
        get_capacity = self.driver.zapi_client.get_flexvol_capacity
        get_capacity.return_value = fake.CAPACITIES

        result = self.driver._get_capacity_info(fake.NFS_SHARE_IPV4)

        self.assertEqual(expected, result)
        get_capacity.assert_has_calls([
            mock.call(flexvol_path=fake.EXPORT_PATH)])

    def test_get_capacity_info_ipv6_share(self):
        expected = fake.CAPACITY_VALUES
        get_capacity = self.driver.zapi_client.get_flexvol_capacity
        get_capacity.return_value = fake.CAPACITIES

        result = self.driver._get_capacity_info(fake.NFS_SHARE_IPV6)

        self.assertEqual(expected, result)
        get_capacity.assert_has_calls([
            mock.call(flexvol_path=fake.EXPORT_PATH)])

    def test_get_pool(self):
        pool = self.driver.get_pool({'provider_location': 'fake-share'})

        self.assertEqual('fake-share', pool)

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_create_volume(self, model_update):
        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(self.driver, '_ensure_flexgroup_not_in_cg')
        self.mock_object(na_utils, 'get_volume_extra_specs')
        self.mock_object(self.driver, '_do_create_volume')
        self.mock_object(self.driver, '_do_qos_for_volume')
        self.mock_object(self.driver, '_get_volume_model_update',
                         return_value=model_update)
        expected = {'provider_location': fake.NFS_SHARE}
        if model_update:
            expected.update(model_update)

        actual = self.driver.create_volume(fake.NFS_VOLUME)

        self.assertEqual(expected, actual)

    def test_create_volume_no_pool(self):
        volume = copy.deepcopy(fake.NFS_VOLUME)
        volume['host'] = '%s@%s' % (fake.HOST_NAME, fake.BACKEND_NAME)
        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(self.driver, '_ensure_flexgroup_not_in_cg')

        self.assertRaises(exception.InvalidHost,
                          self.driver.create_volume,
                          volume)

    def test_create_volume_exception(self):
        self.mock_object(self.driver, '_ensure_shares_mounted')
        self.mock_object(self.driver, '_ensure_flexgroup_not_in_cg')
        self.mock_object(na_utils, 'get_volume_extra_specs')
        mock_create = self.mock_object(self.driver, '_do_create_volume')
        mock_create.side_effect = Exception

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          fake.NFS_VOLUME)

    @ddt.data(None, {'key': 'value'})
    def test_clone_source_to_destination_volume(self, model_update):
        self.mock_object(self.driver, '_get_volume_location',
                         return_value=fake.POOL_NAME)
        self.mock_object(na_utils, 'get_volume_extra_specs',
                         return_value=fake.EXTRA_SPECS)
        self.mock_object(
            self.driver,
            '_clone_with_extension_check')
        self.mock_object(self.driver, '_do_qos_for_volume')
        self.mock_object(self.driver, '_get_volume_model_update',
                         return_value=model_update)
        expected = {'provider_location': fake.POOL_NAME}
        if model_update:
            expected.update(model_update)

        result = self.driver._clone_source_to_destination_volume(
            fake.CLONE_SOURCE, fake.CLONE_DESTINATION)

        self.assertEqual(expected, result)

    def test_clone_source_to_destination_volume_with_do_qos_exception(self):
        self.mock_object(self.driver, '_get_volume_location',
                         return_value=fake.POOL_NAME)
        self.mock_object(na_utils, 'get_volume_extra_specs',
                         return_value=fake.EXTRA_SPECS)
        self.mock_object(
            self.driver,
            '_clone_with_extension_check')
        self.mock_object(self.driver, '_do_qos_for_volume',
                         side_effect=Exception)

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver._clone_source_to_destination_volume,
            fake.CLONE_SOURCE,
            fake.CLONE_DESTINATION)

    def test_clone_with_extension_check_equal_sizes(self):
        clone_source = copy.deepcopy(fake.CLONE_SOURCE)
        clone_source['size'] = fake.VOLUME['size']
        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(self.driver, 'local_path')
        mock_discover = self.mock_object(self.driver,
                                         '_discover_file_till_timeout')
        mock_discover.return_value = True
        self.mock_object(self.driver, '_set_rw_permissions')
        mock_extend_volume = self.mock_object(self.driver, 'extend_volume')

        self.driver._clone_with_extension_check(clone_source, fake.NFS_VOLUME)

        self.assertEqual(0, mock_extend_volume.call_count)

    def test_clone_with_extension_check_unequal_sizes(self):
        clone_source = copy.deepcopy(fake.CLONE_SOURCE)
        clone_source['size'] = fake.VOLUME['size'] + 1
        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(self.driver, 'local_path')
        mock_discover = self.mock_object(self.driver,
                                         '_discover_file_till_timeout')
        mock_discover.return_value = True
        self.mock_object(self.driver, '_set_rw_permissions')
        mock_extend_volume = self.mock_object(self.driver, 'extend_volume')

        self.driver._clone_with_extension_check(clone_source, fake.NFS_VOLUME)

        self.assertEqual(1, mock_extend_volume.call_count)

    def test_clone_with_extension_check_extend_exception(self):
        clone_source = copy.deepcopy(fake.CLONE_SOURCE)
        clone_source['size'] = fake.VOLUME['size'] + 1
        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(self.driver, 'local_path')
        mock_discover = self.mock_object(self.driver,
                                         '_discover_file_till_timeout')
        mock_discover.return_value = True
        self.mock_object(self.driver, '_set_rw_permissions')
        mock_extend_volume = self.mock_object(self.driver, 'extend_volume')
        mock_extend_volume.side_effect = Exception
        mock_cleanup = self.mock_object(self.driver,
                                        '_cleanup_volume_on_failure')

        self.assertRaises(exception.CinderException,
                          self.driver._clone_with_extension_check,
                          clone_source,
                          fake.NFS_VOLUME)

        self.assertEqual(1, mock_cleanup.call_count)

    def test_clone_with_extension_check_no_discovery(self):
        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(self.driver, 'local_path')
        self.mock_object(self.driver, '_set_rw_permissions')
        mock_discover = self.mock_object(self.driver,
                                         '_discover_file_till_timeout')
        mock_discover.return_value = False

        self.assertRaises(exception.CinderException,
                          self.driver._clone_with_extension_check,
                          fake.CLONE_SOURCE,
                          fake.NFS_VOLUME)

    @ddt.data(True, False)
    def test_create_volume_from_snapshot(self, is_flexgroup):
        provider_location = fake.POOL_NAME
        volume = fake.VOLUME
        expected_source = {
            'name': fake.SNAPSHOT_NAME,
            'size': fake.SIZE,
            'id': fake.VOLUME_ID,
        }
        mock_clone_call = self.mock_object(
            self.driver, '_clone_source_to_destination_volume',
            return_value=provider_location)
        self.mock_object(self.driver, '_ensure_flexgroup_not_in_cg')
        self.mock_object(self.driver, '_is_flexgroup',
                         return_value=is_flexgroup)
        self.mock_object(self.driver, '_is_flexgroup_clone_file_supported',
                         return_value=not is_flexgroup)
        mock_super_create = self.mock_object(
            nfs.NfsDriver, 'create_volume_from_snapshot',
            return_value=provider_location)
        mock_do_qos = self.mock_object(
            self.driver, '_do_qos_for_file_flexgroup',
            return_value=provider_location)

        retval = self.driver.create_volume_from_snapshot(volume, fake.SNAPSHOT)

        self.assertEqual(provider_location, retval)
        if is_flexgroup:
            mock_clone_call.assert_not_called()
            mock_super_create.assert_called_once_with(volume, fake.SNAPSHOT)
            mock_do_qos.assert_called_once_with(volume, provider_location)
        else:
            mock_clone_call.assert_called_once_with(expected_source, volume)
            mock_do_qos.assert_not_called()
            mock_super_create.not_called()

    @ddt.data(True, False)
    def test_create_cloned_volume(self, is_flexgroup):
        provider_location = fake.POOL_NAME
        volume = fake.VOLUME
        src_vref = fake.CLONE_SOURCE
        mock_clone_call = self.mock_object(
            self.driver, '_clone_source_to_destination_volume',
            return_value=provider_location)
        self.mock_object(self.driver, '_ensure_flexgroup_not_in_cg')
        self.mock_object(self.driver, '_is_flexgroup',
                         return_value=is_flexgroup)
        self.mock_object(self.driver, '_is_flexgroup_clone_file_supported',
                         return_value=not is_flexgroup)
        mock_super_create = self.mock_object(
            nfs.NfsDriver, 'create_cloned_volume',
            return_value=provider_location)
        mock_do_qos = self.mock_object(
            self.driver, '_do_qos_for_file_flexgroup',
            return_value=provider_location)

        result = self.driver.create_cloned_volume(volume, src_vref)

        self.assertEqual(provider_location, result)
        if is_flexgroup:
            mock_clone_call.assert_not_called()
            mock_super_create.assert_called_once_with(volume, src_vref)
            mock_do_qos.assert_called_once_with(volume, provider_location)
        else:
            mock_clone_call.assert_called_once_with(src_vref, volume)
            mock_do_qos.assert_not_called()
            mock_super_create.not_called()

    def test_do_qos_for_file_flexgroup(self):
        volume = {'provider_location': 'fake'}
        extra_specs = 'fake_extra'
        model = {'provider_location': 'fake'}
        vol_model = {'replication': 'fake'}
        expected_model = {
            'replication': vol_model['replication'],
            'provider_location': model['provider_location'],
        }
        self.mock_object(self.driver, '_do_qos_for_volume')
        self.mock_object(self.driver, '_get_volume_model_update',
                         return_value=vol_model)
        mock_extra = self.mock_object(na_utils, 'get_volume_extra_specs',
                                      return_value=extra_specs)

        model_updated = self.driver._do_qos_for_file_flexgroup(volume, model)

        self.assertEqual(model_updated, expected_model)
        mock_extra.assert_called_once_with(volume)

    def test_do_qos_for_file_flexgroup_error(self):
        self.mock_object(na_utils, 'get_volume_extra_specs',
                         side_effect=exception.NotFound)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._do_qos_for_file_flexgroup,
                          fake.VOLUME, 'fake_model')

    def test_do_qos_for_volume(self):
        self.assertRaises(NotImplementedError,
                          self.driver._do_qos_for_volume,
                          fake.NFS_VOLUME,
                          fake.EXTRA_SPECS)

    @ddt.data(True, False)
    def test_create_snapshot(self, is_flexgroup):
        self.mock_object(self.driver, '_is_flexgroup',
                         return_value=is_flexgroup)
        self.mock_object(self.driver, '_is_flexgroup_clone_file_supported',
                         return_value=not is_flexgroup)
        mock_clone_backing_file_for_volume = self.mock_object(
            self.driver, '_clone_backing_file_for_volume')
        mock_snap_flexgroup = self.mock_object(
            self.driver, '_create_snapshot_for_flexgroup')

        self.driver.create_snapshot(fake.SNAPSHOT)

        if is_flexgroup:
            mock_snap_flexgroup.assert_called_once_with(fake.SNAPSHOT)
            mock_clone_backing_file_for_volume.assert_not_called()
        else:
            mock_snap_flexgroup.assert_not_called()
            mock_clone_backing_file_for_volume.assert_called_once_with(
                fake.SNAPSHOT['volume_name'], fake.SNAPSHOT['name'],
                fake.SNAPSHOT['volume_id'], is_snapshot=True)

    def test_create_snapshot_for_flexgroup(self):
        source_vol = {
            'id': fake.SNAPSHOT['volume_id'],
            'name': fake.SNAPSHOT['volume_name'],
            'volume_type_id': fake.SNAPSHOT['volume_type_id'],
        }
        snap_vol = {
            'name': '%s.%s' % (fake.SNAPSHOT['volume_name'],
                               fake.SNAPSHOT['id']),
            'host': fake.HOST_NAME,
        }
        mock_super_snapshot = self.mock_object(nfs.NfsDriver,
                                               'create_snapshot')
        mock_extra_specs = self.mock_object(na_utils,
                                            'get_volume_extra_specs')
        mock_extra_specs.return_value = fake.EXTRA_SPECS
        mock_get_info = self.mock_object(na_utils,
                                         'get_valid_qos_policy_group_info')
        mock_get_info.return_value = fake.QOS_POLICY_GROUP_INFO
        mock_get_host = self.mock_object(self.driver,
                                         '_get_volume_host')
        mock_get_host.return_value = fake.HOST_NAME
        mock_set_policy = self.mock_object(self.driver,
                                           '_set_qos_policy_group_on_volume')

        self.driver._create_snapshot_for_flexgroup(fake.SNAPSHOT)

        mock_super_snapshot.assert_has_calls([
            mock.call(fake.SNAPSHOT)])
        mock_get_host.assert_has_calls([
            mock.call(source_vol['id'])])
        mock_extra_specs.assert_has_calls([
            mock.call(source_vol)])
        mock_get_info.assert_has_calls([
            mock.call(source_vol, fake.EXTRA_SPECS)])
        mock_set_policy.assert_has_calls([
            mock.call(snap_vol, fake.QOS_POLICY_GROUP_INFO, False)])

    def test_create_snapshot_for_flexgroup_error(self):
        self.mock_object(nfs.NfsDriver, 'create_snapshot',
                         side_effect=exception.NotFound)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver._create_snapshot_for_flexgroup,
                          fake.SNAPSHOT)

    def test_set_qos_policy_group_on_volume(self):
        self.assertRaises(NotImplementedError,
                          self.driver._set_qos_policy_group_on_volume,
                          fake.NFS_VOLUME,
                          fake.QOS_POLICY_GROUP_INFO,
                          False)

    @ddt.data(True, False)
    def test_delete_snapshot(self, is_flexgroup):
        updates = {
            'name': fake.SNAPSHOT_NAME,
            'volume_size': fake.SIZE,
            'volume_id': fake.VOLUME_ID,
            'volume_name': fake.VOLUME_NAME,
            'busy': False,
        }
        snapshot = fake_snapshot.fake_snapshot_obj(self.ctxt, **updates)
        self.mock_object(self.driver, '_delete_file')
        self.mock_object(self.driver, '_is_flexgroup',
                         return_value=is_flexgroup)
        self.mock_object(self.driver, '_is_flexgroup_clone_file_supported',
                         return_value=not is_flexgroup)
        mock_super_delete = self.mock_object(nfs.NfsDriver,
                                             'delete_snapshot')

        self.driver.delete_snapshot(snapshot)

        if is_flexgroup:
            mock_super_delete.assert_called_once_with(snapshot)
            self.driver._delete_file.assert_not_called()
        else:
            mock_super_delete.assert_not_called()
            self.driver._delete_file.assert_called_once_with(
                snapshot.volume_id, snapshot.name)

    @ddt.data(fake.NFS_SHARE, fake.NFS_SHARE_IPV6)
    def test__get_volume_location(self, provider):
        volume_id = fake.VOLUME_ID

        self.mock_object(self.driver, '_get_provider_location',
                         return_value=provider)

        retval = self.driver._get_volume_location(volume_id)

        self.assertEqual(provider, retval)

    def test__clone_backing_file_for_volume(self):
        self.assertRaises(NotImplementedError,
                          self.driver._clone_backing_file_for_volume,
                          fake.VOLUME_NAME, fake.CLONE_SOURCE_NAME,
                          fake.VOLUME_ID, share=None)

    def test__is_flexgroup(self):
        self.assertRaises(NotImplementedError,
                          self.driver._is_flexgroup)

    def test__get_provider_location(self):
        updates = {'provider_location': fake.PROVIDER_LOCATION}
        volume = fake_volume.fake_volume_obj(self.ctxt, **updates)
        self.mock_object(self.driver.db, 'volume_get', return_value=volume)

        retval = self.driver._get_provider_location(fake.VOLUME_ID)

        self.assertEqual(fake.PROVIDER_LOCATION, retval)

    def test__get_volume_host(self):
        updates = {'host': fake.HOST_NAME}
        volume = fake_volume.fake_volume_obj(self.ctxt, **updates)
        self.mock_object(self.driver.db, 'volume_get', return_value=volume)

        retval = self.driver._get_volume_host(fake.VOLUME_ID)

        self.assertEqual(fake.HOST_NAME, retval)

    @ddt.data(None, processutils.ProcessExecutionError)
    def test__volume_not_present(self, side_effect):
        self.mock_object(self.driver, '_get_volume_path')
        self.mock_object(self.driver, '_try_execute', side_effect=side_effect)

        retval = self.driver._volume_not_present(
            fake.MOUNT_PATH, fake.VOLUME_NAME)

        self.assertEqual(side_effect is not None, retval)

    @mock.patch.object(time, 'sleep')
    def test__try_execute_exception(self, patched_sleep):
        self.mock_object(self.driver, '_execute',
                         side_effect=processutils.ProcessExecutionError)
        mock_exception_log = self.mock_object(nfs_base.LOG, 'exception')
        self.driver.configuration.num_shell_tries = 3

        self.assertRaises(processutils.ProcessExecutionError,
                          self.driver._try_execute,
                          'fake-command', attr1='val1', attr2='val2')
        self.assertEqual(2, mock_exception_log.call_count)
        self.driver._execute.assert_has_calls([
            mock.call('fake-command', attr1='val1', attr2='val2'),
            mock.call('fake-command', attr1='val1', attr2='val2'),
            mock.call('fake-command', attr1='val1', attr2='val2')])
        self.assertEqual(2, time.sleep.call_count)
        patched_sleep.assert_has_calls([mock.call(1), mock.call(4)])

    def test__update_volume_stats(self):
        self.assertRaises(NotImplementedError,
                          self.driver._update_volume_stats)

    def test_copy_image_to_volume_base_exception(self):
        mock_info_log = self.mock_object(nfs_base.LOG, 'info')
        self.mock_object(self.driver, '_ensure_flexgroup_not_in_cg')
        self.mock_object(remotefs.RemoteFSDriver, 'copy_image_to_volume',
                         side_effect=exception.NfsException)

        self.assertRaises(exception.NfsException,
                          self.driver.copy_image_to_volume,
                          'fake_context', fake.NFS_VOLUME,
                          'fake_img_service', fake.IMAGE_FILE_ID)
        mock_info_log.assert_not_called()

    def test_copy_image_to_volume(self):
        mock_log = self.mock_object(nfs_base, 'LOG')
        self.mock_object(self.driver, '_is_flexgroup',
                         return_value=False)
        self.mock_object(self.driver, '_is_flexgroup_clone_file_supported',
                         return_value=True)
        self.mock_object(self.driver, '_ensure_flexgroup_not_in_cg')
        mock_copy_image = self.mock_object(
            remotefs.RemoteFSDriver, 'copy_image_to_volume')
        mock_register_image = self.mock_object(
            self.driver, '_register_image_in_cache')

        self.driver.copy_image_to_volume('fake_context',
                                         fake.NFS_VOLUME,
                                         'fake_img_service',
                                         fake.IMAGE_FILE_ID)

        mock_copy_image.assert_called_once_with(
            'fake_context', fake.NFS_VOLUME, 'fake_img_service',
            fake.IMAGE_FILE_ID)
        self.assertEqual(1, mock_log.info.call_count)
        mock_register_image.assert_called_once_with(
            fake.NFS_VOLUME, fake.IMAGE_FILE_ID)

    @ddt.data(None, Exception)
    def test__register_image_in_cache(self, exc):
        mock_log = self.mock_object(nfs_base, 'LOG')
        self.mock_object(self.driver, '_do_clone_rel_img_cache',
                         side_effect=exc)

        retval = self.driver._register_image_in_cache(
            fake.NFS_VOLUME, fake.IMAGE_FILE_ID)

        self.assertIsNone(retval)
        self.assertEqual(exc is not None, mock_log.warning.called)
        self.assertEqual(1, mock_log.info.call_count)

    @ddt.data(True, False)
    def test_do_clone_rel_img_cache(self, path_exists):
        self.mock_object(nfs_base.LOG, 'info')
        self.mock_object(utils, 'synchronized', return_value=lambda f: f)
        self.mock_object(self.driver, '_get_mount_point_for_share',
                         return_value='dir')
        self.mock_object(os.path, 'exists', return_value=path_exists)
        self.mock_object(self.driver, '_clone_backing_file_for_volume')
        self.mock_object(os, 'utime')

        retval = self.driver._do_clone_rel_img_cache(
            fake.CLONE_SOURCE_NAME, fake.CLONE_DESTINATION_NAME,
            fake.NFS_SHARE, 'fake_cache_file')

        self.assertIsNone(retval)
        self.assertTrue(self.driver._get_mount_point_for_share.called)
        if not path_exists:
            self.driver._clone_backing_file_for_volume.assert_called_once_with(
                fake.CLONE_SOURCE_NAME, fake.CLONE_DESTINATION_NAME,
                share=fake.NFS_SHARE, volume_id=None)
            os.utime.assert_called_once_with(
                'dir/' + fake.CLONE_SOURCE_NAME, None)
        else:
            self.driver._clone_backing_file_for_volume.assert_not_called()
            os.utime.assert_not_called()

        os.path.exists.assert_called_once_with(
            'dir/' + fake.CLONE_DESTINATION_NAME)

    def test__spawn_clean_cache_job_clean_job_setup(self):
        self.driver.cleaning = True
        mock_debug_log = self.mock_object(nfs_base.LOG, 'debug')
        self.mock_object(utils, 'synchronized', return_value=lambda f: f)

        retval = self.driver._spawn_clean_cache_job()

        self.assertIsNone(retval)
        self.assertEqual(1, mock_debug_log.call_count)

    def test__spawn_clean_cache_job_new_clean_job(self):

        class FakeTimer(object):
            def start(self):
                pass

        fake_timer = FakeTimer()
        self.mock_object(utils, 'synchronized', return_value=lambda f: f)
        self.mock_object(fake_timer, 'start')
        self.mock_object(nfs_base.LOG, 'debug')
        self.mock_object(self.driver, '_clean_image_cache')
        self.mock_object(threading, 'Timer', return_value=fake_timer)

        retval = self.driver._spawn_clean_cache_job()

        self.assertIsNone(retval)
        threading.Timer.assert_called_once_with(
            0, self.driver._clean_image_cache)
        fake_timer.start.assert_called_once_with()

    def test_cleanup_volume_on_failure(self):
        path = '%s/%s' % (fake.NFS_SHARE, fake.NFS_VOLUME['name'])
        mock_local_path = self.mock_object(self.driver, 'local_path')
        mock_local_path.return_value = path
        mock_exists_check = self.mock_object(os.path, 'exists')
        mock_exists_check.return_value = True
        mock_delete = self.mock_object(self.driver, '_delete_file_at_path')

        self.driver._cleanup_volume_on_failure(fake.NFS_VOLUME)

        mock_delete.assert_has_calls([mock.call(path)])

    def test_cleanup_volume_on_failure_no_path(self):
        self.mock_object(self.driver, 'local_path')
        mock_exists_check = self.mock_object(os.path, 'exists')
        mock_exists_check.return_value = False
        mock_delete = self.mock_object(self.driver, '_delete_file_at_path')

        self.driver._cleanup_volume_on_failure(fake.NFS_VOLUME)

        self.assertEqual(0, mock_delete.call_count)

    @ddt.data((fake.NFS_SHARE, fake.SHARE_IP),
              (fake.NFS_SHARE_IPV6, fake.IPV6_ADDRESS))
    @ddt.unpack
    def test_get_export_ip_path_volume_id_provided(self, provider_location,
                                                   ip):
        mock_get_host_ip = self.mock_object(self.driver,
                                            '_get_provider_location')
        mock_get_host_ip.return_value = provider_location

        expected = (ip, fake.EXPORT_PATH)

        result = self.driver._get_export_ip_path(fake.VOLUME_ID)

        self.assertEqual(expected, result)

    @ddt.data((fake.NFS_SHARE, fake.SHARE_IP, fake.EXPORT_PATH),
              (fake.NFS_SHARE_IPV6, fake.IPV6_ADDRESS, fake.EXPORT_PATH))
    @ddt.unpack
    def test_get_export_ip_path_share_provided(self, share, ip, path):
        expected = (ip, path)

        result = self.driver._get_export_ip_path(share=share)

        self.assertEqual(expected, result)

    def test_get_export_ip_path_volume_id_and_share_provided(self):
        mock_get_host_ip = self.mock_object(self.driver,
                                            '_get_provider_location')
        mock_get_host_ip.return_value = fake.NFS_SHARE_IPV4

        expected = (fake.IPV4_ADDRESS, fake.EXPORT_PATH)

        result = self.driver._get_export_ip_path(
            fake.VOLUME_ID, fake.NFS_SHARE)

        self.assertEqual(expected, result)

    def test_get_export_ip_path_no_args(self):
        self.assertRaises(exception.InvalidInput,
                          self.driver._get_export_ip_path)

    def test_construct_image_url_loc(self):
        img_loc = fake.FAKE_IMAGE_LOCATION

        locations = self.driver._construct_image_nfs_url(img_loc)

        self.assertIn("nfs://host/path/image-id-0", locations)
        self.assertIn("nfs://host/path/image-id-6", locations)
        self.assertEqual(2, len(locations))

    def test_construct_image_url_direct(self):
        img_loc = ("nfs://host/path/image-id", None)

        locations = self.driver._construct_image_nfs_url(img_loc)

        self.assertIn("nfs://host/path/image-id", locations)

    @ddt.data(None, 'raw', 'qcow2')
    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_extend_volume(self, file_format, mock_get):

        volume = fake_volume.fake_volume_obj(self.ctxt)
        if file_format:
            volume.admin_metadata = {'format': file_format}
        mock_get.return_value = volume
        new_size = 100
        volume_copy = copy.copy(volume)
        volume_copy['size'] = new_size

        path = '%s/%s' % (fake.NFS_SHARE, fake.NFS_VOLUME['name'])
        self.mock_object(self.driver,
                         'local_path',
                         return_value=path)
        mock_resize_image_file = self.mock_object(self.driver,
                                                  '_resize_image_file')
        mock_get_volume_extra_specs = self.mock_object(
            na_utils, 'get_volume_extra_specs', return_value=fake.EXTRA_SPECS)
        mock_do_qos_for_volume = self.mock_object(self.driver,
                                                  '_do_qos_for_volume')

        self.driver.extend_volume(volume, new_size)

        mock_resize_image_file.assert_called_once_with(path, new_size,
                                                       file_format=file_format)
        mock_get_volume_extra_specs.assert_called_once_with(volume)
        mock_do_qos_for_volume.assert_called_once_with(volume_copy,
                                                       fake.EXTRA_SPECS,
                                                       cleanup=False)

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_extend_volume_resize_error(self, mock_get):

        volume = fake_volume.fake_volume_obj(self.ctxt)
        mock_get.return_value = volume
        new_size = 100
        volume_copy = copy.copy(volume)
        volume_copy['size'] = new_size

        path = '%s/%s' % (fake.NFS_SHARE, fake.NFS_VOLUME['name'])
        self.mock_object(self.driver,
                         'local_path',
                         return_value=path)
        mock_resize_image_file = self.mock_object(
            self.driver, '_resize_image_file',
            side_effect=netapp_api.NaApiError)
        mock_get_volume_extra_specs = self.mock_object(
            na_utils, 'get_volume_extra_specs', return_value=fake.EXTRA_SPECS)
        mock_do_qos_for_volume = self.mock_object(self.driver,
                                                  '_do_qos_for_volume')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          volume,
                          new_size)

        mock_resize_image_file.assert_called_once_with(path, new_size,
                                                       file_format=None)
        self.assertFalse(mock_get_volume_extra_specs.called)
        self.assertFalse(mock_do_qos_for_volume.called)

    @mock.patch('cinder.objects.volume.Volume.get_by_id')
    def test_extend_volume_qos_error(self, mock_get):

        volume = fake_volume.fake_volume_obj(self.ctxt)
        mock_get.return_value = volume
        new_size = 100
        volume_copy = copy.copy(volume)
        volume_copy['size'] = new_size

        path = '%s/%s' % (fake.NFS_SHARE, fake.NFS_VOLUME['name'])
        self.mock_object(self.driver,
                         'local_path',
                         return_value=path)
        mock_resize_image_file = self.mock_object(self.driver,
                                                  '_resize_image_file')
        mock_get_volume_extra_specs = self.mock_object(
            na_utils, 'get_volume_extra_specs',
            return_value=fake.EXTRA_SPECS)
        mock_do_qos_for_volume = self.mock_object(
            self.driver, '_do_qos_for_volume',
            side_effect=netapp_api.NaApiError)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          volume,
                          new_size)

        mock_resize_image_file.assert_called_once_with(path, new_size,
                                                       file_format=None)
        mock_get_volume_extra_specs.assert_called_once_with(volume)
        mock_do_qos_for_volume.assert_called_once_with(volume_copy,
                                                       fake.EXTRA_SPECS,
                                                       cleanup=False)

    def test_is_share_clone_compatible(self):
        self.assertRaises(NotImplementedError,
                          self.driver._is_share_clone_compatible,
                          fake.NFS_VOLUME,
                          fake.NFS_SHARE)

    def test_get_share_mount_and_vol_from_vol_ref(self):
        self.mock_object(volume_utils, 'resolve_hostname',
                         return_value='10.12.142.11')
        self.mock_object(os.path, 'isfile', return_value=True)
        self.driver._mounted_shares = [self.fake_nfs_export_1]
        vol_path = "%s/%s" % (self.fake_nfs_export_1, 'test_file_name')
        vol_ref = {'source-name': vol_path}
        self.driver._ensure_shares_mounted = mock.Mock()
        self.driver._get_mount_point_for_share = mock.Mock(
            return_value=self.fake_mount_point)

        (share, mount, file_path) = (
            self.driver._get_share_mount_and_vol_from_vol_ref(vol_ref))

        self.assertEqual(self.fake_nfs_export_1, share)
        self.assertEqual(self.fake_mount_point, mount)
        self.assertEqual('test_file_name', file_path)

    def test_get_share_mount_and_vol_from_vol_ref_with_bad_ref(self):
        self.mock_object(volume_utils, 'resolve_hostname',
                         return_value='10.12.142.11')
        self.driver._mounted_shares = [self.fake_nfs_export_1]
        vol_ref = {'source-id': '1234546'}

        self.driver._ensure_shares_mounted = mock.Mock()
        self.driver._get_mount_point_for_share = mock.Mock(
            return_value=self.fake_mount_point)

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver._get_share_mount_and_vol_from_vol_ref,
                          vol_ref)

    def test_get_share_mount_and_vol_from_vol_ref_where_not_found(self):
        self.mock_object(volume_utils, 'resolve_hostname',
                         return_value='10.12.142.11')
        self.driver._mounted_shares = [self.fake_nfs_export_1]
        vol_path = "%s/%s" % (self.fake_nfs_export_2, 'test_file_name')
        vol_ref = {'source-name': vol_path}

        self.driver._ensure_shares_mounted = mock.Mock()
        self.driver._get_mount_point_for_share = mock.Mock(
            return_value=self.fake_mount_point)

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver._get_share_mount_and_vol_from_vol_ref,
                          vol_ref)

    def test_get_share_mount_and_vol_from_vol_ref_where_is_dir(self):
        self.mock_object(volume_utils, 'resolve_hostname',
                         return_value='10.12.142.11')
        self.driver._mounted_shares = [self.fake_nfs_export_1]
        vol_ref = {'source-name': self.fake_nfs_export_2}

        self.driver._ensure_shares_mounted = mock.Mock()
        self.driver._get_mount_point_for_share = mock.Mock(
            return_value=self.fake_mount_point)

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver._get_share_mount_and_vol_from_vol_ref,
                          vol_ref)

    @ddt.data(None,
              {'replication_status': fields.ReplicationStatus.ENABLED})
    def test_manage_existing(self, model_update):
        self.mock_object(utils, 'get_file_size',
                         return_value=1074253824)
        self.driver._mounted_shares = [self.fake_nfs_export_1]
        test_file = 'test_file_name'
        volume = fake.FAKE_MANAGE_VOLUME
        vol_path = "%s/%s" % (self.fake_nfs_export_1, test_file)
        vol_ref = {'source-name': vol_path}
        self.driver._check_volume_type = mock.Mock()
        self.mock_object(self.driver, '_execute')
        self.driver._ensure_shares_mounted = mock.Mock()
        self.driver._get_mount_point_for_share = mock.Mock(
            return_value=self.fake_mount_point)
        self.driver._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.fake_nfs_export_1, self.fake_mount_point,
                          test_file))
        mock_get_specs = self.mock_object(na_utils, 'get_volume_extra_specs')
        mock_get_specs.return_value = {}
        self.mock_object(self.driver, '_do_qos_for_volume')
        self.mock_object(self.driver, '_get_volume_model_update',
                         return_value=model_update)

        actual_model_update = self.driver.manage_existing(volume, vol_ref)

        self.assertEqual(
            self.fake_nfs_export_1, actual_model_update['provider_location'])
        if model_update:
            self.assertEqual(model_update['replication_status'],
                             actual_model_update['replication_status'])
        else:
            self.assertNotIn('replication_status', actual_model_update)
        self.driver._check_volume_type.assert_called_once_with(
            volume, self.fake_nfs_export_1, test_file, {})

    def test_manage_existing_move_fails(self):
        self.mock_object(utils, 'get_file_size', return_value=1074253824)
        self.driver._mounted_shares = [self.fake_nfs_export_1]
        test_file = 'test_file_name'
        volume = fake.FAKE_MANAGE_VOLUME
        vol_path = "%s/%s" % (self.fake_nfs_export_1, test_file)
        vol_ref = {'source-name': vol_path}
        self.driver._check_volume_type = mock.Mock()
        self.driver._ensure_shares_mounted = mock.Mock()
        self.driver._get_mount_point_for_share = mock.Mock(
            return_value=self.fake_mount_point)
        self.driver._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.fake_nfs_export_1, self.fake_mount_point,
                          test_file))
        self.driver._execute = mock.Mock(
            side_effect=processutils.ProcessExecutionError)
        mock_get_specs = self.mock_object(na_utils, 'get_volume_extra_specs')
        mock_get_specs.return_value = {}
        self.mock_object(self.driver, '_do_qos_for_volume')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.manage_existing, volume, vol_ref)

    def test_unmanage(self):
        mock_log = self.mock_object(nfs_base, 'LOG')
        volume = {'id': '123', 'provider_location': '/share'}

        retval = self.driver.unmanage(volume)

        self.assertIsNone(retval)
        self.assertEqual(1, mock_log.info.call_count)

    def test_manage_existing_get_size(self):
        test_file = 'test_file_name'
        self.driver._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.fake_nfs_export_1, self.fake_mount_point,
                          test_file))
        self.mock_object(utils, 'get_file_size', return_value=1073741824)
        self.driver._mounted_shares = [self.fake_nfs_export_1]
        volume = fake.FAKE_MANAGE_VOLUME
        vol_path = "%s/%s" % (self.fake_nfs_export_1, test_file)
        vol_ref = {'source-name': vol_path}

        self.driver._ensure_shares_mounted = mock.Mock()
        self.driver._get_mount_point_for_share = mock.Mock(
            return_value=self.fake_mount_point)

        vol_size = self.driver.manage_existing_get_size(volume, vol_ref)

        self.assertEqual(1, vol_size)

    def test_manage_existing_get_size_round_up(self):
        test_file = 'test_file_name'
        self.driver._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.fake_nfs_export_1, self.fake_mount_point,
                          test_file))
        self.mock_object(utils, 'get_file_size', return_value=1073760270)
        self.driver._mounted_shares = [self.fake_nfs_export_1]
        volume = fake.FAKE_MANAGE_VOLUME
        vol_path = "%s/%s" % (self.fake_nfs_export_1, test_file)
        vol_ref = {'source-name': vol_path}

        self.driver._ensure_shares_mounted = mock.Mock()
        self.driver._get_mount_point_for_share = mock.Mock(
            return_value=self.fake_mount_point)

        vol_size = self.driver.manage_existing_get_size(volume, vol_ref)

        self.assertEqual(2, vol_size)

    def test_manage_existing_get_size_error(self):
        test_file = 'test_file_name'
        self.driver._get_share_mount_and_vol_from_vol_ref = mock.Mock(
            return_value=(self.fake_nfs_export_1, self.fake_mount_point,
                          test_file))
        self.driver._mounted_shares = [self.fake_nfs_export_1]
        volume = fake.FAKE_MANAGE_VOLUME
        vol_path = "%s/%s" % (self.fake_nfs_export_1, test_file)
        vol_ref = {'source-name': vol_path}

        self.driver._ensure_shares_mounted = mock.Mock()
        self.driver._get_mount_point_for_share = mock.Mock(
            return_value=self.fake_mount_point)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.manage_existing_get_size,
                          volume,
                          vol_ref)

    @ddt.data(True, False)
    def test_delete_file(self, volume_not_present):
        mock_get_provider_location = self.mock_object(
            self.driver, '_get_provider_location')
        mock_get_provider_location.return_value = fake.NFS_SHARE
        mock_volume_not_present = self.mock_object(
            self.driver, '_volume_not_present')
        mock_volume_not_present.return_value = volume_not_present
        mock_get_volume_path = self.mock_object(
            self.driver, '_get_volume_path')
        mock_get_volume_path.return_value = fake.PATH
        mock_delete = self.mock_object(self.driver, '_delete')

        self.driver._delete_file(fake.CG_VOLUME_ID, fake.CG_VOLUME_NAME)

        mock_get_provider_location.assert_called_once_with(fake.CG_VOLUME_ID)
        mock_volume_not_present.assert_called_once_with(
            fake.NFS_SHARE, fake.CG_VOLUME_NAME)
        if not volume_not_present:
            mock_get_volume_path.assert_called_once_with(
                fake.NFS_SHARE, fake.CG_VOLUME_NAME)
            mock_delete.assert_called_once_with(fake.PATH)

    def test_delete_file_volume_not_present(self):
        mock_get_provider_location = self.mock_object(
            self.driver, '_get_provider_location')
        mock_get_provider_location.return_value = fake.NFS_SHARE
        mock_volume_not_present = self.mock_object(
            self.driver, '_volume_not_present')
        mock_volume_not_present.return_value = True
        mock_get_volume_path = self.mock_object(
            self.driver, '_get_volume_path')
        mock_delete = self.mock_object(self.driver, '_delete')

        self.driver._delete_file(fake.CG_VOLUME_ID, fake.CG_VOLUME_NAME)

        mock_get_provider_location.assert_called_once_with(fake.CG_VOLUME_ID)
        mock_volume_not_present.assert_called_once_with(
            fake.NFS_SHARE, fake.CG_VOLUME_NAME)
        mock_get_volume_path.assert_not_called()
        mock_delete.assert_not_called()

    def test_check_for_setup_error(self):
        super_check_for_setup_error = self.mock_object(
            nfs.NfsDriver, 'check_for_setup_error')
        mock_start_tasks = self.mock_object(
            self.driver.loopingcalls, 'start_tasks')

        self.driver.check_for_setup_error()

        super_check_for_setup_error.assert_called_once_with()
        mock_start_tasks.assert_called_once_with()

    def test_add_looping_tasks(self):
        mock_add_task = self.mock_object(self.driver.loopingcalls, 'add_task')
        mock_call_snap_cleanup = self.mock_object(
            self.driver, '_delete_snapshots_marked_for_deletion')
        mock_call_ems_logging = self.mock_object(
            self.driver, '_handle_ems_logging')

        self.driver._add_looping_tasks()

        mock_add_task.assert_has_calls([
            mock.call(mock_call_snap_cleanup, loopingcalls.ONE_MINUTE,
                      loopingcalls.ONE_MINUTE),
            mock.call(mock_call_ems_logging, loopingcalls.ONE_HOUR)])

    def test__clone_from_cache(self):
        image_id = 'fake_image_id'
        cache_result = [
            ('fakepool_bad1', '/fakepath/img-cache-1'),
            ('fakepool', '/fakepath/img-cache-2'),
            ('fakepool_bad2', '/fakepath/img-cache-3'),
        ]
        mock_call__is_share_clone_compatible = self.mock_object(
            self.driver, '_is_share_clone_compatible')
        mock_call__is_share_clone_compatible.return_value = True
        mock_call__do_clone_rel_img_cache = self.mock_object(
            self.driver, '_do_clone_rel_img_cache')
        cloned = self.driver._clone_from_cache(fake.test_volume, image_id,
                                               cache_result)
        self.assertTrue(cloned)
        mock_call__is_share_clone_compatible.assert_called_once_with(
            fake.test_volume, 'fakepool')
        mock_call__do_clone_rel_img_cache.assert_called_once_with(
            '/fakepath/img-cache-2', 'fakename', 'fakepool',
            '/fakepath/img-cache-2'
        )

    def test__clone_from_cache_not_found(self):
        image_id = 'fake_image_id'
        cache_result = [
            ('fakepool_bad1', '/fakepath/img-cache-1'),
            ('fakepool_bad2', '/fakepath/img-cache-2'),
            ('fakepool_bad3', '/fakepath/img-cache-3'),
        ]
        mock_call__is_share_clone_compatible = self.mock_object(
            self.driver, '_is_share_clone_compatible')
        mock_call__do_clone_rel_img_cache = self.mock_object(
            self.driver, '_do_clone_rel_img_cache')
        cloned = self.driver._clone_from_cache(fake.test_volume, image_id,
                                               cache_result)
        self.assertFalse(cloned)
        mock_call__is_share_clone_compatible.assert_not_called()
        mock_call__do_clone_rel_img_cache.assert_not_called()

    def test__find_share(self):
        mock_extract = self.mock_object(volume_utils, 'extract_host',
                                        return_value=fake.POOL_NAME)

        pool_name = self.driver._find_share(fake.VOLUME)

        self.assertEqual(pool_name, fake.POOL_NAME)
        mock_extract.assert_called_once_with(fake.VOLUME['host'],
                                             level='pool')

    def test__find_share_error(self):
        mock_extract = self.mock_object(volume_utils, 'extract_host',
                                        return_value=None)

        self.assertRaises(exception.InvalidHost,
                          self.driver._find_share,
                          fake.VOLUME)
        mock_extract.assert_called_once_with(fake.VOLUME['host'],
                                             level='pool')

    def test__ensure_flexgroup_not_in_cg_raises(self):
        self.mock_object(self.driver, '_is_flexgroup',
                         return_value=True)
        self.mock_object(volume_utils, 'is_group_a_cg_snapshot_type',
                         return_value=True)
        fake_v1 = {
            'group': 'fake_group',
            'host': 'fake_host',
            'id': 'fake_id'
        }
        self.assertRaises(na_utils.NetAppDriverException,
                          self.driver._ensure_flexgroup_not_in_cg,
                          fake_v1)

    def test__is_flexgroup_clone_file_supported(self):
        self.assertRaises(NotImplementedError,
                          self.driver._is_flexgroup_clone_file_supported)

    def test_update_migrated_volume(self):
        self.assertRaises(NotImplementedError,
                          self.driver.update_migrated_volume, self.ctxt,
                          fake.test_volume, mock.sentinel.new_volume,
                          mock.sentinel.original_status)

    @ddt.data({'is_flexgroup': False, 'is_flexgroup_supported': False},
              {'is_flexgroup': False, 'is_flexgroup_supported': True},
              {'is_flexgroup': True, 'is_flexgroup_supported': False},
              {'is_flexgroup': True, 'is_flexgroup_supported': True})
    @ddt.unpack
    def test_revert_to_snapshot(self, is_flexgroup, is_flexgroup_supported):
        context = {}

        self.mock_object(self.driver,
                         '_is_flexgroup',
                         return_value=is_flexgroup)
        self.mock_object(self.driver,
                         '_is_flexgroup_clone_file_supported',
                         return_value=is_flexgroup_supported)
        mock_revert_to_snapshot = self.mock_object(
            remotefs.RemoteFSSnapDriverDistributed, 'revert_to_snapshot')
        mock__revert_to_snapshot = self.mock_object(self.driver,
                                                    '_revert_to_snapshot')

        self.driver.revert_to_snapshot(context, fake.SNAPSHOT_VOLUME,
                                       fake.SNAPSHOT)

        if is_flexgroup and not is_flexgroup_supported:
            mock_revert_to_snapshot.assert_called_once_with(
                context, fake.SNAPSHOT_VOLUME, fake.SNAPSHOT)
            mock__revert_to_snapshot.assert_not_called()
        else:
            mock__revert_to_snapshot.assert_called_once_with(
                fake.SNAPSHOT_VOLUME, fake.SNAPSHOT)
            mock_revert_to_snapshot.assert_not_called()

    def test__revert_to_snapshot(self):
        self.assertRaises(NotImplementedError, self.driver._revert_to_snapshot,
                          fake.SNAPSHOT_VOLUME, fake.SNAPSHOT)
