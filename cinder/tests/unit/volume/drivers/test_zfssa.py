# Copyright (c) 2014, 2016, Oracle and/or its affiliates. All rights reserved.
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
"""Unit tests for Oracle's ZFSSA Cinder volume driver."""

from datetime import date
import errno
import json
import math

import mock
from oslo_utils import units
import six

from cinder import context
from cinder import exception
from cinder.image import image_utils
from cinder import test
from cinder.tests.unit import fake_utils
from cinder.tests.unit import utils
from cinder.volume import configuration as conf
from cinder.volume import driver
from cinder.volume.drivers import nfs as nfsdriver
from cinder.volume.drivers import remotefs
from cinder.volume.drivers.zfssa import restclient as client
from cinder.volume.drivers.zfssa import webdavclient
from cinder.volume.drivers.zfssa import zfssaiscsi as iscsi
from cinder.volume.drivers.zfssa import zfssanfs
from cinder.volume.drivers.zfssa import zfssarest as rest
from cinder.volume import utils as volume_utils


nfs_logbias = 'latency'
nfs_compression = 'off'
zfssa_cache_dir = 'os-cinder-cache'

no_virtsize_img = {
    'id': 'no_virtsize_img_id1234',
    'size': 654321,
    'updated_at': date(2015, 1, 1),
}

small_img = {
    'id': '1e5177e7-95e5-4a0f-b170-e45f4b469f6a',
    'size': 654321,
    'virtual_size': 2361393152,
    'updated_at': date(2015, 1, 1),
}

large_img = {
    'id': 'large_id5678',
    'size': 50000000,
    'virtual_size': 11806965760,
    'updated_at': date(2015, 2, 2),
}

fakespecs = {
    'prop1': 'prop1_val',
    'prop2': 'prop2_val',
}

small_img_props = {
    'size': 3,
}

img_props_nfs = {
    'image_id': small_img['id'],
    'updated_at': small_img['updated_at'].isoformat(),
    'size': 3,
    'name': '%(dir)s/os-cache-vol-%(name)s' % ({'dir': zfssa_cache_dir,
                                                'name': small_img['id']}),
    'id': small_img['id']
}

fakecontext = 'fakecontext'
img_service = 'fakeimgservice'
img_location = 'fakeimglocation'


class ImgInfo(object):
    def __init__(self, vsize):
        self.virtual_size = vsize


class FakeResponse(object):
    def __init__(self, statuscode, data='data'):
        self.status = statuscode
        self.data = data


class FakeSSL(object):
    def _create_unverified_context(self):
        return 'fakecontext'


class TestZFSSAISCSIDriver(test.TestCase):

    test_vol = {
        'name': 'cindervol',
        'size': 3,
        'id': 1,
        'provider_location': 'fake_location 1 2',
        'provider_auth': 'fake_auth user pass',
    }

    test_vol2 = {
        'name': 'cindervol2',
        'size': 5,
        'id': 2,
        'provider_location': 'fake_location 3 4',
        'provider_auth': 'fake_auth user pass',
    }

    test_snap = {
        'name': 'cindersnap',
        'volume_name': test_vol['name']
    }

    test_vol_snap = {
        'name': 'cindersnapvol',
        'size': test_vol['size']
    }

    def setUp(self):
        super(TestZFSSAISCSIDriver, self).setUp()
        self._create_fake_config()
        self.mock_object(iscsi, 'factory_zfssa', spec=rest.ZFSSAApi)
        self.mock_object(volume_utils, 'get_max_over_subscription_ratio',
                         return_value=1.0)
        iscsi.ZFSSAISCSIDriver._execute = fake_utils.fake_execute
        self.drv = iscsi.ZFSSAISCSIDriver(configuration=self.configuration)
        self.drv.do_setup({})

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.san_ip = '1.1.1.1'
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'passwd'
        self.configuration.zfssa_pool = 'pool'
        self.configuration.zfssa_project = 'project'
        self.configuration.zfssa_lun_volblocksize = '8k'
        self.configuration.zfssa_lun_sparse = 'false'
        self.configuration.zfssa_lun_logbias = 'latency'
        self.configuration.zfssa_lun_compression = 'off'
        self.configuration.zfssa_initiator_group = 'test-init-grp1'
        self.configuration.zfssa_initiator = \
            'iqn.1-0.org.deb:01:d7, iqn.1-0.org.deb:01:d9'
        self.configuration.zfssa_initiator_user = ''
        self.configuration.zfssa_initiator_password = ''
        self.configuration.zfssa_initiator_config = "{'test-init-grp1':[{'iqn':\
            'iqn.1-0.org.deb:01:d7','user':'','password':''}],'test-init-grp\
            2':[{'iqn':'iqn.1-0.org.deb:01:d9','user':'','password':''}]}"
        self.configuration.zfssa_target_group = 'test-target-grp1'
        self.configuration.zfssa_target_user = ''
        self.configuration.zfssa_target_password = ''
        self.configuration.zfssa_target_portal = '1.1.1.1:3260'
        self.configuration.zfssa_target_interfaces = 'e1000g0'
        self.configuration.zfssa_rest_timeout = 60
        self.configuration.volume_backend_name = 'fake_zfssa'
        self.configuration.zfssa_enable_local_cache = True
        self.configuration.zfssa_cache_project = zfssa_cache_dir
        self.configuration.safe_get = self.fake_safe_get
        self.configuration.zfssa_replication_ip = '1.1.1.1'
        self.configuration.zfssa_manage_policy = 'loose'

    def _util_migrate_volume_exceptions(self):
        self.drv.zfssa.get_lun.return_value = (
            {'targetgroup': 'test-target-grp1'})
        self.drv.zfssa.get_asn.return_value = (
            '9a2b5a0f-e3af-6d14-9578-8825f229dc89')
        self.drv.tgt_zfssa.get_asn.return_value = (
            '9a2b5a0f-e3af-6d14-9578-8825f229dc89')
        targets = {'targets': [{'hostname': '2.2.2.2',
                                'address': '2.2.2.2:216',
                                'label': '2.2.2.2',
                                'asn':
                                '9a2b5a0f-e3af-6d14-9578-8825f229dc89'}]}

        self.drv.zfssa.get_replication_targets.return_value = targets
        self.drv.zfssa.edit_inherit_replication_flag.return_value = {}
        self.drv.zfssa.create_replication_action.return_value = 'action-123'
        self.drv.zfssa.send_repl_update.return_value = True

    @mock.patch.object(iscsi.LOG, 'warning')
    @mock.patch.object(iscsi.LOG, 'error')
    @mock.patch.object(iscsi, 'factory_zfssa')
    def test_parse_initiator_config(self, _factory_zfssa, elog, wlog):
        """Test the parsing of the old style initator config variables. """
        lcfg = self.configuration

        with mock.patch.object(lcfg, 'zfssa_initiator_config', ''):
            # Test empty zfssa_initiator_group
            with mock.patch.object(lcfg, 'zfssa_initiator_group', ''):
                self.assertRaises(exception.InvalidConfigurationValue,
                                  self.drv.do_setup, {})

            # Test empty zfssa_initiator with zfssa_initiator_group set to
            # a value other than "default"
            with mock.patch.object(lcfg, 'zfssa_initiator', ''):
                self.assertRaises(exception.InvalidConfigurationValue,
                                  self.drv.do_setup, {})

            # Test zfssa_initiator_group set to 'default' with non-empty
            # zfssa_initiator.
            with mock.patch.object(lcfg, 'zfssa_initiator_group', 'default'):
                self.drv.do_setup({})
                wlog.assert_called_with(mock.ANY,
                                        {'inigrp': lcfg.zfssa_initiator_group,
                                         'ini': lcfg.zfssa_initiator})

    def test_migrate_volume(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        # Test the normal case
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((True, None), result)

        # Test when volume status is not available
        volume['status'] = 'in-use'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        volume['status'] = 'available'

        # Test when vendor is not Oracle
        host['capabilities']['vendor_name'] = 'elcarO'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['vendor_name'] = 'Oracle'

        # Test when storage protocol is not iSCSI
        host['capabilities']['storage_protocol'] = 'not_iSCSI'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['storage_protocol'] = 'iSCSI'

        # Test when location_info is incorrect
        host['capabilities']['location_info'] = ''
        self.assertEqual((False, None), result)
        host['capabilities']['location_info'] = loc_info

        # Test if replication ip and replication target's address dont match
        invalid_loc_info = (
            '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:9.9.9.9')
        host['capabilities']['location_info'] = invalid_loc_info
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['location_info'] = loc_info

        # Test if no targets are returned
        self.drv.zfssa.get_replication_targets.return_value = {'targets': []}
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)

    def test_migrate_volume_uninherit_exception(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        self.drv.zfssa.edit_inherit_replication_flag.side_effect = (
            exception.VolumeBackendAPIException(data='uniherit ex'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.migrate_volume, ctxt, volume, host)

    def test_migrate_volume_create_action_exception(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        self.drv.zfssa.create_replication_action.side_effect = (
            exception.VolumeBackendAPIException(data=
                                                'failed to create action'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.migrate_volume, ctxt, volume, host)

    def test_migrate_volume_send_update_exception(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        self.drv.zfssa.send_repl_update.side_effect = (
            exception.VolumeBackendAPIException(data='failed to send update'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.migrate_volume, ctxt, volume, host)

    def test_migrate_volume_sever_repl_exception(self):
        self._util_migrate_volume_exceptions()

        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '2.2.2.2:fake_auth:pool2:project2:test-target-grp1:2.2.2.2'

        host = {'host': 'stack@zfssa_iscsi#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'iSCSI',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()
        self.drv.tgt_zfssa.sever_replication.side_effect = (
            exception.VolumeBackendAPIException(data=
                                                'failed to sever replication'))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.migrate_volume, ctxt, volume, host)

    def test_create_delete_volume(self):
        self.drv.zfssa.get_lun.return_value = {'guid':
                                               '00000000000000000000000000000',
                                               'number': 0,
                                               'initiatorgroup': 'default',
                                               'size': 1,
                                               'nodestroy': False}
        lcfg = self.configuration
        self.drv.create_volume(self.test_vol)
        self.drv.zfssa.create_lun.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            six.text_type(self.test_vol['size']) + 'g',
            lcfg.zfssa_target_group,
            mock.ANY)
        self.drv.delete_volume(self.test_vol)
        self.drv.zfssa.get_lun.assert_called_once_with(lcfg.zfssa_pool,
                                                       lcfg.zfssa_project,
                                                       self.test_vol['name'])
        self.drv.zfssa.delete_lun.assert_called_once_with(
            pool=lcfg.zfssa_pool,
            project=lcfg.zfssa_project,
            lun=self.test_vol['name'])

    def test_delete_volume_with_missing_lun(self):
        self.drv.zfssa.get_lun.side_effect = exception.VolumeNotFound(
            volume_id=self.test_vol['name'])
        self.drv.delete_volume(self.test_vol)
        self.drv.zfssa.delete_lun.assert_not_called()

    def test_delete_volume_backend_fail(self):
        self.drv.zfssa.get_lun.side_effect = \
            exception.VolumeBackendAPIException(data='fakemsg')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.delete_volume,
                          self.test_vol)

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_check_origin')
    def test_delete_cache_volume(self, _check_origin):
        lcfg = self.configuration
        lun2del = {
            'guid': '00000000000000000000000000000',
            'number': 0,
            'initiatorgroup': 'default',
            'size': 1,
            'nodestroy': False,
            'origin': {
                'project': lcfg.zfssa_cache_project,
                'snapshot': 'image-%s' % small_img['id'],
                'share': 'os-cache-vol-%s' % small_img['id'],
            }
        }
        self.drv.zfssa.get_lun.return_value = lun2del
        self.drv.delete_volume(self.test_vol)
        self.drv._check_origin.assert_called_once_with(lun2del,
                                                       self.test_vol['name'])

    def test_check_origin(self):
        lcfg = self.configuration
        lun2del = {
            'guid': '00000000000000000000000000000',
            'number': 0,
            'initiatorgroup': 'default',
            'size': 1,
            'nodestroy': False,
            'origin': {
                'project': lcfg.zfssa_cache_project,
                'snapshot': 'image-%s' % small_img['id'],
                'share': 'os-cache-vol-%s' % small_img['id'],
            }
        }
        cache = lun2del['origin']
        self.drv.zfssa.get_lun_snapshot.return_value = {
            'name': self.test_snap['name'],
            'numclones': 0
        }
        self.drv._check_origin(lun2del, 'volname')
        self.drv.zfssa.delete_lun.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_cache_project,
            cache['share'])

    def test_create_delete_snapshot(self):
        self.drv.zfssa.get_lun_snapshot.return_value = {
            'name': self.test_snap['name'],
            'numclones': 0
        }
        lcfg = self.configuration
        self.drv.create_snapshot(self.test_snap)
        self.drv.zfssa.create_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'])
        self.drv.delete_snapshot(self.test_snap)
        self.drv.zfssa.delete_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'])

    def test_delete_nonexistent_snapshot(self):
        self.drv.zfssa.get_lun_snapshot.side_effect = \
            exception.SnapshotNotFound(snapshot_id=self.test_snap['name'])
        self.drv.delete_snapshot(self.test_snap)
        self.drv.zfssa.delete_snapshot.assert_not_called()

    def test_delete_snapshot_backend_fail(self):
        self.drv.zfssa.get_lun_snapshot.side_effect = \
            exception.VolumeBackendAPIException(data='fakemsg')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.delete_snapshot,
                          self.test_snap)

    def test_create_volume_from_snapshot(self):
        lcfg = self.configuration
        self.drv.zfssa.get_lun.return_value = self.test_vol
        self.drv.create_snapshot(self.test_snap)
        self.drv.zfssa.create_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'])
        self.drv.create_volume_from_snapshot(self.test_vol_snap,
                                             self.test_snap)
        specs = self.drv._get_voltype_specs(self.test_vol)
        specs.update({'custom:cinder_managed': True})
        self.drv.zfssa.clone_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'],
            lcfg.zfssa_project,
            self.test_vol_snap['name'],
            specs)

    def test_create_larger_volume_from_snapshot(self):
        lcfg = self.configuration
        self.drv.zfssa.get_lun.return_value = self.test_vol
        self.drv.create_snapshot(self.test_snap)
        self.drv.zfssa.create_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'])

        # use the larger test volume
        self.drv.create_volume_from_snapshot(self.test_vol2,
                                             self.test_snap)
        specs = self.drv._get_voltype_specs(self.test_vol)
        specs.update({'custom:cinder_managed': True})
        self.drv.zfssa.clone_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_snap['volume_name'],
            self.test_snap['name'],
            lcfg.zfssa_project,
            self.test_vol2['name'],
            specs)

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_get_provider_info')
    def test_volume_attach_detach(self, _get_provider_info):
        lcfg = self.configuration
        test_target_iqn = 'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd'
        self.drv._get_provider_info.return_value = {
            'provider_location': '%s %s' % (lcfg.zfssa_target_portal,
                                            test_target_iqn)
        }

        def side_effect_get_initiator_initiatorgroup(arg):
            return [{
                'iqn.1-0.org.deb:01:d7': 'test-init-grp1',
                'iqn.1-0.org.deb:01:d9': 'test-init-grp2',
            }[arg]]

        self.drv.zfssa.get_initiator_initiatorgroup.side_effect = (
            side_effect_get_initiator_initiatorgroup)

        initiator = 'iqn.1-0.org.deb:01:d7'
        initiator_group = 'test-init-grp1'
        lu_number = '246'

        self.drv.zfssa.get_lun.side_effect = iter([
            {'initiatorgroup': [], 'number': []},
            {'initiatorgroup': [initiator_group], 'number': [lu_number]},
            {'initiatorgroup': [initiator_group], 'number': [lu_number]},
        ])

        connector = dict(initiator=initiator)
        props = self.drv.initialize_connection(self.test_vol, connector)
        self.drv._get_provider_info.assert_called_once_with()
        self.assertEqual('iscsi', props['driver_volume_type'])
        self.assertEqual(self.test_vol['id'], props['data']['volume_id'])
        self.assertEqual(lcfg.zfssa_target_portal,
                         props['data']['target_portal'])
        self.assertEqual(test_target_iqn, props['data']['target_iqn'])
        self.assertEqual(int(lu_number), props['data']['target_lun'])
        self.assertFalse(props['data']['target_discovered'])
        self.drv.zfssa.set_lun_initiatorgroup.assert_called_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            [initiator_group])

        self.drv.terminate_connection(self.test_vol, connector)
        self.drv.zfssa.set_lun_initiatorgroup.assert_called_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            [])

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_get_provider_info')
    def test_volume_attach_detach_multipath(self, _get_provider_info):
        lcfg = self.configuration
        test_target_iqn = 'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd'
        self.drv._get_provider_info.return_value = {
            'provider_location': '%s %s' % (lcfg.zfssa_target_portal,
                                            test_target_iqn)
        }

        def side_effect_get_initiator_initiatorgroup(arg):
            return [{
                'iqn.1-0.org.deb:01:d7': 'test-init-grp1',
                'iqn.1-0.org.deb:01:d9': 'test-init-grp2',
            }[arg]]

        self.drv.zfssa.get_initiator_initiatorgroup.side_effect = (
            side_effect_get_initiator_initiatorgroup)

        initiator = 'iqn.1-0.org.deb:01:d7'
        initiator_group = 'test-init-grp1'
        lu_number = '246'

        self.drv.zfssa.get_lun.side_effect = iter([
            {'initiatorgroup': [], 'number': []},
            {'initiatorgroup': [initiator_group], 'number': [lu_number]},
            {'initiatorgroup': [initiator_group], 'number': [lu_number]},
        ])

        connector = {
            'initiator': initiator,
            'multipath': True
        }
        props = self.drv.initialize_connection(self.test_vol, connector)
        self.drv._get_provider_info.assert_called_once_with()
        self.assertEqual('iscsi', props['driver_volume_type'])
        self.assertEqual(self.test_vol['id'], props['data']['volume_id'])
        self.assertEqual([lcfg.zfssa_target_portal],
                         props['data']['target_portals'])
        self.assertEqual([test_target_iqn], props['data']['target_iqns'])
        self.assertEqual([int(lu_number)], props['data']['target_luns'])
        self.assertFalse(props['data']['target_discovered'])
        self.drv.zfssa.set_lun_initiatorgroup.assert_called_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            [initiator_group])

        self.drv.terminate_connection(self.test_vol, connector)
        self.drv.zfssa.set_lun_initiatorgroup.assert_called_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            [])

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_get_provider_info')
    def test_volume_attach_detach_live_migration(self, _get_provider_info):
        lcfg = self.configuration
        test_target_iqn = 'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd'
        self.drv._get_provider_info.return_value = {
            'provider_location': '%s %s' % (lcfg.zfssa_target_portal,
                                            test_target_iqn)
        }

        def side_effect_get_initiator_initiatorgroup(arg):
            return [{
                'iqn.1-0.org.deb:01:d7': 'test-init-grp1',
                'iqn.1-0.org.deb:01:d9': 'test-init-grp2',
            }[arg]]

        self.drv.zfssa.get_initiator_initiatorgroup.side_effect = (
            side_effect_get_initiator_initiatorgroup)

        src_initiator = 'iqn.1-0.org.deb:01:d7'
        src_initiator_group = 'test-init-grp1'
        src_connector = dict(initiator=src_initiator)
        src_lu_number = '123'

        dst_initiator = 'iqn.1-0.org.deb:01:d9'
        dst_initiator_group = 'test-init-grp2'
        dst_connector = dict(initiator=dst_initiator)
        dst_lu_number = '456'

        # In the beginning, the LUN is already presented to the source
        # node. During initialize_connection(), and at the beginning of
        # terminate_connection(), it's presented to both nodes.
        self.drv.zfssa.get_lun.side_effect = iter([
            {'initiatorgroup': [src_initiator_group],
             'number': [src_lu_number]},
            {'initiatorgroup': [dst_initiator_group, src_initiator_group],
             'number': [dst_lu_number, src_lu_number]},
            {'initiatorgroup': [dst_initiator_group, src_initiator_group],
             'number': [dst_lu_number, src_lu_number]},
        ])

        # Before migration, the volume gets connected to the destination
        # node (whilst still connected to the source node), so it should
        # be presented to the initiator groups for both
        props = self.drv.initialize_connection(self.test_vol, dst_connector)
        self.drv.zfssa.set_lun_initiatorgroup.assert_called_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            [src_initiator_group, dst_initiator_group])

        # LU number must be an int -
        # https://bugs.launchpad.net/cinder/+bug/1538582
        # and must be the LU number for the destination node's
        # initiatorgroup (where the connection was just initialized)
        self.assertEqual(int(dst_lu_number), props['data']['target_lun'])

        # After migration, the volume gets detached from the source node
        # so it should be present to only the destination node
        self.drv.terminate_connection(self.test_vol, src_connector)
        self.drv.zfssa.set_lun_initiatorgroup.assert_called_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            [dst_initiator_group])

    def test_volume_attach_detach_negative(self):
        self.drv.zfssa.get_initiator_initiatorgroup.return_value = []

        connector = dict(initiator='iqn.1-0.org.deb:01:d7')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.initialize_connection,
                          self.test_vol,
                          connector)

    def test_get_volume_stats(self):
        self.drv.zfssa.get_project_stats.return_value = 2 * units.Gi,\
            3 * units.Gi
        self.drv.zfssa.get_pool_details.return_value = \
            {"profile": "mirror:log_stripe"}
        lcfg = self.configuration
        stats = self.drv.get_volume_stats(refresh=True)
        self.drv.zfssa.get_project_stats.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project)
        self.drv.zfssa.get_pool_details.assert_called_once_with(
            lcfg.zfssa_pool)
        self.assertEqual('Oracle', stats['vendor_name'])
        self.assertEqual(self.configuration.volume_backend_name,
                         stats['volume_backend_name'])
        self.assertEqual(self.drv.VERSION, stats['driver_version'])
        self.assertEqual(self.drv.protocol, stats['storage_protocol'])
        self.assertEqual(0, stats['reserved_percentage'])
        self.assertFalse(stats['QoS_support'])
        self.assertEqual(3, stats['total_capacity_gb'])
        self.assertEqual(2, stats['free_capacity_gb'])
        self.assertEqual('mirror:log_stripe', stats['zfssa_poolprofile'])
        self.assertEqual('8k', stats['zfssa_volblocksize'])
        self.assertEqual('false', stats['zfssa_sparse'])
        self.assertEqual('off', stats['zfssa_compression'])
        self.assertEqual('latency', stats['zfssa_logbias'])

        self.drv.zfssa.get_pool_details.return_value = {"profile": "raidz2"}
        stats = self.drv.get_volume_stats(refresh=True)
        self.assertEqual('raidz2', stats['zfssa_poolprofile'])

    def test_extend_volume(self):
        lcfg = self.configuration
        self.drv.extend_volume(self.test_vol, 3)
        self.drv.zfssa.set_lun_props.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            self.test_vol['name'],
            volsize= 3 * units.Gi)

    @mock.patch('cinder.volume.volume_types.get_volume_type_extra_specs')
    def test_get_voltype_specs(self, get_volume_type_extra_specs):
        volume_type_id = mock.sentinel.volume_type_id
        volume = {'volume_type_id': volume_type_id}
        get_volume_type_extra_specs.return_value = {
            'zfssa:volblocksize': '128k',
            'zfssa:compression': 'gzip'
        }
        ret = self.drv._get_voltype_specs(volume)
        self.assertEqual('128k', ret.get('volblocksize'))
        self.assertEqual(self.configuration.zfssa_lun_sparse,
                         ret.get('sparse'))
        self.assertEqual('gzip', ret.get('compression'))
        self.assertEqual(self.configuration.zfssa_lun_logbias,
                         ret.get('logbias'))

    def fake_safe_get(self, value):
        try:
            val = getattr(self.configuration, value)
        except AttributeError:
            val = None
        return val

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_verify_cache_volume')
    def test_clone_image_negative(self, _verify_cache_volume):
        # Disabling local cache feature:
        self.configuration.zfssa_enable_local_cache = False

        self.assertEqual((None, False),
                         self.drv.clone_image(fakecontext, self.test_vol,
                                              img_location,
                                              small_img,
                                              img_service))

        self.configuration.zfssa_enable_local_cache = True
        # Creating a volume smaller than image:
        self.assertEqual((None, False),
                         self.drv.clone_image(fakecontext, self.test_vol,
                                              img_location,
                                              large_img,
                                              img_service))

        # Creating a volume equal as image:
        eq_img = large_img.copy()
        eq_img['virtual_size'] = self.test_vol['size'] * units.Gi
        self.assertEqual((None, False),
                         self.drv.clone_image(fakecontext, self.test_vol,
                                              img_location,
                                              eq_img,
                                              img_service))

        # Exception raised in _verify_cache_image
        self.drv._verify_cache_volume.side_effect = (
            exception.VolumeBackendAPIException('fakeerror'))
        self.assertEqual((None, False),
                         self.drv.clone_image(fakecontext, self.test_vol,
                                              img_location,
                                              small_img,
                                              img_service))

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_get_voltype_specs')
    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_verify_cache_volume')
    @mock.patch.object(iscsi.ZFSSAISCSIDriver, 'extend_volume')
    def test_clone_image(self, _extend_vol, _verify_cache, _get_specs):
        lcfg = self.configuration
        cache_vol = 'volume-os-cache-vol-%s' % small_img['id']
        cache_snap = 'image-%s' % small_img['id']
        self.drv._get_voltype_specs.return_value = fakespecs.copy()
        self.drv._verify_cache_volume.return_value = cache_vol, cache_snap

        model, cloned = self.drv.clone_image(fakecontext, self.test_vol2,
                                             img_location,
                                             small_img,
                                             img_service)
        specs = fakespecs
        specs.update({'custom:cinder_managed': True})
        self.drv._verify_cache_volume.assert_called_once_with(fakecontext,
                                                              small_img,
                                                              img_service,
                                                              fakespecs,
                                                              small_img_props)
        self.drv.zfssa.clone_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_cache_project,
            cache_vol,
            cache_snap,
            lcfg.zfssa_project,
            self.test_vol2['name'],
            specs)

        self.drv.extend_volume.assert_called_once_with(self.test_vol2,
                                                       self.test_vol2['size'])

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_create_cache_volume')
    def test_verify_cache_vol_no_cache_vol(self, _create_cache_vol):
        vol_name = 'os-cache-vol-%s' % small_img['id']
        self.drv.zfssa.get_lun.side_effect = exception.VolumeNotFound(
            volume_id=vol_name)
        self.drv._verify_cache_volume(fakecontext, small_img,
                                      img_service, fakespecs, small_img_props)
        self.drv._create_cache_volume.assert_called_once_with(fakecontext,
                                                              small_img,
                                                              img_service,
                                                              fakespecs,
                                                              small_img_props)

    def test_verify_cache_vol_no_cache_snap(self):
        snap_name = 'image-%s' % small_img['id']
        self.drv.zfssa.get_lun_snapshot.side_effect = (
            exception.SnapshotNotFound(snapshot_id=snap_name))
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv._verify_cache_volume,
                          fakecontext,
                          small_img,
                          img_service,
                          fakespecs,
                          small_img_props)

    def test_verify_cache_vol_stale_vol(self):
        self.drv.zfssa.get_lun_snapshot.return_value = {'numclones': 5}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv._verify_cache_volume,
                          fakecontext,
                          small_img,
                          img_service,
                          fakespecs,
                          small_img_props)

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_create_cache_volume')
    def test_verify_cache_vol_updated_vol(self, _create_cache_vol):
        lcfg = self.configuration
        updated_vol = {
            'updated_at': date(3000, 12, 12),
            'image_id': 'updated_id',
        }
        cachevol_name = 'os-cache-vol-%s' % small_img['id']
        self.drv.zfssa.get_lun.return_value = updated_vol
        self.drv.zfssa.get_lun_snapshot.return_value = {'numclones': 0}
        self.drv._verify_cache_volume(fakecontext, small_img,
                                      img_service, fakespecs, small_img_props)
        self.drv.zfssa.delete_lun.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_cache_project,
            cachevol_name)
        self.drv._create_cache_volume.assert_called_once_with(fakecontext,
                                                              small_img,
                                                              img_service,
                                                              fakespecs,
                                                              small_img_props)

    @mock.patch.object(driver.BaseVD, 'copy_image_to_volume')
    def test_create_cache_volume(self, _copy_image):
        lcfg = self.configuration
        virtual_size = int(small_img['virtual_size'])
        volsize = math.ceil(float(virtual_size) / units.Gi)
        lunsize = "%sg" % six.text_type(int(volsize))
        volname = 'os-cache-vol-%s' % small_img['id']
        snapname = 'image-%s' % small_img['id']
        cachevol_props = {
            'cache_name': volname,
            'snap_name': snapname,
        }
        cachevol_props.update(small_img_props)
        cache_vol = {
            'name': volname,
            'id': small_img['id'],
            'size': volsize,
        }
        lun_props = {
            'custom:image_id': small_img['id'],
            'custom:updated_at': (
                six.text_type(small_img['updated_at'].isoformat())),
        }
        lun_props.update(fakespecs)

        self.drv._create_cache_volume(fakecontext,
                                      small_img,
                                      img_service,
                                      fakespecs,
                                      cachevol_props)

        self.drv.zfssa.create_lun.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_cache_project,
            cache_vol['name'],
            lunsize,
            lcfg.zfssa_target_group,
            lun_props)
        _copy_image.assert_called_once_with(fakecontext,
                                            cache_vol,
                                            img_service,
                                            small_img['id'])
        self.drv.zfssa.create_snapshot.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_cache_project,
            cache_vol['name'],
            snapname)

    def test_create_cache_vol_negative(self):
        lcfg = self.configuration
        volname = 'os-cache-vol-%s' % small_img['id']
        snapname = 'image-%s' % small_img['id']
        cachevol_props = {
            'cache_name': volname,
            'snap_name': snapname,
        }
        cachevol_props.update(small_img)

        self.drv.zfssa.get_lun.side_effect = exception.VolumeNotFound(
            volume_id=volname)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv._create_cache_volume,
                          fakecontext,
                          small_img,
                          img_service,
                          fakespecs,
                          cachevol_props)
        self.drv.zfssa.delete_lun.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_cache_project,
            volname)

    def test_get_manageable_volumes(self):
        lcfg = self.configuration

        self.drv.zfssa.get_all_luns.return_value = [
            {'name': 'volume-11111111-1111-1111-1111-111111111111',
             'size': 111 * units.Gi,
             'cinder_managed': True},
            {'name': 'volume2',
             'size': 222 * units.Gi,
             'cinder_managed': False},
            {'name': 'volume-33333333-3333-3333-3333-333333333333',
             'size': 333 * units.Gi,
             'cinder_managed': True},
            {'name': 'volume4',
             'size': 444 * units.Gi}
        ]

        cinder_vols = [{'id': '11111111-1111-1111-1111-111111111111'}]
        args = (cinder_vols, None, 1000, 0, ['size'], ['asc'])

        lcfg.zfssa_manage_policy = 'strict'
        expected = [
            {'reference': {'source-name':
                           'volume-11111111-1111-1111-1111-111111111111'},
             'size': 111,
             'safe_to_manage': False,
             'reason_not_safe': 'already managed',
             'cinder_id': '11111111-1111-1111-1111-111111111111',
             'extra_info': None},
            {'reference': {'source-name': 'volume2'},
             'size': 222,
             'safe_to_manage': True,
             'reason_not_safe': None,
             'cinder_id': None,
             'extra_info': None},
            {'reference': {'source-name':
                           'volume-33333333-3333-3333-3333-333333333333'},
             'size': 333,
             'safe_to_manage': False,
             'reason_not_safe': 'managed by another cinder instance?',
             'cinder_id': None,
             'extra_info': None},
            {'reference': {'source-name': 'volume4'},
             'size': 444,
             'safe_to_manage': False,
             'reason_not_safe': 'cinder_managed schema not present',
             'cinder_id': None,
             'extra_info': None},
        ]

        result = self.drv.get_manageable_volumes(*args)
        self.assertEqual(expected, result)

        lcfg.zfssa_manage_policy = 'loose'
        expected[3]['safe_to_manage'] = True
        expected[3]['reason_not_safe'] = None

        result = self.drv.get_manageable_volumes(*args)
        self.assertEqual(expected, result)

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_get_existing_vol')
    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_verify_volume_to_manage')
    def test_volume_manage(self, _get_existing_vol, _verify_volume_to_manage):
        lcfg = self.configuration
        lcfg.zfssa_manage_policy = 'loose'
        test_vol = self.test_vol
        self.drv._get_existing_vol.return_value = test_vol
        self.drv._verify_volume_to_manage.return_value = None
        self.drv.zfssa.set_lun_props.return_value = True
        self.assertIsNone(self.drv.manage_existing({'name': 'volume-123'},
                                                   {'source-name':
                                                       'volume-567'}))
        self.drv._get_existing_vol.assert_called_once_with({'source-name':
                                                            'volume-567'})
        self.drv._verify_volume_to_manage.assert_called_once_with(test_vol)
        self.drv.zfssa.set_lun_props.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            test_vol['name'],
            name='volume-123',
            schema={"custom:cinder_managed": True})

        # Case when zfssa_manage_policy is 'loose' and 'cinder_managed' is
        # set to true.
        test_vol.update({'cinder_managed': False})
        self.assertIsNone(self.drv.manage_existing({'name': 'volume-123'},
                                                   {'source-name':
                                                       'volume-567'}))

        # Another case is when the zfssa_manage_policy is set to 'strict'
        lcfg.zfssa_manage_policy = 'strict'
        test_vol.update({'cinder_managed': False})
        self.assertIsNone(self.drv.manage_existing({'name': 'volume-123'},
                                                   {'source-name':
                                                       'volume-567'}))

    def test_volume_manage_negative(self):
        lcfg = self.configuration
        lcfg.zfssa_manage_policy = 'strict'
        test_vol = self.test_vol

        if 'cinder_managed' in test_vol:
            del test_vol['cinder_managed']

        self.drv.zfssa.get_lun.return_value = test_vol
        self.assertRaises(exception.InvalidInput,
                          self.drv.manage_existing, {'name': 'cindervol'},
                          {'source-name': 'volume-567'})

        test_vol.update({'cinder_managed': True})
        self.drv.zfssa.get_lun.return_value = test_vol
        self.assertRaises(exception.ManageExistingAlreadyManaged,
                          self.drv.manage_existing, {'name': 'cindervol'},
                          {'source-name': 'volume-567'})

        test_vol.update({'cinder_managed': False})
        self.drv.zfssa.get_lun.return_value = test_vol
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.drv.manage_existing, {'name': 'cindervol'},
                          {'source-id': 'volume-567'})

        lcfg.zfssa_manage_policy = 'loose'
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.drv.manage_existing, {'name': 'cindervol'},
                          {'source-id': 'volume-567'})

    def test_volume_manage_nonexistent(self):
        self.drv.zfssa.get_lun.side_effect = \
            exception.VolumeNotFound(volume_id='bogus_lun')
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.drv.manage_existing, {'name': 'cindervol'},
                          {'source-name': 'bogus_lun'})

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_verify_volume_to_manage')
    def test_volume_manage_negative_api_exception(self,
                                                  _verify_volume_to_manage):
        lcfg = self.configuration
        lcfg.zfssa_manage_policy = 'loose'
        self.drv.zfssa.get_lun.return_value = self.test_vol
        self.drv._verify_volume_to_manage.return_value = None
        self.drv.zfssa.set_lun_props.side_effect = \
            exception.VolumeBackendAPIException(data='fake exception')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.manage_existing, {'name': 'volume-123'},
                          {'source-name': 'volume-567'})

    def test_volume_unmanage(self):
        lcfg = self.configuration
        self.drv.zfssa.set_lun_props.return_value = True
        self.assertIsNone(self.drv.unmanage({'name': 'volume-123'}))
        self.drv.zfssa.set_lun_props.assert_called_once_with(
            lcfg.zfssa_pool,
            lcfg.zfssa_project,
            'volume-123',
            name='unmanaged-volume-123',
            schema={"custom:cinder_managed": False})

    def test_volume_unmanage_negative(self):
        self.drv.zfssa.set_lun_props.side_effect = \
            exception.VolumeBackendAPIException(data='fake exception')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.unmanage, {'name': 'volume-123'})

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_get_existing_vol')
    def test_manage_existing_get_size(self, _get_existing_vol):
        test_vol = self.test_vol
        test_vol['size'] = 3 * units.Gi
        self.drv._get_existing_vol.return_value = test_vol
        self.assertEqual(3, self.drv.manage_existing_get_size(
                         {'name': 'volume-123'},
                         {'source-name': 'volume-567'}))

    @mock.patch.object(iscsi.ZFSSAISCSIDriver, '_get_existing_vol')
    def test_manage_existing_get_size_negative(self, _get_existing_vol):
        self.drv._get_existing_vol.side_effect = \
            exception.VolumeNotFound(volume_id='123')
        self.assertRaises(exception.VolumeNotFound,
                          self.drv.manage_existing_get_size,
                          {'name': 'volume-123'},
                          {'source-name': 'volume-567'})


class TestZFSSANFSDriver(test.TestCase):

    test_vol = {
        'name': 'test-vol',
        'id': '1',
        'size': 3,
        'provider_location':
        'fakelocation',
    }

    test_snap = {
        'name': 'cindersnap',
        'volume_name': test_vol['name'],
        'volume_size': test_vol['size']
    }

    test_vol_snap = {
        'name': 'cindersnapvol',
        'size': test_vol['size']
    }

    def setUp(self):
        super(TestZFSSANFSDriver, self).setUp()
        self._create_fake_config()
        self.mock_object(zfssanfs, 'factory_zfssa', spec=rest.ZFSSAApi)
        self.mock_object(volume_utils, 'get_max_over_subscription_ratio',
                         return_value=1.0)
        self.drv = zfssanfs.ZFSSANFSDriver(configuration=self.configuration)
        self.drv._execute = fake_utils.fake_execute
        self.drv.do_setup({})
        self.drv.mount_path = 'fake_mount_path'
        self.context = context.get_admin_context()

    def _create_fake_config(self):
        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.reserved_percentage = 0
        self.configuration.max_over_subscription_ratio = 20.0
        self.configuration.san_ip = '1.1.1.1'
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'passwd'
        self.configuration.zfssa_data_ip = '2.2.2.2'
        self.configuration.zfssa_https_port = '443'
        self.configuration.zfssa_nfs_pool = 'pool'
        self.configuration.zfssa_nfs_project = 'nfs_project'
        self.configuration.zfssa_nfs_share = 'nfs_share'
        self.configuration.zfssa_nfs_share_logbias = nfs_logbias
        self.configuration.zfssa_nfs_share_compression = nfs_compression
        self.configuration.zfssa_nfs_mount_options = ''
        self.configuration.zfssa_rest_timeout = '30'
        self.configuration.zfssa_enable_local_cache = True
        self.configuration.zfssa_cache_directory = zfssa_cache_dir
        self.configuration.nfs_sparsed_volumes = 'true'
        self.configuration.nfs_mount_point_base = '$state_path/mnt'
        self.configuration.nfs_mount_options = None
        self.configuration.zfssa_manage_policy = 'strict'

    def test_setup_nfs_client(self):
        mock_execute = self.mock_object(self.drv, '_execute',
                                        side_effect= OSError(errno.ENOENT,
                                                             'No such file or '
                                                             'directory.'))

        self.assertRaises(exception.NfsException, self.drv.do_setup,
                          self.context)
        mock_execute.assert_has_calls(
            [mock.call('mount.nfs',
                       check_exit_code=False,
                       run_as_root=True),
             mock.call('/usr/sbin/mount',
                       check_exit_code=False,
                       run_as_root=True)])

    def test_migrate_volume(self):
        self.drv.zfssa.get_asn.return_value = (
            '9a2b5a0f-e3af-6d14-9578-8825f229dc89')
        volume = self.test_vol
        volume.update({'host': 'fake_host',
                       'status': 'available',
                       'name': 'vol-1',
                       'source_volid': self.test_vol['id']})

        loc_info = '9a2b5a0f-e3af-6d14-9578-8825f229dc89:nfs_share'

        host = {'host': 'stack@zfssa_nfs#fake_zfssa',
                'capabilities': {'vendor_name': 'Oracle',
                                 'storage_protocol': 'nfs',
                                 'location_info': loc_info}}
        ctxt = context.get_admin_context()

        # Test Normal case
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((True, None), result)

        # Test when volume status is not available
        volume['status'] = 'in-use'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        volume['status'] = 'available'

        # Test when Vendor is not Oracle
        host['capabilities']['vendor_name'] = 'elcarO'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['vendor_name'] = 'Oracle'

        # Test when storage protocol is not iSCSI
        host['capabilities']['storage_protocol'] = 'not_nfs'
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['storage_protocol'] = 'nfs'

        # Test for exceptions
        host['capabilities']['location_info'] = ''
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)
        host['capabilities']['location_info'] = loc_info

        # Test case when source and target asn dont match
        invalid_loc_info = (
            'fake_asn*https://2.2.2.2:/shares/export/nfs_share*nfs_share')
        host['capabilities']['location_info'] = invalid_loc_info
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)

        # Test case when source and target shares names are different
        invalid_loc_info = (
            '9a2b5a0f-e3af-6d14-9578-8825f229dc89*' +
            'https://tgt:/shares/export/nfs_share*nfs_share_1')
        host['capabilities']['location_info'] = invalid_loc_info
        result = self.drv.migrate_volume(ctxt, volume, host)
        self.assertEqual((False, None), result)

    def test_create_delete_snapshot(self):
        lcfg = self.configuration
        self.drv.create_snapshot(self.test_snap)
        self.drv.zfssa.create_snapshot.assert_called_once_with(
            lcfg.zfssa_nfs_pool,
            lcfg.zfssa_nfs_project,
            lcfg.zfssa_nfs_share,
            mock.ANY)
        self.drv.zfssa.create_snapshot_of_volume_file.assert_called_once_with(
            src_file=mock.ANY,
            dst_file=self.test_snap['name'])
        self.drv.delete_snapshot(self.test_snap)
        self.drv.zfssa.delete_snapshot_of_volume_file.assert_called_with(
            src_file=self.test_snap['name'])

    def test_create_volume_from_snapshot(self):
        self.drv.create_snapshot(self.test_snap)
        with mock.patch.object(self.drv, '_ensure_shares_mounted'):
            self.drv.create_volume_from_snapshot(self.test_vol_snap,
                                                 self.test_snap,
                                                 method='COPY')

        self.drv.zfssa.create_volume_from_snapshot_file.\
            assert_called_once_with(src_file=self.test_snap['name'],
                                    dst_file=self.test_vol_snap['name'],
                                    method='COPY')

    def test_get_volume_stats(self):
        lcfg = self.configuration
        self.drv._mounted_shares = ['nfs_share']
        with mock.patch.object(self.drv, '_ensure_shares_mounted'):
            with mock.patch.object(self.drv, '_get_share_capacity_info') as \
                    mock_get_share_capacity_info:
                mock_get_share_capacity_info.return_value = (1073741824,
                                                             9663676416)
                self.drv.zfssa.get_pool_details.return_value = \
                    {"profile": "mirror:log_stripe"}
                self.drv.zfssa.get_share.return_value = {"compression": "lzjb",
                                                         "encryption": "off",
                                                         "logbias": "latency"}
                stats = self.drv.get_volume_stats(refresh=True)
                self.drv.zfssa.get_pool_details.assert_called_once_with(
                    lcfg.zfssa_nfs_pool)
                self.drv.zfssa.get_share.assert_called_with(
                    lcfg.zfssa_nfs_pool, lcfg.zfssa_nfs_project,
                    lcfg.zfssa_nfs_share)

                self.assertEqual(1, stats['free_capacity_gb'])
                self.assertEqual(10, stats['total_capacity_gb'])
                self.assertEqual('mirror:log_stripe',
                                 stats['zfssa_poolprofile'])
                self.assertEqual('lzjb', stats['zfssa_compression'])
                self.assertEqual('true', stats['zfssa_sparse'])
                self.assertEqual('off', stats['zfssa_encryption'])
                self.assertEqual('latency', stats['zfssa_logbias'])

                self.drv.zfssa.get_pool_details.return_value = \
                    {"profile": "mirror3"}
                stats = self.drv.get_volume_stats(refresh=True)
                self.assertEqual('mirror3', stats['zfssa_poolprofile'])

    @mock.patch.object(nfsdriver.NfsDriver, 'delete_volume')
    @mock.patch.object(zfssanfs.ZFSSANFSDriver, '_check_origin')
    def test_delete_volume(self, _check_origin, _delete_vol):
        self.drv.zfssa.get_volume.side_effect = self._get_volume_side_effect
        test_vol = zfssanfs.Volume()
        test_vol._name_id = small_img['id']
        test_vol.size = 3
        test_vol.provider_location = 'fakelocation'

        self.drv.delete_volume(test_vol)
        _delete_vol.assert_called_once_with(test_vol)
        self.drv._check_origin.assert_called_once_with(img_props_nfs['name'])

    def _get_volume_side_effect(self, *args, **kwargs):
        lcfg = self.configuration
        volname = six.text_type(args[0])
        if volname.startswith(lcfg.zfssa_cache_directory):
            return {'numclones': 0}
        else:
            return {'origin': img_props_nfs['name']}

    def test_check_origin(self):
        self.drv.zfssa.get_volume.side_effect = self._get_volume_side_effect
        self.drv._check_origin(img_props_nfs['name'])
        self.drv.zfssa.delete_file.assert_called_once_with(
            img_props_nfs['name'])

    @mock.patch.object(image_utils, 'qemu_img_info')
    @mock.patch.object(image_utils.TemporaryImages, 'fetch')
    @mock.patch.object(zfssanfs.ZFSSANFSDriver, '_verify_cache_volume')
    @mock.patch.object(zfssanfs.ZFSSANFSDriver, 'create_cloned_volume')
    def test_clone_image_negative(self, _create_clone, _verify_cache_volume,
                                  _fetch, _info):
        _fetch.return_value = mock.MagicMock(spec=utils.get_file_spec())
        _info.return_value = ImgInfo(small_img['virtual_size'])

        # Disabling local cache feature:
        self.configuration.zfssa_enable_local_cache = False
        self.assertEqual((None, False),
                         self.drv.clone_image(fakecontext, self.test_vol,
                                              img_location,
                                              small_img,
                                              img_service))

        self.configuration.zfssa_enable_local_cache = True

        # Creating a volume smaller than image:
        _info.return_value = ImgInfo(large_img['virtual_size'])
        self.assertEqual((None, False),
                         self.drv.clone_image(fakecontext, self.test_vol,
                                              img_location,
                                              large_img,
                                              img_service))

        # Exception raised in _verify_cache_image
        _info.return_value = ImgInfo(small_img['virtual_size'])
        self.drv._verify_cache_volume.side_effect = (
            exception.VolumeBackendAPIException('fakeerror'))
        self.assertEqual((None, False),
                         self.drv.clone_image(fakecontext, self.test_vol,
                                              img_location,
                                              small_img,
                                              img_service))

    @mock.patch.object(image_utils, 'qemu_img_info')
    @mock.patch.object(image_utils.TemporaryImages, 'fetch')
    @mock.patch.object(zfssanfs.ZFSSANFSDriver, 'create_cloned_volume')
    @mock.patch.object(zfssanfs.ZFSSANFSDriver, '_verify_cache_volume')
    @mock.patch.object(zfssanfs.ZFSSANFSDriver, 'extend_volume')
    def test_clone_image(self, _extend_vol, _verify_cache, _create_clone,
                         _fetch, _info):
        _fetch.return_value = mock.MagicMock(spec=utils.get_file_spec())
        _info.return_value = ImgInfo(small_img['virtual_size'])
        self.drv._verify_cache_volume.return_value = \
            'volume-' + img_props_nfs['id']
        prov_loc = {'provider_location': self.test_vol['provider_location']}
        self.drv.create_cloned_volume.return_value = prov_loc
        self.assertEqual((prov_loc, True),
                         self.drv.clone_image(fakecontext, self.test_vol,
                                              img_location,
                                              small_img,
                                              img_service))
        img_props = {}
        img_props['id'] = img_props_nfs['image_id']
        img_props['image_id'] = img_props_nfs['image_id']
        img_props['updated_at'] = img_props_nfs['updated_at']
        img_props['size'] = img_props_nfs['size']

        self.drv._verify_cache_volume.assert_called_once_with(fakecontext,
                                                              small_img,
                                                              img_service,
                                                              img_props)
        cache_vol = {
            'name': self.drv._verify_cache_volume.return_value,
            'size': 3,
            'id': small_img['id'],
        }
        self.drv.create_cloned_volume.assert_called_once_with(self.test_vol,
                                                              cache_vol)

    @mock.patch.object(zfssanfs.ZFSSANFSDriver, '_create_cache_volume')
    def test_verify_cache_vol_no_cache_vol(self, _create_cache_vol):
        self.drv.zfssa.get_volume.side_effect = exception.VolumeNotFound(
            volume_id=img_props_nfs['name'])
        self.drv._verify_cache_volume(fakecontext, small_img,
                                      img_service, img_props_nfs)
        self.drv._create_cache_volume.assert_called_once_with(fakecontext,
                                                              small_img,
                                                              img_service,
                                                              img_props_nfs)

    def test_verify_cache_vol_stale_vol(self):
        self.drv.zfssa.get_volume.return_value = {
            'numclones': 5,
            'updated_at': small_img['updated_at'].isoformat(),
            'image_id': 'wrong_id',
        }
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv._verify_cache_volume,
                          fakecontext,
                          small_img,
                          img_service,
                          img_props_nfs)

    @mock.patch.object(zfssanfs.ZFSSANFSDriver, '_create_cache_volume')
    @mock.patch.object(nfsdriver.NfsDriver, 'delete_volume')
    def test_verify_cache_vol_updated_vol(self, _del_vol, _create_cache_vol):
        updated_vol = {
            'updated_at': date(3000, 12, 12),
            'image_id': 'updated_id',
            'numclones': 0,
        }
        self.drv.zfssa.get_volume.return_value = updated_vol
        self.drv._verify_cache_volume(fakecontext, small_img,
                                      img_service, img_props_nfs)

        self.drv._create_cache_volume.assert_called_once_with(fakecontext,
                                                              small_img,
                                                              img_service,
                                                              img_props_nfs)

    @mock.patch.object(remotefs.RemoteFSDriver, 'copy_image_to_volume')
    @mock.patch.object(nfsdriver.NfsDriver, 'create_volume')
    def test_create_cache_volume(self, _create_vol, _copy_image):
        self.drv.zfssa.webdavclient = mock.Mock()
        self.drv._create_cache_volume(fakecontext,
                                      small_img,
                                      img_service,
                                      img_props_nfs)

        self.assertEqual(1, _create_vol.call_count)
        self.assertEqual(1, _copy_image.call_count)

    def test_create_cache_vol_negative(self):
        self.drv.zfssa.get_lun.side_effect = (
            exception.VolumeBackendAPIException)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv._create_cache_volume,
                          fakecontext,
                          small_img,
                          img_service,
                          img_props_nfs)
        self.drv.zfssa.delete_file.assert_called_once_with(
            'os-cinder-cache/volume-' + img_props_nfs['id'])

    def test_volume_manage(self):
        lcfg = self.configuration
        lcfg.zfssa_manage_policy = 'loose'
        test_vol = self.test_vol

        self.drv.zfssa.get_volume.return_value = test_vol
        self.drv.zfssa.rename_volume.return_value = None
        self.drv.zfssa.set_file_props.return_value = None
        self.drv.mount_path = lcfg.zfssa_data_ip + ':' + 'fake_mountpoint'
        self.assertEqual({'provider_location': self.drv.mount_path},
                         self.drv.manage_existing({'name': 'volume-123'},
                                                  {'source-name':
                                                      'volume-567'}))

        self.drv.zfssa.get_volume.assert_called_once_with('volume-567')
        self.drv.zfssa.rename_volume.assert_called_once_with('volume-567',
                                                             'volume-123')
        self.drv.zfssa.set_file_props.assert_called_once_with(
            'volume-123', {'cinder_managed': 'True'})
        # Test when 'zfssa_manage_policy' is set to 'strict'.
        lcfg.zfssa_manage_policy = 'strict'
        test_vol.update({'cinder_managed': 'False'})
        self.drv.zfssa.get_volume.return_value = test_vol
        self.assertEqual({'provider_location': self.drv.mount_path},
                         self.drv.manage_existing({'name': 'volume-123'},
                                                  {'source-name':
                                                      'volume-567'}))

    def test_volume_manage_negative_no_source_name(self):
        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.drv.manage_existing,
                          {'name': 'volume-123'},
                          {'source-id': 'volume-567'})

    def test_volume_manage_negative_backend_exception(self):
        self.drv.zfssa.get_volume.side_effect = \
            exception.VolumeNotFound(volume_id='volume-567')
        self.assertRaises(exception.InvalidInput,
                          self.drv.manage_existing,
                          {'name': 'volume-123'},
                          {'source-name': 'volume-567'})

    def test_volume_manage_negative_verify_fail(self):
        lcfg = self.configuration
        lcfg.zfssa_manage_policy = 'strict'
        test_vol = self.test_vol
        test_vol['cinder_managed'] = ''

        self.drv.zfssa.get_volume.return_value = test_vol
        self.assertRaises(exception.InvalidInput,
                          self.drv.manage_existing,
                          {'name': 'volume-123'},
                          {'source-name': 'volume-567'})

        test_vol.update({'cinder_managed': 'True'})
        self.drv.zfssa.get_volume.return_value = test_vol
        self.assertRaises(exception.ManageExistingAlreadyManaged,
                          self.drv.manage_existing,
                          {'name': 'volume-123'},
                          {'source-name': 'volume-567'})

    @mock.patch.object(zfssanfs.ZFSSANFSDriver, '_verify_volume_to_manage')
    def test_volume_manage_negative_rename_fail(self,
                                                _verify_volume_to_manage):
        test_vol = self.test_vol
        test_vol.update({'cinder_managed': 'False'})
        self.drv.zfssa.get_volume.return_value = test_vol
        self.drv._verify_volume_to_manage.return_value = None
        self.drv.zfssa.rename_volume.side_effect = \
            exception.VolumeBackendAPIException(data="fake exception")
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.manage_existing, {'name': 'volume-123'},
                          {'source-name': 'volume-567'})

    @mock.patch.object(zfssanfs.ZFSSANFSDriver, '_verify_volume_to_manage')
    def test_volume_manage_negative_set_prop_fail(self,
                                                  _verify_volume_to_manage):
        test_vol = self.test_vol
        test_vol.update({'cinder_managed': 'False'})
        self.drv.zfssa.get_volume.return_value = test_vol
        self.drv._verify_volume_to_manage.return_value = None
        self.drv.zfssa.rename_volume.return_value = None
        self.drv.zfssa.set_file_props.side_effect = \
            exception.VolumeBackendAPIException(data="fake exception")
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.manage_existing, {'name': 'volume-123'},
                          {'source-name': 'volume-567'})

    def test_volume_unmanage(self):
        test_vol = self.test_vol
        test_vol.update({'cinder_managed': 'True'})
        self.drv.zfssa.rename_volume.return_value = None
        self.drv.zfssa.set_file_props.return_value = None
        self.assertIsNone(self.drv.unmanage(test_vol))
        new_vol_name = 'unmanaged-' + test_vol['name']
        self.drv.zfssa.rename_volume.assert_called_once_with(test_vol['name'],
                                                             new_vol_name)
        self.drv.zfssa.set_file_props.assert_called_once_with(
            new_vol_name, {'cinder_managed': 'False'})

    def test_volume_unmanage_negative_rename_fail(self):
        test_vol = self.test_vol
        test_vol.update({'cinder_managed': 'True'})
        self.drv.zfssa.rename_volume.side_effect = \
            exception.VolumeBackendAPIException(data="fake exception")
        self.drv.zfssa.set_file_props.return_value = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.unmanage, test_vol)

    def test_volume_unmanage_negative_set_prop_fail(self):
        test_vol = self.test_vol
        test_vol.update({'cinder_managed': 'True'})
        self.drv.zfssa.rename_volume.return_value = None
        self.drv.zfssa.set_file_props.side_effect = \
            exception.VolumeBackendAPIException(data="fake exception")
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.drv.unmanage, test_vol)

    @mock.patch.object(zfssanfs.ZFSSANFSDriver, '_get_mount_point_for_share')
    def test_manage_existing_get_size(self, _get_mount_point_for_share):
        self.drv._get_mount_point_for_share.return_value = \
            '/fake/mnt/fake_share/'
        self.drv._mounted_shares = []
        self.drv._mounted_shares.append('fake_share')
        file = mock.Mock(st_size=123 * units.Gi)
        with mock.patch('os.path.isfile', return_value=True):
            with mock.patch('os.stat', return_value=file):
                self.assertEqual(float(file.st_size / units.Gi),
                                 self.drv.manage_existing_get_size(
                                     {'name': 'volume-123'},
                                     {'source-name': 'volume-567'}))

    @mock.patch.object(zfssanfs.ZFSSANFSDriver, '_get_mount_point_for_share')
    def test_manage_existing_get_size_negative(self,
                                               _get_mount_point_for_share):
        self.drv._get_mount_point_for_share.return_value = \
            '/fake/mnt/fake_share/'
        self.drv._mounted_shares = []
        self.drv._mounted_shares.append('fake_share')
        with mock.patch('os.path.isfile', return_value=True):
            with mock.patch('os.stat', side_effect=OSError):
                self.assertRaises(exception.VolumeBackendAPIException,
                                  self.drv.manage_existing_get_size,
                                  {'name': 'volume-123'},
                                  {'source-name': 'volume-567'})


class TestZFSSAApi(test.TestCase):
    def setUp(self):
        super(TestZFSSAApi, self).setUp()
        self.host = 'fakehost'
        self.user = 'fakeuser'
        self.url = None
        self.pool = 'fakepool'
        self.project = 'fakeproject'
        self.vol = 'fakevol'
        self.snap = 'fakesnapshot'
        self.clone = 'fakeclone'
        self.targetalias = 'fakealias'
        self.mock_object(rest, 'factory_restclient', spec=rest.ZFSSAApi)
        self.zfssa = rest.ZFSSAApi()
        self.zfssa.set_host('fakehost')
        self.pool_url = '/api/storage/v1/pools/'

    def _create_response(self, status, data='data'):
        response = FakeResponse(status, data)
        return response

    def test_create_project(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        self.zfssa.create_project(self.pool, self.project)
        expected_svc = self.pool_url + self.pool + '/projects/' + self.project
        self.zfssa.rclient.get.assert_called_with(expected_svc)

    def test_create_initiator(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        initiator = 'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd'
        alias = 'init-group'
        self.zfssa.create_initiator(initiator, alias)
        self.zfssa.rclient.get.assert_called_with(
            '/api/san/v1/iscsi/initiators/alias=' + alias)

    def test_create_target(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.NOT_FOUND)
        ret_val = json.dumps(
            {'target': {'iqn':
                        'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd'}})
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.CREATED, ret_val)
        alias = 'tgt-group'
        self.zfssa.create_target(alias)
        self.zfssa.rclient.post.assert_called_with('/api/san/v1/iscsi/targets',
                                                   {'alias': alias})

    def test_get_target(self):
        ret_val = json.dumps(
            {'target': {'href': 'fake_href',
                        'alias': 'tgt-group',
                        'iqn':
                        'iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd',
                        'targetchapuser': '',
                        'targetchapsecret': '',
                        'interfaces': ['nge0']}})
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK, ret_val)
        ret = self.zfssa.get_target('tgt-group')
        self.zfssa.rclient.get.assert_called_once_with(
            '/api/san/v1/iscsi/targets/alias=tgt-group')
        self.assertEqual('iqn.1986-03.com.sun:02:00000-aaaa-bbbb-cccc-ddddd',
                         ret)

    def test_verify_pool(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        self.zfssa.verify_pool(self.pool)
        self.zfssa.rclient.get.assert_called_with(self.pool_url + self.pool)

    def test_verify_project(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.NOT_FOUND)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.zfssa.verify_project,
                          self.pool,
                          self.project)

    def test_verify_initiator(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        self.zfssa.verify_initiator('iqn.1-0.org.deb:01:d7')
        self.zfssa.rclient.get.assert_called_with(
            '/api/san/v1/iscsi/initiators/iqn.1-0.org.deb:01:d7')

    def test_verify_target(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.BAD_REQUEST)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.zfssa.verify_target,
                          self.targetalias)

    def test_create_delete_lun(self):
        arg = json.dumps({'name': self.vol,
                          'initiatorgroup': 'com.sun.ms.vss.hg.maskAll'})
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.CREATED, data=arg)
        self.zfssa.create_lun(self.pool, self.project, self.vol, 1, 'tgt-grp',
                              None)
        expected_arg = {'name': self.vol,
                        'volsize': 1,
                        'targetgroup': 'tgt-grp',
                        'initiatorgroup': 'com.sun.ms.vss.hg.maskAll'}
        self.zfssa.rclient.post.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project + '/luns',
            expected_arg)

        self.zfssa.rclient.delete.return_value = self._create_response(
            client.Status.NO_CONTENT)
        self.zfssa.delete_lun(self.pool, self.project, self.vol)
        self.zfssa.rclient.delete.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/luns/' + self.vol)

    def test_create_delete_snapshot(self):
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.CREATED)
        self.zfssa.create_snapshot(self.pool,
                                   self.project,
                                   self.vol,
                                   self.snap)
        expected_arg = {'name': self.snap}
        self.zfssa.rclient.post.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/luns/' + self.vol + '/snapshots', expected_arg)

        self.zfssa.rclient.delete.return_value = self._create_response(
            client.Status.NO_CONTENT)
        self.zfssa.delete_snapshot(self.pool,
                                   self.project,
                                   self.vol,
                                   self.snap)
        self.zfssa.rclient.delete.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/luns/' + self.vol + '/snapshots/' + self.snap)

    def test_clone_snapshot(self):
        self.zfssa.rclient.put.return_value = self._create_response(
            client.Status.CREATED)
        self.zfssa.clone_snapshot(self.pool,
                                  self.project,
                                  self.vol,
                                  self.snap,
                                  self.project,
                                  self.clone,
                                  None)
        expected_svc = '/api/storage/v1/pools/' + self.pool + '/projects/' + \
            self.project + '/luns/' + self.vol + '/snapshots/' + self.snap + \
            '/clone'
        expected_arg = {'project': self.project,
                        'share': self.clone,
                        'nodestroy': True}
        self.zfssa.rclient.put.assert_called_with(expected_svc, expected_arg)

    def test_get_project_stats(self):
        ret_val = json.dumps({"project": {"name": self.project,
                                          "space_available": 15754895360,
                                          "space_total": 25754895360,
                                          "dedup": False,
                                          "logbias": "latency",
                                          "encryption": "off"}})
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK, ret_val)
        self.zfssa.get_project_stats(self.pool, self.project)
        expected_svc = '/api/storage/v1/pools/' + self.pool + '/projects/' + \
            self.project
        self.zfssa.rclient.get.assert_called_with(expected_svc)

        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.NOT_FOUND)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.zfssa.get_project_stats,
                          self.pool,
                          self.project)

    def test_get_pool_stats_not_owned(self):
        # Case where the pool is owned by the cluster peer when cluster
        # is active. In this case, we should fail, because the driver is
        # configured to talk to the wrong control head.
        pool_data = {'pool': {'asn': 'fake-asn-b',
                     'owner': 'fakepeer'}}
        version_data = {'version': {'asn': 'fake-asn-a',
                        'nodename': 'fakehost'}}
        cluster_data = {'cluster': {'peer_hostname': 'fakepeer',
                                    'peer_asn': 'fake-asn-b',
                                    'peer_state': 'AKCS_CLUSTERED'}}
        self.zfssa.rclient.get.side_effect = [
            self._create_response(client.Status.OK,
                                  json.dumps(pool_data)),
            self._create_response(client.Status.OK,
                                  json.dumps(version_data)),
            self._create_response(client.Status.OK,
                                  json.dumps(cluster_data))]
        self.assertRaises(exception.InvalidInput,
                          self.zfssa.get_pool_details,
                          self.pool)

    def test_get_pool_stats_stripped(self):
        # Case where the pool is owned by the cluster peer when it is in a
        # stripped state. In this case, so long as the owner and ASN for the
        # pool match the peer, we should not fail.
        pool_data = {'pool': {'asn': 'fake-asn-a',
                     'owner': 'fakehost'}}
        version_data = {'version': {'asn': 'fake-asn-b',
                        'nodename': 'fakepeer'}}
        cluster_data = {'cluster': {'peer_hostname': 'fakehost',
                                    'peer_asn': 'fake-asn-a',
                                    'peer_state': 'AKCS_STRIPPED'}}
        self.zfssa.rclient.get.side_effect = [
            self._create_response(client.Status.OK,
                                  json.dumps(pool_data)),
            self._create_response(client.Status.OK,
                                  json.dumps(version_data)),
            self._create_response(client.Status.OK,
                                  json.dumps(cluster_data))]
        self.zfssa.get_pool_details(self.pool)


class TestZFSSANfsApi(test.TestCase):
    def setUp(self):
        super(TestZFSSANfsApi, self).setUp()
        self.host = 'fakehost'
        self.user = 'fakeuser'
        self.url = None
        self.pool = 'fakepool'
        self.project = 'fakeproject'
        self.share = 'fakeshare'
        self.snap = 'fakesnapshot'
        self.targetalias = 'fakealias'
        self.mock_object(rest, 'factory_restclient', spec=rest.ZFSSAApi)
        self.webdavclient = mock.MagicMock(spec=webdavclient.ZFSSAWebDAVClient)
        self.zfssa = rest.ZFSSANfsApi()
        self.zfssa.set_host('fakehost')
        self.pool_url = '/api/storage/v1/pools/'

    def _create_response(self, status, data='data'):
        response = FakeResponse(status, data)
        return response

    def test_verify_share(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK)
        self.zfssa.verify_share(self.pool, self.project, self.share)
        self.zfssa.rclient.get.assert_called_with(self.pool_url + self.pool +
                                                  '/projects/' + self.project +
                                                  '/filesystems/' + self.share)

    def test_create_delete_snapshot(self):
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.CREATED)
        self.zfssa.create_snapshot(self.pool,
                                   self.project,
                                   self.share,
                                   self.snap)
        expected_arg = {'name': self.snap}
        self.zfssa.rclient.post.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/filesystems/' + self.share + '/snapshots', expected_arg)

        self.zfssa.rclient.delete.return_value = self._create_response(
            client.Status.NO_CONTENT)
        self.zfssa.delete_snapshot(self.pool,
                                   self.project,
                                   self.share,
                                   self.snap)
        self.zfssa.rclient.delete.assert_called_with(
            self.pool_url + self.pool + '/projects/' + self.project +
            '/filesystems/' + self.share + '/snapshots/' + self.snap)

    def create_delete_snapshot_of_volume_file(self):
        src_file = "fake_src_file"
        dst_file = "fake_dst_file"
        self.zfssa.create_snapshot_of_volume_file(src_file=src_file,
                                                  dst_file=dst_file)
        self.zfssa.webdavclient.request.assert_called_once_with(
            src_file=src_file,
            dst_file=dst_file,
            method='COPY')
        self.zfssa.delete_snapshot_of_volume_file(src_file=src_file)
        self.zfssa.webdavclient.request.assert_called_once_with(
            src_file=src_file, method='DELETE')

    def test_get_share(self):
        ret_val = json.dumps({'filesystem': 'test_fs'})
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.OK, ret_val)
        ret = self.zfssa.get_share(self.pool, self.project, self.share)
        self.zfssa.rclient.get.assert_called_with(self.pool_url + self.pool +
                                                  '/projects/' + self.project +
                                                  '/filesystems/' + self.share)
        self.assertEqual('test_fs', ret)

    def test_create_share(self):
        self.zfssa.rclient.get.return_value = self._create_response(
            client.Status.NOT_FOUND)
        self.zfssa.rclient.post.return_value = self._create_response(
            client.Status.BAD_REQUEST)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.zfssa.create_share,
                          self.pool,
                          self.project,
                          self.share,
                          {})

    @mock.patch.object(rest.ZFSSANfsApi, '_change_service_state')
    @mock.patch.object(rest.ZFSSANfsApi, 'verify_service')
    def test_enable_disable_modify_service(self,
                                           verify_service,
                                           _change_service_state):
        self.zfssa.enable_service('http')
        self.zfssa._change_service_state.assert_called_with(
            'http', state='enable')
        self.zfssa.verify_service.assert_called_with('http')

        self.zfssa.disable_service('http')
        self.zfssa._change_service_state.assert_called_with(
            'http', state='disable')
        self.zfssa.verify_service.assert_called_with('http', status='offline')

        ret_val = json.dumps({'service': {
            "href": "/api/service/v1/services/http",
            "<status>": "online",
            "require_login": False,
            "protocols": "http/https",
            "listen_port": 81,
            "https_port": 443}})
        self.zfssa.rclient.put.return_value = self._create_response(
            client.Status.ACCEPTED, ret_val)
        args = {'listen_port': 81}
        self.zfssa.modify_service('http', args)
        self.zfssa.rclient.put.called_with('/api/service/v1/services/http',
                                           args)


class TestRestClientURL(test.TestCase):
    def setUp(self):
        super(TestRestClientURL, self).setUp()
        self.timeout = 60
        self.url = '1.1.1.1'
        self.client = client.RestClientURL(self.url, timeout=self.timeout)

    @mock.patch.object(client.RestClientURL, 'request')
    def test_post(self, _request):
        path = '/api/storage/v1/pools'
        body = {'name': 'fakepool'}
        self.client.post(path, body=body)
        self.client.request.assert_called_with(path, 'POST', body)

    @mock.patch.object(client.RestClientURL, 'request')
    def test_get(self, _request):
        path = '/api/storage/v1/pools'
        self.client.get(path)
        self.client.request.assert_called_with(path, 'GET')

    @mock.patch.object(client.RestClientURL, 'request')
    def test_put(self, _request):
        path = '/api/storage/v1/pools'
        body = {'name': 'fakepool'}
        self.client.put(path, body=body)
        self.client.request.assert_called_with(path, 'PUT', body)

    @mock.patch.object(client.RestClientURL, 'request')
    def test_delete(self, _request):
        path = '/api/storage/v1/pools'
        self.client.delete(path)
        self.client.request.assert_called_with(path, 'DELETE')

    @mock.patch.object(client.RestClientURL, 'request')
    def test_head(self, _request):
        path = '/api/storage/v1/pools'
        self.client.head(path)
        self.client.request.assert_called_with(path, 'HEAD')

    @mock.patch.object(client, 'RestResult')
    @mock.patch.object(client.urllib.request, 'Request')
    @mock.patch.object(client.urllib.request, 'urlopen')
    def test_request(self, _urlopen, _Request, _RestResult):
        path = '/api/storage/v1/pools'
        _urlopen.return_value = mock.Mock()
        self.client.request(path, mock.ANY)
        _Request.assert_called_with(self.url + path, None, self.client.headers)
        self.assertEqual(1, _urlopen.call_count)
        _RestResult.assert_called_with(response=mock.ANY)

    @mock.patch.object(client, 'RestResult')
    @mock.patch.object(client.urllib.request, 'Request')
    @mock.patch.object(client.urllib.request, 'urlopen')
    @mock.patch.object(client, 'ssl', new_callable=FakeSSL)
    def test_ssl_with_context(self, _ssl, _urlopen, _Request, _RestResult):
        """Test PEP476 certificate opt_out fix. """
        path = '/api/storage/v1/pools'
        _urlopen.return_value = mock.Mock()
        self.client.request(path, mock.ANY)
        _urlopen.assert_called_once_with(mock.ANY,
                                         timeout=self.timeout,
                                         context='fakecontext')

    @mock.patch.object(client, 'RestResult')
    @mock.patch.object(client.urllib.request, 'Request')
    @mock.patch.object(client.urllib.request, 'urlopen')
    @mock.patch.object(client, 'ssl', new_callable=object)
    def test_ssl_no_context(self, _ssl, _urlopen, _Request, _RestResult):
        """Verify the PEP476 fix backward compatibility. """
        path = '/api/storage/v1/pools'
        _urlopen.return_value = mock.Mock()
        self.client.request(path, mock.ANY)
        _urlopen.assert_called_once_with(mock.ANY, timeout=self.timeout)
