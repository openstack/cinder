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
from cinder.volume.drivers.dell_emc.powermax import iscsi
from cinder.volume.drivers.dell_emc.powermax import rest
from cinder.volume import volume_utils


class PowerMaxISCSITest(test.TestCase):
    def setUp(self):
        self.data = tpd.PowerMaxData()
        super(PowerMaxISCSITest, self).setUp()
        volume_utils.get_max_over_subscription_ratio = mock.Mock()
        configuration = tpfo.FakeConfiguration(
            None, 'ISCSITests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_api_port=8443,
            powermax_port_groups=[self.data.port_group_name_i])
        rest.PowerMaxRest._establish_rest_session = mock.Mock(
            return_value=tpfo.FakeRequestsSession())
        driver = iscsi.PowerMaxISCSIDriver(configuration=configuration)
        self.driver = driver
        self.common = self.driver.common
        self.masking = self.common.masking
        self.utils = self.common.utils
        self.utils.get_volumetype_extra_specs = (
            mock.Mock(return_value=self.data.vol_type_extra_specs))

    def test_create_volume(self):
        with mock.patch.object(self.common, 'create_volume') as mock_create:
            self.driver.create_volume(self.data.test_volume)
            mock_create.assert_called_once_with(
                self.data.test_volume)

    def test_create_volume_from_snapshot(self):
        volume = self.data.test_clone_volume
        snapshot = self.data.test_snapshot
        with mock.patch.object(
                self.common, 'create_volume_from_snapshot') as mock_create:
            self.driver.create_volume_from_snapshot(volume, snapshot)
            mock_create.assert_called_once_with(
                volume, snapshot)

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
            mock_delete.assert_called_once_with(
                self.data.test_volume)

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

    def test_initialize_connection(self):
        phys_port = '%(dir)s:%(port)s' % {'dir': self.data.iscsi_dir,
                                          'port': self.data.iscsi_port}
        ref_dict = {'maskingview': self.data.masking_view_name_f,
                    'array': self.data.array, 'hostlunid': 3,
                    'device_id': self.data.device_id,
                    'ip_and_iqn': [{'ip': self.data.ip,
                                    'iqn': self.data.initiator,
                                    'physical_port': phys_port}],
                    'is_multipath': False}
        with mock.patch.object(self.driver, 'get_iscsi_dict') as mock_get:
            with mock.patch.object(
                self.common, 'get_port_group_from_masking_view',
                    return_value=self.data.port_group_name_i):
                self.driver.initialize_connection(self.data.test_volume,
                                                  self.data.connector)
                mock_get.assert_called_once_with(
                    ref_dict, self.data.test_volume)

    def test_get_iscsi_dict_success(self):
        ip_and_iqn = self.common._find_ip_and_iqns(
            self.data.array, self.data.port_group_name_i)
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        volume = self.data.test_volume
        device_info = self.data.iscsi_device_info
        ref_data = {'driver_volume_type': 'iscsi', 'data': {}}
        with mock.patch.object(
                self.driver, 'vmax_get_iscsi_properties',
                return_value={}) as mock_get:
            data = self.driver.get_iscsi_dict(device_info, volume)
            self.assertEqual(ref_data, data)
            mock_get.assert_called_once_with(
                self.data.array, volume, ip_and_iqn, True, host_lun_id, None,
                None)

    def test_get_iscsi_dict_exception(self):
        device_info = {'ip_and_iqn': ''}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.get_iscsi_dict,
                          device_info, self.data.test_volume)

    def test_get_iscsi_dict_metro(self):
        ip_and_iqn = self.common._find_ip_and_iqns(
            self.data.array, self.data.port_group_name_i)
        host_lun_id = self.data.iscsi_device_info_metro['hostlunid']
        volume = self.data.test_volume
        device_info = self.data.iscsi_device_info_metro
        ref_data = {'driver_volume_type': 'iscsi', 'data': {}}
        with mock.patch.object(self.driver, 'vmax_get_iscsi_properties',
                               return_value={}) as mock_get:
            data = self.driver.get_iscsi_dict(device_info, volume)
            self.assertEqual(ref_data, data)
            mock_get.assert_called_once_with(
                self.data.array, volume, ip_and_iqn, True, host_lun_id,
                self.data.iscsi_device_info_metro['metro_ip_and_iqn'],
                self.data.iscsi_device_info_metro['metro_hostlunid'])

    def test_vmax_get_iscsi_properties_one_target_no_auth(self):
        vol = deepcopy(self.data.test_volume)
        ip_and_iqn = self.common._find_ip_and_iqns(
            self.data.array, self.data.port_group_name_i)
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        ref_properties = {
            'target_discovered': True,
            'target_iqn': ip_and_iqn[0]['iqn'].split(',')[0],
            'target_portal': ip_and_iqn[0]['ip'] + ':3260',
            'target_lun': host_lun_id,
            'volume_id': self.data.test_volume.id}
        iscsi_properties = self.driver.vmax_get_iscsi_properties(
            self.data.array, vol, ip_and_iqn, True, host_lun_id, [], None)
        self.assertEqual(type(ref_properties), type(iscsi_properties))
        self.assertEqual(ref_properties, iscsi_properties)

    def test_vmax_get_iscsi_properties_multiple_targets_random_select(self):
        ip_and_iqn = [{'ip': self.data.ip, 'iqn': self.data.initiator},
                      {'ip': self.data.ip2, 'iqn': self.data.iqn}]
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        iscsi_properties = self.driver.vmax_get_iscsi_properties(
            self.data.array, self.data.test_volume, ip_and_iqn, True,
            host_lun_id, [], None)
        iscsi_tgt_iqn = iscsi_properties.get('target_iqn')
        iscsi_tgt_portal = iscsi_properties.get('target_portal')
        self.assertIn(iscsi_tgt_iqn, [self.data.initiator, self.data.iqn])
        self.assertIn(iscsi_tgt_portal, [self.data.ip + ":3260",
                                         self.data.ip2 + ":3260"])
        for ip_iqn in ip_and_iqn:
            if ip_iqn['ip'] + ":3260" == iscsi_tgt_portal:
                self.assertEqual(iscsi_tgt_iqn, ip_iqn.get('iqn'))

    def test_vmax_get_iscsi_properties_multiple_targets_load_balance(self):
        ip_and_iqn = [
            {'ip': self.data.ip, 'iqn': self.data.initiator,
             'physical_port': self.data.perf_ports[0]},
            {'ip': self.data.ip2, 'iqn': self.data.iqn,
             'physical_port': self.data.perf_ports[1]}]
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        self.driver.performance.config = self.data.performance_config
        ref_tgt_map = {}
        for tgt in ip_and_iqn:
            ref_tgt_map.update({
                tgt['physical_port']: {'ip': tgt['ip'],
                                       'iqn': tgt['iqn']}})

        with mock.patch.object(
                self.driver.performance, 'process_port_load',
                side_effect=(
                    self.driver.performance.process_port_load)) as mck_p:
            iscsi_properties = self.driver.vmax_get_iscsi_properties(
                self.data.array, self.data.test_volume, ip_and_iqn, False,
                host_lun_id, None, None)
            mck_p.assert_called_once_with(self.data.array, ref_tgt_map.keys())
            iscsi_tgt_iqn = iscsi_properties.get('target_iqn')
            iscsi_tgt_portal = iscsi_properties.get('target_portal')
            self.assertIn(iscsi_tgt_iqn, [self.data.initiator, self.data.iqn])
            self.assertIn(iscsi_tgt_portal, [self.data.ip + ":3260",
                                             self.data.ip2 + ":3260"])
            for ip_iqn in ip_and_iqn:
                if ip_iqn['ip'] + ":3260" == iscsi_tgt_portal:
                    self.assertEqual(iscsi_tgt_iqn, ip_iqn.get('iqn'))

    def test_vmax_get_iscsi_properties_multiple_targets_load_balance_exc(self):
        ip_and_iqn = [
            {'ip': self.data.ip, 'iqn': self.data.initiator},
            {'ip': self.data.ip2, 'iqn': self.data.iqn}]
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        self.driver.performance.config = self.data.performance_config

        with mock.patch.object(
                self.driver.performance, 'process_port_load',
                side_effect=(
                    self.driver.performance.process_port_load)) as mck_p:
            iscsi_properties = self.driver.vmax_get_iscsi_properties(
                self.data.array, self.data.test_volume, ip_and_iqn, False,
                host_lun_id, None, None)
            mck_p.assert_not_called()
            iscsi_tgt_iqn = iscsi_properties.get('target_iqn')
            iscsi_tgt_portal = iscsi_properties.get('target_portal')
            self.assertIn(iscsi_tgt_iqn, [self.data.initiator, self.data.iqn])
            self.assertIn(iscsi_tgt_portal, [self.data.ip + ":3260",
                                             self.data.ip2 + ":3260"])
            for ip_iqn in ip_and_iqn:
                if ip_iqn['ip'] + ":3260" == iscsi_tgt_portal:
                    self.assertEqual(iscsi_tgt_iqn, ip_iqn.get('iqn'))

    def test_vmax_get_iscsi_properties_auth(self):
        vol = deepcopy(self.data.test_volume)
        backup_conf = self.common.configuration
        configuration = tpfo.FakeConfiguration(
            None, 'ISCSITests', 1, 1, san_ip='1.1.1.1', san_login='smc',
            powermax_array=self.data.array, powermax_srp='SRP_1',
            san_password='smc', san_rest_port=8443, use_chap_auth=True,
            chap_username='auth_username', chap_password='auth_secret',
            powermax_port_groups=[self.data.port_group_name_i])
        self.driver.configuration = configuration
        ip_and_iqn = [{'ip': self.data.ip, 'iqn': self.data.initiator},
                      {'ip': self.data.ip, 'iqn': self.data.iqn}]
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        iscsi_properties = self.driver.vmax_get_iscsi_properties(
            self.data.array, vol, ip_and_iqn, True, host_lun_id, None, None)
        self.assertIn('auth_method', iscsi_properties.keys())
        self.assertIn('auth_username', iscsi_properties.keys())
        self.assertIn('auth_password', iscsi_properties.keys())
        self.assertEqual('CHAP', iscsi_properties['auth_method'])
        self.assertEqual('auth_username', iscsi_properties['auth_username'])
        self.assertEqual('auth_secret', iscsi_properties['auth_password'])
        self.driver.configuration = backup_conf

    def test_vmax_get_iscsi_properties_metro(self):
        ip_and_iqn = [{'ip': self.data.ip, 'iqn': self.data.iqn}]
        total_ip_list = [{'ip': self.data.ip, 'iqn': self.data.iqn},
                         {'ip': self.data.ip2, 'iqn': self.data.iqn2}]
        host_lun_id = self.data.iscsi_device_info['hostlunid']
        host_lun_id2 = self.data.iscsi_device_info_metro['metro_hostlunid']
        ref_properties = {
            'target_portals': (
                [t['ip'] + ':3260' for t in total_ip_list]),
            'target_iqns': (
                [t['iqn'].split(',')[0] for t in total_ip_list]),
            'target_luns': [host_lun_id, host_lun_id2],
            'target_discovered': True,
            'target_iqn': ip_and_iqn[0]['iqn'].split(',')[0],
            'target_portal': ip_and_iqn[0]['ip'] + ':3260',
            'target_lun': host_lun_id,
            'volume_id': self.data.test_volume.id}
        iscsi_properties = self.driver.vmax_get_iscsi_properties(
            self.data.array, self.data.test_volume, ip_and_iqn, True,
            host_lun_id, self.data.iscsi_device_info_metro['metro_ip_and_iqn'],
            self.data.iscsi_device_info_metro['metro_hostlunid'])
        self.assertEqual(ref_properties, iscsi_properties)

    def test_terminate_connection(self):
        with mock.patch.object(
                self.common, 'terminate_connection') as mock_terminate:
            self.driver.terminate_connection(self.data.test_volume,
                                             self.data.connector)
            mock_terminate.assert_called_once_with(
                self.data.test_volume, self.data.connector)

    def test_extend_volume(self):
        with mock.patch.object(
                self.common, 'extend_volume') as mock_extend:
            self.driver.extend_volume(self.data.test_volume, '3')
            mock_extend.assert_called_once_with(self.data.test_volume, '3')

    def test_get_volume_stats(self):
        with mock.patch.object(
                self.driver, '_update_volume_stats') as mock_update:
            self.driver.get_volume_stats(True)
            mock_update.assert_called_once_with()

    def test_update_volume_stats(self):
        with mock.patch.object(self.common, 'update_volume_stats',
                               return_value={}) as mock_update:
            self.driver.get_volume_stats()
            mock_update.assert_called_once_with()

    def test_check_for_setup_error(self):
        self.driver.check_for_setup_error()

    def test_ensure_export(self):
        self.driver.ensure_export('context', 'volume')

    def test_create_export(self):
        self.driver.create_export('context', 'volume', 'connector')

    def test_remove_export(self):
        self.driver.remove_export('context', 'volume')

    def test_check_for_export(self):
        self.driver.check_for_export('context', 'volume_id')

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
            mock_unmanage.assert_called_once_with(self.data.test_volume)

    def test_retype(self):
        host = {'host': self.data.new_host}
        new_type = {'extra_specs': {}}
        with mock.patch.object(self.common, 'retype',
                               return_value=True) as mck_retype:
            self.driver.retype({}, self.data.test_volume, new_type, '', host)
            mck_retype.assert_called_once_with(
                self.data.test_volume, new_type, host)

    def test_failover_host(self):
        with mock.patch.object(self.common, 'failover_host',
                               return_value={}) as mock_fo:
            self.driver.failover_host({}, [self.data.test_volume])
            mock_fo.assert_called_once_with([self.data.test_volume], None,
                                            None)

    def test_enable_replication(self):
        with mock.patch.object(self.common, 'enable_replication') as mock_er:
            self.driver.enable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_er.assert_called_once()

    def test_disable_replication(self):
        with mock.patch.object(self.common, 'disable_replication') as mock_dr:
            self.driver.disable_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_dr.assert_called_once()

    def test_failover_replication(self):
        with mock.patch.object(self.common, 'failover_replication') as mock_fo:
            self.driver.failover_replication(
                self.data.ctx, self.data.test_group, [self.data.test_volume])
            mock_fo.assert_called_once()
