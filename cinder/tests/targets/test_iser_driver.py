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

from cinder.tests.targets import test_tgt_driver as test_tgt
from cinder import utils
from cinder.volume.targets import iser


class TestIserAdmDriver(test_tgt.TestTgtAdmDriver):

    def setUp(self):
        super(TestIserAdmDriver, self).setUp()
        self.configuration.iser_ip_address = '10.9.8.7'
        self.configuration.iser_target_prefix = 'iqn.2010-10.org.openstack:'
        self.target = iser.ISERTgtAdm(root_helper=utils.get_root_helper(),
                                      configuration=self.configuration)
