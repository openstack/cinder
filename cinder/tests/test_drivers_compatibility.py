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
from cinder.volume.drivers.solidfire import SolidFireDriver


CONF = cfg.CONF

RBD_MODULE = "cinder.volume.drivers.rbd.RBDDriver"
SHEEPDOG_MODULE = "cinder.volume.drivers.sheepdog.SheepdogDriver"
NEXENTA_MODULE = "cinder.volume.drivers.nexenta.iscsi.NexentaISCSIDriver"
SAN_MODULE = "cinder.volume.drivers.san.san.SanISCSIDriver"
SOLARIS_MODULE = "cinder.volume.drivers.san.solaris.SolarisISCSIDriver"
LEFTHAND_MODULE = "cinder.volume.drivers.san.hp_lefthand.HpSanISCSIDriver"
NFS_MODULE = "cinder.volume.drivers.nfs.NfsDriver"
SOLIDFIRE_MODULE = "cinder.volume.drivers.solidfire.SolidFireDriver"
STORWIZE_SVC_MODULE = "cinder.volume.drivers.storwize_svc.StorwizeSVCDriver"
WINDOWS_MODULE = "cinder.volume.drivers.windows.windows.WindowsDriver"
XIV_DS8K_MODULE = "cinder.volume.drivers.xiv_ds8k.XIVDS8KDriver"
ZADARA_MODULE = "cinder.volume.drivers.zadara.ZadaraVPSAISCSIDriver"
NETAPP_MODULE = "cinder.volume.drivers.netapp.common.Deprecated"


class VolumeDriverCompatibility(test.TestCase):
    """Test backwards compatibility for volume drivers."""

    def fake_update_cluster_status(self):
        return

    def setUp(self):
        super(VolumeDriverCompatibility, self).setUp()
        self.manager = importutils.import_object(CONF.volume_manager)
        self.context = context.get_admin_context()

    def tearDown(self):
        super(VolumeDriverCompatibility, self).tearDown()

    def _load_driver(self, driver):
        if 'SolidFire' in driver:
            # SolidFire driver does update_cluster stat on init
            self.stubs.Set(SolidFireDriver, '_update_cluster_status',
                           self.fake_update_cluster_status)
        self.manager.__init__(volume_driver=driver)

    def _driver_module_name(self):
        return "%s.%s" % (self.manager.driver.__class__.__module__,
                          self.manager.driver.__class__.__name__)

    def test_rbd_old(self):
        self._load_driver('cinder.volume.driver.RBDDriver')
        self.assertEqual(self._driver_module_name(), RBD_MODULE)

    def test_rbd_new(self):
        self._load_driver(RBD_MODULE)
        self.assertEqual(self._driver_module_name(), RBD_MODULE)

    def test_sheepdog_old(self):
        self._load_driver('cinder.volume.driver.SheepdogDriver')
        self.assertEqual(self._driver_module_name(), SHEEPDOG_MODULE)

    def test_sheepdog_new(self):
        self._load_driver(SHEEPDOG_MODULE)
        self.assertEqual(self._driver_module_name(), SHEEPDOG_MODULE)

    def test_nexenta_old(self):
        self._load_driver('cinder.volume.nexenta.volume.NexentaDriver')
        self.assertEqual(self._driver_module_name(), NEXENTA_MODULE)

    def test_nexenta_new(self):
        self._load_driver(NEXENTA_MODULE)
        self.assertEqual(self._driver_module_name(), NEXENTA_MODULE)

    def test_san_old(self):
        self._load_driver('cinder.volume.san.SanISCSIDriver')
        self.assertEqual(self._driver_module_name(), SAN_MODULE)

    def test_san_new(self):
        self._load_driver(SAN_MODULE)
        self.assertEqual(self._driver_module_name(), SAN_MODULE)

    def test_solaris_old(self):
        self._load_driver('cinder.volume.san.SolarisISCSIDriver')
        self.assertEqual(self._driver_module_name(), SOLARIS_MODULE)

    def test_solaris_new(self):
        self._load_driver(SOLARIS_MODULE)
        self.assertEqual(self._driver_module_name(), SOLARIS_MODULE)

    def test_hp_lefthand_old(self):
        self._load_driver('cinder.volume.san.HpSanISCSIDriver')
        self.assertEqual(self._driver_module_name(), LEFTHAND_MODULE)

    def test_hp_lefthand_new(self):
        self._load_driver(LEFTHAND_MODULE)
        self.assertEqual(self._driver_module_name(), LEFTHAND_MODULE)

    def test_nfs_old(self):
        self._load_driver('cinder.volume.nfs.NfsDriver')
        self.assertEqual(self._driver_module_name(), NFS_MODULE)

    def test_nfs_new(self):
        self._load_driver(NFS_MODULE)
        self.assertEqual(self._driver_module_name(), NFS_MODULE)

    def test_solidfire_old(self):
        self._load_driver('cinder.volume.solidfire.SolidFire')
        self.assertEqual(self._driver_module_name(), SOLIDFIRE_MODULE)

    def test_solidfire_old2(self):
        self._load_driver('cinder.volume.drivers.solidfire.SolidFire')
        self.assertEqual(self._driver_module_name(), SOLIDFIRE_MODULE)

    def test_solidfire_new(self):
        self._load_driver(SOLIDFIRE_MODULE)
        self.assertEqual(self._driver_module_name(), SOLIDFIRE_MODULE)

    def test_storwize_svc_old(self):
        self._load_driver('cinder.volume.storwize_svc.StorwizeSVCDriver')
        self.assertEqual(self._driver_module_name(), STORWIZE_SVC_MODULE)

    def test_storwize_svc_new(self):
        self._load_driver(STORWIZE_SVC_MODULE)
        self.assertEqual(self._driver_module_name(), STORWIZE_SVC_MODULE)

    def test_windows_old(self):
        self._load_driver('cinder.volume.windows.WindowsDriver')
        self.assertEqual(self._driver_module_name(), WINDOWS_MODULE)

    def test_windows_new(self):
        self._load_driver(WINDOWS_MODULE)
        self.assertEqual(self._driver_module_name(), WINDOWS_MODULE)

    def test_xiv_old(self):
        self._load_driver('cinder.volume.xiv.XIVDriver')
        self.assertEqual(self._driver_module_name(), XIV_DS8K_MODULE)

    def test_xiv_ds8k_new(self):
        self._load_driver(XIV_DS8K_MODULE)
        self.assertEqual(self._driver_module_name(), XIV_DS8K_MODULE)

    def test_zadara_old(self):
        self._load_driver('cinder.volume.zadara.ZadaraVPSAISCSIDriver')
        self.assertEqual(self._driver_module_name(), ZADARA_MODULE)

    def test_zadara_new(self):
        self._load_driver(ZADARA_MODULE)
        self.assertEqual(self._driver_module_name(), ZADARA_MODULE)

    def test_netapp_7m_iscsi_old(self):
        self._load_driver(
            'cinder.volume.drivers.netapp.iscsi.NetAppISCSIDriver')
        self.assertEqual(self._driver_module_name(), NETAPP_MODULE)

    def test_netapp_7m_iscsi_old_old(self):
        self._load_driver('cinder.volume.netapp.NetAppISCSIDriver')
        self.assertEqual(self._driver_module_name(), NETAPP_MODULE)

    def test_netapp_cm_iscsi_old_old(self):
        self._load_driver('cinder.volume.netapp.NetAppCmodeISCSIDriver')
        self.assertEqual(self._driver_module_name(), NETAPP_MODULE)

    def test_netapp_cm_iscsi_old(self):
        self._load_driver(
            'cinder.volume.drivers.netapp.iscsi.NetAppCmodeISCSIDriver')
        self.assertEqual(self._driver_module_name(), NETAPP_MODULE)

    def test_netapp_7m_nfs_old_old(self):
        self._load_driver('cinder.volume.netapp_nfs.NetAppNFSDriver')
        self.assertEqual(self._driver_module_name(), NETAPP_MODULE)

    def test_netapp_7m_nfs_old(self):
        self._load_driver('cinder.volume.drivers.netapp.nfs.NetAppNFSDriver')
        self.assertEqual(self._driver_module_name(), NETAPP_MODULE)

    def test_netapp_cm_nfs_old(self):
        self._load_driver(
            'cinder.volume.drivers.netapp.nfs.NetAppCmodeNfsDriver')
        self.assertEqual(self._driver_module_name(), NETAPP_MODULE)
