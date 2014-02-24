#    (c) Copyright 2014 Brocade Communications Systems Inc.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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


"""Unit tests for Volume Manager."""

import mock

from cinder import exception
from cinder import test
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.driver import VolumeDriver
from cinder.volume.manager import VolumeManager
from cinder.zonemanager.fc_zone_manager import ZoneManager
from mock import Mock
from mock import patch

init_target_map = {'10008c7cff523b01': ['20240002ac000a50']}
conn_info = {
    'driver_volume_type': 'fibre_channel',
    'data': {
        'target_discovered': True,
        'target_lun': 1,
        'target_wwn': '20240002ac000a50',
        'initiator_target_map': {
            '10008c7cff523b01': ['20240002ac000a50']
        }
    }
}
conn_info_no_init_target_map = {
    'driver_volume_type': 'fibre_channel',
    'data': {
        'target_discovered': True,
        'target_lun': 1,
        'target_wwn': '20240002ac000a50',
    }
}


class TestVolumeManager(VolumeManager, test.TestCase):

    def setUp(self):
        super(TestVolumeManager, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.set_default('fc_fabric_names', 'BRCD_FAB_4')
        self.configuration.zoning_mode = 'fabric'
        self.driver = Mock(VolumeDriver)
        self.driver.initialize_connection.return_value = conn_info
        self.driver.terminate_connection.return_value = conn_info
        self.driver.create_export.return_value = None
        self.db = Mock()
        self.db.volume_get.return_value = {'volume_type_id': None}
        self.db.volume_admin_metadata_get.return_value = {}
        self.context_mock = Mock()
        self.context_mock.elevated.return_value = None

    def __init__(self, *args, **kwargs):
        test.TestCase.__init__(self, *args, **kwargs)

    @patch.object(utils, 'require_driver_initialized')
    def test_initialize_connection_voltype_fc_mode_fabric(self,
                                                          utils_mock):
        utils_mock.return_value = True
        with mock.patch.object(VolumeManager, '_add_or_delete_fc_connection')\
                as add_del_conn_mock:
            self.initialize_connection(self.context_mock, None, None)
            add_del_conn_mock.assert_called_once_with(conn_info, 1)

    @patch.object(utils, 'require_driver_initialized')
    def test_initialize_connection_voltype_fc_mode_none(self,
                                                        utils_mock):
        utils_mock.return_value = True
        with mock.patch.object(VolumeManager, '_add_or_delete_fc_connection')\
                as add_del_conn_mock:
            self.configuration.zoning_mode = 'none'
            self.initialize_connection(self.context_mock, None, None)
            assert not add_del_conn_mock.called

    def test_terminate_connection_exception(self):
        with mock.patch.object(VolumeManager, '_add_or_delete_fc_connection')\
                as add_del_conn_mock:
            add_del_conn_mock.side_effect = exception.ZoneManagerException
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.terminate_connection, None, None, None,
                              False)

    @patch.object(utils, 'require_driver_initialized')
    def test_terminate_connection_voltype_fc_mode_fabric(self,
                                                         utils_mock):
        utils_mock.return_value = True
        with mock.patch.object(VolumeManager, '_add_or_delete_fc_connection')\
                as add_del_conn_mock:
            self.terminate_connection(None, None, None, False)
            add_del_conn_mock.assert_called_once_with(conn_info, 0)

    @patch.object(utils, 'require_driver_initialized')
    def test_terminate_connection_mode_none(self,
                                            utils_mock):
        utils_mock.return_value = True
        with mock.patch.object(VolumeManager, '_add_or_delete_fc_connection')\
                as add_del_conn_mock:
            self.configuration.zoning_mode = 'none'
            self.terminate_connection(None, None, None, False)
            assert not add_del_conn_mock.called

    @patch.object(utils, 'require_driver_initialized')
    def test_terminate_connection_conn_info_none(self,
                                                 utils_mock):
        utils_mock.return_value = True
        self.driver.terminate_connection.return_value = None
        with mock.patch.object(VolumeManager, '_add_or_delete_fc_connection')\
                as add_del_conn_mock:
            self.terminate_connection(None, None, None, False)
            assert not add_del_conn_mock.called

    @patch.object(ZoneManager, 'add_connection')
    def test__add_or_delete_connection_add(self,
                                           add_connection_mock):
        self._add_or_delete_fc_connection(conn_info, 1)
        add_connection_mock.assert_called_once_with(init_target_map)

    @patch.object(ZoneManager, 'delete_connection')
    def test__add_or_delete_connection_delete(self,
                                              delete_connection_mock):
        self._add_or_delete_fc_connection(conn_info, 0)
        delete_connection_mock.assert_called_once_with(init_target_map)

    @patch.object(ZoneManager, 'delete_connection')
    def test__add_or_delete_connection_no_init_target_map(self,
                                                          del_conn_mock):
        self._add_or_delete_fc_connection(conn_info_no_init_target_map, 0)
        assert not del_conn_mock.called
