# Copyright 2017 Inspur Corp.
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
#
"""
Tests for the Inspur InStorage volume driver.
"""

import ddt
from eventlet import greenthread
import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import importutils
from oslo_utils import units
import paramiko

from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import ssh_utils
from cinder import test
from cinder.tests.unit import utils as testutils
from cinder.volume import configuration as conf
from cinder.volume.drivers.inspur.instorage import (
    replication as instorage_rep)
from cinder.volume.drivers.inspur.instorage import instorage_common
from cinder.volume.drivers.inspur.instorage import instorage_iscsi
from cinder.volume import qos_specs
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types

from cinder.tests.unit.volume.drivers.inspur.instorage import fakes


CONF = cfg.CONF


@ddt.ddt
class InStorageMCSCommonDriverTestCase(test.TestCase):
    def setUp(self):
        super(InStorageMCSCommonDriverTestCase, self).setUp()
        self._def_flags = {'san_ip': 'hostname',
                           'instorage_san_secondary_ip': 'secondaryname',
                           'san_login': 'user',
                           'san_password': 'pass',
                           'instorage_mcs_volpool_name': fakes.MCS_POOLS,
                           'instorage_mcs_localcopy_timeout': 20,
                           'instorage_mcs_localcopy_rate': 49,
                           'instorage_mcs_allow_tenant_qos': True}
        config = conf.Configuration(instorage_common.instorage_mcs_opts,
                                    conf.SHARED_CONF_GROUP)
        # Override any configs that may get set in __init__
        self._reset_flags(config)
        self.driver = fakes.FakeInStorageMCSISCSIDriver(configuration=config)
        self._driver = instorage_iscsi.InStorageMCSISCSIDriver(
            configuration=config)
        wwpns = ['1234567890123450', '6543210987654325']
        initiator = 'test.initiator.%s' % 123450
        self._connector = {'ip': '1.234.56.78',
                           'host': 'instorage-mcs-test',
                           'wwpns': wwpns,
                           'initiator': initiator}
        self.sim = fakes.FakeInStorage(fakes.MCS_POOLS)

        self.driver.set_fake_storage(self.sim)
        self.ctxt = context.get_admin_context()

        self.ctxt = context.get_admin_context()
        db_driver = CONF.db_driver
        self.db = importutils.import_module(db_driver)
        self.driver.db = self.db
        self.driver.do_setup(None)
        self.driver.check_for_setup_error()
        self.driver._assistant.check_lcmapping_interval = 0
        self.mock_object(instorage_iscsi.InStorageMCSISCSIDriver,
                         'DEFAULT_GR_SLEEP', 0)
        self.mock_object(greenthread, 'sleep')

    def _set_flag(self, flag, value, configuration=None):
        if not configuration:
            configuration = self.driver.configuration
        group = configuration.config_group
        self.override_config(flag, value, group)

    def _reset_flags(self, configuration=None):
        if not configuration:
            configuration = self.driver.configuration
        CONF.reset()
        for k, v in self._def_flags.items():
            self._set_flag(k, v, configuration)

    def _assert_vol_exists(self, name, exists):
        is_vol_defined = self.driver._assistant.is_vdisk_defined(name)
        self.assertEqual(exists, is_vol_defined)

    def test_instorage_mcs_connectivity(self):
        # Make sure we detect if the pool doesn't exist
        no_exist_pool = 'i-dont-exist-%s' % 56789
        self._set_flag('instorage_mcs_volpool_name', no_exist_pool)
        self.assertRaises(exception.InvalidInput,
                          self.driver.do_setup, None)
        self._reset_flags()

        # Check the case where the user didn't configure IP addresses
        # as well as receiving unexpected results from the storage
        self.sim.error_injection('lsnodecanister', 'header_mismatch')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, None)
        self.sim.error_injection('lsnodecanister', 'remove_field')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, None)
        self.sim.error_injection('lsportip', 'header_mismatch')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, None)
        self.sim.error_injection('lsportip', 'remove_field')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, None)

        # Check with bad parameters
        self._set_flag('san_ip', '')
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        self._set_flag('san_password', None)
        self._set_flag('san_private_key', None)
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        self._set_flag('instorage_mcs_vol_grainsize', 42)
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        self._set_flag('instorage_mcs_vol_compression', True)
        self._set_flag('instorage_mcs_vol_rsize', -1)
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        self._set_flag('instorage_mcs_vol_iogrp', 5)
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        self.sim.error_injection('lslicense', 'no_compression')
        self.sim.error_injection('lsguicapabilities', 'no_compression')
        self._set_flag('instorage_mcs_vol_compression', True)
        self.driver.do_setup(None)
        self.assertRaises(exception.InvalidInput,
                          self.driver.check_for_setup_error)
        self._reset_flags()

        # Finally, check with good parameters
        self.driver.do_setup(None)

    @mock.patch.object(ssh_utils, 'SSHPool')
    @mock.patch.object(processutils, 'ssh_execute')
    def test_run_ssh_set_up_with_san_ip(self, mock_ssh_execute, mock_ssh_pool):
        ssh_cmd = ['mcsinq']
        self._driver._run_ssh(ssh_cmd)

        mock_ssh_pool.assert_called_once_with(
            self._driver.configuration.san_ip,
            self._driver.configuration.san_ssh_port,
            self._driver.configuration.ssh_conn_timeout,
            self._driver.configuration.san_login,
            password=self._driver.configuration.san_password,
            privatekey=self._driver.configuration.san_private_key,
            min_size=self._driver.configuration.ssh_min_pool_conn,
            max_size=self._driver.configuration.ssh_max_pool_conn)

    @mock.patch.object(ssh_utils, 'SSHPool')
    @mock.patch.object(processutils, 'ssh_execute')
    def test_run_ssh_set_up_with_secondary_ip(self, mock_ssh_execute,
                                              mock_ssh_pool):
        mock_ssh_pool.side_effect = [paramiko.SSHException, mock.MagicMock()]
        ssh_cmd = ['mcsinq']
        self._driver._run_ssh(ssh_cmd)

        mock_ssh_pool.assert_called_with(
            self._driver.configuration.instorage_san_secondary_ip,
            self._driver.configuration.san_ssh_port,
            self._driver.configuration.ssh_conn_timeout,
            self._driver.configuration.san_login,
            password=self._driver.configuration.san_password,
            privatekey=self._driver.configuration.san_private_key,
            min_size=self._driver.configuration.ssh_min_pool_conn,
            max_size=self._driver.configuration.ssh_max_pool_conn)

    @mock.patch.object(ssh_utils, 'SSHPool')
    @mock.patch.object(processutils, 'ssh_execute')
    def test_run_ssh_fail_to_secondary_ip(self, mock_ssh_execute,
                                          mock_ssh_pool):
        mock_ssh_execute.side_effect = [processutils.ProcessExecutionError,
                                        mock.MagicMock()]
        ssh_cmd = ['mcsinq']
        self._driver._run_ssh(ssh_cmd)

        mock_ssh_pool.assert_called_with(
            self._driver.configuration.instorage_san_secondary_ip,
            self._driver.configuration.san_ssh_port,
            self._driver.configuration.ssh_conn_timeout,
            self._driver.configuration.san_login,
            password=self._driver.configuration.san_password,
            privatekey=self._driver.configuration.san_private_key,
            min_size=self._driver.configuration.ssh_min_pool_conn,
            max_size=self._driver.configuration.ssh_max_pool_conn)

    @mock.patch.object(ssh_utils, 'SSHPool')
    @mock.patch.object(processutils, 'ssh_execute')
    def test_run_secondary_ip_ssh_fail_to_san_ip(self, mock_ssh_execute,
                                                 mock_ssh_pool):
        mock_ssh_pool.side_effect = [
            paramiko.SSHException,
            mock.MagicMock(
                ip=self._driver.configuration.instorage_san_secondary_ip),
            mock.MagicMock()]
        mock_ssh_execute.side_effect = [processutils.ProcessExecutionError,
                                        mock.MagicMock()]
        ssh_cmd = ['mcsinq']
        self._driver._run_ssh(ssh_cmd)

        mock_ssh_pool.assert_called_with(
            self._driver.configuration.san_ip,
            self._driver.configuration.san_ssh_port,
            self._driver.configuration.ssh_conn_timeout,
            self._driver.configuration.san_login,
            password=self._driver.configuration.san_password,
            privatekey=self._driver.configuration.san_private_key,
            min_size=self._driver.configuration.ssh_min_pool_conn,
            max_size=self._driver.configuration.ssh_max_pool_conn)

    @mock.patch.object(ssh_utils, 'SSHPool')
    @mock.patch.object(processutils, 'ssh_execute')
    def test_run_ssh_both_ip_set_failure(self, mock_ssh_execute,
                                         mock_ssh_pool):
        mock_ssh_pool.side_effect = [
            paramiko.SSHException,
            mock.MagicMock(),
            mock.MagicMock()]
        mock_ssh_execute.side_effect = [processutils.ProcessExecutionError,
                                        processutils.ProcessExecutionError]
        ssh_cmd = ['mcsinq']
        self.assertRaises(processutils.ProcessExecutionError,
                          self._driver._run_ssh, ssh_cmd)

    @mock.patch.object(ssh_utils, 'SSHPool')
    @mock.patch.object(processutils, 'ssh_execute')
    def test_run_ssh_second_ip_not_set_failure(self, mock_ssh_execute,
                                               mock_ssh_pool):
        mock_ssh_execute.side_effect = [processutils.ProcessExecutionError,
                                        mock.MagicMock()]
        self._set_flag('instorage_san_secondary_ip', None)
        ssh_cmd = ['mcsinq']
        self.assertRaises(processutils.ProcessExecutionError,
                          self._driver._run_ssh, ssh_cmd)

    @mock.patch.object(ssh_utils, 'SSHPool')
    @mock.patch.object(processutils, 'ssh_execute')
    def test_run_ssh_consistent_active_ip(self, mock_ssh_execute,
                                          mock_ssh_pool):
        ssh_cmd = ['mcsinq']
        self._driver._run_ssh(ssh_cmd)
        self._driver._run_ssh(ssh_cmd)
        self._driver._run_ssh(ssh_cmd)
        self.assertEqual(self._driver.configuration.san_ip,
                         self._driver.active_ip)
        mock_ssh_execute.side_effect = [paramiko.SSHException,
                                        mock.MagicMock(), mock.MagicMock()]
        self._driver._run_ssh(ssh_cmd)
        self._driver._run_ssh(ssh_cmd)
        self.assertEqual(self._driver.configuration.instorage_san_secondary_ip,
                         self._driver.active_ip)

    def _generate_vol_info(self, vol_name, vol_id):
        pool = fakes.get_test_pool()
        prop = {'mdisk_grp_name': pool}
        if vol_name:
            prop.update(volume_name=vol_name,
                        volume_id=vol_id,
                        volume_size=10)
        else:
            prop.update(size=10,
                        volume_type_id=None,
                        mdisk_grp_name=pool,
                        host='openstack@mcs#%s' % pool)
        vol = testutils.create_volume(self.ctxt, **prop)
        return vol

    def _generate_snapshot_info(self, vol):
        snap = testutils.create_snapshot(self.ctxt, vol.id)
        return snap

    def _create_volume(self, **kwargs):
        pool = fakes.get_test_pool()
        prop = {'host': 'openstack@mcs#%s' % pool,
                'size': 1}
        for p in prop.keys():
            if p not in kwargs:
                kwargs[p] = prop[p]
        vol = testutils.create_volume(self.ctxt, **kwargs)
        self.driver.create_volume(vol)
        return vol

    def _delete_volume(self, volume):
        self.driver.delete_volume(volume)
        self.db.volume_destroy(self.ctxt, volume['id'])

    def _create_group_in_db(self, **kwargs):
        group = testutils.create_group(self.ctxt, **kwargs)
        return group

    def _create_group(self, **kwargs):
        group = self._create_group_in_db(**kwargs)

        model_update = self.driver.create_group(self.ctxt, group)
        self.assertEqual(fields.GroupStatus.AVAILABLE,
                         model_update['status'],
                         "Group created failed")
        return group

    def _create_group_snapshot_in_db(self, grp_id, **kwargs):
        group_snapshot = testutils.create_group_snapshot(self.ctxt,
                                                         group_id=grp_id,
                                                         **kwargs)
        snapshots = []
        grp_id = group_snapshot['group_id']
        volumes = self.db.volume_get_all_by_group(self.ctxt.elevated(),
                                                  grp_id)

        if not volumes:
            msg = "Group is empty. No group snapshot will be created."
            raise exception.InvalidGroup(reason=msg)

        for volume in volumes:
            snapshots.append(testutils.create_snapshot(
                self.ctxt, volume['id'],
                group_snapshot.id,
                group_snapshot.name,
                group_snapshot.id,
                fields.SnapshotStatus.CREATING))
        return group_snapshot, snapshots

    def _create_group_snapshot(self, grp_id, **kwargs):
        group_snapshot, snapshots = self._create_group_snapshot_in_db(
            grp_id, **kwargs)

        model_update, snapshots_model = (
            self.driver.create_group_snapshot(
                self.ctxt, group_snapshot, snapshots))
        self.assertEqual('available',
                         model_update['status'],
                         "Group_Snapshot created failed")

        for snapshot in snapshots_model:
            self.assertEqual(fields.SnapshotStatus.AVAILABLE,
                             snapshot['status'])
        return group_snapshot, snapshots

    def _create_test_vol(self, opts):
        ctxt = testutils.get_test_admin_context()
        type_ref = volume_types.create(ctxt, 'testtype', opts)
        volume = self._generate_vol_info(None, None)
        volume.volume_type_id = type_ref['id']
        volume.volume_typ = objects.VolumeType.get_by_id(ctxt,
                                                         type_ref['id'])
        self.driver.create_volume(volume)

        attrs = self.driver._assistant.get_vdisk_attributes(volume['name'])
        self.driver.delete_volume(volume)
        volume_types.destroy(ctxt, type_ref['id'])
        return attrs

    def _get_default_opts(self):
        opt = {'rsize': 2,
               'warning': 0,
               'autoexpand': True,
               'grainsize': 256,
               'compression': False,
               'intier': True,
               'iogrp': '0',
               'qos': None,
               'replication': False}
        return opt

    @mock.patch.object(instorage_common.InStorageAssistant, 'add_vdisk_qos')
    @mock.patch.object(instorage_common.InStorageMCSCommonDriver,
                       '_get_vdisk_params')
    def test_instorage_mcs_create_volume_with_qos(self, get_vdisk_params,
                                                  add_vdisk_qos):
        vol = testutils.create_volume(self.ctxt)
        fake_opts = self._get_default_opts()
        # If the qos is empty, chvdisk should not be called
        # for create_volume.
        get_vdisk_params.return_value = fake_opts
        self.driver.create_volume(vol)
        self._assert_vol_exists(vol['name'], True)
        self.assertFalse(add_vdisk_qos.called)
        self.driver.delete_volume(vol)

        # If the qos is not empty, chvdisk should be called
        # for create_volume.
        fake_opts['qos'] = {'IOThrottling': 5000}
        get_vdisk_params.return_value = fake_opts
        self.driver.create_volume(vol)
        self._assert_vol_exists(vol['name'], True)
        add_vdisk_qos.assert_called_once_with(vol['name'], fake_opts['qos'])

        self.driver.delete_volume(vol)
        self._assert_vol_exists(vol['name'], False)

    def test_instorage_mcs_snapshots(self):
        vol1 = self._create_volume()
        snap1 = self._generate_snapshot_info(vol1)

        # Test timeout and volume cleanup
        self._set_flag('instorage_mcs_localcopy_timeout', 1)
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_snapshot, snap1)
        self._assert_vol_exists(snap1['name'], False)
        self._reset_flags()

        # Test prestartlcmap failing
        with mock.patch.object(
                instorage_common.InStorageSSH, 'prestartlcmap') as prestart:
            prestart.side_effect = exception.VolumeBackendAPIException(data='')
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.create_snapshot, snap1)

        self.sim.error_injection('lslcmap', 'speed_up')
        self.sim.error_injection('startlcmap', 'bad_id')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, snap1)
        self._assert_vol_exists(snap1['name'], False)
        self.sim.error_injection('prestartlcmap', 'bad_id')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, snap1)
        self._assert_vol_exists(snap1['name'], False)

        # Test successful snapshot
        self.driver.create_snapshot(snap1)
        self._assert_vol_exists(snap1['name'], True)

        # Try to create a snapshot from an non-existing volume - should fail
        snap_vol_src = self._generate_vol_info(None, None)
        snap_novol = self._generate_snapshot_info(snap_vol_src)
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_snapshot,
                          snap_novol)

        # We support deleting a volume that has snapshots, so delete the volume
        # first
        self.driver.delete_volume(vol1)
        self.driver.delete_snapshot(snap1)

    def test_instorage_mcs_create_cloned_volume(self):
        vol1 = self._create_volume()
        vol2 = testutils.create_volume(self.ctxt)
        vol3 = testutils.create_volume(self.ctxt)

        # Try to clone where source size > target size
        vol1['size'] = vol2['size'] + 1
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_cloned_volume,
                          vol2, vol1)
        self._assert_vol_exists(vol2['name'], False)

        # Try to clone where source size = target size
        vol1['size'] = vol2['size']
        self.sim.error_injection('lslcmap', 'speed_up')
        self.driver.create_cloned_volume(vol2, vol1)
        # validate copyrate was set on the local copy
        for i, lcmap in self.sim._lcmappings_list.items():
            if lcmap['target'] == vol1['name']:
                self.assertEqual('49', lcmap['copyrate'])
        self._assert_vol_exists(vol2['name'], True)

        # Try to clone where  source size < target size
        vol3['size'] = vol1['size'] + 1
        self.sim.error_injection('lslcmap', 'speed_up')
        self.driver.create_cloned_volume(vol3, vol1)
        # Validate copyrate was set on the local copy
        for i, lcmap in self.sim._lcmappings_list.items():
            if lcmap['target'] == vol1['name']:
                self.assertEqual('49', lcmap['copyrate'])
        self._assert_vol_exists(vol3['name'], True)

        # Delete in the 'opposite' order to make sure it works
        self.driver.delete_volume(vol3)
        self._assert_vol_exists(vol3['name'], False)
        self.driver.delete_volume(vol2)
        self._assert_vol_exists(vol2['name'], False)
        self.driver.delete_volume(vol1)
        self._assert_vol_exists(vol1['name'], False)

    def test_instorage_mcs_create_volume_from_snapshot(self):
        vol1 = self._create_volume(size=10)
        snap1 = self._generate_snapshot_info(vol1)
        self.driver.create_snapshot(snap1)
        vol2 = self._generate_vol_info(None, None)
        vol3 = self._generate_vol_info(None, None)

        # Try to create a volume from a non-existing snapshot
        snap_vol_src = self._generate_vol_info(None, None)
        snap_novol = self._generate_snapshot_info(snap_vol_src)
        vol_novol = self._generate_vol_info(None, None)
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume_from_snapshot,
                          vol_novol,
                          snap_novol)

        # Fail the snapshot
        with mock.patch.object(
                instorage_common.InStorageSSH, 'prestartlcmap') as prestart:
            prestart.side_effect = exception.VolumeBackendAPIException(data='')
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver.create_volume_from_snapshot,
                              vol2, snap1)
            self._assert_vol_exists(vol2['name'], False)

        # Try to create where volume size < snapshot size
        snap1.volume_size += 1
        self.assertRaises(exception.InvalidInput,
                          self.driver.create_volume_from_snapshot,
                          vol2, snap1)
        self._assert_vol_exists(vol2['name'], False)
        snap1.volume_size -= 1

        # Try to create where volume size > snapshot size
        vol2['size'] += 1
        self.sim.error_injection('lslcmap', 'speed_up')
        self.driver.create_volume_from_snapshot(vol2, snap1)
        self._assert_vol_exists(vol2['name'], True)
        vol2['size'] -= 1

        # Try to create where volume size = snapshot size
        self.sim.error_injection('lslcmap', 'speed_up')
        self.driver.create_volume_from_snapshot(vol3, snap1)
        self._assert_vol_exists(vol3['name'], True)

        # Delete in the 'opposite' order to make sure it works
        self.driver.delete_volume(vol3)
        self._assert_vol_exists(vol3['name'], False)
        self.driver.delete_volume(vol2)
        self._assert_vol_exists(vol2['name'], False)
        self.driver.delete_snapshot(snap1)
        self._assert_vol_exists(snap1['name'], False)
        self.driver.delete_volume(vol1)
        self._assert_vol_exists(vol1['name'], False)

    @mock.patch.object(instorage_common.InStorageAssistant, 'add_vdisk_qos')
    def test_instorage_mcs_create_volfromsnap_clone_with_qos(self,
                                                             add_vdisk_qos):
        vol1 = self._create_volume()
        snap1 = self._generate_snapshot_info(vol1)
        self.driver.create_snapshot(snap1)
        vol2 = self._generate_vol_info(None, None)
        vol3 = self._generate_vol_info(None, None)
        fake_opts = self._get_default_opts()

        # Succeed
        self.sim.error_injection('lslcmap', 'speed_up')

        # If the qos is empty, chvdisk should not be called
        # for create_volume_from_snapshot.
        with mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                               '_get_vdisk_params') as get_vdisk_params:
            get_vdisk_params.return_value = fake_opts
            self.driver.create_volume_from_snapshot(vol2, snap1)
            self._assert_vol_exists(vol2['name'], True)
            self.assertFalse(add_vdisk_qos.called)
            self.driver.delete_volume(vol2)

            # If the qos is not empty, chvdisk should be called
            # for create_volume_from_snapshot.
            fake_opts['qos'] = {'IOThrottling': 5000}
            get_vdisk_params.return_value = fake_opts
            self.driver.create_volume_from_snapshot(vol2, snap1)
            self._assert_vol_exists(vol2['name'], True)
            add_vdisk_qos.assert_called_once_with(vol2['name'],
                                                  fake_opts['qos'])

            self.sim.error_injection('lslcmap', 'speed_up')

            # If the qos is empty, chvdisk should not be called
            # for create_volume_from_snapshot.
            add_vdisk_qos.reset_mock()
            fake_opts['qos'] = None
            get_vdisk_params.return_value = fake_opts
            self.driver.create_cloned_volume(vol3, vol2)
            self._assert_vol_exists(vol3['name'], True)
            self.assertFalse(add_vdisk_qos.called)
            self.driver.delete_volume(vol3)

            # If the qos is not empty, chvdisk should be called
            # for create_volume_from_snapshot.
            fake_opts['qos'] = {'IOThrottling': 5000}
            get_vdisk_params.return_value = fake_opts
            self.driver.create_cloned_volume(vol3, vol2)
            self._assert_vol_exists(vol3['name'], True)
            add_vdisk_qos.assert_called_once_with(vol3['name'],
                                                  fake_opts['qos'])

        # Delete in the 'opposite' order to make sure it works
        self.driver.delete_volume(vol3)
        self._assert_vol_exists(vol3['name'], False)
        self.driver.delete_volume(vol2)
        self._assert_vol_exists(vol2['name'], False)
        self.driver.delete_snapshot(snap1)
        self._assert_vol_exists(snap1['name'], False)
        self.driver.delete_volume(vol1)
        self._assert_vol_exists(vol1['name'], False)

    def test_instorage_mcs_delete_vol_with_lcmap(self):
        vol1 = self._create_volume()
        # create two snapshots
        snap1 = self._generate_snapshot_info(vol1)
        snap2 = self._generate_snapshot_info(vol1)
        self.driver.create_snapshot(snap1)
        self.driver.create_snapshot(snap2)
        vol2 = self._generate_vol_info(None, None)
        vol3 = self._generate_vol_info(None, None)

        # Create vol from the second snapshot
        self.sim.error_injection('lslcmap', 'speed_up')
        self.driver.create_volume_from_snapshot(vol2, snap2)
        # validate copyrate was set on the local copy
        for i, lcmap in self.sim._lcmappings_list.items():
            if lcmap['target'] == vol2['name']:
                self.assertEqual('copying', lcmap['status'])
        self._assert_vol_exists(vol2['name'], True)

        self.sim.error_injection('lslcmap', 'speed_up')
        self.driver.create_cloned_volume(vol3, vol2)

        # validate copyrate was set on the local copy
        for i, lcmap in self.sim._lcmappings_list.items():
            if lcmap['target'] == vol3['name']:
                self.assertEqual('copying', lcmap['status'])
        self._assert_vol_exists(vol3['name'], True)

        # Delete in the 'opposite' order to make sure it works
        self.driver.delete_volume(vol3)
        self._assert_vol_exists(vol3['name'], False)
        self.driver.delete_volume(vol2)
        self._assert_vol_exists(vol2['name'], False)
        self.driver.delete_snapshot(snap2)
        self._assert_vol_exists(snap2['name'], False)
        self.driver.delete_snapshot(snap1)
        self._assert_vol_exists(snap1['name'], False)
        self.driver.delete_volume(vol1)
        self._assert_vol_exists(vol1['name'], False)

    def test_instorage_mcs_volumes(self):
        # Create a first volume
        volume = self._generate_vol_info(None, None)
        self.driver.create_volume(volume)

        self.driver.ensure_export(None, volume)

        # Do nothing
        self.driver.create_export(None, volume, {})
        self.driver.remove_export(None, volume)

        # Make sure volume attributes are as they should be
        attributes = self.driver._assistant.get_vdisk_attributes(volume[
                                                                 'name'])
        attr_size = float(attributes['capacity']) / units.Gi  # bytes to GB
        self.assertEqual(float(volume['size']), attr_size)
        pool = fakes.get_test_pool()
        self.assertEqual(pool, attributes['mdisk_grp_name'])

        # Try to create the volume again (should fail)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume,
                          volume)

        # Try to delete a volume that doesn't exist (should not fail)
        vol_no_exist = self._generate_vol_info('i_dont_exist', '111111')
        self.driver.delete_volume(vol_no_exist)
        # Ensure export for volume that doesn't exist (should not fail)
        self.driver.ensure_export(None, vol_no_exist)

        # Delete the volume
        self.driver.delete_volume(volume)

    def test_instorage_mcs_volume_name(self):
        # Create a volume with space in name
        volume = self._create_volume()
        self.driver.ensure_export(None, volume)

        # Ensure lsvdisk can find the volume by name
        attributes = self.driver._assistant.get_vdisk_attributes(volume.name)
        self.assertIn('name', attributes)
        self.assertEqual(volume.name, attributes['name'])
        self.driver.delete_volume(volume)

    def test_instorage_mcs_volume_params(self):
        # Option test matrix
        # Option        Value   Covered by test #
        # rsize         -1      1
        # rsize         2       2,3
        # warning       0       2
        # warning       80      3
        # autoexpand    True    2
        # autoexpand    False   3
        # grainsize     32      2
        # grainsize     256     3
        # compression   True    4
        # compression   False   2,3
        # intier      True    1,3
        # intier      False   2
        # iogrp         0       1
        # iogrp         1       2

        opts_list = []
        chck_list = []
        opts_list.append({'rsize': -1, 'intier': True, 'iogrp': '0'})
        chck_list.append({'free_capacity': '0', 'in_tier': 'on',
                          'IO_group_id': '0'})

        test_iogrp = '1'
        opts_list.append({'rsize': 2, 'compression': False, 'warning': 0,
                          'autoexpand': True, 'grainsize': 32,
                          'intier': False, 'iogrp': test_iogrp})
        chck_list.append({'-free_capacity': '0', 'compressed_copy': 'no',
                          'warning': '0', 'autoexpand': 'on',
                          'grainsize': '32', 'in_tier': 'off',
                          'IO_group_id': (test_iogrp)})
        opts_list.append({'rsize': 2, 'compression': False, 'warning': 80,
                          'autoexpand': False, 'grainsize': 256,
                          'intier': True})
        chck_list.append({'-free_capacity': '0', 'compressed_copy': 'no',
                          'warning': '80', 'autoexpand': 'off',
                          'grainsize': '256', 'in_tier': 'on'})
        opts_list.append({'rsize': 2, 'compression': True})
        chck_list.append({'-free_capacity': '0',
                          'compressed_copy': 'yes'})

        for idx in range(len(opts_list)):
            attrs = self._create_test_vol(opts_list[idx])
            for k, v in chck_list[idx].items():
                try:
                    if k[0] == '-':
                        k = k[1:]
                        self.assertNotEqual(v, attrs[k])
                    else:
                        self.assertEqual(v, attrs[k])
                except processutils.ProcessExecutionError as e:
                    if 'CMMVC7050E' not in e.stderr:
                        raise

    def test_instorage_mcs_unicode_host_and_volume_names(self):
        # We'll check with iSCSI only - nothing protocol-dependent here
        self.driver.do_setup(None)

        rand_id = 56789
        volume1 = self._generate_vol_info(None, None)
        self.driver.create_volume(volume1)
        self._assert_vol_exists(volume1['name'], True)

        self.assertRaises(exception.VolumeDriverException,
                          self.driver._assistant.create_host,
                          {'host': 12345})

        # Add a host first to make life interesting (this host and
        # conn['host'] should be translated to the same prefix, and the
        # initiator should differentiate
        tmpconn1 = {'initiator': u'unicode:initiator1.%s' % rand_id,
                    'ip': '10.10.10.10',
                    'host': u'unicode.foo}.bar{.baz-%s' % rand_id}
        self.driver._assistant.create_host(tmpconn1)

        # Add a host with a different prefix
        tmpconn2 = {'initiator': u'unicode:initiator2.%s' % rand_id,
                    'ip': '10.10.10.11',
                    'host': u'unicode.hello.world-%s' % rand_id}
        self.driver._assistant.create_host(tmpconn2)

        conn = {'initiator': u'unicode:initiator3.%s' % rand_id,
                'ip': '10.10.10.12',
                'host': u'unicode.foo.bar.baz-%s' % rand_id}
        self.driver.initialize_connection(volume1, conn)
        host_name = self.driver._assistant.get_host_from_connector(conn)
        self.assertIsNotNone(host_name)
        self.driver.terminate_connection(volume1, conn)
        host_name = self.driver._assistant.get_host_from_connector(conn)
        self.assertIsNone(host_name)
        self.driver.delete_volume(volume1)

        # Clean up temporary hosts
        for tmpconn in [tmpconn1, tmpconn2]:
            host_name = self.driver._assistant.get_host_from_connector(tmpconn)
            self.assertIsNotNone(host_name)
            self.driver._assistant.delete_host(host_name)

    def test_instorage_mcs_delete_volume_snapshots(self):
        # Create a volume with two snapshots
        master = self._create_volume()

        # Delete a snapshot
        snap = self._generate_snapshot_info(master)
        self.driver.create_snapshot(snap)
        self._assert_vol_exists(snap['name'], True)
        self.driver.delete_snapshot(snap)
        self._assert_vol_exists(snap['name'], False)

        # Delete a volume with snapshots (regular)
        snap = self._generate_snapshot_info(master)
        self.driver.create_snapshot(snap)
        self._assert_vol_exists(snap['name'], True)
        self.driver.delete_volume(master)
        self._assert_vol_exists(master['name'], False)

        # Fail create volume from snapshot - will force delete the volume
        volfs = self._generate_vol_info(None, None)
        self.sim.error_injection('startlcmap', 'bad_id')
        self.sim.error_injection('lslcmap', 'speed_up')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          volfs, snap)
        self._assert_vol_exists(volfs['name'], False)

        # Create volume from snapshot and delete it
        volfs = self._generate_vol_info(None, None)
        self.sim.error_injection('lslcmap', 'speed_up')
        self.driver.create_volume_from_snapshot(volfs, snap)
        self._assert_vol_exists(volfs['name'], True)
        self.driver.delete_volume(volfs)
        self._assert_vol_exists(volfs['name'], False)

        # Create volume from snapshot and delete the snapshot
        volfs = self._generate_vol_info(None, None)
        self.sim.error_injection('lslcmap', 'speed_up')
        self.driver.create_volume_from_snapshot(volfs, snap)
        self.driver.delete_snapshot(snap)
        self._assert_vol_exists(snap['name'], False)

        # Fail create clone - will force delete the target volume
        clone = self._generate_vol_info(None, None)
        self.sim.error_injection('startlcmap', 'bad_id')
        self.sim.error_injection('lslcmap', 'speed_up')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume, clone, volfs)
        self._assert_vol_exists(clone['name'], False)

        # Create the clone, delete the source and target
        clone = self._generate_vol_info(None, None)
        self.sim.error_injection('lslcmap', 'speed_up')
        self.driver.create_cloned_volume(clone, volfs)
        self._assert_vol_exists(clone['name'], True)
        self.driver.delete_volume(volfs)
        self._assert_vol_exists(volfs['name'], False)
        self.driver.delete_volume(clone)
        self._assert_vol_exists(clone['name'], False)

    @ddt.data((True, None), (True, 5), (False, -1), (False, 100))
    @ddt.unpack
    def test_instorage_mcs_get_volume_stats(
            self, is_thin_provisioning_enabled, rsize):
        self._set_flag('reserved_percentage', 25)
        self._set_flag('instorage_mcs_vol_rsize', rsize)
        stats = self.driver.get_volume_stats()
        for each_pool in stats['pools']:
            self.assertIn(each_pool['pool_name'],
                          self._def_flags['instorage_mcs_volpool_name'])
            self.assertFalse(each_pool['multiattach'])
            self.assertLessEqual(each_pool['free_capacity_gb'],
                                 each_pool['total_capacity_gb'])
            self.assertEqual(25, each_pool['reserved_percentage'])
            self.assertEqual(is_thin_provisioning_enabled,
                             each_pool['thin_provisioning_support'])
            self.assertEqual(not is_thin_provisioning_enabled,
                             each_pool['thick_provisioning_support'])
        expected = 'instorage-mcs-sim'
        self.assertEqual(expected, stats['volume_backend_name'])
        for each_pool in stats['pools']:
            self.assertIn(each_pool['pool_name'],
                          self._def_flags['instorage_mcs_volpool_name'])
            self.assertAlmostEqual(3328.0, each_pool['total_capacity_gb'])
            self.assertAlmostEqual(3287.5, each_pool['free_capacity_gb'])
            if is_thin_provisioning_enabled:
                self.assertAlmostEqual(
                    1576.96, each_pool['provisioned_capacity_gb'])

    def test_get_pool(self):
        ctxt = testutils.get_test_admin_context()
        type_ref = volume_types.create(ctxt, 'testtype', None)
        volume = self._generate_vol_info(None, None)
        volume.volume_type_id = type_ref['id']
        volume.volume_type = objects.VolumeType.get_by_id(ctxt,
                                                          type_ref['id'])
        self.driver.create_volume(volume)
        self.assertEqual(volume['mdisk_grp_name'],
                         self.driver.get_pool(volume))

        self.driver.delete_volume(volume)
        volume_types.destroy(ctxt, type_ref['id'])

    def test_instorage_mcs_extend_volume(self):
        volume = self._create_volume()
        self.driver.extend_volume(volume, '13')
        attrs = self.driver._assistant.get_vdisk_attributes(volume['name'])
        vol_size = int(attrs['capacity']) / units.Gi

        self.assertAlmostEqual(vol_size, 13)

        snap = self._generate_snapshot_info(volume)
        self.driver.create_snapshot(snap)
        self._assert_vol_exists(snap['name'], True)
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.extend_volume, volume, '16')

        self.driver.delete_snapshot(snap)
        self.driver.delete_volume(volume)

    @mock.patch.object(instorage_rep.InStorageMCSReplicationAsyncCopy,
                       'create_relationship')
    @mock.patch.object(instorage_rep.InStorageMCSReplicationAsyncCopy,
                       'extend_target_volume')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'delete_relationship')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_relationship_info')
    def _instorage_mcs_extend_volume_replication(self,
                                                 get_relationship,
                                                 delete_relationship,
                                                 extend_target_volume,
                                                 create_relationship):
        fake_target = mock.Mock()
        rep_type = 'async'
        self.driver.replications[rep_type] = (
            self.driver.replication_factory(rep_type, fake_target))
        volume = self._create_volume()
        volume['replication_status'] = 'enabled'
        fake_target_vol = 'vol-target-id'
        get_relationship.return_value = {'aux_vdisk_name': fake_target_vol}
        with mock.patch.object(
                self.driver,
                '_get_volume_replicated_type_mirror') as mirror_type:
            mirror_type.return_value = 'async'
            self.driver.extend_volume(volume, '13')
            attrs = self.driver._assistant.get_vdisk_attributes(volume['name'])
            vol_size = int(attrs['capacity']) / units.Gi
            self.assertAlmostEqual(vol_size, 13)
            delete_relationship.assert_called_once_with(volume['name'])
            extend_target_volume.assert_called_once_with(fake_target_vol,
                                                         12)
            create_relationship.assert_called_once_with(volume,
                                                        fake_target_vol)

        self.driver.delete_volume(volume)

    def _instorage_mcs_extend_volume_replication_failover(self):
        volume = self._create_volume()
        volume['replication_status'] = 'failed-over'
        with mock.patch.object(
                self.driver,
                '_get_volume_replicated_type_mirror') as mirror_type:
            mirror_type.return_value = 'async'
            self.driver.extend_volume(volume, '13')
            attrs = self.driver._assistant.get_vdisk_attributes(volume['name'])
            vol_size = int(attrs['capacity']) / units.Gi
            self.assertAlmostEqual(vol_size, 13)

        self.driver.delete_volume(volume)

    def _check_loc_info(self, capabilities, expected):
        volume = self._create_volume()
        host = {'host': 'foo', 'capabilities': capabilities}
        ctxt = context.get_admin_context()
        moved, model_update = self.driver.migrate_volume(ctxt, volume, host)
        self.assertEqual(expected['moved'], moved)
        self.assertEqual(expected['model_update'], model_update)
        self.driver.delete_volume(volume)

    def test_instorage_mcs_migrate_bad_loc_info(self):
        self._check_loc_info({}, {'moved': False, 'model_update': None})
        cap = {'location_info': 'foo'}
        self._check_loc_info(cap, {'moved': False, 'model_update': None})
        cap = {'location_info': 'FooDriver:foo:bar'}
        self._check_loc_info(cap, {'moved': False, 'model_update': None})
        cap = {'location_info': 'InStorageMCSDriver:foo:bar'}
        self._check_loc_info(cap, {'moved': False, 'model_update': None})

    def test_instorage_mcs_volume_migrate(self):
        # Make sure we don't call migrate_volume_vdiskcopy
        self.driver.do_setup(None)
        loc = ('InStorageMCSDriver:' + self.driver._state['system_id'] +
               ':openstack2')
        cap = {'location_info': loc, 'extent_size': '256'}
        host = {'host': 'openstack@mcs#openstack2', 'capabilities': cap}
        ctxt = context.get_admin_context()
        volume = self._create_volume()
        volume['volume_type_id'] = None
        self.driver.migrate_volume(ctxt, volume, host)
        self._delete_volume(volume)

    def test_instorage_mcs_get_vdisk_params(self):
        self.driver.do_setup(None)
        fake_qos = {'qos:IOThrottling': '5000'}
        expected_qos = {'IOThrottling': 5000}
        fake_opts = self._get_default_opts()
        # The parameters retured should be the same to the default options,
        # if the QoS is empty.
        vol_type_empty_qos = self._create_volume_type_qos(True, None)
        type_id = vol_type_empty_qos['id']
        params = self.driver._get_vdisk_params(type_id,
                                               volume_type=vol_type_empty_qos,
                                               volume_metadata=None)
        self.assertEqual(fake_opts, params)
        volume_types.destroy(self.ctxt, type_id)

        # If the QoS is set via the qos association with the volume type,
        # qos value should be set in the retured parameters.
        vol_type_qos = self._create_volume_type_qos(False, fake_qos)
        type_id = vol_type_qos['id']
        # If type_id is not none and volume_type is none, it should work fine.
        params = self.driver._get_vdisk_params(type_id, volume_type=None,
                                               volume_metadata=None)
        self.assertEqual(expected_qos, params['qos'])
        # If type_id is not none and volume_type is not none, it should
        # work fine.
        params = self.driver._get_vdisk_params(type_id,
                                               volume_type=vol_type_qos,
                                               volume_metadata=None)
        self.assertEqual(expected_qos, params['qos'])
        # If type_id is none and volume_type is not none, it should work fine.
        params = self.driver._get_vdisk_params(None, volume_type=vol_type_qos,
                                               volume_metadata=None)
        self.assertEqual(expected_qos, params['qos'])
        # If both type_id and volume_type are none, no qos will be returned
        # in the parameter.
        params = self.driver._get_vdisk_params(None, volume_type=None,
                                               volume_metadata=None)
        self.assertIsNone(params['qos'])
        qos_spec = volume_types.get_volume_type_qos_specs(type_id)
        volume_types.destroy(self.ctxt, type_id)
        qos_specs.delete(self.ctxt, qos_spec['qos_specs']['id'])

        # If the QoS is set via the extra specs in the volume type,
        # qos value should be set in the retured parameters.
        vol_type_qos = self._create_volume_type_qos(True, fake_qos)
        type_id = vol_type_qos['id']
        # If type_id is not none and volume_type is none, it should work fine.
        params = self.driver._get_vdisk_params(type_id, volume_type=None,
                                               volume_metadata=None)
        self.assertEqual(expected_qos, params['qos'])
        # If type_id is not none and volume_type is not none,
        # it should work fine.
        params = self.driver._get_vdisk_params(type_id,
                                               volume_type=vol_type_qos,
                                               volume_metadata=None)
        self.assertEqual(expected_qos, params['qos'])
        # If type_id is none and volume_type is not none,
        # it should work fine.
        params = self.driver._get_vdisk_params(None,
                                               volume_type=vol_type_qos,
                                               volume_metadata=None)
        self.assertEqual(expected_qos, params['qos'])
        # If both type_id and volume_type are none, no qos will be returned
        # in the parameter.
        params = self.driver._get_vdisk_params(None, volume_type=None,
                                               volume_metadata=None)
        self.assertIsNone(params['qos'])
        volume_types.destroy(self.ctxt, type_id)

        # If the QoS is set in the volume metadata,
        # qos value should be set in the retured parameters.
        metadata = [{'key': 'qos:IOThrottling', 'value': 4000}]
        expected_qos_metadata = {'IOThrottling': 4000}
        params = self.driver._get_vdisk_params(None, volume_type=None,
                                               volume_metadata=metadata)
        self.assertEqual(expected_qos_metadata, params['qos'])

        # If the QoS is set both in the metadata and the volume type, the one
        # in the volume type will take effect.
        vol_type_qos = self._create_volume_type_qos(True, fake_qos)
        type_id = vol_type_qos['id']
        params = self.driver._get_vdisk_params(type_id, volume_type=None,
                                               volume_metadata=metadata)
        self.assertEqual(expected_qos, params['qos'])
        volume_types.destroy(self.ctxt, type_id)

        # If the QoS is set both via the qos association and the
        # extra specs, the one from the qos association will take effect.
        fake_qos_associate = {'qos:IOThrottling': '6000'}
        expected_qos_associate = {'IOThrottling': 6000}
        vol_type_qos = self._create_volume_type_qos_both(fake_qos,
                                                         fake_qos_associate)
        type_id = vol_type_qos['id']
        params = self.driver._get_vdisk_params(type_id, volume_type=None,
                                               volume_metadata=None)
        self.assertEqual(expected_qos_associate, params['qos'])
        qos_spec = volume_types.get_volume_type_qos_specs(type_id)
        volume_types.destroy(self.ctxt, type_id)
        qos_specs.delete(self.ctxt, qos_spec['qos_specs']['id'])

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'disable_vdisk_qos')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'update_vdisk_qos')
    def test_instorage_mcs_retype_no_copy(self, update_vdisk_qos,
                                          disable_vdisk_qos):
        self.driver.do_setup(None)
        loc = ('InStorageMCSDriver:' + self.driver._state['system_id'] +
               ':openstack')
        cap = {'location_info': loc, 'extent_size': '128'}
        self.driver._stats = {'location_info': loc}
        host = {'host': 'openstack@mcs#openstack', 'capabilities': cap}
        ctxt = context.get_admin_context()

        key_specs_old = {'intier': False, 'warning': 2, 'autoexpand': True}
        key_specs_new = {'intier': True, 'warning': 5, 'autoexpand': False}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        diff, _equal = volume_types.volume_types_diff(ctxt, old_type_ref['id'],
                                                      new_type_ref['id'])

        volume = self._generate_vol_info(None, None)
        old_type = objects.VolumeType.get_by_id(ctxt,
                                                old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host['host']
        new_type = objects.VolumeType.get_by_id(ctxt,
                                                new_type_ref['id'])

        self.driver.create_volume(volume)
        self.driver.retype(ctxt, volume, new_type, diff, host)
        attrs = self.driver._assistant.get_vdisk_attributes(volume['name'])
        self.assertEqual('on', attrs['in_tier'], 'Volume retype failed')
        self.assertEqual('5', attrs['warning'], 'Volume retype failed')
        self.assertEqual('off', attrs['autoexpand'], 'Volume retype failed')
        self.driver.delete_volume(volume)

        fake_opts = self._get_default_opts()
        fake_opts_old = self._get_default_opts()
        fake_opts_old['qos'] = {'IOThrottling': 4000}
        fake_opts_qos = self._get_default_opts()
        fake_opts_qos['qos'] = {'IOThrottling': 5000}
        self.driver.create_volume(volume)
        with mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                               '_get_vdisk_params') as get_vdisk_params:
            # If qos is empty for both the source and target volumes,
            # add_vdisk_qos and disable_vdisk_qos will not be called for
            # retype.
            get_vdisk_params.side_effect = [fake_opts, fake_opts]
            self.driver.retype(ctxt, volume, new_type, diff, host)
            self.assertFalse(update_vdisk_qos.called)
            self.assertFalse(disable_vdisk_qos.called)
            self.driver.delete_volume(volume)

        self.driver.create_volume(volume)
        update_vdisk_qos.reset_mock()
        with mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                               '_get_vdisk_params') as get_vdisk_params:
            # If qos is specified for both source and target volumes,
            # add_vdisk_qos will be called for retype, and disable_vdisk_qos
            # will not be called.
            get_vdisk_params.side_effect = [fake_opts_old, fake_opts_qos]
            self.driver.retype(ctxt, volume, new_type, diff, host)
            update_vdisk_qos.assert_called_with(volume['name'],
                                                fake_opts_qos['qos'])
            self.assertFalse(disable_vdisk_qos.called)
            self.driver.delete_volume(volume)

        self.driver.create_volume(volume)
        update_vdisk_qos.reset_mock()
        with mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                               '_get_vdisk_params') as get_vdisk_params:
            # If qos is empty for source and speficied for target volume,
            # add_vdisk_qos will be called for retype, and disable_vdisk_qos
            # will not be called.
            get_vdisk_params.side_effect = [fake_opts, fake_opts_qos]
            self.driver.retype(ctxt, volume, new_type, diff, host)
            update_vdisk_qos.assert_called_with(volume['name'],
                                                fake_opts_qos['qos'])
            self.assertFalse(disable_vdisk_qos.called)
            self.driver.delete_volume(volume)

        self.driver.create_volume(volume)
        update_vdisk_qos.reset_mock()
        with mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                               '_get_vdisk_params') as get_vdisk_params:
            # If qos is empty for target volume and specified for source
            # volume, add_vdisk_qos will not be called for retype, and
            # disable_vdisk_qos will be called.
            get_vdisk_params.side_effect = [fake_opts_qos, fake_opts]
            self.driver.retype(ctxt, volume, new_type, diff, host)
            self.assertFalse(update_vdisk_qos.called)
            disable_vdisk_qos.assert_called_with(volume['name'],
                                                 fake_opts_qos['qos'])
            self.driver.delete_volume(volume)

    def test_instorage_mcs_retype_only_change_iogrp(self):
        self.driver.do_setup(None)
        loc = ('InStorageMCSDriver:' + self.driver._state['system_id'] +
               ':openstack')
        cap = {'location_info': loc, 'extent_size': '128'}
        self.driver._stats = {'location_info': loc}
        host = {'host': 'openstack@mcs#openstack', 'capabilities': cap}
        ctxt = context.get_admin_context()

        key_specs_old = {'iogrp': 0}
        key_specs_new = {'iogrp': 1}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        diff, _equal = volume_types.volume_types_diff(ctxt, old_type_ref['id'],
                                                      new_type_ref['id'])

        volume = self._generate_vol_info(None, None)
        old_type = objects.VolumeType.get_by_id(ctxt,
                                                old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host['host']
        new_type = objects.VolumeType.get_by_id(ctxt,
                                                new_type_ref['id'])

        self.driver.create_volume(volume)
        attrs = self.driver._assistant.get_vdisk_attributes(volume['name'])
        self.assertEqual('0', attrs['IO_group_id'], 'Volume retype '
                                                    'failed')
        self.driver.retype(ctxt, volume, new_type, diff, host)
        attrs = self.driver._assistant.get_vdisk_attributes(volume['name'])
        self.assertEqual('1', attrs['IO_group_id'], 'Volume retype '
                         'failed')
        self.driver.delete_volume(volume)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'disable_vdisk_qos')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'update_vdisk_qos')
    def test_instorage_mcs_retype_need_copy(self, update_vdisk_qos,
                                            disable_vdisk_qos):
        self.driver.do_setup(None)
        loc = ('InStorageMCSDriver:' + self.driver._state['system_id'] +
               ':openstack')
        cap = {'location_info': loc, 'extent_size': '128'}
        self.driver._stats = {'location_info': loc}
        host = {'host': 'openstack@mcs#openstack', 'capabilities': cap}
        ctxt = context.get_admin_context()

        key_specs_old = {'compression': True, 'iogrp': 0}
        key_specs_new = {'compression': False, 'iogrp': 1}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        diff, _equal = volume_types.volume_types_diff(ctxt, old_type_ref['id'],
                                                      new_type_ref['id'])

        volume = self._generate_vol_info(None, None)
        old_type = objects.VolumeType.get_by_id(ctxt,
                                                old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host['host']
        new_type = objects.VolumeType.get_by_id(ctxt,
                                                new_type_ref['id'])

        self.driver.create_volume(volume)
        self.driver.retype(ctxt, volume, new_type, diff, host)
        attrs = self.driver._assistant.get_vdisk_attributes(volume['name'])
        self.assertEqual('no', attrs['compressed_copy'])
        self.assertEqual('1', attrs['IO_group_id'], 'Volume retype '
                         'failed')
        self.driver.delete_volume(volume)

        fake_opts = self._get_default_opts()
        fake_opts_old = self._get_default_opts()
        fake_opts_old['qos'] = {'IOThrottling': 4000}
        fake_opts_qos = self._get_default_opts()
        fake_opts_qos['qos'] = {'IOThrottling': 5000}
        self.driver.create_volume(volume)
        with mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                               '_get_vdisk_params') as get_vdisk_params:
            # If qos is empty for both the source and target volumes,
            # add_vdisk_qos and disable_vdisk_qos will not be called for
            # retype.
            get_vdisk_params.side_effect = [fake_opts, fake_opts]
            self.driver.retype(ctxt, volume, new_type, diff, host)
            self.assertFalse(update_vdisk_qos.called)
            self.assertFalse(disable_vdisk_qos.called)
            self.driver.delete_volume(volume)

        self.driver.create_volume(volume)
        update_vdisk_qos.reset_mock()
        with mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                               '_get_vdisk_params') as get_vdisk_params:
            # If qos is specified for both source and target volumes,
            # add_vdisk_qos will be called for retype, and disable_vdisk_qos
            # will not be called.
            get_vdisk_params.side_effect = [fake_opts_old, fake_opts_qos]
            self.driver.retype(ctxt, volume, new_type, diff, host)
            update_vdisk_qos.assert_called_with(volume['name'],
                                                fake_opts_qos['qos'])
            self.assertFalse(disable_vdisk_qos.called)
            self.driver.delete_volume(volume)

        self.driver.create_volume(volume)
        update_vdisk_qos.reset_mock()
        with mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                               '_get_vdisk_params') as get_vdisk_params:
            # If qos is empty for source and speficied for target volume,
            # add_vdisk_qos will be called for retype, and disable_vdisk_qos
            # will not be called.
            get_vdisk_params.side_effect = [fake_opts, fake_opts_qos]
            self.driver.retype(ctxt, volume, new_type, diff, host)
            update_vdisk_qos.assert_called_with(volume['name'],
                                                fake_opts_qos['qos'])
            self.assertFalse(disable_vdisk_qos.called)
            self.driver.delete_volume(volume)

        self.driver.create_volume(volume)
        update_vdisk_qos.reset_mock()
        with mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                               '_get_vdisk_params') as get_vdisk_params:
            # If qos is empty for target volume and specified for source
            # volume, add_vdisk_qos will not be called for retype, and
            # disable_vdisk_qos will be called.
            get_vdisk_params.side_effect = [fake_opts_qos, fake_opts]
            self.driver.retype(ctxt, volume, new_type, diff, host)
            self.assertFalse(update_vdisk_qos.called)
            disable_vdisk_qos.assert_called_with(volume['name'],
                                                 fake_opts_qos['qos'])
            self.driver.delete_volume(volume)

    def test_set_storage_code_level_success(self):
        res = self.driver._assistant.get_system_info()
        self.assertEqual((3, 1, 1, 0), res['code_level'],
                         'Get code level error')

    @mock.patch.object(instorage_common.InStorageAssistant, 'rename_vdisk')
    def test_instorage_update_migrated_volume(self, rename_vdisk):
        ctxt = testutils.get_test_admin_context()
        backend_volume = self._create_volume()
        volume = self._create_volume()
        model_update = self.driver.update_migrated_volume(ctxt, volume,
                                                          backend_volume,
                                                          'available')
        rename_vdisk.assert_called_once_with(backend_volume.name, volume.name)
        self.assertEqual({'_name_id': None}, model_update)

        rename_vdisk.reset_mock()
        rename_vdisk.side_effect = exception.VolumeBackendAPIException(data='')
        model_update = self.driver.update_migrated_volume(ctxt, volume,
                                                          backend_volume,
                                                          'available')
        self.assertEqual({'_name_id': backend_volume.id}, model_update)

        rename_vdisk.reset_mock()
        rename_vdisk.side_effect = exception.VolumeBackendAPIException(data='')
        model_update = self.driver.update_migrated_volume(ctxt, volume,
                                                          backend_volume,
                                                          'attached')
        self.assertEqual({'_name_id': backend_volume.id}, model_update)

    def test_instorage_vdisk_copy_ops(self):
        ctxt = testutils.get_test_admin_context()
        volume = self._create_volume()
        driver = self.driver
        dest_pool = volume_utils.extract_host(volume['host'], 'pool')
        new_ops = driver._assistant.add_vdisk_copy(volume['name'], dest_pool,
                                                   None, self.driver._state,
                                                   self.driver.configuration)
        self.driver._add_vdisk_copy_op(ctxt, volume, new_ops)
        self.assertEqual([new_ops],
                         self.driver._vdiskcopyops[volume.id]['copyops'],
                         'InStorage driver add vdisk copy error.')
        self.driver._check_volume_copy_ops()
        self.driver._rm_vdisk_copy_op(ctxt, volume.id, new_ops[0], new_ops[1])
        self.assertNotIn(volume.id, self.driver._vdiskcopyops,
                         'InStorage driver delete vdisk copy error')
        self._delete_volume(volume)

    def test_instorage_delete_with_vdisk_copy_ops(self):
        volume = self._create_volume()
        self.driver._vdiskcopyops = {volume['id']: {'name': volume.name,
                                                    'copyops': [('0', '1')]}}
        with mock.patch.object(self.driver, '_vdiskcopyops_loop'):
            self.assertIn(volume['id'], self.driver._vdiskcopyops)
            self.driver.delete_volume(volume)
            self.assertNotIn(volume['id'], self.driver._vdiskcopyops)

    def _create_volume_type_qos(self, extra_specs, fake_qos):
        # Generate a QoS volume type for volume.
        if extra_specs:
            spec = fake_qos
            type_ref = volume_types.create(self.ctxt, "qos_extra_specs", spec)
        else:
            type_ref = volume_types.create(self.ctxt, "qos_associate", None)
            if fake_qos:
                qos_ref = qos_specs.create(self.ctxt, 'qos-specs', fake_qos)
                qos_specs.associate_qos_with_type(self.ctxt, qos_ref['id'],
                                                  type_ref['id'])

        qos_type = volume_types.get_volume_type(self.ctxt, type_ref['id'])
        return qos_type

    def _create_volume_type_qos_both(self, fake_qos, fake_qos_associate):
        type_ref = volume_types.create(self.ctxt, "qos_extra_specs", fake_qos)
        qos_ref = qos_specs.create(self.ctxt, 'qos-specs', fake_qos_associate)
        qos_specs.associate_qos_with_type(self.ctxt, qos_ref['id'],
                                          type_ref['id'])
        qos_type = volume_types.get_volume_type(self.ctxt, type_ref['id'])
        return qos_type

    def _create_replication_volume_type(self, enable):
        # Generate a volume type for volume repliation.
        if enable:
            spec = {'capabilities:replication': '<is> True'}
            type_ref = volume_types.create(self.ctxt, "replication_1", spec)
        else:
            spec = {'capabilities:replication': '<is> False'}
            type_ref = volume_types.create(self.ctxt, "replication_2", spec)

        replication_type = objects.VolumeType.get_by_id(self.ctxt,
                                                        type_ref['id'])
        return replication_type

    def _create_consistency_group_volume_type(self):
        # Generate a volume type for volume consistencygroup.
        spec = {'capabilities:consistencygroup_support': '<is> True'}
        type_ref = volume_types.create(self.ctxt, "cg", spec)

        cg_type = volume_types.get_volume_type(self.ctxt, type_ref['id'])

        return cg_type

    def _create_group_volume_type(self):
        # Generate a volume type for volume group.
        spec = {'capabilities:group_support': '<is> True'}
        type_ref = volume_types.create(self.ctxt, "group", spec)

        group_type = volume_types.get_volume_type(self.ctxt, type_ref['id'])

        return group_type

    def _get_vdisk_uid(self, vdisk_name):
        """Return vdisk_UID for given vdisk.

        Given a vdisk by name, performs an lvdisk command that extracts
        the vdisk_UID parameter and returns it.
        Returns None if the specified vdisk does not exist.
        """
        vdisk_properties, _err = self.sim._cmd_lsvdisk(obj=vdisk_name,
                                                       delim='!')

        # Iterate through each row until we find the vdisk_UID entry
        for row in vdisk_properties.split('\n'):
            words = row.split('!')
            if words[0] == 'vdisk_UID':
                return words[1]
        return None

    def _create_volume_and_return_uid(self, volume_name):
        """Creates a volume and returns its UID.

        Creates a volume with the specified name, and returns the UID that
        the InStorage controller allocated for it.  We do this by executing a
        create_volume and then calling into the simulator to perform an
        lsvdisk directly.
        """
        volume = self._generate_vol_info(None, None)
        self.driver.create_volume(volume)

        return (volume, self._get_vdisk_uid(volume['name']))

    def test_manage_existing_get_size_bad_ref(self):
        """Error on manage with bad reference.

        This test case attempts to manage an existing volume but passes in
        a bad reference that the InStorage driver doesn't understand.  We
        expect an exception to be raised.
        """
        volume = self._generate_vol_info(None, None)
        ref = {}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, volume, ref)

    def test_manage_existing_get_size_bad_uid(self):
        """Error when the specified UUID does not exist."""
        volume = self._generate_vol_info(None, None)
        ref = {'source-id': 'bad_uid'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, volume, ref)
        pass

    def test_manage_existing_get_size_bad_name(self):
        """Error when the specified name does not exist."""
        volume = self._generate_vol_info(None, None)
        ref = {'source-name': 'bad_name'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, volume, ref)

    def test_manage_existing_bad_ref(self):
        """Error on manage with bad reference.

        This test case attempts to manage an existing volume but passes in
        a bad reference that the InStorage driver doesn't understand.  We
        expect an exception to be raised.
        """

        # Error when neither UUID nor name are specified.
        volume = self._generate_vol_info(None, None)
        ref = {}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, volume, ref)

        # Error when the specified UUID does not exist.
        volume = self._generate_vol_info(None, None)
        ref = {'source-id': 'bad_uid'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, volume, ref)

        # Error when the specified name does not exist.
        volume = self._generate_vol_info(None, None)
        ref = {'source-name': 'bad_name'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing, volume, ref)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_vdisk_copy_attrs')
    def test_manage_existing_mismatch(self,
                                      get_vdisk_copy_attrs):
        ctxt = testutils.get_test_admin_context()
        _volume, uid = self._create_volume_and_return_uid('manage_test')

        opts = {'rsize': -1}
        type_thick_ref = volume_types.create(ctxt, 'testtype1', opts)

        opts = {'rsize': 2}
        type_thin_ref = volume_types.create(ctxt, 'testtype2', opts)

        opts = {'rsize': 2, 'compression': True}
        type_comp_ref = volume_types.create(ctxt, 'testtype3', opts)

        opts = {'rsize': -1, 'iogrp': 1}
        type_iogrp_ref = volume_types.create(ctxt, 'testtype4', opts)

        new_volume = self._generate_vol_info(None, None)
        ref = {'source-name': _volume['name']}

        fake_copy_thin = self._get_default_opts()
        fake_copy_thin['autoexpand'] = 'on'

        fake_copy_comp = self._get_default_opts()
        fake_copy_comp['autoexpand'] = 'on'
        fake_copy_comp['compressed_copy'] = 'yes'

        fake_copy_thick = self._get_default_opts()
        fake_copy_thick['autoexpand'] = ''
        fake_copy_thick['compressed_copy'] = 'no'

        fake_copy_no_comp = self._get_default_opts()
        fake_copy_no_comp['compressed_copy'] = 'no'

        valid_iogrp = self.driver._state['available_iogrps']
        self.driver._state['available_iogrps'] = [9999]
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)
        self.driver._state['available_iogrps'] = valid_iogrp

        get_vdisk_copy_attrs.side_effect = [fake_copy_thin,
                                            fake_copy_thick,
                                            fake_copy_no_comp,
                                            fake_copy_comp,
                                            fake_copy_thick,
                                            fake_copy_thick
                                            ]
        new_volume['volume_type_id'] = type_thick_ref['id']
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)

        new_volume['volume_type_id'] = type_thin_ref['id']
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)

        new_volume['volume_type_id'] = type_comp_ref['id']
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)

        new_volume['volume_type_id'] = type_thin_ref['id']
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)

        new_volume['volume_type_id'] = type_iogrp_ref['id']
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)

        new_volume['volume_type_id'] = type_thick_ref['id']
        no_exist_pool = 'i-dont-exist-%s' % 56789
        new_volume['host'] = 'openstack@mcs#%s' % no_exist_pool
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)

        self._reset_flags()
        volume_types.destroy(ctxt, type_thick_ref['id'])
        volume_types.destroy(ctxt, type_comp_ref['id'])
        volume_types.destroy(ctxt, type_iogrp_ref['id'])

    def test_manage_existing_good_uid_not_mapped(self):
        """Tests managing a volume with no mappings.

        This test case attempts to manage an existing volume by UID, and
        we expect it to succeed.  We verify that the backend volume was
        renamed to have the name of the Cinder volume that we asked for it to
        be associated with.
        """

        # Create a volume as a way of getting a vdisk created, and find out the
        # UID of that vdisk.
        _volume, uid = self._create_volume_and_return_uid('manage_test')

        # Descriptor of the Cinder volume that we want to own the vdisk
        # referenced by uid.
        new_volume = self._generate_vol_info(None, None)

        # Submit the request to manage it.
        ref = {'source-id': uid}
        size = self.driver.manage_existing_get_size(new_volume, ref)
        self.assertEqual(10, size)
        self.driver.manage_existing(new_volume, ref)

        # Assert that there is a disk named after the new volume that has the
        # ID that we passed in, indicating that the disk has been renamed.
        uid_of_new_volume = self._get_vdisk_uid(new_volume['name'])
        self.assertEqual(uid, uid_of_new_volume)

    def test_manage_existing_good_name_not_mapped(self):
        """Tests managing a volume with no mappings.

        This test case attempts to manage an existing volume by name, and
        we expect it to succeed.  We verify that the backend volume was
        renamed to have the name of the Cinder volume that we asked for it to
        be associated with.
        """

        # Create a volume as a way of getting a vdisk created, and find out the
        # UID of that vdisk.
        _volume, uid = self._create_volume_and_return_uid('manage_test')

        # Descriptor of the Cinder volume that we want to own the vdisk
        # referenced by uid.
        new_volume = self._generate_vol_info(None, None)

        # Submit the request to manage it.
        ref = {'source-name': _volume['name']}
        size = self.driver.manage_existing_get_size(new_volume, ref)
        self.assertEqual(10, size)
        self.driver.manage_existing(new_volume, ref)

        # Assert that there is a disk named after the new volume that has the
        # ID that we passed in, indicating that the disk has been renamed.
        uid_of_new_volume = self._get_vdisk_uid(new_volume['name'])
        self.assertEqual(uid, uid_of_new_volume)

    def test_manage_existing_mapped(self):
        """Tests managing a mapped volume with no override.

        This test case attempts to manage an existing volume by UID, but
        the volume is mapped to a host, so we expect to see an exception
        raised.
        """
        # Create a volume as a way of getting a vdisk created, and find out the
        # UUID of that vdisk.
        # Set replication target.
        volume, uid = self._create_volume_and_return_uid('manage_test')

        # Map a host to the disk
        conn = {'initiator': u'unicode:initiator3',
                'ip': '10.10.10.12',
                'host': u'unicode.foo.bar.baz'}
        self.driver.initialize_connection(volume, conn)

        # Descriptor of the Cinder volume that we want to own the vdisk
        # referenced by uid.
        volume = self._generate_vol_info(None, None)
        ref = {'source-id': uid}

        # Attempt to manage this disk, and except an exception beause the
        # volume is already mapped.
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, volume, ref)

        ref = {'source-name': volume['name']}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, volume, ref)

    def test_manage_existing_good_uid_mapped_with_override(self):
        """Tests managing a mapped volume with override.

        This test case attempts to manage an existing volume by UID, when it
        already mapped to a host, but the ref specifies that this is OK.
        We verify that the backend volume was renamed to have the name of the
        Cinder volume that we asked for it to be associated with.
        """
        # Create a volume as a way of getting a vdisk created, and find out the
        # UUID of that vdisk.
        volume, uid = self._create_volume_and_return_uid('manage_test')

        # Map a host to the disk
        conn = {'initiator': u'unicode:initiator3',
                'ip': '10.10.10.12',
                'host': u'unicode.foo.bar.baz'}
        self.driver.initialize_connection(volume, conn)

        # Descriptor of the Cinder volume that we want to own the vdisk
        # referenced by uid.
        new_volume = self._generate_vol_info(None, None)

        # Submit the request to manage it, specifying that it is OK to
        # manage a volume that is already attached.
        ref = {'source-id': uid, 'manage_if_in_use': True}
        size = self.driver.manage_existing_get_size(new_volume, ref)
        self.assertEqual(10, size)
        self.driver.manage_existing(new_volume, ref)

        # Assert that there is a disk named after the new volume that has the
        # ID that we passed in, indicating that the disk has been renamed.
        uid_of_new_volume = self._get_vdisk_uid(new_volume['name'])
        self.assertEqual(uid, uid_of_new_volume)

    def test_manage_existing_good_name_mapped_with_override(self):
        """Tests managing a mapped volume with override.

        This test case attempts to manage an existing volume by name, when it
        already mapped to a host, but the ref specifies that this is OK.
        We verify that the backend volume was renamed to have the name of the
        Cinder volume that we asked for it to be associated with.
        """
        # Create a volume as a way of getting a vdisk created, and find out the
        # UUID of that vdisk.
        volume, uid = self._create_volume_and_return_uid('manage_test')

        # Map a host to the disk
        conn = {'initiator': u'unicode:initiator3',
                'ip': '10.10.10.12',
                'host': u'unicode.foo.bar.baz'}
        self.driver.initialize_connection(volume, conn)

        # Descriptor of the Cinder volume that we want to own the vdisk
        # referenced by uid.
        new_volume = self._generate_vol_info(None, None)

        # Submit the request to manage it, specifying that it is OK to
        # manage a volume that is already attached.
        ref = {'source-name': volume['name'], 'manage_if_in_use': True}
        size = self.driver.manage_existing_get_size(new_volume, ref)
        self.assertEqual(10, size)
        self.driver.manage_existing(new_volume, ref)

        # Assert that there is a disk named after the new volume that has the
        # ID that we passed in, indicating that the disk has been renamed.
        uid_of_new_volume = self._get_vdisk_uid(new_volume['name'])
        self.assertEqual(uid, uid_of_new_volume)
