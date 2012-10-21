#    Copyright 2012 OpenStack LLC
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

from cinder import context
from cinder import flags
from cinder.openstack.common import importutils
from cinder import test

FLAGS = flags.FLAGS

RBD_MODULE = "cinder.volume.drivers.rbd.RBDDriver"
SHEEPDOG_MODULE = "cinder.volume.drivers.sheepdog.SheepdogDriver"


class VolumeDriverCompatibility(test.TestCase):
    """Test backwards compatibility for volume drivers."""

    def setUp(self):
        super(VolumeDriverCompatibility, self).setUp()
        self.manager = importutils.import_object(FLAGS.volume_manager)
        self.context = context.get_admin_context()

    def tearDown(self):
        super(VolumeDriverCompatibility, self).tearDown()

    def _load_driver(self, driver):
        self.manager.__init__(volume_driver=driver)

    def _driver_module_name(self):
        return "%s.%s" % (self.manager.driver.__class__.__module__,
                          self.manager.driver.__class__.__name__)

    def test_rbd_old(self):
        self._load_driver('cinder.volume.driver.RBDDriver')
        self.assertEquals(self._driver_module_name(), RBD_MODULE)

    def test_rbd_new(self):
        self._load_driver(RBD_MODULE)
        self.assertEquals(self._driver_module_name(), RBD_MODULE)

    def test_sheepdog_old(self):
        self._load_driver('cinder.volume.driver.SheepdogDriver')
        self.assertEquals(self._driver_module_name(), SHEEPDOG_MODULE)

    def test_sheepdog_new(self):
        self._load_driver('cinder.volume.drivers.sheepdog.SheepdogDriver')
        self.assertEquals(self._driver_module_name(), SHEEPDOG_MODULE)
