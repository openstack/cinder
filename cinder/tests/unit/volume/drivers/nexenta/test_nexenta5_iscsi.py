# Copyright 2016 Nexenta Systems, Inc.
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
"""
Unit tests for OpenStack Cinder volume driver
"""

import mock
from mock import patch
from oslo_serialization import jsonutils
from oslo_utils import units
import requests

from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.nexenta.ns5 import iscsi
from cinder.volume.drivers.nexenta.ns5 import jsonrpc


class TestNexentaISCSIDriver(test.TestCase):
    TEST_VOLUME_NAME = 'volume1'
    TEST_VOLUME_NAME2 = 'volume2'
    TEST_VOLUME_NAME3 = 'volume3'
    TEST_SNAPSHOT_NAME = 'snapshot1'
    TEST_VOLUME_REF = {
        'name': TEST_VOLUME_NAME,
        'size': 1,
        'id': '1',
        'status': 'available'
    }
    TEST_VOLUME_REF2 = {
        'name': TEST_VOLUME_NAME2,
        'size': 1,
        'id': '2',
        'status': 'in-use'
    }
    TEST_VOLUME_REF3 = {
        'name': TEST_VOLUME_NAME3,
        'size': 2,
        'id': '2',
        'status': 'in-use'
    }
    TEST_SNAPSHOT_REF = {
        'name': TEST_SNAPSHOT_NAME,
        'volume_name': TEST_VOLUME_NAME,
        'volume_id': '1',
        'volume_size': 1
    }

    def __init__(self, method):
        super(TestNexentaISCSIDriver, self).__init__(method)

    def setUp(self):
        super(TestNexentaISCSIDriver, self).setUp()
        self.cfg = mock.Mock(spec=conf.Configuration)
        self.ctxt = context.get_admin_context()
        self.cfg.nexenta_dataset_description = ''
        self.cfg.nexenta_host = '1.1.1.1'
        self.cfg.nexenta_user = 'admin'
        self.cfg.nexenta_password = 'nexenta'
        self.cfg.nexenta_volume = 'cinder'
        self.cfg.nexenta_rest_port = 2000
        self.cfg.nexenta_rest_protocol = 'http'
        self.cfg.nexenta_iscsi_target_portal_port = 8080
        self.cfg.nexenta_target_prefix = 'iqn:'
        self.cfg.nexenta_target_group_prefix = 'cinder/'
        self.cfg.nexenta_ns5_blocksize = 32
        self.cfg.nexenta_sparse = True
        self.cfg.nexenta_dataset_compression = 'on'
        self.cfg.nexenta_dataset_dedup = 'off'
        self.cfg.reserved_percentage = 20
        self.cfg.nexenta_volume = 'pool'
        self.cfg.nexenta_volume_group = 'dsg'
        self.nef_mock = mock.Mock()
        self.mock_object(jsonrpc, 'NexentaJSONProxy',
                         return_value=self.nef_mock)
        self.drv = iscsi.NexentaISCSIDriver(
            configuration=self.cfg)
        self.drv.db = db
        self.drv.do_setup(self.ctxt)

    def _create_volume_db_entry(self):
        vol = {
            'id': '1',
            'size': 1,
            'status': 'available',
            'provider_location': self.TEST_VOLUME_NAME
        }
        return db.volume_create(self.ctxt, vol)['id']

    def test_do_setup(self):
        self.nef_mock.post.side_effect = exception.NexentaException(
            'Could not create volume group')
        self.assertRaises(
            exception.NexentaException,
            self.drv.do_setup, self.ctxt)

        self.nef_mock.post.side_effect = exception.NexentaException(
            '{"code": "EEXIST"}')
        self.assertIsNone(self.drv.do_setup(self.ctxt))

    def test_check_for_setup_error(self):
        self.nef_mock.get.return_value = {
            'data': [{'name': 'iscsit', 'state': 'offline'}]}
        self.assertRaises(
            exception.NexentaException, self.drv.check_for_setup_error)

        self.nef_mock.get.side_effect = exception.NexentaException()
        self.assertRaises(LookupError, self.drv.check_for_setup_error)

    def test_create_volume(self):
        self.drv.create_volume(self.TEST_VOLUME_REF)
        url = 'storage/pools/pool/volumeGroups/dsg/volumes'
        self.nef_mock.post.assert_called_with(url, {
            'name': self.TEST_VOLUME_REF['name'],
            'volumeSize': 1 * units.Gi,
            'volumeBlockSize': 32768,
            'sparseVolume': self.cfg.nexenta_sparse})

    def test_delete_volume(self):
        self.nef_mock.delete.side_effect = exception.NexentaException()
        self.assertIsNone(self.drv.delete_volume(self.TEST_VOLUME_REF))
        url = 'storage/pools/pool/volumeGroups'
        data = {'name': 'dsg', 'volumeBlockSize': 32768}
        self.nef_mock.post.assert_called_with(url, data)

    def test_extend_volume(self):
        self.drv.extend_volume(self.TEST_VOLUME_REF, 2)
        url = ('storage/pools/pool/volumeGroups/dsg/volumes/%(name)s') % {
            'name': self.TEST_VOLUME_REF['name']}
        self.nef_mock.put.assert_called_with(url, {
            'volumeSize': 2 * units.Gi})

    def test_delete_snapshot(self):
        self._create_volume_db_entry()
        url = ('storage/pools/pool/volumeGroups/dsg/'
               'volumes/volume-1/snapshots/snapshot1')

        self.nef_mock.delete.side_effect = exception.NexentaException('EBUSY')
        self.drv.delete_snapshot(self.TEST_SNAPSHOT_REF)
        self.nef_mock.delete.assert_called_with(url)

        self.nef_mock.delete.side_effect = exception.NexentaException('Error')
        self.drv.delete_snapshot(self.TEST_SNAPSHOT_REF)
        self.nef_mock.delete.assert_called_with(url)

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver.create_snapshot')
    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver.delete_snapshot')
    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver.create_volume_from_snapshot')
    def test_create_cloned_volume(self, crt_vol, dlt_snap, crt_snap):
        self._create_volume_db_entry()
        vol = self.TEST_VOLUME_REF2
        src_vref = self.TEST_VOLUME_REF
        crt_vol.side_effect = exception.NexentaException()
        dlt_snap.side_effect = exception.NexentaException()
        self.assertRaises(
            exception.NexentaException,
            self.drv.create_cloned_volume, vol, src_vref)

    def test_create_snapshot(self):
        self._create_volume_db_entry()
        self.drv.create_snapshot(self.TEST_SNAPSHOT_REF)
        url = 'storage/pools/pool/volumeGroups/dsg/volumes/volume-1/snapshots'
        self.nef_mock.post.assert_called_with(
            url, {'name': 'snapshot1'})

    def test_create_larger_volume_from_snapshot(self):
        self._create_volume_db_entry()
        vol = self.TEST_VOLUME_REF3
        src_vref = self.TEST_SNAPSHOT_REF

        self.drv.create_volume_from_snapshot(vol, src_vref)

        # make sure the volume get extended!
        url = ('storage/pools/pool/volumeGroups/dsg/volumes/%(name)s') % {
            'name': self.TEST_VOLUME_REF3['name']}
        self.nef_mock.put.assert_called_with(url, {
            'volumeSize': 2 * units.Gi})

    def test_get_target_by_alias(self):
        self.nef_mock.get.return_value = {'data': []}
        self.assertIsNone(self.drv._get_target_by_alias('1.1.1.1-0'))

        self.nef_mock.get.return_value = {'data': [{'name': 'iqn-0'}]}
        self.assertEqual(
            {'name': 'iqn-0'}, self.drv._get_target_by_alias('1.1.1.1-0'))

    def test_target_group_exists(self):
        self.nef_mock.get.return_value = {'data': []}
        self.assertFalse(
            self.drv._target_group_exists({'data': [{'name': 'iqn-0'}]}))

        self.nef_mock.get.return_value = {'data': [{'name': '1.1.1.1-0'}]}
        self.assertTrue(self.drv._target_group_exists(
            {'data': [{'name': 'iqn-0'}]}))

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_target_by_alias')
    def test_create_target(self, target):
        self.nef_mock.get.return_value = {}
        target.return_value = {'name': 'iqn-0'}
        self.assertEqual('iqn-0', self.drv._create_target(0))

        target.return_value = None
        self.assertRaises(TypeError, self.drv._create_target, 0)

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._create_target')
    def test_get_target_name(self, target_name):
        self._create_volume_db_entry()
        self.drv.targets = {}
        target_name.return_value = 'iqn-0'
        self.drv.targets['iqn-0'] = []
        self.assertEqual(
            'iqn-0', self.drv._get_target_name(self.TEST_VOLUME_REF))

        volume = self.TEST_VOLUME_REF
        volume['provider_location'] = '1.1.1.1:8080,1 iqn-0 0'
        self.nef_mock.get.return_value = {'data': [{'alias': '1.1.1.1-0'}]}
        self.assertEqual(
            'iqn-0', self.drv._get_target_name(self.TEST_VOLUME_REF))
        self.assertEqual('1.1.1.1-0', self.drv.targetgroups['iqn-0'])

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._create_target')
    def test_get_targetgroup_name(self, target_name):
        self.TEST_VOLUME_REF['provider_location'] = '1.1.1.1:8080,1 iqn-0 0'
        self._create_volume_db_entry()
        target_name = 'iqn-0'
        self.drv.targetgroups[target_name] = '1.1.1.1-0'
        self.assertEqual(
            '1.1.1.1-0', self.drv._get_targetgroup_name(self.TEST_VOLUME_REF))

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_targetgroup_name')
    def test_get_lun_id(self, targetgroup):
        targetgroup.return_value = '1.1.1.1-0'
        self.nef_mock.get.return_value = {'data': [{'guid': '0'}]}
        self.assertEqual('0', self.drv._get_lun_id(self.TEST_VOLUME_REF))

        self.nef_mock.get.return_value = {}
        self.assertRaises(
            LookupError, self.drv._get_lun_id, self.TEST_VOLUME_REF)

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_lun_id')
    def test_lu_exists(self, lun_id):
        lun_id.return_value = '0'
        self.assertTrue(self.drv._lu_exists(self.TEST_VOLUME_REF))
        lun_id.side_effect = LookupError
        self.assertFalse(self.drv._lu_exists(self.TEST_VOLUME_REF))

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_lun_id')
    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_targetgroup_name')
    def test_get_lun(self, targetgroup, lun_id):
        lun_id.return_value = '0'
        targetgroup.return_value = '1.1.1.1-0'
        self.nef_mock.get.return_value = {'data': [{'lunNumber': 0}]}
        self.assertEqual(0, self.drv._get_lun(self.TEST_VOLUME_REF))

        self.nef_mock.get.return_value = {}
        self.assertRaises(
            LookupError, self.drv._get_lun, self.TEST_VOLUME_REF)

        lun_id.side_effect = LookupError()
        self.assertIsNone(self.drv._get_lun(self.TEST_VOLUME_REF))

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_target_name')
    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_targetgroup_name')
    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._lu_exists')
    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_lun')
    def test_do_export(self, get_lun, lu_exists, targetgroup, target):
        target.return_value = 'iqn-0'
        targetgroup.return_value = '1.1.1.1-0'
        lu_exists.return_value = False
        get_lun.return_value = 0
        self.assertEqual(
            {'provider_location': '1.1.1.1:8080,1 iqn-0 0'},
            self.drv._do_export({}, self.TEST_VOLUME_REF))

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_targetgroup_name')
    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._get_lun_id')
    def test_remove_export(self, lun_id, tg_name):
        lun_id.return_value = '0'
        tg_name.return_value = '1.1.1.1-0'
        self.nef_mock.delete.side_effect = exception.NexentaException(
            'No such logical unit in target group')
        self.assertIsNone(
            self.drv.remove_export(self.ctxt, self.TEST_VOLUME_REF))

        self.nef_mock.delete.side_effect = exception.NexentaException(
            'Error')
        self.assertRaises(
            exception.NexentaException,
            self.drv.remove_export, self.ctxt, self.TEST_VOLUME_REF)

        lun_id.side_effect = LookupError()
        self.assertIsNone(
            self.drv.remove_export(self.ctxt, self.TEST_VOLUME_REF))

    def test_update_volume_stats(self):
        self.nef_mock.get.return_value = {
            'bytesAvailable': 10 * units.Gi,
            'bytesUsed': 2 * units.Gi
        }
        location_info = '%(driver)s:%(host)s:%(pool)s/%(group)s' % {
            'driver': self.drv.__class__.__name__,
            'host': self.cfg.nexenta_host,
            'pool': self.cfg.nexenta_volume,
            'group': self.cfg.nexenta_volume_group,
        }
        stats = {
            'vendor_name': 'Nexenta',
            'dedup': self.cfg.nexenta_dataset_dedup,
            'compression': self.cfg.nexenta_dataset_compression,
            'description': self.cfg.nexenta_dataset_description,
            'driver_version': self.drv.VERSION,
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': 10,
            'free_capacity_gb': 8,
            'reserved_percentage': self.cfg.reserved_percentage,
            'QoS_support': False,
            'volume_backend_name': self.drv.backend_name,
            'location_info': location_info,
            'iscsi_target_portal_port': (
                self.cfg.nexenta_iscsi_target_portal_port),
            'nef_url': self.drv.nef.url
        }
        self.drv._update_volume_stats()
        self.assertEqual(stats, self.drv._stats)


class TestNexentaJSONProxy(test.TestCase):

    def __init__(self, method):
        super(TestNexentaJSONProxy, self).__init__(method)

    @patch('requests.Response.close')
    @patch('requests.get')
    @patch('requests.post')
    def test_call(self, post, get, close):
        nef_get = jsonrpc.NexentaJSONProxy(
            'http', '1.1.1.1', '8080', 'user', 'pass', method='get')
        nef_post = jsonrpc.NexentaJSONProxy(
            'http', '1.1.1.1', '8080', 'user', 'pass', method='post')
        data = {'key': 'value'}
        get.return_value = requests.Response()
        post.return_value = requests.Response()

        get.return_value.__setstate__({
            'status_code': 200, '_content': jsonutils.dumps(data)})
        self.assertEqual({'key': 'value'}, nef_get('url'))

        get.return_value.__setstate__({
            'status_code': 201, '_content': ''})
        self.assertEqual('Success', nef_get('url'))

        data2 = {'links': [{'href': 'redirect_url'}]}
        post.return_value.__setstate__({
            'status_code': 202, '_content': jsonutils.dumps(data2)})
        get.return_value.__setstate__({
            'status_code': 200, '_content': jsonutils.dumps(data)})
        self.assertEqual({'key': 'value'}, nef_post('url'))

        get.return_value.__setstate__({
            'status_code': 200, '_content': ''})
        self.assertEqual('Success', nef_post('url', data))

        get.return_value.__setstate__({
            'status_code': 400,
            '_content': jsonutils.dumps({'code': 'ENOENT'})})
        self.assertRaises(exception.NexentaException, lambda: nef_get('url'))
