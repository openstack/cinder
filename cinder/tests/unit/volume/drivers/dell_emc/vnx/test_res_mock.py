# Copyright (c) 2016 EMC Corporation.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from cinder import test
from cinder.tests.unit.volume.drivers.dell_emc.vnx import res_mock
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.vnx import utils


class TestResMock(test.TestCase):
    def test_load_cinder_resource(self):
        cinder_res = res_mock.CinderResourceMock('mocked_cinder.yaml')

        volume = cinder_res['test_mock_driver_input_inner']['volume']

        items = ['base_lun_name^test', 'version^07.00.00', 'type^lun',
                 'system^fake_serial', 'id^1']
        self.assertEqual(sorted(items),
                         sorted(volume.provider_location.split('|')))

    def test_mock_driver_input(self):
        @res_mock.mock_driver_input
        def test_mock_driver_input_inner(self, mocked_input):
            items = ['base_lun_name^test', 'version^07.00.00', 'type^lun',
                     'system^fake_serial', 'id^1']
            mocked_items = mocked_input['volume'].provider_location.split('|')
            self.assertEqual(sorted(items),
                             sorted(mocked_items))

        test_mock_driver_input_inner(self)

    def test_load_storage_resource(self):
        vnx_res = res_mock.StorageResourceMock('test_res_mock.yaml')
        lun = vnx_res['test_load_storage_resource']['lun']
        pool = vnx_res['test_load_storage_resource']['pool']
        created_lun = pool.create_lun()
        self.assertEqual(lun.lun_id, created_lun.lun_id)
        self.assertEqual(lun.poll, created_lun.poll)
        self.assertEqual(lun.state, created_lun.state)

    def test_patch_client(self):
        @res_mock.patch_client
        def test_patch_client_inner(self, patched_client, mocked):
            vnx = patched_client.vnx
            self.assertEqual('fake_serial', vnx.serial)

            pool = vnx.get_pool()
            self.assertEqual('pool_name', pool.name)

        test_patch_client_inner(self)

    def test_patch_client_mocked(self):
        @res_mock.patch_client
        def test_patch_client_mocked_inner(self, patched_client, mocked):
            lun = mocked['lun']
            self.assertEqual('Offline', lun.state)

        test_patch_client_mocked_inner(self)

    def test_patch_adapter_common(self):
        self.configuration = conf.Configuration(None)
        utils.init_ops(self.configuration)
        self.configuration.san_ip = '192.168.1.1'
        self.configuration.storage_vnx_authentication_type = 'global'
        self.configuration.storage_vnx_pool_names = 'pool1,unit_test_pool'

        @res_mock.patch_common_adapter
        def test_patch_common_adapter_inner(self, patched_adapter, mocked):
            pool = patched_adapter.client.vnx.get_pool()
            self.assertEqual('pool_name', pool.name)

        test_patch_common_adapter_inner(self)
