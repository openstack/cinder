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


from oslo.config import cfg

from cinder import context
from cinder.openstack.common import importutils
from cinder import test


CONF = cfg.CONF

STORWIZE_MODULE = "cinder.volume.drivers.ibm.storwize_svc.StorwizeSVCDriver"
LEFTHAND_REST_MODULE = ("cinder.volume.drivers.san.hp.hp_lefthand_iscsi."
                        "HPLeftHandISCSIDriver")
GPFS_MODULE = "cinder.volume.drivers.ibm.gpfs.GPFSDriver"


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

    def test_storwize_svc_old(self):
        self._load_driver(
            'cinder.volume.drivers.storwize_svc.StorwizeSVCDriver')
        self.assertEqual(self._driver_module_name(), STORWIZE_MODULE)

    def test_storwize_svc_old2(self):
        self._load_driver('cinder.volume.drivers.storwize_svc.'
                          'StorwizeSVCDriver')
        self.assertEqual(self._driver_module_name(), STORWIZE_MODULE)

    def test_storwize_svc_new(self):
        self._load_driver(STORWIZE_MODULE)
        self.assertEqual(self._driver_module_name(), STORWIZE_MODULE)

    def test_hp_lefthand_rest_old(self):
        self._load_driver(
            'cinder.volume.drivers.san.hp_lefthand.HpSanISCSIDriver')
        self.assertEqual(self._driver_module_name(), LEFTHAND_REST_MODULE)

    def test_hp_lefthand_rest_new(self):
        self._load_driver(LEFTHAND_REST_MODULE)
        self.assertEqual(self._driver_module_name(), LEFTHAND_REST_MODULE)

    def test_gpfs_old(self):
        self._load_driver('cinder.volume.drivers.gpfs.GPFSDriver')
        self.assertEqual(self._driver_module_name(), GPFS_MODULE)

    def test_gpfs_new(self):
        self._load_driver(GPFS_MODULE)
        self.assertEqual(self._driver_module_name(), GPFS_MODULE)
