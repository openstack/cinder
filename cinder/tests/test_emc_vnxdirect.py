# Copyright (c) 2012 - 2014 EMC Corporation, Inc.
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

import os
import re

import mock

from cinder import exception
from cinder.openstack.common import processutils
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.emc.emc_cli_fc import EMCCLIFCDriver
from cinder.volume.drivers.emc.emc_cli_iscsi import EMCCLIISCSIDriver
import cinder.volume.drivers.emc.emc_vnx_cli as emc_vnx_cli
from cinder.volume.drivers.emc.emc_vnx_cli import CommandLineHelper
from cinder.volume.drivers.emc.emc_vnx_cli import EMCVnxCLICmdError
from cinder.volume import volume_types
from cinder.zonemanager.fc_san_lookup_service import FCSanLookupService

SUCCEED = ("", 0)
FAKE_ERROR_RETURN = ("FAKE ERROR", 255)


class EMCVNXCLIDriverTestData():

    test_volume = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}]
    }

    test_volume_rw = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'volume_admin_metadata': [{'key': 'access_mode', 'value': 'rw'},
                                  {'key': 'readonly', 'value': 'False'}]
    }

    test_volume2 = {
        'name': 'vol2',
        'size': 1,
        'volume_name': 'vol2',
        'id': '1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol2',
        'display_description': 'test volume',
        'volume_type_id': None}

    test_volume_with_type = {
        'name': 'vol_with_type',
        'size': 1,
        'volume_name': 'vol_with_type',
        'id': '1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'thin_vol',
        'display_description': 'vol with type',
        'volume_type_id': 'abc1-2320-9013-8813-8941-1374-8112-1231'}

    test_failed_volume = {
        'name': 'failed_vol1',
        'size': 1,
        'volume_name': 'failed_vol1',
        'id': '4',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'failed_vol',
        'display_description': 'test failed volume',
        'volume_type_id': None}
    test_snapshot = {
        'name': 'snapshot1',
        'size': 1,
        'id': '4444',
        'volume_name': 'vol1',
        'volume_size': 1,
        'project_id': 'project'}
    test_failed_snapshot = {
        'name': 'failed_snapshot',
        'size': 1,
        'id': '5555',
        'volume_name': 'vol-vol1',
        'volume_size': 1,
        'project_id': 'project'}
    test_clone = {
        'name': 'clone1',
        'size': 1,
        'id': '2',
        'volume_name': 'vol1',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'clone1',
        'display_description': 'volume created from snapshot',
        'volume_type_id': None}
    connector = {
        'ip': '10.0.0.2',
        'initiator': 'iqn.1993-08.org.debian:01:222',
        'wwpns': ["1234567890123456", "1234567890543216"],
        'wwnns': ["2234567890123456", "2234567890543216"],
        'host': 'fakehost'}
    test_volume3 = {'migration_status': None, 'availability_zone': 'nova',
                    'id': '1181d1b2-cea3-4f55-8fa8-3360d026ce24',
                    'name': 'vol3',
                    'size': 2,
                    'volume_admin_metadata': [],
                    'status': 'available',
                    'volume_type_id':
                    '19fdd0dd-03b3-4d7c-b541-f4df46f308c8',
                    'deleted': False, 'provider_location': None,
                    'host': 'ubuntu-server12@pool_backend_1',
                    'source_volid': None, 'provider_auth': None,
                    'display_name': 'vol-test02', 'instance_uuid': None,
                    'attach_status': 'detached',
                    'volume_type': [],
                    'attached_host': None,
                    '_name_id': None, 'volume_metadata': []}

    test_new_type = {'name': 'voltype0', 'qos_specs_id': None,
                     'deleted': False,
                     'extra_specs': {'storagetype:provisioning': 'thin'},
                     'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

    test_diff = {'encryption': {}, 'qos_specs': {},
                 'extra_specs':
                 {'storagetype:provisioning': ('thick', 'thin')}}

    test_host = {'host': 'ubuntu-server12@pool_backend_1',
                 'capabilities':
                 {'location_info': 'POOL_SAS1|FNM00124500890',
                  'volume_backend_name': 'pool_backend_1',
                  'storage_protocol': 'iSCSI'}}

    test_volume4 = {'migration_status': None, 'availability_zone': 'nova',
                    'id': '1181d1b2-cea3-4f55-8fa8-3360d026ce24',
                    'name': 'vol4',
                    'size': 2L,
                    'volume_admin_metadata': [],
                    'status': 'available',
                    'volume_type_id':
                    '19fdd0dd-03b3-4d7c-b541-f4df46f308c8',
                    'deleted': False, 'provider_location': None,
                    'host': 'ubuntu-server12@array_backend_1',
                    'source_volid': None, 'provider_auth': None,
                    'display_name': 'vol-test02', 'instance_uuid': None,
                    'attach_status': 'detached',
                    'volume_type': [],
                    '_name_id': None, 'volume_metadata': []}

    test_volume5 = {'migration_status': None, 'availability_zone': 'nova',
                    'id': '1181d1b2-cea3-4f55-8fa8-3360d026ce25',
                    'name_id': '1181d1b2-cea3-4f55-8fa8-3360d026ce25',
                    'name': 'vol5',
                    'size': 1,
                    'volume_admin_metadata': [],
                    'status': 'available',
                    'volume_type_id':
                    '19fdd0dd-03b3-4d7c-b541-f4df46f308c8',
                    'deleted': False, 'provider_location':
                    'system^FNM11111|type^lun|lun_id^5',
                    'host': 'ubuntu-server12@array_backend_1',
                    'source_volid': None, 'provider_auth': None,
                    'display_name': 'vol-test05', 'instance_uuid': None,
                    'attach_status': 'detached',
                    'volume_type': [],
                    '_name_id': None, 'volume_metadata': []}

    test_new_type2 = {'name': 'voltype0', 'qos_specs_id': None,
                      'deleted': False,
                      'extra_specs': {'storagetype:pool': 'POOL_SAS2'},
                      'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

    test_diff2 = {'encryption': {}, 'qos_specs': {},
                  'extra_specs':
                  {'storagetype:pool': ('POOL_SAS1', 'POOL_SAS2')}}

    test_host2 = {'host': 'ubuntu-server12@array_backend_1',
                  'capabilities':
                  {'location_info': '|FNM00124500890',
                   'volume_backend_name': 'array_backend_1',
                   'storage_protocol': 'iSCSI'}}

    test_lun_id = 1
    test_existing_ref = {'id': test_lun_id}
    test_pool_name = 'Pool_02_SASFLASH'
    device_map = {
        '1122334455667788': {
            'initiator_port_wwn_list': ['123456789012345', '123456789054321'],
            'target_port_wwn_list': ['1122334455667777']}}
    i_t_map = {'123456789012345': ['1122334455667777'],
               '123456789054321': ['1122334455667777']}

    POOL_PROPERTY_CMD = ('storagepool', '-list', '-name', 'unit_test_pool',
                         '-userCap', '-availableCap')

    NDU_LIST_CMD = ('ndu', '-list')
    NDU_LIST_RESULT = ("Name of the software package:   -Compression " +
                       "Name of the software package:   -Deduplication " +
                       "Name of the software package:   -FAST " +
                       "Name of the software package:   -FASTCache " +
                       "Name of the software package:   -ThinProvisioning ",
                       0)

    def SNAP_MP_CREATE_CMD(self, name='vol1', source='vol1'):
        return ('lun', '-create', '-type', 'snap', '-primaryLunName',
                source, '-name', name)

    def SNAP_ATTACH_CMD(self, name='vol1', snapName='snapshot1'):
        return ('lun', '-attach', '-name', name, '-snapName', snapName)

    def SNAP_DELETE_CMD(self, name):
        return ('snap', '-destroy', '-id', name, '-o')

    def SNAP_CREATE_CMD(self, name):
        return ('snap', '-create', '-res', 1, '-name', name,
                '-allowReadWrite', 'yes',
                '-allowAutoDelete', 'no')

    def LUN_DELETE_CMD(self, name):
        return ('lun', '-destroy', '-name', name, '-forceDetach', '-o')

    def LUN_CREATE_CMD(self, name, isthin=False):
        return ('lun', '-create', '-type', 'Thin' if isthin else 'NonThin',
                '-capacity', 1, '-sq', 'gb', '-poolName',
                'unit_test_pool', '-name', name)

    def LUN_EXTEND_CMD(self, name, newsize):
        return ('lun', '-expand', '-name', name, '-capacity', newsize,
                '-sq', 'gb', '-o', '-ignoreThresholds')

    def LUN_PROPERTY_ALL_CMD(self, lunname):
        return ('lun', '-list', '-name', lunname,
                '-state', '-status', '-opDetails', '-userCap', '-owner',
                '-attachedSnapshot')

    def MIGRATION_CMD(self, src_id=1, dest_id=1):
        return ("migrate", "-start", "-source", src_id, "-dest", dest_id,
                "-rate", "high", "-o")

    def MIGRATION_VERIFY_CMD(self, src_id):
        return ("migrate", "-list", "-source", src_id)

    def GETPORT_CMD(self):
        return ("connection", "-getport", "-address", "-vlanid")

    def PINGNODE_CMD(self, sp, portid, vportid, ip):
        return ("connection", "-pingnode", "-sp", sp, '-portid', portid,
                "-vportid", vportid, "-address", ip)

    def GETFCPORT_CMD(self):
        return ('port', '-list', '-sp')

    def CONNECTHOST_CMD(self, hostname, gname):
        return ('storagegroup', '-connecthost',
                '-host', hostname, '-gname', gname, '-o')

    def ENABLE_COMPRESSION_CMD(self, lun_id):
        return ('compression', '-on',
                '-l', lun_id, '-ignoreThresholds', '-o')

    provisioning_values = {
        'thin': ['-type', 'Thin'],
        'thick': ['-type', 'NonThin'],
        'compressed': ['-type', 'Thin'],
        'deduplicated': ['-type', 'Thin', '-deduplication', 'on']}
    tiering_values = {
        'starthighthenauto': [
            '-initialTier', 'highestAvailable',
            '-tieringPolicy', 'autoTier'],
        'auto': [
            '-initialTier', 'optimizePool',
            '-tieringPolicy', 'autoTier'],
        'highestavailable': [
            '-initialTier', 'highestAvailable',
            '-tieringPolicy', 'highestAvailable'],
        'lowestavailable': [
            '-initialTier', 'lowestAvailable',
            '-tieringPolicy', 'lowestAvailable'],
        'nomovement': [
            '-initialTier', 'optimizePool',
            '-tieringPolicy', 'noMovement']}

    def LUN_CREATION_CMD(self, name, size, pool, provisioning, tiering):
        initial = ['lun', '-create',
                   '-capacity', size,
                   '-sq', 'gb',
                   '-poolName', pool,
                   '-name', name]
        if provisioning:
            initial.extend(self.provisioning_values[provisioning])
        else:
            initial.extend(self.provisioning_values['thick'])
        if tiering:
            initial.extend(self.tiering_values[tiering])
        return tuple(initial)

    def CHECK_FASTCACHE_CMD(self, storage_pool):
        return ('-np', 'storagepool', '-list', '-name',
                storage_pool, '-fastcache')

    POOL_PROPERTY = ("""\
Pool Name:  unit_test_pool
Pool ID:  1
User Capacity (Blocks):  5769501696
User Capacity (GBs):  10000.5
Available Capacity (Blocks):  5676521472
Available Capacity (GBs):  1000.6
                        """, 0)

    ALL_PORTS = ("SP:  A\n" +
                 "Port ID:  4\n" +
                 "Port WWN:  iqn.1992-04.com.emc:cx.fnm00124000215.a4\n" +
                 "iSCSI Alias:  0215.a4\n\n" +
                 "Virtual Port ID:  0\n" +
                 "VLAN ID:  Disabled\n" +
                 "IP Address:  10.244.214.118\n\n" +
                 "SP:  A\n" +
                 "Port ID:  5\n" +
                 "Port WWN:  iqn.1992-04.com.emc:cx.fnm00124000215.a5\n" +
                 "iSCSI Alias:  0215.a5\n", 0)

    iscsi_connection_info_ro = \
        {'data': {'access_mode': 'ro',
                  'target_discovered': True,
                  'target_iqn':
                  'iqn.1992-04.com.emc:cx.fnm00124000215.a4',
                  'target_lun': 1,
                  'target_portal': '10.244.214.118:3260'},
         'driver_volume_type': 'iscsi'}

    iscsi_connection_info_rw = \
        {'data': {'access_mode': 'rw',
                  'target_discovered': True,
                  'target_iqn':
                  'iqn.1992-04.com.emc:cx.fnm00124000215.a4',
                  'target_lun': 1,
                  'target_portal': '10.244.214.118:3260'},
         'driver_volume_type': 'iscsi'}

    PING_OK = ("Reply from 10.0.0.2:  bytes=32 time=1ms TTL=30\n" +
               "Reply from 10.0.0.2:  bytes=32 time=1ms TTL=30\n" +
               "Reply from 10.0.0.2:  bytes=32 time=1ms TTL=30\n" +
               "Reply from 10.0.0.2:  bytes=32 time=1ms TTL=30\n", 0)

    FC_PORTS = ("Information about each SPPORT:\n" +
                "\n" +
                "SP Name:             SP A\n" +
                "SP Port ID:          0\n" +
                "SP UID:              50:06:01:60:88:60:01:95:" +
                "50:06:01:60:08:60:01:95\n" +
                "Link Status:         Up\n" +
                "Port Status:         Online\n" +
                "Switch Present:      YES\n" +
                "Switch UID:          10:00:00:05:1E:72:EC:A6:" +
                "20:46:00:05:1E:72:EC:A6\n" +
                "SP Source ID:        272896\n" +
                "\n" +
                "SP Name:             SP B\n" +
                "SP Port ID:          4\n" +
                "SP UID:              iqn.1992-04.com.emc:cx." +
                "fnm00124000215.b4\n" +
                "Link Status:         Up\n" +
                "Port Status:         Online\n" +
                "Switch Present:      Not Applicable\n" +
                "\n" +
                "SP Name:             SP A\n" +
                "SP Port ID:          2\n" +
                "SP UID:              50:06:01:60:88:60:01:95:" +
                "50:06:01:62:08:60:01:95\n" +
                "Link Status:         Down\n" +
                "Port Status:         Online\n" +
                "Switch Present:      NO\n", 0)

    FAKEHOST_PORTS = (
        "Information about each HBA:\n" +
        "\n" +
        "HBA UID:                 20:00:00:90:FA:53:46:41:12:34:" +
        "56:78:90:12:34:56\n" +
        "Server Name:             fakehost\n" +
        "Server IP Address:       10.0.0.2" +
        "HBA Model Description:\n" +
        "HBA Vendor Description:\n" +
        "HBA Device Driver Name:\n" +
        "Information about each port of this HBA:\n\n" +
        "    SP Name:               SP A\n" +
        "    SP Port ID:            0\n" +
        "    HBA Devicename:\n" +
        "    Trusted:               NO\n" +
        "    Logged In:             YES\n" +
        "    Defined:               YES\n" +
        "    Initiator Type:           3\n" +
        "    StorageGroup Name:     fakehost\n\n" +
        "    SP Name:               SP A\n" +
        "    SP Port ID:            2\n" +
        "    HBA Devicename:\n" +
        "    Trusted:               NO\n" +
        "    Logged In:             YES\n" +
        "    Defined:               YES\n" +
        "    Initiator Type:           3\n" +
        "    StorageGroup Name:     fakehost\n\n" +
        "Information about each SPPORT:\n" +
        "\n" +
        "SP Name:             SP A\n" +
        "SP Port ID:          0\n" +
        "SP UID:              50:06:01:60:88:60:01:95:" +
        "50:06:01:60:08:60:01:95\n" +
        "Link Status:         Up\n" +
        "Port Status:         Online\n" +
        "Switch Present:      YES\n" +
        "Switch UID:          10:00:00:05:1E:72:EC:A6:" +
        "20:46:00:05:1E:72:EC:A6\n" +
        "SP Source ID:        272896\n" +
        "\n" +
        "SP Name:             SP B\n" +
        "SP Port ID:          4\n" +
        "SP UID:              iqn.1992-04.com.emc:cx." +
        "fnm00124000215.b4\n" +
        "Link Status:         Up\n" +
        "Port Status:         Online\n" +
        "Switch Present:      Not Applicable\n" +
        "\n" +
        "SP Name:             SP A\n" +
        "SP Port ID:          2\n" +
        "SP UID:              50:06:01:60:88:60:01:95:" +
        "50:06:01:62:08:60:01:95\n" +
        "Link Status:         Down\n" +
        "Port Status:         Online\n" +
        "Switch Present:      NO\n", 0)

    def LUN_PROPERTY(self, name, isThin=False, hasSnap=False, size=1):
        return """\
               LOGICAL UNIT NUMBER 1
               Name:  %s
               UID:  60:06:01:60:09:20:32:00:13:DF:B4:EF:C2:63:E3:11
               Current Owner:  SP A
               Default Owner:  SP A
               Allocation Owner:  SP A
               Attached Snapshot: %s
               User Capacity (Blocks):  2101346304
               User Capacity (GBs):  %d
               Consumed Capacity (Blocks):  2149576704
               Consumed Capacity (GBs):  1024.998
               Pool Name:  Pool_02_SASFLASH
               Current State:  Ready
               Status:  OK(0x0)
               Is Faulted:  false
               Is Transitioning:  false
               Current Operation:  None
               Current Operation State:  N/A
               Current Operation Status:  N/A
               Current Operation Percent Completed:  0
               Is Thin LUN:  %s""" % (name,
                                      'FakeSnap' if hasSnap else 'N/A',
                                      size,
                                      'Yes' if isThin else 'No'), 0

    def STORAGE_GROUP_NO_MAP(self, sgname):
        return ("""\
        Storage Group Name:    %s
        Storage Group UID:     27:D2:BE:C1:9B:A2:E3:11:9A:8D:FF:E5:3A:03:FD:6D
        Shareable:             YES""" % sgname, 0)

    def STORAGE_GROUP_HAS_MAP(self, sgname):

        return ("""\
        Storage Group Name:    %s
        Storage Group UID:     54:46:57:0F:15:A2:E3:11:9A:8D:FF:E5:3A:03:FD:6D
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:222                     SP A         4

        HLU/ALU Pairs:

          HLU Number     ALU Number
          ----------     ----------
            1               1
        Shareable:             YES""" % sgname, 0)


class EMCVNXCLIDriverISCSITestCase(test.TestCase):

    def setUp(self):
        super(EMCVNXCLIDriverISCSITestCase, self).setUp()

        self.stubs.Set(CommandLineHelper, 'command_execute',
                       self.succeed_fake_command_execute)
        self.stubs.Set(CommandLineHelper, 'get_array_serial',
                       mock.Mock(return_value={'array_serial':
                                               'fakeSerial'}))
        self.stubs.Set(os.path, 'exists', mock.Mock(return_value=1))

        self.stubs.Set(emc_vnx_cli, 'INTERVAL_5_SEC', 0.01)
        self.stubs.Set(emc_vnx_cli, 'INTERVAL_30_SEC', 0.01)
        self.stubs.Set(emc_vnx_cli, 'INTERVAL_60_SEC', 0.01)

        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.naviseccli_path = '/opt/Navisphere/bin/naviseccli'
        self.configuration.san_ip = '10.0.0.1'
        self.configuration.storage_vnx_pool_name = 'unit_test_pool'
        self.configuration.san_login = 'sysadmin'
        self.configuration.san_password = 'sysadmin'
        #set the timeout to 0.012s = 0.0002 * 60 = 1.2ms
        self.configuration.default_timeout = 0.0002
        self.configuration.initiator_auto_registration = True
        self.stubs.Set(self.configuration, 'safe_get', self.fake_safe_get)
        self.testData = EMCVNXCLIDriverTestData()
        self.navisecclicmd = '/opt/Navisphere/bin/naviseccli ' + \
            '-address 10.0.0.1 -user sysadmin -password sysadmin -scope 0 '
        self.configuration.iscsi_initiators = '{"fakehost": ["10.0.0.2"]}'

    def tearDown(self):
        super(EMCVNXCLIDriverISCSITestCase, self).tearDown()

    def driverSetup(self, commands=tuple(), results=tuple()):
        self.driver = EMCCLIISCSIDriver(configuration=self.configuration)
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.Mock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli
        return fake_cli

    def get_command_execute_simulator(self, commands=tuple(),
                                      results=tuple()):

        assert(len(commands) == len(results))

        def fake_command_execute(*args, **kwargv):
            for i in range(len(commands)):
                if args == commands[i]:
                    if isinstance(results[i], list):
                        if len(results[i]) > 0:
                            ret = results[i][0]
                            del results[i][0]
                            return ret
                    else:
                        return results[i]
            return self.standard_fake_command_execute(*args, **kwargv)
        return fake_command_execute

    def standard_fake_command_execute(self, *args, **kwargv):
        standard_commands = [
            self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
            self.testData.LUN_PROPERTY_ALL_CMD('vol2'),
            self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
            self.testData.LUN_PROPERTY_ALL_CMD('vol-vol1'),
            self.testData.LUN_PROPERTY_ALL_CMD('snapshot1'),
            self.testData.POOL_PROPERTY_CMD]

        standard_results = [
            self.testData.LUN_PROPERTY('vol1'),
            self.testData.LUN_PROPERTY('vol2'),
            self.testData.LUN_PROPERTY('vol2_dest'),
            self.testData.LUN_PROPERTY('vol-vol1'),
            self.testData.LUN_PROPERTY('snapshot1'),
            self.testData.POOL_PROPERTY]

        standard_default = SUCCEED
        for i in range(len(standard_commands)):
            if args == standard_commands[i]:
                return standard_results[i]

        return standard_default

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    def test_create_destroy_volume_without_extra_spec(self):
        fake_cli = self.driverSetup()
        self.driver.create_volume(self.testData.test_volume)
        self.driver.delete_volume(self.testData.test_volume)
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol1', 1,
                'unit_test_pool',
                'thick', None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
            mock.call(*self.testData.LUN_DELETE_CMD('vol1'))]

        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    def test_create_volume_compressed(self):
        extra_specs = {'storagetype:provisioning': 'compressed'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        #case
        self.driver.create_volume(self.testData.test_volume_with_type)
        #verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'compressed', None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type')),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(
                1))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    def test_create_volume_compressed_tiering_highestavailable(self):
        extra_specs = {'storagetype:provisioning': 'compressed',
                       'storagetype:tiering': 'HighestAvailable'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        #case
        self.driver.create_volume(self.testData.test_volume_with_type)

        #verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'compressed', 'highestavailable')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type')),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(
                1))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    def test_create_volume_deduplicated(self):
        extra_specs = {'storagetype:provisioning': 'deduplicated'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        #case
        self.driver.create_volume(self.testData.test_volume_with_type)

        #verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'deduplicated', None))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    def test_create_volume_tiering_auto(self):
        extra_specs = {'storagetype:tiering': 'Auto'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        #case
        self.driver.create_volume(self.testData.test_volume_with_type)

        #verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                None, 'auto'))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_volume_deduplicated_tiering_auto(self):
        extra_specs = {'storagetype:tiering': 'Auto',
                       'storagetype:provisioning': 'Deduplicated'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        self.driverSetup(commands, results)
        ex = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume,
            self.testData.test_volume_with_type)
        self.assertTrue(
            re.match(r".*deduplicated and auto tiering can't be both enabled",
                     ex.msg))

    def test_create_volume_compressed_no_enabler(self):
        extra_specs = {'storagetype:provisioning': 'Compressed'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   ('No package', 0)]
        self.driverSetup(commands, results)
        ex = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume,
            self.testData.test_volume_with_type)
        self.assertTrue(
            re.match(r".*Compression Enabler is not installed",
                     ex.msg))

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    def test_create_compression_volume_on_array_backend(self):
        """Unit test for create a compression volume on array
        backend.
        """
        #Set up the array backend
        config = conf.Configuration(None)
        config.append_config_values = mock.Mock(return_value=0)
        config.naviseccli_path = '/opt/Navisphere/bin/naviseccli'
        config.san_ip = '10.0.0.1'
        config.san_login = 'sysadmin'
        config.san_password = 'sysadmin'
        config.default_timeout = 0.0002
        config.initiator_auto_registration = True
        config.navisecclicmd = '/opt/Navisphere/bin/naviseccli ' + \
            '-address 10.0.0.1 -user sysadmin -password sysadmin -scope 0 '
        config.iscsi_initiators = '{"fakehost": ["10.0.0.2"]}'
        self.driver = EMCCLIISCSIDriver(configuration=config)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliArray)

        extra_specs = {'storagetype:provisioning': 'Compressed',
                       'storagetype:pool': 'unit_test_pool'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.MagicMock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli

        self.driver.cli.stats['compression_support'] = 'True'
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        #case
        self.driver.create_volume(self.testData.test_volume_with_type)
        #verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'compressed', None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type')),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(
                1))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_get_volume_stats(self):
        #expect_result = [POOL_PROPERTY]
        self.driverSetup()
        stats = self.driver.get_volume_stats(True)
        self.assertTrue(stats['driver_version'] is not None,
                        "dirver_version is not returned")
        self.assertTrue(
            stats['free_capacity_gb'] == 1000.6,
            "free_capacity_gb is not correct")
        self.assertTrue(
            stats['reserved_percentage'] == 0,
            "reserved_percentage is not correct")
        self.assertTrue(
            stats['storage_protocol'] == 'iSCSI',
            "storage_protocol is not correct")
        self.assertTrue(
            stats['total_capacity_gb'] == 10000.5,
            "total_capacity_gb is not correct")
        self.assertTrue(
            stats['vendor_name'] == "EMC",
            "vender name is not correct")
        self.assertTrue(
            stats['volume_backend_name'] == "namedbackend",
            "volume backend name is not correct")
        self.assertTrue(stats['location_info'] == "unit_test_pool|fakeSerial")
        self.assertTrue(
            stats['driver_version'] == "04.00.00",
            "driver version is incorrect.")

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(return_value=True))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            side_effect=[1, 1]))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase."
        "get_lun_id_by_name",
        mock.Mock(return_value=1))
    def test_volume_migration_timeout(self):
        commands = [self.testData.MIGRATION_CMD(),
                    self.testData.MIGRATION_VERIFY_CMD(1)]
        FAKE_ERROR_MSG = """\
A network error occurred while trying to connect: '10.244.213.142'.
Message : Error occurred because connection refused. \
Unable to establish a secure connection to the Management Server.
"""
        FAKE_ERROR_MSG = FAKE_ERROR_MSG.replace('\n', ' ')
        FAKE_MIGRATE_PROPERTY = """\
Source LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d
Source LU ID:  63950
Dest LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d_dest
Dest LU ID:  136
Migration Rate:  high
Current State:  MIGRATED
Percent Complete:  100
Time Remaining:  0 second(s)
"""
        results = [(FAKE_ERROR_MSG, 255),
                   [SUCCEED,
                    (FAKE_MIGRATE_PROPERTY, 0),
                    ('The specified source LUN is not currently migrating',
                     23)]]
        fake_cli = self.driverSetup(commands, results)
        fakehost = {'capabilities': {'location_info':
                                     "unit_test_pool2|fakeSerial",
                                     'storage_protocol': 'iSCSI'}}
        ret = self.driver.migrate_volume(None, self.testData.test_volume,
                                         fakehost)[0]
        self.assertTrue(ret)
        #verification
        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(1, 1),
                                retry_disable=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1)),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(
                    return_value=True))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            side_effect=[1, 1]))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase."
        "get_lun_id_by_name",
        mock.Mock(return_value=1))
    def test_volume_migration(self):

        commands = [self.testData.MIGRATION_CMD(),
                    self.testData.MIGRATION_VERIFY_CMD(1)]
        FAKE_MIGRATE_PROPERTY = """\
Source LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d
Source LU ID:  63950
Dest LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d_dest
Dest LU ID:  136
Migration Rate:  high
Current State:  MIGRATED
Percent Complete:  100
Time Remaining:  0 second(s)
"""
        results = [SUCCEED, [(FAKE_MIGRATE_PROPERTY, 0),
                             ('The specified source LUN is not '
                              'currently migrating',
                              23)]]
        fake_cli = self.driverSetup(commands, results)
        fakehost = {'capabilities': {'location_info':
                                     "unit_test_pool2|fakeSerial",
                                     'storage_protocol': 'iSCSI'}}
        ret = self.driver.migrate_volume(None, self.testData.test_volume,
                                         fakehost)[0]
        self.assertTrue(ret)
        #verification
        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(),
                                retry_disable=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1)),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(
                    return_value=True))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase."
        "get_lun_id_by_name",
        mock.Mock(return_value=5))
    def test_volume_migration_02(self):

        commands = [self.testData.MIGRATION_CMD(5, 5),
                    self.testData.MIGRATION_VERIFY_CMD(5)]
        FAKE_MIGRATE_PROPERTY = """\
Source LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d
Source LU ID:  63950
Dest LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d_dest
Dest LU ID:  136
Migration Rate:  high
Current State:  MIGRATED
Percent Complete:  100
Time Remaining:  0 second(s)
"""
        results = [SUCCEED, [(FAKE_MIGRATE_PROPERTY, 0),
                             ('The specified source LUN is not '
                              'currently migrating',
                              23)]]
        fake_cli = self.driverSetup(commands, results)
        fakehost = {'capabilities': {'location_info':
                                     "unit_test_pool2|fakeSerial",
                                     'storage_protocol': 'iSCSI'}}
        ret = self.driver.migrate_volume(None, self.testData.test_volume5,
                                         fakehost)[0]
        self.assertTrue(ret)
        #verification
        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(5, 5),
                                retry_disable=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(5)),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(5))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(
                    return_value=True))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            side_effect=[1, 1]))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase."
        "get_lun_id_by_name",
        mock.Mock(return_value=1))
    def test_volume_migration_failed(self):
        commands = [self.testData.MIGRATION_CMD()]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)
        fakehost = {'capabilities': {'location_info':
                                     "unit_test_pool2|fakeSerial",
                                     'storage_protocol': 'iSCSI'}}
        ret = self.driver.migrate_volume(None, self.testData.test_volume,
                                         fakehost)[0]
        self.assertFalse(ret)
        #verification
        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(),
                                retry_disable=True)]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_destroy_volume_snapshot(self):
        fake_cli = self.driverSetup()

        #case
        self.driver.create_snapshot(self.testData.test_snapshot)
        self.driver.delete_snapshot(self.testData.test_snapshot)

        #verification
        expect_cmd = [mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
                      mock.call(*self.testData.SNAP_CREATE_CMD('snapshot1')),
                      mock.call(*self.testData.SNAP_DELETE_CMD('snapshot1'))]

        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.openstack.common.processutils.execute",
        mock.Mock(
            return_value=(
                "fakeportal iqn.1992-04.fake.com:fake.apm00123907237.a8", 0)))
    @mock.patch("random.shuffle", mock.Mock())
    def test_initialize_connection(self):
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
                    self.testData.GETPORT_CMD(),
                    self.testData.PINGNODE_CMD('A', 4, 0, '10.0.0.2')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_NO_MAP('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   self.testData.ALL_PORTS,
                   self.testData.PING_OK]

        fake_cli = self.driverSetup(commands, results)
        connection_info = self.driver.initialize_connection(
            self.testData.test_volume,
            self.testData.connector)

        self.assertEqual(connection_info,
                         self.testData.iscsi_connection_info_ro)

        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-list'),
                    mock.call(*self.testData.GETPORT_CMD()),
                    mock.call('storagegroup', '-gname', 'fakehost', '-setpath',
                              '-hbauid', 'iqn.1993-08.org.debian:01:222',
                              '-sp', 'A', '-spport', 4, '-spvport', 0,
                              '-ip', '10.0.0.2', '-host', 'fakehost', '-o'),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-addhlu', '-hlu', 1, '-alu', 1,
                              '-gname', 'fakehost'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call(*self.testData.GETPORT_CMD()),
                    mock.call(*self.testData.PINGNODE_CMD('A', 4, 0,
                                                          '10.0.0.2'))]
        fake_cli.assert_has_calls(expected)

        # Test for manaul registration
        self.configuration.initiator_auto_registration = False

        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
                    self.testData.CONNECTHOST_CMD('fakehost', 'fakehost'),
                    self.testData.GETPORT_CMD(),
                    self.testData.PINGNODE_CMD('A', 4, 0, '10.0.0.2')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_NO_MAP('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   ('', 0),
                   self.testData.ALL_PORTS,
                   self.testData.PING_OK]
        fake_cli = self.driverSetup(commands, results)
        connection_info = self.driver.initialize_connection(
            self.testData.test_volume_rw,
            self.testData.connector)

        self.assertEqual(connection_info,
                         self.testData.iscsi_connection_info_rw)

        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-addhlu', '-hlu', 1, '-alu', 1,
                              '-gname', 'fakehost'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('connection', '-getport', '-address', '-vlanid')]
        fake_cli.assert_has_calls(expected)

    def test_terminate_connection(self):

        os.path.exists = mock.Mock(return_value=1)
        self.driver = EMCCLIISCSIDriver(configuration=self.configuration)
        cli_helper = self.driver.cli._client
        data = {'storage_group_name': "fakehost",
                'storage_group_uid': "2F:D4:00:00:00:00:00:"
                "00:00:00:FF:E5:3A:03:FD:6D",
                'lunmap': {1: 16, 2: 88, 3: 47}}
        cli_helper.get_storage_group = mock.Mock(
            return_value=data)
        lun_info = {'lun_name': "unit_test_lun",
                    'lun_id': 1,
                    'pool': "unit_test_pool",
                    'attached_snapshot': "N/A",
                    'owner': "A",
                    'total_capacity_gb': 1.0,
                    'state': "Ready"}
        cli_helper.get_lun_by_name = mock.Mock(return_value=lun_info)
        cli_helper.remove_hlu_from_storagegroup = mock.Mock()
        self.driver.terminate_connection(self.testData.test_volume,
                                         self.testData.connector)
        cli_helper.remove_hlu_from_storagegroup.assert_called_once_with(
            16, self.testData.connector["host"])
#         expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost'),
#                     mock.call('lun', '-list', '-name', 'vol1'),
#                     mock.call('storagegroup', '-list', '-gname', 'fakehost'),
#                     mock.call('lun', '-list', '-l', '10', '-owner')]

    def test_create_volume_cli_failed(self):
        commands = [self.testData.LUN_CREATION_CMD(
            'failed_vol1', 1, 'unit_test_pool', None, None)]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(EMCVnxCLICmdError,
                          self.driver.create_volume,
                          self.testData.test_failed_volume)
        expect_cmd = [mock.call(*self.testData.LUN_CREATION_CMD(
            'failed_vol1', 1, 'unit_test_pool', None, None))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_volume_snapshot_failed(self):
        commands = [self.testData.SNAP_CREATE_CMD('failed_snapshot')]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        #case
        self.assertRaises(EMCVnxCLICmdError,
                          self.driver.create_snapshot,
                          self.testData.test_failed_snapshot)

        #verification
        expect_cmd = [
            mock.call(
                *self.testData.LUN_PROPERTY_ALL_CMD(
                    'vol-vol1')),
            mock.call(
                *self.testData.SNAP_CREATE_CMD(
                    'failed_snapshot'))]

        fake_cli.assert_has_calls(expect_cmd)

    def test_create_volume_from_snapshot(self):
        #set up
        cmd_smp = ('lun', '-list', '-name', 'vol2', '-attachedSnapshot')
        output_smp = ("""LOGICAL UNIT NUMBER 1
                     Name:  vol2
                     Attached Snapshot:  N/A""", 0)
        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        output_dest = self.testData.LUN_PROPERTY("vol2_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        output_migrate = ("", 0)
        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        commands = [cmd_smp, cmd_dest, cmd_migrate, cmd_migrate_verify]
        results = [output_smp, output_dest, output_migrate,
                   output_migrate_verify]
        fake_cli = self.driverSetup(commands, results)

        self.driver.create_volume_from_snapshot(self.testData.test_volume2,
                                                self.testData.test_snapshot)
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_MP_CREATE_CMD(
                    name='vol2', source='vol1')),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='snapshot1')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest')),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      retry_disable=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1)),

            mock.call('lun', '-list', '-name', 'vol2', '-attachedSnapshot')]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_volume_from_snapshot_sync_failed(self):

        output_smp = ("""LOGICAL UNIT NUMBER 1
                    Name:  vol1
                    Attached Snapshot:  fakesnap""", 0)
        cmd_smp = ('lun', '-list', '-name', 'vol2', '-attachedSnapshot')
        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        output_dest = self.testData.LUN_PROPERTY("vol2_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        output_migrate = ("", 0)
        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        commands = [cmd_smp, cmd_dest, cmd_migrate, cmd_migrate_verify]
        results = [output_smp, output_dest, output_migrate,
                   output_migrate_verify]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.testData.test_volume2,
                          self.testData.test_snapshot)
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_MP_CREATE_CMD(
                    name='vol2', source='vol1')),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='snapshot1')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest')),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      retry_disable=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_cloned_volume(self):
        cmd_smp = ('lun', '-list', '-name', 'vol1', '-attachedSnapshot')
        output_smp = ("""LOGICAL UNIT NUMBER 1
                     Name:  vol1
                     Attached Snapshot:  N/A""", 0)
        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol1_dest")
        output_dest = self.testData.LUN_PROPERTY("vol1_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        output_migrate = ("", 0)
        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        commands = [cmd_smp, cmd_dest, cmd_migrate,
                    cmd_migrate_verify,
                    self.testData.NDU_LIST_CMD]
        results = [output_smp, output_dest, output_migrate,
                   output_migrate_verify,
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)

        self.driver.create_cloned_volume(self.testData.test_volume,
                                         self.testData.test_snapshot)
        tmp_snap = 'tmp-snap-' + self.testData.test_volume['id']
        expect_cmd = [
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('snapshot1')),
            mock.call(
                *self.testData.SNAP_CREATE_CMD(tmp_snap)),
            mock.call(*self.testData.SNAP_MP_CREATE_CMD(name='vol1',
                                                        source='snapshot1')),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol1', snapName=tmp_snap)),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol1_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1_dest')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1_dest')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1_dest')),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      retry_disable=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1)),
            mock.call('lun', '-list', '-name', 'vol1', '-attachedSnapshot'),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
            mock.call(*self.testData.SNAP_DELETE_CMD(tmp_snap))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_delete_volume_failed(self):
        commands = [self.testData.LUN_DELETE_CMD('failed_vol1')]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(EMCVnxCLICmdError,
                          self.driver.delete_volume,
                          self.testData.test_failed_volume)
        expected = [mock.call(*self.testData.LUN_DELETE_CMD('failed_vol1'))]
        fake_cli.assert_has_calls(expected)

    def test_extend_volume(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol1')]
        results = [self.testData.LUN_PROPERTY('vol1', size=2)]
        fake_cli = self.driverSetup(commands, results)

        # case
        self.driver.extend_volume(self.testData.test_volume, 2)
        expected = [mock.call(*self.testData.LUN_EXTEND_CMD('vol1', 2)),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                        'vol1'))]
        fake_cli.assert_has_calls(expected)

    def test_extend_volume_has_snapshot(self):
        commands = [self.testData.LUN_EXTEND_CMD('failed_vol1', 2)]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(EMCVnxCLICmdError,
                          self.driver.extend_volume,
                          self.testData.test_failed_volume,
                          2)
        expected = [mock.call(*self.testData.LUN_EXTEND_CMD('failed_vol1', 2))]
        fake_cli.assert_has_calls(expected)

    def test_extend_volume_failed(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('failed_vol1')]
        results = [self.testData.LUN_PROPERTY('failed_vol1', size=2)]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.testData.test_failed_volume,
                          3)
        expected = [
            mock.call(
                *self.testData.LUN_EXTEND_CMD('failed_vol1', 3)),
            mock.call(
                *self.testData.LUN_PROPERTY_ALL_CMD('failed_vol1'))]
        fake_cli.assert_has_calls(expected)

    def test_create_remove_export(self):
        fake_cli = self.driverSetup()

        self.driver.create_export(None, self.testData.test_volume)
        self.driver.remove_export(None, self.testData.test_volume)
        expected = [mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'))]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing(self):
        """Unit test for the manage_existing function
        of driver
        """
        get_lun_cmd = ('lun', '-list', '-l', self.testData.test_lun_id,
                       '-state', '-userCap', '-owner',
                       '-attachedSnapshot', '-poolName')
        lun_rename_cmd = ('lun', '-modify', '-l', self.testData.test_lun_id,
                          '-newName', 'vol_with_type', '-o')
        commands = [get_lun_cmd, lun_rename_cmd]

        results = [self.testData.LUN_PROPERTY('lun_name'), SUCCEED]
        self.configuration.storage_vnx_pool_name = \
            self.testData.test_pool_name
        self.driver = EMCCLIISCSIDriver(configuration=self.configuration)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliPool)
        #mock the command executor
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.MagicMock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli
        self.driver.manage_existing(
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref)
        expected = [mock.call(*get_lun_cmd),
                    mock.call(*lun_rename_cmd)]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing_lun_in_another_pool(self):
        """Unit test for the manage_existing function
        of driver with a invalid pool backend.
        An exception would occur in this case
        """
        get_lun_cmd = ('lun', '-list', '-l', self.testData.test_lun_id,
                       '-state', '-userCap', '-owner',
                       '-attachedSnapshot', '-poolName')
        commands = [get_lun_cmd]

        results = [self.testData.LUN_PROPERTY('lun_name')]
        invalid_pool_name = "fake_pool"
        self.configuration.storage_vnx_pool_name = invalid_pool_name
        self.driver = EMCCLIISCSIDriver(configuration=self.configuration)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliPool)
        #mock the command executor
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.MagicMock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli
        ex = self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing,
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref)
        self.assertTrue(
            re.match(r'.*not in a manageable pool backend by cinder',
                     ex.msg))
        expected = [mock.call(*get_lun_cmd)]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing_get_size(self):
        """Unit test for the manage_existing_get_size
        function of driver.
        """
        get_lun_cmd = ('lun', '-list', '-l', self.testData.test_lun_id,
                       '-state', '-status', '-opDetails', '-userCap', '-owner',
                       '-attachedSnapshot')
        test_size = 2
        commands = [get_lun_cmd]
        results = [self.testData.LUN_PROPERTY('lun_name', size=test_size)]

        self.configuration.storage_vnx_pool_name = \
            self.testData.test_pool_name
        self.driver = EMCCLIISCSIDriver(configuration=self.configuration)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliPool)

        #mock the command executor
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.MagicMock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli

        get_size = self.driver.manage_existing_get_size(
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref)
        expected = [mock.call(*get_lun_cmd)]
        assert get_size == test_size
        fake_cli.assert_has_calls(expected)
        #Test the function with invalid reference.
        invaild_ref = {'fake': 'fake_ref'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          self.testData.test_volume_with_type,
                          invaild_ref)

    def test_manage_existing_with_array_backend(self):
        """Unit test for the manage_existing with the
        array backend which is not support the manage
        existing functinality.
        """
        #Set up the array backend
        config = conf.Configuration(None)
        config.append_config_values = mock.Mock(return_value=0)
        config.naviseccli_path = '/opt/Navisphere/bin/naviseccli'
        config.san_ip = '10.0.0.1'
        config.san_login = 'sysadmin'
        config.san_password = 'sysadmin'
        config.default_timeout = 0.0002
        config.initiator_auto_registration = True
        config.navisecclicmd = '/opt/Navisphere/bin/naviseccli ' + \
            '-address 10.0.0.1 -user sysadmin -password sysadmin -scope 0 '
        config.iscsi_initiators = '{"fakehost": ["10.0.0.2"]}'
        self.driver = EMCCLIISCSIDriver(configuration=config)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliArray)
        #mock the command executor
        lun_rename_cmd = ('lun', '-modify', '-l', self.testData.test_lun_id,
                          '-newName', 'vol_with_type', '-o')
        commands = [lun_rename_cmd]
        results = [SUCCEED]
        #mock the command executor
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.MagicMock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli
        self.driver.manage_existing(
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref)
        expected = [mock.call(*lun_rename_cmd)]
        fake_cli.assert_has_calls(expected)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase."
        "get_lun_id_by_name",
        mock.Mock(return_value=1))
    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "time.time",
        mock.Mock(return_value=123456))
    def test_retype_compressed_to_deduplicated(self):
        """Unit test for retype compressed to deduplicated."""
        diff_data = {'encryption': {}, 'qos_specs': {},
                     'extra_specs':
                     {'storagetype:provsioning': ('compressed',
                                                  'deduplicated')}}

        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:provisioning':
                                         'deduplicated'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'ubuntu-server12@pool_backend_1',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    ('snap', '-list', '-res', 1)]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        extra_specs = {'storagetype:provisioning': 'compressed'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)
        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd = [
            mock.call('snap', '-list', '-res', 1),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol3-123456', 2, 'unit_test_pool', 'deduplicated', None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol3-123456')),
            mock.call(*self.testData.MIGRATION_CMD(), retry_disable=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 1}))
    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "time.time",
        mock.Mock(return_value=123456))
    def test_retype_thin_to_compressed_auto(self):
        """Unit test for retype thin to compressed and auto tiering."""
        diff_data = {'encryption': {}, 'qos_specs': {},
                     'extra_specs':
                     {'storagetype:provsioning': ('thin',
                                                  'compressed'),
                      'storagetype:tiering': (None, 'auto')}}

        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:provisioning':
                                         'compressed',
                                         'storagetype:tiering': 'auto'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'ubuntu-server12@pool_backend_1',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    ('snap', '-list', '-res', 1)]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        extra_specs = {'storagetype:provisioning': 'thin'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)
        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd = [
            mock.call('snap', '-list', '-res', 1),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol3-123456', 2, 'unit_test_pool', 'compressed', 'auto')),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(1)),
            mock.call(*self.testData.MIGRATION_CMD(), retry_disable=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 1}))
    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "time.time",
        mock.Mock(return_value=123456))
    def test_retype_pool_changed_dedup_to_compressed_auto(self):
        """Unit test for retype dedup to compressed and auto tiering
        and pool changed
        """
        diff_data = {'encryption': {}, 'qos_specs': {},
                     'extra_specs':
                     {'storagetype:provsioning': ('deduplicated',
                                                  'compressed'),
                      'storagetype:tiering': (None, 'auto'),
                      'storagetype:pool': ('unit_test_pool',
                                           'unit_test_pool2')}}

        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:provisioning':
                                             'compressed',
                                         'storagetype:tiering': 'auto',
                                         'storagetype:pool':
                                             'unit_test_pool2'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'ubuntu-server12@pool_backend_1',
                          'capabilities':
                          {'location_info': 'unit_test_pool2|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    ('snap', '-list', '-res', 1)]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        extra_specs = {'storagetype:provisioning': 'deduplicated',
                       'storagetype:pool': 'unit_test_pool'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)
        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd = [
            mock.call('snap', '-list', '-res', 1),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol3-123456', 2, 'unit_test_pool2', 'compressed', 'auto')),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(1)),
            mock.call(*self.testData.MIGRATION_CMD(), retry_disable=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 1}))
    def test_retype_compressed_auto_to_compressed_nomovement(self):
        """Unit test for retype only tiering changed."""
        diff_data = {'encryption': {}, 'qos_specs': {},
                     'extra_specs':
                     {'storagetype:tiering': ('auto', 'nomovement')}}

        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:provisioning':
                                             'compressed',
                                         'storagetype:tiering': 'nomovement',
                                         'storagetype:pool':
                                             'unit_test_pool'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'ubuntu-server12@pool_backend_1',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    ('snap', '-list', '-res', 1)]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        extra_specs = {'storagetype:provisioning': 'compressed',
                       'storagetype:pool': 'unit_test_pool',
                       'storagetype:tiering': 'auto'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)
        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd = [
            mock.call('lun', '-modify', '-name', 'vol3', '-o', '-initialTier',
                      'optimizePool', '-tieringPolicy', 'noMovement')]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 1}))
    def test_retype_compressed_to_thin_cross_array(self):
        """Unit test for retype cross array."""
        diff_data = {'encryption': {}, 'qos_specs': {},
                     'extra_specs':
                     {'storagetype:provsioning': ('compressed', 'thin')}}

        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:provisioning': 'thin',
                                         'storagetype:pool':
                                             'unit_test_pool'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'ubuntu-server12@pool_backend_2',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500891',
                           'volume_backend_name': 'pool_backend_2',
                           'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    ('snap', '-list', '-res', 1)]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023)]
        self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        extra_specs = {'storagetype:provisioning': 'thin',
                       'storagetype:pool': 'unit_test_pool'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)
        retyped = self.driver.retype(None, self.testData.test_volume3,
                                     new_type_data, diff_data,
                                     host_test_data)
        self.assertFalse(retyped,
                         "Retype should failed due to"
                         " different protocol or array")

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 1}))
    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "time.time",
        mock.Mock(return_value=123456))
    def test_retype_thin_auto_to_dedup_diff_procotol(self):
        """Unit test for retype different procotol."""
        diff_data = {'encryption': {}, 'qos_specs': {},
                     'extra_specs':
                     {'storagetype:provsioning': ('thin', 'deduplicated'),
                      'storagetype:tiering': ('auto', None)}}

        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:provisioning':
                                             'deduplicated',
                                         'storagetype:pool':
                                             'unit_test_pool'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'ubuntu-server12@pool_backend_2',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500890',
                           'volume_backend_name': 'pool_backend_2',
                           'storage_protocol': 'FC'}}

        commands = [self.testData.NDU_LIST_CMD,
                    ('snap', '-list', '-res', 1)]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        extra_specs = {'storagetype:provisioning': 'thin',
                       'storagetype:tiering': 'auto',
                       'storagetype:pool': 'unit_test_pool'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd = [
            mock.call('snap', '-list', '-res', 1),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol3-123456', 2, 'unit_test_pool', 'deduplicated', None)),
            mock.call(*self.testData.MIGRATION_CMD(), retry_disable=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 1}))
    def test_retype_thin_auto_has_snap_to_thick_highestavailable(self):
        """Unit test for retype volume has snap when need migration."""
        diff_data = {'encryption': {}, 'qos_specs': {},
                     'extra_specs':
                     {'storagetype:provsioning': ('thin', None),
                      'storagetype:tiering': ('auto', 'highestAvailable')}}

        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:tiering':
                                             'highestAvailable',
                                         'storagetype:pool':
                                             'unit_test_pool'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'ubuntu-server12@pool_backend_1',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    ('snap', '-list', '-res', 1)]
        results = [self.testData.NDU_LIST_RESULT,
                   ('Has snap', 0)]
        self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        extra_specs = {'storagetype:provisioning': 'thin',
                       'storagetype:tiering': 'auto',
                       'storagetype:pool': 'unit_test_pool'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        retyped = self.driver.retype(None, self.testData.test_volume3,
                                     new_type_data,
                                     diff_data,
                                     host_test_data)
        self.assertFalse(retyped,
                         "Retype should failed due to"
                         " different protocol or array")

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 1}))
    def test_retype_thin_auto_to_thin_auto(self):
        """Unit test for retype volume which has no change."""
        diff_data = {'encryption': {}, 'qos_specs': {},
                     'extra_specs': {}}

        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:tiering':
                                             'auto',
                                         'storagetype:provisioning':
                                             'thin'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'ubuntu-server12@pool_backend_1',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD]
        results = [self.testData.NDU_LIST_RESULT]
        self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        extra_specs = {'storagetype:provisioning': 'thin',
                       'storagetype:tiering': 'auto',
                       'storagetype:pool': 'unit_test_pool'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)
        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)

    def test_create_volume_with_fastcache(self):
        '''enable fastcache when creating volume.'''
        extra_specs = {'fast_cache_enabled': 'True'}
        volume_types.get_volume_type_extra_specs = \
            mock.Mock(return_value=extra_specs)

        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD,
                    self.testData.CHECK_FASTCACHE_CMD(
                        self.testData.test_pool_name)]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   SUCCEED,
                   ('FAST Cache:  Enabled', 0)]
        fake_cli = self.driverSetup(commands, results)

        lun_info = {'lun_name': "vol_with_type",
                    'lun_id': 1,
                    'pool': "unit_test_pool",
                    'attached_snapshot': "N/A",
                    'owner': "A",
                    'total_capacity_gb': 1.0,
                    'state': "Ready",
                    'status': 'OK(0x0)',
                    'operation': 'None'
                    }

        self.configuration.storage_vnx_pool_name = \
            self.testData.test_pool_name
        self.driver = EMCCLIISCSIDriver(configuration=self.configuration)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliPool)

        cli_helper = self.driver.cli._client
        cli_helper.command_execute = fake_cli
        cli_helper.get_lun_by_name = mock.Mock(return_value=lun_info)
        cli_helper.get_enablers_on_array = mock.Mock(return_value="-FASTCache")
        self.driver.update_volume_stats()
        self.driver.create_volume(self.testData.test_volume_with_type)
        self.assertEqual(self.driver.cli.stats['fast_cache_enabled'], 'True')
        expect_cmd = [
            mock.call('storagepool', '-list', '-name',
                      'Pool_02_SASFLASH', '-userCap', '-availableCap'),
            mock.call('-np', 'storagepool', '-list', '-name',
                      'Pool_02_SASFLASH', '-fastcache'),
            mock.call('lun', '-create', '-capacity',
                      1, '-sq', 'gb', '-poolName', 'Pool_02_SASFLASH',
                      '-name', 'vol_with_type', '-type', 'NonThin')
        ]

        fake_cli.assert_has_calls(expect_cmd)

    def test_get_lun_id_provider_location_exists(self):
        '''test function get_lun_id.'''
        self.driverSetup()
        volume_01 = {
            'name': 'vol_01',
            'size': 1,
            'volume_name': 'vol_01',
            'id': '1',
            'name_id': '1',
            'provider_location': 'system^FNM11111|type^lun|lun_id^1',
            'project_id': 'project',
            'display_name': 'vol_01',
            'display_description': 'test volume',
            'volume_type_id': None,
            'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}]}
        self.assertEqual(self.driver.cli.get_lun_id(volume_01), 1)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 2}))
    def test_get_lun_id_provider_location_has_no_lun_id(self):
        '''test function get_lun_id.'''
        self.driverSetup()
        volume_02 = {
            'name': 'vol_02',
            'size': 1,
            'volume_name': 'vol_02',
            'id': '2',
            'provider_location': 'system^FNM11111|type^lun|',
            'project_id': 'project',
            'display_name': 'vol_02',
            'display_description': 'test volume',
            'volume_type_id': None,
            'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}]}
        self.assertEqual(self.driver.cli.get_lun_id(volume_02), 2)

    def succeed_fake_command_execute(self, *command, **kwargv):
        return SUCCEED

    def fake_get_pool_properties(self, filter_option, properties=None):
        pool_info = {'pool_name': "unit_test_pool0",
                     'total_capacity_gb': 1000.0,
                     'free_capacity_gb': 1000.0
                     }
        return pool_info

    def fake_get_lun_properties(self, filter_option, properties=None):
        lun_info = {'lun_name': "vol1",
                    'lun_id': 1,
                    'pool': "unit_test_pool",
                    'attached_snapshot': "N/A",
                    'owner': "A",
                    'total_capacity_gb': 1.0,
                    'state': "Ready"}
        return lun_info

    def fake_safe_get(self, value):
        if value == "storage_vnx_pool_name":
            return "unit_test_pool"
        elif 'volume_backend_name' == value:
            return "namedbackend"
        else:
            return None


class EMCVNXCLIDriverFCTestCase(test.TestCase):

    def setUp(self):
        super(EMCVNXCLIDriverFCTestCase, self).setUp()

        self.stubs.Set(CommandLineHelper, 'command_execute',
                       self.succeed_fake_command_execute)
        self.stubs.Set(CommandLineHelper, 'get_array_serial',
                       mock.Mock(return_value={'array_serial':
                                               "fakeSerial"}))
        self.stubs.Set(os.path, 'exists', mock.Mock(return_value=1))

        self.stubs.Set(emc_vnx_cli, 'INTERVAL_5_SEC', 0.01)
        self.stubs.Set(emc_vnx_cli, 'INTERVAL_30_SEC', 0.01)
        self.stubs.Set(emc_vnx_cli, 'INTERVAL_60_SEC', 0.01)

        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.naviseccli_path = '/opt/Navisphere/bin/naviseccli'
        self.configuration.san_ip = '10.0.0.1'
        self.configuration.storage_vnx_pool_name = 'unit_test_pool'
        self.configuration.san_login = 'sysadmin'
        self.configuration.san_password = 'sysadmin'
        #set the timeout to 0.012s = 0.0002 * 60 = 1.2ms
        self.configuration.default_timeout = 0.0002
        self.configuration.initiator_auto_registration = True
        self.configuration.zoning_mode = None
        self.stubs.Set(self.configuration, 'safe_get', self.fake_safe_get)
        self.testData = EMCVNXCLIDriverTestData()
        self.navisecclicmd = '/opt/Navisphere/bin/naviseccli ' + \
            '-address 10.0.0.1 -user sysadmin -password sysadmin -scope 0 '

    def tearDown(self):
        super(EMCVNXCLIDriverFCTestCase, self).tearDown()

    def driverSetup(self, commands=tuple(), results=tuple()):
        self.driver = EMCCLIFCDriver(configuration=self.configuration)
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.Mock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli
        return fake_cli

    def get_command_execute_simulator(self, commands=tuple(),
                                      results=tuple()):

        assert(len(commands) == len(results))

        def fake_command_execute(*args, **kwargv):
            for i in range(len(commands)):
                if args == commands[i]:
                    if isinstance(results[i], list):
                        if len(results[i]) > 0:
                            ret = results[i][0]
                            del results[i][0]
                            return ret
                    else:
                        return results[i]
            return self.standard_fake_command_execute(*args, **kwargv)
        return fake_command_execute

    def standard_fake_command_execute(self, *args, **kwargv):
        standard_commands = [
            self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
            self.testData.LUN_PROPERTY_ALL_CMD('vol2'),
            self.testData.LUN_PROPERTY_ALL_CMD('vol-vol1'),
            self.testData.LUN_PROPERTY_ALL_CMD('snapshot1'),
            self.testData.POOL_PROPERTY_CMD]

        standard_results = [
            self.testData.LUN_PROPERTY('vol1'),
            self.testData.LUN_PROPERTY('vol2'),
            self.testData.LUN_PROPERTY('vol-vol1'),
            self.testData.LUN_PROPERTY('snapshot1'),
            self.testData.POOL_PROPERTY]

        standard_default = SUCCEED
        for i in range(len(standard_commands)):
            if args == standard_commands[i]:
                return standard_results[i]

        return standard_default

    def succeed_fake_command_execute(self, *command, **kwargv):
        return SUCCEED

    def fake_get_pool_properties(self, filter_option, properties=None):
        pool_info = {'pool_name': "unit_test_pool0",
                     'total_capacity_gb': 1000.0,
                     'free_capacity_gb': 1000.0
                     }
        return pool_info

    def fake_get_lun_properties(self, filter_option, properties=None):
        lun_info = {'lun_name': "vol1",
                    'lun_id': 1,
                    'pool': "unit_test_pool",
                    'attached_snapshot': "N/A",
                    'owner': "A",
                    'total_capacity_gb': 1.0,
                    'state': "Ready"}
        return lun_info

    def fake_safe_get(self, value):
        if value == "storage_vnx_pool_name":
            return "unit_test_pool"
        elif 'volume_backend_name' == value:
            return "namedbackend"
        else:
            return None

    @mock.patch(
        "cinder.openstack.common.processutils.execute",
        mock.Mock(
            return_value=(
                "fakeportal iqn.1992-04.fake.com:fake.apm00123907237.a8", 0)))
    @mock.patch("random.shuffle", mock.Mock())
    def test_initialize_connection_fc_auto_reg(self):
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
                    ('storagegroup', '-list'),
                    self.testData.GETFCPORT_CMD(),
                    ('port', '-list', '-gname', 'fakehost')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_NO_MAP('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   self.testData.STORAGE_GROUP_HAS_MAP('fakehost'),
                   self.testData.FC_PORTS,
                   self.testData.FAKEHOST_PORTS]

        fake_cli = self.driverSetup(commands, results)
        data = self.driver.initialize_connection(
            self.testData.test_volume,
            self.testData.connector)

        self.assertEqual(data['data']['access_mode'], 'ro')

        expected = [
            mock.call('storagegroup', '-list', '-gname', 'fakehost'),
            mock.call('storagegroup', '-create', '-gname', 'fakehost'),
            mock.call('storagegroup', '-list'),
            mock.call('port', '-list', '-sp'),
            mock.call('storagegroup', '-gname', 'fakehost',
                      '-setpath', '-hbauid',
                      '22:34:56:78:90:12:34:56:12:34:56:78:90:12:34:56',
                      '-sp', 'A', '-spport', '0', '-ip', '10.0.0.2',
                      '-host', 'fakehost', '-o'),
            mock.call('port', '-list', '-sp'),
            mock.call('storagegroup', '-gname', 'fakehost',
                      '-setpath', '-hbauid',
                      '22:34:56:78:90:54:32:16:12:34:56:78:90:54:32:16',
                      '-sp', 'A', '-spport', '0', '-ip', '10.0.0.2',
                      '-host', 'fakehost', '-o'),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
            mock.call('storagegroup', '-list', '-gname', 'fakehost'),
            mock.call('storagegroup', '-addhlu', '-hlu', 1, '-alu', 1,
                      '-gname', 'fakehost'),
            mock.call('port', '-list', '-gname', 'fakehost'),
            mock.call('storagegroup', '-list', '-gname', 'fakehost'),
            mock.call('port', '-list', '-sp')]
        fake_cli.assert_has_calls(expected)

        # Test for manaul registration
        self.configuration.initiator_auto_registration = False

        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
                    ('storagegroup', '-list'),
                    self.testData.CONNECTHOST_CMD('fakehost', 'fakehost'),
                    self.testData.GETFCPORT_CMD(),
                    ('port', '-list', '-gname', 'fakehost')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_NO_MAP('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   self.testData.STORAGE_GROUP_HAS_MAP('fakehost'),
                   ('', 0),
                   self.testData.FC_PORTS,
                   self.testData.FAKEHOST_PORTS]
        fake_cli = self.driverSetup(commands, results)
        data = self.driver.initialize_connection(
            self.testData.test_volume_rw,
            self.testData.connector)

        self.assertEqual(data['data']['access_mode'], 'rw')

        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1')),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-addhlu', '-hlu', 1, '-alu', 1,
                              '-gname', 'fakehost'),
                    mock.call('port', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('port', '-list', '-sp')]
        fake_cli.assert_has_calls(expected)

    @mock.patch(
        "cinder.zonemanager.fc_san_lookup_service.FCSanLookupService." +
        "get_device_mapping_from_network",
        mock.Mock(return_value=EMCVNXCLIDriverTestData.device_map))
    @mock.patch("random.shuffle", mock.Mock())
    def test_initialize_connection_fc_auto_zoning(self):
        # Test for auto zoning
        self.configuration.zoning_mode = 'fabric'
        self.configuration.initiator_auto_registration = False
        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
                    ('storagegroup', '-list'),
                    self.testData.CONNECTHOST_CMD('fakehost', 'fakehost'),
                    self.testData.GETFCPORT_CMD(),
                    ('port', '-list', '-gname', 'fakehost')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_NO_MAP('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   self.testData.STORAGE_GROUP_HAS_MAP('fakehost'),
                   ('', 0),
                   self.testData.FC_PORTS,
                   self.testData.FAKEHOST_PORTS]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.zonemanager_lookup_service = FCSanLookupService(
            configuration=self.configuration)

        conn_info = self.driver.initialize_connection(
            self.testData.test_volume,
            self.testData.connector)

        self.assertEqual(conn_info['data']['initiator_target_map'],
                         EMCVNXCLIDriverTestData.i_t_map)
        self.assertEqual(conn_info['data']['target_wwn'],
                         ['1122334455667777'])
        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call('lun', '-list', '-name', 'vol1',
                              '-state', '-status', '-opDetails',
                              '-userCap', '-owner', '-attachedSnapshot'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-addhlu', '-hlu', 1, '-alu', 1,
                              '-gname', 'fakehost'),
                    mock.call('port', '-list', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost'),
                    mock.call('port', '-list', '-sp')]
        fake_cli.assert_has_calls(expected)

    @mock.patch(
        "cinder.zonemanager.fc_san_lookup_service.FCSanLookupService." +
        "get_device_mapping_from_network",
        mock.Mock(return_value=EMCVNXCLIDriverTestData.device_map))
    def test_terminate_connection_remove_zone_false(self):
        self.driver = EMCCLIFCDriver(configuration=self.configuration)
        cli_helper = self.driver.cli._client
        data = {'storage_group_name': "fakehost",
                'storage_group_uid': "2F:D4:00:00:00:00:00:"
                "00:00:00:FF:E5:3A:03:FD:6D",
                'lunmap': {1: 16, 2: 88, 3: 47}}
        cli_helper.get_storage_group = mock.Mock(
            return_value=data)
        lun_info = {'lun_name': "unit_test_lun",
                    'lun_id': 1,
                    'pool': "unit_test_pool",
                    'attached_snapshot': "N/A",
                    'owner': "A",
                    'total_capacity_gb': 1.0,
                    'state': "Ready"}
        cli_helper.get_lun_by_name = mock.Mock(return_value=lun_info)
        cli_helper.remove_hlu_from_storagegroup = mock.Mock()
        self.driver.cli.zonemanager_lookup_service = FCSanLookupService(
            configuration=self.configuration)
        connection_info = self.driver.terminate_connection(
            self.testData.test_volume,
            self.testData.connector)
        self.assertFalse('initiator_target_map' in connection_info['data'],
                         'initiator_target_map should not appear.')

        cli_helper.remove_hlu_from_storagegroup.assert_called_once_with(
            16, self.testData.connector["host"])

    @mock.patch(
        "cinder.zonemanager.fc_san_lookup_service.FCSanLookupService." +
        "get_device_mapping_from_network",
        mock.Mock(return_value=EMCVNXCLIDriverTestData.device_map))
    def test_terminate_connection_remove_zone_true(self):
        self.driver = EMCCLIFCDriver(configuration=self.configuration)
        cli_helper = self.driver.cli._client
        data = {'storage_group_name': "fakehost",
                'storage_group_uid': "2F:D4:00:00:00:00:00:"
                "00:00:00:FF:E5:3A:03:FD:6D",
                'lunmap': {}}
        cli_helper.get_storage_group = mock.Mock(
            return_value=data)
        lun_info = {'lun_name': "unit_test_lun",
                    'lun_id': 1,
                    'pool': "unit_test_pool",
                    'attached_snapshot': "N/A",
                    'owner': "A",
                    'total_capacity_gb': 1.0,
                    'state': "Ready"}
        cli_helper.get_lun_by_name = mock.Mock(return_value=lun_info)
        cli_helper.remove_hlu_from_storagegroup = mock.Mock()
        self.driver.cli.zonemanager_lookup_service = FCSanLookupService(
            configuration=self.configuration)
        connection_info = self.driver.terminate_connection(
            self.testData.test_volume,
            self.testData.connector)
        self.assertTrue('initiator_target_map' in connection_info['data'],
                        'initiator_target_map should be populated.')
        self.assertEqual(connection_info['data']['initiator_target_map'],
                         EMCVNXCLIDriverTestData.i_t_map)

    def test_get_volume_stats(self):
        #expect_result = [POOL_PROPERTY]
        self.driverSetup()
        stats = self.driver.get_volume_stats(True)
        self.assertTrue(stats['driver_version'] is not None,
                        "dirver_version is not returned")
        self.assertTrue(
            stats['free_capacity_gb'] == 1000.6,
            "free_capacity_gb is not correct")
        self.assertTrue(
            stats['reserved_percentage'] == 0,
            "reserved_percentage is not correct")
        self.assertTrue(
            stats['storage_protocol'] == 'FC',
            "storage_protocol is not correct")
        self.assertTrue(
            stats['total_capacity_gb'] == 10000.5,
            "total_capacity_gb is not correct")
        self.assertTrue(
            stats['vendor_name'] == "EMC",
            "vender name is not correct")
        self.assertTrue(
            stats['volume_backend_name'] == "namedbackend",
            "volume backend name is not correct")
        self.assertTrue(stats['location_info'] == "unit_test_pool|fakeSerial")
        self.assertTrue(
            stats['driver_version'] == "04.00.00",
            "driver version is incorrect.")


class EMCVNXCLIToggleSPTestData():
    def FAKE_COMMAND_PREFIX(self, sp_address):
        return ('/opt/Navisphere/bin/naviseccli', '-address', sp_address,
                '-user', 'sysadmin', '-password', 'sysadmin',
                '-scope', 'global')


class EMCVNXCLIToggleSPTestCase(test.TestCase):
    def setUp(self):
        super(EMCVNXCLIToggleSPTestCase, self).setUp()
        self.stubs.Set(os.path, 'exists', mock.Mock(return_value=1))
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.naviseccli_path = '/opt/Navisphere/bin/naviseccli'
        self.configuration.san_ip = '10.10.10.10'
        self.configuration.san_secondary_ip = "10.10.10.11"
        self.configuration.storage_vnx_pool_name = 'unit_test_pool'
        self.configuration.san_login = 'sysadmin'
        self.configuration.san_password = 'sysadmin'
        self.configuration.default_timeout = 1
        self.configuration.max_luns_per_storage_group = 10
        self.configuration.destroy_empty_storage_group = 10
        self.configuration.storage_vnx_authentication_type = "global"
        self.configuration.iscsi_initiators = '{"fakehost": ["10.0.0.2"]}'
        self.configuration.zoning_mode = None
        self.configuration.storage_vnx_security_file_dir = ""
        self.cli_client = emc_vnx_cli.CommandLineHelper(
            configuration=self.configuration)
        self.test_data = EMCVNXCLIToggleSPTestData()

    def tearDown(self):
        super(EMCVNXCLIToggleSPTestCase, self).tearDown()

    def test_no_sp_toggle(self):
        self.cli_client.active_storage_ip = '10.10.10.10'
        FAKE_SUCCESS_RETURN = ('success', 0)
        FAKE_COMMAND = ('list', 'pool')
        SIDE_EFFECTS = [FAKE_SUCCESS_RETURN, FAKE_SUCCESS_RETURN]

        with mock.patch('cinder.utils.execute') as mock_utils:
            mock_utils.side_effect = SIDE_EFFECTS
            self.cli_client.command_execute(*FAKE_COMMAND)
            self.assertEqual(self.cli_client.active_storage_ip, "10.10.10.10")
            expected = [mock.call(*('ping', '-c', 1, '10.10.10.10'),
                                  check_exit_code=True),
                        mock.call(
                            *(self.test_data.FAKE_COMMAND_PREFIX('10.10.10.10')
                              + FAKE_COMMAND),
                            check_exit_code=True)]
            mock_utils.assert_has_calls(expected)

    def test_toggle_sp_with_server_unavailabe(self):
        self.cli_client.active_storage_ip = '10.10.10.10'
        FAKE_ERROR_MSG = """\
Error occurred during HTTP request/response from the target: '10.244.213.142'.
Message : HTTP/1.1 503 Service Unavailable"""
        FAKE_SUCCESS_RETURN = ('success', 0)
        FAKE_COMMAND = ('list', 'pool')
        SIDE_EFFECTS = [FAKE_SUCCESS_RETURN,
                        processutils.ProcessExecutionError(
                            exit_code=255, stdout=FAKE_ERROR_MSG),
                        FAKE_SUCCESS_RETURN]

        with mock.patch('cinder.utils.execute') as mock_utils:
            mock_utils.side_effect = SIDE_EFFECTS
            self.cli_client.command_execute(*FAKE_COMMAND)
            self.assertEqual(self.cli_client.active_storage_ip, "10.10.10.11")
            expected = [
                mock.call(
                    *(self.test_data.FAKE_COMMAND_PREFIX('10.10.10.10')
                        + FAKE_COMMAND),
                    check_exit_code=True),
                mock.call(
                    *(self.test_data.FAKE_COMMAND_PREFIX('10.10.10.11')
                        + FAKE_COMMAND),
                    check_exit_code=True)]
            mock_utils.assert_has_calls(expected)

    def test_toggle_sp_with_end_of_data(self):
        self.cli_client.active_storage_ip = '10.10.10.10'
        FAKE_ERROR_MSG = """\
Error occurred during HTTP request/response from the target: '10.244.213.142'.
Message : End of data stream"""
        FAKE_SUCCESS_RETURN = ('success', 0)
        FAKE_COMMAND = ('list', 'pool')
        SIDE_EFFECTS = [FAKE_SUCCESS_RETURN,
                        processutils.ProcessExecutionError(
                            exit_code=255, stdout=FAKE_ERROR_MSG),
                        FAKE_SUCCESS_RETURN]

        with mock.patch('cinder.utils.execute') as mock_utils:
            mock_utils.side_effect = SIDE_EFFECTS
            self.cli_client.command_execute(*FAKE_COMMAND)
            self.assertEqual(self.cli_client.active_storage_ip, "10.10.10.11")
            expected = [
                mock.call(
                    *(self.test_data.FAKE_COMMAND_PREFIX('10.10.10.10')
                        + FAKE_COMMAND),
                    check_exit_code=True),
                mock.call(
                    *(self.test_data.FAKE_COMMAND_PREFIX('10.10.10.11')
                        + FAKE_COMMAND),
                    check_exit_code=True)]
            mock_utils.assert_has_calls(expected)

    def test_toggle_sp_with_connection_refused(self):
        self.cli_client.active_storage_ip = '10.10.10.10'
        FAKE_ERROR_MSG = """\
A network error occurred while trying to connect: '10.244.213.142'.
Message : Error occurred because connection refused. \
Unable to establish a secure connection to the Management Server.
"""
        FAKE_SUCCESS_RETURN = ('success', 0)
        FAKE_COMMAND = ('list', 'pool')
        SIDE_EFFECTS = [FAKE_SUCCESS_RETURN,
                        processutils.ProcessExecutionError(
                            exit_code=255, stdout=FAKE_ERROR_MSG),
                        FAKE_SUCCESS_RETURN]

        with mock.patch('cinder.utils.execute') as mock_utils:
            mock_utils.side_effect = SIDE_EFFECTS
            self.cli_client.command_execute(*FAKE_COMMAND)
            self.assertEqual(self.cli_client.active_storage_ip, "10.10.10.11")
            expected = [
                mock.call(
                    *(self.test_data.FAKE_COMMAND_PREFIX('10.10.10.10')
                        + FAKE_COMMAND),
                    check_exit_code=True),
                mock.call(
                    *(self.test_data.FAKE_COMMAND_PREFIX('10.10.10.11')
                        + FAKE_COMMAND),
                    check_exit_code=True)]
            mock_utils.assert_has_calls(expected)
