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
        self.cfg.nexenta_use_https = False
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
        self.drv._fetch_volumes = lambda: None
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

        self.nef_mock.get.side_effect = exception.NexentaException(
            'fake_exception')
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
        self.drv.collect_zfs_garbage = lambda x: None
        self.nef_mock.delete.side_effect = exception.NexentaException(
            'Failed to destroy snapshot')
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
        crt_vol.side_effect = exception.NexentaException('fake_exception')
        dlt_snap.side_effect = exception.NexentaException('fake_exception')
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

    def test_do_export(self):
        target_name = 'new_target'
        lun = 0

        class GetSideEffect(object):
            def __init__(self):
                self.lm_counter = -1

            def __call__(self, *args, **kwargs):
                # Find out whether the volume is exported
                if 'san/lunMappings?volume=' in args[0]:
                    self.lm_counter += 1
                    # a value for the first call
                    if self.lm_counter == 0:
                        return {'data': []}
                    else:
                        return {'data': [{'lun': lun}]}
                # Get the name of just created target
                elif 'san/iscsi/targets' in args[0]:
                    return {'data': [{'name': target_name}]}

        def post_side_effect(*args, **kwargs):
            if 'san/iscsi/targets' in args[0]:
                return {'data': [{'name': target_name}]}

        self.nef_mock.get.side_effect = GetSideEffect()
        self.nef_mock.post.side_effect = post_side_effect
        res = self.drv._do_export(self.ctxt, self.TEST_VOLUME_REF)
        provider_location = '%(host)s:%(port)s,1 %(name)s %(lun)s' % {
            'host': self.cfg.nexenta_host,
            'port': self.cfg.nexenta_iscsi_target_portal_port,
            'name': target_name,
            'lun': lun,
        }
        expected = {'provider_location': provider_location}
        self.assertEqual(expected, res)

    def test_remove_export(self):
        mapping_id = '1234567890'
        self.nef_mock.get.return_value = {'data': [{'id': mapping_id}]}
        self.drv.remove_export(self.ctxt, self.TEST_VOLUME_REF)
        url = 'san/lunMappings/%s' % mapping_id
        self.nef_mock.delete.assert_called_with(url)

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
