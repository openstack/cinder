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

import ddt
import os
import socket

import mock
from oslo_concurrency import processutils
from oslo_config import cfg

from cinder.brick.local_dev import lvm as brick_lvm
from cinder import db
from cinder import exception
from cinder.objects import fields
from cinder.tests import fake_driver
from cinder.tests.unit.brick import fake_lvm
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as tests_utils
from cinder.tests.unit.volume import test_driver
from cinder.volume import configuration as conf
from cinder.volume.drivers import lvm
import cinder.volume.utils
from cinder.volume import utils as volutils

CONF = cfg.CONF

fake_opt = [
    cfg.StrOpt('fake_opt1', default='fake', help='fake opts')
]


@ddt.ddt
class LVMVolumeDriverTestCase(test_driver.BaseDriverTestCase):
    """Test case for VolumeDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMVolumeDriver"
    FAKE_VOLUME = {'name': 'test1',
                   'id': 'test1'}

    @mock.patch.object(os.path, 'exists', return_value=True)
    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver, 'create_export')
    def test_delete_volume_invalid_parameter(self, _mock_create_export,
                                             mock_exists):
        self.configuration.volume_clear = 'zero'
        self.configuration.volume_clear_size = 0
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db)
        # Test volume without 'size' field and 'volume_size' field
        self.assertRaises(exception.InvalidParameterValue,
                          lvm_driver._delete_volume,
                          self.FAKE_VOLUME)

    @mock.patch.object(os.path, 'exists', return_value=False)
    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver, 'create_export')
    def test_delete_volume_bad_path(self, _mock_create_export, mock_exists):
        self.configuration.volume_clear = 'zero'
        self.configuration.volume_clear_size = 0
        self.configuration.volume_type = 'default'

        volume = dict(self.FAKE_VOLUME, size=1)
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db)

        self.assertRaises(exception.VolumeBackendAPIException,
                          lvm_driver._delete_volume, volume)

    @mock.patch.object(volutils, 'clear_volume')
    @mock.patch.object(volutils, 'copy_volume')
    @mock.patch.object(fake_driver.FakeLoggingVolumeDriver, 'create_export')
    def test_delete_volume_thinlvm_snap(self, _mock_create_export,
                                        mock_copy, mock_clear):
        vg_obj = fake_lvm.FakeBrickLVM('cinder-volumes',
                                       False,
                                       None,
                                       'default')
        self.configuration.volume_clear = 'zero'
        self.configuration.volume_clear_size = 0
        self.configuration.lvm_type = 'thin'
        self.configuration.iscsi_helper = 'tgtadm'
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         vg_obj=vg_obj, db=db)

        uuid = '00000000-0000-0000-0000-c3aa7ee01536'

        fake_snapshot = {'name': 'volume-' + uuid,
                         'id': uuid,
                         'size': 123}
        lvm_driver._delete_volume(fake_snapshot, is_snapshot=True)

    @mock.patch.object(volutils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_lvm_version',
                return_value=(2, 2, 100))
    def test_check_for_setup_error(self, _mock_get_version, vgs):
        vg_obj = fake_lvm.FakeBrickLVM('cinder-volumes',
                                       False,
                                       None,
                                       'auto')

        configuration = conf.Configuration(fake_opt, 'fake_group')
        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration,
                                         vg_obj=vg_obj, db=db)

        lvm_driver.delete_snapshot = mock.Mock()

        volume = tests_utils.create_volume(self.context,
                                           host=socket.gethostname())
        volume_id = volume['id']

        backup = {}
        backup['volume_id'] = volume_id
        backup['user_id'] = fake.USER_ID
        backup['project_id'] = fake.PROJECT_ID
        backup['host'] = socket.gethostname()
        backup['availability_zone'] = '1'
        backup['display_name'] = 'test_check_for_setup_error'
        backup['display_description'] = 'test_check_for_setup_error'
        backup['container'] = 'fake'
        backup['status'] = fields.BackupStatus.CREATING
        backup['fail_reason'] = ''
        backup['service'] = 'fake'
        backup['parent_id'] = None
        backup['size'] = 5 * 1024 * 1024
        backup['object_count'] = 22
        db.backup_create(self.context, backup)

        lvm_driver.check_for_setup_error()

    def test_retype_volume(self):
        vol = tests_utils.create_volume(self.context)
        new_type = fake.VOLUME_TYPE_ID
        diff = {}
        host = 'fake_host'
        retyped = self.volume.driver.retype(self.context, vol, new_type,
                                            diff, host)
        self.assertTrue(retyped)

    def test_update_migrated_volume(self):
        fake_volume_id = fake.VOLUME_ID
        fake_new_volume_id = fake.VOLUME2_ID
        fake_provider = 'fake_provider'
        original_volume_name = CONF.volume_name_template % fake_volume_id
        current_name = CONF.volume_name_template % fake_new_volume_id
        fake_volume = tests_utils.create_volume(self.context)
        fake_volume['id'] = fake_volume_id
        fake_new_volume = tests_utils.create_volume(self.context)
        fake_new_volume['id'] = fake_new_volume_id
        fake_new_volume['provider_location'] = fake_provider
        fake_vg = fake_lvm.FakeBrickLVM('cinder-volumes', False,
                                        None, 'default')
        with mock.patch.object(self.volume.driver, 'vg') as vg:
            vg.return_value = fake_vg
            vg.rename_volume.return_value = None
            update = self.volume.driver.update_migrated_volume(self.context,
                                                               fake_volume,
                                                               fake_new_volume,
                                                               'available')
            vg.rename_volume.assert_called_once_with(current_name,
                                                     original_volume_name)
            self.assertEqual({'_name_id': None,
                              'provider_location': None}, update)

            vg.rename_volume.reset_mock()
            vg.rename_volume.side_effect = processutils.ProcessExecutionError
            update = self.volume.driver.update_migrated_volume(self.context,
                                                               fake_volume,
                                                               fake_new_volume,
                                                               'available')
            vg.rename_volume.assert_called_once_with(current_name,
                                                     original_volume_name)
            self.assertEqual({'_name_id': fake_new_volume_id,
                              'provider_location': fake_provider},
                             update)

    def test_create_volume_from_snapshot_none_sparse(self):

        with mock.patch.object(self.volume.driver, 'vg'), \
                mock.patch.object(self.volume.driver, '_create_volume'), \
                mock.patch.object(volutils, 'copy_volume') as mock_copy:

            # Test case for thick LVM
            src_volume = tests_utils.create_volume(self.context)
            snapshot_ref = tests_utils.create_snapshot(self.context,
                                                       src_volume['id'])
            dst_volume = tests_utils.create_volume(self.context)
            self.volume.driver.create_volume_from_snapshot(dst_volume,
                                                           snapshot_ref)

            volume_path = self.volume.driver.local_path(dst_volume)
            snapshot_path = self.volume.driver.local_path(snapshot_ref)
            volume_size = 1024
            block_size = '1M'
            mock_copy.assert_called_with(snapshot_path,
                                         volume_path,
                                         volume_size,
                                         block_size,
                                         execute=self.volume.driver._execute,
                                         sparse=False)

    def test_create_volume_from_snapshot_sparse(self):

        self.configuration.lvm_type = 'thin'
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db)

        with mock.patch.object(lvm_driver, 'vg'):

            # Test case for thin LVM
            lvm_driver._sparse_copy_volume = True
            src_volume = tests_utils.create_volume(self.context)
            snapshot_ref = tests_utils.create_snapshot(self.context,
                                                       src_volume['id'])
            dst_volume = tests_utils.create_volume(self.context)
            lvm_driver.create_volume_from_snapshot(dst_volume,
                                                   snapshot_ref)

    def test_create_volume_from_snapshot_sparse_extend(self):

        self.configuration.lvm_type = 'thin'
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db)

        with mock.patch.object(lvm_driver, 'vg'), \
                mock.patch.object(lvm_driver, 'extend_volume') as mock_extend:

            # Test case for thin LVM
            lvm_driver._sparse_copy_volume = True
            src_volume = tests_utils.create_volume(self.context)
            snapshot_ref = tests_utils.create_snapshot(self.context,
                                                       src_volume['id'])
            dst_volume = tests_utils.create_volume(self.context)
            dst_volume['size'] = snapshot_ref['volume_size'] + 1
            lvm_driver.create_volume_from_snapshot(dst_volume,
                                                   snapshot_ref)
            mock_extend.assert_called_with(dst_volume, dst_volume['size'])

    @mock.patch.object(cinder.volume.utils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.update_volume_group_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_physical_volumes')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.supports_thin_provisioning',
                return_value=True)
    def test_lvm_type_auto_thin_pool_exists(self, *_unused_mocks):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.lvm_type = 'auto'

        vg_obj = fake_lvm.FakeBrickLVM('cinder-volumes',
                                       False,
                                       None,
                                       'default')

        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration,
                                         vg_obj=vg_obj)

        lvm_driver.check_for_setup_error()

        self.assertEqual('thin', lvm_driver.configuration.lvm_type)

    @mock.patch.object(cinder.volume.utils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    @mock.patch.object(cinder.brick.local_dev.lvm.LVM, 'get_volumes',
                       return_value=[])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.update_volume_group_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_physical_volumes')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.supports_thin_provisioning',
                return_value=True)
    def test_lvm_type_auto_no_lvs(self, *_unused_mocks):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.lvm_type = 'auto'

        vg_obj = fake_lvm.FakeBrickLVM('cinder-volumes',
                                       False,
                                       None,
                                       'default')

        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration,
                                         vg_obj=vg_obj)

        lvm_driver.check_for_setup_error()

        self.assertEqual('thin', lvm_driver.configuration.lvm_type)

    @mock.patch.object(cinder.volume.utils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_lv_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.activate_lv')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.'
                'supports_lvchange_ignoreskipactivation')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.update_volume_group_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_physical_volumes')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.supports_thin_provisioning',
                return_value=False)
    def test_lvm_type_auto_no_thin_support(self, *_unused_mocks):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.lvm_type = 'auto'

        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration)

        lvm_driver.check_for_setup_error()

        self.assertEqual('default', lvm_driver.configuration.lvm_type)

    @mock.patch.object(cinder.volume.utils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_lv_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.activate_lv')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.'
                'supports_lvchange_ignoreskipactivation')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.update_volume_group_info')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_all_physical_volumes')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_volume')
    @mock.patch('cinder.brick.local_dev.lvm.LVM.supports_thin_provisioning',
                return_value=False)
    def test_lvm_type_auto_no_thin_pool(self, *_unused_mocks):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.lvm_type = 'auto'

        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration)

        lvm_driver.check_for_setup_error()

        self.assertEqual('default', lvm_driver.configuration.lvm_type)

    @mock.patch.object(lvm.LVMVolumeDriver, 'extend_volume')
    def test_create_cloned_volume_by_thin_snapshot(self, mock_extend):
        self.configuration.lvm_type = 'thin'
        fake_vg = mock.Mock(fake_lvm.FakeBrickLVM('cinder-volumes', False,
                                                  None, 'default'))
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         vg_obj=fake_vg,
                                         db=db)
        fake_volume = tests_utils.create_volume(self.context, size=1)
        fake_new_volume = tests_utils.create_volume(self.context, size=2)

        lvm_driver.create_cloned_volume(fake_new_volume, fake_volume)
        fake_vg.create_lv_snapshot.assert_called_once_with(
            fake_new_volume['name'], fake_volume['name'], 'thin')
        mock_extend.assert_called_once_with(fake_new_volume, 2)
        fake_vg.activate_lv.assert_called_once_with(
            fake_new_volume['name'], is_snapshot=True, permanent=True)

    def test_lvm_migrate_volume_no_loc_info(self):
        host = {'capabilities': {}}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_bad_loc_info(self):
        capabilities = {'location_info': 'foo'}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_diff_driver(self):
        capabilities = {'location_info': 'FooDriver:foo:bar:default:0'}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_diff_host(self):
        capabilities = {'location_info': 'LVMVolumeDriver:foo:bar:default:0'}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_in_use(self):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:bar' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'in-use'}
        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    @mock.patch.object(volutils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    def test_lvm_migrate_volume_same_volume_group(self, vgs):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume.driver.migrate_volume, self.context,
                          vol, host)

    @mock.patch.object(lvm.LVMVolumeDriver, '_create_volume')
    @mock.patch.object(brick_lvm.LVM, 'get_all_physical_volumes')
    @mock.patch.object(brick_lvm.LVM, 'delete')
    @mock.patch.object(volutils, 'copy_volume',
                       side_effect=processutils.ProcessExecutionError)
    @mock.patch.object(volutils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes'}])
    def test_lvm_migrate_volume_volume_copy_error(self, vgs, copy_volume,
                                                  mock_delete, mock_pvs,
                                                  mock_create):

        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}
        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes-old',
                                                      False, None, 'default')
        self.assertRaises(processutils.ProcessExecutionError,
                          self.volume.driver.migrate_volume, self.context,
                          vol, host)
        mock_delete.assert_called_once_with(vol)

    @mock.patch.object(volutils, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes-2'}])
    def test_lvm_volume_group_missing(self, vgs):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes-3:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'test', 'id': 1, 'size': 1, 'status': 'available'}

        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

        moved, model_update = self.volume.driver.migrate_volume(self.context,
                                                                vol, host)
        self.assertFalse(moved)
        self.assertIsNone(model_update)

    def test_lvm_migrate_volume_proceed(self):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes-2:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'testvol', 'id': 1, 'size': 2, 'status': 'available'}

        def fake_execute(*args, **kwargs):
            pass

        def get_all_volume_groups():
            # NOTE(flaper87) Return just the destination
            # host to test the check of dest VG existence.
            return [{'name': 'cinder-volumes-2'}]

        def _fake_get_all_physical_volumes(obj, root_helper, vg_name):
            return [{}]

        with mock.patch.object(brick_lvm.LVM, 'get_all_physical_volumes',
                               return_value = [{}]), \
                mock.patch.object(self.volume.driver, '_execute') \
                as mock_execute, \
                mock.patch.object(volutils, 'copy_volume') as mock_copy, \
                mock.patch.object(volutils, 'get_all_volume_groups',
                                  side_effect = get_all_volume_groups), \
                mock.patch.object(self.volume.driver, '_delete_volume'):

            self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                          False,
                                                          None,
                                                          'default')
            mock_execute.return_value = ("mock_outs", "mock_errs")
            moved, model_update = \
                self.volume.driver.migrate_volume(self.context, vol, host)
            self.assertTrue(moved)
            self.assertIsNone(model_update)
            mock_copy.assert_called_once_with(
                '/dev/mapper/cinder--volumes-testvol',
                '/dev/mapper/cinder--volumes--2-testvol',
                2048,
                '1M',
                execute=mock_execute,
                sparse=False)

    def test_lvm_migrate_volume_proceed_with_thin(self):
        hostname = socket.gethostname()
        capabilities = {'location_info': 'LVMVolumeDriver:%s:'
                        'cinder-volumes-2:default:0' % hostname}
        host = {'capabilities': capabilities}
        vol = {'name': 'testvol', 'id': 1, 'size': 2, 'status': 'available'}

        def fake_execute(*args, **kwargs):
            pass

        def get_all_volume_groups():
            # NOTE(flaper87) Return just the destination
            # host to test the check of dest VG existence.
            return [{'name': 'cinder-volumes-2'}]

        def _fake_get_all_physical_volumes(obj, root_helper, vg_name):
            return [{}]

        self.configuration.lvm_type = 'thin'
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db)

        with mock.patch.object(brick_lvm.LVM, 'get_all_physical_volumes',
                               return_value = [{}]), \
                mock.patch.object(lvm_driver, '_execute') \
                as mock_execute, \
                mock.patch.object(volutils, 'copy_volume') as mock_copy, \
                mock.patch.object(volutils, 'get_all_volume_groups',
                                  side_effect = get_all_volume_groups), \
                mock.patch.object(lvm_driver, '_delete_volume'):

            lvm_driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                  False,
                                                  None,
                                                  'default')
            lvm_driver._sparse_copy_volume = True
            mock_execute.return_value = ("mock_outs", "mock_errs")
            moved, model_update = \
                lvm_driver.migrate_volume(self.context, vol, host)
            self.assertTrue(moved)
            self.assertIsNone(model_update)
            mock_copy.assert_called_once_with(
                '/dev/mapper/cinder--volumes-testvol',
                '/dev/mapper/cinder--volumes--2-testvol',
                2048,
                '1M',
                execute=mock_execute,
                sparse=True)

    @staticmethod
    def _get_manage_existing_lvs(name):
        """Helper method used by the manage_existing tests below."""
        lvs = [{'name': 'fake_lv', 'size': '1.75'},
               {'name': 'fake_lv_bad_size', 'size': 'Not a float'}]
        for lv in lvs:
            if lv['name'] == name:
                return lv

    def _setup_stubs_for_manage_existing(self):
        """Helper to set up common stubs for the manage_existing tests."""
        self.volume.driver.vg = fake_lvm.FakeBrickLVM('cinder-volumes',
                                                      False,
                                                      None,
                                                      'default')

    @mock.patch.object(db.sqlalchemy.api, 'volume_get',
                       side_effect=exception.VolumeNotFound(
                           volume_id='d8cd1feb-2dcc-404d-9b15-b86fe3bec0a1'))
    def test_lvm_manage_existing_not_found(self, mock_vol_get):
        self._setup_stubs_for_manage_existing()

        vol_name = 'volume-d8cd1feb-2dcc-404d-9b15-b86fe3bec0a1'
        ref = {'source-name': 'fake_lv'}
        vol = {'name': vol_name, 'id': fake.VOLUME_ID, 'size': 0}

        with mock.patch.object(self.volume.driver.vg, 'rename_volume'):
            model_update = self.volume.driver.manage_existing(vol, ref)
            self.assertIsNone(model_update)

    @mock.patch('cinder.db.sqlalchemy.api.resource_exists', return_value=True)
    def test_lvm_manage_existing_already_managed(self, exists_mock):
        self._setup_stubs_for_manage_existing()

        vol_name = 'volume-d8cd1feb-2dcc-404d-9b15-b86fe3bec0a1'
        ref = {'source-name': vol_name}
        vol = {'name': 'test', 'id': 1, 'size': 0}

        with mock.patch.object(self.volume.driver.vg, 'rename_volume'):
            self.assertRaises(exception.ManageExistingAlreadyManaged,
                              self.volume.driver.manage_existing,
                              vol, ref)

    def test_lvm_manage_existing(self):
        """Good pass on managing an LVM volume.

        This test case ensures that, when a logical volume with the
        specified name exists, and the size is as expected, no error is
        returned from driver.manage_existing, and that the rename_volume
        function is called in the Brick LVM code with the correct arguments.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_lv'}
        vol = {'name': 'test', 'id': fake.VOLUME_ID, 'size': 0}

        def _rename_volume(old_name, new_name):
            self.assertEqual(ref['source-name'], old_name)
            self.assertEqual(vol['name'], new_name)

        with mock.patch.object(self.volume.driver.vg,
                               'rename_volume') as mock_rename_volume, \
                mock.patch.object(self.volume.driver.vg, 'get_volume',
                                  self._get_manage_existing_lvs):
                mock_rename_volume.return_value = _rename_volume
                size = self.volume.driver.manage_existing_get_size(vol, ref)
                self.assertEqual(2, size)
                model_update = self.volume.driver.manage_existing(vol, ref)
                self.assertIsNone(model_update)

    def test_lvm_manage_existing_bad_size(self):
        """Make sure correct exception on bad size returned from LVM.

        This test case ensures that the correct exception is raised when
        the information returned for the existing LVs is not in the format
        that the manage_existing code expects.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_lv_bad_size'}
        vol = {'name': 'test', 'id': fake.VOLUME_ID, 'size': 2}

        with mock.patch.object(self.volume.driver.vg, 'get_volume',
                               self._get_manage_existing_lvs):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.volume.driver.manage_existing_get_size,
                              vol, ref)

    def test_lvm_manage_existing_bad_ref(self):
        """Error case where specified LV doesn't exist.

        This test case ensures that the correct exception is raised when
        the caller attempts to manage a volume that does not exist.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_nonexistent_lv'}
        vol = {'name': 'test', 'id': 1, 'size': 0, 'status': 'available'}

        with mock.patch.object(self.volume.driver.vg, 'get_volume',
                               self._get_manage_existing_lvs):
            self.assertRaises(exception.ManageExistingInvalidReference,
                              self.volume.driver.manage_existing_get_size,
                              vol, ref)

    def test_lvm_manage_existing_snapshot(self):
        """Good pass on managing an LVM snapshot.

        This test case ensures that, when a logical volume's snapshot with the
        specified name exists, and the size is as expected, no error is
        returned from driver.manage_existing_snapshot, and that the
        rename_volume function is called in the Brick LVM code with the correct
        arguments.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_lv'}
        snp = {'name': 'test', 'id': fake.SNAPSHOT_ID, 'size': 0}

        def _rename_volume(old_name, new_name):
            self.assertEqual(ref['source-name'], old_name)
            self.assertEqual(snp['name'], new_name)

        with mock.patch.object(self.volume.driver.vg,
                               'rename_volume') as mock_rename_volume, \
                mock.patch.object(self.volume.driver.vg, 'get_volume',
                                  self._get_manage_existing_lvs):
                mock_rename_volume.return_value = _rename_volume
                size = self.volume.driver.manage_existing_snapshot_get_size(
                    snp, ref)
                self.assertEqual(2, size)
                model_update = self.volume.driver.manage_existing_snapshot(
                    snp, ref)
                self.assertIsNone(model_update)

    def test_lvm_manage_existing_snapshot_bad_ref(self):
        """Error case where specified LV snapshot doesn't exist.

        This test case ensures that the correct exception is raised when
        the caller attempts to manage a snapshot that does not exist.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_nonexistent_lv'}
        snp = {
            'name': 'test',
            'id': fake.SNAPSHOT_ID,
            'size': 0,
            'status': 'available',
        }
        with mock.patch.object(self.volume.driver.vg, 'get_volume',
                               self._get_manage_existing_lvs):
            self.assertRaises(
                exception.ManageExistingInvalidReference,
                self.volume.driver.manage_existing_snapshot_get_size,
                snp, ref)

    def test_revert_snapshot(self):
        self._setup_stubs_for_manage_existing()
        self.configuration.lvm_type = 'auto'
        fake_volume = tests_utils.create_volume(self.context,
                                                display_name='fake_volume')
        fake_snapshot = tests_utils.create_snapshot(
            self.context, fake_volume.id)

        with mock.patch.object(self.volume.driver.vg,
                               'revert') as mock_revert,\
                mock.patch.object(self.volume.driver.vg,
                                  'create_lv_snapshot') as mock_create,\
                mock.patch.object(self.volume.driver.vg,
                                  'deactivate_lv') as mock_deactive,\
                mock.patch.object(self.volume.driver.vg,
                                  'activate_lv') as mock_active:
            self.volume.driver.revert_to_snapshot(self.context,
                                                  fake_volume,
                                                  fake_snapshot)
            mock_revert.assert_called_once_with(
                self.volume.driver._escape_snapshot(fake_snapshot.name))
            mock_deactive.assert_called_once_with(fake_volume.name)
            mock_active.assert_called_once_with(fake_volume.name)
            mock_create.assert_called_once_with(
                self.volume.driver._escape_snapshot(fake_snapshot.name),
                fake_volume.name, self.configuration.lvm_type)

    def test_revert_thin_snapshot(self):

        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.lvm_type = 'thin'
        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration,
                                         db=db)
        fake_volume = tests_utils.create_volume(self.context,
                                                display_name='fake_volume')
        fake_snapshot = tests_utils.create_snapshot(
            self.context, fake_volume.id)

        self.assertRaises(NotImplementedError,
                          lvm_driver.revert_to_snapshot,
                          self.context, fake_volume,
                          fake_snapshot)

    def test_lvm_manage_existing_snapshot_bad_size(self):
        """Make sure correct exception on bad size returned from LVM.

        This test case ensures that the correct exception is raised when
        the information returned for the existing LVs is not in the format
        that the manage_existing_snapshot code expects.
        """
        self._setup_stubs_for_manage_existing()

        ref = {'source-name': 'fake_lv_bad_size'}
        snp = {'name': 'test', 'id': fake.SNAPSHOT_ID, 'size': 2}

        with mock.patch.object(self.volume.driver.vg, 'get_volume',
                               self._get_manage_existing_lvs):
            self.assertRaises(
                exception.VolumeBackendAPIException,
                self.volume.driver.manage_existing_snapshot_get_size,
                snp, ref)

    def test_lvm_unmanage(self):
        volume = tests_utils.create_volume(self.context, status='available',
                                           size=1, host=CONF.host)
        ret = self.volume.driver.unmanage(volume)
        self.assertIsNone(ret)

    def test_lvm_get_manageable_volumes(self):
        cinder_vols = [{'id': '00000000-0000-0000-0000-000000000000'}]
        lvs = [{'name': 'volume-00000000-0000-0000-0000-000000000000',
                'size': '1.75'},
               {'name': 'volume-00000000-0000-0000-0000-000000000001',
                'size': '3.0'},
               {'name': 'snapshot-00000000-0000-0000-0000-000000000002',
                'size': '2.2'},
               {'name': 'myvol', 'size': '4.0'}]
        self.volume.driver.vg = mock.Mock()
        self.volume.driver.vg.get_volumes.return_value = lvs
        self.volume.driver.vg.lv_is_snapshot.side_effect = [False, False,
                                                            True, False]
        self.volume.driver.vg.lv_is_open.side_effect = [True, False]
        res = self.volume.driver.get_manageable_volumes(cinder_vols, None,
                                                        1000, 0,
                                                        ['size'], ['asc'])
        exp = [{'size': 2, 'reason_not_safe': 'already managed',
                'extra_info': None,
                'reference': {'source-name':
                              'volume-00000000-0000-0000-0000-000000000000'},
                'cinder_id': '00000000-0000-0000-0000-000000000000',
                'safe_to_manage': False},
               {'size': 3, 'reason_not_safe': 'volume in use',
                'reference': {'source-name':
                              'volume-00000000-0000-0000-0000-000000000001'},
                'safe_to_manage': False, 'cinder_id': None,
                'extra_info': None},
               {'size': 4, 'reason_not_safe': None,
                'safe_to_manage': True, 'reference': {'source-name': 'myvol'},
                'cinder_id': None, 'extra_info': None}]
        self.assertEqual(exp, res)

    def test_lvm_get_manageable_snapshots(self):
        cinder_snaps = [{'id': '00000000-0000-0000-0000-000000000000'}]
        lvs = [{'name': 'snapshot-00000000-0000-0000-0000-000000000000',
                'size': '1.75'},
               {'name': 'volume-00000000-0000-0000-0000-000000000001',
                'size': '3.0'},
               {'name': 'snapshot-00000000-0000-0000-0000-000000000002',
                'size': '2.2'},
               {'name': 'mysnap', 'size': '4.0'}]
        self.volume.driver.vg = mock.Mock()
        self.volume.driver.vg.get_volumes.return_value = lvs
        self.volume.driver.vg.lv_is_snapshot.side_effect = [True, False, True,
                                                            True]
        self.volume.driver.vg.lv_is_open.side_effect = [True, False]
        self.volume.driver.vg.lv_get_origin.side_effect = [
            'volume-00000000-0000-0000-0000-000000000000',
            'volume-00000000-0000-0000-0000-000000000002',
            'myvol']
        res = self.volume.driver.get_manageable_snapshots(cinder_snaps, None,
                                                          1000, 0,
                                                          ['size'], ['asc'])
        exp = [{'size': 2, 'reason_not_safe': 'already managed',
                'reference':
                {'source-name':
                 'snapshot-00000000-0000-0000-0000-000000000000'},
                'safe_to_manage': False, 'extra_info': None,
                'cinder_id': '00000000-0000-0000-0000-000000000000',
                'source_reference':
                {'source-name':
                 'volume-00000000-0000-0000-0000-000000000000'}},
               {'size': 3, 'reason_not_safe': 'snapshot in use',
                'reference':
                {'source-name':
                 'snapshot-00000000-0000-0000-0000-000000000002'},
                'safe_to_manage': False, 'extra_info': None,
                'cinder_id': None,
                'source_reference':
                {'source-name':
                 'volume-00000000-0000-0000-0000-000000000002'}},
               {'size': 4, 'reason_not_safe': None,
                'reference': {'source-name': 'mysnap'},
                'safe_to_manage': True, 'cinder_id': None,
                'source_reference': {'source-name': 'myvol'},
                'extra_info': None}]
        self.assertEqual(exp, res)

    # Global setting, LVM setting, expected outcome
    @ddt.data((10.0, 2.0, 2.0))
    @ddt.data((10.0, None, 10.0))
    @ddt.unpack
    def test_lvm_max_over_subscription_ratio(self,
                                             global_value,
                                             lvm_value,
                                             expected_value):
        configuration = conf.Configuration(fake_opt, 'fake_group')
        configuration.max_over_subscription_ratio = global_value
        configuration.lvm_max_over_subscription_ratio = lvm_value

        fake_vg = mock.Mock(fake_lvm.FakeBrickLVM('cinder-volumes', False,
                                                  None, 'default'))
        lvm_driver = lvm.LVMVolumeDriver(configuration=configuration,
                                         vg_obj=fake_vg, db=db)

        self.assertEqual(expected_value,
                         lvm_driver.configuration.max_over_subscription_ratio)


class LVMISCSITestCase(test_driver.BaseDriverTestCase):
    """Test Case for LVMISCSIDriver"""
    driver_name = "cinder.volume.drivers.lvm.LVMVolumeDriver"

    def setUp(self):
        super(LVMISCSITestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.iscsi_target_prefix = 'iqn.2010-10.org.openstack:'
        self.configuration.iscsi_ip_address = '0.0.0.0'
        self.configuration.iscsi_port = 3260

    def _attach_volume(self):
        """Attach volumes to an instance."""
        volume_id_list = []
        for index in range(3):
            vol = {}
            vol['size'] = 0
            vol_ref = db.volume_create(self.context, vol)
            self.volume.create_volume(self.context, vol_ref)
            vol_ref = db.volume_get(self.context, vol_ref['id'])

            # each volume has a different mountpoint
            mountpoint = "/dev/sd" + chr((ord('b') + index))
            instance_uuid = '12345678-1234-5678-1234-567812345678'
            db.volume_attached(self.context, vol_ref['id'], instance_uuid,
                               mountpoint)
            volume_id_list.append(vol_ref['id'])

        return volume_id_list

    def test_do_iscsi_discovery(self):
        self.configuration = conf.Configuration(None)
        iscsi_driver = \
            cinder.volume.targets.tgt.TgtAdm(
                configuration=self.configuration)

        ret = ("%s dummy" % CONF.iscsi_ip_address, '')
        with mock.patch('cinder.utils.execute',
                        return_value=ret):
            volume = {"name": "dummy",
                      "host": "0.0.0.0",
                      "id": "12345678-1234-5678-1234-567812345678"}
            iscsi_driver._do_iscsi_discovery(volume)

    def test_get_iscsi_properties(self):
        volume = {"provider_location": '',
                  "id": "0",
                  "provider_auth": "a b c",
                  "attached_mode": "rw"}
        iscsi_driver = \
            cinder.volume.targets.tgt.TgtAdm(configuration=self.configuration)
        iscsi_driver._do_iscsi_discovery = lambda v: "0.0.0.0:0000,0 iqn:iqn 0"
        result = iscsi_driver._get_iscsi_properties(volume)
        self.assertEqual("0.0.0.0:0000", result["target_portal"])
        self.assertEqual("iqn:iqn", result["target_iqn"])
        self.assertEqual(0, result["target_lun"])

    def test_get_iscsi_properties_multiple_portals(self):
        volume = {"provider_location": '1.1.1.1:3260;2.2.2.2:3261,1 iqn:iqn 0',
                  "id": "0",
                  "provider_auth": "a b c",
                  "attached_mode": "rw"}
        iscsi_driver = \
            cinder.volume.targets.tgt.TgtAdm(configuration=self.configuration)
        result = iscsi_driver._get_iscsi_properties(volume)
        self.assertEqual("1.1.1.1:3260", result["target_portal"])
        self.assertEqual("iqn:iqn", result["target_iqn"])
        self.assertEqual(0, result["target_lun"])
        self.assertEqual(["1.1.1.1:3260", "2.2.2.2:3261"],
                         result["target_portals"])
        self.assertEqual(["iqn:iqn", "iqn:iqn"], result["target_iqns"])
        self.assertEqual([0, 0], result["target_luns"])

    @mock.patch.object(brick_lvm.LVM, 'get_volumes',
                       return_value=[{'vg': 'fake_vg', 'name': 'fake_vol',
                                      'size': '1000'}])
    @mock.patch.object(brick_lvm.LVM, 'get_all_physical_volumes')
    @mock.patch.object(brick_lvm.LVM, 'get_all_volume_groups',
                       return_value=[{'name': 'cinder-volumes',
                                      'size': '5.52',
                                      'available': '0.52',
                                      'lv_count': '2',
                                      'uuid': 'vR1JU3-FAKE-C4A9-PQFh-Mctm'}])
    @mock.patch('cinder.brick.local_dev.lvm.LVM.get_lvm_version',
                return_value=(2, 2, 100))
    def test_get_volume_stats(self, _mock_get_version, mock_vgs, mock_pvs,
                              mock_get_volumes):
        self.volume.driver.vg = brick_lvm.LVM('cinder-volumes', 'sudo')

        self.volume.driver._update_volume_stats()

        stats = self.volume.driver._stats

        self.assertEqual(
            float('5.52'), stats['pools'][0]['total_capacity_gb'])
        self.assertEqual(
            float('0.52'), stats['pools'][0]['free_capacity_gb'])
        self.assertEqual(
            float('5.0'), stats['pools'][0]['provisioned_capacity_gb'])
        self.assertEqual(
            int('1'), stats['pools'][0]['total_volumes'])
        self.assertFalse(stats['sparse_copy_volume'])

        # Check value of sparse_copy_volume for thin enabled case.
        # This value is set in check_for_setup_error.
        self.configuration = conf.Configuration(None)
        self.configuration.lvm_type = 'thin'
        vg_obj = fake_lvm.FakeBrickLVM('cinder-volumes',
                                       False,
                                       None,
                                       'default')
        lvm_driver = lvm.LVMVolumeDriver(configuration=self.configuration,
                                         db=db,
                                         vg_obj=vg_obj)
        lvm_driver.check_for_setup_error()
        lvm_driver.vg = brick_lvm.LVM('cinder-volumes', 'sudo')
        lvm_driver._update_volume_stats()
        stats = lvm_driver._stats
        self.assertTrue(stats['sparse_copy_volume'])

    def test_validate_connector(self):
        iscsi_driver =\
            cinder.volume.targets.tgt.TgtAdm(
                configuration=self.configuration)

        # Validate a valid connector
        connector = {'ip': '10.0.0.2',
                     'host': 'fakehost',
                     'initiator': 'iqn.2012-07.org.fake:01'}
        iscsi_driver.validate_connector(connector)

        # Validate a connector without the initiator
        connector = {'ip': '10.0.0.2', 'host': 'fakehost'}
        self.assertRaises(exception.InvalidConnectorException,
                          iscsi_driver.validate_connector, connector)
