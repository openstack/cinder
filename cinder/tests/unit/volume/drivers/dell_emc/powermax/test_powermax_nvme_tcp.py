# Copyright (c) 2020 Dell Inc. or its subsidiaries.
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

from copy import deepcopy
from unittest import mock

from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_data as tpd)
from cinder.tests.unit.volume.drivers.dell_emc.powermax import (
    powermax_fake_objects as tpfo)
from cinder.volume.drivers.dell_emc.powermax import nvme_tcp
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume import volume_utils


class PowerMaxNVMeTCPTest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxNVMeTCPTest, self).setUp()
        self.mock_object(volume_utils, 'get_max_over_subscription_ratio')
        self.configuration = tpfo.FakeConfiguration(
            None, 'NVMeTests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_i])
        self.mock_object(rest.PowerMaxRest, '_establish_rest_session',
                         return_value=tpfo.FakeRequestsSession())
        driver = (nvme_tcp.
                  PowerMaxNVMETCPDriver(configuration=self.configuration))
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.utils = self.common.utils
        self.rest = self.common.rest
        self.mock_object(
            self.utils, 'get_volumetype_extra_specs',
            return_value=deepcopy(self.data.vol_type_extra_specs))

    def test_create_volume(self):
        with mock.patch.object(self.common, 'create_volume') as mock_create:
            self.driver.create_volume(self.data.test_volume)
            mock_create.assert_called_once_with(self.data.test_volume)

    def test_create_volume_from_snapshot(self):
        volume = self.data.test_clone_volume
        snapshot = self.data.test_snapshot
        with mock.patch.object(
                self.common, 'create_volume_from_snapshot') as mock_create:
            self.driver.create_volume_from_snapshot(volume, snapshot)
            mock_create.assert_called_once_with(volume, snapshot)

    def test_create_cloned_volume(self):
        volume = self.data.test_clone_volume
        src_volume = self.data.test_volume
        with mock.patch.object(
                self.common, 'create_cloned_volume') as mock_create:
            self.driver.create_cloned_volume(volume, src_volume)
            mock_create.assert_called_once_with(volume, src_volume)

    def test_delete_volume(self):
        with mock.patch.object(self.common, 'delete_volume') as mock_delete:
            self.driver.delete_volume(self.data.test_volume)
            mock_delete.assert_called_once_with(self.data.test_volume)

    def test_create_snapshot(self):
        with mock.patch.object(self.common, 'create_snapshot') as mock_create:
            self.driver.create_snapshot(self.data.test_snapshot)
            mock_create.assert_called_once_with(
                self.data.test_snapshot, self.data.test_snapshot.volume)

    def test_delete_snapshot(self):
        with mock.patch.object(self.common, 'delete_snapshot') as mock_delete:
            self.driver.delete_snapshot(self.data.test_snapshot)
            mock_delete.assert_called_once_with(
                self.data.test_snapshot, self.data.test_snapshot.volume)

    def test_update_volume_stats(self):
        with mock.patch.object(self.common, 'update_volume_stats',
                               return_value={}) as mock_update:
            self.driver._update_volume_stats()
            mock_update.assert_called_once_with()

    def test_check_for_setup_error_with_valid_versions(self):
        with mock.patch.object(
                self.common.rest, 'get_uni_version',
                return_value=('10.1.0.6', '101')) as mock_uni_version:
            with mock.patch.object(
                    self.common.rest, 'get_vmax_model',
                    return_value=('Powermax_2500')) as mock_pmax_version:
                self.driver.check_for_setup_error()
                mock_uni_version.assert_called_once()
                mock_pmax_version.assert_called_once()

    def test_check_for_setup_error_with_valid_powermax_850_version(self):
        with mock.patch.object(
                self.common.rest, 'get_uni_version',
                return_value=('10.1.0.6', '101')) as mock_uni_version:
            with mock.patch.object(
                    self.common.rest, 'get_vmax_model',
                    return_value=('Powermax_8500')) as mock_pmax_version:
                self.driver.check_for_setup_error()
                mock_uni_version.assert_called_once()
                mock_pmax_version.assert_called_once()

    def test_check_for_setup_error_exception(self):
        with mock.patch.object(
                self.common.rest, 'get_uni_version',
                return_value=('9.2.0.0', '92')) as mock_rest:
            with mock.patch.object(
                    self.common.rest, 'get_vmax_model',
                    return_value=('Powermax_2000')) as mock_pmax_version:
                mock_rest.assert_not_called()
                mock_pmax_version.assert_not_called()
                self.assertRaises(
                    exception.InvalidConfigurationValue,
                    self.driver.check_for_setup_error)

    def test_check_for_setup_error_exception_with_invalid_powermax_version(
            self):
        with mock.patch.object(
                self.common.rest, 'get_uni_version',
                return_value=('10.1.0.6', '101')) as mock_uni_version:
            with mock.patch.object(
                    self.common.rest, 'get_vmax_model',
                    return_value=('Powermax_2000')) as mock_pmax_version:
                mock_uni_version.assert_not_called()
                mock_pmax_version.assert_not_called()
                self.assertRaises(
                    exception.InvalidConfigurationValue,
                    self.driver.check_for_setup_error)

    def test_check_for_setup_error_exception_with_invalid_powermax_version_2(
            self):
        with mock.patch.object(
                self.common.rest, 'get_uni_version',
                return_value=('10.1.0.6', '101')) as mock_uni_version:
            with mock.patch.object(
                    self.common.rest, 'get_vmax_model',
                    return_value=('Powermax_8000')) as mock_pmax_version:
                mock_uni_version.assert_not_called()
                mock_pmax_version.assert_not_called()
                self.assertRaises(
                    exception.InvalidConfigurationValue,
                    self.driver.check_for_setup_error)

    def test_check_for_setup_error_exception_without_unisphere_version(self):
        with mock.patch.object(
                self.common.rest, 'get_uni_version',
                return_value=(None, None)) as mock_rest:
            with mock.patch.object(
                    self.common.rest, 'get_vmax_model',
                    return_value=('Powermax_8500')) as mock_pmax_version:
                mock_rest.assert_not_called()
                mock_pmax_version.assert_not_called()
                self.assertRaises(
                    exception.InvalidConfigurationValue,
                    self.driver.check_for_setup_error)

    def test_check_for_setup_error_exception_without_powermax_version(self):
        with mock.patch.object(
                self.common.rest, 'get_uni_version',
                return_value=('10.1.0.6', '101')) as mock_rest:
            with mock.patch.object(
                    self.common.rest, 'get_vmax_model',
                    return_value=None) as mock_pmax_version:
                mock_rest.assert_not_called()
                mock_pmax_version.assert_not_called()
                self.assertRaises(
                    exception.InvalidConfigurationValue,
                    self.driver.check_for_setup_error)

    def test_ensure_export(self):
        self.driver.ensure_export('context', 'volume')

    def test_create_export(self):
        self.driver.create_export('context', 'volume', 'connector')

    def test_remove_export(self):
        self.driver.remove_export('context', 'volume')

    def test_check_for_export(self):
        self.driver.check_for_export('context', 'volume_id')

    def test_extend_volume(self):
        with mock.patch.object(self.common, 'extend_volume') as mock_extend:
            self.driver.extend_volume(self.data.test_volume, '8')
            mock_extend.assert_called_once_with(self.data.test_volume, '8')

    def test_manage_existing(self):
        with mock.patch.object(self.common, 'manage_existing',
                               return_value={}) as mock_manage:
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing(self.data.test_volume, external_ref)
            mock_manage.assert_called_once_with(
                self.data.test_volume, external_ref)

    def test_manage_existing_get_size(self):
        with mock.patch.object(self.common, 'manage_existing_get_size',
                               return_value='1') as mock_manage:
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing_get_size(
                self.data.test_volume, external_ref)
            mock_manage.assert_called_once_with(
                self.data.test_volume, external_ref)

    def test_unmanage_volume(self):
        with mock.patch.object(self.common, 'unmanage',
                               return_value={}) as mock_unmanage:
            self.driver.unmanage(self.data.test_volume)
            mock_unmanage.assert_called_once_with(
                self.data.test_volume)

    def test_retype(self):
        host = {'host': self.data.new_host}
        new_type = {'extra_specs': {}}
        with mock.patch.object(self.common, 'retype',
                               return_value=True) as mck_retype:
            self.driver.retype({}, self.data.test_volume, new_type, '', host)
            mck_retype.assert_called_once_with(
                self.data.test_volume, new_type, host)

    def test_failover_host(self):
        with mock.patch.object(
                self.common, 'failover',
                return_value=(self.data.remote_array, [], [])) as mock_fo:
            self.driver.failover_host(self.data.ctx, [self.data.test_volume])
            mock_fo.assert_called_once_with([self.data.test_volume], None,
                                            None)

    def test_enable_replication(self):
        with mock.patch.object(
                self.common, 'enable_replication') as mock_er:
            self.driver.enable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_er.assert_called_once()

    def test_disable_replication(self):
        with mock.patch.object(
                self.common, 'disable_replication') as mock_dr:
            self.driver.disable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_dr.assert_called_once()

    def test_failover_replication(self):
        with mock.patch.object(
                self.common, 'failover_replication') as mock_fo:
            self.driver.failover_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_fo.assert_called_once()

    def test_initialize_connection(self):
        with (mock.patch.object(
                self.common, 'initialize_connection',
                return_value=self.data.nvme_tcp_device_info)
                as mock_initialize):
            with mock.patch.object(
                    self.driver, '_populate_data') as mock_populate:
                self.driver.initialize_connection(
                    self.data.test_volume, self.data.connector)
                mock_initialize.assert_called_once_with(
                    self.data.test_volume, self.data.connector)
                mock_populate.assert_called_once_with(
                    self.data.nvme_tcp_device_info)

    def test_terminate_connection(self):
        with mock.patch.object(
                self.common, 'terminate_connection') as mock_terminate:
            self.driver.terminate_connection(
                self.data.test_volume, self.data.connector)
            mock_terminate.assert_called_once_with(
                self.data.test_volume, self.data.connector)

    def test_manage_existing_snapshot(self):
        with mock.patch.object(self.common, 'manage_existing_snapshot',
                               return_value={}) as mock_manage:
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing_snapshot(
                self.data.test_snapshot_manage,
                external_ref)
            mock_manage.assert_called_once_with(
                self.data.test_snapshot_manage,
                external_ref)

    def test_manage_existing_snapshot_get_size(self):
        with mock.patch.object(self.common,
                               'manage_existing_snapshot_get_size',
                               return_value='1') as mock_manage:
            external_ref = {u'source-name': u'00002'}
            self.driver.manage_existing_snapshot_get_size(
                self.data.test_snapshot_manage, external_ref)
            mock_manage.assert_called_once_with(
                self.data.test_snapshot_manage)

    def test_unmanage_snapshot(self):
        with mock.patch.object(self.common, 'unmanage_snapshot',
                               return_value={}) as mock_unmanage:
            self.driver.unmanage_snapshot(self.data.test_snapshot_manage)
            mock_unmanage.assert_called_once_with(
                self.data.test_snapshot_manage)

    def test_get_manageable_volumes(self):
        cinder_volumes = marker = limit = offset = sort_keys = sort_dirs = None
        with mock.patch.object(self.common, 'get_manageable_volumes',
                               return_value={}) as mock_manage:
            self.driver.get_manageable_volumes(cinder_volumes,
                                               marker, limit,
                                               offset, sort_keys,
                                               sort_dirs)
            mock_manage.assert_called_once_with(
                marker, limit,
                offset, sort_keys,
                sort_dirs)

    def test_get_manageable_snapshots(self):
        cinder_snapshots = marker = limit = offset = \
            sort_keys = sort_dirs = None
        with mock.patch.object(self.common, 'get_manageable_snapshots',
                               return_value={}) as mock_manage:
            self.driver.get_manageable_snapshots(cinder_snapshots,
                                                 marker, limit,
                                                 offset, sort_keys,
                                                 sort_dirs)
            mock_manage.assert_called_once_with(
                marker, limit,
                offset, sort_keys,
                sort_dirs)

    def test_create_group(self):
        context = {'dummy_key': 'dummy_value'}
        group = 'dummy_group'
        with mock.patch.object(self.common, 'create_group',
                               return_value={}) as mock_group:
            self.driver.create_group(context, group)
            mock_group.assert_called_once_with(
                context, group)

    def test_delete_group(self):
        context = {'dummy_key': 'dummy_value'}
        group = 'dummy_group'
        volumes = ['dummy_volume']
        with mock.patch.object(self.common, 'delete_group',
                               return_value={}) as mock_group:
            self.driver.delete_group(context, group, volumes)
            mock_group.assert_called_once_with(
                context, group, volumes)

    def test_create_group_snapshot(self):
        context = {'dummy_key': 'dummy_value'}
        group_snapshot = 'dummy_group_snapshot'
        snapshots = ['dummy_snapshot']
        with mock.patch.object(self.common, 'create_group_snapshot',
                               return_value={}) as mock_group:
            self.driver.create_group_snapshot(context,
                                              group_snapshot,
                                              snapshots)
            mock_group.assert_called_once_with(
                context, group_snapshot, snapshots)

    def test_delete_group_snapshot(self):
        context = {'dummy_key': 'dummy_value'}
        group_snapshot = 'dummy_group_snapshot'
        snapshots = ['dummy_snapshot']
        with mock.patch.object(self.common, 'delete_group_snapshot',
                               return_value={}) as mock_group:
            self.driver.delete_group_snapshot(context,
                                              group_snapshot,
                                              snapshots)
            mock_group.assert_called_once_with(
                context, group_snapshot, snapshots)

    def test_update_group(self):
        context = {'dummy_key': 'dummy_value'}
        group = 'dummy_group'
        add_volumes = ['dummy_add_volume']
        remove_volumes = ['dummy_remove_volume']
        with mock.patch.object(self.common, 'update_group',
                               return_value={}) as mock_group:
            self.driver.update_group(context,
                                     group,
                                     add_volumes,
                                     remove_volumes)
            mock_group.assert_called_once_with(
                group, add_volumes, remove_volumes)

    def test_create_group_from_src(self):
        context = {'dummy_key': 'dummy_value'}
        group = 'dummy_group'
        group_snapshot = 'dummy_group_snapshot'
        snapshots = ['dummy_snapshot']
        volumes = ['dummy_add_volume']
        source_group = 'dummy_source_group'
        source_volumes = ['dummy_source_volume']
        with mock.patch.object(self.common, 'create_group_from_src',
                               return_value={}) as mock_group:
            self.driver.create_group_from_src(context, group, volumes,
                                              group_snapshot, snapshots,
                                              source_group, source_volumes)
            mock_group.assert_called_once_with(
                context, group, volumes,
                group_snapshot, snapshots,
                source_group, source_volumes)
