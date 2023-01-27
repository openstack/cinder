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
"""Mock unit tests for NetApp Data ONTAP FibreChannel storage systems."""

from unittest import mock

from cinder import context
from cinder.tests.unit import test
import cinder.tests.unit.volume.drivers.netapp.fakes as na_fakes
from cinder.volume.drivers.netapp.dataontap import nvme_cmode


class NetAppCmodeNVMeDriverTestCase(test.TestCase):

    def setUp(self):
        super(NetAppCmodeNVMeDriverTestCase, self).setUp()

        kwargs = {
            'configuration': self.get_config_base(),
            'host': 'openstack@netappblock',
        }
        self.library = nvme_cmode.NetAppCmodeNVMeDriver(**kwargs)
        self.library.zapi_client = mock.Mock()
        self.zapi_client = self.library.zapi_client
        self.mock_request = mock.Mock()
        self.ctxt = context.RequestContext('fake', 'fake', auth_token=True)

    def get_config_base(self):
        return na_fakes.create_configuration()
