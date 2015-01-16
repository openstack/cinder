#    Copyright 2012 OpenStack Foundation
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


from oslo_config import cfg
from oslo_utils import importutils

from cinder import context
from cinder import test


CONF = cfg.CONF
HUAWEI_ISCSI_MODULE = ("cinder.volume.drivers.huawei.huawei_18000."
                       "Huawei18000ISCSIDriver")
HUAWEI_FC_MODULE = ("cinder.volume.drivers.huawei.huawei_18000."
                    "Huawei18000FCDriver")


class VolumeDriverCompatibility(test.TestCase):
    """Test backwards compatibility for volume drivers."""

    def fake_update_cluster_status(self):
        return

    def setUp(self):
        super(VolumeDriverCompatibility, self).setUp()
        self.manager = importutils.import_object(CONF.volume_manager)
        self.context = context.get_admin_context()

    def _load_driver(self, driver):
        self.manager.__init__(volume_driver=driver)

    def _driver_module_name(self):
        return "%s.%s" % (self.manager.driver.__class__.__module__,
                          self.manager.driver.__class__.__name__)

    def test_huawei_driver_iscsi_old(self):
        self._load_driver(
            'cinder.volume.drivers.huawei.huawei_hvs.HuaweiHVSISCSIDriver')
        self.assertEqual(self._driver_module_name(), HUAWEI_ISCSI_MODULE)

    def test_huawei_driver_iscsi_new(self):
        self._load_driver(HUAWEI_ISCSI_MODULE)
        self.assertEqual(self._driver_module_name(), HUAWEI_ISCSI_MODULE)

    def test_huawei_driver_fc_old(self):
        self._load_driver(
            'cinder.volume.drivers.huawei.huawei_hvs.HuaweiHVSFCDriver')
        self.assertEqual(self._driver_module_name(), HUAWEI_FC_MODULE)

    def test_huawei_driver_fc_new(self):
        self._load_driver(HUAWEI_FC_MODULE)
        self.assertEqual(self._driver_module_name(), HUAWEI_FC_MODULE)
