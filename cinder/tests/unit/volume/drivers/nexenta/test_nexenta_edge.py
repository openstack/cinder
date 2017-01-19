#
# Copyright 2015 Nexenta Systems, Inc.
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

import json
import mock

from cinder import context
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.nexenta.nexentaedge import iscsi

NEDGE_URL = 'service/isc/iscsi'
NEDGE_BUCKET = 'c/t/bk'
NEDGE_SERVICE = 'isc'
NEDGE_BLOCKSIZE = 4096
NEDGE_CHUNKSIZE = 16384

MOCK_VOL = {
    'id': 'vol1',
    'name': 'vol1',
    'size': 1
}
MOCK_VOL2 = {
    'id': 'vol2',
    'name': 'vol2',
    'size': 1
}
MOCK_VOL3 = {
    'id': 'vol3',
    'name': 'vol3',
    'size': 2
}
MOCK_SNAP = {
    'id': 'snap1',
    'name': 'snap1',
    'volume_name': 'vol1'
}
NEW_VOL_SIZE = 2
ISCSI_TARGET_NAME = 'iscsi_target_name'
ISCSI_TARGET_STATUS = 'Target 1: ' + ISCSI_TARGET_NAME


class TestNexentaEdgeISCSIDriver(test.TestCase):

    def setUp(self):
        def _safe_get(opt):
            return getattr(self.cfg, opt)
        super(TestNexentaEdgeISCSIDriver, self).setUp()
        self.context = context.get_admin_context()
        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.safe_get = mock.Mock(side_effect=_safe_get)
        self.cfg.trace_flags = 'fake_trace_flags'
        self.cfg.driver_data_namespace = 'fake_driver_data_namespace'
        self.cfg.nexenta_client_address = '0.0.0.0'
        self.cfg.nexenta_rest_address = '0.0.0.0'
        self.cfg.nexenta_rest_port = 8080
        self.cfg.nexenta_rest_protocol = 'http'
        self.cfg.nexenta_iscsi_target_portal_port = 3260
        self.cfg.nexenta_rest_user = 'admin'
        self.cfg.nexenta_rest_password = 'admin'
        self.cfg.nexenta_lun_container = NEDGE_BUCKET
        self.cfg.nexenta_iscsi_service = NEDGE_SERVICE
        self.cfg.nexenta_blocksize = NEDGE_BLOCKSIZE
        self.cfg.nexenta_chunksize = NEDGE_CHUNKSIZE
        self.cfg.replication_device = []

        mock_exec = mock.Mock()
        mock_exec.return_value = ('', '')
        self.driver = iscsi.NexentaEdgeISCSIDriver(execute=mock_exec,
                                                   configuration=self.cfg)
        self.api_patcher = mock.patch('cinder.volume.drivers.nexenta.'
                                      'nexentaedge.jsonrpc.'
                                      'NexentaEdgeJSONProxy.__call__')
        self.mock_api = self.api_patcher.start()

        self.mock_api.return_value = {
            'data': {'value': ISCSI_TARGET_STATUS}
        }
        self.driver.do_setup(self.context)

        self.addCleanup(self.api_patcher.stop)

    def test_check_do_setup(self):
        self.assertEqual(ISCSI_TARGET_NAME, self.driver.target_name)

    def test_check_do_setup__vip(self):
        first_vip = '/'.join((self.cfg.nexenta_client_address, '32'))
        vips = [
            [{'ip': first_vip}],
            [{'ip': '0.0.0.1/32'}]
        ]

        def my_side_effect(*args, **kwargs):
            if args[0] == 'service/isc/iscsi/status':
                return {'data': {'value': ISCSI_TARGET_STATUS}}
            else:
                return {'data': {'X-VIPS': json.dumps(vips)}}

        self.mock_api.side_effect = my_side_effect
        self.driver.do_setup(self.context)
        self.assertEqual(self.driver.ha_vip, first_vip)

    def test_check_do_setup__vip_not_in_xvips(self):
        first_vip = '1.2.3.4/32'
        vips = [
            [{'ip': first_vip}],
            [{'ip': '0.0.0.1/32'}]
        ]

        def my_side_effect(*args, **kwargs):
            if args[0] == 'service/isc/iscsi/status':
                return {'data': {'value': ISCSI_TARGET_STATUS}}
            else:
                return {'data': {'X-VIPS': json.dumps(vips)}}

        self.mock_api.side_effect = my_side_effect
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, self.context)

    def test_check_do_setup__vip_no_client_address(self):
        self.cfg.nexenta_client_address = None
        first_vip = '1.2.3.4/32'
        vips = [
            [{'ip': first_vip}]
        ]

        def my_side_effect(*args, **kwargs):
            if args[0] == 'service/isc/iscsi/status':
                return {'data': {'value': ISCSI_TARGET_STATUS}}
            else:
                return {'data': {'X-VIPS': json.dumps(vips)}}

        self.mock_api.side_effect = my_side_effect
        self.driver.do_setup(self.context)
        self.assertEqual(self.driver.ha_vip, first_vip)

    def test_check_do_setup__vip_no_client_address_2_xvips(self):
        self.cfg.nexenta_client_address = None
        first_vip = '1.2.3.4/32'
        vips = [
            [{'ip': first_vip}],
            [{'ip': '0.0.0.1/32'}]
        ]

        def my_side_effect(*args, **kwargs):
            if args[0] == 'service/isc/iscsi/status':
                return {'data': {'value': ISCSI_TARGET_STATUS}}
            else:
                return {'data': {'X-VIPS': json.dumps(vips)}}

        self.mock_api.side_effect = my_side_effect
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.do_setup, self.context)

    def test_create_volume(self):
        self.driver.create_volume(MOCK_VOL)
        self.mock_api.assert_called_with(NEDGE_URL, {
            'objectPath': NEDGE_BUCKET + '/' + MOCK_VOL['id'],
            'volSizeMB': MOCK_VOL['size'] * 1024,
            'blockSize': NEDGE_BLOCKSIZE,
            'chunkSize': NEDGE_CHUNKSIZE
        })

    def test_create_volume__vip(self):
        self.driver.ha_vip = self.cfg.nexenta_client_address + '/32'
        self.driver.create_volume(MOCK_VOL)
        self.mock_api.assert_called_with(NEDGE_URL, {
            'objectPath': NEDGE_BUCKET + '/' + MOCK_VOL['id'],
            'volSizeMB': MOCK_VOL['size'] * 1024,
            'blockSize': NEDGE_BLOCKSIZE,
            'chunkSize': NEDGE_CHUNKSIZE,
            'vip': self.cfg.nexenta_client_address + '/32'
        })

    def test_create_volume_fail(self):
        self.mock_api.side_effect = RuntimeError
        self.assertRaises(RuntimeError, self.driver.create_volume, MOCK_VOL)

    def test_delete_volume(self):
        self.mock_api.side_effect = exception.VolumeBackendAPIException(
            'No volume')
        self.driver.delete_volume(MOCK_VOL)
        self.mock_api.assert_called_with(NEDGE_URL, {
            'objectPath': NEDGE_BUCKET + '/' + MOCK_VOL['id']
        })

    def test_delete_volume_fail(self):
        self.mock_api.side_effect = RuntimeError
        self.assertRaises(RuntimeError, self.driver.delete_volume, MOCK_VOL)

    def test_extend_volume(self):
        self.driver.extend_volume(MOCK_VOL, NEW_VOL_SIZE)
        self.mock_api.assert_called_with(NEDGE_URL + '/resize', {
            'objectPath': NEDGE_BUCKET + '/' + MOCK_VOL['id'],
            'newSizeMB': NEW_VOL_SIZE * 1024
        })

    def test_extend_volume_fail(self):
        self.mock_api.side_effect = RuntimeError
        self.assertRaises(RuntimeError, self.driver.extend_volume,
                          MOCK_VOL, NEW_VOL_SIZE)

    def test_create_snapshot(self):
        self.driver.create_snapshot(MOCK_SNAP)
        self.mock_api.assert_called_with(NEDGE_URL + '/snapshot', {
            'objectPath': NEDGE_BUCKET + '/' + MOCK_VOL['id'],
            'snapName': MOCK_SNAP['id']
        })

    def test_create_snapshot_fail(self):
        self.mock_api.side_effect = RuntimeError
        self.assertRaises(RuntimeError, self.driver.create_snapshot, MOCK_SNAP)

    def test_delete_snapshot(self):
        self.driver.delete_snapshot(MOCK_SNAP)
        self.mock_api.assert_called_with(NEDGE_URL + '/snapshot', {
            'objectPath': NEDGE_BUCKET + '/' + MOCK_VOL['id'],
            'snapName': MOCK_SNAP['id']
        })

    def test_delete_snapshot_fail(self):
        self.mock_api.side_effect = RuntimeError
        self.assertRaises(RuntimeError, self.driver.delete_snapshot, MOCK_SNAP)

    def test_create_volume_from_snapshot(self):
        self.driver.create_volume_from_snapshot(MOCK_VOL2, MOCK_SNAP)
        self.mock_api.assert_called_with(NEDGE_URL + '/snapshot/clone', {
            'objectPath': NEDGE_BUCKET + '/' + MOCK_SNAP['volume_name'],
            'clonePath': NEDGE_BUCKET + '/' + MOCK_VOL2['id'],
            'snapName': MOCK_SNAP['id']
        })

    def test_create_volume_from_snapshot_fail(self):
        self.mock_api.side_effect = RuntimeError
        self.assertRaises(RuntimeError,
                          self.driver.create_volume_from_snapshot,
                          MOCK_VOL2, MOCK_SNAP)

    def test_create_cloned_volume(self):
        self.driver.create_cloned_volume(MOCK_VOL2, MOCK_VOL)
        self.mock_api.assert_called_with(NEDGE_URL, {
            'objectPath': NEDGE_BUCKET + '/' + MOCK_VOL2['id'],
            'volSizeMB': MOCK_VOL2['size'] * 1024,
            'blockSize': NEDGE_BLOCKSIZE,
            'chunkSize': NEDGE_CHUNKSIZE
        })

    def test_create_cloned_volume_larger(self):
        self.driver.create_cloned_volume(MOCK_VOL3, MOCK_VOL)
        # ignore the clone call, this has been tested before
        self.mock_api.assert_called_with(NEDGE_URL + '/resize', {
            'objectPath': NEDGE_BUCKET + '/' + MOCK_VOL3['id'],
            'newSizeMB': MOCK_VOL3['size'] * 1024
        })

    def test_create_cloned_volume_fail(self):
        self.mock_api.side_effect = RuntimeError
        self.assertRaises(RuntimeError, self.driver.create_cloned_volume,
                          MOCK_VOL2, MOCK_VOL)
