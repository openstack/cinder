#
# Copyright 2011 Nexenta Systems, Inc.
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

from mox3 import mox as mox_lib
from oslo_utils import units

from cinder import context
from cinder import db
from cinder import test
from cinder.volume import configuration as conf
from cinder.volume.drivers.nexenta import iscsi
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import nfs
from cinder.volume.drivers.nexenta import utils


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
    }

    def __init__(self, method):
        super(TestNexentaISCSIDriver, self).__init__(method)

    def setUp(self):
        super(TestNexentaISCSIDriver, self).setUp()
        self.ctxt = context.get_admin_context()
        self.configuration = mox_lib.MockObject(conf.Configuration)
        self.configuration.nexenta_volume_description = ''
        self.configuration.nexenta_host = '1.1.1.1'
        self.configuration.nexenta_user = 'admin'
        self.configuration.nexenta_password = 'nexenta'
        self.configuration.nexenta_volume = 'cinder'
        self.configuration.nexenta_rest_port = 2000
        self.configuration.nexenta_rest_protocol = 'http'
        self.configuration.nexenta_iscsi_target_portal_port = 3260
        self.configuration.nexenta_target_prefix = 'iqn:'
        self.configuration.nexenta_target_group_prefix = 'cinder/'
        self.configuration.nexenta_blocksize = '8K'
        self.configuration.nexenta_sparse = True
        self.configuration.nexenta_volume_compression = 'on'
        self.configuration.nexenta_volume_dedup = 'off'
        self.configuration.nexenta_rrmgr_compression = 1
        self.configuration.nexenta_rrmgr_tcp_buf_size = 1024
        self.configuration.nexenta_rrmgr_connections = 2
        self.configuration.nexenta_capacitycheck = 80
        self.nms_mock = self.mox.CreateMockAnything()
        for mod in ['volume', 'zvol', 'iscsitarget', 'appliance',
                    'stmf', 'scsidisk', 'snapshot']:
            setattr(self.nms_mock, mod, self.mox.CreateMockAnything())
        self.stubs.Set(jsonrpc, 'NexentaJSONProxy',
                       lambda *_, **__: self.nms_mock)
        self.drv = iscsi.NexentaISCSIDriver(
            configuration=self.configuration)
        self.drv.db = db
        self.drv.nms = self.nms_mock

    def test_check_for_setup_error(self):
        self.nms_mock.volume.object_exists('cinder').AndReturn(True)
        self.mox.ReplayAll()
        self.drv.check_for_setup_error()

        self.mox.ResetAll()

        self.nms_mock.volume.object_exists('cinder').AndReturn(False)
        self.mox.ReplayAll()
        self.assertRaises(LookupError, self.drv.check_for_setup_error)

    def test_local_path(self):
        self.assertRaises(NotImplementedError, self.drv.local_path, '')

    def test_create_volume(self):
        self.nms_mock.zvol.create('cinder/volume1', '1G', '8K', True)
        self.mox.ReplayAll()
        self.drv.create_volume(self.TEST_VOLUME_REF)

    def test_delete_volume(self):
        self.nms_mock.zvol.get_child_props('cinder/volume1',
                                           'origin').AndReturn({})
        self.nms_mock.zvol.destroy('cinder/volume1', '')
        self.mox.ReplayAll()
        self.drv.delete_volume(self.TEST_VOLUME_REF)
        self.mox.ResetAll()

        c = self.nms_mock.zvol.get_child_props('cinder/volume1', 'origin')
        c.AndReturn({'origin': 'cinder/volume0@snapshot'})
        self.nms_mock.zvol.destroy('cinder/volume1', '')
        self.nms_mock.volume.object_exists('cinder/volume0')
        self.mox.ReplayAll()
        self.drv.delete_volume(self.TEST_VOLUME_REF)
        self.mox.ResetAll()

        c = self.nms_mock.zvol.get_child_props('cinder/volume1', 'origin')
        c.AndReturn({'origin': 'cinder/volume0@cinder-clone-snapshot-1'})
        self.nms_mock.zvol.destroy('cinder/volume1', '')
        self.nms_mock.snapshot.destroy(
            'cinder/volume0@cinder-clone-snapshot-1', '')
        self.nms_mock.volume.object_exists('cinder/volume0')
        self.mox.ReplayAll()
        self.drv.delete_volume(self.TEST_VOLUME_REF)
        self.mox.ResetAll()

    def test_create_cloned_volume(self):
        vol = self.TEST_VOLUME_REF2
        src_vref = self.TEST_VOLUME_REF
        snapshot = {
            'volume_name': src_vref['name'],
            'name': 'cinder-clone-snapshot-%s' % vol['id'],
        }
        self.nms_mock.zvol.create_snapshot('cinder/%s' % src_vref['name'],
                                           snapshot['name'], '')
        self.nms_mock.zvol.clone('cinder/%s@%s' % (src_vref['name'],
                                                   snapshot['name']),
                                 'cinder/%s' % vol['name'])
        self.mox.ReplayAll()
        self.drv.create_cloned_volume(vol, src_vref)

    def test_migrate_volume(self):
        volume = self.TEST_VOLUME_REF
        host = {
            'capabilities': {
                'vendor_name': 'Nexenta',
                'location_info': 'NexentaISCSIDriver:1.1.1.1:cinder',
                'free_capacity_gb': 1,
                'iscsi_target_portal_port': 3260,
                'nms_url': 'http://admin:password@1.1.1.1:2000'
            }
        }
        snapshot = {
            'volume_name': volume['name'],
            'name': 'cinder-migrate-snapshot-%s' % volume['id'],
        }
        self.nms_mock.appliance.ssh_list_bindings().AndReturn({
            '0': [True, True, True, '1.1.1.1']})
        self.nms_mock.zvol.create_snapshot('cinder/%s' % volume['name'],
                                           snapshot['name'], '')

        src = '%(volume)s/%(zvol)s@%(snapshot)s' % {
            'volume': 'cinder',
            'zvol': volume['name'],
            'snapshot': snapshot['name']
        }
        dst = '1.1.1.1:cinder'
        cmd = ' '.join(['rrmgr -s zfs -c 1 -q -e -w 1024 -n 2', src, dst])

        self.nms_mock.appliance.execute(cmd)

        snapshot_name = 'cinder/%(volume)s@%(snapshot)s' % {
            'volume': volume['name'],
            'snapshot': snapshot['name']
        }
        self.nms_mock.snapshot.destroy(snapshot_name, '')
        volume_name = 'cinder/%s' % volume['name']
        self.nms_mock.zvol.get_child_props(volume_name,
                                           'origin').AndReturn(None)
        self.nms_mock.zvol.destroy(volume_name, '')
        self.nms_mock.snapshot.destroy('cinder/%(volume)s@%(snapshot)s' % {
            'volume': volume['name'],
            'snapshot': snapshot['name']
        }, '')
        self.nms_mock.volume.object_exists(volume_name)
        self.mox.ReplayAll()
        self.drv.migrate_volume(None, volume, host)

    def test_create_snapshot(self):
        self.nms_mock.zvol.create_snapshot('cinder/volume1', 'snapshot1', '')
        self.mox.ReplayAll()
        self.drv.create_snapshot(self.TEST_SNAPSHOT_REF)

    def test_create_volume_from_snapshot(self):
        self.nms_mock.zvol.clone('cinder/volume1@snapshot1', 'cinder/volume2')
        self.mox.ReplayAll()
        self.drv.create_volume_from_snapshot(self.TEST_VOLUME_REF2,
                                             self.TEST_SNAPSHOT_REF)

    def test_delete_snapshot(self):
        self._create_volume_db_entry()
        self.nms_mock.snapshot.destroy('cinder/volume1@snapshot1', '')
        self.nms_mock.volume.object_exists('cinder/volume1')
        self.mox.ReplayAll()
        self.drv.delete_snapshot(self.TEST_SNAPSHOT_REF)
        self.mox.ResetAll()

        # Check that exception not raised if snapshot does not exist
        mock = self.nms_mock.snapshot.destroy('cinder/volume1@snapshot1', '')
        mock.AndRaise(jsonrpc.NexentaJSONException(
            'Snapshot cinder/volume1@snapshot1 does not exist'))
        self.nms_mock.volume.object_exists('cinder/volume1')
        self.mox.ReplayAll()
        self.drv.delete_snapshot(self.TEST_SNAPSHOT_REF)

    def _stub_all_export_methods(self, fail=False):
        self.nms_mock.stmf.list_targets()
        self.nms_mock.iscsitarget.create_target(
            {'target_name': 'iqn:1.1.1.1-0'})
        self.nms_mock.stmf.list_targetgroups()
        zvol_name = 'cinder/volume1'
        self.nms_mock.stmf.create_targetgroup(
            'cinder/1.1.1.1-0')
        self.nms_mock.stmf.list_targetgroup_members(
            'cinder/1.1.1.1-0').AndReturn(['iqn:1.1.1.1-0'])
        self.nms_mock.scsidisk.lu_exists(zvol_name)
        self.nms_mock.scsidisk.create_lu(zvol_name, {})
        self.nms_mock.scsidisk.lu_shared(zvol_name)
        self.nms_mock.scsidisk.add_lun_mapping_entry(zvol_name, {
                    'target_group': 'cinder/1.1.1.1-0'}).AndReturn({'lun': 0})

    def test_create_export(self):
        self._stub_all_export_methods()
        self.mox.ReplayAll()
        retval = self.drv.create_export({}, self.TEST_VOLUME_REF, None)
        location = '%(host)s:%(port)s,1 %(name)s %(lun)s' % {
            'host': self.configuration.nexenta_host,
            'port': self.configuration.nexenta_iscsi_target_portal_port,
            'name': 'iqn:1.1.1.1-0',
            'lun': '0'
        }
        self.assertEqual(retval, {'provider_location': location})

    def test_ensure_export(self):
        self._stub_all_export_methods()
        self.mox.ReplayAll()
        self.drv.ensure_export({}, self.TEST_VOLUME_REF)

    def test_remove_export(self):
        self.nms_mock.stmf.list_targets()
        self.nms_mock.iscsitarget.create_target(
            {'target_name': 'iqn:1.1.1.1-0'})
        self.nms_mock.stmf.list_targetgroups()
        self.nms_mock.stmf.create_targetgroup(
            'cinder/1.1.1.1-0')
        self.nms_mock.stmf.list_targetgroup_members(
            'cinder/1.1.1.1-0').AndReturn(['iqn:1.1.1.1-0'])
        self.nms_mock.scsidisk.delete_lu('cinder/volume1')
        self.mox.ReplayAll()
        self.drv.remove_export({}, self.TEST_VOLUME_REF)

    def test_get_volume_stats(self):
        stats = {'size': '5368709120G',
                 'used': '5368709120G',
                 'available': '5368709120G',
                 'health': 'ONLINE'}
        self.nms_mock.volume.get_child_props(
            self.configuration.nexenta_volume,
            'health|size|used|available').AndReturn(stats)
        self.mox.ReplayAll()
        stats = self.drv.get_volume_stats(True)
        self.assertEqual(stats['storage_protocol'], 'iSCSI')
        self.assertEqual(stats['total_capacity_gb'], 5368709120.0)
        self.assertEqual(stats['free_capacity_gb'], 5368709120.0)
        self.assertEqual(stats['reserved_percentage'], 20)
        self.assertEqual(stats['QoS_support'], False)

    def _create_volume_db_entry(self):
        vol = {
            'id': '1',
            'size': 1,
            'status': 'available',
            'provider_location': self.TEST_VOLUME_NAME
        }
        return db.volume_create(self.ctxt, vol)['id']


class TestNexentaNfsDriver(test.TestCase):
    TEST_EXPORT1 = 'host1:/volumes/stack/share'
    TEST_NMS1 = 'http://admin:nexenta@host1:2000'

    TEST_EXPORT2 = 'host2:/volumes/stack/share'
    TEST_NMS2 = 'http://admin:nexenta@host2:2000'

    TEST_EXPORT2_OPTIONS = '-o intr'

    TEST_FILE_NAME = 'test.txt'
    TEST_SHARES_CONFIG_FILE = '/etc/cinder/nexenta-shares.conf'

    TEST_SHARE_SVC = 'svc:/network/nfs/server:default'

    TEST_SHARE_OPTS = {
        'read_only': '',
        'read_write': '*',
        'recursive': 'true',
        'anonymous_rw': 'true',
        'extra_options': 'anon=0',
        'root': 'nobody'
    }

    def _create_volume_db_entry(self):
        vol = {
            'id': '1',
            'size': 1,
            'status': 'available',
            'provider_location': self.TEST_EXPORT1
        }
        return db.volume_create(self.ctxt, vol)['id']

    def setUp(self):
        super(TestNexentaNfsDriver, self).setUp()
        self.ctxt = context.get_admin_context()
        self.configuration = mox_lib.MockObject(conf.Configuration)
        self.configuration.nexenta_volume_description = ''
        self.configuration.nexenta_shares_config = None
        self.configuration.nexenta_mount_point_base = '$state_path/mnt'
        self.configuration.nexenta_sparsed_volumes = True
        self.configuration.nexenta_volume_compression = 'on'
        self.configuration.nexenta_volume_dedup = 'off'
        self.configuration.nexenta_rrmgr_compression = 1
        self.configuration.nexenta_rrmgr_tcp_buf_size = 1024
        self.configuration.nexenta_rrmgr_connections = 2
        self.configuration.nfs_mount_point_base = '/mnt/test'
        self.configuration.nfs_mount_options = None
        self.configuration.nas_mount_options = None
        self.configuration.nexenta_nms_cache_volroot = False
        self.configuration.nfs_mount_attempts = 3
        self.configuration.nexenta_capacitycheck = 80
        self.configuration.nfs_used_ratio = .95
        self.configuration.nfs_oversub_ratio = 1.0
        self.configuration.reserved_percentage = 0
        self.configuration.max_over_subscription_ratio = 20.0
        self.nms_mock = self.mox.CreateMockAnything()
        for mod in ('appliance', 'folder', 'server', 'volume', 'netstorsvc',
                    'snapshot', 'netsvc'):
            setattr(self.nms_mock, mod, self.mox.CreateMockAnything())
        self.nms_mock.__hash__ = lambda *_, **__: 1
        self.stubs.Set(jsonrpc, 'NexentaJSONProxy',
                       lambda *_, **__: self.nms_mock)
        self.drv = nfs.NexentaNfsDriver(configuration=self.configuration)
        self.drv.shares = {}
        self.drv.share2nms = {}

    def test_check_for_setup_error(self):
        self.drv.share2nms = {
            'host1:/volumes/stack/share': self.nms_mock
        }

        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.nms_mock.volume.object_exists('stack').AndReturn(True)
        self.nms_mock.folder.object_exists('stack/share').AndReturn(True)
        share_opts = {
            'read_write': '*',
            'read_only': '',
            'root': 'nobody',
            'extra_options': 'anon=0',
            'recursive': 'true',
            'anonymous_rw': 'true',
        }
        self.nms_mock.netstorsvc.share_folder(
            'svc:/network/nfs/server:default', 'stack/share', share_opts)

        self.mox.ReplayAll()

        self.drv.check_for_setup_error()

        self.mox.ResetAll()

        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.nms_mock.volume.object_exists('stack').AndReturn(False)

        self.mox.ReplayAll()

        self.assertRaises(LookupError, self.drv.check_for_setup_error)

        self.mox.ResetAll()

        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.nms_mock.volume.object_exists('stack').AndReturn(True)
        self.nms_mock.folder.object_exists('stack/share').AndReturn(False)

        self.mox.ReplayAll()

        self.assertRaises(LookupError, self.drv.check_for_setup_error)

    def test_initialize_connection(self):
        self.drv.shares = {
            self.TEST_EXPORT1: None
        }
        volume = {
            'provider_location': self.TEST_EXPORT1,
            'name': 'volume'
        }
        result = self.drv.initialize_connection(volume, None)
        self.assertEqual(result['data']['export'],
                         '%s/volume' % self.TEST_EXPORT1)

    def test_do_create_volume(self):
        volume = {
            'provider_location': self.TEST_EXPORT1,
            'size': 1,
            'name': 'volume-1'
        }
        self.drv.shares = {self.TEST_EXPORT1: None}
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}

        compression = self.configuration.nexenta_volume_compression
        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.nms_mock.folder.create_with_props(
            'stack', 'share/volume-1', {'compression': compression})
        self.nms_mock.netstorsvc.share_folder(self.TEST_SHARE_SVC,
                                              'stack/share/volume-1',
                                              self.TEST_SHARE_OPTS)
        self.nms_mock.appliance.execute(
            'truncate --size 1G /volumes/stack/share/volume-1/volume')
        self.nms_mock.appliance.execute('chmod ugo+rw '
                                        '/volumes/stack/share/volume-1/volume')
        self.nms_mock.netsvc.get_confopts('svc:/network/nfs/server:default',
                                          'configure').AndReturn({
                                              'nfs_server_versmax': {
                                                  'current': u'3'}})

        self.mox.ReplayAll()

        self.mox.StubOutWithMock(self.drv, '_ensure_share_mounted')
        self.drv._do_create_volume(volume)

        self.mox.ResetAll()

        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.nms_mock.folder.create_with_props(
            'stack', 'share/volume-1', {'compression': compression})
        self.nms_mock.netstorsvc.share_folder(
            self.TEST_SHARE_SVC, 'stack/share/volume-1',
            self.TEST_SHARE_OPTS).AndRaise(
                jsonrpc.NexentaJSONException('-'))
        self.nms_mock.folder.destroy('stack/share/volume-1')

        self.mox.ReplayAll()

        self.assertRaises(jsonrpc.NexentaJSONException,
                          self.drv._do_create_volume, volume)

    def test_create_sparsed_file(self):
        self.nms_mock.appliance.execute('truncate --size 1G /tmp/path')
        self.mox.ReplayAll()

        self.drv._create_sparsed_file(self.nms_mock, '/tmp/path', 1)

    def test_create_regular_file(self):
        self.nms_mock.appliance.execute('dd if=/dev/zero of=/tmp/path bs=1M '
                                        'count=1024')
        self.mox.ReplayAll()

        self.drv._create_regular_file(self.nms_mock, '/tmp/path', 1)

    def test_set_rw_permissions_for_all(self):
        path = '/tmp/path'
        self.nms_mock.appliance.execute('chmod ugo+rw %s' % path)
        self.mox.ReplayAll()

        self.drv._set_rw_permissions_for_all(self.nms_mock, path)

    def test_local_path(self):
        volume = {'provider_location': self.TEST_EXPORT1, 'name': 'volume-1'}
        path = self.drv.local_path(volume)
        self.assertEqual(
            path,
            '$state_path/mnt/b3f660847a52b29ac330d8555e4ad669/volume-1/volume'
        )

    def test_remote_path(self):
        volume = {'provider_location': self.TEST_EXPORT1, 'name': 'volume-1'}
        path = self.drv.remote_path(volume)
        self.assertEqual(path, '/volumes/stack/share/volume-1/volume')

    def test_share_folder(self):
        path = 'stack/share/folder'
        self.nms_mock.netstorsvc.share_folder(self.TEST_SHARE_SVC, path,
                                              self.TEST_SHARE_OPTS)
        self.mox.ReplayAll()

        self.drv._share_folder(self.nms_mock, 'stack', 'share/folder')

    def test_load_shares_config(self):
        self.drv.configuration.nfs_shares_config = self.TEST_SHARES_CONFIG_FILE

        self.mox.StubOutWithMock(self.drv, '_read_config_file')
        config_data = [
            '%s  %s' % (self.TEST_EXPORT1, self.TEST_NMS1),
            '# %s   %s' % (self.TEST_EXPORT2, self.TEST_NMS2),
            '',
            '%s  %s %s' % (self.TEST_EXPORT2, self.TEST_NMS2,
                           self.TEST_EXPORT2_OPTIONS)
        ]

        self.drv._read_config_file(self.TEST_SHARES_CONFIG_FILE).\
            AndReturn(config_data)
        self.mox.ReplayAll()

        self.drv._load_shares_config(self.drv.configuration.nfs_shares_config)

        self.assertIn(self.TEST_EXPORT1, self.drv.shares)
        self.assertIn(self.TEST_EXPORT2, self.drv.shares)
        self.assertEqual(len(self.drv.shares), 2)

        self.assertIn(self.TEST_EXPORT1, self.drv.share2nms)
        self.assertIn(self.TEST_EXPORT2, self.drv.share2nms)
        self.assertEqual(len(self.drv.share2nms.keys()), 2)

        self.assertEqual(self.drv.shares[self.TEST_EXPORT2],
                         self.TEST_EXPORT2_OPTIONS)

        self.mox.VerifyAll()

    def test_get_capacity_info(self):
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}
        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.nms_mock.folder.get_child_props('stack/share',
                                             'used|available').AndReturn({
            'available': '1G',
            'used': '2G'
        })
        self.mox.ReplayAll()
        total, free, allocated = self.drv._get_capacity_info(self.TEST_EXPORT1)

        self.assertEqual(total, 3 * units.Gi)
        self.assertEqual(free, units.Gi)
        self.assertEqual(allocated, 2 * units.Gi)

    def test_get_share_datasets(self):
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}
        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.mox.ReplayAll()

        volume_name, folder_name = \
            self.drv._get_share_datasets(self.TEST_EXPORT1)

        self.assertEqual(volume_name, 'stack')
        self.assertEqual(folder_name, 'share')

    def test_delete_snapshot(self):
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}
        self._create_volume_db_entry()

        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.nms_mock.snapshot.destroy('stack/share/volume-1@snapshot1', '')
        self.mox.ReplayAll()
        self.drv.delete_snapshot({'volume_id': '1', 'name': 'snapshot1'})
        self.mox.ResetAll()

        # Check that exception not raised if snapshot does not exist on
        # NexentaStor appliance.
        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        mock = self.nms_mock.snapshot.destroy('stack/share/volume-1@snapshot1',
                                              '')
        mock.AndRaise(jsonrpc.NexentaJSONException("Snapshot does not exist"))
        self.mox.ReplayAll()
        self.drv.delete_snapshot({'volume_id': '1', 'name': 'snapshot1'})
        self.mox.ResetAll()

    def test_delete_volume(self):
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}
        self._create_volume_db_entry()

        self.drv._ensure_share_mounted = lambda *_, **__: 0
        self.drv._execute = lambda *_, **__: 0

        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.nms_mock.folder.get_child_props('stack/share/volume-1',
                                             'origin').AndReturn(None)
        self.nms_mock.folder.destroy('stack/share/volume-1', '-r')
        self.mox.ReplayAll()
        self.drv.delete_volume({
            'id': '1',
            'name': 'volume-1',
            'provider_location': self.TEST_EXPORT1
        })
        self.mox.ResetAll()

        # Check that exception not raised if folder does not exist on
        # NexentaStor appliance.
        self.nms_mock.server.get_prop('volroot').AndReturn('/volumes')
        self.nms_mock.folder.get_child_props('stack/share/volume-1',
                                             'origin').AndReturn(None)
        mock = self.nms_mock.folder.destroy('stack/share/volume-1', '-r')
        mock.AndRaise(jsonrpc.NexentaJSONException("Folder does not exist"))
        self.mox.ReplayAll()
        self.drv.delete_volume({
            'id': '1',
            'name': 'volume-1',
            'provider_location': self.TEST_EXPORT1
        })
        self.mox.ResetAll()


class TestNexentaUtils(test.TestCase):

    def test_str2size(self):
        values_to_test = (
            # Test empty value
            (None, 0),
            ('', 0),
            ('0', 0),
            ('12', 12),
            # Test int and long values
            (10, 10),
            (long(10), 10),
            # Test bytes string
            ('1b', 1),
            ('1B', 1),
            ('1023b', 1023),
            ('0B', 0),
            # Test other units
            ('1M', units.Mi),
            ('1.0M', units.Mi),
        )

        for value, result in values_to_test:
            self.assertEqual(utils.str2size(value), result)

        # Invalid format value
        self.assertRaises(ValueError, utils.str2size, 'A')

    def test_str2gib_size(self):
        self.assertEqual(utils.str2gib_size('1024M'), 1)
        self.assertEqual(utils.str2gib_size('300M'),
                         300 * units.Mi // units.Gi)
        self.assertEqual(utils.str2gib_size('1.2T'),
                         1.2 * units.Ti // units.Gi)
        self.assertRaises(ValueError, utils.str2gib_size, 'A')

    def test_parse_nms_url(self):
        urls = (
            ('http://192.168.1.1/', (False, 'http', 'admin', 'nexenta',
                                     '192.168.1.1', '2000', '/rest/nms/')),
            ('http://192.168.1.1:8080', (False, 'http', 'admin', 'nexenta',
                                         '192.168.1.1', '8080', '/rest/nms/')),
            ('https://root:password@192.168.1.1:8080',
             (False, 'https', 'root', 'password', '192.168.1.1', '8080',
              '/rest/nms/')),
        )
        for url, result in urls:
            self.assertEqual(utils.parse_nms_url(url), result)
