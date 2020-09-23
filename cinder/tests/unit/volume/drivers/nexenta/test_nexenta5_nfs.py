# Copyright 2019 Nexenta Systems, Inc.
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
"""Unit tests for OpenStack Cinder volume driver."""
import os
from unittest import mock

from oslo_utils.secretutils import md5
from oslo_utils import units

from cinder import context
from cinder import db
from cinder.tests.unit.consistencygroup.fake_cgsnapshot import (
    fake_cgsnapshot_obj as fake_cgsnapshot)
from cinder.tests.unit.consistencygroup.fake_consistencygroup import (
    fake_consistencyobject_obj as fake_cgroup)
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.fake_snapshot import fake_snapshot_obj as fake_snapshot
from cinder.tests.unit.fake_volume import fake_volume_obj as fake_volume
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from cinder.volume.drivers.nexenta.ns5 import nfs


class TestNexentaNfsDriver(test.TestCase):

    def setUp(self):
        super(TestNexentaNfsDriver, self).setUp()
        self.ctxt = context.get_admin_context()
        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.volume_backend_name = 'nexenta_nfs'
        self.cfg.nexenta_group_snapshot_template = 'group-snapshot-%s'
        self.cfg.nexenta_origin_snapshot_template = 'origin-snapshot-%s'
        self.cfg.nexenta_dataset_description = ''
        self.cfg.nexenta_mount_point_base = '$state_path/mnt'
        self.cfg.nexenta_sparsed_volumes = True
        self.cfg.nexenta_qcow2_volumes = False
        self.cfg.nexenta_dataset_compression = 'on'
        self.cfg.nexenta_dataset_dedup = 'off'
        self.cfg.nfs_mount_point_base = '/mnt/test'
        self.cfg.nfs_mount_attempts = 3
        self.cfg.nas_mount_options = 'vers=4'
        self.cfg.reserved_percentage = 20
        self.cfg.nexenta_use_https = False
        self.cfg.driver_ssl_cert_verify = False
        self.cfg.nexenta_user = 'user'
        self.cfg.nexenta_password = 'pass'
        self.cfg.max_over_subscription_ratio = 20.0
        self.cfg.nas_host = '1.1.1.2'
        self.cfg.nexenta_rest_address = '1.1.1.1'
        self.cfg.nexenta_rest_port = 8443
        self.cfg.nexenta_rest_backoff_factor = 1
        self.cfg.nexenta_rest_retry_count = 3
        self.cfg.nexenta_rest_connect_timeout = 1
        self.cfg.nexenta_rest_read_timeout = 1
        self.cfg.nas_share_path = 'pool/share'
        self.cfg.nfs_mount_options = '-o vers=4'
        self.cfg.safe_get = self.fake_safe_get
        self.nef_mock = mock.Mock()
        self.mock_object(jsonrpc, 'NefRequest',
                         return_value=self.nef_mock)
        self.drv = nfs.NexentaNfsDriver(configuration=self.cfg)
        self.drv.db = db
        self.drv.do_setup(self.ctxt)

    def fake_safe_get(self, key):
        try:
            value = getattr(self.cfg, key)
        except AttributeError:
            value = None
        return value

    def test_do_setup(self):
        self.assertIsNone(self.drv.do_setup(self.ctxt))

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefNfs.get')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefServices.get')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.set')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.get')
    def test_check_for_setup_error(self, get_filesystem,
                                   set_filesystem,
                                   get_service, get_nfs):
        get_filesystem.return_value = {
            'mountPoint': '/path/to/volume',
            'nonBlockingMandatoryMode': False,
            'smartCompression': False,
            'isMounted': True
        }
        get_service.return_value = {
            'state': 'online'
        }
        get_nfs.return_value = {
            'shareState': 'online'
        }
        self.assertIsNone(self.drv.check_for_setup_error())
        get_filesystem.assert_called_with(self.drv.root_path)
        set_filesystem.assert_not_called()
        get_service.assert_called_with('nfs')
        get_nfs.assert_called_with(self.drv.root_path)
        get_filesystem.return_value = {
            'mountPoint': '/path/to/volume',
            'nonBlockingMandatoryMode': True,
            'smartCompression': True,
            'isMounted': True
        }
        set_filesystem.return_value = {}
        payload = {
            'nonBlockingMandatoryMode': False,
            'smartCompression': False
        }
        self.assertIsNone(self.drv.check_for_setup_error())
        get_filesystem.assert_called_with(self.drv.root_path)
        set_filesystem.assert_called_with(self.drv.root_path, payload)
        get_service.assert_called_with('nfs')
        get_nfs.assert_called_with(self.drv.root_path)
        get_filesystem.return_value = {
            'mountPoint': '/path/to/volume',
            'nonBlockingMandatoryMode': False,
            'smartCompression': True,
            'isMounted': True
        }
        payload = {
            'smartCompression': False
        }
        set_filesystem.return_value = {}
        self.assertIsNone(self.drv.check_for_setup_error())
        get_filesystem.assert_called_with(self.drv.root_path)
        set_filesystem.assert_called_with(self.drv.root_path, payload)
        get_service.assert_called_with('nfs')
        get_nfs.assert_called_with(self.drv.root_path)
        get_filesystem.return_value = {
            'mountPoint': '/path/to/volume',
            'nonBlockingMandatoryMode': True,
            'smartCompression': False,
            'isMounted': True
        }
        payload = {
            'nonBlockingMandatoryMode': False
        }
        set_filesystem.return_value = {}
        self.assertIsNone(self.drv.check_for_setup_error())
        get_filesystem.assert_called_with(self.drv.root_path)
        set_filesystem.assert_called_with(self.drv.root_path, payload)
        get_service.assert_called_with('nfs')
        get_nfs.assert_called_with(self.drv.root_path)
        get_filesystem.return_value = {
            'mountPoint': 'none',
            'nonBlockingMandatoryMode': False,
            'smartCompression': False,
            'isMounted': False
        }
        self.assertRaises(jsonrpc.NefException,
                          self.drv.check_for_setup_error)
        get_filesystem.return_value = {
            'mountPoint': '/path/to/volume',
            'nonBlockingMandatoryMode': False,
            'smartCompression': False,
            'isMounted': False
        }
        self.assertRaises(jsonrpc.NefException,
                          self.drv.check_for_setup_error)
        get_service.return_value = {
            'state': 'online'
        }
        self.assertRaises(jsonrpc.NefException,
                          self.drv.check_for_setup_error)
        get_nfs.return_value = {
            'shareState': 'offline'
        }
        self.assertRaises(jsonrpc.NefException,
                          self.drv.check_for_setup_error)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._unmount_volume')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.delete')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.set')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._create_regular_file')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._create_sparsed_file')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.local_path')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._mount_volume')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._set_volume_acl')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.create')
    def test_create_volume(self, create_volume, set_volume_acl,
                           mount_volume, get_volume_local_path,
                           create_sparsed_file, created_regular_file,
                           set_volume, delete_volume, umount_volume):
        volume = fake_volume(self.ctxt)
        local_path = '/local/volume/path'
        create_volume.return_value = {}
        set_volume_acl.return_value = {}
        mount_volume.return_value = True
        get_volume_local_path.return_value = local_path
        create_sparsed_file.return_value = True
        created_regular_file.return_value = True
        set_volume.return_value = {}
        delete_volume.return_value = {}
        umount_volume.return_value = {}
        with mock.patch.object(self.drv, 'sparsed_volumes', True):
            self.assertIsNone(self.drv.create_volume(volume))
            create_sparsed_file.assert_called_with(local_path, volume['size'])
        with mock.patch.object(self.drv, 'sparsed_volumes', False):
            self.assertIsNone(self.drv.create_volume(volume))
            created_regular_file.assert_called_with(local_path, volume['size'])
        volume_path = self.drv._get_volume_path(volume)
        payload = {
            'path': volume_path,
            'compressionMode': 'off'
        }
        create_volume.assert_called_with(payload)
        set_volume_acl.assert_called_with(volume)
        payload = {'compressionMode': self.cfg.nexenta_dataset_compression}
        set_volume.assert_called_with(volume_path, payload)
        umount_volume.assert_called_with(volume)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._unmount_volume')
    @mock.patch('cinder.volume.drivers.remotefs.'
                'RemoteFSDriver.copy_image_to_volume')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._mount_volume')
    def test_copy_image_to_volume(self, mount_volume,
                                  copy_image_to_volume,
                                  unmount_volume):
        volume = fake_volume(self.ctxt)
        image_service = fake_image.FakeImageService()
        image = image_service.images[fake.IMAGE_ID]
        mount_volume.return_value = True
        copy_image_to_volume.return_value = True
        unmount_volume.return_value = True
        self.drv.copy_image_to_volume(self.ctxt, volume,
                                      image_service,
                                      image['id'])
        mount_volume.assert_called_with(volume)
        copy_image_to_volume.assert_called_with(self.ctxt, volume,
                                                image_service,
                                                image['id'])
        unmount_volume.assert_called_with(volume)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._unmount_volume')
    @mock.patch('cinder.volume.drivers.remotefs.'
                'RemoteFSSnapDriverDistributed.copy_volume_to_image')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._mount_volume')
    def test_copy_volume_to_image(self, mount_volume,
                                  copy_volume_to_image,
                                  unmount_volume):
        volume = fake_volume(self.ctxt)
        image_service = fake_image.FakeImageService()
        image = image_service.images[fake.IMAGE_ID]
        mount_volume.return_value = True
        copy_volume_to_image.return_value = True
        unmount_volume.return_value = True
        self.drv.copy_volume_to_image(self.ctxt, volume,
                                      image_service, image)
        mount_volume.assert_called_with(volume)
        copy_volume_to_image.assert_called_with(self.ctxt, volume,
                                                image_service, image)
        unmount_volume.assert_called_with(volume)

    @mock.patch('os.rmdir')
    @mock.patch('cinder.privsep.fs.umount')
    @mock.patch('os_brick.remotefs.remotefs.'
                'RemoteFsClient._read_mounts')
    @mock.patch('cinder.volume.drivers.nfs.'
                'NfsDriver._get_mount_point_for_share')
    def test__ensure_share_unmounted(self, get_mount_point,
                                     list_mount_points,
                                     unmount_filesystem,
                                     remove_mount_point):
        mount_point = '/mount/point1'
        get_mount_point.return_value = mount_point
        list_mount_points.return_value = [
            mount_point,
            '/mount/point2',
            '/mount/point3'
        ]
        unmount_filesystem.return_value = True
        remove_mount_point.return_value = True
        share = '1.1.1.1:/path/to/volume'
        self.assertIsNone(self.drv._ensure_share_unmounted(share))
        get_mount_point.assert_called_with(share)
        unmount_filesystem.assert_called_with(mount_point)
        remove_mount_point.assert_called_with(mount_point)

    @mock.patch('cinder.volume.drivers.nfs.'
                'NfsDriver._ensure_share_mounted')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.get')
    def test__mount_volume(self, get_filesystem, mount_share):
        volume = fake_volume(self.ctxt)
        mount_point = '/path/to/volume'
        get_filesystem.return_value = {
            'mountPoint': mount_point,
            'isMounted': True
        }
        mount_share.return_value = True
        self.assertIsNone(self.drv._mount_volume(volume))
        path = self.drv._get_volume_path(volume)
        payload = {'fields': 'mountPoint,isMounted'}
        get_filesystem.assert_called_with(path, payload)
        share = '%s:%s' % (self.drv.nas_host, mount_point)
        mount_share.assert_called_with(share)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._ensure_share_unmounted')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._get_volume_share')
    def test__unmount_volume(self, get_share, unmount_share):
        volume = fake_volume(self.ctxt)
        mount_point = '/path/to/volume'
        share = '%s:%s' % (self.drv.nas_host, mount_point)
        get_share.return_value = share
        unmount_share.return_value = True
        self.assertIsNone(self.drv._unmount_volume(volume))
        get_share.assert_called_with(volume)
        unmount_share.assert_called_with(share)

    @mock.patch('cinder.volume.drivers.remotefs.'
                'RemoteFSDriver._create_qcow2_file')
    @mock.patch('cinder.volume.drivers.remotefs.'
                'RemoteFSDriver._create_sparsed_file')
    def test__create_sparsed_file(self, create_sparsed_file,
                                  create_qcow2_file):
        create_sparsed_file.return_value = True
        create_qcow2_file.return_value = True
        path = '/path/to/file'
        size = 1
        with mock.patch.object(self.cfg, 'nexenta_qcow2_volumes', True):
            self.assertIsNone(self.drv._create_sparsed_file(path, size))
            create_qcow2_file.assert_called_with(path, size)
        with mock.patch.object(self.cfg, 'nexenta_qcow2_volumes', False):
            self.assertIsNone(self.drv._create_sparsed_file(path, size))
            create_sparsed_file.assert_called_with(path, size)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.delete_volume')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefHpr.delete')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefHpr.get')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefHpr.start')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefHpr.create')
    def test_migrate_volume(self, create_service,
                            start_service, get_service,
                            delete_service, delete_volume):
        create_service.return_value = {}
        start_service.return_value = {}
        get_service.return_value = {
            'state': 'disabled'
        }
        delete_service.return_value = {}
        delete_volume.return_value = {}
        volume = fake_volume(self.ctxt)
        dst_host = '4.4.4.4'
        dst_port = 8443
        dst_path = 'tank/nfs'
        location_info = 'NexentaNfsDriver:%s:/%s' % (dst_host, dst_path)
        host = {
            'host': 'stack@nexenta_nfs#fake_nfs',
            'capabilities': {
                'vendor_name': 'Nexenta',
                'nef_url': dst_host,
                'nef_port': dst_port,
                'storage_protocol': 'NFS',
                'free_capacity_gb': 32,
                'location_info': location_info
            }
        }
        result = self.drv.migrate_volume(self.ctxt, volume, host)
        expected = (True, None)
        svc = 'cinder-migrate-%s' % volume['name']
        src = self.drv._get_volume_path(volume)
        dst = '%s/%s' % (dst_path, volume['name'])
        payload = {
            'name': svc,
            'sourceDataset': src,
            'destinationDataset': dst,
            'type': 'scheduled',
            'sendShareNfs': True,
            'isSource': True,
            'remoteNode': {
                'host': dst_host,
                'port': dst_port
            }
        }
        create_service.assert_called_with(payload)
        start_service.assert_called_with(svc)
        get_service.assert_called_with(svc)
        payload = {
            'destroySourceSnapshots': True,
            'destroyDestinationSnapshots': True
        }
        delete_service.assert_called_with(svc, payload)
        delete_volume.assert_called_with(volume)
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._unmount_volume')
    def test_terminate_connection(self, unmount_volume):
        unmount_volume.return_value = True
        volume = fake_volume(self.ctxt)
        connector = {
            'initiator': 'iqn:cinder-client',
            'multipath': True
        }
        self.assertIsNone(self.drv.terminate_connection(volume, connector))
        unmount_volume.assert_called_with(volume)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._get_volume_share')
    def test_initialize_connection(self, get_share):
        volume = fake_volume(self.ctxt)
        path = self.drv._get_volume_path(volume)
        share = '%s:/%s' % (self.drv.nas_host, path)
        get_share.return_value = share
        connector = {
            'initiator': 'iqn:cinder-client',
            'multipath': True
        }
        result = self.drv.initialize_connection(volume, connector)
        get_share.assert_called_with(volume)
        base = self.cfg.nexenta_mount_point_base
        expected = {
            'driver_volume_type': 'nfs',
            'mount_point_base': base,
            'data': {
                'export': share,
                'name': 'volume'
            }
        }
        self.assertEqual(expected, result)

    def test_ensure_export(self):
        volume = fake_volume(self.ctxt)
        self.assertIsNone(self.drv.ensure_export(self.ctxt, volume))

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.delete')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._unmount_volume')
    def test_delete_volume(self, unmount_volume, delete_filesystem):
        volume = fake_volume(self.ctxt)
        path = self.drv._get_volume_path(volume)
        unmount_volume.return_value = {}
        delete_filesystem.return_value = {}
        self.assertIsNone(self.drv.delete_volume(volume))
        unmount_volume.assert_called_with(volume)
        payload = {'force': True, 'snapshots': True}
        delete_filesystem.assert_called_with(path, payload)

    @mock.patch('os.rmdir')
    def test__delete(self, rmdir):
        rmdir.return_value = True
        path = '/path/to/volume/mountpoint'
        self.assertIsNone(self.drv._delete(path))
        rmdir.assert_called_with(path)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._unmount_volume')
    @mock.patch('oslo_concurrency.processutils.execute')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.local_path')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._mount_volume')
    def test_extend_volume(self, mount_volume, get_volume_local_path,
                           execute_command, unmount_volume):
        volume = fake_volume(self.ctxt)
        root_helper = 'sudo cinder-rootwrap /etc/cinder/rootwrap.conf'
        local_path = '/path/to/volume/file'
        new_size = volume['size'] * 2
        bs = 1 * units.Mi
        seek = volume['size'] * units.Ki
        count = (new_size - volume['size']) * units.Ki
        mount_volume.return_value = True
        get_volume_local_path.return_value = local_path
        execute_command.return_value = True
        unmount_volume.return_value = True
        with mock.patch.object(self.drv, 'sparsed_volumes', False):
            self.assertIsNone(self.drv.extend_volume(volume, new_size))
            execute_command.assert_called_with('dd', 'if=/dev/zero',
                                               'of=%s' % local_path,
                                               'bs=%d' % bs,
                                               'seek=%d' % seek,
                                               'count=%d' % count,
                                               run_as_root=True,
                                               root_helper=root_helper)
        with mock.patch.object(self.drv, 'sparsed_volumes', True):
            self.assertIsNone(self.drv.extend_volume(volume, new_size))
            execute_command.assert_called_with('truncate', '-s',
                                               '%dG' % new_size,
                                               local_path,
                                               run_as_root=True,
                                               root_helper=root_helper)
        mount_volume.assert_called_with(volume)
        unmount_volume.assert_called_with(volume)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.create')
    def test_create_snapshot(self, create_snapshot):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        create_snapshot.return_value = {}
        self.assertIsNone(self.drv.create_snapshot(snapshot))
        path = self.drv._get_snapshot_path(snapshot)
        payload = {'path': path}
        create_snapshot.assert_called_with(payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.delete')
    def test_delete_snapshot(self, delete_snapshot):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        delete_snapshot.return_value = {}
        self.assertIsNone(self.drv.delete_snapshot(snapshot))
        path = self.drv._get_snapshot_path(snapshot)
        payload = {'defer': True}
        delete_snapshot.assert_called_with(path, payload)

    def test_snapshot_revert_use_temp_snapshot(self):
        result = self.drv.snapshot_revert_use_temp_snapshot()
        expected = False
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.rollback')
    def test_revert_to_snapshot(self, rollback_volume):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        rollback_volume.return_value = {}
        self.assertIsNone(
            self.drv.revert_to_snapshot(self.ctxt, volume, snapshot)
        )
        path = self.drv._get_volume_path(volume)
        payload = {'snapshot': snapshot['name']}
        rollback_volume.assert_called_with(path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.extend_volume')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.mount')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.unmount')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.clone')
    def test_create_volume_from_snapshot(self, clone_snapshot,
                                         unmount_filesystem,
                                         mount_filesystem,
                                         extend_volume):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        clone_size = 10
        clone_spec = {
            'id': fake.VOLUME2_ID,
            'size': clone_size
        }
        clone = fake_volume(self.ctxt, **clone_spec)
        snapshot_path = self.drv._get_snapshot_path(snapshot)
        clone_path = self.drv._get_volume_path(clone)
        clone_snapshot.return_value = {}
        unmount_filesystem.return_value = {}
        mount_filesystem.return_value = {}
        extend_volume.return_value = None
        self.assertIsNone(
            self.drv.create_volume_from_snapshot(clone, snapshot)
        )
        clone_payload = {'targetPath': clone_path}
        clone_snapshot.assert_called_with(snapshot_path, clone_payload)
        unmount_filesystem.assert_called_with(clone_path)
        mount_filesystem.assert_called_with(clone_path)
        extend_volume.assert_called_with(clone, clone_size)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.delete_snapshot')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.create_volume_from_snapshot')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.create_snapshot')
    def test_create_cloned_volume(self, create_snapshot, create_volume,
                                  delete_snapshot):
        volume = fake_volume(self.ctxt)
        clone_spec = {'id': fake.VOLUME2_ID}
        clone = fake_volume(self.ctxt, **clone_spec)
        create_snapshot.return_value = {}
        create_volume.return_value = {}
        delete_snapshot.return_value = {}
        self.assertIsNone(self.drv.create_cloned_volume(clone, volume))
        snapshot = {
            'name': self.drv.origin_snapshot_template % clone['id'],
            'volume_id': volume['id'],
            'volume_name': volume['name'],
            'volume_size': volume['size']
        }
        create_snapshot.assert_called_with(snapshot)
        create_volume.assert_called_with(clone, snapshot)
        create_volume.side_effect = jsonrpc.NefException({
            'message': 'Failed to create volume',
            'code': 'EBUSY'
        })
        self.assertRaises(jsonrpc.NefException,
                          self.drv.create_cloned_volume,
                          clone, volume)
        create_snapshot.side_effect = jsonrpc.NefException({
            'message': 'Failed to open dataset',
            'code': 'ENOENT'
        })
        self.assertRaises(jsonrpc.NefException,
                          self.drv.create_cloned_volume,
                          clone, volume)

    def test_create_consistencygroup(self):
        cgroup = fake_cgroup(self.ctxt)
        result = self.drv.create_consistencygroup(self.ctxt, cgroup)
        expected = {}
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.delete_volume')
    def test_delete_consistencygroup(self, delete_volume):
        cgroup = fake_cgroup(self.ctxt)
        volume1 = fake_volume(self.ctxt)
        volume2_spec = {'id': fake.VOLUME2_ID}
        volume2 = fake_volume(self.ctxt, **volume2_spec)
        volumes = [volume1, volume2]
        delete_volume.return_value = {}
        result = self.drv.delete_consistencygroup(self.ctxt,
                                                  cgroup,
                                                  volumes)
        expected = ({}, [])
        self.assertEqual(expected, result)

    def test_update_consistencygroup(self):
        cgroup = fake_cgroup(self.ctxt)
        volume1 = fake_volume(self.ctxt)
        volume2_spec = {'id': fake.VOLUME2_ID}
        volume2 = fake_volume(self.ctxt, **volume2_spec)
        volume3_spec = {'id': fake.VOLUME3_ID}
        volume3 = fake_volume(self.ctxt, **volume3_spec)
        volume4_spec = {'id': fake.VOLUME4_ID}
        volume4 = fake_volume(self.ctxt, **volume4_spec)
        add_volumes = [volume1, volume2]
        remove_volumes = [volume3, volume4]
        result = self.drv.update_consistencygroup(self.ctxt,
                                                  cgroup,
                                                  add_volumes,
                                                  remove_volumes)
        expected = ({}, [], [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.delete')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.rename')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.create')
    def test_create_cgsnapshot(self, create_snapshot,
                               rename_snapshot,
                               delete_snapshot):
        cgsnapshot = fake_cgsnapshot(self.ctxt)
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        snapshots = [snapshot]
        cgsnapshot_name = (
            self.cfg.nexenta_group_snapshot_template % cgsnapshot['id'])
        cgsnapshot_path = '%s@%s' % (self.drv.root_path, cgsnapshot_name)
        snapshot_path = '%s/%s@%s' % (self.drv.root_path,
                                      snapshot['volume_name'],
                                      cgsnapshot_name)
        create_snapshot.return_value = {}
        rename_snapshot.return_value = {}
        delete_snapshot.return_value = {}
        result = self.drv.create_cgsnapshot(self.ctxt,
                                            cgsnapshot,
                                            snapshots)
        create_payload = {'path': cgsnapshot_path, 'recursive': True}
        create_snapshot.assert_called_with(create_payload)
        rename_payload = {'newName': snapshot['name']}
        rename_snapshot.assert_called_with(snapshot_path, rename_payload)
        delete_payload = {'defer': True, 'recursive': True}
        delete_snapshot.assert_called_with(cgsnapshot_path, delete_payload)
        expected = ({}, [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.delete_snapshot')
    def test_delete_cgsnapshot(self, delete_snapshot):
        cgsnapshot = fake_cgsnapshot(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        volume = fake_volume(self.ctxt)
        snapshot.volume = volume
        snapshots = [snapshot]
        delete_snapshot.return_value = {}
        result = self.drv.delete_cgsnapshot(self.ctxt,
                                            cgsnapshot,
                                            snapshots)
        delete_snapshot.assert_called_with(snapshot)
        expected = ({}, [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.create_volume_from_snapshot')
    def test_create_consistencygroup_from_src_snapshots(self, create_volume):
        cgroup = fake_cgroup(self.ctxt)
        cgsnapshot = fake_cgsnapshot(self.ctxt)
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        snapshots = [snapshot]
        clone_spec = {'id': fake.VOLUME2_ID}
        clone = fake_volume(self.ctxt, **clone_spec)
        clones = [clone]
        create_volume.return_value = {}
        result = self.drv.create_consistencygroup_from_src(self.ctxt, cgroup,
                                                           clones, cgsnapshot,
                                                           snapshots, None,
                                                           None)
        create_volume.assert_called_with(clone, snapshot)
        expected = ({}, [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.delete')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.create_volume_from_snapshot')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.create')
    def test_create_consistencygroup_from_src_volumes(self, create_snapshot,
                                                      create_volume,
                                                      delete_snapshot):
        src_cgroup = fake_cgroup(self.ctxt)
        dst_cgroup_spec = {'id': fake.CONSISTENCY_GROUP2_ID}
        dst_cgroup = fake_cgroup(self.ctxt, **dst_cgroup_spec)
        src_volume = fake_volume(self.ctxt)
        src_volumes = [src_volume]
        dst_volume_spec = {'id': fake.VOLUME2_ID}
        dst_volume = fake_volume(self.ctxt, **dst_volume_spec)
        dst_volumes = [dst_volume]
        create_snapshot.return_value = {}
        create_volume.return_value = {}
        delete_snapshot.return_value = {}
        result = self.drv.create_consistencygroup_from_src(self.ctxt,
                                                           dst_cgroup,
                                                           dst_volumes,
                                                           None, None,
                                                           src_cgroup,
                                                           src_volumes)
        snapshot_name = (
            self.cfg.nexenta_origin_snapshot_template % dst_cgroup['id'])
        snapshot_path = '%s@%s' % (self.drv.root_path, snapshot_name)
        create_payload = {'path': snapshot_path, 'recursive': True}
        create_snapshot.assert_called_with(create_payload)
        snapshot = {
            'name': snapshot_name,
            'volume_id': src_volume['id'],
            'volume_name': src_volume['name'],
            'volume_size': src_volume['size']
        }
        create_volume.assert_called_with(dst_volume, snapshot)
        delete_payload = {'defer': True, 'recursive': True}
        delete_snapshot.assert_called_with(snapshot_path, delete_payload)
        expected = ({}, [])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._get_volume_share')
    def test__local_volume_dir(self, get_share):
        volume = fake_volume(self.ctxt)
        share = '1.1.1.1:/path/to/share'
        get_share.return_value = share
        result = self.drv._local_volume_dir(volume)
        get_share.assert_called_with(volume)
        share = share.encode('utf-8')
        digest = md5(share, usedforsecurity=False).hexdigest()
        expected = os.path.join(self.cfg.nexenta_mount_point_base, digest)
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._local_volume_dir')
    def test_local_path(self, get_local):
        volume = fake_volume(self.ctxt)
        local_dir = '/path/to'
        get_local.return_value = local_dir
        result = self.drv.local_path(volume)
        get_local.assert_called_with(volume)
        expected = os.path.join(local_dir, 'volume')
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.acl')
    def test__set_volume_acl(self, set_acl):
        volume = fake_volume(self.ctxt)
        set_acl.return_value = {}
        path = self.drv._get_volume_path(volume)
        payload = {
            'type': 'allow',
            'principal': 'everyone@',
            'permissions': ['full_set'],
            'flags': ['file_inherit', 'dir_inherit']
        }
        self.assertIsNone(self.drv._set_volume_acl(volume))
        set_acl.assert_called_with(path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.get')
    def test__get_volume_share(self, get_filesystem):
        volume = fake_volume(self.ctxt)
        path = self.drv._get_volume_path(volume)
        mount_point = '/path/to'
        get_filesystem.return_value = {'mountPoint': mount_point}
        result = self.drv._get_volume_share(volume)
        payload = {'fields': 'mountPoint'}
        get_filesystem.assert_called_with(path, payload)
        expected = '%s:%s' % (self.drv.nas_host, mount_point)
        self.assertEqual(expected, result)

    def test__get_volume_path(self):
        volume = fake_volume(self.ctxt)
        result = self.drv._get_volume_path(volume)
        expected = '%s/%s' % (self.drv.root_path, volume['name'])
        self.assertEqual(expected, result)

    def test__get_snapshot_path(self):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        result = self.drv._get_snapshot_path(snapshot)
        expected = '%s/%s@%s' % (self.drv.root_path,
                                 snapshot['volume_name'],
                                 snapshot['name'])
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.get')
    def test_get_volume_stats(self, get_filesystem):
        available = 100
        used = 75
        get_filesystem.return_value = {
            'mountPoint': '/path/to',
            'bytesAvailable': available * units.Gi,
            'bytesUsed': used * units.Gi
        }
        result = self.drv.get_volume_stats(True)
        payload = {'fields': 'mountPoint,bytesAvailable,bytesUsed'}
        get_filesystem.assert_called_with(self.drv.root_path, payload)
        self.assertEqual(self.drv._stats, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.get')
    def test_update_volume_stats(self, get_filesystem):
        available = 8
        used = 2
        share = '%s:/%s' % (self.drv.nas_host, self.drv.root_path)
        get_filesystem.return_value = {
            'mountPoint': '/%s' % self.drv.root_path,
            'bytesAvailable': available * units.Gi,
            'bytesUsed': used * units.Gi
        }
        location_info = '%(driver)s:%(share)s' % {
            'driver': self.drv.__class__.__name__,
            'share': share
        }
        expected = {
            'vendor_name': 'Nexenta',
            'dedup': self.cfg.nexenta_dataset_dedup,
            'compression': self.cfg.nexenta_dataset_compression,
            'description': self.cfg.nexenta_dataset_description,
            'nef_url': self.cfg.nexenta_rest_address,
            'nef_port': self.cfg.nexenta_rest_port,
            'driver_version': self.drv.VERSION,
            'storage_protocol': 'NFS',
            'sparsed_volumes': self.cfg.nexenta_sparsed_volumes,
            'total_capacity_gb': used + available,
            'free_capacity_gb': available,
            'reserved_percentage': self.cfg.reserved_percentage,
            'QoS_support': False,
            'multiattach': True,
            'consistencygroup_support': True,
            'consistent_group_snapshot_enabled': True,
            'volume_backend_name': self.cfg.volume_backend_name,
            'location_info': location_info,
            'nfs_mount_point_base': self.cfg.nexenta_mount_point_base
        }
        self.assertIsNone(self.drv._update_volume_stats())
        self.assertEqual(expected, self.drv._stats)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.list')
    def test__get_existing_volume(self, list_filesystems):
        volume = fake_volume(self.ctxt)
        parent = self.drv.root_path
        name = volume['name']
        path = self.drv._get_volume_path(volume)
        list_filesystems.return_value = [{
            'name': name,
            'path': path
        }]
        result = self.drv._get_existing_volume({'source-name': name})
        payload = {
            'path': path,
            'parent': parent,
            'fields': 'path',
            'recursive': False
        }
        list_filesystems.assert_called_with(payload)
        expected = {
            'name': name,
            'path': path
        }
        self.assertEqual(expected, result)

    def test__check_already_managed_snapshot(self):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        result = self.drv._check_already_managed_snapshot(snapshot)
        expected = False
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.list')
    def test__get_existing_snapshot(self, list_snapshots):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        name = snapshot['name']
        path = self.drv._get_snapshot_path(snapshot)
        parent = self.drv._get_volume_path(volume)
        list_snapshots.return_value = [{
            'name': name,
            'path': path
        }]
        payload = {'source-name': name}
        result = self.drv._get_existing_snapshot(snapshot, payload)
        payload = {
            'parent': parent,
            'fields': 'name,path',
            'recursive': False,
            'name': name
        }
        list_snapshots.assert_called_with(payload)
        expected = {
            'name': name,
            'path': path,
            'volume_name': volume['name'],
            'volume_size': volume['size']
        }
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.rename')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._get_existing_volume')
    def test_manage_existing(self, get_existing_volume, rename_volume):
        existing_volume = fake_volume(self.ctxt)
        manage_volume_spec = {'id': fake.VOLUME2_ID}
        manage_volume = fake_volume(self.ctxt, **manage_volume_spec)
        existing_name = existing_volume['name']
        existing_path = self.drv._get_volume_path(existing_volume)
        manage_path = self.drv._get_volume_path(manage_volume)
        get_existing_volume.return_value = {
            'name': existing_name,
            'path': existing_path
        }
        rename_volume.return_value = {}
        payload = {'source-name': existing_name}
        self.assertIsNone(self.drv.manage_existing(manage_volume, payload))
        get_existing_volume.assert_called_with(payload)
        payload = {'newPath': manage_path}
        rename_volume.assert_called_with(existing_path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._unmount_volume')
    @mock.patch('os.path.getsize')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver.local_path')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._mount_volume')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._set_volume_acl')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._get_existing_volume')
    def test_manage_existing_get_size(self, get_volume, set_acl,
                                      mount_volume, get_local,
                                      get_size, unmount_volume):
        volume = fake_volume(self.ctxt)
        name = volume['name']
        size = volume['size']
        path = self.drv._get_volume_path(volume)
        get_volume.return_value = {
            'name': name,
            'path': path
        }
        set_acl.return_value = {}
        mount_volume.return_value = True
        get_local.return_value = '/path/to/volume/file'
        get_size.return_value = size * units.Gi
        unmount_volume.return_value = True
        payload = {'source-name': name}
        result = self.drv.manage_existing_get_size(volume, payload)
        expected = size
        self.assertEqual(expected, result)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefFilesystems.list')
    def test_get_manageable_volumes(self, list_filesystems):
        volume = fake_volume(self.ctxt)
        volumes = [volume]
        size = volume['size']
        path = self.drv._get_volume_path(volume)
        guid = 12345
        parent = self.drv.root_path
        list_filesystems.return_value = [{
            'guid': guid,
            'parent': parent,
            'path': path,
            'bytesUsed': size * units.Gi
        }]
        result = self.drv.get_manageable_volumes(volumes, None, 1,
                                                 0, 'size', 'asc')
        payload = {
            'parent': parent,
            'fields': 'guid,parent,path,bytesUsed',
            'recursive': False
        }
        list_filesystems.assert_called_with(payload)
        expected = [{
            'cinder_id': volume['id'],
            'extra_info': None,
            'reason_not_safe': 'Volume already managed',
            'reference': {
                'source-guid': guid,
                'source-name': volume['name']
            },
            'safe_to_manage': False,
            'size': volume['size']
        }]
        self.assertEqual(expected, result)

    def test_unmanage(self):
        volume = fake_volume(self.ctxt)
        self.assertIsNone(self.drv.unmanage(volume))

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.rename')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._get_existing_snapshot')
    def test_manage_existing_snapshot(self, get_existing_snapshot,
                                      rename_snapshot):
        volume = fake_volume(self.ctxt)
        existing_snapshot = fake_snapshot(self.ctxt)
        existing_snapshot.volume = volume
        manage_snapshot_spec = {'id': fake.SNAPSHOT2_ID}
        manage_snapshot = fake_snapshot(self.ctxt, **manage_snapshot_spec)
        manage_snapshot.volume = volume
        existing_name = existing_snapshot['name']
        manage_name = manage_snapshot['name']
        volume_name = volume['name']
        volume_size = volume['size']
        existing_path = self.drv._get_snapshot_path(existing_snapshot)
        get_existing_snapshot.return_value = {
            'name': existing_name,
            'path': existing_path,
            'volume_name': volume_name,
            'volume_size': volume_size
        }
        rename_snapshot.return_value = {}
        payload = {'source-name': existing_name}
        self.assertIsNone(
            self.drv.manage_existing_snapshot(manage_snapshot, payload)
        )
        get_existing_snapshot.assert_called_with(manage_snapshot, payload)
        payload = {'newName': manage_name}
        rename_snapshot.assert_called_with(existing_path, payload)

    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'nfs.NexentaNfsDriver._get_existing_snapshot')
    def test_manage_existing_snapshot_get_size(self, get_snapshot):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        snapshot_name = snapshot['name']
        volume_name = volume['name']
        volume_size = volume['size']
        snapshot_path = self.drv._get_snapshot_path(snapshot)
        get_snapshot.return_value = {
            'name': snapshot_name,
            'path': snapshot_path,
            'volume_name': volume_name,
            'volume_size': volume_size
        }
        payload = {'source-name': snapshot_name}
        result = self.drv.manage_existing_snapshot_get_size(volume, payload)
        expected = volume['size']
        self.assertEqual(expected, result)

    @mock.patch('cinder.objects.VolumeList.get_all_by_host')
    @mock.patch('cinder.volume.drivers.nexenta.ns5.'
                'jsonrpc.NefSnapshots.list')
    def test_get_manageable_snapshots(self, list_snapshots, list_volumes):
        volume = fake_volume(self.ctxt)
        volumes = [volume]
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        snapshots = [snapshot]
        guid = 12345
        name = snapshot['name']
        path = self.drv._get_snapshot_path(snapshot)
        parent = self.drv._get_volume_path(volume)
        list_snapshots.return_value = [{
            'name': name,
            'path': path,
            'guid': guid,
            'parent': parent,
            'hprService': '',
            'snaplistId': ''
        }]
        list_volumes.return_value = volumes
        result = self.drv.get_manageable_snapshots(snapshots, None, 1,
                                                   0, 'size', 'asc')
        payload = {
            'parent': self.drv.root_path,
            'fields': 'name,guid,path,parent,hprService,snaplistId',
            'recursive': True
        }
        list_snapshots.assert_called_with(payload)
        expected = [{
            'cinder_id': snapshot['id'],
            'extra_info': None,
            'reason_not_safe': 'Snapshot already managed',
            'source_reference': {
                'name': volume['name']
            },
            'reference': {
                'source-guid': guid,
                'source-name': snapshot['name']
            },
            'safe_to_manage': False,
            'size': volume['size']
        }]
        self.assertEqual(expected, result)

    def test_unmanage_snapshot(self):
        volume = fake_volume(self.ctxt)
        snapshot = fake_snapshot(self.ctxt)
        snapshot.volume = volume
        self.assertIsNone(self.drv.unmanage_snapshot(snapshot))
