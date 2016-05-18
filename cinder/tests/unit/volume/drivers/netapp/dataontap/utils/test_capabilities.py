# Copyright (c) 2016 Clinton Knight
# All rights reserved.
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

import ddt
import mock

from cinder import exception
from cinder import test
from cinder.volume.drivers.netapp.dataontap.utils import capabilities


@ddt.ddt
class CapabilitiesLibraryTestCase(test.TestCase):

    def setUp(self):
        super(CapabilitiesLibraryTestCase, self).setUp()

        self.zapi_client = mock.Mock()
        self.ssc_library = capabilities.CapabilitiesLibrary(self.zapi_client)

    def test_check_api_permissions(self):

        mock_log = self.mock_object(capabilities.LOG, 'warning')

        self.ssc_library.check_api_permissions()

        self.zapi_client.check_cluster_api.assert_has_calls(
            [mock.call(*key) for key in capabilities.SSC_API_MAP.keys()])
        self.assertEqual(0, mock_log.call_count)

    def test_check_api_permissions_failed_ssc_apis(self):

        def check_cluster_api(object_name, operation_name, api):
            if api != 'volume-get-iter':
                return False
            return True

        self.zapi_client.check_cluster_api.side_effect = check_cluster_api
        mock_log = self.mock_object(capabilities.LOG, 'warning')

        self.ssc_library.check_api_permissions()

        self.assertEqual(1, mock_log.call_count)

    def test_check_api_permissions_failed_volume_api(self):

        def check_cluster_api(object_name, operation_name, api):
            if api == 'volume-get-iter':
                return False
            return True

        self.zapi_client.check_cluster_api.side_effect = check_cluster_api
        mock_log = self.mock_object(capabilities.LOG, 'warning')

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.ssc_library.check_api_permissions)

        self.assertEqual(0, mock_log.call_count)
