# Copyright (c) 2015 Alex Meade.  All rights reserved.
# Copyright (c) 2015 Michael Price.  All rights reserved.
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

import abc
import copy
import ddt
import mock
import socket

from cinder import exception
from cinder.volume import configuration as conf

from cinder.tests.unit.volume.drivers.netapp.eseries import fakes as \
    fakes
from cinder.volume.drivers.netapp import common
from cinder.volume.drivers.netapp.eseries import client
from cinder.volume.drivers.netapp.eseries import library
from cinder.volume.drivers.netapp.eseries import utils
from cinder.volume.drivers.netapp import options
import cinder.volume.drivers.netapp.utils as na_utils


@ddt.ddt
class NetAppESeriesDriverTestCase(object):
    """Test case for NetApp e-series iscsi driver."""

    volume = {'id': '114774fb-e15a-4fae-8ee2-c9723e3645ef', 'size': 1,
              'volume_name': 'lun1', 'host': 'hostname@backend#DDP',
              'os_type': 'linux', 'provider_location': 'lun1',
              'name_id': '114774fb-e15a-4fae-8ee2-c9723e3645ef',
              'provider_auth': 'provider a b', 'project_id': 'project',
              'display_name': None, 'display_description': 'lun1',
              'volume_type_id': None}
    snapshot = {'id': '17928122-553b-4da9-9737-e5c3dcd97f75',
                'volume_id': '114774fb-e15a-4fae-8ee2-c9723e3645ef',
                'size': 2, 'volume_name': 'lun1',
                'volume_size': 2, 'project_id': 'project',
                'display_name': None, 'display_description': 'lun1',
                'volume_type_id': None}
    volume_sec = {'id': 'b6c01641-8955-4917-a5e3-077147478575',
                  'size': 2, 'volume_name': 'lun1',
                  'os_type': 'linux', 'provider_location': 'lun1',
                  'name_id': 'b6c01641-8955-4917-a5e3-077147478575',
                  'provider_auth': None, 'project_id': 'project',
                  'display_name': None, 'display_description': 'lun1',
                  'volume_type_id': None}
    volume_clone = {'id': 'b4b24b27-c716-4647-b66d-8b93ead770a5', 'size': 3,
                    'volume_name': 'lun1',
                    'os_type': 'linux', 'provider_location': 'cl_sm',
                    'name_id': 'b4b24b27-c716-4647-b66d-8b93ead770a5',
                    'provider_auth': None,
                    'project_id': 'project', 'display_name': None,
                    'display_description': 'lun1',
                    'volume_type_id': None}
    volume_clone_large = {'id': 'f6ef5bf5-e24f-4cbb-b4c4-11d631d6e553',
                          'size': 6, 'volume_name': 'lun1',
                          'os_type': 'linux', 'provider_location': 'cl_lg',
                          'name_id': 'f6ef5bf5-e24f-4cbb-b4c4-11d631d6e553',
                          'provider_auth': None,
                          'project_id': 'project', 'display_name': None,
                          'display_description': 'lun1',
                          'volume_type_id': None}
    fake_eseries_volume_label = utils.convert_uuid_to_es_fmt(volume['id'])
    fake_size_gb = volume['size']
    fake_eseries_pool_label = 'DDP'
    fake_ref = {'source-name': 'CFDGJSLS'}
    fake_ret_vol = {'id': 'vol_id', 'label': 'label',
                    'worldWideName': 'wwn', 'capacity': '2147583648'}
    PROTOCOL = 'iscsi'

    def setUp(self):
        super(NetAppESeriesDriverTestCase, self).setUp()
        self._custom_setup()

    def _custom_setup(self):
        self.mock_object(na_utils, 'OpenStackInfo')

        configuration = self._set_config(self.create_configuration())
        self.driver = common.NetAppDriver(configuration=configuration)
        self.library = self.driver.library
        self.mock_object(self.library,
                         '_check_mode_get_or_register_storage_system')
        self.mock_object(self.library, '_version_check')
        self.mock_object(self.driver.library, '_check_storage_system')
        self.driver.do_setup(context='context')
        self.driver.library._client._endpoint = fakes.FAKE_ENDPOINT_HTTP
        self.driver.library._client.features = mock.Mock()
        self.driver.library._client.features.REST_1_4_RELEASE = True

    def _set_config(self, configuration):
        configuration.netapp_storage_family = 'eseries'
        configuration.netapp_storage_protocol = self.PROTOCOL
        configuration.netapp_transport_type = 'http'
        configuration.netapp_server_hostname = '127.0.0.1'
        configuration.netapp_server_port = None
        configuration.netapp_webservice_path = '/devmgr/vn'
        configuration.netapp_controller_ips = '127.0.0.2,127.0.0.3'
        configuration.netapp_sa_password = 'pass1234'
        configuration.netapp_login = 'rw'
        configuration.netapp_password = 'rw'
        configuration.netapp_storage_pools = 'DDP'
        configuration.netapp_enable_multiattach = False
        return configuration

    @staticmethod
    def create_configuration():
        configuration = conf.Configuration(None)
        configuration.append_config_values(options.netapp_basicauth_opts)
        configuration.append_config_values(options.netapp_eseries_opts)
        configuration.append_config_values(options.netapp_san_opts)
        return configuration

    @abc.abstractmethod
    @mock.patch.object(na_utils, 'validate_instantiation')
    def test_instantiation(self, mock_validate_instantiation):
        pass

    def test_embedded_mode(self):
        self.mock_object(client.RestClient, '_init_features')
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_controller_ips = '127.0.0.1,127.0.0.3'
        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(driver.library, '_version_check')
        self.mock_object(client.RestClient, 'list_storage_systems',
                         return_value=[fakes.STORAGE_SYSTEM])
        driver.do_setup(context='context')

        self.assertEqual('1fa6efb5-f07b-4de4-9f0e-52e5f7ff5d1b',
                         driver.library._client.get_system_id())

    def test_check_system_pwd_not_sync(self):
        def list_system():
            if getattr(self, 'test_count', None):
                self.test_count = 1
                return {'status': 'passwordoutofsync'}
            return {'status': 'needsAttention'}

        self.library._client.list_storage_system = mock.Mock(wraps=list_system)
        result = self.library._check_storage_system()
        self.assertTrue(result)

    def test_create_destroy(self):
        self.mock_object(client.RestClient, 'delete_volume',
                         return_value='None')
        self.mock_object(self.driver.library, 'create_volume',
                         return_value=self.volume)
        self.mock_object(self.library._client, 'list_volume',
                         return_value=fakes.VOLUME)

        self.driver.create_volume(self.volume)
        self.driver.delete_volume(self.volume)

    def test_vol_stats(self):
        self.driver.get_volume_stats(refresh=False)

    def test_get_pool(self):
        self.mock_object(self.library, '_get_volume',
                         return_value={'volumeGroupRef': 'fake_ref'})
        self.mock_object(self.library._client, "get_storage_pool",
                         return_value={'volumeGroupRef': 'fake_ref',
                                       'label': 'ddp1'})

        pool = self.driver.get_pool({'name_id': 'fake-uuid'})

        self.assertEqual('ddp1', pool)

    def test_get_pool_no_pools(self):
        self.mock_object(self.library, '_get_volume',
                         return_value={'volumeGroupRef': 'fake_ref'})
        self.mock_object(self.library._client, "get_storage_pool",
                         return_value=None)

        pool = self.driver.get_pool({'name_id': 'fake-uuid'})

        self.assertIsNone(pool)

    @mock.patch.object(library.NetAppESeriesLibrary, '_create_volume',
                       mock.Mock())
    def test_create_volume(self):

        self.driver.create_volume(self.volume)

        self.library._create_volume.assert_called_with(
            'DDP', self.fake_eseries_volume_label, self.volume['size'], {})

    def test_create_volume_no_pool_provided_by_scheduler(self):
        volume = copy.deepcopy(self.volume)
        volume['host'] = "host@backend"  # missing pool
        self.assertRaises(exception.InvalidHost, self.driver.create_volume,
                          volume)

    @mock.patch.object(client.RestClient, 'list_storage_pools')
    def test_helper_create_volume_fail(self, fake_list_pools):
        fake_pool = {}
        fake_pool['label'] = self.fake_eseries_pool_label
        fake_pool['volumeGroupRef'] = 'foo'
        fake_pool['raidLevel'] = 'raidDiskPool'
        fake_pools = [fake_pool]
        fake_list_pools.return_value = fake_pools
        wrong_eseries_pool_label = 'hostname@backend'
        self.assertRaises(exception.NetAppDriverException,
                          self.library._create_volume,
                          wrong_eseries_pool_label,
                          self.fake_eseries_volume_label,
                          self.fake_size_gb)

    @mock.patch.object(library.LOG, 'info')
    @mock.patch.object(client.RestClient, 'list_storage_pools')
    @mock.patch.object(client.RestClient, 'create_volume',
                       mock.MagicMock(return_value='CorrectVolume'))
    def test_helper_create_volume(self, storage_pools, log_info):
        fake_pool = {}
        fake_pool['label'] = self.fake_eseries_pool_label
        fake_pool['volumeGroupRef'] = 'foo'
        fake_pool['raidLevel'] = 'raidDiskPool'
        fake_pools = [fake_pool]
        storage_pools.return_value = fake_pools
        storage_vol = self.library._create_volume(
            self.fake_eseries_pool_label,
            self.fake_eseries_volume_label,
            self.fake_size_gb)
        log_info.assert_called_once_with("Created volume with label %s.",
                                         self.fake_eseries_volume_label)
        self.assertEqual('CorrectVolume', storage_vol)

    @mock.patch.object(client.RestClient, 'list_storage_pools')
    @mock.patch.object(client.RestClient, 'create_volume',
                       mock.MagicMock(
                           side_effect=exception.NetAppDriverException))
    @mock.patch.object(library.LOG, 'info', mock.Mock())
    def test_create_volume_check_exception(self, fake_list_pools):
        fake_pool = {}
        fake_pool['label'] = self.fake_eseries_pool_label
        fake_pool['volumeGroupRef'] = 'foo'
        fake_pool['raidLevel'] = 'raidDiskPool'
        fake_pools = [fake_pool]
        fake_list_pools.return_value = fake_pools
        self.assertRaises(exception.NetAppDriverException,
                          self.library._create_volume,
                          self.fake_eseries_pool_label,
                          self.fake_eseries_volume_label, self.fake_size_gb)

    def test_portal_for_vol_controller(self):
        volume = {'id': 'vol_id', 'currentManager': 'ctrl1'}
        vol_nomatch = {'id': 'vol_id', 'currentManager': 'ctrl3'}
        portals = [{'controller': 'ctrl2', 'iqn': 'iqn2'},
                   {'controller': 'ctrl1', 'iqn': 'iqn1'}]
        portal = self.library._get_iscsi_portal_for_vol(volume, portals)
        self.assertEqual({'controller': 'ctrl1', 'iqn': 'iqn1'}, portal)
        portal = self.library._get_iscsi_portal_for_vol(vol_nomatch, portals)
        self.assertEqual({'controller': 'ctrl2', 'iqn': 'iqn2'}, portal)

    def test_portal_for_vol_any_false(self):
        vol_nomatch = {'id': 'vol_id', 'currentManager': 'ctrl3'}
        portals = [{'controller': 'ctrl2', 'iqn': 'iqn2'},
                   {'controller': 'ctrl1', 'iqn': 'iqn1'}]
        self.assertRaises(exception.NetAppDriverException,
                          self.library._get_iscsi_portal_for_vol,
                          vol_nomatch, portals, False)

    def test_do_setup_all_default(self):
        configuration = self._set_config(self.create_configuration())
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        mock_invoke.assert_called_with(**fakes.FAKE_CLIENT_PARAMS)

    def test_do_setup_http_default_port(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_transport_type = 'http'
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        mock_invoke.assert_called_with(**fakes.FAKE_CLIENT_PARAMS)

    def test_do_setup_https_default_port(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_transport_type = 'https'
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        FAKE_EXPECTED_PARAMS = dict(fakes.FAKE_CLIENT_PARAMS, port=8443,
                                    scheme='https')
        mock_invoke.assert_called_with(**FAKE_EXPECTED_PARAMS)

    def test_do_setup_http_non_default_port(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_server_port = 81
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        FAKE_EXPECTED_PARAMS = dict(fakes.FAKE_CLIENT_PARAMS, port=81)
        mock_invoke.assert_called_with(**FAKE_EXPECTED_PARAMS)

    def test_do_setup_https_non_default_port(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_transport_type = 'https'
        configuration.netapp_server_port = 446
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system = mock.Mock()
        mock_invoke = self.mock_object(client, 'RestClient')
        driver.do_setup(context='context')
        FAKE_EXPECTED_PARAMS = dict(fakes.FAKE_CLIENT_PARAMS, port=446,
                                    scheme='https')
        mock_invoke.assert_called_with(**FAKE_EXPECTED_PARAMS)

    def test_setup_good_controller_ip(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_controller_ips = '127.0.0.1'
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system

    def test_setup_good_controller_ips(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_controller_ips = '127.0.0.2,127.0.0.1'
        driver = common.NetAppDriver(configuration=configuration)
        driver.library._check_mode_get_or_register_storage_system

    def test_setup_missing_controller_ip(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_controller_ips = None
        driver = common.NetAppDriver(configuration=configuration)
        self.assertRaises(exception.InvalidInput,
                          driver.do_setup, context='context')

    def test_setup_error_invalid_controller_ip(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_controller_ips = '987.65.43.21'
        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(na_utils, 'resolve_hostname',
                         side_effect=socket.gaierror)

        self.assertRaises(
            exception.NoValidBackend,
            driver.library._check_mode_get_or_register_storage_system)

    def test_setup_error_invalid_first_controller_ip(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_controller_ips = '987.65.43.21,127.0.0.1'
        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(na_utils, 'resolve_hostname',
                         side_effect=socket.gaierror)

        self.assertRaises(
            exception.NoValidBackend,
            driver.library._check_mode_get_or_register_storage_system)

    def test_setup_error_invalid_second_controller_ip(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_controller_ips = '127.0.0.1,987.65.43.21'
        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(na_utils, 'resolve_hostname',
                         side_effect=socket.gaierror)

        self.assertRaises(
            exception.NoValidBackend,
            driver.library._check_mode_get_or_register_storage_system)

    def test_setup_error_invalid_both_controller_ips(self):
        configuration = self._set_config(self.create_configuration())
        configuration.netapp_controller_ips = '564.124.1231.1,987.65.43.21'
        driver = common.NetAppDriver(configuration=configuration)
        self.mock_object(na_utils, 'resolve_hostname',
                         side_effect=socket.gaierror)

        self.assertRaises(
            exception.NoValidBackend,
            driver.library._check_mode_get_or_register_storage_system)

    def test_manage_existing_get_size(self):
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=self.fake_ret_vol)
        size = self.driver.manage_existing_get_size(self.volume, self.fake_ref)
        self.assertEqual(3, size)
        self.library._get_existing_vol_with_manage_ref.assert_called_once_with(
            self.fake_ref)

    def test_get_exist_vol_source_name_missing(self):
        self.library._client.list_volume = mock.Mock(
            side_effect=exception.InvalidInput)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.library._get_existing_vol_with_manage_ref,
                          {'id': '1234'})

    @ddt.data('source-id', 'source-name')
    def test_get_exist_vol_source_not_found(self, attr_name):
        def _get_volume(v_id):
            d = {'id': '1', 'name': 'volume1', 'worldWideName': '0'}
            if v_id in d:
                return d[v_id]
            else:
                raise exception.VolumeNotFound(message=v_id)

        self.library._client.list_volume = mock.Mock(wraps=_get_volume)
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.library._get_existing_vol_with_manage_ref,
                          {attr_name: 'name2'})

        self.library._client.list_volume.assert_called_once_with(
            'name2')

    def test_get_exist_vol_with_manage_ref(self):
        fake_ret_vol = {'id': 'right'}
        self.library._client.list_volume = mock.Mock(return_value=fake_ret_vol)

        actual_vol = self.library._get_existing_vol_with_manage_ref(
            {'source-name': 'name2'})

        self.library._client.list_volume.assert_called_once_with('name2')
        self.assertEqual(fake_ret_vol, actual_vol)

    @mock.patch.object(utils, 'convert_uuid_to_es_fmt')
    def test_manage_existing_same_label(self, mock_convert_es_fmt):
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=self.fake_ret_vol)
        mock_convert_es_fmt.return_value = 'label'
        self.driver.manage_existing(self.volume, self.fake_ref)
        self.library._get_existing_vol_with_manage_ref.assert_called_once_with(
            self.fake_ref)
        mock_convert_es_fmt.assert_called_once_with(
            '114774fb-e15a-4fae-8ee2-c9723e3645ef')

    @mock.patch.object(utils, 'convert_uuid_to_es_fmt')
    def test_manage_existing_new(self, mock_convert_es_fmt):
        self.library._get_existing_vol_with_manage_ref = mock.Mock(
            return_value=self.fake_ret_vol)
        mock_convert_es_fmt.return_value = 'vol_label'
        self.library._client.update_volume = mock.Mock(
            return_value={'id': 'update', 'worldWideName': 'wwn'})
        self.driver.manage_existing(self.volume, self.fake_ref)
        self.library._get_existing_vol_with_manage_ref.assert_called_once_with(
            self.fake_ref)
        mock_convert_es_fmt.assert_called_once_with(
            '114774fb-e15a-4fae-8ee2-c9723e3645ef')
        self.library._client.update_volume.assert_called_once_with(
            'vol_id', 'vol_label')

    @mock.patch.object(library.LOG, 'info')
    def test_unmanage(self, log_info):
        self.library._get_volume = mock.Mock(return_value=self.fake_ret_vol)
        self.driver.unmanage(self.volume)
        self.library._get_volume.assert_called_once_with(
            '114774fb-e15a-4fae-8ee2-c9723e3645ef')
        self.assertEqual(1, log_info.call_count)

    @mock.patch.object(library.NetAppESeriesLibrary, 'ensure_export',
                       mock.Mock())
    def test_ensure_export(self):
        self.driver.ensure_export('context', self.fake_ret_vol)
        self.assertTrue(self.library.ensure_export.called)

    @mock.patch.object(library.NetAppESeriesLibrary, 'extend_volume',
                       mock.Mock())
    def test_extend_volume(self):
        capacity = 10
        self.driver.extend_volume(self.fake_ret_vol, capacity)
        self.library.extend_volume.assert_called_with(self.fake_ret_vol,
                                                      capacity)

    @mock.patch.object(library.NetAppESeriesLibrary,
                       'create_cgsnapshot', mock.Mock())
    def test_create_cgsnapshot(self):
        cgsnapshot = copy.deepcopy(fakes.FAKE_CINDER_CG_SNAPSHOT)
        snapshots = copy.deepcopy([fakes.SNAPSHOT_IMAGE])

        self.driver.create_cgsnapshot('ctx', cgsnapshot, snapshots)

        self.library.create_cgsnapshot.assert_called_with(cgsnapshot,
                                                          snapshots)

    @mock.patch.object(library.NetAppESeriesLibrary,
                       'delete_cgsnapshot', mock.Mock())
    def test_delete_cgsnapshot(self):
        cgsnapshot = copy.deepcopy(fakes.FAKE_CINDER_CG_SNAPSHOT)
        snapshots = copy.deepcopy([fakes.SNAPSHOT_IMAGE])

        self.driver.delete_cgsnapshot('ctx', cgsnapshot, snapshots)

        self.library.delete_cgsnapshot.assert_called_with(cgsnapshot,
                                                          snapshots)

    @mock.patch.object(library.NetAppESeriesLibrary,
                       'create_consistencygroup', mock.Mock())
    def test_create_consistencygroup(self):
        cg = copy.deepcopy(fakes.FAKE_CINDER_CG)

        self.driver.create_consistencygroup('ctx', cg)

        self.library.create_consistencygroup.assert_called_with(cg)

    @mock.patch.object(library.NetAppESeriesLibrary,
                       'delete_consistencygroup', mock.Mock())
    def test_delete_consistencygroup(self):
        cg = copy.deepcopy(fakes.FAKE_CINDER_CG)
        volumes = copy.deepcopy([fakes.VOLUME])

        self.driver.delete_consistencygroup('ctx', cg, volumes)

        self.library.delete_consistencygroup.assert_called_with(cg, volumes)

    @mock.patch.object(library.NetAppESeriesLibrary,
                       'update_consistencygroup', mock.Mock())
    def test_update_consistencygroup(self):
        group = copy.deepcopy(fakes.FAKE_CINDER_CG)

        self.driver.update_consistencygroup('ctx', group, {}, {})

        self.library.update_consistencygroup.assert_called_with(group, {}, {})

    @mock.patch.object(library.NetAppESeriesLibrary,
                       'create_consistencygroup_from_src', mock.Mock())
    def test_create_consistencygroup_from_src(self):
        cg = copy.deepcopy(fakes.FAKE_CINDER_CG)
        volumes = copy.deepcopy([fakes.VOLUME])
        source_vols = copy.deepcopy([fakes.VOLUME])
        cgsnapshot = copy.deepcopy(fakes.FAKE_CINDER_CG_SNAPSHOT)
        source_cg = copy.deepcopy(fakes.FAKE_CINDER_CG_SNAPSHOT)
        snapshots = copy.deepcopy([fakes.SNAPSHOT_IMAGE])

        self.driver.create_consistencygroup_from_src(
            'ctx', cg, volumes, cgsnapshot, snapshots, source_cg,
            source_vols)

        self.library.create_consistencygroup_from_src.assert_called_with(
            cg, volumes, cgsnapshot, snapshots, source_cg, source_vols)
