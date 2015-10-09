# Copyright (c) 2012 - 2015 EMC Corporation, Inc.
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
from oslo_concurrency import processutils
import six

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_consistencygroup
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.emc import emc_cli_fc
from cinder.volume.drivers.emc import emc_cli_iscsi
from cinder.volume.drivers.emc import emc_vnx_cli
from cinder.zonemanager import fc_san_lookup_service as fc_service

from mock import patch


SUCCEED = ("", 0)
FAKE_ERROR_RETURN = ("FAKE ERROR", 255)
VERSION = emc_vnx_cli.EMCVnxCliBase.VERSION


class EMCVNXCLIDriverTestData(object):

    test_volume = {
        'status': 'creating',
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'provider_location': 'system^FNM11111|type^lun|id^1|version^05.03.00',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'consistencygroup_id': None
    }

    test_legacy_volume = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'provider_location': 'system^FNM11111|type^lun|id^1',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'consistencygroup_id': None
    }

    test_volume_clone_cg = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'consistencygroup_id': None,
        'provider_location': 'system^FNM11111|type^lun|id^1',
    }

    test_volume_cg = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'consistencygroup_id': 'cg_id'
    }

    test_volume_rw = {
        'name': 'vol1',
        'size': 1,
        'volume_name': 'vol1',
        'id': '1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'vol1',
        'display_description': 'test volume',
        'volume_type_id': None,
        'consistencygroup_id': None,
        'provider_location': 'system^FNM11111|type^lun|id^1|version^05.03.00',
    }

    test_volume2 = {
        'name': 'vol2',
        'size': 1,
        'volume_name': 'vol2',
        'id': '1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'vol2',
        'consistencygroup_id': None,
        'display_description': 'test volume',
        'volume_type_id': None,
        'provider_location': 'system^FNM11111|type^lun|id^1|version^05.03.00',
        'volume_metadata': [{'key': 'lun_type', 'value': 'lun'}]}

    volume_in_cg = {
        'name': 'vol2',
        'size': 1,
        'volume_name': 'vol2',
        'id': '1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'vol1_in_cg',
        'provider_location': 'system^FNM11111|type^lun|id^1',
        'consistencygroup_id': 'consistencygroup_id',
        'display_description': 'test volume',
        'volume_type_id': None}

    volume2_in_cg = {
        'name': 'vol2',
        'size': 1,
        'volume_name': 'vol2',
        'id': '3',
        'provider_auth': None,
        'project_id': 'project',
        'display_name': 'vol2_in_cg',
        'provider_location': 'system^FNM11111|type^lun|id^3',
        'consistencygroup_id': 'consistencygroup_id',
        'display_description': 'test volume',
        'volume_type_id': None}

    test_volume_with_type = {
        'name': 'vol_with_type',
        'size': 1,
        'volume_name': 'vol_with_type',
        'id': '1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'thin_vol',
        'consistencygroup_id': None,
        'display_description': 'vol with type',
        'volume_type_id': 'abc1-2320-9013-8813-8941-1374-8112-1231',
        'provider_location': 'system^FNM11111|type^lun|id^1'}

    test_failed_volume = {
        'name': 'failed_vol1',
        'size': 1,
        'volume_name': 'failed_vol1',
        'id': '4',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'failed_vol',
        'consistencygroup_id': None,
        'display_description': 'test failed volume',
        'volume_type_id': None}

    test_volume1_in_sg = {
        'name': 'vol1_in_sg',
        'size': 1,
        'volume_name': 'vol1_in_sg',
        'id': '4',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'failed_vol',
        'display_description': 'Volume 1 in SG',
        'volume_type_id': None,
        'provider_location': 'system^fakesn|type^lun|id^4|version^05.03.00'}

    test_volume2_in_sg = {
        'name': 'vol2_in_sg',
        'size': 1,
        'volume_name': 'vol2_in_sg',
        'id': '5',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'failed_vol',
        'display_description': 'Volume 2 in SG',
        'volume_type_id': None,
        'provider_location': 'system^fakesn|type^lun|id^3|version^05.03.00'}

    test_snapshot = {
        'name': 'snapshot1',
        'size': 1,
        'id': '4444',
        'volume_name': 'vol1',
        'volume': test_volume,
        'volume_size': 1,
        'consistencygroup_id': None,
        'cgsnapshot_id': None,
        'project_id': 'project'}
    test_failed_snapshot = {
        'name': 'failed_snapshot',
        'size': 1,
        'id': '5555',
        'volume_name': 'vol-vol1',
        'volume': test_volume,
        'volume_size': 1,
        'project_id': 'project'}
    test_clone = {
        'name': 'clone1',
        'size': 1,
        'id': '2',
        'volume_name': 'vol1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'clone1',
        'consistencygroup_id': None,
        'display_description': 'volume created from snapshot',
        'volume_type_id': '19fdd0dd-03b3-4d7c-b541-f4df46f308c8',
        'provider_location': 'system^fakesn|type^lun|id^2|version^05.03.00'}
    test_clone_cg = {
        'name': 'clone1',
        'size': 1,
        'id': '2',
        'volume_name': 'vol1',
        'provider_auth': None,
        'host': "host@backendsec#unit_test_pool",
        'project_id': 'project',
        'display_name': 'clone1',
        'consistencygroup_id': 'consistencygroup_id',
        'display_description': 'volume created from snapshot',
        'volume_type_id': None,
        'provider_location': 'system^fakesn|type^lun|id^2|version^05.03.00'}
    connector = {
        'ip': '10.0.0.2',
        'initiator': 'iqn.1993-08.org.debian:01:222',
        'wwpns': ["1234567890123456", "1234567890543216"],
        'wwnns': ["2234567890123456", "2234567890543216"],
        'host': 'fakehost'}
    test_volume3 = {
        'migration_status': None, 'availability_zone': 'nova',
        'id': '1181d1b2-cea3-4f55-8fa8-3360d026ce24',
        'name': 'vol3',
        'size': 2,
        'status': 'available',
        'volume_type_id':
        '19fdd0dd-03b3-4d7c-b541-f4df46f308c8',
        'deleted': False,
        'host': "host@backendsec#unit_test_pool",
        'source_volid': None, 'provider_auth': None,
        'display_name': 'vol-test02',
        'attach_status': 'detached',
        'volume_type': [],
        'volume_attachment': [],
        'provider_location':
        'system^FNM11111|type^lun|id^1|version^05.03.00',
        '_name_id': None, 'volume_metadata': []}

    test_new_type = {'name': 'voltype0', 'qos_specs_id': None,
                     'deleted': False,
                     'extra_specs': {'storagetype:provisioning': 'thin'},
                     'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

    test_diff = {'encryption': {}, 'qos_specs': {},
                 'extra_specs':
                 {'storagetype:provisioning': ('thick', 'thin')}}

    test_host = {'host': 'ubuntu-server12@pool_backend_1#POOL_SAS1',
                 'capabilities':
                 {'pool_name': 'POOL_SAS1',
                  'location_info': 'POOL_SAS1|FNM00124500890',
                  'volume_backend_name': 'pool_backend_1',
                  'storage_protocol': 'iSCSI'}}

    test_volume4 = {'migration_status': None, 'availability_zone': 'nova',
                    'id': '1181d1b2-cea3-4f55-8fa8-3360d026ce24',
                    'name': 'vol4',
                    'size': 2,
                    'status': 'available',
                    'volume_type_id':
                    '19fdd0dd-03b3-4d7c-b541-f4df46f308c8',
                    'deleted': False, 'provider_location':
                    'system^FNM11111|type^lun|id^4',
                    'host': 'ubuntu-server12@array_backend_1',
                    'source_volid': None, 'provider_auth': None,
                    'display_name': 'vol-test02',
                    'volume_attachment': [],
                    'attach_status': 'detached',
                    'volume_type': [],
                    '_name_id': None, 'volume_metadata': []}

    test_volume5 = {'migration_status': None, 'availability_zone': 'nova',
                    'id': '1181d1b2-cea3-4f55-8fa8-3360d026ce25',
                    'name_id': '1181d1b2-cea3-4f55-8fa8-3360d026ce25',
                    'name': 'vol5',
                    'size': 1,
                    'status': 'available',
                    'volume_type_id':
                    '19fdd0dd-03b3-4d7c-b541-f4df46f308c8',
                    'deleted': False, 'provider_location':
                    'system^FNM11111|type^lun|id^5|version^05.02.00',
                    'host': 'ubuntu-server12@array_backend_1#unit_test_pool',
                    'source_volid': None, 'provider_auth': None,
                    'display_name': 'vol-test05',
                    'volume_attachment': [],
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

    test_cg = {'id': 'consistencygroup_id',
               'name': 'group_name',
               'status': 'deleting'}

    test_cg_with_type = {'id': 'consistencygroup_id',
                         'name': 'group_name',
                         'status': 'creating',
                         'volume_type_id':
                         'abc1-2320-9013-8813-8941-1374-8112-1231,'
                         '19fdd0dd-03b3-4d7c-b541-f4df46f308c8,'}

    test_cgsnapshot = {
        'consistencygroup_id': 'consistencygroup_id',
        'id': 'cgsnapshot_id',
        'status': 'available'}

    test_member_cgsnapshot = {
        'name': 'snapshot1',
        'size': 1,
        'id': 'cgsnapshot_id',
        'volume': test_volume,
        'volume_name': 'vol1',
        'volume_size': 1,
        'consistencygroup_id': 'consistencygroup_id',
        'cgsnapshot_id': 'cgsnapshot_id',
        'project_id': 'project'
    }

    test_lun_id = 1
    test_existing_ref = {'source-id': test_lun_id}
    test_existing_ref_source_name = {'source-name': 'vol1'}
    test_pool_name = 'unit_test_pool'
    device_map = {
        '1122334455667788': {
            'initiator_port_wwn_list': ['123456789012345', '123456789054321'],
            'target_port_wwn_list': ['1122334455667777']}}
    i_t_map = {'123456789012345': ['1122334455667777'],
               '123456789054321': ['1122334455667777']}

    POOL_PROPERTY_CMD = ('storagepool', '-list', '-name', 'unit_test_pool',
                         '-userCap', '-availableCap',
                         '-state', '-prcntFullThreshold')

    POOL_PROPERTY_W_FASTCACHE_CMD = ('storagepool', '-list', '-name',
                                     'unit_test_pool', '-availableCap',
                                     '-userCap', '-state',
                                     '-subscribedCap',
                                     '-prcntFullThreshold',
                                     '-fastcache')

    def POOL_GET_ALL_CMD(self, withfastcache=False):
        if withfastcache:
            return ('storagepool', '-list', '-availableCap',
                    '-userCap', '-state', '-subscribedCap',
                    '-prcntFullThreshold',
                    '-fastcache')
        else:
            return ('storagepool', '-list', '-availableCap',
                    '-userCap', '-state', '-subscribedCap',
                    '-prcntFullThreshold')

    def POOL_GET_ALL_RESULT(self, withfastcache=False):
        if withfastcache:
            return ("Pool Name:  unit_test_pool\n"
                    "Pool ID:  0\n"
                    "Percent Full Threshold:  70\n"
                    "User Capacity (Blocks):  6881061888\n"
                    "User Capacity (GBs):  3281.146\n"
                    "Available Capacity (Blocks):  6512292864\n"
                    "Available Capacity (GBs):  3105.303\n"
                    "Total Subscribed Capacity (GBs):  536.140\n"
                    "FAST Cache:  Enabled\n"
                    "State: Ready\n"
                    "\n"
                    "Pool Name:  unit_test_pool2\n"
                    "Pool ID:  1\n"
                    "Percent Full Threshold:  70\n"
                    "User Capacity (Blocks):  8598306816\n"
                    "User Capacity (GBs):  4099.992\n"
                    "Available Capacity (Blocks):  8356663296\n"
                    "Available Capacity (GBs):  3984.768\n"
                    "Total Subscribed Capacity (GBs):  636.240\n"
                    "FAST Cache:  Disabled\n"
                    "State: Ready\n", 0)
        else:
            return ("Pool Name:  unit_test_pool\n"
                    "Pool ID:  0\n"
                    "Percent Full Threshold:  70\n"
                    "User Capacity (Blocks):  6881061888\n"
                    "User Capacity (GBs):  3281.146\n"
                    "Available Capacity (Blocks):  6512292864\n"
                    "Available Capacity (GBs):  3105.303\n"
                    "Total Subscribed Capacity (GBs):  536.140\n"
                    "State: Ready\n"
                    "\n"
                    "Pool Name:  unit_test_pool2\n"
                    "Pool ID:  1\n"
                    "Percent Full Threshold:  70\n"
                    "User Capacity (Blocks):  8598306816\n"
                    "User Capacity (GBs):  4099.992\n"
                    "Available Capacity (Blocks):  8356663296\n"
                    "Available Capacity (GBs):  3984.768\n"
                    "Total Subscribed Capacity (GBs):  636.240\n"
                    "State: Ready\n", 0)

    def POOL_GET_STATE_RESULT(self, pools):
        output = []
        for i, po in enumerate(pools):
            if i != 0:
                output.append("\n")
            output.append("Pool Name:  %s" % po['pool_name'])
            output.append("Pool ID: %s" % i)
            output.append("State: %s" % po['state'])
        return ("\n".join(output), 0)

    def POOL_GET_ALL_STATES_TEST(self, states=['Ready']):
        output = ""
        for i, stat in enumerate(states):
            out = ("Pool Name:  Pool_" + str(i) + "\n"
                   "Pool ID:  " + str(i) + "\n"
                   "Percent Full Threshold:  70\n"
                   "User Capacity (Blocks):  8598306816\n"
                   "User Capacity (GBs):  4099.992\n"
                   "Available Capacity (Blocks):  8356663296\n"
                   "Available Capacity (GBs):  3984.768\n"
                   "FAST Cache:  Enabled\n"
                   "State: " + stat + "\n\n")
            output += out
        return (output, 0)

    NDU_LIST_CMD = ('ndu', '-list')
    NDU_LIST_RESULT = ("Name of the software package:   -Compression " +
                       "Name of the software package:   -Deduplication " +
                       "Name of the software package:   -FAST " +
                       "Name of the software package:   -FASTCache " +
                       "Name of the software package:   -ThinProvisioning "
                       "Name of the software package:   -VNXSnapshots",
                       0)

    NDU_LIST_RESULT_WO_LICENSE = (
        "Name of the software package:   -Unisphere ",
        0)
    MIGRATE_PROPERTY_MIGRATING = """\
        Source LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d
        Source LU ID:  63950
        Dest LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d_dest
        Dest LU ID:  136
        Migration Rate:  high
        Current State:  MIGRATING
        Percent Complete:  50
        Time Remaining:  0 second(s)
        """
    MIGRATE_PROPERTY_STOPPED = """\
        Source LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d
        Source LU ID:  63950
        Dest LU Name:  volume-f6247ae1-8e1c-4927-aa7e-7f8e272e5c3d_dest
        Dest LU ID:  136
        Migration Rate:  high
        Current State:  STOPPED - Destination full
        Percent Complete:  60
        Time Remaining:  0 second(s)
        """

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

    def SNAP_MODIFY_CMD(self, name, rw):
        return ('snap', '-modify', '-id', name, '-allowReadWrite', rw,
                '-allowAutoDelete', 'yes')

    def SNAP_LIST_CMD(self, res_id=1):
        cmd = ('snap', '-list', '-res', res_id)
        return cmd

    def LUN_DELETE_CMD(self, name):
        return ('lun', '-destroy', '-name', name, '-forceDetach', '-o')

    def LUN_EXTEND_CMD(self, name, newsize):
        return ('lun', '-expand', '-name', name, '-capacity', newsize,
                '-sq', 'gb', '-o', '-ignoreThresholds')

    def LUN_PROPERTY_POOL_CMD(self, lunname):
        return ('lun', '-list', '-name', lunname, '-poolName')

    def LUN_PROPERTY_ALL_CMD(self, lunname):
        return ('lun', '-list', '-name', lunname,
                '-state', '-status', '-opDetails', '-userCap', '-owner',
                '-attachedSnapshot')

    def MIGRATION_CMD(self, src_id=1, dest_id=1):
        cmd = ("migrate", "-start", "-source", src_id, "-dest", dest_id,
               "-rate", "high", "-o")
        return cmd

    def MIGRATION_VERIFY_CMD(self, src_id):
        return ("migrate", "-list", "-source", src_id)

    def MIGRATION_CANCEL_CMD(self, src_id):
        return ("migrate", "-cancel", "-source", src_id, '-o')

    def GETPORT_CMD(self):
        return ("connection", "-getport", "-address", "-vlanid")

    def PINGNODE_CMD(self, sp, portid, vportid, ip):
        return ("connection", "-pingnode", "-sp", sp, '-portid', portid,
                "-vportid", vportid, "-address", ip, '-count', '1')

    def GETFCPORT_CMD(self):
        return ('port', '-list', '-sp')

    def CONNECTHOST_CMD(self, hostname, gname):
        return ('storagegroup', '-connecthost',
                '-host', hostname, '-gname', gname, '-o')

    def ENABLE_COMPRESSION_CMD(self, lun_id):
        return ('compression', '-on',
                '-l', lun_id, '-ignoreThresholds', '-o')

    def STORAGEGROUP_LIST_CMD(self, gname=None):
        if gname:
            return ('storagegroup', '-list',
                    '-gname', gname, '-host', '-iscsiAttributes')
        else:
            return ('storagegroup', '-list')

    def STORAGEGROUP_REMOVEHLU_CMD(self, gname, hlu):
        return ('storagegroup', '-removehlu',
                '-hlu', hlu, '-gname', gname, '-o')

    def SNAP_COPY_CMD(self, src_snap, snap_name):
        return ('snap', '-copy', '-id', src_snap, '-name', snap_name,
                '-ignoreMigrationCheck', '-ignoreDeduplicationCheck')

    def ALLOW_READWRITE_ON_SNAP_CMD(self, snap_name):
        return ('snap', '-modify', '-id', snap_name,
                '-allowReadWrite', 'yes', '-allowAutoDelete', 'yes')

    def MODIFY_TIERING_CMD(self, lun_name, tiering):
        cmd = ['lun', '-modify', '-name', lun_name, '-o']
        cmd.extend(self.tiering_values[tiering])
        return tuple(cmd)

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

    def LUN_CREATION_CMD(self, name, size, pool, provisioning, tiering,
                         ignore_thresholds=False, poll=True):
        initial = ['lun', '-create',
                   '-capacity', size,
                   '-sq', 'gb',
                   '-poolName', pool,
                   '-name', name]
        if not poll:
            initial = ['-np'] + initial
        if provisioning:
            initial.extend(self.provisioning_values[provisioning])
        else:
            initial.extend(self.provisioning_values['thick'])
        if tiering:
            initial.extend(self.tiering_values[tiering])
        if ignore_thresholds:
            initial.append('-ignoreThresholds')
        return tuple(initial)

    def CHECK_FASTCACHE_CMD(self, storage_pool):
        return ('storagepool', '-list', '-name',
                storage_pool, '-fastcache')

    def CREATE_CONSISTENCYGROUP_CMD(self, cg_name, members=None):
        create_cmd = ('snap', '-group', '-create',
                      '-name', cg_name, '-allowSnapAutoDelete', 'no')

        if not members:
            return create_cmd
        else:
            return create_cmd + ('-res', ','.join(map(six.text_type,
                                                      members)))

    def DELETE_CONSISTENCYGROUP_CMD(self, cg_name):
        return ('-np', 'snap', '-group', '-destroy',
                '-id', cg_name)

    def ADD_LUN_TO_CG_CMD(self, cg_name, lun_id):
        return ('snap', '-group',
                '-addmember', '-id', cg_name, '-res', lun_id)

    def CREATE_CG_SNAPSHOT(self, cg_name, snap_name):
        return ('-np', 'snap', '-create', '-res', cg_name,
                '-resType', 'CG', '-name', snap_name, '-allowReadWrite',
                'yes', '-allowAutoDelete', 'no')

    def DELETE_CG_SNAPSHOT(self, snap_name):
        return ('-np', 'snap', '-destroy', '-id', snap_name, '-o')

    def GET_CG_BY_NAME_CMD(self, cg_name):
        return ('snap', '-group', '-list', '-id', cg_name)

    def REMOVE_LUNS_FROM_CG_CMD(self, cg_name, remove_ids):
        return ('snap', '-group', '-rmmember', '-id', cg_name, '-res',
                ','.join(remove_ids))

    def REPLACE_LUNS_IN_CG_CMD(self, cg_name, new_ids):
        return ('snap', '-group', '-replmember', '-id', cg_name, '-res',
                ','.join(new_ids))

    def CONSISTENCY_GROUP_VOLUMES(self):
        volumes = []
        volumes.append(self.test_volume)
        volumes.append(self.test_volume)
        return volumes

    def SNAPS_IN_SNAP_GROUP(self):
        snaps = []
        snaps.append(self.test_snapshot)
        snaps.append(self.test_snapshot)
        return snaps

    def VOLUMES_NOT_IN_CG(self):
        add_volumes = []
        add_volumes.append(self.test_volume4)
        add_volumes.append(self.test_volume5)
        return add_volumes

    def VOLUMES_IN_CG(self):
        remove_volumes = []
        remove_volumes.append(self.volume_in_cg)
        remove_volumes.append(self.volume2_in_cg)
        return remove_volumes

    def CG_PROPERTY(self, cg_name):
        return """
Name:  %(cg_name)s
Description:
Allow auto delete:  No
Member LUN ID(s):  1, 3
State:  Ready
""" % {'cg_name': cg_name}, 0

    def CG_REPL_ERROR(self):
        return """
        The specified LUN is already a member
        of another consistency group. (0x716d8045)
        """, 71

    def LUN_PREP_ERROR(self):
        return ("The operation cannot be performed because "
                "the LUN is 'Preparing'.  Wait for the LUN's "
                "Current Operation to complete 'Preparing' "
                "and retry the operation. (0x712d8e0e)", 14)

    POOL_PROPERTY = (
        "Pool Name:  unit_test_pool\n"
        "Pool ID:  1\n"
        "Percent Full Threshold:  70\n"
        "User Capacity (Blocks):  6881061888\n"
        "User Capacity (GBs):  3281.146\n"
        "Available Capacity (Blocks):  6832207872\n"
        "Available Capacity (GBs):  3257.851\n"
        "State: Ready\n"
        "\n", 0)

    POOL_PROPERTY_W_FASTCACHE = (
        "Pool Name:  unit_test_pool\n"
        "Pool ID:  1\n"
        "Percent Full Threshold:  70\n"
        "User Capacity (Blocks):  6881061888\n"
        "User Capacity (GBs):  3281.146\n"
        "Available Capacity (Blocks):  6832207872\n"
        "Available Capacity (GBs):  3257.851\n"
        "Total Subscribed Capacity (GBs):  636.240\n"
        "FAST Cache:  Enabled\n"
        "State: Ready\n\n", 0)

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
                 "iSCSI Alias:  0215.a5\n" +
                 "SP:  A\n" +
                 "Port ID:  0\n" +
                 "Port WWN:  iqn.1992-04.com.emc:cx.fnm00124000215.a0\n" +
                 "iSCSI Alias:  0215.a0\n\n" +
                 "Virtual Port ID:  0\n" +
                 "VLAN ID:  Disabled\n" +
                 "IP Address:  10.244.214.119\n\n" +
                 "SP:  B\n" +
                 "Port ID:  2\n" +
                 "Port WWN:  iqn.1992-04.com.emc:cx.fnm00124000215.b2\n" +
                 "iSCSI Alias:  0215.b2\n\n" +
                 "Virtual Port ID:  0\n" +
                 "VLAN ID:  Disabled\n" +
                 "IP Address:  10.244.214.120\n\n", 0)

    WHITE_LIST_PORTS = ("""SP:  A
Port ID:  0
Port WWN:  iqn.1992-04.com.emc:cx.fnmxxx.a0
iSCSI Alias:  0235.a7

Virtual Port ID:  0
VLAN ID:  Disabled
IP Address:  192.168.3.52

SP:  A
Port ID:  9
Port WWN:  iqn.1992-04.com.emc:cx.fnmxxx.a9
iSCSI Alias:  0235.a9

SP:  A
Port ID:  4
Port WWN:  iqn.1992-04.com.emc:cx.fnmxxx.a4
iSCSI Alias:  0235.a4

SP:  B
Port ID:  2
Port WWN:  iqn.1992-04.com.emc:cx.fnmxxx.b2
iSCSI Alias:  0235.b6

Virtual Port ID:  0
VLAN ID:  Disabled
IP Address:  192.168.4.53
""", 0)

    iscsi_connection_info = {
        'data': {'target_discovered': True,
                 'target_iqn':
                 'iqn.1992-04.com.emc:cx.fnm00124000215.a4',
                 'target_lun': 2,
                 'target_portal': '10.244.214.118:3260',
                 'target_iqns': ['iqn.1992-04.com.emc:cx.fnm00124000215.a4'],
                 'target_luns': [2],
                 'target_portals': ['10.244.214.118:3260'],
                 'volume_id': '1'},
        'driver_volume_type': 'iscsi'}

    iscsi_connection_info_mp = {
        'data': {'target_discovered': True,
                 'target_iqns': [
                     'iqn.1992-04.com.emc:cx.fnm00124000215.a4',
                     'iqn.1992-04.com.emc:cx.fnm00124000215.a5'],
                 'target_iqn': 'iqn.1992-04.com.emc:cx.fnm00124000215.a4',
                 'target_luns': [2, 2],
                 'target_lun': 2,
                 'target_portals': [
                     '10.244.214.118:3260',
                     '10.244.214.119:3260'],
                 'target_portal': '10.244.214.118:3260',
                 'volume_id': '1'},
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
                "Switch Present:      NO\n" +
                "\n" +
                "SP Name:             SP B\n" +
                "SP Port ID:          2\n" +
                "SP UID:              50:06:01:60:88:60:08:0F:"
                "50:06:01:6A:08:60:08:0F\n" +
                "Link Status:         Up\n" +
                "Port Status:         Online\n" +
                "Switch Present:      YES\n" +
                "Switch UID:          10:00:50:EB:1A:03:3F:59:"
                "20:11:50:EB:1A:03:3F:59\n" +
                "SP Source ID:        69888\n", 0)

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
        "    SP Name:               SP B\n" +
        "    SP Port ID:            2\n" +
        "    HBA Devicename:\n" +
        "    Trusted:               NO\n" +
        "    Logged In:             YES\n" +
        "    Defined:               YES\n" +
        "    Initiator Type:           3\n" +
        "    StorageGroup Name:     fakehost\n\n"
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
        "Switch Present:      NO\n" +
        "\n" +
        "SP Name:             SP B\n" +
        "SP Port ID:          2\n" +
        "SP UID:              50:06:01:60:88:60:01:95:" +
        "50:06:01:6A:08:60:08:0F\n" +
        "Link Status:         Up\n" +
        "Port Status:         Online\n" +
        "Switch Present:      YES\n" +
        "Switch UID:          10:00:00:05:1E:72:EC:A6:" +
        "20:46:00:05:1E:72:EC:A6\n" +
        "SP Source ID:        272896\n", 0)

    def LUN_PROPERTY(self, name, is_thin=False, has_snap=False, size=1,
                     state='Ready', faulted='false', operation='None',
                     lunid=1, pool_name='unit_test_pool'):
        return ("""
               LOGICAL UNIT NUMBER %(lunid)s
               Name:  %(name)s
               UID:  60:06:01:60:09:20:32:00:13:DF:B4:EF:C2:63:E3:11
               Current Owner:  SP A
               Default Owner:  SP A
               Allocation Owner:  SP A
               Attached Snapshot: %(has_snap)s
               User Capacity (Blocks):  2101346304
               User Capacity (GBs):  %(size)d
               Consumed Capacity (Blocks):  2149576704
               Consumed Capacity (GBs):  1024.998
               Pool Name:  %(pool_name)s
               Current State:  %(state)s
               Status:  OK(0x0)
               Is Faulted:  %(faulted)s
               Is Transitioning:  false
               Current Operation:  %(operation)s
               Current Operation State:  N/A
               Current Operation Status:  N/A
               Current Operation Percent Completed:  0
               Is Thin LUN:  %(is_thin)s""" % {
            'lunid': lunid,
            'name': name,
            'has_snap': 'FakeSnap' if has_snap else 'N/A',
            'size': size,
            'pool_name': pool_name,
            'state': state,
            'faulted': faulted,
            'operation': operation,
            'is_thin': 'Yes' if is_thin else 'No'}, 0)

    def STORAGE_GROUP_ISCSI_FC_HBA(self, sgname):

        return ("""\
        Storage Group Name:    %s
        Storage Group UID:     54:46:57:0F:15:A2:E3:11:9A:8D:FF:E5:3A:03:FD:6D
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:222                     SP A         4
        Host name:             fakehost
        SPPort:                A-4v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

          22:34:56:78:90:12:34:56:12:34:56:78:90:12:34:56   SP B         2
        Host name:             fakehost2
        SPPort:                B-2v0
        Initiator IP:          N/A
        TPGT:                  0
        ISID:                  N/A

          22:34:56:78:90:54:32:16:12:34:56:78:90:54:32:16   SP B         2
        Host name:             fakehost2
        SPPort:                B-2v0
        Initiator IP:          N/A
        TPGT:                  0
        ISID:                  N/A

        HLU/ALU Pairs:

          HLU Number     ALU Number
          ----------     ----------
            1               1
        Shareable:             YES""" % sgname, 0)

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
        Host name:             fakehost
        SPPort:                A-4v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

        HLU/ALU Pairs:

          HLU Number     ALU Number
          ----------     ----------
            1               1
        Shareable:             YES""" % sgname, 0)

    def STORAGE_GROUP_HAS_MAP_ISCSI(self, sgname):

        return ("""\
        Storage Group Name:    %s
        Storage Group UID:     54:46:57:0F:15:A2:E3:11:9A:8D:FF:E5:3A:03:FD:6D
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:222                     SP A         2
        Host name:             fakehost
        SPPort:                A-2v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

          iqn.1993-08.org.debian:01:222                     SP A         0
        Host name:             fakehost
        SPPort:                A-0v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

          iqn.1993-08.org.debian:01:222                     SP B         2
        Host name:             fakehost
        SPPort:                B-2v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

        HLU/ALU Pairs:

          HLU Number     ALU Number
          ----------     ----------
            1               1
        Shareable:             YES""" % sgname, 0)

    def STORAGE_GROUP_HAS_MAP_MP(self, sgname):

        return ("""\
        Storage Group Name:    %s
        Storage Group UID:     54:46:57:0F:15:A2:E3:11:9A:8D:FF:E5:3A:03:FD:6D
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:222                     SP A         4
        Host name:             fakehost
        SPPort:                A-4v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

          iqn.1993-08.org.debian:01:222                     SP A         5
        Host name:             fakehost
        SPPort:                A-5v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

        HLU/ALU Pairs:

          HLU Number     ALU Number
          ----------     ----------
            1               1
        Shareable:             YES""" % sgname, 0)

    def STORAGE_GROUP_HAS_MAP_2(self, sgname):

        return ("""\
        Storage Group Name:    %s
        Storage Group UID:     54:46:57:0F:15:A2:E3:11:9A:8D:FF:E5:3A:03:FD:6D
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:222                     SP A         4
        Host name:             fakehost
        SPPort:                A-4v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

        HLU/ALU Pairs:

          HLU Number     ALU Number
          ----------     ----------
            1               1
            2               3
        Shareable:             YES""" % sgname, 0)

    def POOL_FEATURE_INFO_POOL_LUNS_CMD(self):
        cmd = ('storagepool', '-feature', '-info',
               '-maxPoolLUNs', '-numPoolLUNs')
        return cmd

    def POOL_FEATURE_INFO_POOL_LUNS(self, max, total):
        return (('Max. Pool LUNs:  %s\n' % max) +
                ('Total Number of Pool LUNs:  %s\n' % total), 0)

    def STORAGE_GROUPS_HAS_MAP(self, sgname1, sgname2):

        return ("""

        Storage Group Name:    irrelative
        Storage Group UID:     9C:86:4F:30:07:76:E4:11:AC:83:C8:C0:8E:9C:D6:1F
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:5741c6307e60            SP A         6
        Host name:             fakehost
        SPPort:                A-6v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

        Storage Group Name:    %(sgname1)s
        Storage Group UID:     54:46:57:0F:15:A2:E3:11:9A:8D:FF:E5:3A:03:FD:6D
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:222                     SP A         4
        Host name:             fakehost
        SPPort:                A-4v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

        HLU/ALU Pairs:

          HLU Number     ALU Number
          ----------     ----------
            31              3
            41              4
        Shareable:             YES

        Storage Group Name:    %(sgname2)s
        Storage Group UID:     9C:86:4F:30:07:76:E4:11:AC:83:C8:C0:8E:9C:D6:1F
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:5741c6307e60            SP A         6
        Host name:             fakehost
        SPPort:                A-6v0
        Initiator IP:          fakeip
        TPGT:                  3
        ISID:                  fakeid

        HLU/ALU Pairs:

          HLU Number     ALU Number
          ----------     ----------
            32              3
            42              4
        Shareable:             YES""" % {'sgname1': sgname1,
                                         'sgname2': sgname2}, 0)

    def LUN_DELETE_IN_SG_ERROR(self, up_to_date=True):
        if up_to_date:
            return ("Cannot unbind LUN "
                    "because it's contained in a Storage Group",
                    156)
        else:
            return ("SP B: Request failed.  "
                    "Host LUN/LUN mapping still exists.",
                    0)

    def set_path_cmd(self, gname, hba, sp, spport, vport=None, ip=None):
        if vport is None:
            return ('storagegroup', '-setpath', '-gname', gname,
                    '-hbauid', hba,
                    '-sp', sp, '-spport', spport,
                    '-ip', ip, '-host', gname, '-o')
        return ('storagegroup', '-setpath', '-gname', gname,
                '-hbauid', hba,
                '-sp', sp, '-spport', spport, '-spvport', vport,
                '-ip', ip, '-host', gname, '-o')


class DriverTestCaseBase(test.TestCase):
    def setUp(self):
        super(DriverTestCaseBase, self).setUp()

        self.stubs.Set(emc_vnx_cli.CommandLineHelper, 'command_execute',
                       self.fake_command_execute_for_driver_setup)
        self.stubs.Set(emc_vnx_cli.CommandLineHelper, 'get_array_serial',
                       mock.Mock(return_value={'array_serial':
                                               'fakeSerial'}))
        self.stubs.Set(os.path, 'exists', mock.Mock(return_value=1))

        self.stubs.Set(emc_vnx_cli, 'INTERVAL_5_SEC', 0.01)
        self.stubs.Set(emc_vnx_cli, 'INTERVAL_30_SEC', 0.01)

        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.naviseccli_path = '/opt/Navisphere/bin/naviseccli'
        self.configuration.san_ip = '10.0.0.1'
        self.configuration.storage_vnx_pool_name = 'unit_test_pool'
        self.configuration.san_login = 'sysadmin'
        self.configuration.san_password = 'sysadmin'
        self.configuration.initiator_auto_registration = True
        self.configuration.check_max_pool_luns_threshold = False
        self.stubs.Set(self.configuration, 'safe_get',
                       self.fake_safe_get({'storage_vnx_pool_names':
                                           'unit_test_pool',
                                           'volume_backend_name':
                                           'namedbackend'}))
        self.testData = EMCVNXCLIDriverTestData()
        self.navisecclicmd = '/opt/Navisphere/bin/naviseccli ' + \
            '-address 10.0.0.1 -user sysadmin -password sysadmin -scope 0 '
        self.configuration.iscsi_initiators = '{"fakehost": ["10.0.0.2"]}'
        self.configuration.ignore_pool_full_threshold = False

    def driverSetup(self, commands=tuple(), results=tuple()):
        self.driver = self.generate_driver(self.configuration)
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.Mock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli
        return fake_cli

    def generate_driver(self, conf):
        raise NotImplementedError

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

    def fake_command_execute_for_driver_setup(self, *command, **kwargv):
        if (command == ('connection', '-getport', '-address', '-vlanid') or
                command == ('connection', '-getport', '-vlanid')):
            return self.testData.ALL_PORTS
        elif command == ('storagepool', '-list', '-state'):
            return self.testData.POOL_GET_STATE_RESULT([
                {'pool_name': self.testData.test_pool_name, 'state': "Ready"},
                {'pool_name': "unit_test_pool2", 'state': "Ready"}])
        if command == self.testData.GETFCPORT_CMD():
            return self.testData.FC_PORTS
        else:
            return SUCCEED

    def fake_safe_get(self, values):
        def _safe_get(key):
            return values.get(key)
        return _safe_get


class EMCVNXCLIDriverISCSITestCase(DriverTestCaseBase):
    def generate_driver(self, conf):
        return emc_cli_iscsi.EMCCLIISCSIDriver(configuration=conf)

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
                'thick', None, poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                      poll=False),
            mock.call(*self.testData.LUN_DELETE_CMD('vol1'))]

        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    def test_create_volume_ignore_thresholds(self):
        self.configuration.ignore_pool_full_threshold = True
        fake_cli = self.driverSetup()
        self.driver.create_volume(self.testData.test_volume)
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol1', 1,
                'unit_test_pool',
                'thick', None,
                ignore_thresholds=True, poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                      poll=False)]

        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'compressed'}))
    def test_create_volume_compressed(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        # case
        self.driver.create_volume(self.testData.test_volume_with_type)
        # verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'compressed', None, poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=True),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(
                1))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        'oslo_service.loopingcall.FixedIntervalLoopingCall',
        new=utils.ZeroIntervalLoopingCall)
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'provisioning:type': 'thin',
                                'storagetype:provisioning': 'thick'}))
    def test_create_volume_thin(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        # case
        self.driver.create_volume(self.testData.test_volume_with_type)
        # verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'thin', None, poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        'oslo_service.loopingcall.FixedIntervalLoopingCall',
        new=utils.ZeroIntervalLoopingCall)
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'provisioning:type': 'thick'}))
    def test_create_volume_thick(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', False),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        # case
        self.driver.create_volume(self.testData.test_volume_with_type)
        # verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'thick', None, poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'compressed',
                                'storagetype:tiering': 'HighestAvailable'}))
    def test_create_volume_compressed_tiering_highestavailable(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        # case
        self.driver.create_volume(self.testData.test_volume_with_type)

        # verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'compressed', 'highestavailable', poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=True),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(
                1))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'deduplicated'}))
    def test_create_volume_deduplicated(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        # case
        self.driver.create_volume(self.testData.test_volume_with_type)

        # verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'deduplicated', None, poll=False))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:tiering': 'Auto'}))
    def test_create_volume_tiering_auto(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        # case
        self.driver.create_volume(self.testData.test_volume_with_type)

        # verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                None, 'auto', poll=False))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:tiering': 'Auto',
                                'storagetype:provisioning': 'Deduplicated'}))
    def test_create_volume_deduplicated_tiering_auto(self):
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

    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'Compressed'}))
    def test_create_volume_compressed_no_enabler(self):
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
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'copytype:snap': 'true'}))
    def test_create_volume_snapcopy_in_cg(self):
        self.driverSetup()
        vol = self.testData.test_volume_with_type.copy()
        vol['consistencygroup_id'] = '7450764f-9d24-4c70-ad46-7cd90acd4292'
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume,
            vol)

    def test_get_volume_stats(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_GET_ALL_CMD(True)]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_GET_ALL_RESULT(True)]
        self.driverSetup(commands, results)
        stats = self.driver.get_volume_stats(True)

        self.assertTrue(stats['driver_version'] == VERSION,
                        "driver_version is incorrect")
        self.assertTrue(
            stats['storage_protocol'] == 'iSCSI',
            "storage_protocol is incorrect")
        self.assertTrue(
            stats['vendor_name'] == "EMC",
            "vendor name is incorrect")
        self.assertTrue(
            stats['volume_backend_name'] == "namedbackend",
            "volume backend name is incorrect")

        pool_stats = stats['pools'][0]

        expected_pool_stats = {
            'free_capacity_gb': 3105.303,
            'reserved_percentage': 32,
            'location_info': 'unit_test_pool|fakeSerial',
            'total_capacity_gb': 3281.146,
            'provisioned_capacity_gb': 536.14,
            'compression_support': 'True',
            'deduplication_support': 'True',
            'thin_provisioning_support': True,
            'thick_provisioning_support': True,
            'max_over_subscription_ratio': 20.0,
            'consistencygroup_support': 'True',
            'pool_name': 'unit_test_pool',
            'fast_cache_enabled': 'True',
            'fast_support': 'True'}

        self.assertEqual(expected_pool_stats, pool_stats)

    def test_get_volume_stats_ignore_threshold(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_GET_ALL_CMD(True)]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_GET_ALL_RESULT(True)]
        self.driverSetup(commands, results)
        self.driver.cli.ignore_pool_full_threshold = True
        stats = self.driver.get_volume_stats(True)

        pool_stats = stats['pools'][0]
        self.assertEqual(2, pool_stats['reserved_percentage'])

    def test_get_volume_stats_reserved_percentage_from_conf(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_GET_ALL_CMD(True)]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_GET_ALL_RESULT(True)]
        self.configuration.reserved_percentage = 22
        self.driverSetup(commands, results)
        self.driver.cli.ignore_pool_full_threshold = True
        stats = self.driver.get_volume_stats(True)

        pool_stats = stats['pools'][0]
        self.assertEqual(22, pool_stats['reserved_percentage'])

    def test_get_volume_stats_too_many_luns(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_GET_ALL_CMD(True),
                    self.testData.POOL_FEATURE_INFO_POOL_LUNS_CMD()]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_GET_ALL_RESULT(True),
                   self.testData.POOL_FEATURE_INFO_POOL_LUNS(1000, 1000)]
        fake_cli = self.driverSetup(commands, results)

        self.driver.cli.check_max_pool_luns_threshold = True
        stats = self.driver.get_volume_stats(True)
        pool_stats = stats['pools'][0]
        self.assertTrue(
            pool_stats['free_capacity_gb'] == 0,
            "free_capacity_gb is incorrect")
        expect_cmd = [
            mock.call(*self.testData.POOL_FEATURE_INFO_POOL_LUNS_CMD(),
                      poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

        self.driver.cli.check_max_pool_luns_threshold = False
        stats = self.driver.get_volume_stats(True)
        pool_stats = stats['pools'][0]
        self.assertTrue(stats['driver_version'] is not None,
                        "driver_version is not returned")
        self.assertTrue(
            pool_stats['free_capacity_gb'] == 3105.303,
            "free_capacity_gb is incorrect")

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(return_value={'lun_id': 1}))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            side_effect=[1, 1]))
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
                   [(FAKE_MIGRATE_PROPERTY, 0),
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
        # verification
        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(1, 1),
                                retry_disable=True,
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(
                    return_value={'lun_id': 1}))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            side_effect=[1, 1]))
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
        results = [SUCCEED,
                   [(FAKE_MIGRATE_PROPERTY, 0),
                    ('The specified source LUN is not '
                     'currently migrating', 23)]]
        fake_cli = self.driverSetup(commands, results)
        fake_host = {'capabilities': {'location_info':
                                      "unit_test_pool2|fakeSerial",
                                      'storage_protocol': 'iSCSI'}}
        ret = self.driver.migrate_volume(None, self.testData.test_volume,
                                         fake_host)[0]
        self.assertTrue(ret)
        # verification
        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(),
                                retry_disable=True,
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(
                    return_value={'lun_id': 5}))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:tiering': 'Auto'}))
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
        results = [SUCCEED,
                   [(FAKE_MIGRATE_PROPERTY, 0),
                    ('The specified source LUN is not currently migrating',
                     23)]]
        fake_cli = self.driverSetup(commands, results)
        fakehost = {'capabilities': {'location_info':
                                     "unit_test_pool2|fakeSerial",
                                     'storage_protocol': 'iSCSI'}}
        ret = self.driver.migrate_volume(None, self.testData.test_volume5,
                                         fakehost)[0]
        self.assertTrue(ret)
        # verification
        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(5, 5),
                                retry_disable=True,
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(5),
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(5),
                                poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(
                    return_value={'lun_id': 1}))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            side_effect=[1, 1]))
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
        # verification
        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(),
                                retry_disable=True,
                                poll=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(
                    return_value={'lun_id': 1}))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            side_effect=[1, 1]))
    def test_volume_migration_stopped(self):

        commands = [self.testData.MIGRATION_CMD(),
                    self.testData.MIGRATION_VERIFY_CMD(1),
                    self.testData.MIGRATION_CANCEL_CMD(1)]

        results = [SUCCEED, [(self.testData.MIGRATE_PROPERTY_MIGRATING, 0),
                             (self.testData.MIGRATE_PROPERTY_STOPPED, 0),
                             ('The specified source LUN is not '
                              'currently migrating', 23)],
                   SUCCEED]
        fake_cli = self.driverSetup(commands, results)
        fake_host = {'capabilities': {'location_info':
                                      "unit_test_pool2|fakeSerial",
                                      'storage_protocol': 'iSCSI'}}

        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               "Migration of LUN 1 has been stopped or"
                               " faulted.",
                               self.driver.migrate_volume,
                               None, self.testData.test_volume, fake_host)

        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(),
                                retry_disable=True,
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=False),
                      mock.call(*self.testData.MIGRATION_CANCEL_CMD(1)),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(
                    return_value={'lun_id': 1}))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            side_effect=[1, 1]))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:tiering': 'Auto',
                                'copytype:snap': 'true'}))
    def test_volume_migration_smp(self):

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
        results = [SUCCEED,
                   [(FAKE_MIGRATE_PROPERTY, 0),
                    ('The specified source LUN is not '
                     'currently migrating', 23)]]
        fake_cli = self.driverSetup(commands, results)
        fake_host = {'capabilities': {'location_info':
                                      "unit_test_pool2|fakeSerial",
                                      'storage_protocol': 'iSCSI'}}

        vol = self.testData.test_volume.copy()
        vol['provider_location'] = 'system^FNM11111|type^smp|id^1'
        tmp_snap = "snap-as-vol-%s" % vol['id']
        ret = self.driver.migrate_volume(None,
                                         vol,
                                         fake_host)
        self.assertTrue(ret[0])
        self.assertTrue(
            ret[1]['provider_location'].find('type^lun') > 0)
        # verification
        expect_cmd = [mock.call(*self.testData.MIGRATION_CMD(),
                                retry_disable=True,
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=True),
                      mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                                poll=False),
                      mock.call(*self.testData.SNAP_DELETE_CMD(tmp_snap),
                                poll=True)]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_destroy_volume_snapshot(self):
        fake_cli = self.driverSetup()

        # case
        self.driver.create_snapshot(self.testData.test_snapshot)
        self.driver.delete_snapshot(self.testData.test_snapshot)

        # verification
        expect_cmd = [mock.call(*self.testData.SNAP_CREATE_CMD('snapshot1'),
                                poll=False),
                      mock.call(*self.testData.SNAP_DELETE_CMD('snapshot1'),
                                poll=True)]

        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_snapshot_preparing_volume(self):
        commands = [self.testData.SNAP_CREATE_CMD('snapshot1'),
                    self.testData.LUN_PROPERTY_ALL_CMD('vol1')]
        results = [[self.testData.LUN_PREP_ERROR(), SUCCEED],
                   [self.testData.LUN_PROPERTY('vol1', size=1,
                                               operation='Preparing'),
                    self.testData.LUN_PROPERTY('vol1', size=1,
                                               operation='Optimizing'),
                    self.testData.LUN_PROPERTY('vol1', size=1,
                                               operation='None')]]

        fake_cli = self.driverSetup(commands, results)

        self.driver.create_snapshot(self.testData.test_snapshot)
        expected = [mock.call(*self.testData.SNAP_CREATE_CMD('snapshot1'),
                              poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=True),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False),
                    mock.call(*self.testData.SNAP_CREATE_CMD('snapshot1'),
                              poll=False)]
        fake_cli.assert_has_calls(expected)

    @mock.patch(
        "oslo_concurrency.processutils.execute",
        mock.Mock(
            return_value=(
                "fakeportal iqn.1992-04.fake.com:fake.apm00123907237.a8", 0)))
    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection(self):
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    self.testData.PINGNODE_CMD('A', 4, 0, '10.0.0.2')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   self.testData.PING_OK]

        fake_cli = self.driverSetup(commands, results)

        connection_info = self.driver.initialize_connection(
            self.testData.test_volume,
            self.testData.connector)

        self.assertEqual(self.testData.iscsi_connection_info,
                         connection_info)

        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call(*self.testData.set_path_cmd(
                              'fakehost', 'iqn.1993-08.org.debian:01:222', 'A',
                              4, 0, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                              'fakehost', 'iqn.1993-08.org.debian:01:222',
                              'A', 0, 0, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                              'fakehost', 'iqn.1993-08.org.debian:01:222',
                              'B', 2, 0, '10.0.0.2')),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', '-o',
                              poll=False),
                    mock.call(*self.testData.PINGNODE_CMD('A', 4, 0,
                                                          '10.0.0.2'))]
        fake_cli.assert_has_calls(expected)

        # Test for manual registration
        self.configuration.initiator_auto_registration = False

        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    self.testData.CONNECTHOST_CMD('fakehost', 'fakehost'),
                    self.testData.PINGNODE_CMD('A', 4, 0, '10.0.0.2')]
        results = [
            [("No group", 83),
             self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
            ('', 0),
            self.testData.PING_OK
        ]
        fake_cli = self.driverSetup(commands, results)
        test_volume_rw = self.testData.test_volume_rw
        connection_info = self.driver.initialize_connection(
            test_volume_rw,
            self.testData.connector)

        self.assertEqual(self.testData.iscsi_connection_info,
                         connection_info)

        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', '-o', poll=False),
                    mock.call(*self.testData.PINGNODE_CMD('A', 4, 0,
                                                          '10.0.0.2'))]
        fake_cli.assert_has_calls(expected)

        # Test No Ping
        self.configuration.iscsi_initiators = None

        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    self.testData.CONNECTHOST_CMD('fakehost', 'fakehost')]
        results = [
            [("No group", 83),
             self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
            ('', 0)]
        fake_cli = self.driverSetup(commands, results)
        test_volume_rw = self.testData.test_volume_rw.copy()
        test_volume_rw['provider_location'] = 'system^fakesn|type^lun|id^1'
        connection_info = self.driver.initialize_connection(
            test_volume_rw,
            self.testData.connector)

        self.assertEqual(self.testData.iscsi_connection_info,
                         connection_info)

        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', '-o', poll=False)]
        fake_cli.assert_has_calls(expected)

    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    @mock.patch('cinder.volume.drivers.emc.emc_vnx_cli.'
                'CommandLineHelper.ping_node',
                mock.Mock(return_value=True))
    @mock.patch('random.shuffle', mock.Mock(return_value=0))
    def test_initialize_connection_multipath(self):
        self.configuration.initiator_auto_registration = False

        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost')]
        results = [self.testData.STORAGE_GROUP_HAS_MAP_MP('fakehost')]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.iscsi_targets = {
            'A': [
                {'Port WWN': 'iqn.1992-04.com.emc:cx.fnm00124000215.a4',
                 'SP': 'A',
                 'Port ID': 4,
                 'Virtual Port ID': 0,
                 'IP Address': '10.244.214.118'},
                {'Port WWN': 'iqn.1992-04.com.emc:cx.fnm00124000215.a5',
                 'SP': 'A',
                 'Port ID': 5,
                 'Virtual Port ID': 0,
                 'IP Address': '10.244.214.119'}],
            'B': []}
        test_volume_rw = self.testData.test_volume_rw.copy()
        test_volume_rw['provider_location'] = 'system^fakesn|type^lun|id^1'
        connector_m = dict(self.testData.connector)
        connector_m['multipath'] = True
        connection_info = self.driver.initialize_connection(
            test_volume_rw,
            connector_m)

        self.assertEqual(self.testData.iscsi_connection_info_mp,
                         connection_info)

        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', '-o', poll=False)]
        fake_cli.assert_has_calls(expected)

    @mock.patch(
        "oslo_concurrency.processutils.execute",
        mock.Mock(
            return_value=(
                "fakeportal iqn.1992-04.fake.com:fake.apm00123907237.a8", 0)))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            return_value=3))
    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection_exist(self):
        """Test if initialize connection exists.

        A LUN is added to the SG right before the attach,
        it may not exists in the first SG query
        """
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        self.configuration.max_luns_per_storage_group = 2
        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    ('storagegroup', '-addhlu', '-hlu', 2, '-alu', 3,
                     '-gname', 'fakehost', '-o'),
                    self.testData.PINGNODE_CMD('A', 4, 0, '10.0.0.2')]
        results = [[self.testData.STORAGE_GROUP_HAS_MAP('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP_2('fakehost')],
                   ("fakeerror", 23),
                   self.testData.PING_OK]

        fake_cli = self.driverSetup(commands, results)

        iscsi_data = self.driver.initialize_connection(
            self.testData.test_volume,
            self.testData.connector
        )
        self.assertTrue(iscsi_data['data']['target_lun'] == 2,
                        "iSCSI initialize connection returned wrong HLU")
        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 3,
                              '-gname', 'fakehost', '-o',
                              poll=False),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call(*self.testData.PINGNODE_CMD('A', 4, 0,
                                                          '10.0.0.2'))]
        fake_cli.assert_has_calls(expected)

    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection_iscsi_white_list(self):
        self.configuration.io_port_list = 'a-0-0,B-2-0'
        test_volume = self.testData.test_volume.copy()
        test_volume['provider_location'] = 'system^fakesn|type^lun|id^1'
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_HAS_MAP_ISCSI('fakehost')]]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.iscsi_targets = {'A': [{'SP': 'A', 'Port ID': 0,
                                                'Virtual Port ID': 0,
                                                'Port WWN': 'fake_iqn',
                                                'IP Address': '192.168.1.1'}],
                                         'B': [{'SP': 'B', 'Port ID': 2,
                                                'Virtual Port ID': 0,
                                                'Port WWN': 'fake_iqn1',
                                                'IP Address': '192.168.1.2'}]}
        self.driver.initialize_connection(
            test_volume,
            self.testData.connector)
        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call(*self.testData.set_path_cmd(
                              'fakehost', 'iqn.1993-08.org.debian:01:222',
                              'A', 0, 0, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                              'fakehost', 'iqn.1993-08.org.debian:01:222',
                              'B', 2, 0, '10.0.0.2')),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', '-o',
                              poll=False)]
        fake_cli.assert_has_calls(expected)

    @mock.patch('cinder.volume.drivers.emc.emc_vnx_cli.'
                'EMCVnxCliBase._build_pool_stats',
                mock.Mock(return_value=None))
    @mock.patch('cinder.volume.drivers.emc.emc_vnx_cli.'
                'CommandLineHelper.get_pool',
                mock.Mock(return_value={'total_capacity_gb': 0.0,
                                        'free_capacity_gb': 0.0}))
    def test_update_iscsi_io_ports(self):
        self.configuration.io_port_list = 'a-0-0,B-2-0'
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        commands = [self.testData.GETPORT_CMD()]
        results = [self.testData.WHITE_LIST_PORTS]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.update_volume_stats()
        expected = [mock.call(*self.testData.GETPORT_CMD(), poll=False)]
        fake_cli.assert_has_calls(expected)
        io_ports = self.driver.cli.iscsi_targets
        self.assertEqual((0, 'iqn.1992-04.com.emc:cx.fnmxxx.a0'),
                         (io_ports['A'][0]['Port ID'],
                          io_ports['A'][0]['Port WWN']))
        self.assertEqual((2, 'iqn.1992-04.com.emc:cx.fnmxxx.b2'),
                         (io_ports['B'][0]['Port ID'],
                          io_ports['B'][0]['Port WWN']))

    @mock.patch(
        "oslo_concurrency.processutils.execute",
        mock.Mock(
            return_value=(
                "fakeportal iqn.1992-04.fake.com:fake.apm00123907237.a8", 0)))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            return_value=4))
    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection_no_hlu_left_1(self):
        """Test initialize connection with no hlu per first SG query.

        There is no hlu per the first SG query
        But there are hlu left after the full poll
        """
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        self.configuration.max_luns_per_storage_group = 2
        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    ('storagegroup', '-addhlu', '-hlu', 2, '-alu', 4,
                     '-gname', 'fakehost', '-o'),
                    self.testData.PINGNODE_CMD('A', 4, 0, '10.0.0.2')]
        results = [[self.testData.STORAGE_GROUP_HAS_MAP_2('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   ("", 0),
                   self.testData.PING_OK]

        fake_cli = self.driverSetup(commands, results)

        iscsi_data = self.driver.initialize_connection(
            self.testData.test_volume,
            self.testData.connector)
        self.assertTrue(iscsi_data['data']['target_lun'] == 2,
                        "iSCSI initialize connection returned wrong HLU")
        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 4,
                              '-gname', 'fakehost', '-o',
                              poll=False),
                    mock.call(*self.testData.PINGNODE_CMD('A', 4, 0,
                                                          u'10.0.0.2'))]
        fake_cli.assert_has_calls(expected)

    @mock.patch(
        "oslo_concurrency.processutils.execute",
        mock.Mock(
            return_value=(
                "fakeportal iqn.1992-04.fake.com:fake.apm00123907237.a8", 0)))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(
            return_value=4))
    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection_no_hlu_left_2(self):
        """Test initialize connection with no hlu left."""
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        self.configuration.max_luns_per_storage_group = 2
        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost')]
        results = [
            [self.testData.STORAGE_GROUP_HAS_MAP_2('fakehost'),
             self.testData.STORAGE_GROUP_HAS_MAP_2('fakehost')]
        ]

        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          self.testData.test_volume,
                          self.testData.connector)
        expected = [
            mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                      poll=False),
            mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                      poll=True),
        ]
        fake_cli.assert_has_calls(expected)

    @mock.patch('os.path.exists', return_value=True)
    def test_terminate_connection(self, _mock_exists):

        self.driver = emc_cli_iscsi.EMCCLIISCSIDriver(
            configuration=self.configuration)
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

    def test_create_volume_cli_failed(self):
        commands = [self.testData.LUN_CREATION_CMD(
            'failed_vol1', 1, 'unit_test_pool', None, None, poll=False)]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(exception.EMCVnxCLICmdError,
                          self.driver.create_volume,
                          self.testData.test_failed_volume)
        expect_cmd = [mock.call(*self.testData.LUN_CREATION_CMD(
            'failed_vol1', 1, 'unit_test_pool', None, None, poll=False))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_create_faulted_volume(self):
        volume_name = 'faulted_volume'
        cmd_create = self.testData.LUN_CREATION_CMD(
            volume_name, 1, 'unit_test_pool', None, None, poll=False)
        cmd_list_preparing = self.testData.LUN_PROPERTY_ALL_CMD(volume_name)
        commands = [cmd_create, cmd_list_preparing]
        results = [SUCCEED,
                   [self.testData.LUN_PROPERTY(name=volume_name,
                                               state='Faulted',
                                               faulted='true',
                                               operation='Preparing'),
                    self.testData.LUN_PROPERTY(name=volume_name,
                                               state='Faulted',
                                               faulted='true',
                                               operation='None')]]
        fake_cli = self.driverSetup(commands, results)
        faulted_volume = self.testData.test_volume.copy()
        faulted_volume.update({'name': volume_name})
        self.driver.create_volume(faulted_volume)
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                volume_name, 1, 'unit_test_pool', None, None, poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(volume_name),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(volume_name),
                      poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_create_offline_volume(self):
        volume_name = 'offline_volume'
        cmd_create = self.testData.LUN_CREATION_CMD(
            volume_name, 1, 'unit_test_pool', None, None, poll=False)
        cmd_list = self.testData.LUN_PROPERTY_ALL_CMD(volume_name)
        commands = [cmd_create, cmd_list]
        results = [SUCCEED,
                   self.testData.LUN_PROPERTY(name=volume_name,
                                              state='Offline',
                                              faulted='true')]
        self.driverSetup(commands, results)
        offline_volume = self.testData.test_volume.copy()
        offline_volume.update({'name': volume_name})
        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               "Volume %s was created in VNX, but in"
                               " Offline state." % volume_name,
                               self.driver.create_volume,
                               offline_volume)

    def test_create_volume_snapshot_failed(self):
        commands = [self.testData.SNAP_CREATE_CMD('failed_snapshot')]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        # case
        self.assertRaises(exception.EMCVnxCLICmdError,
                          self.driver.create_snapshot,
                          self.testData.test_failed_snapshot)
        # verification
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_CREATE_CMD('failed_snapshot'),
                poll=False)]

        fake_cli.assert_has_calls(expect_cmd)

    def test_create_volume_from_snapshot(self):
        # set up
        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        cmd_dest_np = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        output_dest = self.testData.LUN_PROPERTY("vol2_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        output_migrate = ("", 0)
        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        commands = [cmd_dest, cmd_dest_np, cmd_migrate,
                    cmd_migrate_verify]
        results = [output_dest, output_dest, output_migrate,
                   output_migrate_verify]
        fake_cli1 = self.driverSetup(commands, results)

        self.driver.create_volume_from_snapshot(self.testData.test_volume2,
                                                self.testData.test_snapshot)
        expect_cmd1 = [
            mock.call(
                *self.testData.SNAP_MP_CREATE_CMD(
                    name='vol2', source='vol1'),
                poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2'),
                      poll=True),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='snapshot1')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      retry_disable=True,
                      poll=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=True)]
        fake_cli1.assert_has_calls(expect_cmd1)

        self.configuration.ignore_pool_full_threshold = True
        fake_cli2 = self.driverSetup(commands, results)
        self.driver.create_volume_from_snapshot(self.testData.test_volume2,
                                                self.testData.test_snapshot)
        expect_cmd2 = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None,
                ignore_thresholds=True))]
        fake_cli2.assert_has_calls(expect_cmd2)

    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'copytype:snap': 'true'}))
    def test_create_volume_from_snapshot_smp(self):
        fake_cli = self.driverSetup()
        vol = self.driver.create_volume_from_snapshot(
            self.testData.test_volume_with_type,
            self.testData.test_snapshot)
        self.assertTrue(
            vol['provider_location'].find('type^smp') > 0)
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_COPY_CMD(
                    src_snap='snapshot1',
                    snap_name='snap-as-vol-%s' % '1')),
            mock.call(
                *self.testData.SNAP_MODIFY_CMD(
                    name='snap-as-vol-%s' % '1',
                    rw='yes')),
            mock.call(
                *self.testData.SNAP_MP_CREATE_CMD(
                    name='vol_with_type', source='vol1'),
                poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                      poll=True),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol_with_type', snapName='snap-as-vol-%s' % '1'))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_create_volume_from_snapshot_sync_failed(self):

        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        cmd_dest_np = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        output_dest = self.testData.LUN_PROPERTY("vol2_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        cmd_detach_lun = ('lun', '-detach', '-name', 'vol2', '-o')
        output_migrate = ("", 0)
        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        cmd_migrate_cancel = self.testData.MIGRATION_CANCEL_CMD(1)
        output_migrate_cancel = ("", 0)

        commands = [cmd_dest, cmd_dest_np, cmd_migrate,
                    cmd_migrate_verify, cmd_migrate_cancel]
        results = [output_dest, output_dest, output_migrate,
                   [FAKE_ERROR_RETURN, output_migrate_verify],
                   output_migrate_cancel]

        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.testData.test_volume2,
                          self.testData.test_snapshot)
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_MP_CREATE_CMD(
                    name='vol2', source='vol1'),
                poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2'),
                      poll=True),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='snapshot1')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      retry_disable=True,
                      poll=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=True),
            mock.call(*self.testData.MIGRATION_CANCEL_CMD(1)),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=False),
            mock.call(*self.testData.LUN_DELETE_CMD('vol2_dest')),
            mock.call(*cmd_detach_lun),
            mock.call(*self.testData.LUN_DELETE_CMD('vol2'))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_vol_from_snap_failed_in_migrate_lun(self):
        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        output_dest = self.testData.LUN_PROPERTY("vol2_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        cmd_detach_lun = ('lun', '-detach', '-name', 'vol2', '-o')
        commands = [cmd_dest, cmd_migrate]
        results = [output_dest, FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          self.testData.test_volume2,
                          self.testData.test_snapshot)
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_MP_CREATE_CMD(
                    name='vol2', source='vol1'), poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2'), poll=True),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='snapshot1')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      poll=True,
                      retry_disable=True),
            mock.call(*self.testData.LUN_DELETE_CMD('vol2_dest')),
            mock.call(*cmd_detach_lun),
            mock.call(*self.testData.LUN_DELETE_CMD('vol2'))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_cloned_volume(self):
        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("clone1_dest")
        cmd_dest_p = self.testData.LUN_PROPERTY_ALL_CMD("clone1_dest")
        output_dest = self.testData.LUN_PROPERTY("clone1_dest")
        cmd_clone = self.testData.LUN_PROPERTY_ALL_CMD("clone1")
        output_clone = self.testData.LUN_PROPERTY("clone1")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        output_migrate = ("", 0)
        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        commands = [cmd_dest, cmd_dest_p, cmd_clone, cmd_migrate,
                    cmd_migrate_verify]
        results = [output_dest, output_dest, output_clone, output_migrate,
                   output_migrate_verify]
        fake_cli = self.driverSetup(commands, results)

        volume = self.testData.test_volume.copy()
        volume['name'] = 'clone1'

        self.driver.create_cloned_volume(volume, self.testData.test_volume)
        tmp_snap = 'tmp-snap-' + self.testData.test_volume['id']
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_CREATE_CMD(tmp_snap), poll=False),
            mock.call(*self.testData.SNAP_MP_CREATE_CMD(
                name='clone1',
                source='vol1'), poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('clone1'),
                      poll=True),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='clone1', snapName=tmp_snap)),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'clone1_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('clone1_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('clone1_dest'),
                      poll=False),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      poll=True,
                      retry_disable=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=True),
            mock.call(*self.testData.SNAP_DELETE_CMD(tmp_snap),
                      poll=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'copytype:snap': 'true'}))
    def test_create_cloned_volume_smp(self):
        fake_cli = self.driverSetup()
        vol = self.driver.create_cloned_volume(
            self.testData.test_clone,
            self.testData.test_volume_with_type)
        self.assertTrue(
            vol['provider_location'].find('type^smp') > 0)
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_CREATE_CMD(
                    name='snap-as-vol-%s' % '2'),
                poll=False),
            mock.call(
                *self.testData.SNAP_MP_CREATE_CMD(
                    name='clone1', source='vol_with_type'),
                poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('clone1'),
                      poll=True),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='clone1', snapName='snap-as-vol-%s' % '2'))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_delete_volume_failed(self):
        commands = [self.testData.LUN_DELETE_CMD('failed_vol1')]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(exception.EMCVnxCLICmdError,
                          self.driver.delete_volume,
                          self.testData.test_failed_volume)
        expected = [mock.call(*self.testData.LUN_DELETE_CMD('failed_vol1'))]
        fake_cli.assert_has_calls(expected)

    def test_delete_volume_in_sg_failed(self):
        commands = [self.testData.LUN_DELETE_CMD('vol1_in_sg'),
                    self.testData.LUN_DELETE_CMD('vol2_in_sg')]
        results = [self.testData.LUN_DELETE_IN_SG_ERROR(),
                   self.testData.LUN_DELETE_IN_SG_ERROR(False)]
        self.driverSetup(commands, results)
        self.assertRaises(exception.EMCVnxCLICmdError,
                          self.driver.delete_volume,
                          self.testData.test_volume1_in_sg)
        self.assertRaises(exception.EMCVnxCLICmdError,
                          self.driver.delete_volume,
                          self.testData.test_volume2_in_sg)

    def test_delete_volume_in_sg_force(self):
        commands = [self.testData.LUN_DELETE_CMD('vol1_in_sg'),
                    self.testData.STORAGEGROUP_LIST_CMD(),
                    self.testData.STORAGEGROUP_REMOVEHLU_CMD('fakehost1',
                                                             '41'),
                    self.testData.STORAGEGROUP_REMOVEHLU_CMD('fakehost1',
                                                             '42'),
                    self.testData.LUN_DELETE_CMD('vol2_in_sg'),
                    self.testData.STORAGEGROUP_REMOVEHLU_CMD('fakehost2',
                                                             '31'),
                    self.testData.STORAGEGROUP_REMOVEHLU_CMD('fakehost2',
                                                             '32')]
        results = [[self.testData.LUN_DELETE_IN_SG_ERROR(),
                    SUCCEED],
                   self.testData.STORAGE_GROUPS_HAS_MAP('fakehost1',
                                                        'fakehost2'),
                   SUCCEED,
                   SUCCEED,
                   [self.testData.LUN_DELETE_IN_SG_ERROR(False),
                    SUCCEED],
                   SUCCEED,
                   SUCCEED]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.force_delete_lun_in_sg = True
        self.driver.delete_volume(self.testData.test_volume1_in_sg)
        self.driver.delete_volume(self.testData.test_volume2_in_sg)
        expected = [mock.call(*self.testData.LUN_DELETE_CMD('vol1_in_sg')),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD(),
                              poll=True),
                    mock.call(*self.testData.STORAGEGROUP_REMOVEHLU_CMD(
                        'fakehost1', '41'), poll=False),
                    mock.call(*self.testData.STORAGEGROUP_REMOVEHLU_CMD(
                        'fakehost2', '42'), poll=False),
                    mock.call(*self.testData.LUN_DELETE_CMD('vol1_in_sg')),
                    mock.call(*self.testData.LUN_DELETE_CMD('vol2_in_sg')),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD(),
                              poll=True),
                    mock.call(*self.testData.STORAGEGROUP_REMOVEHLU_CMD(
                        'fakehost1', '31'), poll=False),
                    mock.call(*self.testData.STORAGEGROUP_REMOVEHLU_CMD(
                        'fakehost2', '32'), poll=False),
                    mock.call(*self.testData.LUN_DELETE_CMD('vol2_in_sg'))]
        fake_cli.assert_has_calls(expected)

    def test_delete_volume_smp(self):
        fake_cli = self.driverSetup()
        vol = self.testData.test_volume_with_type.copy()
        vol['provider_location'] = 'system^FNM11111|type^smp|id^1'
        tmp_snap = 'snap-as-vol-%s' % vol['id']
        self.driver.delete_volume(vol)
        expected = [mock.call(*self.testData.LUN_DELETE_CMD(vol['name'])),
                    mock.call(*self.testData.SNAP_DELETE_CMD(tmp_snap),
                              poll=True)]
        fake_cli.assert_has_calls(expected)

    def test_extend_volume(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol1')]
        results = [self.testData.LUN_PROPERTY('vol1', size=2)]
        fake_cli = self.driverSetup(commands, results)

        # case
        self.driver.extend_volume(self.testData.test_volume, 2)
        expected = [mock.call(*self.testData.LUN_EXTEND_CMD('vol1', 2),
                              poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False)]
        fake_cli.assert_has_calls(expected)

    def test_extend_volume_has_snapshot(self):
        commands = [self.testData.LUN_EXTEND_CMD('failed_vol1', 2)]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(exception.EMCVnxCLICmdError,
                          self.driver.extend_volume,
                          self.testData.test_failed_volume,
                          2)
        expected = [mock.call(*self.testData.LUN_EXTEND_CMD('failed_vol1', 2),
                              poll=False)]
        fake_cli.assert_has_calls(expected)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_extend_volume_failed(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('failed_vol1')]
        results = [self.testData.LUN_PROPERTY('failed_vol1', size=2)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli._client.timeout = 0

        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume,
                          self.testData.test_failed_volume,
                          3)
        expected = [
            mock.call(
                *self.testData.LUN_EXTEND_CMD('failed_vol1', 3),
                poll=False),
            mock.call(
                *self.testData.LUN_PROPERTY_ALL_CMD('failed_vol1'),
                poll=False)]
        fake_cli.assert_has_calls(expected)

    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_extend_preparing_volume(self):
        commands = [self.testData.LUN_EXTEND_CMD('vol1', 2),
                    self.testData.LUN_PROPERTY_ALL_CMD('vol1')]
        results = [[self.testData.LUN_PREP_ERROR(), SUCCEED],
                   [self.testData.LUN_PROPERTY('vol1', size=1,
                                               operation='Preparing'),
                    self.testData.LUN_PROPERTY('vol1', size=1,
                                               operation='Optimizing'),
                    self.testData.LUN_PROPERTY('vol1', size=1,
                                               operation='None'),
                    self.testData.LUN_PROPERTY('vol1', size=2)]]
        fake_cli = self.driverSetup(commands, results)

        self.driver.extend_volume(self.testData.test_volume, 2)
        expected = [mock.call(*self.testData.LUN_EXTEND_CMD('vol1', 2),
                              poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=True),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False),
                    mock.call(*self.testData.LUN_EXTEND_CMD('vol1', 2),
                              poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False)]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing(self):
        lun_rename_cmd = ('lun', '-modify', '-l', self.testData.test_lun_id,
                          '-newName', 'vol_with_type', '-o')
        commands = [lun_rename_cmd]

        results = [SUCCEED]
        self.configuration.storage_vnx_pool_name = \
            self.testData.test_pool_name
        fake_cli = self.driverSetup(commands, results)
        self.driver.manage_existing(
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref)
        expected = [mock.call(*lun_rename_cmd, poll=False)]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing_source_name(self):
        lun_rename_cmd = ('lun', '-modify', '-l', self.testData.test_lun_id,
                          '-newName', 'vol_with_type', '-o')
        commands = [lun_rename_cmd]

        results = [SUCCEED]
        fake_cli = self.driverSetup(commands, results)
        self.driver.manage_existing(
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref_source_name)
        expected = [mock.call(*lun_rename_cmd, poll=False)]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing_lun_in_another_pool(self):
        get_lun_cmd = ('lun', '-list', '-l', self.testData.test_lun_id,
                       '-state', '-userCap', '-owner',
                       '-attachedSnapshot', '-poolName')
        invalid_pool_name = "fake_pool"
        commands = [get_lun_cmd]
        results = [self.testData.LUN_PROPERTY('lun_name',
                                              pool_name=invalid_pool_name)]
        self.configuration.storage_vnx_pool_name = invalid_pool_name
        fake_cli = self.driverSetup(commands, results)
        # mock the command executor
        ex = self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size,
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref)
        self.assertTrue(
            re.match(r'.*not managed by the host',
                     ex.msg))
        expected = [mock.call(*get_lun_cmd, poll=True)]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing_get_size(self):
        get_lun_cmd = ('lun', '-list', '-l', self.testData.test_lun_id,
                       '-state', '-userCap', '-owner',
                       '-attachedSnapshot', '-poolName')
        test_size = 2
        commands = [get_lun_cmd]
        results = [self.testData.LUN_PROPERTY('lun_name', size=test_size)]

        self.configuration.storage_vnx_pool_name = \
            self.testData.test_pool_name
        fake_cli = self.driverSetup(commands, results)

        get_size = self.driver.manage_existing_get_size(
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref)
        expected = [mock.call(*get_lun_cmd, poll=True)]
        assert get_size == test_size
        fake_cli.assert_has_calls(expected)
        # Test the function with invalid reference.
        invaild_ref = {'fake': 'fake_ref'}
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size,
                          self.testData.test_volume_with_type,
                          invaild_ref)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "time.time",
        mock.Mock(return_value=123456))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'compressed'}))
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

        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.SNAP_LIST_CMD(),
                    cmd_migrate_verify]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023),
                   output_migrate_verify]
        fake_cli1 = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd1 = [
            mock.call(*self.testData.SNAP_LIST_CMD(), poll=False),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol3-123456', 2, 'unit_test_pool', 'deduplicated', None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol3-123456'),
                      poll=False),
            mock.call(*self.testData.MIGRATION_CMD(1, None),
                      retry_disable=True,
                      poll=True)]
        fake_cli1.assert_has_calls(expect_cmd1)

        self.configuration.ignore_pool_full_threshold = True
        fake_cli2 = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd2 = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol3-123456', 2, 'unit_test_pool', 'deduplicated', None,
                ignore_thresholds=True))]
        fake_cli2.assert_has_calls(expect_cmd2)

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
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(side_effect=[{'provisioning:type': 'thin'},
                               {'provisioning:type': 'thick'}]))
    def test_retype_turn_on_compression_and_autotiering(self):
        """Unit test for retype a volume to compressed and auto tiering."""
        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:provisioning':
                                         'compressed',
                                         'storagetype:tiering': 'auto'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'host@backendsec#unit_test_pool',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.SNAP_LIST_CMD()]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})
        # Retype a thin volume to a compressed volume
        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data, None, host_test_data)
        expect_cmd = [
            mock.call(*self.testData.SNAP_LIST_CMD(), poll=False),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(1)),
            mock.call(*self.testData.MODIFY_TIERING_CMD('vol3', 'auto'))
        ]
        fake_cli.assert_has_calls(expect_cmd)

        # Retype a thick volume to a compressed volume
        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data, None, host_test_data)
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
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'provisioning:type': 'thin'}))
    def test_retype_turn_on_compression_volume_has_snap(self):
        """Unit test for retype a volume which has snap to compressed."""
        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:provisioning':
                                         'compressed'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'host@backendsec#unit_test_pool',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.SNAP_LIST_CMD()]
        results = [self.testData.NDU_LIST_RESULT,
                   ('Has snap', 0)]
        self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})
        # Retype a thin volume which has a snap to a compressed volume
        retyped = self.driver.retype(None, self.testData.test_volume3,
                                     new_type_data, None, host_test_data)
        self.assertFalse(retyped,
                         "Retype should failed due to "
                         "the volume has snapshot")

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
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'deduplicated',
                                'storagetype:pool': 'unit_test_pool'}))
    def test_retype_pool_changed_dedup_to_compressed_auto(self):
        """Test retype from dedup to compressed and auto tiering.

        Unit test for retype dedup to compressed and auto tiering
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

        host_test_data = {'host':
                          'ubuntu-server12@pool_backend_1#unit_test_pool2',
                          'capabilities':
                          {'location_info': 'unit_test_pool2|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.SNAP_LIST_CMD(),
                    self.testData.MIGRATION_VERIFY_CMD(1)]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023),
                   ('The specified source LUN is not currently migrating', 23)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd = [
            mock.call(*self.testData.SNAP_LIST_CMD(), poll=False),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol3-123456', 2, 'unit_test_pool2', 'compressed', 'auto')),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(1)),
            mock.call(*self.testData.MIGRATION_CMD(),
                      retry_disable=True,
                      poll=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 1}))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'compressed',
                                'storagetype:pool': 'unit_test_pool',
                                'storagetype:tiering': 'auto'}))
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

        host_test_data = {
            'host': 'host@backendsec#unit_test_pool',
            'capabilities': {
                'location_info': 'unit_test_pool|FNM00124500890',
                'volume_backend_name': 'pool_backend_1',
                'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.SNAP_LIST_CMD()]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

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
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'thin',
                                'storagetype:pool': 'unit_test_pool'}))
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

        host_test_data = {
            'host': 'ubuntu-server12@pool_backend_2#unit_test_pool',
            'capabilities':
                {'location_info': 'unit_test_pool|FNM00124500891',
                 'volume_backend_name': 'pool_backend_2',
                 'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.SNAP_LIST_CMD()]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023)]
        self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

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
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'thin',
                                'storagetype:tiering': 'auto',
                                'storagetype:pool': 'unit_test_pool'}))
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

        host_test_data = {
            'host': 'ubuntu-server12@pool_backend_2#unit_test_pool',
            'capabilities':
                {'location_info': 'unit_test_pool|FNM00124500890',
                 'volume_backend_name': 'pool_backend_2',
                 'storage_protocol': 'FC'}}

        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.SNAP_LIST_CMD(),
                    self.testData.MIGRATION_VERIFY_CMD(1)]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023),
                   ('The specified source LUN is not currently migrating', 23)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd = [
            mock.call(*self.testData.SNAP_LIST_CMD(), poll=False),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol3-123456', 2, 'unit_test_pool', 'deduplicated', None)),
            mock.call(*self.testData.MIGRATION_CMD(),
                      retry_disable=True,
                      poll=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase.get_lun_id",
        mock.Mock(return_value=1))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 1}))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'thin',
                                'storagetype:tiering': 'auto',
                                'storagetype:pool': 'unit_test_pool'}))
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

        host_test_data = {
            'host': 'ubuntu-server12@pool_backend_1#unit_test_pool',
            'capabilities':
                {'location_info': 'unit_test_pool|FNM00124500890',
                 'volume_backend_name': 'pool_backend_1',
                 'storage_protocol': 'iSCSI'}}

        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.SNAP_LIST_CMD()]
        results = [self.testData.NDU_LIST_RESULT,
                   ('Has snap', 0)]
        self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

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
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'thin',
                                'storagetype:tiering': 'auto',
                                'storagetype:pool': 'unit_test_pool'}))
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

        host_test_data = {
            'host': 'ubuntu-server12@pool_backend_1#unit_test_pool',
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
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper."
        "migrate_lun_with_verification",
        mock.Mock(return_value=True))
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper."
        "create_lun_with_advance_feature",
        mock.Mock(return_value={'lun_id': '1'}))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'thin',
                                'copytype:snap': 'true'}))
    def test_retype_copytype_snap_true_to_false(self):
        diff_data = {'encryption': {}, 'qos_specs': {},
                     'extra_specs':
                     {'copytype:snap': ('true',
                                        'false')}}

        new_type_data = {'name': 'voltype0', 'qos_specs_id': None,
                         'deleted': False,
                         'extra_specs': {'storagetype:provisioning': 'thin',
                                         'copytype:snap': 'false'},
                         'id': 'f82f28c8-148b-416e-b1ae-32d3c02556c0'}

        host_test_data = {'host': 'ubuntu-server12@pool_backend_1',
                          'capabilities':
                          {'location_info': 'unit_test_pool|FNM00124500890',
                           'volume_backend_name': 'pool_backend_1',
                           'storage_protocol': 'iSCSI'}}

        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.SNAP_LIST_CMD(),
                    cmd_migrate_verify]
        results = [self.testData.NDU_LIST_RESULT,
                   ('No snap', 1023),
                   output_migrate_verify]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        emc_vnx_cli.CommandLineHelper.get_array_serial = mock.Mock(
            return_value={'array_serial': "FNM00124500890"})

        vol = self.testData.test_volume3.copy()
        vol['provider_location'] = 'system^FNM11111|type^smp|id^1'
        tmp_snap = 'snap-as-vol-%s' % vol['id']
        ret = self.driver.retype(None, vol,
                                 new_type_data,
                                 diff_data,
                                 host_test_data)
        self.assertTrue(type(ret) == tuple)
        self.assertTrue(ret[0])
        self.assertTrue(
            ret[1]['provider_location'].find('type^lun') > 0)
        expect_cmd = [
            mock.call(*self.testData.SNAP_LIST_CMD(), poll=False),
            mock.call(*self.testData.SNAP_DELETE_CMD(tmp_snap),
                      poll=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'fast_cache_enabled': 'True'}))
    def test_create_volume_with_fastcache(self):
        """Test creating volume with fastcache enabled."""
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_PROPERTY_W_FASTCACHE_CMD,
                    self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    ]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_PROPERTY_W_FASTCACHE,
                   self.testData.LUN_PROPERTY('vol_with_type', True),
                   ]
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

        cli_helper = self.driver.cli._client
        cli_helper.command_execute = fake_cli
        cli_helper.get_lun_by_name = mock.Mock(return_value=lun_info)
        cli_helper.get_enablers_on_array = mock.Mock(return_value="-FASTCache")
        cli_helper.get_pool_list = mock.Mock(return_value=[{
            'lun_nums': 1000,
            'total_capacity_gb': 10,
            'free_capacity_gb': 5,
            'provisioned_capacity_gb': 8,
            'pool_name': "unit_test_pool",
            'fast_cache_enabled': 'True',
            'state': 'Ready',
            'pool_full_threshold': 70.0}])

        self.driver.update_volume_stats()
        self.driver.create_volume(self.testData.test_volume_with_type)
        pool_stats = self.driver.cli.stats['pools'][0]
        self.assertEqual('True', pool_stats['fast_cache_enabled'])
        expect_cmd = [
            mock.call('connection', '-getport', '-address', '-vlanid',
                      poll=False),
            mock.call('-np', 'lun', '-create', '-capacity',
                      1, '-sq', 'gb', '-poolName',
                      self.testData.test_pool_name,
                      '-name', 'vol_with_type', '-type', 'NonThin')
        ]

        fake_cli.assert_has_calls(expect_cmd)

    def test_get_lun_id_provider_location_exists(self):
        """Test function get_lun_id."""
        self.driverSetup()
        volume_01 = {
            'name': 'vol_01',
            'size': 1,
            'volume_name': 'vol_01',
            'id': '1',
            'name_id': '1',
            'provider_location': 'system^FNM11111|type^lun|id^4',
            'project_id': 'project',
            'display_name': 'vol_01',
            'display_description': 'test volume',
            'volume_type_id': None}
        self.assertEqual(4, self.driver.cli.get_lun_id(volume_01))

    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.CommandLineHelper." +
        "get_lun_by_name",
        mock.Mock(return_value={'lun_id': 2}))
    def test_get_lun_id_provider_location_has_no_lun_id(self):
        """Test function get_lun_id."""
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
            'volume_type_id': None}
        self.assertEqual(2, self.driver.cli.get_lun_id(volume_02))

    def test_create_consistency_group(self):
        cg_name = self.testData.test_cg['id']
        commands = [self.testData.CREATE_CONSISTENCYGROUP_CMD(cg_name)]
        results = [SUCCEED]
        fake_cli = self.driverSetup(commands, results)

        model_update = self.driver.create_consistencygroup(
            None, self.testData.test_cg)
        self.assertDictMatch({'status': 'available'}, model_update)
        expect_cmd = [
            mock.call(
                *self.testData.CREATE_CONSISTENCYGROUP_CMD(
                    cg_name), poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.volume_types.get_volume_type_extra_specs",
        mock.Mock(side_effect=[{'storagetype:provisioning': 'thin'},
                               {'storagetype:provisioning': 'compressed'}]))
    def test_create_consistency_group_failed_with_compression(self):
        self.driverSetup([], [])
        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               "Failed to create consistency group "
                               "consistencygroup_id "
                               "because VNX consistency group cannot "
                               "accept compressed LUNs as members.",
                               self.driver.create_consistencygroup,
                               None,
                               self.testData.test_cg_with_type)

    def test_delete_consistency_group(self):
        cg_name = self.testData.test_cg['id']
        commands = [self.testData.DELETE_CONSISTENCYGROUP_CMD(cg_name),
                    self.testData.LUN_DELETE_CMD('vol1')]
        results = [SUCCEED, SUCCEED]
        fake_cli = self.driverSetup(commands, results)
        self.driver.db = mock.MagicMock()
        self.driver.db.volume_get_all_by_group.return_value =\
            self.testData.CONSISTENCY_GROUP_VOLUMES()
        self.driver.delete_consistencygroup(None,
                                            self.testData.test_cg)
        expect_cmd = [
            mock.call(
                *self.testData.DELETE_CONSISTENCYGROUP_CMD(
                    cg_name)),
            mock.call(*self.testData.LUN_DELETE_CMD('vol1')),
            mock.call(*self.testData.LUN_DELETE_CMD('vol1'))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        'cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_create_cgsnapshot(self, get_all_for_cgsnapshot):
        cgsnapshot = self.testData.test_cgsnapshot['id']
        cg_name = self.testData.test_cgsnapshot['consistencygroup_id']
        commands = [self.testData.CREATE_CG_SNAPSHOT(cg_name, cgsnapshot)]
        results = [SUCCEED]
        fake_cli = self.driverSetup(commands, results)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(
            self.testData.SNAPS_IN_SNAP_GROUP())
        snapshot_obj.consistencygroup_id = cg_name
        get_all_for_cgsnapshot.return_value = [snapshot_obj]
        self.driver.create_cgsnapshot(None, self.testData.test_cgsnapshot)
        expect_cmd = [
            mock.call(
                *self.testData.CREATE_CG_SNAPSHOT(
                    cg_name, cgsnapshot))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        'cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_delete_cgsnapshot(self, get_all_for_cgsnapshot):
        snap_name = self.testData.test_cgsnapshot['id']
        commands = [self.testData.DELETE_CG_SNAPSHOT(snap_name)]
        results = [SUCCEED]
        fake_cli = self.driverSetup(commands, results)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(
            self.testData.SNAPS_IN_SNAP_GROUP())
        cg_name = self.testData.test_cgsnapshot['consistencygroup_id']
        snapshot_obj.consistencygroup_id = cg_name
        get_all_for_cgsnapshot.return_value = [snapshot_obj]
        self.driver.delete_cgsnapshot(None,
                                      self.testData.test_cgsnapshot)
        expect_cmd = [
            mock.call(
                *self.testData.DELETE_CG_SNAPSHOT(
                    snap_name))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    def test_add_volume_to_cg(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                    self.testData.ADD_LUN_TO_CG_CMD('cg_id', 1),
                    ]
        results = [self.testData.LUN_PROPERTY('vol1', True),
                   SUCCEED]
        fake_cli = self.driverSetup(commands, results)

        self.driver.create_volume(self.testData.test_volume_cg)

        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol1', 1,
                'unit_test_pool',
                None, None, poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                      poll=False),
            mock.call(*self.testData.ADD_LUN_TO_CG_CMD(
                'cg_id', 1), poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_cloned_volume_from_consistnecy_group(self):
        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol1_dest")
        cmd_dest_p = self.testData.LUN_PROPERTY_ALL_CMD("vol1_dest")
        output_dest = self.testData.LUN_PROPERTY("vol1_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        output_migrate = ("", 0)
        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        cg_name = self.testData.test_cgsnapshot['consistencygroup_id']

        commands = [cmd_dest, cmd_dest_p, cmd_migrate,
                    cmd_migrate_verify]
        results = [output_dest, output_dest, output_migrate,
                   output_migrate_verify]
        fake_cli = self.driverSetup(commands, results)

        self.driver.create_cloned_volume(self.testData.test_volume_clone_cg,
                                         self.testData.test_clone_cg)
        tmp_cgsnapshot = 'tmp-cgsnapshot-' + self.testData.test_volume['id']
        expect_cmd = [
            mock.call(
                *self.testData.CREATE_CG_SNAPSHOT(cg_name, tmp_cgsnapshot)),
            mock.call(*self.testData.SNAP_MP_CREATE_CMD(name='vol1',
                                                        source='clone1'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'), poll=True),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol1', snapName=tmp_cgsnapshot)),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol1_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1_dest'),
                      poll=False),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      retry_disable=True,
                      poll=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=True),
            mock.call(*self.testData.DELETE_CG_SNAPSHOT(tmp_cgsnapshot))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_volume_from_cgsnapshot(self):
        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        cmd_dest_np = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        output_dest = self.testData.LUN_PROPERTY("vol2_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        output_migrate = ("", 0)
        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        commands = [cmd_dest, cmd_dest_np, cmd_migrate,
                    cmd_migrate_verify]
        results = [output_dest, output_dest, output_migrate,
                   output_migrate_verify]
        fake_cli = self.driverSetup(commands, results)

        self.driver.create_volume_from_snapshot(
            self.testData.volume_in_cg, self.testData.test_member_cgsnapshot)
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_MP_CREATE_CMD(
                    name='vol2', source='vol1'),
                poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2'),
                      poll=True),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='cgsnapshot_id')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      retry_disable=True,
                      poll=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=True)]
        fake_cli.assert_has_calls(expect_cmd)

    def test_update_consistencygroup(self):
        cg_name = self.testData.test_cg['id']
        commands = [self.testData.GET_CG_BY_NAME_CMD(cg_name)]
        results = [self.testData.CG_PROPERTY(cg_name)]
        fake_cli = self.driverSetup(commands, results)

        (model_update, add_vols, remove_vols) = (
            self.driver.update_consistencygroup(None, self.testData.test_cg,
                                                self.testData.
                                                VOLUMES_NOT_IN_CG(),
                                                self.testData.VOLUMES_IN_CG()))
        expect_cmd = [
            mock.call(*self.testData.REPLACE_LUNS_IN_CG_CMD(
                cg_name, ['4', '5']), poll=False)]
        fake_cli.assert_has_calls(expect_cmd)
        self.assertEqual('available', model_update['status'])

    def test_update_consistencygroup_remove_all(self):
        cg_name = self.testData.test_cg['id']
        commands = [self.testData.GET_CG_BY_NAME_CMD(cg_name)]
        results = [self.testData.CG_PROPERTY(cg_name)]
        fake_cli = self.driverSetup(commands, results)

        (model_update, add_vols, remove_vols) = (
            self.driver.update_consistencygroup(None, self.testData.test_cg,
                                                None,
                                                self.testData.VOLUMES_IN_CG()))
        expect_cmd = [
            mock.call(*self.testData.REMOVE_LUNS_FROM_CG_CMD(
                cg_name, ['1', '3']), poll=False)]
        fake_cli.assert_has_calls(expect_cmd)
        self.assertEqual('available', model_update['status'])

    def test_update_consistencygroup_remove_not_in_cg(self):
        cg_name = self.testData.test_cg['id']
        commands = [self.testData.GET_CG_BY_NAME_CMD(cg_name)]
        results = [self.testData.CG_PROPERTY(cg_name)]
        fake_cli = self.driverSetup(commands, results)

        (model_update, add_vols, remove_vols) = (
            self.driver.update_consistencygroup(None, self.testData.test_cg,
                                                None,
                                                self.testData.
                                                VOLUMES_NOT_IN_CG()))
        expect_cmd = [
            mock.call(*self.testData.REPLACE_LUNS_IN_CG_CMD(
                cg_name, ['1', '3']), poll=False)]
        fake_cli.assert_has_calls(expect_cmd)
        self.assertEqual('available', model_update['status'])

    def test_update_consistencygroup_error(self):
        cg_name = self.testData.test_cg['id']
        commands = [self.testData.GET_CG_BY_NAME_CMD(cg_name),
                    self.testData.REPLACE_LUNS_IN_CG_CMD(
                    cg_name, ['1', '3'])]
        results = [self.testData.CG_PROPERTY(cg_name),
                   self.testData.CG_REPL_ERROR()]
        fake_cli = self.driverSetup(commands, results)
        self.assertRaises(exception.EMCVnxCLICmdError,
                          self.driver.update_consistencygroup,
                          None,
                          self.testData.test_cg,
                          [],
                          self.testData.VOLUMES_NOT_IN_CG())
        expect_cmd = [
            mock.call(*self.testData.REPLACE_LUNS_IN_CG_CMD(
                cg_name, ['1', '3']), poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_consistencygroup_from_cgsnapshot(self):
        output_migrate_verify = ('The specified source LUN '
                                 'is not currently migrating.', 23)
        new_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        new_cg.id = 'new_cg_id'
        vol1_in_new_cg = self.testData.test_volume_cg.copy()
        vol1_in_new_cg.update(
            {'name': 'vol1_in_cg',
             'id': '111111',
             'consistencygroup_id': 'new_cg_id',
             'provider_location': None})
        vol2_in_new_cg = self.testData.test_volume_cg.copy()
        vol2_in_new_cg.update(
            {'name': 'vol2_in_cg',
             'id': '222222',
             'consistencygroup_id': 'new_cg_id',
             'provider_location': None})
        src_cgsnap = self.testData.test_cgsnapshot
        snap1_in_src_cgsnap = self.testData.test_member_cgsnapshot.copy()
        snap1_in_src_cgsnap.update(
            {'volume': fake_volume.fake_volume_obj(
             None, **self.testData.test_volume),
             'expected_attrs': ['volume']})
        snap1_in_src_cgsnap = fake_snapshot.fake_snapshot_obj(
            None, **snap1_in_src_cgsnap)
        snap2_in_src_cgsnap = self.testData.test_member_cgsnapshot.copy()
        snap2_in_src_cgsnap.update(
            {'volume': fake_volume.fake_volume_obj(
             None, **self.testData.test_volume2),
             'expected_attrs': ['volume']})
        snap2_in_src_cgsnap = fake_snapshot.fake_snapshot_obj(
            None, **snap2_in_src_cgsnap)
        copied_snap_name = 'temp_snapshot_for_%s' % new_cg['id']
        td = self.testData
        commands = [td.SNAP_COPY_CMD(src_cgsnap['id'], copied_snap_name),
                    td.ALLOW_READWRITE_ON_SNAP_CMD(copied_snap_name),
                    td.SNAP_MP_CREATE_CMD(vol1_in_new_cg['name'],
                                          snap1_in_src_cgsnap.volume_name),
                    td.SNAP_ATTACH_CMD(vol1_in_new_cg['name'],
                                       copied_snap_name),
                    td.LUN_CREATION_CMD(vol1_in_new_cg['name'] + '_dest',
                                        vol1_in_new_cg['size'],
                                        'unit_test_pool', 'thin', None),
                    td.LUN_PROPERTY_ALL_CMD(vol1_in_new_cg['name'] + '_dest'),
                    td.LUN_PROPERTY_ALL_CMD(vol1_in_new_cg['name']),
                    td.MIGRATION_CMD(6231, 1),

                    td.SNAP_MP_CREATE_CMD(vol2_in_new_cg['name'],
                                          snap2_in_src_cgsnap.volume_name),
                    td.SNAP_ATTACH_CMD(vol2_in_new_cg['name'],
                                       copied_snap_name),
                    td.LUN_CREATION_CMD(vol2_in_new_cg['name'] + '_dest',
                                        vol2_in_new_cg['size'],
                                        'unit_test_pool', 'thin', None),
                    td.LUN_PROPERTY_ALL_CMD(vol2_in_new_cg['name'] + '_dest'),
                    td.LUN_PROPERTY_ALL_CMD(vol2_in_new_cg['name']),
                    td.MIGRATION_CMD(6232, 2),

                    td.MIGRATION_VERIFY_CMD(6231),
                    td.MIGRATION_VERIFY_CMD(6232),
                    td.CREATE_CONSISTENCYGROUP_CMD(new_cg['id'], [6231, 6232]),
                    td.DELETE_CG_SNAPSHOT(copied_snap_name)
                    ]
        results = [SUCCEED, SUCCEED, SUCCEED, SUCCEED, SUCCEED,
                   td.LUN_PROPERTY(vol1_in_new_cg['name'] + '_dest',
                                   lunid=1),
                   td.LUN_PROPERTY(vol1_in_new_cg['name'], lunid=6231),
                   SUCCEED, SUCCEED, SUCCEED, SUCCEED,
                   td.LUN_PROPERTY(vol2_in_new_cg['name'] + '_dest',
                                   lunid=2),
                   td.LUN_PROPERTY(vol2_in_new_cg['name'], lunid=6232),
                   SUCCEED, output_migrate_verify, output_migrate_verify,
                   SUCCEED, SUCCEED]

        fake_cli = self.driverSetup(commands, results)

        cg_model_update, volumes_model_update = (
            self.driver.create_consistencygroup_from_src(
                None, new_cg, [vol1_in_new_cg, vol2_in_new_cg],
                cgsnapshot=src_cgsnap, snapshots=[snap1_in_src_cgsnap,
                                                  snap2_in_src_cgsnap],
                source_cg=None, source_vols=None))
        self.assertEqual(2, len(volumes_model_update))
        self.assertTrue('id^%s' % 6231 in
                        volumes_model_update[0]['provider_location'])
        self.assertTrue('id^%s' % 6232 in
                        volumes_model_update[1]['provider_location'])

        expect_cmd = [
            mock.call(*td.SNAP_COPY_CMD(src_cgsnap['id'], copied_snap_name)),
            mock.call(*td.ALLOW_READWRITE_ON_SNAP_CMD(copied_snap_name)),
            mock.call(*td.SNAP_MP_CREATE_CMD(vol1_in_new_cg['name'],
                      snap1_in_src_cgsnap.volume_name),
                      poll=False),
            mock.call(*td.LUN_PROPERTY_ALL_CMD(vol1_in_new_cg['name']),
                      poll=True),
            mock.call(*td.SNAP_ATTACH_CMD(vol1_in_new_cg['name'],
                      copied_snap_name)),
            mock.call(*td.LUN_CREATION_CMD(vol1_in_new_cg['name'] + '_dest',
                      vol1_in_new_cg['size'],
                      'unit_test_pool', 'thick', None)),
            mock.call(*td.LUN_PROPERTY_ALL_CMD(
                      vol1_in_new_cg['name'] + '_dest'), poll=False),
            mock.call(*td.LUN_PROPERTY_ALL_CMD(
                      vol1_in_new_cg['name'] + '_dest'), poll=False),
            mock.call(*td.MIGRATION_CMD(6231, 1),
                      poll=True, retry_disable=True),
            mock.call(*td.SNAP_MP_CREATE_CMD(vol2_in_new_cg['name'],
                      snap2_in_src_cgsnap.volume_name),
                      poll=False),
            mock.call(*td.LUN_PROPERTY_ALL_CMD(vol2_in_new_cg['name']),
                      poll=True),
            mock.call(*td.SNAP_ATTACH_CMD(vol2_in_new_cg['name'],
                      copied_snap_name)),
            mock.call(*td.LUN_CREATION_CMD(vol2_in_new_cg['name'] + '_dest',
                      vol2_in_new_cg['size'],
                      'unit_test_pool', 'thick', None)),
            mock.call(*td.LUN_PROPERTY_ALL_CMD(
                      vol2_in_new_cg['name'] + '_dest'), poll=False),
            mock.call(*td.LUN_PROPERTY_ALL_CMD(
                      vol2_in_new_cg['name'] + '_dest'), poll=False),
            mock.call(*td.MIGRATION_CMD(6232, 2),
                      poll=True, retry_disable=True),
            mock.call(*td.MIGRATION_VERIFY_CMD(6232), poll=True),
            mock.call(*td.MIGRATION_VERIFY_CMD(6231), poll=True),
            mock.call(*td.CREATE_CONSISTENCYGROUP_CMD(
                      new_cg['id'], [6232, 6231]), poll=True),
            mock.call(*td.DELETE_CG_SNAPSHOT(copied_snap_name))]
        self.assertEqual(expect_cmd, fake_cli.call_args_list)

    def test_create_cg_from_src_failed_without_source(self):
        new_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        vol1_in_new_cg = self.testData.test_volume_cg
        self.driverSetup()
        self.assertRaises(
            exception.InvalidInput,
            self.driver.create_consistencygroup_from_src,
            new_cg, [vol1_in_new_cg],
            None, None, None, None)

    def test_create_cg_from_src_failed_with_multiple_sources(self):
        new_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        vol1_in_new_cg = self.testData.test_volume_cg
        src_cgsnap = self.testData.test_cgsnapshot
        snap1_in_src_cgsnap = fake_snapshot.fake_snapshot_obj(
            None, **self.testData.test_member_cgsnapshot)
        src_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        src_cg.id = 'fake_source_cg'
        vol1_in_src_cg = {'id': 'fake_volume',
                          'consistencygroup_id': src_cg.id}
        self.driverSetup()
        self.assertRaises(
            exception.InvalidInput,
            self.driver.create_consistencygroup_from_src,
            new_cg, [vol1_in_new_cg],
            src_cgsnap, [snap1_in_src_cgsnap], src_cg, [vol1_in_src_cg])

    def test_create_cg_from_src_failed_with_invalid_source(self):
        new_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        src_cgsnap = self.testData.test_cgsnapshot
        vol1_in_new_cg = self.testData.test_volume_cg

        src_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        src_cg.id = 'fake_source_cg'
        self.driverSetup()
        self.assertRaises(
            exception.InvalidInput,
            self.driver.create_consistencygroup_from_src,
            new_cg, [vol1_in_new_cg],
            src_cgsnap, None, src_cg, None)

    def test_create_cg_from_cgsnapshot_migrate_failed(self):
        new_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        new_cg.id = 'new_cg_id'
        vol1_in_new_cg = self.testData.test_volume_cg.copy()
        vol1_in_new_cg.update(
            {'name': 'vol1_in_cg',
             'id': '111111',
             'consistencygroup_id': 'new_cg_id',
             'provider_location': None})
        vol2_in_new_cg = self.testData.test_volume_cg.copy()
        vol2_in_new_cg.update(
            {'name': 'vol2_in_cg',
             'id': '222222',
             'consistencygroup_id': 'new_cg_id',
             'provider_location': None})
        src_cgsnap = self.testData.test_cgsnapshot
        snap1_in_src_cgsnap = self.testData.test_member_cgsnapshot.copy()
        snap1_in_src_cgsnap.update(
            {'volume': fake_volume.fake_volume_obj(
             None, **self.testData.test_volume),
             'expected_attrs': ['volume']})
        snap1_in_src_cgsnap = fake_snapshot.fake_snapshot_obj(
            None, **snap1_in_src_cgsnap)
        snap2_in_src_cgsnap = self.testData.test_member_cgsnapshot.copy()
        snap2_in_src_cgsnap.update(
            {'volume': fake_volume.fake_volume_obj(
             None, **self.testData.test_volume2),
             'expected_attrs': ['volume']})
        snap2_in_src_cgsnap = fake_snapshot.fake_snapshot_obj(
            None, **snap2_in_src_cgsnap)
        copied_snap_name = 'temp_snapshot_for_%s' % new_cg['id']
        td = self.testData
        commands = [td.LUN_PROPERTY_ALL_CMD(vol1_in_new_cg['name'] + '_dest'),
                    td.LUN_PROPERTY_ALL_CMD(vol1_in_new_cg['name']),
                    td.LUN_PROPERTY_ALL_CMD(vol2_in_new_cg['name'] + '_dest'),
                    td.LUN_PROPERTY_ALL_CMD(vol2_in_new_cg['name']),
                    td.MIGRATION_CMD(6232, 2)]
        results = [td.LUN_PROPERTY(vol1_in_new_cg['name'] + '_dest',
                                   lunid=1),
                   td.LUN_PROPERTY(vol1_in_new_cg['name'], lunid=6231),
                   td.LUN_PROPERTY(vol2_in_new_cg['name'] + '_dest',
                                   lunid=2),
                   td.LUN_PROPERTY(vol2_in_new_cg['name'], lunid=6232),
                   FAKE_ERROR_RETURN]

        fake_cli = self.driverSetup(commands, results)
        self.assertRaisesRegex(exception.VolumeBackendAPIException,
                               'Migrate volume failed',
                               self.driver.create_consistencygroup_from_src,
                               None, new_cg, [vol1_in_new_cg, vol2_in_new_cg],
                               cgsnapshot=src_cgsnap,
                               snapshots=[snap1_in_src_cgsnap,
                                          snap2_in_src_cgsnap],
                               source_cg=None, source_vols=None)

        expect_cmd = [
            mock.call(*self.testData.LUN_DELETE_CMD(
                      vol2_in_new_cg['name'] + '_dest')),
            mock.call('lun', '-detach', '-name', vol2_in_new_cg['name'], '-o'),
            mock.call(*self.testData.LUN_DELETE_CMD(vol2_in_new_cg['name'])),
            mock.call(*self.testData.LUN_DELETE_CMD(
                      vol1_in_new_cg['name'] + '_dest')),
            mock.call('lun', '-detach', '-name', vol1_in_new_cg['name'], '-o'),
            mock.call(*self.testData.LUN_DELETE_CMD(vol1_in_new_cg['name'])),
            mock.call(*td.SNAP_DELETE_CMD(copied_snap_name), poll=True)]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_consistencygroup_from_cg(self):
        output_migrate_verify = ('The specified source LUN '
                                 'is not currently migrating.', 23)
        new_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        new_cg.id = 'new_cg_id'
        vol1_in_new_cg = self.testData.test_volume_cg.copy()
        vol1_in_new_cg.update(
            {'name': 'vol1_in_cg',
             'id': '111111',
             'consistencygroup_id': 'new_cg_id',
             'provider_location': None})
        vol2_in_new_cg = self.testData.test_volume_cg.copy()
        vol2_in_new_cg.update(
            {'name': 'vol2_in_cg',
             'id': '222222',
             'consistencygroup_id': 'new_cg_id',
             'provider_location': None})
        src_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        src_cg.id = 'src_cg_id'
        vol1_in_src_cg = self.testData.test_volume_cg.copy()
        vol1_in_src_cg.update(
            {'name': 'vol1_in_src_cg',
             'id': '111110000',
             'consistencygroup_id': 'src_cg_id',
             'provider_location': None})
        vol2_in_src_cg = self.testData.test_volume_cg.copy()
        vol2_in_src_cg.update(
            {'name': 'vol2_in_src_cg',
             'id': '222220000',
             'consistencygroup_id': 'src_cg_id',
             'provider_location': None})
        temp_snap_name = 'temp_snapshot_for_%s' % new_cg['id']
        td = self.testData
        commands = [td.CREATE_CG_SNAPSHOT(src_cg['id'], temp_snap_name),
                    td.SNAP_MP_CREATE_CMD(vol1_in_new_cg['name'],
                                          vol1_in_src_cg['name']),
                    td.SNAP_ATTACH_CMD(vol1_in_new_cg['name'],
                                       temp_snap_name),
                    td.LUN_CREATION_CMD(vol1_in_new_cg['name'] + '_dest',
                                        vol1_in_new_cg['size'],
                                        'unit_test_pool', 'thin', None),
                    td.LUN_PROPERTY_ALL_CMD(vol1_in_new_cg['name'] + '_dest'),
                    td.LUN_PROPERTY_ALL_CMD(vol1_in_new_cg['name']),
                    td.MIGRATION_CMD(6231, 1),

                    td.SNAP_MP_CREATE_CMD(vol2_in_new_cg['name'],
                                          vol2_in_src_cg['name']),
                    td.SNAP_ATTACH_CMD(vol2_in_new_cg['name'],
                                       temp_snap_name),
                    td.LUN_CREATION_CMD(vol2_in_new_cg['name'] + '_dest',
                                        vol2_in_new_cg['size'],
                                        'unit_test_pool', 'thin', None),
                    td.LUN_PROPERTY_ALL_CMD(vol2_in_new_cg['name'] + '_dest'),
                    td.LUN_PROPERTY_ALL_CMD(vol2_in_new_cg['name']),
                    td.MIGRATION_CMD(6232, 2),

                    td.MIGRATION_VERIFY_CMD(6231),
                    td.MIGRATION_VERIFY_CMD(6232),
                    td.CREATE_CONSISTENCYGROUP_CMD(new_cg['id'], [6231, 6232]),
                    td.DELETE_CG_SNAPSHOT(temp_snap_name)
                    ]
        results = [SUCCEED, SUCCEED, SUCCEED, SUCCEED,
                   td.LUN_PROPERTY(vol1_in_new_cg['name'] + '_dest',
                                   lunid=1),
                   td.LUN_PROPERTY(vol1_in_new_cg['name'], lunid=6231),
                   SUCCEED, SUCCEED, SUCCEED, SUCCEED,
                   td.LUN_PROPERTY(vol2_in_new_cg['name'] + '_dest',
                                   lunid=2),
                   td.LUN_PROPERTY(vol2_in_new_cg['name'], lunid=6232),
                   SUCCEED, output_migrate_verify, output_migrate_verify,
                   SUCCEED, SUCCEED]

        fake_cli = self.driverSetup(commands, results)

        cg_model_update, volumes_model_update = (
            self.driver.create_consistencygroup_from_src(
                None, new_cg, [vol1_in_new_cg, vol2_in_new_cg],
                cgsnapshot=None, snapshots=None,
                source_cg=src_cg, source_vols=[vol1_in_src_cg,
                                               vol2_in_src_cg]))
        self.assertEqual(2, len(volumes_model_update))
        self.assertTrue('id^%s' % 6231 in
                        volumes_model_update[0]['provider_location'])
        self.assertTrue('id^%s' % 6232 in
                        volumes_model_update[1]['provider_location'])

        delete_temp_snap_cmd = [
            mock.call(*td.DELETE_CG_SNAPSHOT(temp_snap_name))]
        fake_cli.assert_has_calls(delete_temp_snap_cmd)

    @mock.patch.object(emc_vnx_cli, 'LOG')
    @mock.patch.object(emc_vnx_cli.CommandLineHelper,
                       'delete_cgsnapshot')
    def test_delete_temp_cgsnapshot_failed_will_not_raise_exception(
            self, mock_delete_cgsnapshot, mock_logger):
        temp_snap_name = 'fake_temp'
        self.driverSetup()
        mock_delete_cgsnapshot.side_effect = exception.EMCVnxCLICmdError(
            cmd='fake_cmd', rc=200, out='fake_output')
        self.driver.cli._delete_temp_cgsnap(temp_snap_name)
        mock_delete_cgsnapshot.assert_called_once_with(temp_snap_name)
        self.assertTrue(mock_logger.warning.called)

    @mock.patch.object(emc_vnx_cli.CreateSMPTask, 'execute',
                       mock.Mock(side_effect=exception.EMCVnxCLICmdError(
                           cmd='fake_cmd', rc=20, out='fake_output')))
    @mock.patch.object(emc_vnx_cli.CreateSMPTask, 'revert',
                       mock.Mock())
    def test_create_consistencygroup_from_cg_roll_back(self):
        new_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        new_cg.id = 'new_cg_id'
        vol1_in_new_cg = self.testData.test_volume_cg.copy()
        vol1_in_new_cg.update(
            {'name': 'vol1_in_cg',
             'id': '111111',
             'consistencygroup_id': 'new_cg_id',
             'provider_location': None})
        src_cg = fake_consistencygroup.fake_consistencyobject_obj(
            None, **self.testData.test_cg)
        src_cg.id = 'src_cg_id'
        vol1_in_src_cg = self.testData.test_volume_cg.copy()
        vol1_in_src_cg.update(
            {'name': 'vol1_in_src_cg',
             'id': '111110000',
             'consistencygroup_id': 'src_cg_id',
             'provider_location': None})
        temp_snap_name = 'temp_snapshot_for_%s' % new_cg['id']
        td = self.testData
        commands = [td.CREATE_CG_SNAPSHOT(src_cg['id'], temp_snap_name),
                    td.DELETE_CG_SNAPSHOT(temp_snap_name)]
        results = [SUCCEED, SUCCEED]

        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(
            exception.EMCVnxCLICmdError,
            self.driver.create_consistencygroup_from_src,
            None, new_cg, [vol1_in_new_cg],
            cgsnapshot=None, snapshots=None,
            source_cg=src_cg, source_vols=[vol1_in_src_cg])

        rollback_cmd = [
            mock.call(*td.DELETE_CG_SNAPSHOT(temp_snap_name))]
        fake_cli.assert_has_calls(rollback_cmd)

    def test_deregister_initiator(self):
        fake_cli = self.driverSetup()
        self.driver.cli.destroy_empty_sg = True
        self.driver.cli.itor_auto_dereg = True
        cli_helper = self.driver.cli._client
        data = {'storage_group_name': "fakehost",
                'storage_group_uid': "2F:D4:00:00:00:00:00:"
                "00:00:00:FF:E5:3A:03:FD:6D",
                'lunmap': {1: 16}}
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
        cli_helper.disconnect_host_from_storage_group = mock.Mock()
        cli_helper.delete_storage_group = mock.Mock()
        self.driver.terminate_connection(self.testData.test_volume,
                                         self.testData.connector)
        expect_cmd = [
            mock.call('port', '-removeHBA', '-hbauid',
                      self.testData.connector['initiator'],
                      '-o')]
        fake_cli.assert_has_calls(expect_cmd)

    def test_unmanage(self):
        self.driverSetup()
        try:
            self.driver.unmanage(self.testData.test_volume)
        except NotImplementedError:
            self.fail('Interface unmanage need to be implemented')

    @mock.patch("random.shuffle", mock.Mock())
    def test_find_available_iscsi_targets_without_pingnode(self):
        self.configuration.iscsi_initiators = None
        self.driverSetup()
        port_a1 = {'Port WWN': 'fake_iqn_a1',
                   'SP': 'A',
                   'Port ID': 1,
                   'Virtual Port ID': 0,
                   'IP Address': 'fake_ip_a1'}
        port_a2 = {'Port WWN': 'fake_iqn_a2',
                   'SP': 'A',
                   'Port ID': 2,
                   'Virtual Port ID': 0,
                   'IP Address': 'fake_ip_a2'}
        port_b1 = {'Port WWN': 'fake_iqn_b1',
                   'SP': 'B',
                   'Port ID': 1,
                   'Virtual Port ID': 0,
                   'IP Address': 'fake_ip_b1'}
        all_targets = {'A': [port_a1, port_a2],
                       'B': [port_b1]}
        targets = self.driver.cli._client.find_available_iscsi_targets(
            'fakehost',
            {('A', 2, 0), ('B', 1, 0)},
            all_targets)
        self.assertTrue(port_a2 in targets)
        self.assertTrue(port_b1 in targets)

    @mock.patch.object(emc_vnx_cli.CommandLineHelper,
                       'ping_node')
    def test_find_available_iscsi_targets_with_pingnode(self, ping_node):
        self.configuration.iscsi_initiators = (
            '{"fakehost": ["10.0.0.2"]}')
        self.driverSetup()
        port_a1 = {'Port WWN': 'fake_iqn_a1',
                   'SP': 'A',
                   'Port ID': 1,
                   'Virtual Port ID': 0,
                   'IP Address': 'fake_ip_a1'}
        port_a2 = {'Port WWN': 'fake_iqn_a2',
                   'SP': 'A',
                   'Port ID': 2,
                   'Virtual Port ID': 0,
                   'IP Address': 'fake_ip_a2'}
        port_b1 = {'Port WWN': 'fake_iqn_b1',
                   'SP': 'B',
                   'Port ID': 1,
                   'Virtual Port ID': 0,
                   'IP Address': 'fake_ip_b1'}
        all_targets = {'A': [port_a1, port_a2],
                       'B': [port_b1]}
        ping_node.side_effect = [False, False, True]
        targets = self.driver.cli._client.find_available_iscsi_targets(
            'fakehost',
            {('A', 2, 0), ('A', 1, 0), ('B', 1, 0)},
            all_targets)
        self.assertTrue(port_a1 in targets)
        self.assertTrue(port_a2 in targets)
        self.assertTrue(port_b1 in targets)

    @mock.patch('cinder.volume.drivers.emc.emc_vnx_cli.'
                'EMCVnxCliBase.get_lun_owner',
                mock.Mock(return_value='A'))
    @mock.patch('cinder.volume.drivers.emc.emc_vnx_cli.'
                'CommandLineHelper.get_registered_spport_set',
                mock.Mock())
    @mock.patch.object(emc_vnx_cli.CommandLineHelper,
                       'find_available_iscsi_targets')
    def test_vnx_get_iscsi_properties(self, find_available_iscsi_targets):
        self.driverSetup()
        port_a1 = {'Port WWN': 'fake_iqn_a1',
                   'SP': 'A',
                   'Port ID': 1,
                   'Virtual Port ID': 0,
                   'IP Address': 'fake_ip_a1'}
        port_b1 = {'Port WWN': 'fake_iqn_b1',
                   'SP': 'B',
                   'Port ID': 1,
                   'Virtual Port ID': 0,
                   'IP Address': 'fake_ip_b1'}
        find_available_iscsi_targets.return_value = [port_a1, port_b1]
        connect_info = self.driver.cli.vnx_get_iscsi_properties(
            self.testData.test_volume, self.testData.connector, 1, '')
        expected_info = {
            'target_discovered': True,
            'target_iqns': [
                'fake_iqn_a1',
                'fake_iqn_b1'],
            'target_iqn': 'fake_iqn_a1',
            'target_luns': [1, 1],
            'target_lun': 1,
            'target_portals': [
                'fake_ip_a1:3260',
                'fake_ip_b1:3260'],
            'target_portal': 'fake_ip_a1:3260',
            'volume_id': '1'}
        self.assertEqual(expected_info, connect_info)

    def test_update_migrated_volume(self):
        self.driverSetup()
        expected_update = {'metadata': {'lun_type': 'lun'}}
        model_update = self.driver.update_migrated_volume(
            None, self.testData.test_volume,
            self.testData.test_volume2, 'available')
        self.assertDictMatch(expected_update, model_update)


class EMCVNXCLIDArrayBasedDriverTestCase(DriverTestCaseBase):
    def setUp(self):
        super(EMCVNXCLIDArrayBasedDriverTestCase, self).setUp()
        self.configuration.safe_get = self.fake_safe_get(
            {'storage_vnx_pool_names': None,
             'volume_backend_name': 'namedbackend'})

    def generate_driver(self, conf):
        driver = emc_cli_iscsi.EMCCLIISCSIDriver(configuration=conf)
        return driver

    def test_get_volume_stats(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_GET_ALL_CMD(True)]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_GET_ALL_RESULT(True)]
        self.driverSetup(commands, results)
        stats = self.driver.get_volume_stats(True)

        self.assertTrue(stats['driver_version'] == VERSION,
                        "driver_version is incorrect")
        self.assertTrue(
            stats['storage_protocol'] == 'iSCSI',
            "storage_protocol is not correct")
        self.assertTrue(
            stats['vendor_name'] == "EMC",
            "vendor name is not correct")
        self.assertTrue(
            stats['volume_backend_name'] == "namedbackend",
            "volume backend name is not correct")

        self.assertEqual(2, len(stats['pools']))
        pool_stats1 = stats['pools'][0]
        expected_pool_stats1 = {
            'free_capacity_gb': 3105.303,
            'reserved_percentage': 32,
            'location_info': 'unit_test_pool|fakeSerial',
            'total_capacity_gb': 3281.146,
            'provisioned_capacity_gb': 536.140,
            'compression_support': 'True',
            'deduplication_support': 'True',
            'thin_provisioning_support': True,
            'thick_provisioning_support': True,
            'consistencygroup_support': 'True',
            'pool_name': 'unit_test_pool',
            'max_over_subscription_ratio': 20.0,
            'fast_cache_enabled': 'True',
            'fast_support': 'True'}
        self.assertEqual(expected_pool_stats1, pool_stats1)

        pool_stats2 = stats['pools'][1]
        expected_pool_stats2 = {
            'free_capacity_gb': 3984.768,
            'reserved_percentage': 32,
            'location_info': 'unit_test_pool2|fakeSerial',
            'total_capacity_gb': 4099.992,
            'provisioned_capacity_gb': 636.240,
            'compression_support': 'True',
            'deduplication_support': 'True',
            'thin_provisioning_support': True,
            'thick_provisioning_support': True,
            'consistencygroup_support': 'True',
            'pool_name': 'unit_test_pool2',
            'max_over_subscription_ratio': 20.0,
            'fast_cache_enabled': 'False',
            'fast_support': 'True'}
        self.assertEqual(expected_pool_stats2, pool_stats2)

    def test_get_volume_stats_wo_fastcache(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_GET_ALL_CMD(False)]
        results = [self.testData.NDU_LIST_RESULT_WO_LICENSE,
                   self.testData.POOL_GET_ALL_RESULT(False)]
        self.driverSetup(commands, results)

        stats = self.driver.get_volume_stats(True)

        self.assertEqual(2, len(stats['pools']))
        pool_stats1 = stats['pools'][0]
        expected_pool_stats1 = {
            'free_capacity_gb': 3105.303,
            'reserved_percentage': 32,
            'location_info': 'unit_test_pool|fakeSerial',
            'total_capacity_gb': 3281.146,
            'provisioned_capacity_gb': 536.140,
            'compression_support': 'False',
            'deduplication_support': 'False',
            'thin_provisioning_support': False,
            'thick_provisioning_support': True,
            'consistencygroup_support': 'False',
            'pool_name': 'unit_test_pool',
            'max_over_subscription_ratio': 20.0,
            'fast_cache_enabled': 'False',
            'fast_support': 'False'}
        self.assertEqual(expected_pool_stats1, pool_stats1)

        pool_stats2 = stats['pools'][1]
        expected_pool_stats2 = {
            'free_capacity_gb': 3984.768,
            'reserved_percentage': 32,
            'location_info': 'unit_test_pool2|fakeSerial',
            'total_capacity_gb': 4099.992,
            'provisioned_capacity_gb': 636.240,
            'compression_support': 'False',
            'deduplication_support': 'False',
            'thin_provisioning_support': False,
            'thick_provisioning_support': True,
            'consistencygroup_support': 'False',
            'pool_name': 'unit_test_pool2',
            'max_over_subscription_ratio': 20.0,
            'fast_cache_enabled': 'False',
            'fast_support': 'False'}
        self.assertEqual(expected_pool_stats2, pool_stats2)

    def test_get_volume_stats_storagepool_states(self):
        commands = [self.testData.POOL_GET_ALL_CMD(False)]
        results = [self.testData.POOL_GET_ALL_STATES_TEST
                   (['Initializing', 'Ready', 'Faulted',
                     'Offline', 'Deleting'])]
        self.driverSetup(commands, results)

        stats = self.driver.get_volume_stats(True)
        self.assertTrue(
            stats['pools'][0]['free_capacity_gb'] == 0,
            "free_capacity_gb is incorrect")
        self.assertTrue(
            stats['pools'][1]['free_capacity_gb'] != 0,
            "free_capacity_gb is incorrect")
        self.assertTrue(
            stats['pools'][2]['free_capacity_gb'] != 0,
            "free_capacity_gb is incorrect")
        self.assertTrue(
            stats['pools'][3]['free_capacity_gb'] == 0,
            "free_capacity_gb is incorrect")
        self.assertTrue(
            stats['pools'][4]['free_capacity_gb'] == 0,
            "free_capacity_gb is incorrect")

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'deduplicated'}))
    def test_create_volume_deduplicated(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type')]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True)]

        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        # Case
        self.driver.create_volume(self.testData.test_volume_with_type)

        # Verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'deduplicated', None, poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                      poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    def test_get_pool(self):
        testVolume = self.testData.test_volume_with_type
        commands = [self.testData.LUN_PROPERTY_POOL_CMD(testVolume['name'])]
        results = [self.testData.LUN_PROPERTY(testVolume['name'], False)]
        fake_cli = self.driverSetup(commands, results)
        pool = self.driver.get_pool(testVolume)
        self.assertEqual('unit_test_pool', pool)
        fake_cli.assert_has_calls(
            [mock.call(*self.testData.LUN_PROPERTY_POOL_CMD(
                testVolume['name']), poll=False)])

    def test_get_target_pool_for_cloned_volme(self):
        testSrcVolume = self.testData.test_volume
        testNewVolume = self.testData.test_volume2
        fake_cli = self.driverSetup()
        pool = self.driver.cli.get_target_storagepool(testNewVolume,
                                                      testSrcVolume)
        self.assertEqual('unit_test_pool', pool)
        self.assertFalse(fake_cli.called)

    def test_get_target_pool_for_clone_legacy_volme(self):
        testSrcVolume = self.testData.test_legacy_volume
        testNewVolume = self.testData.test_volume2
        commands = [self.testData.LUN_PROPERTY_POOL_CMD(testSrcVolume['name'])]
        results = [self.testData.LUN_PROPERTY(testSrcVolume['name'], False)]
        fake_cli = self.driverSetup(commands, results)
        pool = self.driver.cli.get_target_storagepool(testNewVolume,
                                                      testSrcVolume)
        self.assertEqual('unit_test_pool', pool)
        fake_cli.assert_has_calls(
            [mock.call(*self.testData.LUN_PROPERTY_POOL_CMD(
                testSrcVolume['name']), poll=False)])

    def test_manage_existing_get_size(self):
        get_lun_cmd = ('lun', '-list', '-l', self.testData.test_lun_id,
                       '-state', '-userCap', '-owner',
                       '-attachedSnapshot', '-poolName')
        test_size = 2
        commands = [get_lun_cmd]
        results = [self.testData.LUN_PROPERTY('lun_name', size=test_size)]
        fake_cli = self.driverSetup(commands, results)
        test_volume = self.testData.test_volume2.copy()
        test_volume['host'] = "host@backendsec#unit_test_pool"
        get_size = self.driver.manage_existing_get_size(
            test_volume,
            self.testData.test_existing_ref)
        expected = [mock.call(*get_lun_cmd, poll=True)]
        self.assertEqual(test_size, get_size)
        fake_cli.assert_has_calls(expected)

    def test_manage_existing_get_size_incorrect_pool(self):
        """Test manage_existing function of driver with an invalid pool."""

        get_lun_cmd = ('lun', '-list', '-l', self.testData.test_lun_id,
                       '-state', '-userCap', '-owner',
                       '-attachedSnapshot', '-poolName')
        commands = [get_lun_cmd]
        results = [self.testData.LUN_PROPERTY('lun_name')]
        fake_cli = self.driverSetup(commands, results)
        test_volume = self.testData.test_volume2.copy()
        test_volume['host'] = "host@backendsec#fake_pool"
        ex = self.assertRaises(
            exception.ManageExistingInvalidReference,
            self.driver.manage_existing_get_size,
            test_volume,
            self.testData.test_existing_ref)
        self.assertTrue(
            re.match(r'.*not managed by the host',
                     ex.msg))
        expected = [mock.call(*get_lun_cmd, poll=True)]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing(self):
        lun_rename_cmd = ('lun', '-modify', '-l', self.testData.test_lun_id,
                          '-newName', 'vol_with_type', '-o')
        commands = [lun_rename_cmd]
        results = [SUCCEED]
        fake_cli = self.driverSetup(commands, results)
        self.driver.manage_existing(
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref)
        expected = [mock.call(*lun_rename_cmd, poll=False)]
        fake_cli.assert_has_calls(expected)

    @mock.patch(
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'Compressed',
                                'storagetype:pool': 'unit_test_pool'}))
    def test_create_compression_volume(self):
        commands = [self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.LUN_PROPERTY_ALL_CMD('vol_with_type'),
                    self.testData.NDU_LIST_CMD]
        results = [self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.LUN_PROPERTY('vol_with_type', True),
                   self.testData.NDU_LIST_RESULT]

        fake_cli = self.driverSetup(commands, results)

        self.driver.cli.stats['compression_support'] = 'True'
        self.driver.cli.enablers = ['-Compression',
                                    '-Deduplication',
                                    '-ThinProvisioning',
                                    '-FAST']
        # Case
        self.driver.create_volume(self.testData.test_volume_with_type)
        # Verification
        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol_with_type', 1,
                'unit_test_pool',
                'compressed', None, poll=False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=True),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(
                1))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_get_registered_spport_set(self):
        self.driverSetup()
        spport_set = self.driver.cli._client.get_registered_spport_set(
            'iqn.1993-08.org.debian:01:222', 'fakehost',
            self.testData.STORAGE_GROUP_HAS_MAP_ISCSI('fakehost')[0])
        self.assertEqual({('A', 2, 0), ('A', 0, 0), ('B', 2, 0)}, spport_set)

    def test_validate_iscsi_port(self):
        self.driverSetup()
        port_list = (
            "SP:  A\n"
            "Port ID:  6\n"
            "Port WWN:  iqn.fake.a6\n"
            "iSCSI Alias:  1111.a6\n"
            "\n"
            "Virtual Port ID:  0\n"
            "VLAN ID:  Disabled\n"
            "\n"
            "SP:  B\n"
            "Port ID:  7\n"
            "Port WWN:  iqn.fake.b7\n"
            "iSCSI Alias:  0235.b7"
            "\n"
            "Virtual Port ID:  0\n"
            "VLAN ID:  Disabled\n"
            "\n"
            "Virtual Port ID:  1\n"
            "VLAN ID:  200\n"
            "\n\n")
        self.assertFalse(self.driver.cli._validate_iscsi_port(
            'A', 5, 0, port_list))
        self.assertTrue(self.driver.cli._validate_iscsi_port(
            'A', 6, 0, port_list))
        self.assertFalse(self.driver.cli._validate_iscsi_port(
            'A', 6, 2, port_list))
        self.assertTrue(self.driver.cli._validate_iscsi_port(
            'B', 7, 1, port_list))
        self.assertTrue(self.driver.cli._validate_iscsi_port(
            'B', 7, 0, port_list))
        self.assertFalse(self.driver.cli._validate_iscsi_port(
            'B', 7, 2, port_list))


class EMCVNXCLIDriverFCTestCase(DriverTestCaseBase):
    def generate_driver(self, conf):
        return emc_cli_fc.EMCCLIFCDriver(configuration=conf)

    @mock.patch(
        "oslo_concurrency.processutils.execute",
        mock.Mock(
            return_value=(
                "fakeportal iqn.1992-04.fake.com:fake.apm00123907237.a8", 0)))
    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection_fc_auto_reg(self):
        # Test for auto registration
        test_volume = self.testData.test_volume.copy()
        test_volume['provider_location'] = 'system^fakesn|type^lun|id^1'
        self.configuration.initiator_auto_registration = True
        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    self.testData.GETFCPORT_CMD(),
                    ('port', '-list', '-gname', 'fakehost')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   self.testData.FC_PORTS,
                   self.testData.FAKEHOST_PORTS]

        fake_cli = self.driverSetup(commands, results)
        self.driver.initialize_connection(
            test_volume,
            self.testData.connector)

        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('port', '-list', '-sp'),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:12:34:56:12:34:56:78:90'
                        ':12:34:56', 'A', '0', None, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:12:34:56:12:34:56:78:90'
                        ':12:34:56', 'B', '2', None, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:54:32:16:12:34:56:78:90'
                        ':54:32:16', 'A', '0', None, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:54:32:16:12:34:56:78:90'
                        ':54:32:16', 'B', '2', None, '10.0.0.2')),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', '-o',
                              poll=False),
                    mock.call('port', '-list', '-gname', 'fakehost')
                    ]
        fake_cli.assert_has_calls(expected)

        # Test for manaul registration
        self.configuration.initiator_auto_registration = False

        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    self.testData.CONNECTHOST_CMD('fakehost', 'fakehost'),
                    self.testData.GETFCPORT_CMD(),
                    ('port', '-list', '-gname', 'fakehost')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_NO_MAP('fakehost')],
                   ('', 0),
                   self.testData.FC_PORTS,
                   self.testData.FAKEHOST_PORTS]
        fake_cli = self.driverSetup(commands, results)
        self.driver.initialize_connection(
            test_volume,
            self.testData.connector)

        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 1, '-alu', 1,
                              '-gname', 'fakehost', '-o', poll=False),
                    mock.call('port', '-list', '-gname', 'fakehost')
                    ]
        fake_cli.assert_has_calls(expected)

    @mock.patch(
        "cinder.zonemanager.fc_san_lookup_service.FCSanLookupService." +
        "get_device_mapping_from_network",
        mock.Mock(return_value=EMCVNXCLIDriverTestData.device_map))
    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection_fc_auto_zoning(self):
        # Test for auto zoning
        self.configuration.zoning_mode = 'fabric'
        self.configuration.initiator_auto_registration = False
        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    self.testData.CONNECTHOST_CMD('fakehost', 'fakehost'),
                    self.testData.GETFCPORT_CMD()]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_NO_MAP('fakehost'),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   ('', 0),
                   self.testData.FC_PORTS]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.zonemanager_lookup_service =\
            fc_service.FCSanLookupService(configuration=self.configuration)

        conn_info = self.driver.initialize_connection(
            self.testData.test_volume,
            self.testData.connector)

        self.assertEqual(EMCVNXCLIDriverTestData.i_t_map,
                         conn_info['data']['initiator_target_map'])
        self.assertEqual(['1122334455667777'],
                         conn_info['data']['target_wwn'])
        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 1, '-alu', 1,
                              '-gname', 'fakehost', '-o',
                              poll=False),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call('port', '-list', '-sp')]
        fake_cli.assert_has_calls(expected)

    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection_fc_white_list(self):
        self.configuration.io_port_list = 'a-0,B-2'
        test_volume = self.testData.test_volume.copy()
        test_volume['provider_location'] = 'system^fakesn|type^lun|id^1'
        self.configuration.initiator_auto_registration = True
        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    self.testData.GETFCPORT_CMD(),
                    ('port', '-list', '-gname', 'fakehost')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_HAS_MAP_ISCSI('fakehost')],
                   self.testData.FC_PORTS,
                   self.testData.FAKEHOST_PORTS]

        fake_cli = self.driverSetup(commands, results)
        data = self.driver.initialize_connection(
            test_volume,
            self.testData.connector)

        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:12:34:56:12:34:56:78:'
                        '90:12:34:56', 'A', 0, None, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:12:34:56:12:34:56:78:'
                        '90:12:34:56', 'B', 2, None, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:54:32:16:12:34:56:78'
                        ':90:54:32:16', 'A', 0, None, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:54:32:16:12:34:56:78'
                        ':90:54:32:16', 'B', 2, None, '10.0.0.2')),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', '-o',
                              poll=False),
                    mock.call('port', '-list', '-gname', 'fakehost')]
        fake_cli.assert_has_calls(expected)
        self.assertEqual(['5006016A0860080F', '5006016008600195'],
                         data['data']['target_wwn'])

    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection_fc_port_registered_wl(self):
        self.configuration.io_port_list = 'a-0,B-2'
        test_volume = self.testData.test_volume.copy()
        test_volume['provider_location'] = 'system^fakesn|type^lun|id^1'
        self.configuration.initiator_auto_registration = True
        commands = [self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                    self.testData.GETFCPORT_CMD(),
                    ('port', '-list', '-gname', 'fakehost')]
        results = [self.testData.STORAGE_GROUP_ISCSI_FC_HBA('fakehost'),
                   self.testData.FC_PORTS,
                   self.testData.FAKEHOST_PORTS]

        fake_cli = self.driverSetup(commands, results)
        data = self.driver.initialize_connection(
            test_volume,
            self.testData.connector)

        expected = [mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=False),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:12:34:56:12:34:56:78:90'
                        ':12:34:56', 'A', 0, None, '10.0.0.2')),
                    mock.call(*self.testData.set_path_cmd(
                        'fakehost', '22:34:56:78:90:54:32:16:12:34:56:78:'
                        '90:54:32:16', 'A', 0, None, '10.0.0.2')),
                    mock.call(*self.testData.STORAGEGROUP_LIST_CMD('fakehost'),
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', '-o',
                              poll=False),
                    mock.call('port', '-list', '-gname', 'fakehost')]
        fake_cli.assert_has_calls(expected)
        self.assertEqual(['5006016A0860080F', '5006016008600195'],
                         data['data']['target_wwn'])

    @mock.patch(
        "cinder.zonemanager.fc_san_lookup_service.FCSanLookupService." +
        "get_device_mapping_from_network",
        mock.Mock(return_value=EMCVNXCLIDriverTestData.device_map))
    def test_terminate_connection_remove_zone_false(self):
        self.driver = emc_cli_fc.EMCCLIFCDriver(
            configuration=self.configuration)
        cli_helper = self.driver.cli._client
        data = {'storage_group_name': "fakehost",
                'storage_group_uid': "2F:D4:00:00:00:00:00:"
                "00:00:00:FF:E5:3A:03:FD:6D",
                'lunmap': {1: 16, 2: 88, 3: 47}}
        cli_helper.get_storage_group = mock.Mock(
            return_value=data)
        cli_helper.remove_hlu_from_storagegroup = mock.Mock()
        self.driver.cli.zonemanager_lookup_service =\
            fc_service.FCSanLookupService(configuration=self.configuration)
        connection_info = self.driver.terminate_connection(
            self.testData.test_volume,
            self.testData.connector)
        self.assertFalse(connection_info['data'],
                         'connection_info data should not be None.')

        cli_helper.remove_hlu_from_storagegroup.assert_called_once_with(
            16, self.testData.connector["host"])

    @mock.patch(
        "cinder.zonemanager.fc_san_lookup_service.FCSanLookupService." +
        "get_device_mapping_from_network",
        mock.Mock(return_value=EMCVNXCLIDriverTestData.device_map))
    def test_terminate_connection_remove_zone_true(self):
        self.driver = emc_cli_fc.EMCCLIFCDriver(
            configuration=self.configuration)
        cli_helper = self.driver.cli._client
        data = {'storage_group_name': "fakehost",
                'storage_group_uid': "2F:D4:00:00:00:00:00:"
                "00:00:00:FF:E5:3A:03:FD:6D",
                'lunmap': {}}
        cli_helper.get_storage_group = mock.Mock(
            return_value=data)
        cli_helper.remove_hlu_from_storagegroup = mock.Mock()
        self.driver.cli.zonemanager_lookup_service =\
            fc_service.FCSanLookupService(configuration=self.configuration)
        connection_info = self.driver.terminate_connection(
            self.testData.test_volume,
            self.testData.connector)
        self.assertTrue('initiator_target_map' in connection_info['data'],
                        'initiator_target_map should be populated.')
        self.assertEqual(EMCVNXCLIDriverTestData.i_t_map,
                         connection_info['data']['initiator_target_map'])

    def test_get_volume_stats(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_GET_ALL_CMD(True)]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_GET_ALL_RESULT(True)]
        self.driverSetup(commands, results)
        stats = self.driver.get_volume_stats(True)

        self.assertTrue(stats['driver_version'] == VERSION,
                        "driver_version is incorrect")
        self.assertTrue(
            stats['storage_protocol'] == 'FC',
            "storage_protocol is incorrect")
        self.assertTrue(
            stats['vendor_name'] == "EMC",
            "vendor name is incorrect")
        self.assertTrue(
            stats['volume_backend_name'] == "namedbackend",
            "volume backend name is incorrect")

        pool_stats = stats['pools'][0]

        expected_pool_stats = {
            'free_capacity_gb': 3105.303,
            'reserved_percentage': 32,
            'location_info': 'unit_test_pool|fakeSerial',
            'total_capacity_gb': 3281.146,
            'provisioned_capacity_gb': 536.14,
            'compression_support': 'True',
            'deduplication_support': 'True',
            'thin_provisioning_support': True,
            'thick_provisioning_support': True,
            'max_over_subscription_ratio': 20.0,
            'consistencygroup_support': 'True',
            'pool_name': 'unit_test_pool',
            'fast_cache_enabled': 'True',
            'fast_support': 'True'}

        self.assertEqual(expected_pool_stats, pool_stats)

    def test_get_volume_stats_too_many_luns(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_GET_ALL_CMD(True),
                    self.testData.POOL_FEATURE_INFO_POOL_LUNS_CMD()]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_GET_ALL_RESULT(True),
                   self.testData.POOL_FEATURE_INFO_POOL_LUNS(1000, 1000)]
        fake_cli = self.driverSetup(commands, results)
        self.driver.cli.check_max_pool_luns_threshold = True
        stats = self.driver.get_volume_stats(True)
        pool_stats = stats['pools'][0]
        self.assertTrue(
            pool_stats['free_capacity_gb'] == 0,
            "free_capacity_gb is incorrect")
        expect_cmd = [
            mock.call(*self.testData.POOL_FEATURE_INFO_POOL_LUNS_CMD(),
                      poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

        self.driver.cli.check_max_pool_luns_threshold = False
        stats = self.driver.get_volume_stats(True)
        pool_stats = stats['pools'][0]
        self.assertTrue(stats['driver_version'] is not None,
                        "driver_version is incorrect")
        self.assertTrue(
            pool_stats['free_capacity_gb'] == 3105.303,
            "free_capacity_gb is incorrect")

    def test_deregister_initiator(self):
        fake_cli = self.driverSetup()
        self.driver.cli.destroy_empty_sg = True
        self.driver.cli.itor_auto_dereg = True
        cli_helper = self.driver.cli._client
        data = {'storage_group_name': "fakehost",
                'storage_group_uid': "2F:D4:00:00:00:00:00:"
                "00:00:00:FF:E5:3A:03:FD:6D",
                'lunmap': {1: 16}}
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
        cli_helper.disconnect_host_from_storage_group = mock.Mock()
        cli_helper.delete_storage_group = mock.Mock()
        self.driver.terminate_connection(self.testData.test_volume,
                                         self.testData.connector)
        fc_itor_1 = '22:34:56:78:90:12:34:56:12:34:56:78:90:12:34:56'
        fc_itor_2 = '22:34:56:78:90:54:32:16:12:34:56:78:90:54:32:16'
        expect_cmd = [
            mock.call('port', '-removeHBA', '-hbauid', fc_itor_1, '-o'),
            mock.call('port', '-removeHBA', '-hbauid', fc_itor_2, '-o')]
        fake_cli.assert_has_calls(expect_cmd)


class EMCVNXCLIToggleSPTestData(object):
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

    def test_no_sp_toggle(self):
        self.cli_client.active_storage_ip = '10.10.10.10'
        FAKE_SUCCESS_RETURN = ('success', 0)
        FAKE_COMMAND = ('list', 'pool')
        SIDE_EFFECTS = [FAKE_SUCCESS_RETURN]

        with mock.patch('cinder.utils.execute') as mock_utils:
            mock_utils.side_effect = SIDE_EFFECTS
            self.cli_client.command_execute(*FAKE_COMMAND)
            self.assertEqual("10.10.10.10", self.cli_client.active_storage_ip)
            expected = [
                mock.call(*(self.test_data.FAKE_COMMAND_PREFIX('10.10.10.10')
                          + FAKE_COMMAND), check_exit_code=True)]
            mock_utils.assert_has_calls(expected)

    def test_toggle_sp_with_server_unavailabe(self):
        self.cli_client.active_storage_ip = '10.10.10.10'
        FAKE_ERROR_MSG = """\
Error occurred during HTTP request/response from the target: '10.244.213.142'.
Message : HTTP/1.1 503 Service Unavailable"""
        FAKE_SUCCESS_RETURN = ('success', 0)
        FAKE_COMMAND = ('list', 'pool')
        SIDE_EFFECTS = [processutils.ProcessExecutionError(
            exit_code=255, stdout=FAKE_ERROR_MSG),
            FAKE_SUCCESS_RETURN]

        with mock.patch('cinder.utils.execute') as mock_utils:
            mock_utils.side_effect = SIDE_EFFECTS
            self.cli_client.command_execute(*FAKE_COMMAND)
            self.assertEqual("10.10.10.11", self.cli_client.active_storage_ip)
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
        SIDE_EFFECTS = [processutils.ProcessExecutionError(
            exit_code=255, stdout=FAKE_ERROR_MSG),
            FAKE_SUCCESS_RETURN]

        with mock.patch('cinder.utils.execute') as mock_utils:
            mock_utils.side_effect = SIDE_EFFECTS
            self.cli_client.command_execute(*FAKE_COMMAND)
            self.assertEqual("10.10.10.11", self.cli_client.active_storage_ip)
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
        SIDE_EFFECTS = [processutils.ProcessExecutionError(
            exit_code=255, stdout=FAKE_ERROR_MSG),
            FAKE_SUCCESS_RETURN]

        with mock.patch('cinder.utils.execute') as mock_utils:
            mock_utils.side_effect = SIDE_EFFECTS
            self.cli_client.command_execute(*FAKE_COMMAND)
            self.assertEqual("10.10.10.11", self.cli_client.active_storage_ip)
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

    def test_toggle_sp_with_connection_error(self):
        self.cli_client.active_storage_ip = '10.10.10.10'
        FAKE_ERROR_MSG = """\
A network error occurred while trying to connect: '192.168.1.56'.
Message : Error occurred because of time out"""
        FAKE_SUCCESS_RETURN = ('success', 0)
        FAKE_COMMAND = ('list', 'pool')
        SIDE_EFFECTS = [processutils.ProcessExecutionError(
            exit_code=255, stdout=FAKE_ERROR_MSG),
            FAKE_SUCCESS_RETURN]

        with mock.patch('cinder.utils.execute') as mock_utils:
            mock_utils.side_effect = SIDE_EFFECTS
            self.cli_client.command_execute(*FAKE_COMMAND)
            self.assertEqual("10.10.10.11", self.cli_client.active_storage_ip)
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


class EMCVNXCLIBackupTestCase(DriverTestCaseBase):
    """Provides cli-level and client-level mock test."""

    def driverSetup(self):
        self.context = context.get_admin_context()
        self.driver = self.generate_driver(self.configuration)
        self.driver.cli._client = mock.Mock()
        self.snapshot = fake_snapshot.fake_snapshot_obj(
            self.context, **self.testData.test_snapshot)
        volume = fake_volume.fake_volume_obj(self.context)
        self.snapshot.volume = volume
        return self.driver.cli._client

    def generate_driver(self, conf):
        driver = emc_cli_iscsi.EMCCLIISCSIDriver(configuration=conf)
        return driver

    @patch.object(emc_vnx_cli.EMCVnxCliBase, 'terminate_connection')
    def test_terminate_connection_snapshot(self, terminate_connection):
        fake_client = self.driverSetup()
        connector = self.testData.connector
        smp_name = 'tmp-smp-' + self.snapshot['id']
        volume = {'name': smp_name}
        self.driver.terminate_connection_snapshot(
            self.snapshot, connector)
        terminate_connection.assert_called_once_with(
            volume, connector)
        fake_client.detach_mount_point.assert_called_once_with(
            smp_name)

    @patch.object(emc_vnx_cli.EMCVnxCliBase, 'initialize_connection')
    def test_initialize_connection_snapshot(self, initialize_connection):
        fake_client = self.driverSetup()
        connector = self.testData.connector
        smp_name = 'tmp-smp-' + self.snapshot['id']
        self.driver.initialize_connection_snapshot(
            self.snapshot, connector)
        fake_client.attach_mount_point.assert_called_once_with(
            smp_name, self.snapshot['name'])
        volume = {'name': smp_name, 'id': self.snapshot['id']}
        initialize_connection.assert_called_once_with(
            volume, connector)

    def test_create_export_snapshot(self):
        fake_client = self.driverSetup()
        connector = self.testData.connector
        smp_name = 'tmp-smp-' + self.snapshot['id']
        self.driver.create_export_snapshot(
            None, self.snapshot, connector)
        fake_client.create_mount_point.assert_called_once_with(
            self.snapshot['volume_name'], smp_name)

    @patch.object(emc_vnx_cli.EMCVnxCliBase, 'delete_volume')
    def test_remove_export_snapshot(self, delete_volume):
        self.driverSetup()
        smp_name = 'tmp-smp-' + self.snapshot['id']
        self.driver.remove_export_snapshot(None, self.snapshot)
        volume = {'name': smp_name, 'provider_location': None}
        delete_volume.assert_called_once_with(volume, True)


class EMCVNXCLIMultiPoolsTestCase(DriverTestCaseBase):

    def generate_driver(self, conf):
        driver = emc_cli_iscsi.EMCCLIISCSIDriver(configuration=conf)
        return driver

    def fake_command_execute_for_driver_setup(self, *command, **kwargv):
        if command == ('connection', '-getport', '-address', '-vlanid'):
            return self.testData.ALL_PORTS
        elif command == ('storagepool', '-list', '-state'):
            return self.testData.POOL_GET_STATE_RESULT([
                {'pool_name': self.testData.test_pool_name, 'state': "Ready"},
                {'pool_name': "unit_test_pool2", 'state': "Ready"},
                {'pool_name': "unit_test_pool3", 'state': "Ready"},
                {'pool_name': "unit_text_pool4", 'state': "Ready"}])
        else:
            return SUCCEED

    def test_storage_pool_names_option(self):
        self.configuration.safe_get = self.fake_safe_get(
            {'storage_vnx_pool_names': "unit_test_pool, unit_test_pool3",
             'volume_backend_name': 'namedbackend'})

        driver = self.generate_driver(self.configuration)
        self.assertEqual(set(["unit_test_pool", "unit_test_pool3"]),
                         driver.cli.storage_pools)

        self.configuration.safe_get = self.fake_safe_get(
            {'storage_vnx_pool_names': "unit_test_pool2,",
             'volume_backend_name': 'namedbackend'})
        driver = self.generate_driver(self.configuration)
        self.assertEqual(set(["unit_test_pool2"]),
                         driver.cli.storage_pools)

        self.configuration.safe_get = self.fake_safe_get(
            {'storage_vnx_pool_names': "unit_test_pool3",
             'volume_backend_name': 'namedbackend'})
        driver = self.generate_driver(self.configuration)
        self.assertEqual(set(["unit_test_pool3"]),
                         driver.cli.storage_pools)

    def test_configured_pool_does_not_exist(self):
        self.configuration.safe_get = self.fake_safe_get(
            {'storage_vnx_pool_names': "unit_test_pool2, unit_test_pool_none2",
             'volume_backend_name': 'namedbackend'})
        driver = self.generate_driver(self.configuration)
        self.assertEqual(set(["unit_test_pool2"]),
                         driver.cli.storage_pools)

        self.configuration.safe_get = self.fake_safe_get(
            {'storage_vnx_pool_names': "unit_test_pool_none1",
             "unit_test_pool_none2"
             'volume_backend_name': 'namedbackend'})
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.generate_driver,
                          self.configuration)

    def test_no_storage_pool_is_configured(self):
        self.configuration.safe_get = self.fake_safe_get(
            {'storage_vnx_pool_names': None,
             'volume_backend_name': 'namedbackend'})
        driver = self.generate_driver(self.configuration)
        self.assertEqual(set(),
                         driver.cli.storage_pools)

VNXError = emc_vnx_cli.VNXError


class VNXErrorTest(test.TestCase):

    def test_has_error(self):
        output = "The specified snapshot name is already in use. (0x716d8005)"
        self.assertTrue(VNXError.has_error(output))

    def test_has_error_with_specific_error(self):
        output = "The specified snapshot name is already in use. (0x716d8005)"
        has_error = VNXError.has_error(output, VNXError.SNAP_NAME_EXISTED)
        self.assertTrue(has_error)

        has_error = VNXError.has_error(output, VNXError.LUN_ALREADY_EXPANDED)
        self.assertFalse(has_error)

    def test_has_error_not_found(self):
        output = "Cannot find the consistency group."
        has_error = VNXError.has_error(output)
        self.assertTrue(has_error)

        has_error = VNXError.has_error(output, VNXError.GENERAL_NOT_FOUND)
        self.assertTrue(has_error)

    def test_has_error_not_exist(self):
        output = "The specified snapshot does not exist."
        has_error = VNXError.has_error(output, VNXError.GENERAL_NOT_FOUND)
        self.assertTrue(has_error)

        output = "The (pool lun) may not exist."
        has_error = VNXError.has_error(output, VNXError.GENERAL_NOT_FOUND)
        self.assertTrue(has_error)

    def test_has_error_multi_line(self):
        output = """Could not retrieve the specified (pool lun).
                    The (pool lun) may not exist."""
        has_error = VNXError.has_error(output, VNXError.GENERAL_NOT_FOUND)
        self.assertTrue(has_error)

    def test_has_error_regular_string_false(self):
        output = "Cannot unbind LUN because it's contained in a Storage Group."
        has_error = VNXError.has_error(output, VNXError.GENERAL_NOT_FOUND)
        self.assertFalse(has_error)

    def test_has_error_multi_errors(self):
        output = "Cannot unbind LUN because it's contained in a Storage Group."
        has_error = VNXError.has_error(output,
                                       VNXError.LUN_IN_SG,
                                       VNXError.GENERAL_NOT_FOUND)
        self.assertTrue(has_error)

        output = "Cannot unbind LUN because it's contained in a Storage Group."
        has_error = VNXError.has_error(output,
                                       VNXError.LUN_ALREADY_EXPANDED,
                                       VNXError.LUN_NOT_MIGRATING)
        self.assertFalse(has_error)
