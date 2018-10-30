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

"""Common VNC test needs."""

from cinder import context
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.vnx import common


class TestCase(test.TestCase):

    def setUp(self):
        super(TestCase, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.san_ip = '192.168.1.1'
        self.configuration.storage_vnx_authentication_type = 'global'
        self.configuration.config_group = 'vnx_backend'
        self.ctxt = context.get_admin_context()
        common.DEFAULT_TIMEOUT = 0
        common.INTERVAL_30_SEC = 0
