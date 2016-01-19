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
from oslo_utils import units

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
    TEST_SNAPSHOT_REF = {
        'name': TEST_SNAPSHOT_NAME,
        'volume_name': TEST_VOLUME_NAME,
        'volume_id': '1'
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
        self.stubs.Set(jsonrpc, 'NexentaJSONProxy',
                       lambda *_, **__: self.nef_mock)
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

    def check_for_setup_error(self):
        self.nef_mock.get.return_value = {
            'services': {'data': {'iscsit': {'state': 'offline'}}}}
        self.assertRaises(
            exception.NexentaException, self.drv.check_for_setup_error)

    def test_create_volume(self):
        self.drv.create_volume(self.TEST_VOLUME_REF)
        url = 'storage/pools/pool/volumeGroups/dsg/volumes'
        self.nef_mock.post.assert_called_with(url, {
            'name': self.TEST_VOLUME_REF['name'],
            'volumeSize': 1 * units.Gi,
            'volumeBlockSize': 32768,
            'sparseVolume': self.cfg.nexenta_sparse})

    def test_delete_volume(self):
        self.drv.delete_volume(self.TEST_VOLUME_REF)
        url = 'storage/pools/pool/volumeGroups'
        data = {'name': 'dsg', 'volumeBlockSize': 32768}
        self.nef_mock.post.assert_called_with(url, data)

    def test_create_cloned_volume(self):
        self._create_volume_db_entry()
        vol = self.TEST_VOLUME_REF2
        src_vref = self.TEST_VOLUME_REF

        self.drv.create_cloned_volume(vol, src_vref)
        url = 'storage/pools/pool/volumeGroups/dsg/volumes/volume2/promote'
        self.nef_mock.post.assert_called_with(url)

    def test_create_snapshot(self):
        self._create_volume_db_entry()
        self.drv.create_snapshot(self.TEST_SNAPSHOT_REF)
        url = 'storage/pools/pool/volumeGroups/dsg/volumes/volume-1/snapshots'
        self.nef_mock.post.assert_called_with(
            url, {'name': 'snapshot1'})

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
        target.return_value = {'name': 'iqn-0'}
        self.assertEqual('iqn-0', self.drv._create_target(0))

    @patch('cinder.volume.drivers.nexenta.ns5.iscsi.'
           'NexentaISCSIDriver._create_target')
    def test_get_target_name(self, target_name):
        self._create_volume_db_entry()
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
           'NexentaISCSIDriver._get_targetgroup_name')
    def test_get_lun_id(self, targetgroup):
        targetgroup.return_value = '1.1.1.1-0'
        self.nef_mock.get.return_value = {'data': [{'guid': '0'}]}
        self.assertEqual('0', self.drv._get_lun_id(self.TEST_VOLUME_REF))

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
