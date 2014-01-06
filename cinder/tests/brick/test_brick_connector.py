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

import os.path
import string
import time

import mox

from cinder.brick import exception
from cinder.brick.initiator import connector
from cinder.brick.initiator import host_driver
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.openstack.common import processutils as putils
from cinder import test

LOG = logging.getLogger(__name__)


class ConnectorTestCase(test.TestCase):

    def setUp(self):
        super(ConnectorTestCase, self).setUp()
        self.cmds = []
        self.stubs.Set(os.path, 'exists', lambda x: True)

    def fake_execute(self, *cmd, **kwargs):
        self.cmds.append(string.join(cmd))
        return "", None

    def test_connect_volume(self):
        self.connector = connector.InitiatorConnector(None)
        self.assertRaises(NotImplementedError,
                          self.connector.connect_volume, None)

    def test_disconnect_volume(self):
        self.connector = connector.InitiatorConnector(None)
        self.assertRaises(NotImplementedError,
                          self.connector.disconnect_volume, None, None)

    def test_factory(self):
        obj = connector.InitiatorConnector.factory('iscsi', None)
        self.assertEqual(obj.__class__.__name__, "ISCSIConnector")

        obj = connector.InitiatorConnector.factory('fibre_channel', None)
        self.assertEqual(obj.__class__.__name__, "FibreChannelConnector")

        obj = connector.InitiatorConnector.factory('aoe', None)
        self.assertEqual(obj.__class__.__name__, "AoEConnector")

        obj = connector.InitiatorConnector.factory(
            'nfs', None, nfs_mount_point_base='/mnt/test')
        self.assertEqual(obj.__class__.__name__, "RemoteFsConnector")

        obj = connector.InitiatorConnector.factory(
            'glusterfs', None, glusterfs_mount_point_base='/mnt/test')
        self.assertEqual(obj.__class__.__name__, "RemoteFsConnector")

        obj = connector.InitiatorConnector.factory('local', None)
        self.assertEqual(obj.__class__.__name__, "LocalConnector")

        self.assertRaises(ValueError,
                          connector.InitiatorConnector.factory,
                          "bogus", None)

    def test_check_valid_device_with_wrong_path(self):
        self.connector = connector.InitiatorConnector(None)
        self.stubs.Set(self.connector,
                       '_execute', lambda *args, **kwargs: ("", None))
        self.assertFalse(self.connector.check_valid_device('/d0v'))

    def test_check_valid_device(self):
        self.connector = connector.InitiatorConnector(None)
        self.stubs.Set(self.connector,
                       '_execute', lambda *args, **kwargs: ("", ""))
        self.assertTrue(self.connector.check_valid_device('/dev'))

    def test_check_valid_device_with_cmd_error(self):
        def raise_except(*args, **kwargs):
            raise putils.ProcessExecutionError
        self.connector = connector.InitiatorConnector(None)
        self.stubs.Set(self.connector,
                       '_execute', raise_except)
        self.assertFalse(self.connector.check_valid_device('/dev'))


class HostDriverTestCase(test.TestCase):

    def setUp(self):
        super(HostDriverTestCase, self).setUp()
        self.stubs.Set(os.path, 'isdir', lambda x: True)
        self.devlist = ['device1', 'device2']
        self.stubs.Set(os, 'listdir', lambda x: self.devlist)

    def test_host_driver(self):
        expected = ['/dev/disk/by-path/' + dev for dev in self.devlist]
        driver = host_driver.HostDriver()
        actual = driver.get_all_block_devices()
        self.assertEqual(expected, actual)


class ISCSIConnectorTestCase(ConnectorTestCase):

    def setUp(self):
        super(ISCSIConnectorTestCase, self).setUp()
        self.connector = connector.ISCSIConnector(
            None, execute=self.fake_execute, use_multipath=False)
        self.stubs.Set(self.connector._linuxscsi,
                       'get_name_from_path', lambda x: "/dev/sdb")

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

    def test_get_initiator(self):
        def initiator_no_file(*args, **kwargs):
            raise putils.ProcessExecutionError('No file')

        def initiator_get_text(*arg, **kwargs):
            text = ('## DO NOT EDIT OR REMOVE THIS FILE!\n'
                    '## If you remove this file, the iSCSI daemon '
                    'will not start.\n'
                    '## If you change the InitiatorName, existing '
                    'access control lists\n'
                    '## may reject this initiator.  The InitiatorName must '
                    'be unique\n'
                    '## for each iSCSI initiator.  Do NOT duplicate iSCSI '
                    'InitiatorNames.\n'
                    'InitiatorName=iqn.1234-56.foo.bar:01:23456789abc')
            return text, None

        self.stubs.Set(self.connector, '_execute', initiator_no_file)
        initiator = self.connector.get_initiator()
        self.assertIsNone(initiator)
        self.stubs.Set(self.connector, '_execute', initiator_get_text)
        initiator = self.connector.get_initiator()
        self.assertEqual(initiator, 'iqn.1234-56.foo.bar:01:23456789abc')

    @test.testtools.skipUnless(os.path.exists('/dev/disk/by-path'),
                               'Test requires /dev/disk/by-path')
    def test_connect_volume(self):
        self.stubs.Set(os.path, 'exists', lambda x: True)
        location = '10.0.2.15:3260'
        name = 'volume-00000001'
        iqn = 'iqn.2010-10.org.openstack:%s' % name
        vol = {'id': 1, 'name': name}
        connection_info = self.iscsi_connection(vol, location, iqn)
        device = self.connector.connect_volume(connection_info['data'])
        dev_str = '/dev/disk/by-path/ip-%s-iscsi-%s-lun-1' % (location, iqn)
        self.assertEqual(device['type'], 'block')
        self.assertEqual(device['path'], dev_str)

        self.connector.disconnect_volume(connection_info['data'], device)
        expected_commands = [('iscsiadm -m node -T %s -p %s' %
                              (iqn, location)),
                             ('iscsiadm -m session'),
                             ('iscsiadm -m node -T %s -p %s --login' %
                              (iqn, location)),
                             ('iscsiadm -m node -T %s -p %s --op update'
                              ' -n node.startup -v automatic' % (iqn,
                              location)),
                             ('iscsiadm -m node --rescan'),
                             ('iscsiadm -m session --rescan'),
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

    def test_connect_volume_with_multipath(self):
        location = '10.0.2.15:3260'
        name = 'volume-00000001'
        iqn = 'iqn.2010-10.org.openstack:%s' % name
        vol = {'id': 1, 'name': name}
        connection_properties = self.iscsi_connection(vol, location, iqn)

        self.connector_with_multipath =\
            connector.ISCSIConnector(None, use_multipath=True)
        self.stubs.Set(self.connector_with_multipath,
                       '_run_iscsiadm_bare',
                       lambda *args, **kwargs: "%s %s" % (location, iqn))
        self.stubs.Set(self.connector_with_multipath,
                       '_get_target_portals_from_iscsiadm_output',
                       lambda x: [[location, iqn]])
        self.stubs.Set(self.connector_with_multipath,
                       '_connect_to_iscsi_portal',
                       lambda x: None)
        self.stubs.Set(self.connector_with_multipath,
                       '_rescan_iscsi',
                       lambda: None)
        self.stubs.Set(self.connector_with_multipath,
                       '_rescan_multipath',
                       lambda: None)
        self.stubs.Set(self.connector_with_multipath,
                       '_get_multipath_device_name',
                       lambda x: 'iqn.2010-10.org.openstack:%s' % name)
        self.stubs.Set(os.path, 'exists', lambda x: True)
        result = self.connector_with_multipath.connect_volume(
            connection_properties['data'])
        expected_result = {'path': 'iqn.2010-10.org.openstack:volume-00000001',
                           'type': 'block'}
        self.assertEqual(result, expected_result)

    def test_connect_volume_with_not_found_device(self):
        self.stubs.Set(os.path, 'exists', lambda x: False)
        self.stubs.Set(time, 'sleep', lambda x: None)
        location = '10.0.2.15:3260'
        name = 'volume-00000001'
        iqn = 'iqn.2010-10.org.openstack:%s' % name
        vol = {'id': 1, 'name': name}
        connection_info = self.iscsi_connection(vol, location, iqn)
        self.assertRaises(exception.VolumeDeviceNotFound,
                          self.connector.connect_volume,
                          connection_info['data'])

    def test_get_target_portals_from_iscsiadm_output(self):
        connector = self.connector
        test_output = '''10.15.84.19:3260 iqn.1992-08.com.netapp:sn.33615311
                         10.15.85.19:3260 iqn.1992-08.com.netapp:sn.33615311'''
        res = connector._get_target_portals_from_iscsiadm_output(test_output)
        ip_iqn1 = ['10.15.84.19:3260', 'iqn.1992-08.com.netapp:sn.33615311']
        ip_iqn2 = ['10.15.85.19:3260', 'iqn.1992-08.com.netapp:sn.33615311']
        expected = [ip_iqn1, ip_iqn2]
        self.assertEqual(expected, res)

    def test_get_multipath_device_name(self):
        self.stubs.Set(os.path, 'realpath', lambda x: None)
        multipath_return_string = [('mpath2 (20017380006c00036)'
                                   'dm-7 IBM,2810XIV')]
        self.stubs.Set(self.connector, '_run_multipath',
                       lambda *args, **kwargs: multipath_return_string)
        expected = '/dev/mapper/mpath2'
        self.assertEqual(expected,
                         self.connector.
                         _get_multipath_device_name('/dev/md-1'))

    def test_get_iscsi_devices(self):
        paths = [('ip-10.0.0.1:3260-iscsi-iqn.2013-01.ro.'
                 'com.netapp:node.netapp02-lun-0')]
        self.stubs.Set(os, 'walk', lambda x: [(['.'], ['by-path'], paths)])
        self.assertEqual(self.connector._get_iscsi_devices(), paths)

    def test_get_iscsi_devices_with_empty_dir(self):
        self.stubs.Set(os, 'walk', lambda x: [])
        self.assertEqual(self.connector._get_iscsi_devices(), [])

    def test_get_multipath_iqn(self):
        paths = [('ip-10.0.0.1:3260-iscsi-iqn.2013-01.ro.'
                 'com.netapp:node.netapp02-lun-0')]
        self.stubs.Set(os.path, 'realpath',
                       lambda x: '/dev/disk/by-path/%s' % paths[0])
        self.stubs.Set(self.connector, '_get_iscsi_devices', lambda: paths)
        self.stubs.Set(self.connector, '_get_multipath_device_name',
                       lambda x: paths[0])
        self.assertEqual(self.connector._get_multipath_iqn(paths[0]),
                         'iqn.2013-01.ro.com.netapp:node.netapp02')

    def test_disconnect_volume_multipath_iscsi(self):
        result = []

        def fake_disconnect_from_iscsi_portal(properties):
            result.append(properties)
        iqn1 = 'iqn.2013-01.ro.com.netapp:node.netapp01'
        iqn2 = 'iqn.2013-01.ro.com.netapp:node.netapp02'
        iqns = [iqn1, iqn2]
        portal = '10.0.0.1:3260'
        dev = ('ip-%s-iscsi-%s-lun-0' % (portal, iqn1))
        self.stubs.Set(self.connector,
                       '_get_target_portals_from_iscsiadm_output',
                       lambda x: [[portal, iqn1]])
        self.stubs.Set(self.connector, '_rescan_iscsi', lambda: None)
        self.stubs.Set(self.connector, '_rescan_multipath', lambda: None)
        self.stubs.Set(self.connector.driver, 'get_all_block_devices',
                       lambda: [dev, '/dev/mapper/md-1'])
        self.stubs.Set(self.connector, '_get_multipath_device_name',
                       lambda x: '/dev/mapper/md-3')
        self.stubs.Set(self.connector, '_get_multipath_iqn',
                       lambda x: iqns.pop())
        self.stubs.Set(self.connector, '_disconnect_from_iscsi_portal',
                       fake_disconnect_from_iscsi_portal)
        fake_property = {'target_portal': portal,
                         'target_iqn': iqn1}
        self.connector._disconnect_volume_multipath_iscsi(fake_property,
                                                          'fake/multipath')
        # Target in use by other mp devices, don't disconnect
        self.assertEqual([], result)

    def test_disconnect_volume_multipath_iscsi_without_other_mp_devices(self):
        result = []

        def fake_disconnect_from_iscsi_portal(properties):
            result.append(properties)
        portal = '10.0.2.15:3260'
        name = 'volume-00000001'
        iqn = 'iqn.2010-10.org.openstack:%s' % name
        self.stubs.Set(self.connector,
                       '_get_target_portals_from_iscsiadm_output',
                       lambda x: [[portal, iqn]])
        self.stubs.Set(self.connector, '_rescan_iscsi', lambda: None)
        self.stubs.Set(self.connector, '_rescan_multipath', lambda: None)
        self.stubs.Set(self.connector.driver, 'get_all_block_devices',
                       lambda: [])
        self.stubs.Set(self.connector, '_disconnect_from_iscsi_portal',
                       fake_disconnect_from_iscsi_portal)
        fake_property = {'target_portal': portal,
                         'target_iqn': iqn}
        self.connector._disconnect_volume_multipath_iscsi(fake_property,
                                                          'fake/multipath')
        # Target not in use by other mp devices, disconnect
        self.assertEqual([fake_property], result)


class FibreChannelConnectorTestCase(ConnectorTestCase):
    def setUp(self):
        super(FibreChannelConnectorTestCase, self).setUp()
        self.connector = connector.FibreChannelConnector(
            None, execute=self.fake_execute, use_multipath=False)
        self.assertIsNotNone(self.connector)
        self.assertIsNotNone(self.connector._linuxfc)
        self.assertIsNotNone(self.connector._linuxscsi)

    def fake_get_fc_hbas(self):
        return [{'ClassDevice': 'host1',
                 'ClassDevicePath': '/sys/devices/pci0000:00/0000:00:03.0'
                                    '/0000:05:00.2/host1/fc_host/host1',
                 'dev_loss_tmo': '30',
                 'fabric_name': '0x1000000533f55566',
                 'issue_lip': '<store method only>',
                 'max_npiv_vports': '255',
                 'maxframe_size': '2048 bytes',
                 'node_name': '0x200010604b019419',
                 'npiv_vports_inuse': '0',
                 'port_id': '0x680409',
                 'port_name': '0x100010604b019419',
                 'port_state': 'Online',
                 'port_type': 'NPort (fabric via point-to-point)',
                 'speed': '10 Gbit',
                 'supported_classes': 'Class 3',
                 'supported_speeds': '10 Gbit',
                 'symbolic_name': 'Emulex 554M FV4.0.493.0 DV8.3.27',
                 'tgtid_bind_type': 'wwpn (World Wide Port Name)',
                 'uevent': None,
                 'vport_create': '<store method only>',
                 'vport_delete': '<store method only>'}]

    def fake_get_fc_hbas_info(self):
        hbas = self.fake_get_fc_hbas()
        info = [{'port_name': hbas[0]['port_name'].replace('0x', ''),
                 'node_name': hbas[0]['node_name'].replace('0x', ''),
                 'host_device': hbas[0]['ClassDevice'],
                 'device_path': hbas[0]['ClassDevicePath']}]
        return info

    def fibrechan_connection(self, volume, location, wwn):
        return {'driver_volume_type': 'fibrechan',
                'data': {
                    'volume_id': volume['id'],
                    'target_portal': location,
                    'target_wwn': wwn,
                    'target_lun': 1,
                }}

    def test_connect_volume(self):
        self.stubs.Set(self.connector._linuxfc, "get_fc_hbas",
                       self.fake_get_fc_hbas)
        self.stubs.Set(self.connector._linuxfc, "get_fc_hbas_info",
                       self.fake_get_fc_hbas_info)
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.stubs.Set(os.path, 'realpath', lambda x: '/dev/sdb')

        multipath_devname = '/dev/md-1'
        devices = {"device": multipath_devname,
                   "id": "1234567890",
                   "devices": [{'device': '/dev/sdb',
                                'address': '1:0:0:1',
                                'host': 1, 'channel': 0,
                                'id': 0, 'lun': 1}]}
        self.stubs.Set(self.connector._linuxscsi, 'find_multipath_device',
                       lambda x: devices)
        self.stubs.Set(self.connector._linuxscsi, 'remove_scsi_device',
                       lambda x: None)
        self.stubs.Set(self.connector._linuxscsi, 'get_device_info',
                       lambda x: devices['devices'][0])
        location = '10.0.2.15:3260'
        name = 'volume-00000001'
        vol = {'id': 1, 'name': name}
        # Should work for string, unicode, and list
        wwns = ['1234567890123456', unicode('1234567890123456'),
                ['1234567890123456', '1234567890123457']]
        for wwn in wwns:
            connection_info = self.fibrechan_connection(vol, location, wwn)
            dev_info = self.connector.connect_volume(connection_info['data'])
            exp_wwn = wwn[0] if isinstance(wwn, list) else wwn
            dev_str = ('/dev/disk/by-path/pci-0000:05:00.2-fc-0x%s-lun-1' %
                       exp_wwn)
            self.assertEqual(dev_info['type'], 'block')
            self.assertEqual(dev_info['path'], dev_str)

            self.connector.disconnect_volume(connection_info['data'], dev_info)
            expected_commands = []
            self.assertEqual(expected_commands, self.cmds)

        # Should not work for anything other than string, unicode, and list
        connection_info = self.fibrechan_connection(vol, location, 123)
        self.assertRaises(exception.NoFibreChannelHostsFound,
                          self.connector.connect_volume,
                          connection_info['data'])

        self.stubs.Set(self.connector._linuxfc, 'get_fc_hbas',
                       lambda: [])
        self.stubs.Set(self.connector._linuxfc, 'get_fc_hbas_info',
                       lambda: [])
        self.assertRaises(exception.NoFibreChannelHostsFound,
                          self.connector.connect_volume,
                          connection_info['data'])


class FakeFixedIntervalLoopingCall(object):
    def __init__(self, f=None, *args, **kw):
        self.args = args
        self.kw = kw
        self.f = f
        self._stop = False

    def stop(self):
        self._stop = True

    def wait(self):
        return self

    def start(self, interval, initial_delay=None):
        while not self._stop:
            try:
                self.f(*self.args, **self.kw)
            except loopingcall.LoopingCallDone:
                return self
            except Exception:
                LOG.exception(_('in fixed duration looping call'))
                raise


class AoEConnectorTestCase(ConnectorTestCase):
    """Test cases for AoE initiator class."""
    def setUp(self):
        super(AoEConnectorTestCase, self).setUp()
        self.mox = mox.Mox()
        self.connector = connector.AoEConnector('sudo')
        self.connection_properties = {'target_shelf': 'fake_shelf',
                                      'target_lun': 'fake_lun'}
        self.stubs.Set(loopingcall,
                       'FixedIntervalLoopingCall',
                       FakeFixedIntervalLoopingCall)

    def tearDown(self):
        self.mox.VerifyAll()
        self.mox.UnsetStubs()
        super(AoEConnectorTestCase, self).tearDown()

    def _mock_path_exists(self, aoe_path, mock_values=[]):
        self.mox.StubOutWithMock(os.path, 'exists')
        for value in mock_values:
            os.path.exists(aoe_path).AndReturn(value)

    def test_connect_volume(self):
        """Ensure that if path exist aoe-revaliadte was called."""
        aoe_device, aoe_path = self.connector._get_aoe_info(
            self.connection_properties)

        self._mock_path_exists(aoe_path, [True, True])

        self.mox.StubOutWithMock(self.connector, '_execute')
        self.connector._execute('aoe-revalidate',
                                aoe_device,
                                run_as_root=True,
                                root_helper='sudo',
                                check_exit_code=0).AndReturn(("", ""))
        self.mox.ReplayAll()

        self.connector.connect_volume(self.connection_properties)

    def test_connect_volume_without_path(self):
        """Ensure that if path doesn't exist aoe-discovery was called."""

        aoe_device, aoe_path = self.connector._get_aoe_info(
            self.connection_properties)
        expected_info = {
            'type': 'block',
            'device': aoe_device,
            'path': aoe_path,
        }

        self._mock_path_exists(aoe_path, [False, True])

        self.mox.StubOutWithMock(self.connector, '_execute')
        self.connector._execute('aoe-discover',
                                run_as_root=True,
                                root_helper='sudo',
                                check_exit_code=0).AndReturn(("", ""))
        self.mox.ReplayAll()

        volume_info = self.connector.connect_volume(
            self.connection_properties)

        self.assertDictMatch(volume_info, expected_info)

    def test_connect_volume_could_not_discover_path(self):
        aoe_device, aoe_path = self.connector._get_aoe_info(
            self.connection_properties)

        number_of_calls = 4
        self._mock_path_exists(aoe_path, [False] * (number_of_calls + 1))
        self.mox.StubOutWithMock(self.connector, '_execute')

        for i in xrange(number_of_calls):
            self.connector._execute('aoe-discover',
                                    run_as_root=True,
                                    root_helper='sudo',
                                    check_exit_code=0).AndReturn(("", ""))
        self.mox.ReplayAll()
        self.assertRaises(exception.VolumeDeviceNotFound,
                          self.connector.connect_volume,
                          self.connection_properties)

    def test_disconnect_volume(self):
        """Ensure that if path exist aoe-revaliadte was called."""
        aoe_device, aoe_path = self.connector._get_aoe_info(
            self.connection_properties)

        self._mock_path_exists(aoe_path, [True])

        self.mox.StubOutWithMock(self.connector, '_execute')
        self.connector._execute('aoe-flush',
                                aoe_device,
                                run_as_root=True,
                                root_helper='sudo',
                                check_exit_code=0).AndReturn(("", ""))
        self.mox.ReplayAll()

        self.connector.disconnect_volume(self.connection_properties, {})


class RemoteFsConnectorTestCase(ConnectorTestCase):
    """Test cases for Remote FS initiator class."""
    TEST_DEV = '172.18.194.100:/var/nfs'
    TEST_PATH = '/mnt/test/df0808229363aad55c27da50c38d6328'

    def setUp(self):
        super(RemoteFsConnectorTestCase, self).setUp()
        self.mox = mox.Mox()
        self.connection_properties = {
            'export': self.TEST_DEV,
            'name': '9c592d52-ce47-4263-8c21-4ecf3c029cdb'}
        self.connector = connector.RemoteFsConnector(
            'nfs', root_helper='sudo', nfs_mount_point_base='/mnt/test')

    def tearDown(self):
        self.mox.VerifyAll()
        self.mox.UnsetStubs()
        super(RemoteFsConnectorTestCase, self).tearDown()

    def test_connect_volume(self):
        """Test the basic connect volume case."""
        client = self.connector._remotefsclient
        self.mox.StubOutWithMock(client, '_execute')
        client._execute('mount',
                        check_exit_code=0).AndReturn(("", ""))
        client._execute('mkdir', '-p', self.TEST_PATH,
                        check_exit_code=0).AndReturn(("", ""))
        client._execute('mount', '-t', 'nfs',
                        self.TEST_DEV, self.TEST_PATH,
                        root_helper='sudo', run_as_root=True,
                        check_exit_code=0).AndReturn(("", ""))
        self.mox.ReplayAll()

        self.connector.connect_volume(self.connection_properties)

    def test_disconnect_volume(self):
        """Nothing should happen here -- make sure it doesn't blow up."""
        self.connector.disconnect_volume(self.connection_properties, {})


class LocalConnectorTestCase(test.TestCase):

    def setUp(self):
        super(LocalConnectorTestCase, self).setUp()
        self.connection_properties = {'name': 'foo',
                                      'device_path': '/tmp/bar'}

    def test_connect_volume(self):
        self.connector = connector.LocalConnector(None)
        cprops = self.connection_properties
        dev_info = self.connector.connect_volume(cprops)
        self.assertEqual(dev_info['type'], 'local')
        self.assertEqual(dev_info['path'], cprops['device_path'])

    def test_connect_volume_with_invalid_connection_data(self):
        self.connector = connector.LocalConnector(None)
        cprops = {}
        self.assertRaises(ValueError,
                          self.connector.connect_volume, cprops)
