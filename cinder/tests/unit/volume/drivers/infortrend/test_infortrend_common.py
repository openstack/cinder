# Copyright (c) 2015 Infortrend Technology, Inc.
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

import copy
from unittest import mock

from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit import utils
from cinder.tests.unit.volume.drivers.infortrend import test_infortrend_cli
from cinder.volume import configuration
from cinder.volume.drivers.infortrend.raidcmd_cli import common_cli
from cinder.volume import volume_utils

SUCCEED = (0, '')
FAKE_ERROR_RETURN = (-1, '')


class InfortrendTestCase(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(InfortrendTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(InfortrendTestCase, self).setUp()
        self.cli_data = test_infortrend_cli.InfortrendCLITestData()

        self.configuration = configuration.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.safe_get = self._fake_safe_get

    def _fake_safe_get(self, key):
        return getattr(self.configuration, key)

    def _driver_setup(self, mock_commands, configuration=None):
        if configuration is None:
            configuration = self.configuration
        self.driver = self._get_driver(configuration)

        mock_commands_execute = self._mock_command_execute(mock_commands)
        mock_cli = mock.Mock(side_effect=mock_commands_execute)

        self.driver._execute_command = mock_cli

    def _get_driver(self, conf):
        raise NotImplementedError

    def _mock_command_execute(self, mock_commands):
        def fake_execute_command(cli_type, *args, **kwargs):
            if cli_type in mock_commands.keys():
                if isinstance(mock_commands[cli_type], list):
                    ret = mock_commands[cli_type][0]
                    del mock_commands[cli_type][0]
                    return ret
                elif isinstance(mock_commands[cli_type], tuple):
                    return mock_commands[cli_type]
                else:
                    return mock_commands[cli_type](*args, **kwargs)
            return FAKE_ERROR_RETURN
        return fake_execute_command

    def _mock_show_lv_for_migrate(self, *args, **kwargs):
        if 'tier' in args:
            return self.cli_data.get_test_show_lv_tier_for_migration()
        return self.cli_data.get_test_show_lv()

    def _mock_show_lv(self, *args, **kwargs):
        if 'tier' in args:
            return self.cli_data.get_test_show_lv_tier()
        return self.cli_data.get_test_show_lv()

    def _assert_cli_has_calls(self, expect_cli_cmd):
        self.driver._execute_command.assert_has_calls(expect_cli_cmd)


class InfortrendFCCommonTestCase(InfortrendTestCase):

    def __init__(self, *args, **kwargs):
        super(InfortrendFCCommonTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(InfortrendFCCommonTestCase, self).setUp()

        self.configuration.volume_backend_name = 'infortrend_backend_1'
        self.configuration.san_ip = self.cli_data.fake_manage_port_ip[0]
        self.configuration.san_password = '111111'
        self.configuration.infortrend_provisioning = 'full'
        self.configuration.infortrend_tiering = '0'
        self.configuration.infortrend_pools_name = ['LV-1', 'LV-2']
        self.configuration.infortrend_slots_a_channels_id = [0, 5]
        self.configuration.infortrend_slots_b_channels_id = [0, 5]
        self.pool_dict = {
            'LV-1': self.cli_data.fake_lv_id[0],
            'LV-2': self.cli_data.fake_lv_id[1],
        }

    @mock.patch.object(
        common_cli.InfortrendCommon, '_init_raidcmd', mock.Mock())
    @mock.patch.object(
        common_cli.InfortrendCommon, '_init_raid_connection', mock.Mock())
    @mock.patch.object(
        common_cli.InfortrendCommon, '_set_raidcmd', mock.Mock())
    def _get_driver(self, conf):
        driver = common_cli.InfortrendCommon('FC', configuration=conf)
        driver.do_setup()
        driver.pool_dict = self.pool_dict
        return driver

    def test_normal_channel(self):

        test_map_dict = {
            'slot_a': {'0': [], '5': []},
            'slot_b': {},
        }
        test_target_dict = {
            'slot_a': {'0': '112', '5': '112'},
            'slot_b': {},
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
        }
        self._driver_setup(mock_commands)

        self.driver._init_map_info()

        self.assertDictEqual(test_map_dict, self.driver.map_dict)
        self.assertDictEqual(test_target_dict, self.driver.target_dict)

    def test_normal_channel_with_r_model(self):

        test_map_dict = {
            'slot_a': {'0': [], '5': []},
            'slot_b': {'0': [], '5': []},
        }
        test_target_dict = {
            'slot_a': {'0': '112', '5': '112'},
            'slot_b': {'0': '113', '5': '113'},
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model(),
        }
        self._driver_setup(mock_commands)
        self.driver._init_map_info()

        self.assertDictEqual(test_map_dict, self.driver.map_dict)
        self.assertDictEqual(test_target_dict, self.driver.target_dict)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_fc

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_without_mcs(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn_with_g_model(),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictEqual(self.cli_data.test_fc_properties, properties)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_specific_channel(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_fc
        configuration = copy.copy(self.configuration)
        configuration.infortrend_slots_a_channels_id = '5'

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn_with_g_model(),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands, configuration)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictEqual(
            self.cli_data.test_fc_properties_with_specific_channel, properties)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_with_diff_target_id(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_fc
        test_initiator_wwpns = test_connector['wwpns']
        test_partition_id = self.cli_data.fake_partition_id[0]
        configuration = copy.copy(self.configuration)
        configuration.infortrend_slots_a_channels_id = '5'

        mock_commands = {
            'ShowChannel':
                self.cli_data.get_test_show_channel_with_diff_target_id(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn_with_g_model(),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands, configuration)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        expect_cli_cmd = [
            mock.call('ShowDevice'),
            mock.call('ShowChannel'),
            mock.call('ShowWWN'),
            mock.call('ShowMap', 'part=%s' % test_partition_id),
            mock.call('ShowMap'),
            mock.call('CreateMap', 'part', test_partition_id, '5', '48', '0',
                      'wwn=%s' % test_initiator_wwpns[0]),
            mock.call('CreateMap', 'part', test_partition_id, '5', '48', '0',
                      'wwn=%s' % test_initiator_wwpns[1]),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

        self.assertDictEqual(
            self.cli_data.test_fc_properties_with_specific_channel, properties)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_multipath_with_r_model(self):

        test_volume = self.cli_data.test_volume
        test_connector = copy.deepcopy(self.cli_data.test_connector_fc)

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn(),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)
        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictEqual(
            self.cli_data.test_fc_properties_multipath_r_model, properties)

    def test_initialize_connection_with_get_wwn_fail(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_fc

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.initialize_connection,
            test_volume,
            test_connector)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_with_zoning(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_fc
        test_initiator_wwpns = test_connector['wwpns']
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_all_target_wwpns = self.cli_data.fake_target_wwpns[0:2]
        test_lookup_map = self.cli_data.fake_lookup_map

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn_with_g_model(),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)
        self.driver.fc_lookup_service = mock.Mock()
        get_device_mapping_from_network = (
            self.driver.fc_lookup_service.get_device_mapping_from_network
        )
        get_device_mapping_from_network.return_value = test_lookup_map

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        get_device_mapping_from_network.assert_has_calls(
            [mock.call(test_connector['wwpns'], test_all_target_wwpns)])

        expect_cli_cmd = [
            mock.call('ShowDevice'),
            mock.call('ShowChannel'),
            mock.call('ShowWWN'),
            mock.call('ShowMap', 'part=%s' % test_partition_id),
            mock.call('ShowMap'),
            mock.call('CreateMap', 'part', test_partition_id, '0', '112', '0',
                      'wwn=%s' % test_initiator_wwpns[0]),
            mock.call('CreateMap', 'part', test_partition_id, '5', '112', '0',
                      'wwn=%s' % test_initiator_wwpns[0]),
            mock.call('CreateMap', 'part', test_partition_id, '0', '112', '0',
                      'wwn=%s' % test_initiator_wwpns[1]),
            mock.call('CreateMap', 'part', test_partition_id, '5', '112', '0',
                      'wwn=%s' % test_initiator_wwpns[1]),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

        self.assertDictEqual(
            self.cli_data.test_fc_properties_zoning, properties)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_with_zoning_r_model(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_fc
        test_initiator_wwpns = test_connector['wwpns']
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_all_target_wwpns = self.cli_data.fake_target_wwpns[:]
        test_all_target_wwpns[1] = self.cli_data.fake_target_wwpns[2]
        test_all_target_wwpns[2] = self.cli_data.fake_target_wwpns[1]
        test_lookup_map = self.cli_data.fake_lookup_map_r_model

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn(),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)
        self.driver.fc_lookup_service = mock.Mock()
        get_device_mapping_from_network = (
            self.driver.fc_lookup_service.get_device_mapping_from_network
        )
        get_device_mapping_from_network.return_value = test_lookup_map

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        get_device_mapping_from_network.assert_has_calls(
            [mock.call(test_connector['wwpns'], test_all_target_wwpns)])

        expect_cli_cmd = [
            mock.call('ShowDevice'),
            mock.call('ShowChannel'),
            mock.call('ShowWWN'),
            mock.call('ShowMap', 'part=%s' % test_partition_id),
            mock.call('ShowMap'),
            mock.call('CreateMap', 'part', test_partition_id, '5', '112', '0',
                      'wwn=%s' % test_initiator_wwpns[0]),
            mock.call('CreateMap', 'part', test_partition_id, '0', '113', '0',
                      'wwn=%s' % test_initiator_wwpns[0]),
            mock.call('CreateMap', 'part', test_partition_id, '5', '112', '0',
                      'wwn=%s' % test_initiator_wwpns[1]),
            mock.call('CreateMap', 'part', test_partition_id, '0', '113', '0',
                      'wwn=%s' % test_initiator_wwpns[1]),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

        self.assertDictEqual(
            self.cli_data.test_fc_properties_zoning_r_model, properties)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_with_zoning_r_model_diff_target_id(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_fc
        test_initiator_wwpns = test_connector['wwpns']
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_all_target_wwpns = self.cli_data.fake_target_wwpns[:]
        test_all_target_wwpns[1] = self.cli_data.fake_target_wwpns[2]
        test_all_target_wwpns[2] = self.cli_data.fake_target_wwpns[1]
        test_lookup_map = self.cli_data.fake_lookup_map_r_model

        mock_commands = {
            'ShowChannel':
                self.cli_data.get_test_show_channel_r_model_diff_target_id(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'CreateMap': SUCCEED,
            'ShowWWN': self.cli_data.get_test_show_wwn_with_diff_target_id(),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        self.driver.fc_lookup_service = mock.Mock()
        get_device_mapping_from_network = (
            self.driver.fc_lookup_service.get_device_mapping_from_network
        )
        get_device_mapping_from_network.return_value = test_lookup_map

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        get_device_mapping_from_network.assert_has_calls(
            [mock.call(test_connector['wwpns'], test_all_target_wwpns)])

        expect_cli_cmd = [
            mock.call('ShowDevice'),
            mock.call('ShowChannel'),
            mock.call('ShowWWN'),
            mock.call('ShowMap', 'part=%s' % test_partition_id),
            mock.call('ShowMap'),
            mock.call('CreateMap', 'part', test_partition_id, '5', '48', '0',
                      'wwn=%s' % test_initiator_wwpns[0]),
            mock.call('CreateMap', 'part', test_partition_id, '0', '33', '0',
                      'wwn=%s' % test_initiator_wwpns[0]),
            mock.call('CreateMap', 'part', test_partition_id, '5', '48', '0',
                      'wwn=%s' % test_initiator_wwpns[1]),
            mock.call('CreateMap', 'part', test_partition_id, '0', '33', '0',
                      'wwn=%s' % test_initiator_wwpns[1]),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

        self.assertDictEqual(
            self.cli_data.test_fc_properties_zoning_r_model, properties)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_terminate_connection(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_connector = self.cli_data.test_connector_fc

        mock_commands = {
            'DeleteMap': SUCCEED,
            'ShowMap': [self.cli_data.get_test_show_map_fc(),
                        self.cli_data.get_test_show_empty_list()],
            'ShowWWN': SUCCEED,
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        self.driver.terminate_connection(test_volume, test_connector)

        expect_cli_cmd = [
            mock.call('ShowDevice'),
            mock.call('ShowMap', 'part=%s' % test_partition_id),
            mock.call('DeleteMap',
                      'part', test_partition_id, '0', '112', '0', '-y'),
            mock.call('DeleteMap',
                      'part', test_partition_id, '5', '112', '0', '-y'),
            mock.call('ShowMap'),
            mock.call('ShowWWN'),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_terminate_connection_with_zoning(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_connector = self.cli_data.test_connector_fc
        test_all_target_wwpns = self.cli_data.fake_target_wwpns[:2]
        test_lookup_map = self.cli_data.fake_lookup_map

        mock_commands = {
            'DeleteMap': SUCCEED,
            'ShowMap': [self.cli_data.get_test_show_map_fc(),
                        self.cli_data.get_test_show_empty_list()],
            'ShowWWN': self.cli_data.get_test_show_wwn_with_g_model(),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)
        self.driver.map_dict = {
            'slot_a': {'0': [], '5': []},
            'slot_b': {},
        }
        self.driver.fc_lookup_service = mock.Mock()
        get_device_mapping_from_network = (
            self.driver.fc_lookup_service.get_device_mapping_from_network
        )
        get_device_mapping_from_network.return_value = test_lookup_map

        conn_info = self.driver.terminate_connection(
            test_volume, test_connector)

        get_device_mapping_from_network.assert_has_calls(
            [mock.call(test_connector['wwpns'], test_all_target_wwpns)])

        expect_cli_cmd = [
            mock.call('ShowMap', 'part=%s' % test_partition_id),
            mock.call('DeleteMap',
                      'part', test_partition_id, '0', '112', '0', '-y'),
            mock.call('DeleteMap',
                      'part', test_partition_id, '5', '112', '0', '-y'),
            mock.call('ShowMap'),
            mock.call('ShowWWN'),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

        self.assertDictEqual(
            self.cli_data.test_fc_terminate_conn_info, conn_info)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_terminate_connection_with_zoning_and_lun_map_exist(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_connector = self.cli_data.test_connector_fc

        mock_commands = {
            'DeleteMap': SUCCEED,
            'ShowMap': self.cli_data.get_show_map_with_lun_map_on_zoning(),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)
        self.driver.map_dict = {
            'slot_a': {'0': [], '5': []},
            'slot_b': {},
        }
        self.driver.target_dict = {
            'slot_a': {'0': '112', '5': '112'},
            'slot_b': {},
        }
        self.driver.fc_lookup_service = mock.Mock()

        conn_info = self.driver.terminate_connection(
            test_volume, test_connector)

        expect_cli_cmd = [
            mock.call('ShowMap', 'part=%s' % test_partition_id),
            mock.call('DeleteMap',
                      'part', test_partition_id, '0', '112', '0', '-y'),
            mock.call('ShowMap'),
        ]
        expect_conn_info = {'driver_volume_type': 'fibre_channel',
                            'data': {}}
        self._assert_cli_has_calls(expect_cli_cmd)

        self.assertEqual(expect_conn_info, conn_info)


class InfortrendiSCSICommonTestCase(InfortrendTestCase):

    def __init__(self, *args, **kwargs):
        super(InfortrendiSCSICommonTestCase, self).__init__(*args, **kwargs)

    def setUp(self):
        super(InfortrendiSCSICommonTestCase, self).setUp()

        self.configuration.volume_backend_name = 'infortrend_backend_1'
        self.configuration.san_ip = self.cli_data.fake_manage_port_ip[0]
        self.configuration.san_password = '111111'
        self.configuration.infortrend_provisioning = 'full'
        self.configuration.infortrend_tiering = '0'
        self.configuration.infortrend_pools_name = ['LV-1', 'LV-2']
        self.configuration.infortrend_slots_a_channels_id = [1, 2, 4]
        self.configuration.infortrend_slots_b_channels_id = [1, 2, 4]
        self.pool_dict = {
            'LV-1': self.cli_data.fake_lv_id[0],
            'LV-2': self.cli_data.fake_lv_id[1],
        }

    @mock.patch.object(
        common_cli.InfortrendCommon, '_init_raidcmd', mock.Mock())
    @mock.patch.object(
        common_cli.InfortrendCommon, '_init_raid_connection', mock.Mock())
    @mock.patch.object(
        common_cli.InfortrendCommon, '_set_raidcmd', mock.Mock())
    def _get_driver(self, conf):
        driver = common_cli.InfortrendCommon('iSCSI', configuration=conf)
        driver.do_setup()
        driver.pool_dict = self.pool_dict
        return driver

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_create_map_warning_return_code(self, log_warning):

        FAKE_RETURN_CODE = (20, '')
        mock_commands = {
            'CreateMap': FAKE_RETURN_CODE,
        }
        self._driver_setup(mock_commands)

        self.driver._execute('CreateMap')
        self.assertEqual(1, log_warning.call_count)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_delete_map_warning_return_code(self, log_warning):

        FAKE_RETURN_CODE = (11, '')
        mock_commands = {
            'DeleteMap': FAKE_RETURN_CODE,
        }
        self._driver_setup(mock_commands)

        self.driver._execute('DeleteMap')
        self.assertEqual(1, log_warning.call_count)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_create_iqn_warning_return_code(self, log_warning):

        FAKE_RETURN_CODE = (20, '')
        mock_commands = {
            'CreateIQN': FAKE_RETURN_CODE,
        }
        self._driver_setup(mock_commands)

        self.driver._execute('CreateIQN')
        self.assertEqual(1, log_warning.call_count)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_delete_iqn_warning_return_code_has_map(self, log_warning):

        FAKE_RETURN_CODE = (20, '')
        mock_commands = {
            'DeleteIQN': FAKE_RETURN_CODE,
        }
        self._driver_setup(mock_commands)

        self.driver._execute('DeleteIQN')
        self.assertEqual(1, log_warning.call_count)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_delete_iqn_warning_return_code_no_such_name(self, log_warning):

        FAKE_RETURN_CODE = (11, '')
        mock_commands = {
            'DeleteIQN': FAKE_RETURN_CODE,
        }
        self._driver_setup(mock_commands)

        self.driver._execute('DeleteIQN')
        self.assertEqual(1, log_warning.call_count)

    def test_normal_channel(self):

        test_map_dict = {
            'slot_a': {'1': [], '2': [], '4': []},
            'slot_b': {},
        }
        test_target_dict = {
            'slot_a': {'1': '0', '2': '0', '4': '0'},
            'slot_b': {},
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
        }
        self._driver_setup(mock_commands)
        self.driver._init_map_info()

        self.assertDictEqual(test_map_dict, self.driver.map_dict)
        self.assertDictEqual(test_target_dict, self.driver.target_dict)

    def test_normal_channel_with_multipath(self):

        test_map_dict = {
            'slot_a': {'1': [], '2': [], '4': []},
            'slot_b': {'1': [], '2': [], '4': []},
        }
        test_target_dict = {
            'slot_a': {'1': '0', '2': '0', '4': '0'},
            'slot_b': {'1': '1', '2': '1', '4': '1'},
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model(),
        }
        self._driver_setup(mock_commands)

        self.driver._init_map_info()

        self.assertDictEqual(test_map_dict, self.driver.map_dict)
        self.assertDictEqual(test_target_dict, self.driver.target_dict)

    def test_specific_channel(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_slots_a_channels_id = '2, 4'

        test_map_dict = {
            'slot_a': {'2': [], '4': []},
            'slot_b': {},
        }
        test_target_dict = {
            'slot_a': {'2': '0', '4': '0'},
            'slot_b': {},
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
        }
        self._driver_setup(mock_commands, configuration)
        self.driver._init_map_info()

        self.assertDictEqual(test_map_dict, self.driver.map_dict)
        self.assertDictEqual(test_target_dict, self.driver.target_dict)

    def test_update_mcs_dict(self):

        configuration = copy.copy(self.configuration)
        configuration.use_multipath_for_image_xfer = True

        test_mcs_dict = {
            'slot_a': {'1': ['1', '2'], '2': ['4']},
            'slot_b': {},
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_with_mcs(),
        }

        self._driver_setup(mock_commands, configuration)
        self.driver._init_map_info()

        self.assertDictEqual(test_mcs_dict, self.driver.mcs_dict)

    def test_mapping_info_with_mpio_no_mcs(self):

        configuration = copy.copy(self.configuration)
        configuration.use_multipath_for_image_xfer = True

        fake_mcs_dict = {
            'slot_a': {'1': ['1'], '2': ['2'], '4': ['4']},
            'slot_b': {'1': ['1'], '2': ['2'], '4': ['4']},
        }
        lun_list = list(range(0, 127))
        fake_map_dict = {
            'slot_a': {'1': lun_list[2:], '2': lun_list[:], '4': lun_list[1:]},
            'slot_b': {'1': lun_list[:], '2': lun_list[:], '4': lun_list[:]},
        }

        test_map_chl = {
            'slot_a': ['1', '2', '4'],
            'slot_b': ['1', '2', '4'],
        }
        test_map_lun = ['2']
        self.driver = self._get_driver(configuration)
        self.driver.mcs_dict = fake_mcs_dict
        self.driver.map_dict = fake_map_dict

        map_chl, map_lun = self.driver._get_mapping_info_with_mpio()

        map_chl['slot_a'].sort()
        map_chl['slot_b'].sort()

        self.assertDictEqual(test_map_chl, map_chl)
        self.assertEqual(test_map_lun, map_lun)

    def test_mapping_info_with_mcs(self):

        configuration = copy.copy(self.configuration)
        configuration.use_multipath_for_image_xfer = True

        fake_mcs_dict = {
            'slot_a': {'0': ['1', '2'], '2': ['4']},
            'slot_b': {'0': ['1', '2']},
        }
        lun_list = list(range(0, 127))
        fake_map_dict = {
            'slot_a': {'1': lun_list[2:], '2': lun_list[:], '4': lun_list[1:]},
            'slot_b': {'1': lun_list[:], '2': lun_list[:]},
        }

        test_map_chl = {
            'slot_a': ['1', '4'],
            'slot_b': ['1'],
        }
        test_map_lun = ['2']
        self.driver = self._get_driver(configuration)
        self.driver.mcs_dict = fake_mcs_dict
        self.driver.map_dict = fake_map_dict

        map_chl, map_lun = self.driver._get_mapping_info_with_mpio()

        map_chl['slot_a'].sort()
        map_chl['slot_b'].sort()

        self.assertDictEqual(test_map_chl, map_chl)
        self.assertEqual(test_map_lun, map_lun)

    def test_mapping_info_with_mcs_multi_group(self):

        configuration = copy.copy(self.configuration)
        configuration.use_multipath_for_image_xfer = True

        fake_mcs_dict = {
            'slot_a': {'0': ['1', '2'], '1': ['3', '4'], '2': ['5']},
            'slot_b': {'0': ['1', '2']},
        }
        lun_list = list(range(0, 127))
        fake_map_dict = {
            'slot_a': {
                '1': lun_list[2:],
                '2': lun_list[3:],
                '3': lun_list[:],
                '4': lun_list[1:],
                '5': lun_list[:],
            },
            'slot_b': {
                '1': lun_list[:],
                '2': lun_list[:],
            },
        }

        test_map_chl = {
            'slot_a': ['1', '3', '5'],
            'slot_b': ['1'],
        }
        test_map_lun = ['2']
        self.driver = self._get_driver(configuration)
        self.driver.mcs_dict = fake_mcs_dict
        self.driver.map_dict = fake_map_dict

        map_chl, map_lun = self.driver._get_mapping_info_with_mpio()

        map_chl['slot_a'].sort()
        map_chl['slot_b'].sort()

        self.assertDictEqual(test_map_chl, map_chl)
        self.assertEqual(test_map_lun, map_lun)

    def test_specific_channel_with_multipath(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_slots_a_channels_id = '1,2'

        test_map_dict = {
            'slot_a': {'1': [], '2': []},
            'slot_b': {},
        }
        test_target_dict = {
            'slot_a': {'1': '0', '2': '0'},
            'slot_b': {},
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
        }
        self._driver_setup(mock_commands, configuration)

        self.driver._init_map_info()

        self.assertDictEqual(test_map_dict, self.driver.map_dict)
        self.assertDictEqual(test_target_dict, self.driver.target_dict)

    def test_specific_channel_with_multipath_r_model(self):

        configuration = copy.copy(self.configuration)
        configuration.infortrend_slots_a_channels_id = '1,2'
        configuration.infortrend_slots_b_channels_id = '1'

        test_map_dict = {
            'slot_a': {'1': [], '2': []},
            'slot_b': {'1': []},
        }
        test_target_dict = {
            'slot_a': {'1': '0', '2': '0'},
            'slot_b': {'1': '1'},
        }
        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model(),
        }
        self._driver_setup(mock_commands, configuration)
        self.driver._init_map_info()

        self.assertDictEqual(test_map_dict, self.driver.map_dict)
        self.assertDictEqual(test_target_dict, self.driver.target_dict)

    @mock.patch.object(common_cli.LOG, 'info')
    def test_create_volume(self, log_info):

        test_volume = self.cli_data.test_volume
        test_model_update = {
            'provider_location': 'partition_id^%s@system_id^%s' % (
                self.cli_data.fake_partition_id[0],
                int(self.cli_data.fake_system_id[0], 16)
            )
        }

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'ShowLV': self._mock_show_lv,
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.create_volume(test_volume)

        self.assertDictEqual(test_model_update, model_update)
        self.assertEqual(1, log_info.call_count)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_create_volume_with_create_fail(self):
        test_volume = self.cli_data.test_volume

        mock_commands = {
            'CreatePartition': FAKE_ERROR_RETURN,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'ShowLV': self._mock_show_lv,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.create_volume,
            test_volume)

    @mock.patch.object(common_cli.LOG, 'info')
    def test_delete_volume_with_mapped(self, log_info):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]

        mock_commands = {
            'ShowPartition':
                self.cli_data.get_test_show_partition_detail_for_map(
                    test_partition_id),
            'DeleteMap': SUCCEED,
            'DeletePartition': SUCCEED,
        }
        self._driver_setup(mock_commands)

        self.driver.delete_volume(test_volume)

        expect_cli_cmd = [
            mock.call('ShowPartition', '-l'),
            mock.call('DeleteMap', 'part', test_partition_id, '-y'),
            mock.call('DeletePartition', test_partition_id, '-y'),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertEqual(1, log_info.call_count)

    @mock.patch.object(common_cli.LOG, 'info')
    def test_delete_volume_without_mapped(self, log_info):

        test_volume = self.cli_data.test_volume_1
        test_partition_id = self.cli_data.fake_partition_id[1]

        mock_commands = {
            'ShowPartition':
                self.cli_data.get_test_show_partition_detail(
                    test_volume['id'], '5DE94FF775D81C30'),
            'DeletePartition': SUCCEED,
        }
        self._driver_setup(mock_commands)
        self.driver.delete_volume(test_volume)

        expect_cli_cmd = [
            mock.call('ShowPartition', '-l'),
            mock.call('DeletePartition', test_partition_id, '-y'),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertEqual(1, log_info.call_count)

    def test_delete_volume_with_delete_fail(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]

        mock_commands = {
            'ShowPartition':
                self.cli_data.get_test_show_partition_detail_for_map(
                    test_partition_id),
            'ShowReplica': self.cli_data.get_test_show_replica_detail(),
            'DeleteReplica': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(),
            'DeleteSnapshot': SUCCEED,
            'ShowMap': self.cli_data.get_test_show_map(),
            'DeleteMap': SUCCEED,
            'DeletePartition': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.delete_volume,
            test_volume)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_delete_volume_with_partiton_not_found(self, log_warning):

        test_volume = self.cli_data.test_volume

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_empty_list(),
        }
        self._driver_setup(mock_commands)

        self.driver.delete_volume(test_volume)

        self.assertEqual(1, log_warning.call_count)

    @mock.patch.object(common_cli.LOG, 'info')
    def test_delete_volume_without_provider(self, log_info):

        test_system_id = self.cli_data.fake_system_id[0]
        test_volume = copy.deepcopy(self.cli_data.test_volume)
        test_volume['provider_location'] = 'partition_id^%s@system_id^%s' % (
            'None', int(test_system_id, 16))
        test_partition_id = self.cli_data.fake_partition_id[0]

        mock_commands = {
            'ShowPartition':
                self.cli_data.get_test_show_partition_detail_for_map(
                    test_partition_id),
            'ShowReplica': self.cli_data.get_test_show_replica_detail(),
            'DeleteReplica': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(),
            'DeleteSnapshot': SUCCEED,
            'ShowMap': self.cli_data.get_test_show_map(),
            'DeleteMap': SUCCEED,
            'DeletePartition': SUCCEED,
        }
        self._driver_setup(mock_commands)

        self.driver.delete_volume(test_volume)

        self.assertEqual(1, log_info.call_count)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    @mock.patch.object(common_cli.LOG, 'info')
    def test_create_cloned_volume(self, log_info):

        fake_partition_id = self.cli_data.fake_partition_id[0]
        test_dst_volume = self.cli_data.test_dst_volume
        test_dst_volume_id = test_dst_volume['id']
        test_src_volume = self.cli_data.test_volume
        test_dst_part_id = self.cli_data.fake_partition_id[1]
        test_model_update = {
            'provider_location': 'partition_id^%s@system_id^%s' % (
                self.cli_data.fake_partition_id[1],
                int(self.cli_data.fake_system_id[0], 16)
            )
        }

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'CreateReplica': SUCCEED,
            'ShowLV': self._mock_show_lv,
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_migrate(
                    fake_partition_id, test_dst_part_id, test_dst_volume_id),
            'DeleteReplica': SUCCEED,
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.create_cloned_volume(
            test_dst_volume, test_src_volume)

        self.assertDictEqual(test_model_update, model_update)
        self.assertEqual(1, log_info.call_count)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_create_cloned_volume_with_create_replica_fail(self):

        test_dst_volume = self.cli_data.test_dst_volume
        test_src_volume = self.cli_data.test_volume

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'CreateReplica': FAKE_ERROR_RETURN,
            'ShowLV': self._mock_show_lv,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.create_cloned_volume,
            test_dst_volume,
            test_src_volume)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_create_export(self):

        test_volume = self.cli_data.test_volume
        test_model_update = {
            'provider_location': test_volume['provider_location'],
        }
        self.driver = self._get_driver(self.configuration)

        model_update = self.driver.create_export(None, test_volume)

        self.assertDictEqual(test_model_update, model_update)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_get_volume_stats_full(self):

        test_volume_states = self.cli_data.test_volume_states_full

        mock_commands = {
            'InitCache': SUCCEED,
            'ShowLicense': self.cli_data.get_test_show_license_full(),
            'ShowLV': [self.cli_data.get_test_show_lv_tier(),
                       self.cli_data.get_test_show_lv()],
            'ShowDevice': self.cli_data.get_test_show_device(),
            'CheckConnection': SUCCEED,
        }
        self._driver_setup(mock_commands)
        self.driver.VERSION = '99.99'
        self.driver.system_id = self.cli_data.fake_system_id[0]

        volume_states = self.driver.get_volume_stats(True)

        self.assertDictEqual.__self__.maxDiff = None
        self.assertDictEqual(test_volume_states, volume_states)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_get_volume_stats_thin(self):

        test_volume_states = self.cli_data.test_volume_states_thin

        mock_commands = {
            'InitCache': SUCCEED,
            'ShowLicense': self.cli_data.get_test_show_license_thin(),
            'ShowLV': [self.cli_data.get_test_show_lv_tier(),
                       self.cli_data.get_test_show_lv()],
            'ShowPartition': self.cli_data.get_test_show_partition_detail(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'CheckConnection': SUCCEED,
        }
        self._driver_setup(mock_commands)
        self.driver.VERSION = '99.99'
        self.driver.system_id = self.cli_data.fake_system_id[0]

        volume_states = self.driver.get_volume_stats(True)

        self.assertDictEqual.__self__.maxDiff = None
        self.assertDictEqual(test_volume_states, volume_states)

    def test_get_volume_stats_fail(self):

        mock_commands = {
            'InitCache': SUCCEED,
            'ShowLicense': self.cli_data.get_test_show_license_thin(),
            'ShowLV': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.get_volume_stats)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_create_snapshot(self):

        fake_partition_id = self.cli_data.fake_partition_id[0]
        fake_snapshot_id = self.cli_data.fake_snapshot_id[0]

        mock_commands = {
            'CreateSnapshot': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(
                partition_id=fake_partition_id,
                snapshot_id=fake_snapshot_id),
            'ShowPartition': self.cli_data.get_test_show_partition(),
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.create_snapshot(self.cli_data.test_snapshot)

        self.assertEqual(fake_snapshot_id, model_update['provider_location'])

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_create_snapshot_without_partition_id(self):

        fake_partition_id = self.cli_data.fake_partition_id[0]
        fake_snapshot_id = self.cli_data.fake_snapshot_id[0]
        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'CreateSnapshot': SUCCEED,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(
                partition_id=fake_partition_id,
                snapshot_id=fake_snapshot_id),
            'ShowPartition': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.create_snapshot,
            test_snapshot)

    def test_create_snapshot_with_create_fail(self):

        fake_partition_id = self.cli_data.fake_partition_id[0]
        fake_snapshot_id = self.cli_data.fake_snapshot_id[0]
        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'CreateSnapshot': FAKE_ERROR_RETURN,
            'ShowSnapshot': self.cli_data.get_test_show_snapshot(
                partition_id=fake_partition_id,
                snapshot_id=fake_snapshot_id),
            'ShowPartition': self.cli_data.get_test_show_partition(),
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.create_snapshot,
            test_snapshot)

    def test_create_snapshot_with_show_fail(self):

        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'CreateSnapshot': SUCCEED,
            'ShowSnapshot': FAKE_ERROR_RETURN,
            'ShowPartition': self.cli_data.get_test_show_partition(),
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.create_snapshot,
            test_snapshot)

    @mock.patch.object(common_cli.LOG, 'info')
    def test_delete_snapshot(self, log_info):

        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'ShowReplica': self.cli_data.get_test_show_replica_detail(),
            'DeleteSnapshot': SUCCEED,
        }
        self._driver_setup(mock_commands)

        self.driver.delete_snapshot(test_snapshot)

        self.assertEqual(1, log_info.call_count)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_delete_snapshot_without_provider_location(self, log_warning):

        test_snapshot = self.cli_data.test_snapshot_without_provider_location

        self.driver = self._get_driver(self.configuration)
        self.driver.delete_snapshot(test_snapshot)

        self.assertEqual(1, log_warning.call_count)

    def test_delete_snapshot_with_fail(self):

        test_snapshot = self.cli_data.test_snapshot

        mock_commands = {
            'DeleteSnapshot': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.delete_snapshot,
            test_snapshot)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    @mock.patch.object(common_cli.LOG, 'info')
    def test_create_volume_from_snapshot(self, log_info):

        test_snapshot = self.cli_data.test_snapshot
        test_snapshot_id = self.cli_data.fake_snapshot_id[0]
        test_dst_volume = self.cli_data.test_dst_volume
        test_dst_volume_id = test_dst_volume['id']
        test_dst_part_id = self.cli_data.fake_partition_id[1]
        test_model_update = {
            'provider_location': 'partition_id^%s@system_id^%s' % (
                self.cli_data.fake_partition_id[1],
                int(self.cli_data.fake_system_id[0], 16)
            )
        }
        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'CreateReplica': SUCCEED,
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_migrate(
                    test_snapshot_id, test_dst_part_id, test_dst_volume_id),
            'DeleteReplica': SUCCEED,
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.create_volume_from_snapshot(
            test_dst_volume, test_snapshot)

        self.assertDictEqual(test_model_update, model_update)
        self.assertEqual(1, log_info.call_count)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    @mock.patch.object(common_cli.LOG, 'info')
    def test_create_volume_from_snapshot_with_different_size(self, log_info):

        test_snapshot = self.cli_data.test_snapshot
        test_snapshot_id = self.cli_data.fake_snapshot_id[0]
        test_dst_volume = self.cli_data.test_dst_volume
        test_dst_volume['size'] = 10
        test_dst_volume_id = test_dst_volume['id'].replace('-', '')
        test_dst_part_id = self.cli_data.fake_partition_id[1]
        test_model_update = {
            'provider_location': 'partition_id^%s@system_id^%s' % (
                self.cli_data.fake_partition_id[1],
                int(self.cli_data.fake_system_id[0], 16))
        }
        mock_commands = {
            'ShowSnapshot':
                self.cli_data.get_test_show_snapshot_detail_filled_block(),
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'ShowDevice': self.cli_data.get_test_show_device(),
            'CreateReplica': SUCCEED,
            'ShowLV': self._mock_show_lv,
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_migrate(
                    test_snapshot_id, test_dst_part_id, test_dst_volume_id),
            'DeleteReplica': SUCCEED,
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.create_volume_from_snapshot(
            test_dst_volume, test_snapshot)
        self.assertDictEqual(test_model_update, model_update)
        self.assertEqual(1, log_info.call_count)
        self.assertEqual(10, test_dst_volume['size'])

    def test_create_volume_from_snapshot_without_provider_location(
            self):

        test_snapshot = self.cli_data.test_snapshot_without_provider_location
        test_dst_volume = self.cli_data.test_dst_volume

        self.driver = self._get_driver(self.configuration)

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume_from_snapshot,
            test_dst_volume,
            test_snapshot)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_connector = copy.deepcopy(self.cli_data.test_connector_iscsi)
        test_iscsi_properties = self.cli_data.test_iscsi_properties
        test_target_protal = [test_iscsi_properties['data']['target_portal']]
        test_target_iqn = [test_iscsi_properties['data']['target_iqn']]

        test_connector['multipath'] = False

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqn, test_target_protal),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictEqual(test_iscsi_properties, properties)

        expect_cli_cmd = [
            mock.call('CreateMap', 'part', test_partition_id, '2', '0', '0',
                      'iqn=%s' % test_connector['initiator']),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_with_iqn_not_exist(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_initiator = copy.deepcopy(self.cli_data.fake_initiator_iqn[1])
        test_connector = copy.deepcopy(self.cli_data.test_connector_iscsi)
        test_iscsi_properties = self.cli_data.test_iscsi_properties
        test_target_protal = [test_iscsi_properties['data']['target_portal']]
        test_target_iqn = [test_iscsi_properties['data']['target_iqn']]

        test_connector['multipath'] = False
        test_connector['initiator'] = test_initiator

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateIQN': SUCCEED,
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqn, test_target_protal),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictEqual(test_iscsi_properties, properties)

        expect_cli_cmd = [
            mock.call('ShowDevice'),
            mock.call('ShowChannel'),
            mock.call('ShowIQN'),
            mock.call('CreateIQN', test_initiator, test_initiator[-16:]),
            mock.call('ShowNet'),
            mock.call('ShowMap'),
            mock.call('ShowMap', 'part=6A41315B0EDC8EB7'),
            mock.call('CreateMap', 'part', test_partition_id, '2', '0', '0',
                      'iqn=%s' % test_connector['initiator']),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_with_empty_map(self):

        test_volume = self.cli_data.test_volume
        test_connector = copy.deepcopy(self.cli_data.test_connector_iscsi)
        test_iscsi_properties = self.cli_data.test_iscsi_properties_empty_map
        test_target_protal = [test_iscsi_properties['data']['target_portal']]
        test_target_iqn = [test_iscsi_properties['data']['target_iqn']]

        test_connector['multipath'] = False

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_empty_list(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqn, test_target_protal),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictEqual(
            self.cli_data.test_iscsi_properties_empty_map, properties)

    def test_initialize_connection_with_create_map_fail(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_iscsi

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_r_model(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': FAKE_ERROR_RETURN,
            'ShowNet': SUCCEED,
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.initialize_connection,
            test_volume,
            test_connector)

    def test_initialize_connection_with_get_ip_fail(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_iscsi

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.initialize_connection,
            test_volume,
            test_connector)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_with_mcs(self):

        configuration = copy.copy(self.configuration)

        test_volume = self.cli_data.test_volume_1
        test_partition_id = self.cli_data.fake_partition_id[1]
        test_connector = copy.deepcopy(self.cli_data.test_connector_iscsi_1)
        test_iscsi_properties = self.cli_data.test_iscsi_properties_with_mcs_1
        test_target_portal = [test_iscsi_properties['data']['target_portal']]
        test_target_iqn = [test_iscsi_properties['data']['target_iqn']]

        test_connector['multipath'] = False

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_with_mcs(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateIQN': SUCCEED,
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqn, test_target_portal),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands, configuration)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictEqual(test_iscsi_properties, properties)

        expect_cli_cmd = [
            mock.call('CreateMap', 'part', test_partition_id, '4', '0', '1',
                      'iqn=%s' % test_connector['initiator']),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_initialize_connection_with_exist_map(self):

        configuration = copy.copy(self.configuration)

        test_volume = self.cli_data.test_volume
        test_connector = copy.deepcopy(self.cli_data.test_connector_iscsi)
        test_iscsi_properties = self.cli_data.test_iscsi_properties_with_mcs
        test_target_portal = [test_iscsi_properties['data']['target_portal']]
        test_target_iqn = [test_iscsi_properties['data']['target_iqn']]

        test_connector['multipath'] = False

        mock_commands = {
            'ShowChannel': self.cli_data.get_test_show_channel_with_mcs(),
            'ShowMap': self.cli_data.get_test_show_map(),
            'ShowIQN': self.cli_data.get_test_show_iqn(),
            'CreateMap': SUCCEED,
            'ShowNet': self.cli_data.get_test_show_net(),
            'ExecuteCommand': self.cli_data.get_fake_discovery(
                test_target_iqn, test_target_portal),
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands, configuration)

        properties = self.driver.initialize_connection(
            test_volume, test_connector)

        self.assertDictEqual(test_iscsi_properties, properties)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_extend_volume(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_new_size = 10
        test_expand_size = test_new_size - test_volume['size']

        mock_commands = {
            'SetPartition': SUCCEED,
        }
        self._driver_setup(mock_commands)

        self.driver.extend_volume(test_volume, test_new_size)

        expect_cli_cmd = [
            mock.call('SetPartition', 'expand', test_partition_id,
                      'size=%sGB' % test_expand_size),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_extend_volume_mb(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_new_size = 5.5
        test_expand_size = round((test_new_size - test_volume['size']) * 1024)

        mock_commands = {
            'SetPartition': SUCCEED,
        }
        self._driver_setup(mock_commands)

        self.driver.extend_volume(test_volume, test_new_size)

        expect_cli_cmd = [
            mock.call('SetPartition', 'expand', test_partition_id,
                      'size=%sMB' % test_expand_size),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    def test_extend_volume_fail(self):

        test_volume = self.cli_data.test_volume
        test_new_size = 10

        mock_commands = {
            'SetPartition': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.extend_volume,
            test_volume,
            test_new_size)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_terminate_connection(self):

        test_volume = self.cli_data.test_volume
        test_partition_id = self.cli_data.fake_partition_id[0]
        test_connector = self.cli_data.test_connector_iscsi

        mock_commands = {
            'DeleteMap': SUCCEED,
            'ShowMap': [self.cli_data.get_test_show_map(),
                        self.cli_data.get_test_show_empty_list()],
            'DeleteIQN': SUCCEED,
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        self.driver.terminate_connection(test_volume, test_connector)

        expect_cli_cmd = [
            mock.call('ShowDevice'),
            mock.call('ShowMap', 'part=%s' % test_partition_id),
            mock.call('DeleteMap',
                      'part', test_partition_id, '1', '0', '0', '-y'),
            mock.call('DeleteMap',
                      'part', test_partition_id, '1', '0', '1', '-y'),
            mock.call('DeleteMap',
                      'part', test_partition_id, '4', '0', '0', '-y'),
            mock.call('ShowMap'),
            mock.call('DeleteIQN', test_connector['initiator'][-16:]),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)

    def test_terminate_connection_fail(self):

        test_volume = self.cli_data.test_volume
        test_connector = self.cli_data.test_connector_iscsi

        mock_commands = {
            'DeleteMap': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.terminate_connection,
            test_volume,
            test_connector)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_migrate_volume(self):

        test_host = copy.deepcopy(self.cli_data.test_migrate_host)
        fake_pool = copy.deepcopy(self.cli_data.fake_pool)
        test_volume = self.cli_data.test_volume
        test_volume_id = test_volume['id']
        test_src_part_id = self.cli_data.fake_partition_id[0]
        test_dst_part_id = self.cli_data.fake_partition_id[2]
        test_pair_id = self.cli_data.fake_pair_id[0]
        test_model_update = {
            'provider_location': 'partition_id^%s@system_id^%s' % (
                test_dst_part_id,
                int(self.cli_data.fake_system_id[0], 16)
            )
        }

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(
                test_volume_id, fake_pool['pool_id']),
            'CreateReplica': SUCCEED,
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_migrate(
                    test_src_part_id, test_dst_part_id, test_volume_id),
            'DeleteReplica': SUCCEED,
            'DeleteMap': SUCCEED,
            'DeletePartition': SUCCEED,
        }
        self._driver_setup(mock_commands)
        self.driver.system_id = 'DEEC'

        rc, model_update = self.driver.migrate_volume(test_volume, test_host)

        expect_cli_cmd = [
            mock.call('CreatePartition',
                      fake_pool['pool_id'],
                      test_volume['id'],
                      'size=%s' % (test_volume['size'] * 1024),
                      ''),
            mock.call('ShowPartition'),
            mock.call('CreateReplica',
                      'Cinder-Migrate',
                      'part', test_src_part_id,
                      'part', test_dst_part_id,
                      'type=mirror'),
            mock.call('ShowReplica', '-l'),
            mock.call('DeleteReplica', test_pair_id, '-y'),
            mock.call('DeleteMap', 'part', test_src_part_id, '-y'),
            mock.call('DeletePartition', test_src_part_id, '-y'),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertTrue(rc)
        self.assertDictEqual(test_model_update, model_update)

    @mock.patch.object(common_cli.LOG, 'error')
    def test_migrate_volume_with_invalid_storage(self, log_error):

        fake_host = self.cli_data.fake_host
        test_volume = self.cli_data.test_volume

        mock_commands = {
            'ShowLV': self._mock_show_lv_for_migrate,
        }
        self._driver_setup(mock_commands)

        rc, model_update = self.driver.migrate_volume(test_volume, fake_host)

        self.assertFalse(rc)
        self.assertIsNone(model_update)
        self.assertEqual(1, log_error.call_count)

    @mock.patch('time.sleep')
    def test_migrate_volume_with_get_part_id_fail(self, mock_sleep):
        test_host = copy.deepcopy(self.cli_data.test_migrate_host)
        test_volume = self.cli_data.test_volume

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(),
            'DeleteMap': SUCCEED,
            'CreateReplica': SUCCEED,
            'CreateMap': SUCCEED,
            'ShowLV': self._mock_show_lv_for_migrate,
        }
        self._driver_setup(mock_commands)
        self.driver.system_id = 'DEEC'

        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.migrate_volume,
            test_volume,
            test_host)
        mock_sleep.assert_called()

    def test_migrate_volume_with_create_replica_fail(self):

        test_host = copy.deepcopy(self.cli_data.test_migrate_host)
        fake_pool = copy.deepcopy(self.cli_data.fake_pool)
        test_volume = self.cli_data.test_volume

        mock_commands = {
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(
                test_volume['id'], fake_pool['pool_id']),
            'DeleteMap': SUCCEED,
            'CreateReplica': FAKE_ERROR_RETURN,
            'CreateMap': SUCCEED,
            'ShowLV': self._mock_show_lv_for_migrate,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.migrate_volume,
            test_volume,
            test_host)

    def test_manage_existing_get_size(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume_with_id
        test_pool = self.cli_data.fake_lv_id[0]
        test_ref_volume_id = test_ref_volume['source-id']

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                'cinder-unmanaged-%s' % test_ref_volume_id[:-17], test_pool),
            'ShowMap': SUCCEED,
        }

        self._driver_setup(mock_commands)

        size = self.driver.manage_existing_get_size(
            test_volume, test_ref_volume)

        expect_cli_cmd = [
            mock.call('ShowPartition', '-l'),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertEqual(20, size)

    def test_manage_existing_get_size_with_name(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume_with_name
        test_pool = self.cli_data.fake_lv_id[0]

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                test_ref_volume['source-name'], test_pool),
            'ShowMap': SUCCEED,
        }

        self._driver_setup(mock_commands)

        size = self.driver.manage_existing_get_size(
            test_volume, test_ref_volume)

        expect_cli_cmd = [
            mock.call('ShowPartition', '-l'),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertEqual(20, size)

    def test_manage_existing_get_size_in_use(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume
        test_pool = self.cli_data.fake_lv_id[0]
        test_ref_volume_id = test_ref_volume['source-id']

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                'cinder-unmanaged-%s' % test_ref_volume_id[:-17], test_pool),
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            exception.VolumeDriverException,
            self.driver.manage_existing_get_size,
            test_volume,
            test_ref_volume)

    def test_manage_existing_get_size_no_source_id(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_dst_volume
        self.driver = self._get_driver(self.configuration)

        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size,
            test_volume,
            test_ref_volume)

    def test_manage_existing_get_size_show_part_fail(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume_with_id

        mock_commands = {
            'ShowPartition': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.manage_existing_get_size,
            test_volume,
            test_ref_volume)

    def test_manage_existing_get_size_with_not_exist(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume_with_id

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(),
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size,
            test_volume,
            test_ref_volume)

    @mock.patch.object(common_cli.LOG, 'info')
    def test_manage_existing(self, log_info):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume_with_id
        test_pool = self.cli_data.fake_lv_id[0]
        test_partition_id = self.cli_data.test_dst_volume['id']
        test_ref_volume_id = test_ref_volume['source-id']
        test_model_update = {
            'provider_location': 'partition_id^%s@system_id^%s' % (
                test_partition_id,
                int(self.cli_data.fake_system_id[0], 16)
            )
        }

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                'cinder-unmanaged-%s' % test_ref_volume_id[:-17], test_pool),
            'SetPartition': SUCCEED,
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.manage_existing(
            test_volume, test_ref_volume)

        expect_cli_cmd = [
            mock.call('ShowPartition', '-l'),
            mock.call('SetPartition', test_partition_id,
                      'name=%s' % test_volume['id']),
            mock.call('ShowDevice'),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertEqual(1, log_info.call_count)
        self.assertDictEqual(test_model_update, model_update)

    def test_manage_existing_rename_fail(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume_with_id
        test_pool = self.cli_data.fake_lv_id[0]
        test_ref_volume_id = test_ref_volume['source-id']

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                'cinder-unmanaged-%s' % test_ref_volume_id[:-17], test_pool),
            'SetPartition': FAKE_ERROR_RETURN,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            common_cli.InfortrendCliException,
            self.driver.manage_existing,
            test_volume,
            test_ref_volume)

    def test_manage_existing_with_part_not_found(self):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume_with_id

        mock_commands = {
            'ShowPartition':
                self.cli_data.get_test_show_partition_detail(),
            'SetPartition': SUCCEED,
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing,
            test_volume,
            test_ref_volume)

    @mock.patch.object(common_cli.LOG, 'info')
    def test_manage_existing_with_import(self, log_info):

        test_volume = self.cli_data.test_volume
        test_ref_volume = self.cli_data.test_ref_volume_with_name
        test_pool = self.cli_data.fake_lv_id[0]
        test_partition_id = self.cli_data.fake_partition_id[2]
        test_model_update = {
            'provider_location': 'partition_id^%s@system_id^%s' % (
                test_partition_id,
                int(self.cli_data.fake_system_id[0], 16)
            )
        }

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                test_ref_volume['source-name'], test_pool),
            'SetPartition': SUCCEED,
            'ShowDevice': self.cli_data.get_test_show_device(),
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.manage_existing(
            test_volume, test_ref_volume)

        expect_cli_cmd = [
            mock.call('SetPartition', test_partition_id,
                      'name=%s' % test_volume['id']),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertEqual(1, log_info.call_count)
        self.assertDictEqual(test_model_update, model_update)

    @mock.patch.object(common_cli.LOG, 'info')
    def test_unmanage(self, log_info):

        test_volume = self.cli_data.test_volume
        test_volume_id = test_volume['id']
        test_partition_id = self.cli_data.fake_partition_id[0]

        mock_commands = {
            'SetPartition': SUCCEED,
        }
        self._driver_setup(mock_commands)

        self.driver.unmanage(test_volume)

        expect_cli_cmd = [
            mock.call(
                'SetPartition',
                test_partition_id,
                'name=cinder-unmanaged-%s' % test_volume_id[:-17]),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertEqual(1, log_info.call_count)

    @mock.patch.object(common_cli.LOG, 'info')
    def test_retype_without_change(self, log_info):

        test_volume = self.cli_data.test_volume
        test_new_type = self.cli_data.test_new_type
        test_diff = {'extra_specs': {}}
        test_host = self.cli_data.test_migrate_host_2

        self.driver = self._get_driver(self.configuration)

        rc = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        self.assertTrue(rc)
        self.assertEqual(1, log_info.call_count)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_retype_with_change_global_provision(self, log_warning):

        test_volume = self.cli_data.test_volume
        test_new_type = self.cli_data.test_new_type
        test_diff = self.cli_data.test_diff
        test_host = self.cli_data.test_migrate_host_2

        self.driver = self._get_driver(self.configuration)

        rc = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        self.assertFalse(rc)
        self.assertEqual(1, log_warning.call_count)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_retype_with_change_individual_provision(self, log_warning):

        test_volume = self.cli_data.test_volume
        test_host = self.cli_data.test_migrate_host_2
        test_new_type = {
            'name': 'type1',
            'qos_specs_id': None,
            'deleted': False,
            'extra_specs': {
                'infortrend:provisioning': 'LV-1:thin',
            },
            'id': '28c8f82f-416e-148b-b1ae-2556c032d3c0',
        }
        test_diff = {
            'extra_specs': {
                'infortrend:provisioning': ('LV-2:thin;LV-1:full', 'LV-1:thin')
            }
        }

        self.driver = self._get_driver(self.configuration)

        rc = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        self.assertFalse(rc)
        self.assertEqual(1, log_warning.call_count)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_retype_with_change_mixed_provision(self, log_warning):

        test_volume = self.cli_data.test_volume
        test_host = self.cli_data.test_migrate_host_2
        test_new_type = {
            'name': 'type1',
            'qos_specs_id': None,
            'deleted': False,
            'extra_specs': {
                'infortrend:provisioning': 'LV-1:thin',
            },
            'id': '28c8f82f-416e-148b-b1ae-2556c032d3c0',
        }
        test_diff = {
            'extra_specs': {
                'infortrend:provisioning': ('full', 'LV-1:thin')
            }
        }

        self.driver = self._get_driver(self.configuration)

        rc = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        self.assertFalse(rc)
        self.assertEqual(1, log_warning.call_count)

    def test_retype_with_change_same_provision(self):

        test_volume = self.cli_data.test_volume
        test_host = self.cli_data.test_migrate_host_2
        test_new_type = {
            'name': 'type1',
            'qos_specs_id': None,
            'deleted': False,
            'extra_specs': {
                'infortrend:provisioning': 'LV-1:thin',
            },
            'id': '28c8f82f-416e-148b-b1ae-2556c032d3c0',
        }
        test_diff = {
            'extra_specs': {
                'infortrend:provisioning': ('thin', 'LV-1:thin')
            }
        }

        self.driver = self._get_driver(self.configuration)

        rc = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        self.assertTrue(rc)

    def test_retype_with_change_global_tier(self):

        test_volume = self.cli_data.test_volume
        test_host = self.cli_data.test_migrate_host_2
        test_new_type = {
            'name': 'type1',
            'qos_specs_id': None,
            'deleted': False,
            'extra_specs': {
                'infortrend:provisioning': 'thin',
                'infortrend:tiering': '2,3',
            },
            'id': '28c8f82f-416e-148b-b1ae-2556c032d3c0',
        }
        test_diff = {
            'extra_specs': {
                'infortrend:tiering': ('0,1', '2,3')
            }
        }

        mock_commands = {
            'ShowLV': self._mock_show_lv(),
            'SetPartition': SUCCEED,
            'SetLV': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition_detail(),
        }
        self._driver_setup(mock_commands)
        self.driver.tier_pools_dict = {
            self.cli_data.fake_lv_id[0]: [0, 1, 2, 3],
        }

        rc = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        self.assertTrue(rc)

    def test_retype_with_change_individual_tier(self):

        test_volume = self.cli_data.test_volume
        test_host = self.cli_data.test_migrate_host_2
        test_new_type = {
            'name': 'type1',
            'qos_specs_id': None,
            'deleted': False,
            'extra_specs': {
                'infortrend:provisioning': 'thin',
                'infortrend:tiering': 'LV-1:2,3',
            },
            'id': '28c8f82f-416e-148b-b1ae-2556c032d3c0',
        }
        test_diff = {
            'extra_specs': {
                'infortrend:tiering': ('LV-1:0,1', 'LV-1:2,3')
            }
        }

        mock_commands = {
            'ShowLV': self._mock_show_lv(),
            'SetPartition': SUCCEED,
            'SetLV': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition_detail(),
        }
        self._driver_setup(mock_commands)
        self.driver.tier_pools_dict = {
            self.cli_data.fake_lv_id[0]: [0, 1, 2, 3],
        }

        rc = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        self.assertTrue(rc)

    def test_retype_change_tier_with_multi_settings(self):

        test_volume = self.cli_data.test_volume
        test_host = self.cli_data.test_migrate_host_2
        test_new_type = {
            'name': 'type1',
            'qos_specs_id': None,
            'deleted': False,
            'extra_specs': {
                'infortrend:provisioning': 'thin',
                'infortrend:tiering': 'LV-2:0;LV-1:2,3',
            },
            'id': '28c8f82f-416e-148b-b1ae-2556c032d3c0',
        }
        test_diff = {
            'extra_specs': {
                'infortrend:tiering': ('LV-1:0,1', 'LV-2:0;LV-1:2,3')
            }
        }

        mock_commands = {
            'ShowLV': self._mock_show_lv(),
            'SetPartition': SUCCEED,
            'SetLV': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition_detail(),
        }
        self._driver_setup(mock_commands)
        self.driver.tier_pools_dict = {
            self.cli_data.fake_lv_id[0]: [0, 1, 2, 3],
        }

        rc = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        self.assertTrue(rc)

    def test_retype_change_with_tier_not_exist(self):

        test_volume = self.cli_data.test_volume
        test_host = self.cli_data.test_migrate_host_2
        test_new_type = {
            'name': 'type1',
            'qos_specs_id': None,
            'deleted': False,
            'extra_specs': {
                'infortrend:provisioning': 'thin',
                'infortrend:tiering': 'LV-2:0;LV-1:2,3',
            },
            'id': '28c8f82f-416e-148b-b1ae-2556c032d3c0',
        }
        test_diff = {
            'extra_specs': {
                'infortrend:tiering': ('LV-1:0,1', 'LV-2:0;LV-1:2,3')
            }
        }

        mock_commands = {
            'ShowLV': self._mock_show_lv(),
        }
        self._driver_setup(mock_commands)
        self.driver.tier_pools_dict = {
            self.cli_data.fake_lv_id[0]: [0, 1, 2],
        }

        self.assertRaises(
            exception.VolumeDriverException,
            self.driver.retype,
            None, test_volume, test_new_type,
            test_diff, test_host)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_retype_change_with_not_a_tier_pool(self, log_warning):

        test_volume = self.cli_data.test_volume
        test_host = self.cli_data.test_migrate_host_2
        test_new_type = {
            'name': 'type1',
            'qos_specs_id': None,
            'deleted': False,
            'extra_specs': {
                'infortrend:provisioning': 'full',
                'infortrend:tiering': 'LV-1:2',
            },
            'id': '28c8f82f-416e-148b-b1ae-2556c032d3c0',
        }
        test_diff = {
            'extra_specs': {
                'infortrend:tiering': ('', 'LV-1:2')
            }
        }

        mock_commands = {
            'ShowLV': self._mock_show_lv(),
        }
        self._driver_setup(mock_commands)
        self.driver.tier_pools_dict = {
            self.cli_data.fake_lv_id[2]: [0, 1, 2],
        }

        rc = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        self.assertTrue(rc)
        self.assertEqual(1, log_warning.call_count)

    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_retype_with_migrate(self):

        fake_pool = copy.deepcopy(self.cli_data.fake_pool)
        test_host = copy.deepcopy(self.cli_data.test_migrate_host)
        test_volume = self.cli_data.test_volume
        test_volume_id = test_volume['id']
        test_new_type = self.cli_data.test_new_type
        test_diff = self.cli_data.test_diff
        test_src_part_id = self.cli_data.fake_partition_id[0]
        test_dst_part_id = self.cli_data.fake_partition_id[2]
        test_pair_id = self.cli_data.fake_pair_id[0]
        test_model_update = {
            'provider_location': 'partition_id^%s@system_id^%s' % (
                test_dst_part_id,
                int(self.cli_data.fake_system_id[0], 16)
            )
        }

        mock_commands = {
            'ShowSnapshot': SUCCEED,
            'CreatePartition': SUCCEED,
            'ShowPartition': self.cli_data.get_test_show_partition(
                test_volume_id, fake_pool['pool_id']),
            'CreateReplica': SUCCEED,
            'ShowReplica':
                self.cli_data.get_test_show_replica_detail_for_migrate(
                    test_src_part_id, test_dst_part_id, test_volume_id),
            'DeleteReplica': SUCCEED,
            'DeleteMap': SUCCEED,
            'DeletePartition': SUCCEED,
        }
        self._driver_setup(mock_commands)
        self.driver.system_id = 'DEEC'

        rc, model_update = self.driver.retype(
            None, test_volume, test_new_type, test_diff, test_host)

        min_size = int(test_volume['size'] * 1024 * 0.2)
        create_params = 'init=disable min=%sMB' % min_size
        expect_cli_cmd = [
            mock.call('ShowSnapshot', 'part=%s' % test_src_part_id),
            mock.call(
                'CreatePartition',
                fake_pool['pool_id'],
                test_volume['id'],
                'size=%s' % (test_volume['size'] * 1024),
                create_params,
            ),
            mock.call('ShowPartition'),
            mock.call(
                'CreateReplica',
                'Cinder-Migrate',
                'part', test_src_part_id,
                'part', test_dst_part_id,
                'type=mirror'
            ),
            mock.call('ShowReplica', '-l'),
            mock.call('DeleteReplica', test_pair_id, '-y'),
            mock.call('DeleteMap', 'part', test_src_part_id, '-y'),
            mock.call('DeletePartition', test_src_part_id, '-y'),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertTrue(rc)
        self.assertDictEqual(test_model_update, model_update)

    @mock.patch.object(common_cli.LOG, 'debug', mock.Mock())
    @mock.patch.object(common_cli.LOG, 'info', mock.Mock())
    def test_update_migrated_volume(self):
        src_volume = self.cli_data.test_volume
        dst_volume = copy.deepcopy(self.cli_data.test_dst_volume)
        test_dst_part_id = self.cli_data.fake_partition_id[1]
        dst_volume['provider_location'] = 'partition_id^%s@system_id^%s' % (
            test_dst_part_id, int(self.cli_data.fake_system_id[0], 16))
        test_model_update = {
            '_name_id': None,
            'provider_location': dst_volume['provider_location'],
        }

        mock_commands = {
            'SetPartition': SUCCEED,
        }
        self._driver_setup(mock_commands)

        model_update = self.driver.update_migrated_volume(
            None, src_volume, dst_volume, 'available')

        expect_cli_cmd = [
            mock.call('SetPartition', test_dst_part_id,
                      'name=%s' % src_volume['id']),
        ]
        self._assert_cli_has_calls(expect_cli_cmd)
        self.assertDictEqual(test_model_update, model_update)

    @mock.patch.object(common_cli.LOG, 'debug', mock.Mock())
    def test_update_migrated_volume_rename_fail(self):
        src_volume = self.cli_data.test_volume
        dst_volume = self.cli_data.test_dst_volume
        dst_volume['_name_id'] = 'fake_name_id'
        test_dst_part_id = self.cli_data.fake_partition_id[1]
        dst_volume['provider_location'] = 'partition_id^%s@system_id^%s' % (
            test_dst_part_id, int(self.cli_data.fake_system_id[0], 16))

        mock_commands = {
            'SetPartition': FAKE_ERROR_RETURN
        }
        self._driver_setup(mock_commands)
        model_update = self.driver.update_migrated_volume(
            None, src_volume, dst_volume, 'available')
        self.assertEqual({'_name_id': 'fake_name_id'}, model_update)

    def test_get_extraspecs_set_with_default_setting(self):
        test_extraspecs = {}

        test_result = {
            'global_provisioning': 'full',
            'global_tiering': 'all',
        }

        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)

    def test_get_extraspecs_set_with_global_settings(self):
        test_extraspecs = {
            'infortrend:tiering': '1,2',
            'infortrend:provisioning': 'thin',
        }

        test_result = {
            'global_provisioning': 'thin',
            'global_tiering': [1, 2],
        }
        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)

    def test_get_extraspecs_set_with_tier_global_settings(self):
        test_extraspecs = {
            'infortrend:tiering': '1,2',
        }

        test_result = {
            'global_provisioning': 'full',
            'global_tiering': [1, 2],
        }
        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)

    def test_get_extraspecs_set_with_provision_global_settings(self):
        test_extraspecs = {
            'infortrend:provisioning': 'thin',
        }

        test_result = {
            'global_provisioning': 'thin',
            'global_tiering': 'all',
        }
        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)

    def test_get_extraspecs_set_with_individual_tier_settings(self):
        test_extraspecs = {
            'infortrend:tiering': 'LV-0:0;LV-1:1,2',
        }

        test_result = {
            'global_provisioning': 'full',
            'global_tiering': 'all',
            'LV-0': {
                'tiering': [0],
            },
            'LV-1': {
                'tiering': [1, 2],
            },
        }
        self.driver = self._get_driver(self.configuration)
        self.driver.pool_dict = {'LV-0': '', 'LV-1': '', 'LV-2': ''}
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_get_extraspecs_set_with_lv0_not_set_in_config(self, log_warning):
        test_extraspecs = {
            'infortrend:tiering': 'LV-0:0;LV-1:1,2',
        }

        test_result = {
            'global_provisioning': 'full',
            'global_tiering': 'all',
            'LV-1': {
                'tiering': [1, 2],
            },
        }
        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)
        self.assertEqual(1, log_warning.call_count)

    def test_get_extraspecs_set_with_individual_provision_settings(self):
        test_extraspecs = {
            'infortrend:provisioning': 'LV-1:FULL; LV-2:Thin',
        }

        test_result = {
            'global_provisioning': 'full',
            'global_tiering': 'all',
            'LV-1': {
                'provisioning': 'full',
            },
            'LV-2': {
                'provisioning': 'thin',
            },
        }
        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)

    def test_get_extraspecs_set_with_mixed_settings(self):
        test_extraspecs = {
            'infortrend:provisioning': 'LV-1:FULL; LV-2:Thin',
            'infortrend:tiering': '1,2',
        }

        test_result = {
            'global_provisioning': 'full',
            'global_tiering': [1, 2],
            'LV-1': {
                'provisioning': 'full',
            },
            'LV-2': {
                'provisioning': 'thin',
            },
        }
        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_get_extraspecs_set_with_err_tier(self, log_warning):
        test_extraspecs = {
            'infortrend:provisioning': 'LV-1:FULL; LV-2:Thin',
            'infortrend:tiering': 'LV-1:4,3; LV-2:-1,0',
        }

        test_result = {
            'global_provisioning': 'full',
            'global_tiering': 'all',
            'LV-1': {
                'provisioning': 'full',
                'tiering': 'Err:[3, 4]',
            },
            'LV-2': {
                'provisioning': 'thin',
                'tiering': 'Err:[0, -1]',
            },
        }
        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)
        self.assertEqual(2, log_warning.call_count)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_get_extraspecs_set_with_err_provision(self, log_warning):
        test_extraspecs = {
            'infortrend:provisioning': 'LV-1:FOO; LV-2:Bar',
            'infortrend:tiering': '1,2',
        }

        test_result = {
            'global_provisioning': 'full',
            'global_tiering': [1, 2],
            'LV-1': {
                'provisioning': 'Err:FOO',
            },
            'LV-2': {
                'provisioning': 'Err:Bar',
            },
        }
        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_extraspecs_set(test_extraspecs)

        self.assertEqual(test_result, result)
        self.assertEqual(2, log_warning.call_count)

    def test_get_pool_extraspecs_global(self):
        test_extraspecs_set = {
            'global_provisioning': 'full',
            'global_tiering': 'all',
            'LV-2': {
                'provisioning': 'thin',
            },
        }

        test_result = {
            'provisioning': 'full',
            'tiering': 'all',
        }

        self.driver = self._get_driver(self.configuration)
        result = self.driver._get_pool_extraspecs(
            'LV-1', test_extraspecs_set)

        self.assertEqual(test_result, result)

    def test_get_pool_extraspecs_individual(self):
        test_extraspecs_set = {
            'global_provisioning': 'full',
            'global_tiering': [1, 2],
            'LV-1': {
                'provisioning': 'full',
                'tiering': [0],
            },
            'LV-2': {
                'provisioning': 'thin',
            },
        }

        test_result = {
            'provisioning': 'full',
            'tiering': [0],
        }

        mock_commands = {
            'ShowLV': self._mock_show_lv(),
        }
        self._driver_setup(mock_commands)

        result = self.driver._get_pool_extraspecs(
            'LV-1', test_extraspecs_set)

        self.assertEqual(test_result, result)

    def test_get_pool_extraspecs_mixed(self):
        test_extraspecs_set = {
            'global_provisioning': 'full',
            'global_tiering': [1, 2],
            'LV-1': {
                'provisioning': 'full',
            },
            'LV-2': {
                'provisioning': 'thin',
            },
        }

        test_result = {
            'provisioning': 'thin',
            'tiering': [1, 2],
        }
        mock_commands = {
            'ShowLV': self._mock_show_lv(),
        }
        self._driver_setup(mock_commands)

        result = self.driver._get_pool_extraspecs(
            'LV-2', test_extraspecs_set)

        self.assertEqual(test_result, result)

    def test_get_pool_extraspecs_conflict(self):
        test_extraspecs_set = {
            'global_provisioning': 'full',
            'global_tiering': [1, 2],
            'LV-1': {
                'provisioning': 'full',
            },
            'LV-2': {
                'provisioning': 'thin',
            },
        }

        mock_commands = {
            'ShowLV': self._mock_show_lv(),
        }
        self._driver_setup(mock_commands)

        self.assertRaises(
            exception.VolumeDriverException,
            self.driver._get_pool_extraspecs,
            'LV-1', test_extraspecs_set)

    def test_get_manageable_volumes(self):
        fake_cinder_volumes = self.cli_data.fake_cinder_volumes

        mock_commands = {
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                volume_id='hello-there',
                pool_id=self.cli_data.fake_lv_id[2])
        }

        ans = [{
            'reference': {
                'source-name': self.cli_data.fake_volume_id[0],
                'source-id': self.cli_data.fake_partition_id[0],
                'pool-name': 'LV-1'
            },
            'size': 20,
            'safe_to_manage': False,
            'reason_not_safe': 'Volume In-use',
            'cinder_id': None,
            'extra_info': None
        }, {
            'reference': {
                'source-name': self.cli_data.fake_volume_id[1],
                'source-id': self.cli_data.fake_partition_id[1],
                'pool-name': 'LV-1'
            },
            'size': 20,
            'safe_to_manage': False,
            'reason_not_safe': 'Already Managed',
            'cinder_id': self.cli_data.fake_volume_id[1],
            'extra_info': None
        }, {
            'reference': {
                'source-name': 'hello-there',
                'source-id': '6bb119a8-d25b-45a7-8d1b-88e127885666',
                'pool-name': 'LV-1'
            },
            'size': 20,
            'safe_to_manage': True,
            'reason_not_safe': None,
            'cinder_id': None,
            'extra_info': None
        }]

        self._driver_setup(mock_commands)
        result = self.driver.get_manageable_volumes(fake_cinder_volumes,
                                                    None, 1000, 0,
                                                    ['reference'], ['desc'])
        ans = volume_utils.paginate_entries_list(ans, None, 1000, 0,
                                                 ['reference'], ['desc'])
        self.assertEqual(ans, result)

    def test_get_manageable_snapshots(self):
        fake_cinder_snapshots = self.cli_data.fake_cinder_snapshots

        mock_commands = {
            'ShowSnapshot':
                self.cli_data.get_test_show_snapshot_get_manage(),
            'ShowPartition': self.cli_data.get_test_show_partition_detail(
                volume_id='hello-there',
                pool_id=self.cli_data.fake_lv_id[2])
        }

        self._driver_setup(mock_commands)

        ans = [{
            'reference': {
                'source-id': self.cli_data.fake_snapshot_id[0],
                'source-name': self.cli_data.fake_snapshot_name[0],
            },
            'size': 20,
            'safe_to_manage': False,
            'reason_not_safe': 'Volume In-use',
            'cinder_id': None,
            'extra_info': None,
            'source_reference': {
                'volume-id': self.cli_data.fake_volume_id[0]
            }
        }, {
            'reference': {
                'source-id': self.cli_data.fake_snapshot_id[1],
                'source-name': self.cli_data.fake_snapshot_name[1],
            },
            'size': 20,
            'safe_to_manage': False,
            'reason_not_safe': 'Already Managed',
            'cinder_id': self.cli_data.fake_snapshot_name[1],
            'extra_info': None,
            'source_reference': {
                'volume-id': self.cli_data.fake_volume_id[1]
            }
        }, {
            'reference': {
                'source-id': self.cli_data.fake_snapshot_id[2],
                'source-name': self.cli_data.fake_snapshot_name[2],
            },
            'size': 20,
            'safe_to_manage': True,
            'reason_not_safe': None,
            'cinder_id': None,
            'extra_info': None,
            'source_reference': {
                'volume-id': 'hello-there'
            }
        }]

        result = self.driver.get_manageable_snapshots(fake_cinder_snapshots,
                                                      None, 1000, 0,
                                                      ['reference'], ['desc'])
        ans = volume_utils.paginate_entries_list(ans, None, 1000, 0,
                                                 ['reference'], ['desc'])
        self.assertEqual(ans, result)

    def test_manage_existing_snapshot(self):
        fake_snapshot = self.cli_data.fake_cinder_snapshots[0]
        fake_ref_from_id = {
            'source-id': self.cli_data.fake_snapshot_id[1]
        }
        fake_ref_from_name = {
            'source-name': self.cli_data.fake_snapshot_name[1]
        }

        mock_commands = {
            'ShowSnapshot': self.cli_data.get_test_show_snapshot_named(),
            'SetSnapshot': (0, None)
        }

        ans = {'provider_location': self.cli_data.fake_snapshot_id[1]}

        self._driver_setup(mock_commands)
        result_from_id = self.driver.manage_existing_snapshot(
            fake_snapshot, fake_ref_from_id)
        result_from_name = self.driver.manage_existing_snapshot(
            fake_snapshot, fake_ref_from_name)

        self.assertEqual(ans, result_from_id)
        self.assertEqual(ans, result_from_name)

    @mock.patch.object(common_cli.LOG, 'warning')
    def test_get_snapshot_ref_data_err_and_warning(self, mock_warning):
        fake_snapshot = self.cli_data.fake_cinder_snapshots[0]
        fake_ref_err1 = {
            'invalid-key': 'invalid-content'
        }
        fake_ref_err2 = {
            'source-id': 'invalid-content'
        }
        fake_ref_err_and_warning = {
            'source-name': '---'
        }

        mock_commands = {
            'ShowSnapshot': self.cli_data.get_test_show_snapshot_named()
        }

        self._driver_setup(mock_commands)

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          fake_snapshot, fake_ref_err1)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          fake_snapshot, fake_ref_err2)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_snapshot,
                          fake_snapshot, fake_ref_err_and_warning)
        self.assertEqual(1, mock_warning.call_count)

    def test_manage_existing_snapshot_get_size(self):
        fake_snapshot = self.cli_data.fake_cinder_snapshots[0]
        fake_ref = {
            'source-id': self.cli_data.fake_snapshot_id[1]
        }

        mock_commands = {
            'ShowSnapshot': self.cli_data.get_test_show_snapshot_named(),
            'ShowPartition': self.cli_data.get_test_show_partition()
        }

        self._driver_setup(mock_commands)

        result = self.driver.manage_existing_snapshot_get_size(fake_snapshot,
                                                               fake_ref)
        self.assertEqual(20, result)

    def test_unmanage_snapshot(self):
        fake_snapshot = self.cli_data.Fake_cinder_snapshot(
            self.cli_data.fake_snapshot_name[1],
            self.cli_data.fake_snapshot_id[1]
        )

        mock_commands = {
            'SetSnapshot': (0, None),
        }

        expect_cli_cmd = [
            mock.call(
                'SetSnapshot', self.cli_data.fake_snapshot_id[1],
                'name=cinder-unmanaged-%s' %
                self.cli_data.fake_snapshot_name[1][:-17]
            )
        ]
        self._driver_setup(mock_commands)
        self.driver.unmanage_snapshot(fake_snapshot)
        self._assert_cli_has_calls(expect_cli_cmd)
