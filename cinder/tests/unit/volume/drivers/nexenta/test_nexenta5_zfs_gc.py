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
Unit tests for NexentaStor 5 ZFS garbage collector
"""

from cinder import exception
from cinder import test
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta.ns5 import zfs_garbage_collector
import mock


class GC(zfs_garbage_collector.ZFSGarbageCollectorMixIn):
    def __init__(self):
        super(GC, self).__init__()
        self.nef = jsonrpc.NexentaJSONProxy('1.1.1.1', 0, 'u', 'p', False)

    def get_delete_snapshot_url(self, zfs_object):
        return 'delete_snapshot/' + zfs_object

    def get_original_snapshot_url(self, zfs_object):
        return 'original_snapshot/' + zfs_object

    def get_delete_volume_url(self, zfs_object):
        return 'delete_volume/' + zfs_object


class TestNexentaJSONProxy(test.TestCase):

    def setUp(self):
        super(TestNexentaJSONProxy, self).setUp()
        self.nef_mock = mock.Mock()
        self.mock_object(jsonrpc, 'NexentaJSONProxy',
                         return_value=self.nef_mock)
        self.gc = GC()

    def test_delete_volume__marked_as_garbage(self):
        vol = 'pool/group/vol-1'
        self.gc.mark_as_garbage(vol)
        self.gc.collect_zfs_garbage(vol)
        self.nef_mock.delete.assert_called_once_with(
            self.gc.get_delete_volume_url(vol))

    def test_delete__not_marked_as_garbage(self):
        self.gc.mark_as_garbage('pool/group/vol-1')
        self.gc.mark_as_garbage('pool/group/vol-3@snap-5')
        self.gc.collect_zfs_garbage('pool/group/vol-2')
        self.gc.collect_zfs_garbage('pool/group/vol-7@snap-3')
        self.nef_mock.delete.assert_not_called()

    def test_delete_volume__nexenta_error_on_delete(self):
        vol = 'pool/group/vol-1'
        self.gc.mark_as_garbage(vol)
        self.nef_mock.delete.side_effect = exception.NexentaException('Error')
        self.gc.collect_zfs_garbage(vol)

    def test_delete_volume__backend_error_on_delete(self):
        vol = 'pool/group/vol-1'
        self.gc.mark_as_garbage(vol)
        self.nef_mock.delete.side_effect = exception.VolumeBackendAPIException(
            data='Error')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.gc.collect_zfs_garbage, vol)

    def test_delete_snapshot__marked_as_garbage(self):
        vol = 'pool/group/vol-1@snap-1'
        self.gc.mark_as_garbage(vol)
        self.gc.collect_zfs_garbage(vol)
        self.nef_mock.delete.assert_called_once_with(
            self.gc.get_delete_snapshot_url(vol))

    def test_delete_snapshot__nexenta_error_on_delete(self):
        vol = 'pool/group/vol-1@snap-1'
        self.gc.mark_as_garbage(vol)
        self.nef_mock.delete.side_effect = exception.NexentaException('Error')
        self.gc.collect_zfs_garbage(vol)

    def test_delete_snapshot__backend_error_on_delete(self):
        vol = 'pool/group/vol-1@snap-1'
        self.gc.mark_as_garbage(vol)
        self.nef_mock.delete.side_effect = exception.VolumeBackendAPIException(
            data='Error')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.gc.collect_zfs_garbage, vol)

    def test_delete_tree(self):
        get_original_snapshot_url = self.gc.get_original_snapshot_url

        class SideEffect(object):
            def __call__(self, *args, **kwargs):
                if get_original_snapshot_url('pool/group/volume-2') in args[0]:
                    return {'originalSnapshot': 'pool/group/volume-1@snap-1'}
                return {'originalSnapshot': ''}

        self.nef_mock.get.side_effect = SideEffect()
        self.gc.mark_as_garbage('pool/group/volume-1')
        self.gc.mark_as_garbage('pool/group/volume-1@snap-1')
        self.gc.mark_as_garbage('pool/group/volume-2')
        self.gc.collect_zfs_garbage('pool/group/volume-2')

        self.assertEqual(3, self.nef_mock.delete.call_count)
        self.nef_mock.delete.assert_called_with(
            self.gc.get_delete_volume_url('pool/group/volume-1'))
