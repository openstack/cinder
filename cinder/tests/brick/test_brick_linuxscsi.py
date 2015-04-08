# (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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

import os
import os.path
import string

from oslo_log import log as logging

from cinder.brick import exception
from cinder.brick.initiator import linuxscsi
from cinder import test

LOG = logging.getLogger(__name__)


class LinuxSCSITestCase(test.TestCase):
    def setUp(self):
        super(LinuxSCSITestCase, self).setUp()
        self.cmds = []
        self.stubs.Set(os.path, 'realpath', lambda x: '/dev/sdc')
        self.linuxscsi = linuxscsi.LinuxSCSI(None, execute=self.fake_execute)
        self.fake_stat_result = os.stat(__file__)

    def fake_execute(self, *cmd, **kwargs):
        self.cmds.append(string.join(cmd))
        return "", None

    def fake_stat(self, path):
        return self.fake_stat_result

    def test_echo_scsi_command(self):
        self.linuxscsi.echo_scsi_command("/some/path", "1")
        expected_commands = ['tee -a /some/path']
        self.assertEqual(expected_commands, self.cmds)

    def test_get_name_from_path(self):
        device_name = "/dev/sdc"
        self.stubs.Set(os.path, 'realpath', lambda x: device_name)
        disk_path = ("/dev/disk/by-path/ip-10.10.220.253:3260-"
                     "iscsi-iqn.2000-05.com.3pardata:21810002ac00383d-lun-0")
        name = self.linuxscsi.get_name_from_path(disk_path)
        self.assertEqual(name, device_name)
        self.stubs.Set(os.path, 'realpath', lambda x: "bogus")
        name = self.linuxscsi.get_name_from_path(disk_path)
        self.assertIsNone(name)

    def test_remove_scsi_device(self):
        self.stubs.Set(os.path, "exists", lambda x: False)
        self.linuxscsi.remove_scsi_device("/dev/sdc")
        expected_commands = []
        self.assertEqual(expected_commands, self.cmds)
        self.stubs.Set(os.path, "exists", lambda x: True)
        self.linuxscsi.remove_scsi_device("/dev/sdc")
        expected_commands = [
            ('blockdev --flushbufs /dev/sdc'),
            ('tee -a /sys/block/sdc/device/delete')]
        self.assertEqual(expected_commands, self.cmds)

    def test_wait_for_volume_removal(self):
        fake_path = '/dev/disk/by-path/fake-iscsi-iqn-lun-0'
        self.stubs.Set(os.path, "exists", lambda x: True)
        self.assertRaises(exception.VolumePathNotRemoved,
                          self.linuxscsi.wait_for_volume_removal,
                          fake_path)

        self.stubs.Set(os.path, "exists", lambda x: False)
        self.linuxscsi.wait_for_volume_removal(fake_path)
        expected_commands = []
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
        expected_commands = [
            ('blockdev --flushbufs /dev/sde'),
            ('tee -a /sys/block/sde/device/delete'),
            ('blockdev --flushbufs /dev/sdf'),
            ('tee -a /sys/block/sdf/device/delete'),
            ('multipath -f 350002ac20398383d'), ]
        self.assertEqual(expected_commands, self.cmds)

    def test_find_multipath_device_3par_ufn(self):
        def fake_execute(*cmd, **kwargs):
            out = ("mpath6 (350002ac20398383d) dm-3 3PARdata,VV\n"
                   "size=2.0G features='0' hwhandler='0' wp=rw\n"
                   "`-+- policy='round-robin 0' prio=-1 status=active\n"
                   "  |- 0:0:0:1 sde 8:64 active undef running\n"
                   "  `- 2:0:0:1 sdf 8:80 active undef running\n"
                   )
            return out, None

        self.stubs.Set(self.linuxscsi, '_execute', fake_execute)
        self.stubs.SmartSet(os, 'stat', self.fake_stat)

        info = self.linuxscsi.find_multipath_device('/dev/sde')
        LOG.error("info = %s" % info)

        self.assertEqual("350002ac20398383d", info['id'])
        self.assertEqual("mpath6", info['name'])
        self.assertEqual("/dev/mapper/mpath6", info['device'])

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
        self.stubs.SmartSet(os, 'stat', self.fake_stat)

        info = self.linuxscsi.find_multipath_device('/dev/sde')
        LOG.error("info = %s" % info)

        self.assertEqual("36005076da00638089c000000000004d5", info["id"])
        self.assertEqual("36005076da00638089c000000000004d5", info["name"])
        self.assertEqual("/dev/mapper/36005076da00638089c000000000004d5",
                         info["device"])

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
        self.stubs.SmartSet(os, 'stat', self.fake_stat)

        info = self.linuxscsi.find_multipath_device('/dev/sdd')
        LOG.error("info = %s" % info)

        self.assertEqual("36005076303ffc48e0000000000000101", info["id"])
        self.assertEqual("36005076303ffc48e0000000000000101", info["name"])
        self.assertEqual("/dev/mapper/36005076303ffc48e0000000000000101",
                         info["device"])

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

    def test_find_multipath_device_with_error(self):
        def fake_execute(*cmd, **kwargs):
            out = ("Oct 13 10:24:01 | /lib/udev/scsi_id exitted with 1\n"
                   "36005076303ffc48e0000000000000101 dm-2 IBM,2107900\n"
                   "size=1.0G features='1 queue_if_no_path' hwhandler='0'"
                   " wp=rw\n"
                   "`-+- policy='round-robin 0' prio=-1 status=active\n"
                   "  |- 6:0:2:0  sdd 8:64  active undef  running\n"
                   "  `- 6:1:0:3  sdc 8:32  active undef  running\n"
                   )
            return out, None

        self.stubs.Set(self.linuxscsi, '_execute', fake_execute)
        self.stubs.SmartSet(os, 'stat', self.fake_stat)

        info = self.linuxscsi.find_multipath_device('/dev/sdd')
        LOG.error("info = %s" % info)

        self.assertEqual("36005076303ffc48e0000000000000101", info["id"])
        self.assertEqual("36005076303ffc48e0000000000000101", info["name"])
        self.assertEqual("/dev/mapper/36005076303ffc48e0000000000000101",
                         info["device"])

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
