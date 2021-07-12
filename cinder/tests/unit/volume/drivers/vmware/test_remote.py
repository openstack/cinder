# Copyright (c) 2020 SAP SE
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

from cinder.tests.unit import test
from cinder.tests.unit import fake_volume
from cinder.volume.drivers.vmware import remote as vmware_remote

import mock


class VmdkDriverRemoteApiTest(test.RPCAPITestCase):

    def setUp(self):
        super(VmdkDriverRemoteApiTest, self).setUp()
        self.rpcapi = vmware_remote.VmdkDriverRemoteApi
        self.base_version = \
            vmware_remote.VmdkDriverRemoteApi.RPC_DEFAULT_VERSION
        self._fake_host = 'fake_host'
        self._fake_volume = fake_volume.fake_db_volume()

    def test_get_service_locator_info(self):
        self._test_rpc_api('get_service_locator_info',
                           rpc_method='call',
                           server=self._fake_host,
                           host=self._fake_host)

    def test_select_ds_for_volume(self):
        self._test_rpc_api('select_ds_for_volume',
                           rpc_method='call',
                           server=self._fake_host,
                           host=self._fake_host,
                           volume=self._fake_volume)

    def test_move_backing_to_folder(self):
        self._test_rpc_api('move_volume_backing_to_folder',
                           rpc_method='call',
                           server=self._fake_host,
                           host=self._fake_host,
                           volume=self._fake_volume,
                           folder='fake-folder')

    def test_create_backing(self):
        self._test_rpc_api('create_backing',
                           rpc_method='call',
                           server=self._fake_host,
                           host=self._fake_host,
                           volume=self._fake_volume,
                           create_params=None
                           )


class VmdkDriverRemoteServiceTest(test.TestCase):

    def setUp(self):
        super(VmdkDriverRemoteServiceTest, self).setUp()
        self._volumeops = mock.Mock()
        self._driver = mock.Mock(
            volumeops=self._volumeops,
            service_locator_info=mock.sentinel.service_locator)
        self._service = vmware_remote.VmdkDriverRemoteService(self._driver)
        self._ctxt = mock.Mock()
        self._fake_volume = fake_volume.fake_db_volume()

    def test_get_service_locator_info(self):
        ret_val = self._service.get_service_locator_info(self._ctxt)
        self.assertEqual(mock.sentinel.service_locator, ret_val)

    def test_select_ds_for_volume(self):
        fake_host = mock.Mock(value='fake-host')
        fake_rp = mock.Mock(value='fake-rp')
        fake_folder = mock.Mock(value='fake-folder')
        fake_summary = mock.Mock(datastore=mock.Mock(vlaue='fake-ds'))
        fake_profile_id = 'fake-uuid'

        self._driver._select_ds_for_volume.return_value = \
            (fake_host, fake_rp, fake_folder, fake_summary)
        self._driver._get_storage_profile_id.return_value = \
            fake_profile_id
        ret_val = self._service.select_ds_for_volume(self._ctxt,
                                                     self._fake_volume)
        self._driver._select_ds_for_volume.assert_called_once_with(
            self._fake_volume)
        self.assertEqual({
            'host': fake_host.value,
            'resource_pool': fake_rp.value,
            'folder': fake_folder.value,
            'profile_id': fake_profile_id,
            'datastore': fake_summary.datastore.value,
        }, ret_val)

    @mock.patch('oslo_vmware.vim_util.get_moref')
    def test_move_volume_backing_to_folder(self, get_moref):
        fake_backing = mock.Mock(value='fake-backing')
        folder_name = 'fake-folder'
        fake_folder = mock.Mock(value=folder_name)
        get_moref.return_value = fake_folder
        self._volumeops.get_backing.return_value = fake_backing

        self._service.move_volume_backing_to_folder(
            self._ctxt, self._fake_volume, folder_name)

        self._volumeops.get_backing.assert_called_once_with(
            self._fake_volume['name'], self._fake_volume['id'])
        get_moref.assert_called_once_with(folder_name, 'Folder')
        self._volumeops.move_backing_to_folder.assert_called_once_with(
            fake_backing, fake_folder)

    def test_create_backing(self):
        self._service.create_backing(self._ctxt, self._fake_volume)
        self._driver._create_backing.assert_called_once_with(
            self._fake_volume, create_params=None)
