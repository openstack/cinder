# Copyright (c) 2014 ProphetStor, Inc.
# All Rights Reserved.
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

import copy
import errno
import httplib
import re

import mock
from oslo_utils import units

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.prophetstor import dpl_iscsi as DPLDRIVER
from cinder.volume.drivers.prophetstor import dplcommon as DPLCOMMON

POOLUUID = 'ac33fc6e417440d5a1ef27d7231e1cc4'
VOLUMEUUID = 'a000000000000000000000000000001'
INITIATOR = 'iqn.2013-08.org.debian:01:aaaaaaaa'
DATA_IN_VOLUME = {'id': VOLUMEUUID}
DATA_IN_CONNECTOR = {'initiator': INITIATOR}
DATA_SERVER_INFO = 0, {
    'metadata': {'vendor': 'ProphetStor',
                 'version': '1.5'}}

DATA_POOLS = 0, {
    'children': [POOLUUID]
}

DATA_POOLINFO = 0, {
    'capabilitiesURI': '',
    'children': [],
    'childrenrange': '',
    'completionStatus': 'Complete',
    'metadata': {'available_capacity': 4294967296,
                 'ctime': 1390551362349,
                 'vendor': 'prophetstor',
                 'version': '1.5',
                 'display_description': 'Default Pool',
                 'display_name': 'default_pool',
                 'event_uuid': '4f7c4d679a664857afa4d51f282a516a',
                 'physical_device': {'cache': [],
                                     'data': ['disk_uuid_0',
                                              'disk_uuid_1',
                                              'disk_uuid_2'],
                                     'log': [],
                                     'spare': []},
                 'pool_uuid': POOLUUID,
                 'properties': {'raid_level': 'raid0'},
                 'state': 'Online',
                 'used_capacity': 0,
                 'total_capacity': 4294967296,
                 'zpool_guid': '8173612007304181810'},
    'objectType': 'application/cdmi-container',
    'percentComplete': 100}

DATA_ASSIGNVDEV = 0, {
    'children': [],
    'childrenrange': '',
    'completionStatus': 'Complete',
    'domainURI': '',
    'exports': {'Network/iSCSI': [
                {'logical_unit_name': '',
                 'logical_unit_number': '101',
                 'permissions': [INITIATOR],
                 'portals': ['172.31.1.210:3260'],
                 'target_identifier':
                 'iqn.2013-09.com.prophetstor:hypervisor.886423051816'
                 }]},
    'metadata': {'ctime': 0,
                 'event_uuid': 'c11e90287e9348d0b4889695f1ec4be5',
                 'type': 'volume'},
    'objectID': '',
    'objectName': 'd827e23d403f4f12bb208a6fec208fd8',
    'objectType': 'application/cdmi-container',
    'parentID': '8daa374670af447e8efea27e16bf84cd',
    'parentURI': '/dpl_volume',
    'snapshots': []
}

DATA_OUTPUT = 0, None

MOD_OUTPUT = {'status': 'available'}

DATA_IN_GROUP = {'id': 'fe2dbc51-5810-451d-ab2f-8c8a48d15bee',
                 'name': 'group123',
                 'description': 'des123',
                 'status': ''}

DATA_IN_VOLUME = {'id': 'abc123',
                  'display_name': 'abc123',
                  'display_description': '',
                  'size': 1,
                  'host': "hostname@backend#%s" % POOLUUID}

DATA_IN_VOLUME_VG = {'id': 'abc123',
                     'display_name': 'abc123',
                     'display_description': '',
                     'size': 1,
                     'consistencygroup_id':
                         'fe2dbc51-5810-451d-ab2f-8c8a48d15bee',
                     'status': 'available',
                     'host': "hostname@backend#%s" % POOLUUID}

DATA_IN_VOLUME1 = {'id': 'abc456',
                   'display_name': 'abc456',
                   'display_description': '',
                   'size': 1,
                   'host': "hostname@backend#%s" % POOLUUID}

DATA_IN_CG_SNAPSHOT = {
    'consistencygroup_id': 'fe2dbc51-5810-451d-ab2f-8c8a48d15bee',
    'id': 'cgsnapshot1',
    'name': 'cgsnapshot1',
    'description': 'cgsnapshot1',
    'status': ''}

DATA_IN_SNAPSHOT = {'id': 'snapshot1',
                    'volume_id': 'abc123',
                    'display_name': 'snapshot1',
                    'display_description': ''}

DATA_OUT_SNAPSHOT_CG = {
    'id': 'snapshot1',
    'volume_id': 'abc123',
    'display_name': 'snapshot1',
    'display_description': '',
    'cgsnapshot_id': 'fe2dbc51-5810-451d-ab2f-8c8a48d15bee'}


class TestProphetStorDPLVolume(test.TestCase):

    def _gen_snapshot_url(self, vdevid, snapshotid):
        snapshot_url = '/%s/%s/%s' % (vdevid, DPLCOMMON.DPL_OBJ_SNAPSHOT,
                                      snapshotid)
        return snapshot_url

    def setUp(self):
        super(TestProphetStorDPLVolume, self).setUp()
        self.dplcmd = DPLCOMMON.DPLVolume('1.1.1.1', 8356, 'admin', 'password')
        self.DPL_MOCK = mock.MagicMock()
        self.dplcmd.objCmd = self.DPL_MOCK
        self.DPL_MOCK.send_cmd.return_value = DATA_OUTPUT

    def test_getserverinfo(self):
        self.dplcmd.get_server_info()
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'GET',
            '/%s/%s/' % (DPLCOMMON.DPL_VER_V1, DPLCOMMON.DPL_OBJ_SYSTEM),
            None,
            [httplib.OK, httplib.ACCEPTED])

    def test_createvdev(self):
        self.dplcmd.create_vdev(DATA_IN_VOLUME['id'],
                                DATA_IN_VOLUME['display_name'],
                                DATA_IN_VOLUME['display_description'],
                                POOLUUID,
                                int(DATA_IN_VOLUME['size']) * units.Gi)

        metadata = {}
        metadata['display_name'] = DATA_IN_VOLUME['display_name']
        metadata['display_description'] = DATA_IN_VOLUME['display_description']
        metadata['pool_uuid'] = POOLUUID
        metadata['total_capacity'] = int(DATA_IN_VOLUME['size']) * units.Gi
        metadata['maximum_snapshot'] = 1024
        metadata['properties'] = dict(thin_provision=True)
        params = {}
        params['metadata'] = metadata
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'PUT',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1, DPLCOMMON.DPL_OBJ_VOLUME,
                            DATA_IN_VOLUME['id']),
            params,
            [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def test_extendvdev(self):
        self.dplcmd.extend_vdev(DATA_IN_VOLUME['id'],
                                DATA_IN_VOLUME['display_name'],
                                DATA_IN_VOLUME['display_description'],
                                int(DATA_IN_VOLUME['size']) * units.Gi)
        metadata = {}
        metadata['display_name'] = DATA_IN_VOLUME['display_name']
        metadata['display_description'] = DATA_IN_VOLUME['display_description']
        metadata['total_capacity'] = int(DATA_IN_VOLUME['size']) * units.Gi
        metadata['maximum_snapshot'] = 1024
        params = {}
        params['metadata'] = metadata
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'PUT',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1, DPLCOMMON.DPL_OBJ_VOLUME,
                            DATA_IN_VOLUME['id']),
            params,
            [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def test_deletevdev(self):
        self.dplcmd.delete_vdev(DATA_IN_VOLUME['id'], True)
        metadata = {}
        params = {}
        metadata['force'] = True
        params['metadata'] = metadata
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'DELETE',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1, DPLCOMMON.DPL_OBJ_VOLUME,
                            DATA_IN_VOLUME['id']),
            params,
            [httplib.OK, httplib.ACCEPTED, httplib.NOT_FOUND,
             httplib.NO_CONTENT])

    def test_createvdevfromsnapshot(self):
        self.dplcmd.create_vdev_from_snapshot(
            DATA_IN_VOLUME['id'],
            DATA_IN_VOLUME['display_name'],
            DATA_IN_VOLUME['display_description'],
            DATA_IN_SNAPSHOT['id'],
            POOLUUID)
        metadata = {}
        params = {}
        metadata['snapshot_operation'] = 'copy'
        metadata['display_name'] = DATA_IN_VOLUME['display_name']
        metadata['display_description'] = DATA_IN_VOLUME['display_description']
        metadata['pool_uuid'] = POOLUUID
        metadata['maximum_snapshot'] = 1024
        metadata['properties'] = dict(thin_provision=True)
        params['metadata'] = metadata
        params['copy'] = self._gen_snapshot_url(DATA_IN_VOLUME['id'],
                                                DATA_IN_SNAPSHOT['id'])
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'PUT',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1, DPLCOMMON.DPL_OBJ_VOLUME,
                            DATA_IN_VOLUME['id']),
            params,
            [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def test_getpool(self):
        self.dplcmd.get_pool(POOLUUID)
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'GET',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1, DPLCOMMON.DPL_OBJ_POOL,
                            POOLUUID),
            None,
            [httplib.OK, httplib.ACCEPTED])

    def test_clonevdev(self):
        self.dplcmd.clone_vdev(
            DATA_IN_VOLUME['id'],
            DATA_IN_VOLUME1['id'],
            POOLUUID,
            DATA_IN_VOLUME['display_name'],
            DATA_IN_VOLUME['display_description'],
            int(DATA_IN_VOLUME['size']) * units.Gi
        )
        metadata = {}
        params = {}
        metadata["snapshot_operation"] = "clone"
        metadata["display_name"] = DATA_IN_VOLUME['display_name']
        metadata["display_description"] = DATA_IN_VOLUME['display_description']
        metadata["pool_uuid"] = POOLUUID
        metadata["total_capacity"] = int(DATA_IN_VOLUME['size']) * units.Gi
        metadata['maximum_snapshot'] = 1024
        metadata['properties'] = dict(thin_provision=True)
        params["metadata"] = metadata
        params["copy"] = DATA_IN_VOLUME['id']

        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'PUT',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1, DPLCOMMON.DPL_OBJ_VOLUME,
                            DATA_IN_VOLUME1['id']),
            params,
            [httplib.OK, httplib.CREATED, httplib.ACCEPTED])

    def test_createvdevsnapshot(self):
        self.dplcmd.create_vdev_snapshot(
            DATA_IN_VOLUME['id'],
            DATA_IN_SNAPSHOT['id'],
            DATA_IN_SNAPSHOT['display_name'],
            DATA_IN_SNAPSHOT['display_description']
        )
        metadata = {}
        params = {}
        metadata['display_name'] = DATA_IN_SNAPSHOT['display_name']
        metadata['display_description'] = \
            DATA_IN_SNAPSHOT['display_description']
        params['metadata'] = metadata
        params['snapshot'] = DATA_IN_SNAPSHOT['id']

        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'PUT',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1, DPLCOMMON.DPL_OBJ_VOLUME,
                            DATA_IN_VOLUME['id']),
            params,
            [httplib.OK, httplib.CREATED, httplib.ACCEPTED])

    def test_getvdev(self):
        self.dplcmd.get_vdev(DATA_IN_VOLUME['id'])
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'GET',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1, DPLCOMMON.DPL_OBJ_VOLUME,
                            DATA_IN_VOLUME['id']),
            None,
            [httplib.OK, httplib.ACCEPTED, httplib.NOT_FOUND])

    def test_getvdevstatus(self):
        self.dplcmd.get_vdev_status(DATA_IN_VOLUME['id'], '123456')
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'GET',
            '/%s/%s/%s/?event_uuid=%s' % (DPLCOMMON.DPL_VER_V1,
                                          DPLCOMMON.DPL_OBJ_VOLUME,
                                          DATA_IN_VOLUME['id'],
                                          '123456'),
            None,
            [httplib.OK, httplib.NOT_FOUND])

    def test_getpoolstatus(self):
        self.dplcmd.get_pool_status(POOLUUID, '123456')
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'GET',
            '/%s/%s/%s/?event_uuid=%s' % (DPLCOMMON.DPL_VER_V1,
                                          DPLCOMMON.DPL_OBJ_POOL,
                                          POOLUUID,
                                          '123456'),
            None,
            [httplib.OK, httplib.NOT_FOUND])

    def test_assignvdev(self):
        self.dplcmd.assign_vdev(
            DATA_IN_VOLUME['id'],
            'iqn.1993-08.org.debian:01:test1',
            '',
            '1.1.1.1:3260',
            0
        )
        params = {}
        metadata = {}
        exports = {}
        metadata['export_operation'] = 'assign'
        exports['Network/iSCSI'] = {}
        target_info = {}
        target_info['logical_unit_number'] = 0
        target_info['logical_unit_name'] = ''
        permissions = []
        portals = []
        portals.append('1.1.1.1:3260')
        permissions.append('iqn.1993-08.org.debian:01:test1')
        target_info['permissions'] = permissions
        target_info['portals'] = portals
        exports['Network/iSCSI'] = target_info

        params['metadata'] = metadata
        params['exports'] = exports
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'PUT',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1,
                            DPLCOMMON.DPL_OBJ_VOLUME,
                            DATA_IN_VOLUME['id']),
            params,
            [httplib.OK, httplib.ACCEPTED, httplib.CREATED])

    def test_unassignvdev(self):
        self.dplcmd.unassign_vdev(DATA_IN_VOLUME['id'],
                                  'iqn.1993-08.org.debian:01:test1',
                                  '')
        params = {}
        metadata = {}
        exports = {}
        metadata['export_operation'] = 'unassign'
        params['metadata'] = metadata

        exports['Network/iSCSI'] = {}
        exports['Network/iSCSI']['target_identifier'] = ''
        permissions = []
        permissions.append('iqn.1993-08.org.debian:01:test1')
        exports['Network/iSCSI']['permissions'] = permissions

        params['exports'] = exports
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'PUT',
            '/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1,
                            DPLCOMMON.DPL_OBJ_VOLUME,
                            DATA_IN_VOLUME['id']),
            params,
            [httplib.OK, httplib.ACCEPTED,
             httplib.NO_CONTENT, httplib.NOT_FOUND])

    def test_deletevdevsnapshot(self):
        self.dplcmd.delete_vdev_snapshot(DATA_IN_VOLUME['id'],
                                         DATA_IN_SNAPSHOT['id'])
        params = {}
        params['copy'] = self._gen_snapshot_url(DATA_IN_VOLUME['id'],
                                                DATA_IN_SNAPSHOT['id'])
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'DELETE',
            '/%s/%s/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1,
                                  DPLCOMMON.DPL_OBJ_VOLUME,
                                  DATA_IN_VOLUME['id'],
                                  DPLCOMMON.DPL_OBJ_SNAPSHOT,
                                  DATA_IN_SNAPSHOT['id']),
            None,
            [httplib.OK, httplib.ACCEPTED, httplib.NO_CONTENT,
             httplib.NOT_FOUND])

    def test_listvdevsnapshots(self):
        self.dplcmd.list_vdev_snapshots(DATA_IN_VOLUME['id'])
        self.DPL_MOCK.send_cmd.assert_called_once_with(
            'GET',
            '/%s/%s/%s/%s/' % (DPLCOMMON.DPL_VER_V1,
                               DPLCOMMON.DPL_OBJ_VOLUME,
                               DATA_IN_VOLUME['id'],
                               DPLCOMMON.DPL_OBJ_SNAPSHOT),
            None,
            [httplib.OK])


class TestProphetStorDPLDriver(test.TestCase):

    def __init__(self, method):
        super(TestProphetStorDPLDriver, self).__init__(method)

    def _conver_uuid2hex(self, strID):
        return strID.replace('-', '')

    def setUp(self):
        super(TestProphetStorDPLDriver, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.san_ip = '1.1.1.1'
        self.configuration.dpl_port = 8356
        self.configuration.san_login = 'admin'
        self.configuration.san_password = 'password'
        self.configuration.dpl_pool = POOLUUID
        self.configuration.iscsi_port = 3260
        self.configuration.san_is_local = False
        self.configuration.san_thin_provision = True
        self.context = ''
        self.DPL_MOCK = mock.MagicMock()
        self.DB_MOCK = mock.MagicMock()
        self.dpldriver = DPLDRIVER.DPLISCSIDriver(
            configuration=self.configuration)
        self.dpldriver.dpl = self.DPL_MOCK
        self.dpldriver.db = self.DB_MOCK
        self.dpldriver.do_setup(self.context)

    def test_get_volume_stats(self):
        self.DPL_MOCK.get_pool.return_value = DATA_POOLINFO
        self.DPL_MOCK.get_server_info.return_value = DATA_SERVER_INFO
        res = self.dpldriver.get_volume_stats(True)
        self.assertEqual('ProphetStor', res['vendor_name'])
        self.assertEqual('1.5', res['driver_version'])
        pool = res["pools"][0]
        self.assertEqual(4, pool['total_capacity_gb'])
        self.assertEqual(4, pool['free_capacity_gb'])
        self.assertEqual(0, pool['reserved_percentage'])
        self.assertFalse(pool['QoS_support'])

    def test_create_volume(self):
        self.DPL_MOCK.create_vdev.return_value = DATA_OUTPUT
        self.dpldriver.create_volume(DATA_IN_VOLUME)
        self.DPL_MOCK.create_vdev.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME['id']),
            DATA_IN_VOLUME['display_name'],
            DATA_IN_VOLUME['display_description'],
            self.configuration.dpl_pool,
            int(DATA_IN_VOLUME['size']) * units.Gi,
            True)

    def test_create_volume_without_pool(self):
        fake_volume = copy.deepcopy(DATA_IN_VOLUME)
        self.DPL_MOCK.create_vdev.return_value = DATA_OUTPUT
        self.configuration.dpl_pool = ""
        fake_volume['host'] = "host@backend"  # missing pool
        self.assertRaises(exception.InvalidHost, self.dpldriver.create_volume,
                          volume=fake_volume)

    def test_create_volume_with_configuration_pool(self):
        fake_volume = copy.deepcopy(DATA_IN_VOLUME)
        fake_volume['host'] = "host@backend"  # missing pool

        self.DPL_MOCK.create_vdev.return_value = DATA_OUTPUT
        self.dpldriver.create_volume(fake_volume)
        self.DPL_MOCK.create_vdev.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME['id']),
            DATA_IN_VOLUME['display_name'],
            DATA_IN_VOLUME['display_description'],
            self.configuration.dpl_pool,
            int(DATA_IN_VOLUME['size']) * units.Gi,
            True)

    def test_create_volume_of_group(self):
        self.DPL_MOCK.create_vdev.return_value = DATA_OUTPUT
        self.DPL_MOCK.join_vg.return_value = DATA_OUTPUT
        self.dpldriver.create_volume(DATA_IN_VOLUME_VG)
        self.DPL_MOCK.create_vdev.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME['id']),
            DATA_IN_VOLUME['display_name'],
            DATA_IN_VOLUME['display_description'],
            self.configuration.dpl_pool,
            int(DATA_IN_VOLUME['size']) * units.Gi,
            True)
        self.DPL_MOCK.join_vg.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME_VG['id']),
            self._conver_uuid2hex(
                DATA_IN_VOLUME_VG['consistencygroup_id']))

    def test_delete_volume(self):
        self.DPL_MOCK.delete_vdev.return_value = DATA_OUTPUT
        self.dpldriver.delete_volume(DATA_IN_VOLUME)
        self.DPL_MOCK.delete_vdev.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME['id']))

    def test_delete_volume_of_group(self):
        self.DPL_MOCK.delete_vdev.return_value = DATA_OUTPUT
        self.DPL_MOCK.leave_vg.return_volume = DATA_OUTPUT
        self.dpldriver.delete_volume(DATA_IN_VOLUME_VG)
        self.DPL_MOCK.leave_vg.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME_VG['id']),
            self._conver_uuid2hex(DATA_IN_GROUP['id'])
        )
        self.DPL_MOCK.delete_vdev.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME['id']))

    def test_create_volume_from_snapshot(self):
        self.DPL_MOCK.create_vdev_from_snapshot.return_value = DATA_OUTPUT
        self.dpldriver.create_volume_from_snapshot(DATA_IN_VOLUME,
                                                   DATA_IN_SNAPSHOT)
        self.DPL_MOCK.create_vdev_from_snapshot.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME['id']),
            DATA_IN_VOLUME['display_name'],
            DATA_IN_VOLUME['display_description'],
            self._conver_uuid2hex(DATA_IN_SNAPSHOT['id']),
            self.configuration.dpl_pool,
            True)

    def test_create_cloned_volume(self):
        self.DPL_MOCK.clone_vdev.return_value = DATA_OUTPUT
        self.dpldriver.create_cloned_volume(DATA_IN_VOLUME1, DATA_IN_VOLUME)
        self.DPL_MOCK.clone_vdev.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME['id']),
            self._conver_uuid2hex(DATA_IN_VOLUME1['id']),
            self.configuration.dpl_pool,
            DATA_IN_VOLUME1['display_name'],
            DATA_IN_VOLUME1['display_description'],
            int(DATA_IN_VOLUME1['size']) *
            units.Gi,
            True)

    def test_create_snapshot(self):
        self.DPL_MOCK.create_vdev_snapshot.return_value = DATA_OUTPUT
        self.dpldriver.create_snapshot(DATA_IN_SNAPSHOT)
        self.DPL_MOCK.create_vdev_snapshot.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_SNAPSHOT['volume_id']),
            self._conver_uuid2hex(DATA_IN_SNAPSHOT['id']),
            DATA_IN_SNAPSHOT['display_name'],
            DATA_IN_SNAPSHOT['display_description'])

    def test_delete_snapshot(self):
        self.DPL_MOCK.delete_vdev_snapshot.return_value = DATA_OUTPUT
        self.dpldriver.delete_snapshot(DATA_IN_SNAPSHOT)
        self.DPL_MOCK.delete_vdev_snapshot.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_SNAPSHOT['volume_id']),
            self._conver_uuid2hex(DATA_IN_SNAPSHOT['id']))

    def test_initialize_connection(self):
        self.DPL_MOCK.assign_vdev.return_value = DATA_ASSIGNVDEV
        self.DPL_MOCK.get_vdev.return_value = DATA_ASSIGNVDEV
        res = self.dpldriver.initialize_connection(DATA_IN_VOLUME,
                                                   DATA_IN_CONNECTOR)
        self.assertEqual('iscsi', res['driver_volume_type'])
        self.assertEqual('101', res['data']['target_lun'])
        self.assertTrue(res['data']['target_discovered'])
        self.assertEqual('172.31.1.210:3260', res['data']['target_portal'])
        self.assertEqual(
            'iqn.2013-09.com.prophetstor:hypervisor.886423051816',
            res['data']['target_iqn'])

    def test_terminate_connection(self):
        self.DPL_MOCK.unassign_vdev.return_value = DATA_OUTPUT
        self.dpldriver.terminate_connection(DATA_IN_VOLUME, DATA_IN_CONNECTOR)
        self.DPL_MOCK.unassign_vdev.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME['id']),
            DATA_IN_CONNECTOR['initiator'])

    def test_terminate_connection_volume_detached(self):
        self.DPL_MOCK.unassign_vdev.return_value = errno.ENODATA, None
        self.dpldriver.terminate_connection(DATA_IN_VOLUME, DATA_IN_CONNECTOR)
        self.DPL_MOCK.unassign_vdev.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_VOLUME['id']),
            DATA_IN_CONNECTOR['initiator'])

    def test_terminate_connection_failed(self):
        self.DPL_MOCK.unassign_vdev.return_value = errno.EFAULT, None
        ex = self.assertRaises(
            exception.VolumeBackendAPIException,
            self.dpldriver.terminate_connection,
            volume=DATA_IN_VOLUME, connector=DATA_IN_CONNECTOR)
        self.assertTrue(
            re.match(r".*Flexvisor failed", ex.msg))

    def test_get_pool_info(self):
        self.DPL_MOCK.get_pool.return_value = DATA_POOLINFO
        _, res = self.dpldriver._get_pool_info(POOLUUID)
        self.assertEqual(4294967296, res['metadata']['available_capacity'])
        self.assertEqual(1390551362349, res['metadata']['ctime'])
        self.assertEqual('Default Pool',
                         res['metadata']['display_description'])
        self.assertEqual('default_pool',
                         res['metadata']['display_name'])
        self.assertEqual('4f7c4d679a664857afa4d51f282a516a',
                         res['metadata']['event_uuid'])
        self.assertEqual(
            {'cache': [],
             'data': ['disk_uuid_0', 'disk_uuid_1', 'disk_uuid_2'],
             'log': [],
             'spare': []},
            res['metadata']['physical_device'])
        self.assertEqual(POOLUUID, res['metadata']['pool_uuid'])
        self.assertEqual(
            {'raid_level': 'raid0'},
            res['metadata']['properties'])
        self.assertEqual('Online', res['metadata']['state'])
        self.assertEqual(4294967296, res['metadata']['total_capacity'])
        self.assertEqual('8173612007304181810', res['metadata']['zpool_guid'])

    def test_create_consistency_group(self):
        self.DPL_MOCK.create_vg.return_value = DATA_OUTPUT
        model_update = self.dpldriver.create_consistencygroup(self.context,
                                                              DATA_IN_GROUP)
        self.DPL_MOCK.create_vg.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_GROUP['id']), DATA_IN_GROUP['name'],
            DATA_IN_GROUP['description'])
        self.assertDictMatch({'status': 'available'}, model_update)

    def test_delete_consistency_group(self):
        self.DB_MOCK.volume_get_all_by_group.return_value = \
            [DATA_IN_VOLUME_VG]
        self.DPL_MOCK.delete_vdev.return_value = DATA_OUTPUT
        self.DPL_MOCK.delete_cg.return_value = DATA_OUTPUT
        model_update, volumes = self.dpldriver.delete_consistencygroup(
            self.context, DATA_IN_GROUP)
        self.DPL_MOCK.delete_vg.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_GROUP['id']))
        self.DPL_MOCK.delete_vdev.assert_called_once_with(
            self._conver_uuid2hex((DATA_IN_VOLUME_VG['id'])))
        self.assertDictMatch({'status': 'deleted'}, model_update, )

    def test_create_consistency_group_snapshot(self):
        self.DB_MOCK.snapshot_get_all_for_cgsnapshot.return_value = \
            [DATA_OUT_SNAPSHOT_CG]
        self.DPL_MOCK.create_vdev_snapshot.return_value = DATA_OUTPUT
        model_update, snapshots = self.dpldriver.create_cgsnapshot(
            self.context, DATA_IN_CG_SNAPSHOT)
        self.assertDictMatch({'status': 'available'}, model_update)

    def test_delete_consistency_group_snapshot(self):
        self.DB_MOCK.snapshot_get_all_for_cgsnapshot.return_value = \
            [DATA_OUT_SNAPSHOT_CG]
        self.DPL_MOCK.delete_cgsnapshot.return_value = DATA_OUTPUT
        model_update, snapshots = self.dpldriver.delete_cgsnapshot(
            self.context, DATA_IN_CG_SNAPSHOT)
        self.DPL_MOCK.delete_vdev_snapshot.assert_called_once_with(
            self._conver_uuid2hex(DATA_IN_CG_SNAPSHOT['consistencygroup_id']),
            self._conver_uuid2hex(DATA_IN_CG_SNAPSHOT['id']),
            True)
        self.assertDictMatch({'status': 'deleted'}, model_update)
