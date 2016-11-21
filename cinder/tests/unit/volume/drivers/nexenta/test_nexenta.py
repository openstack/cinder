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
from cinder.volume.drivers.nexenta import iscsi
from cinder.volume.drivers.nexenta import jsonrpc
from cinder.volume.drivers.nexenta import nfs
from cinder.volume.drivers.nexenta import utils


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
        'size': 3,
        'id': '3',
        'status': 'in-use'
    }
    TEST_SNAPSHOT_REF = {
        'name': TEST_SNAPSHOT_NAME,
        'volume_name': TEST_VOLUME_NAME,
        'volume_size': 1,
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
        self.cfg.nexenta_iscsi_target_portal_port = 3260
        self.cfg.nexenta_target_prefix = 'iqn:'
        self.cfg.nexenta_target_group_prefix = 'cinder/'
        self.cfg.nexenta_blocksize = '8K'
        self.cfg.nexenta_sparse = True
        self.cfg.nexenta_dataset_compression = 'on'
        self.cfg.nexenta_dataset_dedup = 'off'
        self.cfg.nexenta_rrmgr_compression = 1
        self.cfg.nexenta_rrmgr_tcp_buf_size = 1024
        self.cfg.nexenta_rrmgr_connections = 2
        self.cfg.reserved_percentage = 20
        self.nms_mock = mock.Mock()
        for mod in ['volume', 'zvol', 'iscsitarget', 'appliance',
                    'stmf', 'scsidisk', 'snapshot']:
            setattr(self.nms_mock, mod, mock.Mock())
        self.mock_object(jsonrpc, 'NexentaJSONProxy',
                         return_value=self.nms_mock)
        self.drv = iscsi.NexentaISCSIDriver(
            configuration=self.cfg)
        self.drv.db = db
        self.drv.do_setup(self.ctxt)

    def test_check_do_setup(self):
        self.assertEqual('http', self.drv.nms_protocol)

    def test_check_for_setup_error(self):
        self.nms_mock.volume.object_exists.return_value = False
        self.assertRaises(LookupError, self.drv.check_for_setup_error)

    def test_local_path(self):
        self.assertRaises(NotImplementedError, self.drv.local_path, '')

    def test_create_volume(self):
        self.drv.create_volume(self.TEST_VOLUME_REF)
        self.nms_mock.zvol.create.assert_called_with(
            'cinder/%s' % self.TEST_VOLUME_REF['name'], '1G',
            self.cfg.nexenta_blocksize, self.cfg.nexenta_sparse)

    def test_delete_volume(self):
        self.drv._collect_garbage = lambda vol: vol
        self.nms_mock.zvol.get_child_props.return_value = (
            {'origin': 'cinder/volume0@snapshot'})
        self.drv.delete_volume(self.TEST_VOLUME_REF)
        self.nms_mock.zvol.get_child_props.assert_called_with(
            'cinder/volume1', 'origin')
        self.nms_mock.zvol.destroy.assert_called_with(
            'cinder/volume1', '')

        self.nms_mock.zvol.get_child_props.assert_called_with(
            'cinder/volume1', 'origin')
        self.nms_mock.zvol.destroy.assert_called_with('cinder/volume1', '')
        self.drv.delete_volume(self.TEST_VOLUME_REF)

        self.nms_mock.zvol.get_child_props.assert_called_with(
            'cinder/volume1', 'origin')

    def test_create_cloned_volume(self):
        vol = self.TEST_VOLUME_REF2
        src_vref = self.TEST_VOLUME_REF
        snapshot = {
            'volume_name': src_vref['name'],
            'name': 'cinder-clone-snapshot-%s' % vol['id'],
        }
        self.drv.create_cloned_volume(vol, src_vref)
        self.nms_mock.zvol.create_snapshot.assert_called_with(
            'cinder/%s' % src_vref['name'], snapshot['name'], '')
        self.nms_mock.zvol.clone.assert_called_with(
            'cinder/%s@%s' % (src_vref['name'], snapshot['name']),
            'cinder/%s' % vol['name'])

    def test_migrate_volume(self):
        self.drv._collect_garbage = lambda vol: vol
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
        volume_name = 'cinder/%s' % volume['name']

        self.nms_mock.appliance.ssh_list_bindings.return_value = (
            {'0': [True, True, True, '1.1.1.1']})
        self.nms_mock.zvol.get_child_props.return_value = None

        self.drv.migrate_volume(None, volume, host)
        self.nms_mock.zvol.create_snapshot.assert_called_with(
            'cinder/%s' % volume['name'], snapshot['name'], '')

        src = '%(volume)s/%(zvol)s@%(snapshot)s' % {
            'volume': 'cinder',
            'zvol': volume['name'],
            'snapshot': snapshot['name']
        }
        dst = '1.1.1.1:cinder'
        cmd = ' '.join(['rrmgr -s zfs -c 1 -q -e -w 1024 -n 2', src, dst])

        self.nms_mock.appliance.execute.assert_called_with(cmd)

        snapshot_name = 'cinder/%(volume)s@%(snapshot)s' % {
            'volume': volume['name'],
            'snapshot': snapshot['name']
        }
        self.nms_mock.snapshot.destroy.assert_called_with(snapshot_name, '')
        self.nms_mock.zvol.destroy.assert_called_with(volume_name, '')
        self.nms_mock.snapshot.destroy.assert_called_with(
            'cinder/%(volume)s@%(snapshot)s' % {
                'volume': volume['name'],
                'snapshot': snapshot['name']
            }, '')

    def test_create_snapshot(self):
        self.drv.create_snapshot(self.TEST_SNAPSHOT_REF)
        self.nms_mock.zvol.create_snapshot.assert_called_with(
            'cinder/volume1', 'snapshot1', '')

    def test_create_volume_from_snapshot(self):
        self._create_volume_db_entry()
        self.drv.create_volume_from_snapshot(self.TEST_VOLUME_REF3,
                                             self.TEST_SNAPSHOT_REF)
        self.nms_mock.zvol.clone.assert_called_with(
            'cinder/volume1@snapshot1', 'cinder/volume3')
        self.nms_mock.zvol.set_child_prop.assert_called_with(
            'cinder/volume3', 'volsize', '3G')

    def test_delete_snapshot(self):
        self._create_volume_db_entry()
        self.drv._collect_garbage = lambda vol: vol
        self.drv.delete_snapshot(self.TEST_SNAPSHOT_REF)
        self.nms_mock.snapshot.destroy.assert_called_with(
            'cinder/volume1@snapshot1', '')

        # Check that exception not raised if snapshot does not exist
        self.drv.delete_snapshot(self.TEST_SNAPSHOT_REF)
        self.nms_mock.snapshot.destroy.side_effect = (
            exception.NexentaException('does not exist'))
        self.nms_mock.snapshot.destroy.assert_called_with(
            'cinder/volume1@snapshot1', '')

    def _mock_all_export_methods(self, fail=False):
        self.assertTrue(self.nms_mock.stmf.list_targets.called)
        self.nms_mock.iscsitarget.create_target.assert_called_with(
            {'target_name': 'iqn:1.1.1.1-0'})
        self.nms_mock.stmf.list_targetgroups()
        zvol_name = 'cinder/volume1'
        self.nms_mock.stmf.create_targetgroup.assert_called_with(
            'cinder/1.1.1.1-0')
        self.nms_mock.stmf.list_targetgroup_members.assert_called_with(
            'cinder/1.1.1.1-0')
        self.nms_mock.scsidisk.lu_exists.assert_called_with(zvol_name)
        self.nms_mock.scsidisk.create_lu.assert_called_with(zvol_name, {})

    def _stub_all_export_methods(self):
        self.nms_mock.scsidisk.lu_exists.return_value = False
        self.nms_mock.scsidisk.lu_shared.side_effect = (
            exception.NexentaException(['does not exist for zvol']))
        self.nms_mock.scsidisk.create_lu.return_value = {'lun': 0}
        self.nms_mock.stmf.list_targets.return_value = []
        self.nms_mock.stmf.list_targetgroups.return_value = []
        self.nms_mock.stmf.list_targetgroup_members.return_value = []
        self.nms_mock._get_target_name.return_value = ['iqn:1.1.1.1-0']
        self.nms_mock.iscsitarget.create_targetgroup.return_value = ({
            'target_name': 'cinder/1.1.1.1-0'})
        self.nms_mock.scsidisk.add_lun_mapping_entry.return_value = {'lun': 0}

    def test_create_export(self):
        self._stub_all_export_methods()
        retval = self.drv.create_export({}, self.TEST_VOLUME_REF, None)
        self._mock_all_export_methods()
        location = '%(host)s:%(port)s,1 %(name)s %(lun)s' % {
            'host': self.cfg.nexenta_host,
            'port': self.cfg.nexenta_iscsi_target_portal_port,
            'name': 'iqn:1.1.1.1-0',
            'lun': '0'
        }
        self.assertEqual({'provider_location': location}, retval)

    def test_ensure_export(self):
        self._stub_all_export_methods()
        self.drv.ensure_export({}, self.TEST_VOLUME_REF)
        self._mock_all_export_methods()

    def test_remove_export(self):
        self.nms_mock.stmf.list_targets.return_value = ['iqn:1.1.1.1-0']
        self.nms_mock.stmf.list_targetgroups.return_value = (
            ['cinder/1.1.1.1-0'])
        self.nms_mock.stmf.list_targetgroup_members.return_value = (
            ['iqn:1.1.1.1-0'])
        self.drv.remove_export({}, self.TEST_VOLUME_REF)
        self.assertTrue(self.nms_mock.stmf.list_targets.called)
        self.assertTrue(self.nms_mock.stmf.list_targetgroups.called)
        self.nms_mock.scsidisk.delete_lu.assert_called_with('cinder/volume1')

    def test_get_volume_stats(self):
        stats = {'size': '5368709120G',
                 'used': '5368709120G',
                 'available': '5368709120G',
                 'health': 'ONLINE'}
        self.nms_mock.volume.get_child_props.return_value = stats
        stats = self.drv.get_volume_stats(True)
        self.assertEqual('iSCSI', stats['storage_protocol'])
        self.assertEqual(5368709120.0, stats['total_capacity_gb'])
        self.assertEqual(5368709120.0, stats['free_capacity_gb'])
        self.assertEqual(20, stats['reserved_percentage'])
        self.assertFalse(stats['QoS_support'])

    def test_collect_garbage__snapshot(self):
        name = 'cinder/v1@s1'
        self.drv._mark_as_garbage(name)
        self.nms_mock.zvol.get_child_props.return_value = None
        self.drv._collect_garbage(name)
        self.nms_mock.snapshot.destroy.assert_called_with(name, '')
        self.assertNotIn(name, self.drv._needless_objects)

    def test_collect_garbage__volume(self):
        name = 'cinder/v1'
        self.drv._mark_as_garbage(name)
        self.nms_mock.zvol.get_child_props.return_value = None
        self.drv._collect_garbage(name)
        self.nms_mock.zvol.destroy.assert_called_with(name, '')
        self.assertNotIn(name, self.drv._needless_objects)

    def _create_volume_db_entry(self):
        vol = {
            'id': '1',
            'size': 1,
            'status': 'available',
            'provider_location': self.TEST_VOLUME_NAME
        }
        return db.volume_create(self.ctxt, vol)['id']


class TestNexentaNfsDriver(test.TestCase):
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
        'size': 2,
        'id': '2',
        'status': 'in-use'
    }
    TEST_VOLUME_REF3 = {
        'name': TEST_VOLUME_NAME2,
        'id': '2',
        'status': 'in-use'
    }
    TEST_SNAPSHOT_REF = {
        'name': TEST_SNAPSHOT_NAME,
        'volume_name': TEST_VOLUME_NAME,
        'volume_size': 1,
        'volume_id': 1
    }

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
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}
        return db.volume_create(self.ctxt, vol)['id']

    def setUp(self):
        super(TestNexentaNfsDriver, self).setUp()
        self.ctxt = context.get_admin_context()
        self.cfg = mock.Mock(spec=conf.Configuration)
        self.cfg.nexenta_dataset_description = ''
        self.cfg.nexenta_shares_config = None
        self.cfg.nexenta_mount_point_base = '$state_path/mnt'
        self.cfg.nexenta_sparsed_volumes = True
        self.cfg.nexenta_dataset_compression = 'on'
        self.cfg.nexenta_dataset_dedup = 'off'
        self.cfg.nexenta_rrmgr_compression = 1
        self.cfg.nexenta_rrmgr_tcp_buf_size = 1024
        self.cfg.nexenta_rrmgr_connections = 2
        self.cfg.nfs_mount_point_base = '/mnt/test'
        self.cfg.nfs_mount_options = None
        self.cfg.nas_mount_options = None
        self.cfg.nexenta_nms_cache_volroot = False
        self.cfg.nfs_mount_attempts = 3
        self.cfg.reserved_percentage = 20
        self.cfg.max_over_subscription_ratio = 20.0
        self.nms_mock = mock.Mock()
        for mod in ('appliance', 'folder', 'server', 'volume', 'netstorsvc',
                    'snapshot', 'netsvc'):
            setattr(self.nms_mock, mod, mock.Mock())
        self.nms_mock.__hash__ = lambda *_, **__: 1
        self.mock_object(jsonrpc, 'NexentaJSONProxy',
                         return_value=self.nms_mock)
        self.drv = nfs.NexentaNfsDriver(configuration=self.cfg)
        self.drv.shares = {}
        self.drv.share2nms = {}

    def test_check_for_setup_error(self):
        self.drv.share2nms = {
            'host1:/volumes/stack/share': self.nms_mock
        }

        self.nms_mock.server.get_prop.return_value = '/volumes'
        self.nms_mock.volume.object_exists.return_value = True
        self.nms_mock.folder.object_exists.return_value = True
        share_opts = {
            'read_write': '*',
            'read_only': '',
            'root': 'nobody',
            'extra_options': 'anon=0',
            'recursive': 'true',
            'anonymous_rw': 'true',
        }
        self.nms_mock.netstorsvc.get_shared_folders.return_value = ''
        self.nms_mock.folder.get_child_props.return_value = {
            'available': 1, 'used': 1}
        self.drv.check_for_setup_error()
        self.nms_mock.netstorsvc.share_folder.assert_called_with(
            'svc:/network/nfs/server:default', 'stack/share', share_opts)

        self.nms_mock.server.get_prop.return_value = '/volumes'
        self.nms_mock.volume.object_exists.return_value = False

        self.assertRaises(LookupError, self.drv.check_for_setup_error)

        self.nms_mock.server.get_prop.return_value = '/volumes'
        self.nms_mock.volume.object_exists.return_value = True
        self.nms_mock.folder.object_exists.return_value = False

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
        self.assertEqual('%s/volume' % self.TEST_EXPORT1,
                         result['data']['export'])

    def test_do_create_volume(self):
        volume = {
            'provider_location': self.TEST_EXPORT1,
            'size': 1,
            'name': 'volume-1'
        }
        self.drv.shares = {self.TEST_EXPORT1: None}
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}

        compression = self.cfg.nexenta_dataset_compression
        self.nms_mock.folder.get_child_props.return_value = {
            'available': 1, 'used': 1}
        self.nms_mock.server.get_prop.return_value = '/volumes'
        self.nms_mock.netsvc.get_confopts('svc:/network/nfs/server:default',
                                          'configure').AndReturn({
                                              'nfs_server_versmax': {
                                                  'current': u'3'}})
        self.nms_mock.netsvc.get_confopts.return_value = {
            'nfs_server_versmax': {'current': 4}}
        self.nms_mock._ensure_share_mounted.return_value = True
        self.drv._do_create_volume(volume)
        self.nms_mock.folder.create_with_props.assert_called_with(
            'stack', 'share/volume-1', {'compression': compression})
        self.nms_mock.netstorsvc.share_folder.assert_called_with(
            self.TEST_SHARE_SVC, 'stack/share/volume-1', self.TEST_SHARE_OPTS)
        mock_chmod = self.nms_mock.appliance.execute
        mock_chmod.assert_called_with(
            'chmod ugo+rw /volumes/stack/share/volume-1/volume')
        mock_truncate = self.nms_mock.appliance.execute
        mock_truncate.side_effect = exception.NexentaException()
        self.nms_mock.server.get_prop.return_value = '/volumes'
        self.nms_mock.folder.get_child_props.return_value = {
            'available': 1, 'used': 1}
        self.assertRaises(exception.NexentaException,
                          self.drv._do_create_volume, volume)

    def test_create_sparsed_file(self):
        self.drv._create_sparsed_file(self.nms_mock, '/tmp/path', 1)
        self.nms_mock.appliance.execute.assert_called_with(
            'truncate --size 1G /tmp/path')

    def test_create_regular_file(self):
        self.drv._create_regular_file(self.nms_mock, '/tmp/path', 1)
        self.nms_mock.appliance.execute.assert_called_with(
            'dd if=/dev/zero of=/tmp/path bs=1M count=1024')

    @patch('cinder.volume.drivers.remotefs.'
           'RemoteFSDriver._ensure_shares_mounted')
    @patch('cinder.volume.drivers.nexenta.nfs.'
           'NexentaNfsDriver._get_volroot')
    @patch('cinder.volume.drivers.nexenta.nfs.'
           'NexentaNfsDriver._get_nfs_server_version')
    def test_create_larger_volume_from_snap(self, version, volroot, ensure):
        version.return_value = 4
        volroot.return_value = 'volroot'
        self._create_volume_db_entry()
        self.drv.create_volume_from_snapshot(self.TEST_VOLUME_REF2,
                                             self.TEST_SNAPSHOT_REF)
        self.nms_mock.appliance.execute.assert_called_with(
            'truncate --size 2G /volumes/stack/share/volume2/volume')

    @patch('cinder.volume.drivers.remotefs.'
           'RemoteFSDriver._ensure_shares_mounted')
    @patch('cinder.volume.drivers.nexenta.nfs.'
           'NexentaNfsDriver._get_volroot')
    @patch('cinder.volume.drivers.nexenta.nfs.'
           'NexentaNfsDriver._get_nfs_server_version')
    def test_create_volume_from_snapshot(self, version, volroot, ensure):
        version.return_value = 4
        volroot.return_value = 'volroot'
        self._create_volume_db_entry()
        self.drv.create_volume_from_snapshot(self.TEST_VOLUME_REF,
                                             self.TEST_SNAPSHOT_REF)
        self.nms_mock.appliance.execute.assert_not_called()

        self.drv.create_volume_from_snapshot(self.TEST_VOLUME_REF3,
                                             self.TEST_SNAPSHOT_REF)
        self.nms_mock.appliance.execute.assert_not_called()

    def test_set_rw_permissions_for_all(self):
        path = '/tmp/path'
        self.drv._set_rw_permissions_for_all(self.nms_mock, path)
        self.nms_mock.appliance.execute.assert_called_with(
            'chmod ugo+rw %s' % path)

    def test_local_path(self):
        volume = {'provider_location': self.TEST_EXPORT1, 'name': 'volume-1'}
        path = self.drv.local_path(volume)
        self.assertEqual(
            '$state_path/mnt/b3f660847a52b29ac330d8555e4ad669/volume-1/volume',
            path
        )

    def test_remote_path(self):
        volume = {'provider_location': self.TEST_EXPORT1, 'name': 'volume-1'}
        path = self.drv.remote_path(volume)
        self.assertEqual('/volumes/stack/share/volume-1/volume', path)

    def test_share_folder(self):
        self.drv._share_folder(self.nms_mock, 'stack', 'share/folder')
        path = 'stack/share/folder'
        self.nms_mock.netstorsvc.share_folder.assert_called_with(
            self.TEST_SHARE_SVC, path, self.TEST_SHARE_OPTS)

    def test_load_shares_config(self):
        self.drv.configuration.nfs_shares_config = (
            self.TEST_SHARES_CONFIG_FILE)

        config_data = [
            '%s  %s' % (self.TEST_EXPORT1, self.TEST_NMS1),
            '# %s   %s' % (self.TEST_EXPORT2, self.TEST_NMS2),
            '',
            '%s  %s %s' % (self.TEST_EXPORT2, self.TEST_NMS2,
                           self.TEST_EXPORT2_OPTIONS)
        ]

        with mock.patch.object(self.drv, '_read_config_file') as \
                mock_read_config_file:
            mock_read_config_file.return_value = config_data
            self.drv._load_shares_config(
                self.drv.configuration.nfs_shares_config)

            self.assertIn(self.TEST_EXPORT1, self.drv.shares)
            self.assertIn(self.TEST_EXPORT2, self.drv.shares)
            self.assertEqual(2, len(self.drv.shares))

            self.assertIn(self.TEST_EXPORT1, self.drv.share2nms)
            self.assertIn(self.TEST_EXPORT2, self.drv.share2nms)
            self.assertEqual(2, len(self.drv.share2nms.keys()))

            self.assertEqual(self.TEST_EXPORT2_OPTIONS,
                             self.drv.shares[self.TEST_EXPORT2])

    def test_get_capacity_info(self):
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}
        self.nms_mock.server.get_prop.return_value = '/volumes'
        self.nms_mock.folder.get_child_props.return_value = {
            'available': '1G',
            'used': '2G'
        }
        total, free, allocated = self.drv._get_capacity_info(self.TEST_EXPORT1)

        self.assertEqual(3 * units.Gi, total)
        self.assertEqual(units.Gi, free)
        self.assertEqual(2 * units.Gi, allocated)

    def test_get_share_datasets(self):
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}
        self.nms_mock.server.get_prop.return_value = '/volumes'
        volume_name, folder_name = (
            self.drv._get_share_datasets(self.TEST_EXPORT1))

        self.assertEqual('stack', volume_name)
        self.assertEqual('share', folder_name)

    def test_delete_snapshot(self):
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}
        self._create_volume_db_entry()

        self.nms_mock.server.get_prop.return_value = '/volumes'
        self.drv.delete_snapshot({'volume_id': '1', 'name': 'snapshot1'})
        self.nms_mock.snapshot.destroy.assert_called_with(
            'stack/share/volume-1@snapshot1', '')

    def test_delete_volume(self):
        self.drv.share2nms = {self.TEST_EXPORT1: self.nms_mock}
        self._create_volume_db_entry()

        self.drv._ensure_share_mounted = lambda *_, **__: 0
        self.drv._execute = lambda *_, **__: 0

        self.nms_mock.server.get_prop.return_value = '/volumes'
        self.nms_mock.folder.get_child_props.return_value = {
            'available': 1, 'used': 1}
        self.drv.delete_volume({
            'id': '1',
            'name': 'volume-1',
            'provider_location': self.TEST_EXPORT1
        })
        self.nms_mock.folder.destroy.assert_called_with(
            'stack/share/volume-1', '-r')

        # Check that exception not raised if folder does not exist on
        # NexentaStor appliance.
        mock = self.nms_mock.folder.destroy
        mock.side_effect = exception.NexentaException('Folder does not exist')
        self.drv.delete_volume({
            'id': '1',
            'name': 'volume-1',
            'provider_location': self.TEST_EXPORT1
        })


class TestNexentaUtils(test.TestCase):

    def test_str2size(self):
        values_to_test = (
            # Test empty value
            (None, 0),
            ('', 0),
            ('0', 0),
            ('12', 12),
            # Test int values
            (10, 10),
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
            self.assertEqual(result, utils.str2size(value))

        # Invalid format value
        self.assertRaises(ValueError, utils.str2size, 'A')

    def test_str2gib_size(self):
        self.assertEqual(1, utils.str2gib_size('1024M'))
        self.assertEqual(300 * units.Mi // units.Gi,
                         utils.str2gib_size('300M'))
        self.assertEqual(1.2 * units.Ti // units.Gi,
                         utils.str2gib_size('1.2T'))
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
            self.assertEqual(result, utils.parse_nms_url(url))
