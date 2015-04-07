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

from cinder import exception
from cinder import test
from cinder.tests import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.emc import emc_cli_fc
from cinder.volume.drivers.emc import emc_cli_iscsi
from cinder.volume.drivers.emc import emc_vnx_cli
from cinder.zonemanager import fc_san_lookup_service as fc_service


SUCCEED = ("", 0)
FAKE_ERROR_RETURN = ("FAKE ERROR", 255)
VERSION = emc_vnx_cli.EMCVnxCliBase.VERSION


class EMCVNXCLIDriverTestData(object):

    test_volume = {
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
        'consistencygroup_id': None,
        'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}]
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
        'consistencygroup_id': None,
        'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}]
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
        'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}]
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
        'consistencygroup_id': 'cg_id',
        'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}]
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
        'volume_admin_metadata': [{'key': 'attached_mode', 'value': 'rw'},
                                  {'key': 'readonly', 'value': 'False'}],
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
        'volume_type_id': None}

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
        'volume_type_id': 'abc1-2320-9013-8813-8941-1374-8112-1231'}

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
        'volume_type_id': None}
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
        'volume_type_id': None}
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
        'volume_admin_metadata': [],
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
                    'size': 2L,
                    'volume_admin_metadata': [],
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
                    'volume_admin_metadata': [],
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
    test_existing_ref = {'id': test_lun_id}
    test_pool_name = 'unit_test_pool'
    device_map = {
        '1122334455667788': {
            'initiator_port_wwn_list': ['123456789012345', '123456789054321'],
            'target_port_wwn_list': ['1122334455667777']}}
    i_t_map = {'123456789012345': ['1122334455667777'],
               '123456789054321': ['1122334455667777']}

    POOL_PROPERTY_CMD = ('storagepool', '-list', '-name', 'unit_test_pool',
                         '-userCap', '-availableCap')

    POOL_PROPERTY_W_FASTCACHE_CMD = ('storagepool', '-list', '-name',
                                     'unit_test_pool', '-availableCap',
                                     '-userCap', '-fastcache')

    def POOL_GET_ALL_CMD(self, withfastcache=False):
        if withfastcache:
            return ('storagepool', '-list', '-availableCap',
                    '-userCap', '-fastcache')
        else:
            return ('storagepool', '-list', '-availableCap',
                    '-userCap')

    def POOL_GET_ALL_RESULT(self, withfastcache=False):
        if withfastcache:
            return ("Pool Name:  unit_test_pool1\n"
                    "Pool ID:  0\n"
                    "User Capacity (Blocks):  6881061888\n"
                    "User Capacity (GBs):  3281.146\n"
                    "Available Capacity (Blocks):  6512292864\n"
                    "Available Capacity (GBs):  3105.303\n"
                    "FAST Cache:  Enabled\n"
                    "\n"
                    "Pool Name:  unit test pool 2\n"
                    "Pool ID:  1\n"
                    "User Capacity (Blocks):  8598306816\n"
                    "User Capacity (GBs):  4099.992\n"
                    "Available Capacity (Blocks):  8356663296\n"
                    "Available Capacity (GBs):  3984.768\n"
                    "FAST Cache:  Disabled\n", 0)
        else:
            return ("Pool Name:  unit_test_pool1\n"
                    "Pool ID:  0\n"
                    "User Capacity (Blocks):  6881061888\n"
                    "User Capacity (GBs):  3281.146\n"
                    "Available Capacity (Blocks):  6512292864\n"
                    "Available Capacity (GBs):  3105.303\n"
                    "\n"
                    "Pool Name:  unit test pool 2\n"
                    "Pool ID:  1\n"
                    "User Capacity (Blocks):  8598306816\n"
                    "User Capacity (GBs):  4099.992\n"
                    "Available Capacity (Blocks):  8356663296\n"
                    "Available Capacity (GBs):  3984.768\n", 0)

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
            return ('storagegroup', '-list', '-gname', gname)
        else:
            return ('storagegroup', '-list')

    def STORAGEGROUP_REMOVEHLU_CMD(self, gname, hlu):
        return ('storagegroup', '-removehlu',
                '-hlu', hlu, '-gname', gname, '-o')

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
                         poll=True):
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
        return tuple(initial)

    def CHECK_FASTCACHE_CMD(self, storage_pool):
        return ('storagepool', '-list', '-name',
                storage_pool, '-fastcache')

    def CREATE_CONSISTENCYGROUP_CMD(self, cg_name):
        return ('-np', 'snap', '-group', '-create',
                '-name', cg_name, '-allowSnapAutoDelete', 'no')

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

    POOL_PROPERTY = ("""\
Pool Name:  unit_test_pool
Pool ID:  1
User Capacity (Blocks):  6881061888
User Capacity (GBs):  3281.146
Available Capacity (Blocks):  6832207872
Available Capacity (GBs):  3257.851

""", 0)

    POOL_PROPERTY_W_FASTCACHE = (
        "Pool Name:  unit_test_pool\n"
        "Pool ID:  1\n"
        "User Capacity (Blocks):  6881061888\n"
        "User Capacity (GBs):  3281.146\n"
        "Available Capacity (Blocks):  6832207872\n"
        "Available Capacity (GBs):  3257.851\n"
        "FAST Cache:  Enabled\n\n", 0)

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
                  'target_lun': 2,
                  'target_portal': '10.244.214.118:3260',
                  'volume_id': '1'},
         'driver_volume_type': 'iscsi'}

    iscsi_connection_info_rw = \
        {'data': {'access_mode': 'rw',
                  'target_discovered': True,
                  'target_iqn':
                  'iqn.1992-04.com.emc:cx.fnm00124000215.a4',
                  'target_lun': 2,
                  'target_portal': '10.244.214.118:3260',
                  'volume_id': '1'},
         'driver_volume_type': 'iscsi'}

    iscsi_connection_info_mp = \
        {'data': {'access_mode': 'rw',
                  'target_discovered': True,
                  'target_iqns': [
                      'iqn.1992-04.com.emc:cx.fnm00124000215.a4',
                      'iqn.1992-04.com.emc:cx.fnm00124000215.a5'],
                  'target_luns': [2, 2],
                  'target_portals': [
                      '10.244.214.118:3260',
                      '10.244.214.119:3260'],
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

    def LUN_PROPERTY(self, name, is_thin=False, has_snap=False, size=1,
                     state='Ready', faulted='false', operation='None'):
        return ("""
               LOGICAL UNIT NUMBER 1
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
               Pool Name:  unit_test_pool
               Current State:  %(state)s
               Status:  OK(0x0)
               Is Faulted:  %(faulted)s
               Is Transitioning:  false
               Current Operation:  %(operation)s
               Current Operation State:  N/A
               Current Operation Status:  N/A
               Current Operation Percent Completed:  0
               Is Thin LUN:  %(is_thin)s""" % {
            'name': name,
            'has_snap': 'FakeSnap' if has_snap else 'N/A',
            'size': size,
            'state': state,
            'faulted': faulted,
            'operation': operation,
            'is_thin': 'Yes' if is_thin else 'No'}, 0)

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

    def STORAGE_GROUP_HAS_MAP_MP(self, sgname):

        return ("""\
        Storage Group Name:    %s
        Storage Group UID:     54:46:57:0F:15:A2:E3:11:9A:8D:FF:E5:3A:03:FD:6D
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:222                     SP A         4
          iqn.1993-08.org.debian:01:222                     SP A         5

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

        Storage Group Name:    %(sgname1)s
        Storage Group UID:     54:46:57:0F:15:A2:E3:11:9A:8D:FF:E5:3A:03:FD:6D
        HBA/SP Pairs:

          HBA UID                                          SP Name     SPPort
          -------                                          -------     ------
          iqn.1993-08.org.debian:01:222                     SP A         4

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
        self.stubs.Set(emc_vnx_cli, 'INTERVAL_60_SEC', 0.01)

        self.configuration = conf.Configuration(None)
        self.configuration.append_config_values = mock.Mock(return_value=0)
        self.configuration.naviseccli_path = '/opt/Navisphere/bin/naviseccli'
        self.configuration.san_ip = '10.0.0.1'
        self.configuration.storage_vnx_pool_name = 'unit_test_pool'
        self.configuration.san_login = 'sysadmin'
        self.configuration.san_password = 'sysadmin'
        # set the timeout to 0.012s = 0.0002 * 60 = 1.2ms
        self.configuration.default_timeout = 0.0002
        self.configuration.initiator_auto_registration = True
        self.configuration.check_max_pool_luns_threshold = False
        self.stubs.Set(self.configuration, 'safe_get',
                       self.fake_safe_get({'storage_vnx_pool_name':
                                           'unit_test_pool',
                                           'volume_backend_name':
                                           'namedbackend'}))
        self.testData = EMCVNXCLIDriverTestData()
        self.navisecclicmd = '/opt/Navisphere/bin/naviseccli ' + \
            '-address 10.0.0.1 -user sysadmin -password sysadmin -scope 0 '
        self.configuration.iscsi_initiators = '{"fakehost": ["10.0.0.2"]}'

    def driverSetup(self, commands=tuple(), results=tuple()):
        self.driver = self.generateDriver(self.configuration)
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.Mock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli
        return fake_cli

    def generateDriver(self, conf):
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
        if command == ('connection', '-getport', '-address', '-vlanid'):
            return self.testData.ALL_PORTS
        else:
            return SUCCEED

    def fake_safe_get(self, values):
        def _safe_get(key):
            return values.get(key)
        return _safe_get


class EMCVNXCLIDriverISCSITestCase(DriverTestCaseBase):
    def generateDriver(self, conf):
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
                'thick', None, False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                      poll=False),
            mock.call(*self.testData.LUN_DELETE_CMD('vol1'))]

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
                'compressed', None, False)),
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
                'compressed', 'highestavailable', False)),
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
                'deduplicated', None, False))]
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
                None, 'auto', False))]
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

    def test_get_volume_stats(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_PROPERTY_W_FASTCACHE_CMD]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_PROPERTY_W_FASTCACHE]
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
            'free_capacity_gb': 3257.851,
            'reserved_percentage': 3,
            'location_info': 'unit_test_pool|fakeSerial',
            'total_capacity_gb': 3281.146,
            'compression_support': 'True',
            'deduplication_support': 'True',
            'thinprovisioning_support': 'True',
            'consistencygroup_support': 'True',
            'pool_name': 'unit_test_pool',
            'fast_cache_enabled': 'True',
            'fast_support': 'True'}

        self.assertEqual(expected_pool_stats, pool_stats)

    def test_get_volume_stats_too_many_luns(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_PROPERTY_W_FASTCACHE_CMD,
                    self.testData.POOL_FEATURE_INFO_POOL_LUNS_CMD()]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_PROPERTY_W_FASTCACHE,
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
            pool_stats['free_capacity_gb'] == 3257.851,
            "free_capacity_gb is incorrect")

    @mock.patch("cinder.volume.drivers.emc.emc_vnx_cli."
                "CommandLineHelper.create_lun_by_cmd",
                mock.Mock(return_value={'lun_id': 1}))
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
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase."
        "get_lun_id_by_name",
        mock.Mock(return_value=5))
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
    @mock.patch(
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase."
        "get_lun_id_by_name",
        mock.Mock(return_value=1))
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

        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
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
        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
                    self.testData.PINGNODE_CMD('A', 4, 0, '10.0.0.2')]
        results = [[("No group", 83),
                    self.testData.STORAGE_GROUP_HAS_MAP('fakehost')],
                   self.testData.PING_OK]

        fake_cli = self.driverSetup(commands, results)

        connection_info = self.driver.initialize_connection(
            self.testData.test_volume,
            self.testData.connector)

        self.assertEqual(self.testData.iscsi_connection_info_ro,
                         connection_info)

        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-gname', 'fakehost', '-setpath',
                              '-hbauid', 'iqn.1993-08.org.debian:01:222',
                              '-sp', 'A', '-spport', 4, '-spvport', 0,
                              '-ip', '10.0.0.2', '-host', 'fakehost', '-o'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost',
                              poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False),
                    mock.call(*self.testData.PINGNODE_CMD('A', 4, 0,
                                                          '10.0.0.2'))]
        fake_cli.assert_has_calls(expected)

        # Test for manual registration
        self.configuration.initiator_auto_registration = False

        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
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

        self.assertEqual(self.testData.iscsi_connection_info_rw,
                         connection_info)

        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False),
                    mock.call(*self.testData.PINGNODE_CMD('A', 4, 0,
                                                          '10.0.0.2'))]
        fake_cli.assert_has_calls(expected)

        # Test No Ping
        self.configuration.iscsi_initiators = None

        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
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

        self.assertEqual(self.testData.iscsi_connection_info_rw,
                         connection_info)

        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False)]
        fake_cli.assert_has_calls(expected)

    @mock.patch('random.randint',
                mock.Mock(return_value=0))
    def test_initialize_connection_multipath(self):
        self.configuration.initiator_auto_registration = False

        commands = [('storagegroup', '-list', '-gname', 'fakehost')]
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
                 'Virtual Port ID': 1,
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

        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost', poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False)]
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
        """A LUN is added to the SG right before the attach,
        it may not exists in the first SG query
        """
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        self.configuration.max_luns_per_storage_group = 2
        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
                    ('storagegroup', '-addhlu', '-hlu', 2, '-alu', 3,
                     '-gname', 'fakehost'),
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
        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 3,
                              '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                              poll=False),
                    mock.call(*self.testData.PINGNODE_CMD('A', 4, 0,
                                                          '10.0.0.2'))]
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
    def test_initialize_connection_no_hlu_left_1(self):
        """There is no hlu per the first SG query
        But there are hlu left after the full poll
        """
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        self.configuration.max_luns_per_storage_group = 2
        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
                    ('storagegroup', '-addhlu', '-hlu', 2, '-alu', 4,
                     '-gname', 'fakehost'),
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
        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 4,
                              '-gname', 'fakehost',
                              poll=False),
                    mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
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
        """There is no usable hlu for the SG
        """
        # Test for auto registration
        self.configuration.initiator_auto_registration = True
        self.configuration.max_luns_per_storage_group = 2
        commands = [('storagegroup', '-list', '-gname', 'fakehost')]
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
            mock.call('storagegroup', '-list', '-gname', 'fakehost',
                      poll=False),
            mock.call('storagegroup', '-list', '-gname', 'fakehost',
                      poll=True),
        ]
        fake_cli.assert_has_calls(expected)

    def test_terminate_connection(self):

        os.path.exists = mock.Mock(return_value=1)
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
#         expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost'),
#                     mock.call('lun', '-list', '-name', 'vol1'),
#                     mock.call('storagegroup', '-list', '-gname', 'fakehost'),
#                     mock.call('lun', '-list', '-l', '10', '-owner')]

    def test_create_volume_cli_failed(self):
        commands = [self.testData.LUN_CREATION_CMD(
            'failed_vol1', 1, 'unit_test_pool', None, None, False)]
        results = [FAKE_ERROR_RETURN]
        fake_cli = self.driverSetup(commands, results)

        self.assertRaises(exception.EMCVnxCLICmdError,
                          self.driver.create_volume,
                          self.testData.test_failed_volume)
        expect_cmd = [mock.call(*self.testData.LUN_CREATION_CMD(
            'failed_vol1', 1, 'unit_test_pool', None, None, False))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch('cinder.openstack.common.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_create_faulted_volume(self):
        volume_name = 'faulted_volume'
        cmd_create = self.testData.LUN_CREATION_CMD(
            volume_name, 1, 'unit_test_pool', None, None, False)
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
                volume_name, 1, 'unit_test_pool', None, None, False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(volume_name),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(volume_name),
                      poll=False)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch('cinder.openstack.common.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_create_offline_volume(self):
        volume_name = 'offline_volume'
        cmd_create = self.testData.LUN_CREATION_CMD(
            volume_name, 1, 'unit_test_pool', None, None, False)
        cmd_list = self.testData.LUN_PROPERTY_ALL_CMD(volume_name)
        commands = [cmd_create, cmd_list]
        results = [SUCCEED,
                   self.testData.LUN_PROPERTY(name=volume_name,
                                              state='Offline',
                                              faulted='true')]
        self.driverSetup(commands, results)
        offline_volume = self.testData.test_volume.copy()
        offline_volume.update({'name': volume_name})
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
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
        fake_cli = self.driverSetup(commands, results)

        self.driver.create_volume_from_snapshot(self.testData.test_volume2,
                                                self.testData.test_snapshot)
        expect_cmd = [
            mock.call(
                *self.testData.SNAP_MP_CREATE_CMD(
                    name='vol2', source='vol1'),
                poll=False),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='snapshot1')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2'),
                      poll=True),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      retry_disable=True,
                      poll=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=True)]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch('cinder.openstack.common.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
    def test_create_volume_from_snapshot_sync_failed(self):

        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        cmd_dest_np = self.testData.LUN_PROPERTY_ALL_CMD("vol2_dest")
        output_dest = self.testData.LUN_PROPERTY("vol2_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        cmd_detach_lun = ('lun', '-detach', '-name', 'vol2')
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
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='snapshot1')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2'),
                      poll=True),
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
        cmd_detach_lun = ('lun', '-detach', '-name', 'vol2')
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
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='snapshot1')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2'), poll=True),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      poll=True,
                      retry_disable=True),
            mock.call(*self.testData.LUN_DELETE_CMD('vol2_dest')),
            mock.call(*cmd_detach_lun),
            mock.call(*self.testData.LUN_DELETE_CMD('vol2'))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_create_cloned_volume(self):
        cmd_dest = self.testData.LUN_PROPERTY_ALL_CMD("vol1_dest")
        cmd_dest_p = self.testData.LUN_PROPERTY_ALL_CMD("vol1_dest")
        output_dest = self.testData.LUN_PROPERTY("vol1_dest")
        cmd_migrate = self.testData.MIGRATION_CMD(1, 1)
        output_migrate = ("", 0)
        cmd_migrate_verify = self.testData.MIGRATION_VERIFY_CMD(1)
        output_migrate_verify = (r'The specified source LUN '
                                 'is not currently migrating', 23)
        commands = [cmd_dest, cmd_dest_p, cmd_migrate,
                    cmd_migrate_verify]
        results = [output_dest, output_dest, output_migrate,
                   output_migrate_verify]
        fake_cli = self.driverSetup(commands, results)

        self.driver.create_cloned_volume(self.testData.test_volume,
                                         self.testData.test_snapshot)
        tmp_snap = 'tmp-snap-' + self.testData.test_volume['id']
        expect_cmd = [
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('snapshot1'),
                      poll=True),
            mock.call(
                *self.testData.SNAP_CREATE_CMD(tmp_snap), poll=False),
            mock.call(*self.testData.SNAP_MP_CREATE_CMD(
                name='vol1',
                source='snapshot1'), poll=False),
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol1', snapName=tmp_snap)),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol1_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'),
                      poll=True),
            mock.call(*self.testData.MIGRATION_CMD(1, 1),
                      poll=True,
                      retry_disable=True),
            mock.call(*self.testData.MIGRATION_VERIFY_CMD(1),
                      poll=True),
            mock.call(*self.testData.SNAP_DELETE_CMD(tmp_snap),
                      poll=True)]
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

    @mock.patch('cinder.openstack.common.loopingcall.FixedIntervalLoopingCall',
                new=utils.ZeroIntervalLoopingCall)
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
                *self.testData.LUN_EXTEND_CMD('failed_vol1', 3),
                poll=False),
            mock.call(
                *self.testData.LUN_PROPERTY_ALL_CMD('failed_vol1'),
                poll=False)]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing(self):
        lun_rename_cmd = ('lun', '-modify', '-l', self.testData.test_lun_id,
                          '-newName', 'vol_with_type', '-o')
        commands = [lun_rename_cmd]

        results = [SUCCEED]
        self.configuration.storage_vnx_pool_name = \
            self.testData.test_pool_name
        self.driver = emc_cli_iscsi.EMCCLIISCSIDriver(
            configuration=self.configuration)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliPool)
        # mock the command executor
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.MagicMock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli
        self.driver.manage_existing(
            self.testData.test_volume_with_type,
            self.testData.test_existing_ref)
        expected = [mock.call(*lun_rename_cmd, poll=False)]
        fake_cli.assert_has_calls(expected)

    def test_manage_existing_lun_in_another_pool(self):
        get_lun_cmd = ('lun', '-list', '-l', self.testData.test_lun_id,
                       '-state', '-userCap', '-owner',
                       '-attachedSnapshot', '-poolName')
        commands = [get_lun_cmd]

        results = [self.testData.LUN_PROPERTY('lun_name')]
        invalid_pool_name = "fake_pool"
        self.configuration.storage_vnx_pool_name = invalid_pool_name
        self.driver = emc_cli_iscsi.EMCCLIISCSIDriver(
            configuration=self.configuration)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliPool)
        # mock the command executor
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.MagicMock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli
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
        self.driver = emc_cli_iscsi.EMCCLIISCSIDriver(
            configuration=self.configuration)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliPool)

        # mock the command executor
        fake_command_execute = self.get_command_execute_simulator(
            commands, results)
        fake_cli = mock.MagicMock(side_effect=fake_command_execute)
        self.driver.cli._client.command_execute = fake_cli

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
        "cinder.volume.drivers.emc.emc_vnx_cli.EMCVnxCliBase."
        "get_lun_id_by_name",
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
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol3-123456'),
                      poll=False),
            mock.call(*self.testData.MIGRATION_CMD(1, None),
                      retry_disable=True,
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
        "eventlet.event.Event.wait",
        mock.Mock(return_value=None))
    @mock.patch(
        "time.time",
        mock.Mock(return_value=123456))
    @mock.patch(
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'storagetype:provisioning': 'thin'}))
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

        self.driver.retype(None, self.testData.test_volume3,
                           new_type_data,
                           diff_data,
                           host_test_data)
        expect_cmd = [
            mock.call(*self.testData.SNAP_LIST_CMD(), poll=False),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol3-123456', 2, 'unit_test_pool', 'compressed', 'auto')),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(1)),
            mock.call(*self.testData.MIGRATION_CMD(),
                      retry_disable=True,
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
        "cinder.volume.volume_types."
        "get_volume_type_extra_specs",
        mock.Mock(return_value={'fast_cache_enabled': 'True'}))
    def test_create_volume_with_fastcache(self):
        """Enable fastcache when creating volume."""
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

        self.configuration.storage_vnx_pool_name = \
            self.testData.test_pool_name
        self.driver = emc_cli_iscsi.EMCCLIISCSIDriver(
            configuration=self.configuration)
        assert isinstance(self.driver.cli, emc_vnx_cli.EMCVnxCliPool)

        cli_helper = self.driver.cli._client
        cli_helper.command_execute = fake_cli
        cli_helper.get_lun_by_name = mock.Mock(return_value=lun_info)
        cli_helper.get_enablers_on_array = mock.Mock(return_value="-FASTCache")
        cli_helper.get_pool = mock.Mock(return_value={
            'lun_nums': 1000,
            'total_capacity_gb': 10,
            'free_capacity_gb': 5,
            'pool_name': "unit_test_pool",
            'fast_cache_enabled': 'True'})

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
            'volume_type_id': None,
            'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}]}
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
            'volume_type_id': None,
            'volume_admin_metadata': [{'key': 'readonly', 'value': 'True'}]}
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
                    cg_name))]
        fake_cli.assert_has_calls(expect_cmd)

    @mock.patch(
        "cinder.volume.volume_types.get_volume_type_extra_specs",
        mock.Mock(side_effect=[{'storagetype:provisioning': 'thin'},
                               {'storagetype:provisioning': 'compressed'}]))
    def test_create_consistency_group_failed_with_compression(self):
        self.driverSetup([], [])
        self.assertRaisesRegexp(exception.VolumeBackendAPIException,
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

    def test_create_cgsnapshot(self):
        cgsnapshot = self.testData.test_cgsnapshot['id']
        cg_name = self.testData.test_cgsnapshot['consistencygroup_id']
        commands = [self.testData.CREATE_CG_SNAPSHOT(cg_name, cgsnapshot)]
        results = [SUCCEED]
        fake_cli = self.driverSetup(commands, results)
        self.driver.db = mock.MagicMock()
        self.driver.db.volume_get_all_by_group.return_value =\
            self.testData.SNAPS_IN_SNAP_GROUP()
        self.driver.create_cgsnapshot(None, self.testData.test_cgsnapshot)
        expect_cmd = [
            mock.call(
                *self.testData.CREATE_CG_SNAPSHOT(
                    cg_name, cgsnapshot))]
        fake_cli.assert_has_calls(expect_cmd)

    def test_delete_cgsnapshot(self):
        snap_name = self.testData.test_cgsnapshot['id']
        commands = [self.testData.DELETE_CG_SNAPSHOT(snap_name)]
        results = [SUCCEED]
        fake_cli = self.driverSetup(commands, results)
        self.driver.db = mock.MagicMock()
        self.driver.db.snapshot_get_all_for_cgsnapshot.return_value =\
            self.testData.SNAPS_IN_SNAP_GROUP()
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
                    self.testData.GET_CG_BY_NAME_CMD('cg_id')
                    ]
        results = [self.testData.LUN_PROPERTY('vol1', True),
                   SUCCEED,
                   self.testData.CG_PROPERTY('cg_id')]
        fake_cli = self.driverSetup(commands, results)

        self.driver.create_volume(self.testData.test_volume_cg)

        expect_cmd = [
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol1', 1,
                'unit_test_pool',
                None, None, False)),
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
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol1', snapName=tmp_cgsnapshot)),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol1_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol1'), poll=True),
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
            mock.call(
                *self.testData.SNAP_ATTACH_CMD(
                    name='vol2', snapName='cgsnapshot_id')),
            mock.call(*self.testData.LUN_CREATION_CMD(
                'vol2_dest', 1, 'unit_test_pool', None, None)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2_dest'),
                      poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD('vol2'),
                      poll=True),
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


class EMCVNXCLIDArrayBasedDriverTestCase(DriverTestCaseBase):
    def setUp(self):
        super(EMCVNXCLIDArrayBasedDriverTestCase, self).setUp()
        self.configuration.safe_get = self.fake_safe_get(
            {'storage_vnx_pool_name': None,
             'volume_backend_name': 'namedbackend'})

    def generateDriver(self, conf):
        driver = emc_cli_iscsi.EMCCLIISCSIDriver(configuration=conf)
        self.assertTrue(isinstance(driver.cli,
                                   emc_vnx_cli.EMCVnxCliArray))
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
            'reserved_percentage': 2,
            'location_info': 'unit_test_pool1|fakeSerial',
            'total_capacity_gb': 3281.146,
            'compression_support': 'True',
            'deduplication_support': 'True',
            'thinprovisioning_support': 'True',
            'consistencygroup_support': 'True',
            'pool_name': 'unit_test_pool1',
            'fast_cache_enabled': 'True',
            'fast_support': 'True'}
        self.assertEqual(expected_pool_stats1, pool_stats1)

        pool_stats2 = stats['pools'][1]
        expected_pool_stats2 = {
            'free_capacity_gb': 3984.768,
            'reserved_percentage': 2,
            'location_info': 'unit test pool 2|fakeSerial',
            'total_capacity_gb': 4099.992,
            'compression_support': 'True',
            'deduplication_support': 'True',
            'thinprovisioning_support': 'True',
            'consistencygroup_support': 'True',
            'pool_name': 'unit test pool 2',
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
            'reserved_percentage': 2,
            'location_info': 'unit_test_pool1|fakeSerial',
            'total_capacity_gb': 3281.146,
            'compression_support': 'False',
            'deduplication_support': 'False',
            'thinprovisioning_support': 'False',
            'consistencygroup_support': 'False',
            'pool_name': 'unit_test_pool1',
            'fast_cache_enabled': 'False',
            'fast_support': 'False'}
        self.assertEqual(expected_pool_stats1, pool_stats1)

        pool_stats2 = stats['pools'][1]
        expected_pool_stats2 = {
            'free_capacity_gb': 3984.768,
            'reserved_percentage': 2,
            'location_info': 'unit test pool 2|fakeSerial',
            'total_capacity_gb': 4099.992,
            'compression_support': 'False',
            'deduplication_support': 'False',
            'thinprovisioning_support': 'False',
            'consistencygroup_support': 'False',
            'pool_name': 'unit test pool 2',
            'fast_cache_enabled': 'False',
            'fast_support': 'False'}
        self.assertEqual(expected_pool_stats2, pool_stats2)

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
                'deduplicated', None, False)),
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
                'compressed', None, False)),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=False),
            mock.call(*self.testData.LUN_PROPERTY_ALL_CMD(
                'vol_with_type'), poll=True),
            mock.call(*self.testData.ENABLE_COMPRESSION_CMD(
                1))]
        fake_cli.assert_has_calls(expect_cmd)


class EMCVNXCLIDriverFCTestCase(DriverTestCaseBase):
    def generateDriver(self, conf):
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
        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
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

        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('port', '-list', '-sp'),
                    mock.call('storagegroup', '-gname', 'fakehost',
                              '-setpath', '-hbauid',
                              '22:34:56:78:90:12:34:56:12:34:56:78:'
                              '90:12:34:56',
                              '-sp', 'A', '-spport', '0', '-ip', '10.0.0.2',
                              '-host', 'fakehost', '-o'),
                    mock.call('storagegroup', '-gname', 'fakehost',
                              '-setpath', '-hbauid',
                              '22:34:56:78:90:54:32:16:12:34:56:78:'
                              '90:54:32:16',
                              '-sp', 'A', '-spport', '0', '-ip', '10.0.0.2',
                              '-host', 'fakehost', '-o'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 2, '-alu', 1,
                              '-gname', 'fakehost',
                              poll=False),
                    mock.call('port', '-list', '-gname', 'fakehost')
                    ]
        fake_cli.assert_has_calls(expected)

        # Test for manaul registration
        self.configuration.initiator_auto_registration = False

        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
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

        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 1, '-alu', 1,
                              '-gname', 'fakehost', poll=False),
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
        commands = [('storagegroup', '-list', '-gname', 'fakehost'),
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
        expected = [mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-create', '-gname', 'fakehost'),
                    mock.call('storagegroup', '-connecthost',
                              '-host', 'fakehost', '-gname', 'fakehost', '-o'),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call('storagegroup', '-addhlu', '-hlu', 1, '-alu', 1,
                              '-gname', 'fakehost',
                              poll=False),
                    mock.call('storagegroup', '-list', '-gname', 'fakehost',
                              poll=True),
                    mock.call('port', '-list', '-sp')]
        fake_cli.assert_has_calls(expected)

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
                    self.testData.POOL_PROPERTY_W_FASTCACHE_CMD]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_PROPERTY_W_FASTCACHE]
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
            'free_capacity_gb': 3257.851,
            'reserved_percentage': 3,
            'location_info': 'unit_test_pool|fakeSerial',
            'total_capacity_gb': 3281.146,
            'compression_support': 'True',
            'deduplication_support': 'True',
            'thinprovisioning_support': 'True',
            'consistencygroup_support': 'True',
            'pool_name': 'unit_test_pool',
            'fast_cache_enabled': 'True',
            'fast_support': 'True'}

        self.assertEqual(expected_pool_stats, pool_stats)

    def test_get_volume_stats_too_many_luns(self):
        commands = [self.testData.NDU_LIST_CMD,
                    self.testData.POOL_PROPERTY_W_FASTCACHE_CMD,
                    self.testData.POOL_FEATURE_INFO_POOL_LUNS_CMD()]
        results = [self.testData.NDU_LIST_RESULT,
                   self.testData.POOL_PROPERTY_W_FASTCACHE,
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
            pool_stats['free_capacity_gb'] == 3257.851,
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
