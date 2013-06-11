# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Red Hat, Inc.
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

import os.path
import string

from cinder.brick.initiator import connector
from cinder.brick.initiator import host_driver
from cinder.brick.initiator import linuxscsi
from cinder.openstack.common import log as logging
from cinder import test

LOG = logging.getLogger(__name__)


class ConnectorTestCase(test.TestCase):

    def setUp(self):
        super(ConnectorTestCase, self).setUp()
        self.cmds = []
        self.stubs.Set(os.path, 'exists', lambda x: True)

    def fake_init(obj):
        return

    def fake_execute(self, *cmd, **kwargs):
        self.cmds.append(string.join(cmd))
        return "", None

    def test_connect_volume(self):
        self.connector = connector.InitiatorConnector()
        self.assertRaises(NotImplementedError,
                          self.connector.connect_volume, None)

    def test_disconnect_volume(self):
        self.connector = connector.InitiatorConnector()
        self.assertRaises(NotImplementedError,
                          self.connector.connect_volume, None)


class HostDriverTestCase(test.TestCase):

    def setUp(self):
        super(HostDriverTestCase, self).setUp()
        self.devlist = ['device1', 'device2']
        self.stubs.Set(os, 'listdir', lambda x: self.devlist)

    def test_host_driver(self):
        expected = ['/dev/disk/by-path/' + dev for dev in self.devlist]
        driver = host_driver.HostDriver()
        actual = driver.get_all_block_devices()
        self.assertEquals(expected, actual)


class LinuxSCSITestCase(test.TestCase):
    def setUp(self):
        super(LinuxSCSITestCase, self).setUp()
        self.cmds = []
        self.stubs.Set(os.path, 'realpath', lambda x: '/dev/sdc')
        self.linuxscsi = linuxscsi.LinuxSCSI(execute=self.fake_execute)

    def fake_execute(self, *cmd, **kwargs):
        self.cmds.append(string.join(cmd))
        return "", None

    def test_get_name_from_path(self):
        device_name = "/dev/sdc"
        self.stubs.Set(os.path, 'realpath', lambda x: device_name)
        disk_path = ("/dev/disk/by-path/ip-10.10.220.253:3260-"
                     "iscsi-iqn.2000-05.com.3pardata:21810002ac00383d-lun-0")
        name = self.linuxscsi.get_name_from_path(disk_path)
        self.assertTrue(name, device_name)
        self.stubs.Set(os.path, 'realpath', lambda x: "bogus")
        name = self.linuxscsi.get_name_from_path(disk_path)
        self.assertIsNone(name)

    def test_remove_scsi_device(self):
        self.stubs.Set(os.path, "exists", lambda x: False)
        self.linuxscsi.remove_scsi_device("sdc")
        expected_commands = []
        self.assertEqual(expected_commands, self.cmds)
        self.stubs.Set(os.path, "exists", lambda x: True)
        self.linuxscsi.remove_scsi_device("sdc")
        expected_commands = [('tee -a /sys/block/sdc/device/delete')]
        self.assertEqual(expected_commands, self.cmds)

    def test_flush_multipath_device(self):
        self.linuxscsi.flush_multipath_device('/dev/dm-9')
        expected_commands = [('multipath -f /dev/dm-9')]
        self.assertEqual(expected_commands, self.cmds)

    def test_flush_multipath_devices(self):
        self.linuxscsi.flush_multipath_devices()
        expected_commands = [('multipath -F')]
        self.assertEqual(expected_commands, self.cmds)

    def test_remove_multipath_device(self):
        def fake_find_multipath_device(device):
            devices = [{'device': '/dev/sde', 'host': 0,
                        'channel': 0, 'id': 0, 'lun': 1},
                       {'device': '/dev/sdf', 'host': 2,
                        'channel': 0, 'id': 0, 'lun': 1}, ]

            info = {"device": "dm-3",
                    "id": "350002ac20398383d",
                    "devices": devices}
            return info

        self.stubs.Set(os.path, "exists", lambda x: True)
        self.stubs.Set(self.linuxscsi, 'find_multipath_device',
                       fake_find_multipath_device)

        self.linuxscsi.remove_multipath_device('/dev/dm-3')
        expected_commands = [('tee -a /sys/block/sde/device/delete'),
                             ('tee -a /sys/block/sdf/device/delete'),
                             ('multipath -f 350002ac20398383d'), ]
        self.assertEqual(expected_commands, self.cmds)

    def test_find_multipath_device_3par(self):
        def fake_execute(*cmd, **kwargs):
            out = ("mpath6 (350002ac20398383d) dm-3 3PARdata,VV\n"
                   "size=2.0G features='0' hwhandler='0' wp=rw\n"
                   "`-+- policy='round-robin 0' prio=-1 status=active\n"
                   "  |- 0:0:0:1 sde 8:64 active undef running\n"
                   "  `- 2:0:0:1 sdf 8:80 active undef running\n"
                   )
            return out, None

        def fake_execute2(*cmd, **kwargs):
            out = ("350002ac20398383d dm-3 3PARdata,VV\n"
                   "size=2.0G features='0' hwhandler='0' wp=rw\n"
                   "`-+- policy='round-robin 0' prio=-1 status=active\n"
                   "  |- 0:0:0:1  sde 8:64 active undef running\n"
                   "  `- 2:0:0:1  sdf 8:80 active undef running\n"
                   )
            return out, None

        self.stubs.Set(self.linuxscsi, '_execute', fake_execute)

        info = self.linuxscsi.find_multipath_device('/dev/sde')
        LOG.error("info = %s" % info)
        self.assertEqual("/dev/dm-3", info["device"])
        self.assertEqual("/dev/sde", info['devices'][0]['device'])
        self.assertEqual("0", info['devices'][0]['host'])
        self.assertEqual("0", info['devices'][0]['id'])
        self.assertEqual("0", info['devices'][0]['channel'])
        self.assertEqual("1", info['devices'][0]['lun'])

        self.assertEqual("/dev/sdf", info['devices'][1]['device'])
        self.assertEqual("2", info['devices'][1]['host'])
        self.assertEqual("0", info['devices'][1]['id'])
        self.assertEqual("0", info['devices'][1]['channel'])
        self.assertEqual("1", info['devices'][1]['lun'])

    def test_find_multipath_device_svc(self):
        def fake_execute(*cmd, **kwargs):
            out = ("36005076da00638089c000000000004d5 dm-2 IBM,2145\n"
                   "size=954M features='1 queue_if_no_path' hwhandler='0'"
                   " wp=rw\n"
                   "|-+- policy='round-robin 0' prio=-1 status=active\n"
                   "| |- 6:0:2:0 sde 8:64  active undef  running\n"
                   "| `- 6:0:4:0 sdg 8:96  active undef  running\n"
                   "`-+- policy='round-robin 0' prio=-1 status=enabled\n"
                   "  |- 6:0:3:0 sdf 8:80  active undef  running\n"
                   "  `- 6:0:5:0 sdh 8:112 active undef  running\n"
                   )
            return out, None

        self.stubs.Set(self.linuxscsi, '_execute', fake_execute)

        info = self.linuxscsi.find_multipath_device('/dev/sde')
        LOG.error("info = %s" % info)
        self.assertEqual("/dev/dm-2", info["device"])
        self.assertEqual("/dev/sde", info['devices'][0]['device'])
        self.assertEqual("6", info['devices'][0]['host'])
        self.assertEqual("0", info['devices'][0]['channel'])
        self.assertEqual("2", info['devices'][0]['id'])
        self.assertEqual("0", info['devices'][0]['lun'])

        self.assertEqual("/dev/sdf", info['devices'][2]['device'])
        self.assertEqual("6", info['devices'][2]['host'])
        self.assertEqual("0", info['devices'][2]['channel'])
        self.assertEqual("3", info['devices'][2]['id'])
        self.assertEqual("0", info['devices'][2]['lun'])

    def test_find_multipath_device_ds8000(self):
        def fake_execute(*cmd, **kwargs):
            out = ("36005076303ffc48e0000000000000101 dm-2 IBM,2107900\n"
                   "size=1.0G features='1 queue_if_no_path' hwhandler='0'"
                   " wp=rw\n"
                   "`-+- policy='round-robin 0' prio=-1 status=active\n"
                   "  |- 6:0:2:0  sdd 8:64  active undef  running\n"
                   "  `- 6:1:0:3  sdc 8:32  active undef  running\n"
                   )
            return out, None

        self.stubs.Set(self.linuxscsi, '_execute', fake_execute)

        info = self.linuxscsi.find_multipath_device('/dev/sdd')
        LOG.error("info = %s" % info)
        self.assertEqual("/dev/dm-2", info["device"])
        self.assertEqual("/dev/sdd", info['devices'][0]['device'])
        self.assertEqual("6", info['devices'][0]['host'])
        self.assertEqual("0", info['devices'][0]['channel'])
        self.assertEqual("2", info['devices'][0]['id'])
        self.assertEqual("0", info['devices'][0]['lun'])

        self.assertEqual("/dev/sdc", info['devices'][1]['device'])
        self.assertEqual("6", info['devices'][1]['host'])
        self.assertEqual("1", info['devices'][1]['channel'])
        self.assertEqual("0", info['devices'][1]['id'])
        self.assertEqual("3", info['devices'][1]['lun'])


class ISCSIConnectorTestCase(ConnectorTestCase):

    def setUp(self):
        super(ISCSIConnectorTestCase, self).setUp()
        self.connector = connector.ISCSIConnector(execute=self.fake_execute)
        self.stubs.Set(self.connector._linuxscsi,
                       'get_name_from_path',
                       lambda x: "/dev/sdb")

    def tearDown(self):
        super(ISCSIConnectorTestCase, self).tearDown()

    def iscsi_connection(self, volume, location, iqn):
        return {
            'driver_volume_type': 'iscsi',
            'data': {
                'volume_id': volume['id'],
                'target_portal': location,
                'target_iqn': iqn,
                'target_lun': 1,
            }
        }

    def test_connect_volume(self):
        self.stubs.Set(os.path, 'exists', lambda x: True)
        location = '10.0.2.15:3260'
        name = 'volume-00000001'
        iqn = 'iqn.2010-10.org.openstack:%s' % name
        vol = {'id': 1, 'name': name}
        connection_info = self.iscsi_connection(vol, location, iqn)
        conf = self.connector.connect_volume(connection_info['data'])
        dev_str = '/dev/disk/by-path/ip-%s-iscsi-%s-lun-1' % (location, iqn)
        self.assertEquals(conf['type'], 'block')
        self.assertEquals(conf['path'], dev_str)

        self.connector.disconnect_volume(connection_info['data'])
        expected_commands = [('iscsiadm -m node -T %s -p %s' %
                              (iqn, location)),
                             ('iscsiadm -m session'),
                             ('iscsiadm -m node -T %s -p %s --login' %
                              (iqn, location)),
                             ('iscsiadm -m node -T %s -p %s --op update'
                              ' -n node.startup -v automatic' % (iqn,
                              location)),
                             ('tee -a /sys/block/sdb/device/delete'),
                             ('iscsiadm -m node -T %s -p %s --op update'
                              ' -n node.startup -v manual' % (iqn, location)),
                             ('iscsiadm -m node -T %s -p %s --logout' %
                              (iqn, location)),
                             ('iscsiadm -m node -T %s -p %s --op delete' %
                              (iqn, location)), ]
        LOG.debug("self.cmds = %s" % self.cmds)
        LOG.debug("expected = %s" % expected_commands)

        self.assertEqual(expected_commands, self.cmds)
