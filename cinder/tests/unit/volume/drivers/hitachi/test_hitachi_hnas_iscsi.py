# Copyright (c) 2014 Hitachi Data Systems, Inc.
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
#

import mock

from oslo_concurrency import processutils as putils

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.volume import configuration as conf
from cinder.volume.drivers.hitachi.hnas_backend import HNASSSHBackend
from cinder.volume.drivers.hitachi import hnas_iscsi as iscsi
from cinder.volume.drivers.hitachi import hnas_utils
from cinder.volume import volume_types


# The following information is passed on to tests, when creating a volume
_VOLUME = {'name': 'volume-cinder',
           'id': fake.VOLUME_ID,
           'size': 128,
           'host': 'host1@hnas-iscsi-backend#default',
           'provider_location': '83-68-96-AA-DA-5D.volume-2dfe280e-470a-'
                                '4182-afb8-1755025c35b8'}

_VOLUME2 = {'name': 'volume-clone',
            'id': fake.VOLUME2_ID,
            'size': 150,
            'host': 'host1@hnas-iscsi-backend#default',
            'provider_location': '83-68-96-AA-DA-5D.volume-8fe1802a-316b-'
                                 '5237-1c57-c35b81755025'}

_SNAPSHOT = {
    'name': 'snapshot-51dd4-8d8a-4aa9-9176-086c9d89e7fc',
    'id': fake.SNAPSHOT_ID,
    'size': 128,
    'volume_type': None,
    'provider_location': None,
    'volume_size': 128,
    'volume': _VOLUME,
    'volume_name': _VOLUME['name'],
    'host': 'host1@hnas-iscsi-backend#silver',
    'volume_type_id': fake.VOLUME_TYPE_ID,
}


class HNASiSCSIDriverTest(test.TestCase):
    """Test HNAS iSCSI volume driver."""
    def setUp(self):
        super(HNASiSCSIDriverTest, self).setUp()
        self.context = context.get_admin_context()
        self.volume = fake_volume.fake_volume_obj(
            self.context, **_VOLUME)
        self.volume_clone = fake_volume.fake_volume_obj(
            self.context, **_VOLUME2)
        self.snapshot = self.instantiate_snapshot(_SNAPSHOT)

        self.volume_type = fake_volume.fake_volume_type_obj(
            None,
            **{'name': 'silver'}
        )

        self.parsed_xml = {
            'username': 'supervisor',
            'password': 'supervisor',
            'hnas_cmd': 'ssc',
            'fs': {'fs2': 'fs2'},
            'ssh_port': '22',
            'port': '3260',
            'services': {
                'default': {
                    'hdp': 'fs2',
                    'iscsi_ip': '172.17.39.132',
                    'iscsi_port': '3260',
                    'port': '22',
                    'volume_type': 'default',
                    'label': 'svc_0',
                    'evs': '1',
                    'tgt': {
                        'alias': 'test',
                        'secret': 'itEpgB5gPefGhW2'
                    }
                },
                'silver': {
                    'hdp': 'fs3',
                    'iscsi_ip': '172.17.39.133',
                    'iscsi_port': '3260',
                    'port': '22',
                    'volume_type': 'silver',
                    'label': 'svc_1',
                    'evs': '2',
                    'tgt': {
                        'alias': 'iscsi-test',
                        'secret': 'itEpgB5gPefGhW2'
                    }
                }
            },
            'cluster_admin_ip0': None,
            'ssh_private_key': None,
            'chap_enabled': True,
            'mgmt_ip0': '172.17.44.15',
            'ssh_enabled': None
        }

        self.configuration = mock.Mock(spec=conf.Configuration)
        self.configuration.hds_hnas_iscsi_config_file = 'fake.xml'

        self.mock_object(hnas_utils, 'read_cinder_conf',
                         mock.Mock(return_value=self.parsed_xml))

        self.driver = iscsi.HNASISCSIDriver(configuration=self.configuration)

    @staticmethod
    def instantiate_snapshot(snap):
        snap = snap.copy()
        snap['volume'] = fake_volume.fake_volume_obj(
            None, **snap['volume'])
        snapshot = fake_snapshot.fake_snapshot_obj(
            None, expected_attrs=['volume'], **snap)
        return snapshot

    def test_get_service_target_chap_enabled(self):
        lu_info = {'mapped': False,
                   'id': 1,
                   'tgt': {'alias': 'iscsi-test',
                           'secret': 'itEpgB5gPefGhW2'}}
        tgt = {'found': True,
               'tgt': {
                   'alias': 'cinder-default',
                   'secret': 'pxr6U37LZZJBoMc',
                   'iqn': 'iqn.2014-12.10.10.10.10:evstest1.cinder-default',
                   'lus': [
                       {'id': '0',
                        'name': 'cinder-lu'},
                       {'id': '1',
                        'name': 'volume-99da7ae7-1e7f-4d57-8bf...'}
                   ],
                   'auth': 'Enabled'}}
        iqn = 'iqn.2014-12.10.10.10.10:evstest1.cinder-default'

        self.mock_object(HNASSSHBackend, 'get_evs',
                         mock.Mock(return_value='1'))
        self.mock_object(HNASSSHBackend, 'check_lu',
                         mock.Mock(return_value=lu_info))
        self.mock_object(HNASSSHBackend, 'check_target',
                         mock.Mock(return_value=tgt))
        self.mock_object(HNASSSHBackend, 'get_target_secret',
                         mock.Mock(return_value=''))
        self.mock_object(HNASSSHBackend, 'set_target_secret')
        self.mock_object(HNASSSHBackend, 'get_target_iqn',
                         mock.Mock(return_value=iqn))

        self.driver._get_service_target(self.volume)

    def test_get_service_target_chap_disabled(self):
        lu_info = {'mapped': False,
                   'id': 1,
                   'tgt': {'alias': 'iscsi-test',
                           'secret': 'itEpgB5gPefGhW2'}}
        tgt = {'found': False,
               'tgt': {
                   'alias': 'cinder-default',
                   'secret': 'pxr6U37LZZJBoMc',
                   'iqn': 'iqn.2014-12.10.10.10.10:evstest1.cinder-default',
                   'lus': [
                       {'id': '0',
                        'name': 'cinder-lu'},
                       {'id': '1',
                        'name': 'volume-99da7ae7-1e7f-4d57-8bf...'}
                   ],
                   'auth': 'Enabled'}}
        iqn = 'iqn.2014-12.10.10.10.10:evstest1.cinder-default'

        self.driver.config['chap_enabled'] = False

        self.mock_object(HNASSSHBackend, 'get_evs',
                         mock.Mock(return_value='1'))
        self.mock_object(HNASSSHBackend, 'check_lu',
                         mock.Mock(return_value=lu_info))
        self.mock_object(HNASSSHBackend, 'check_target',
                         mock.Mock(return_value=tgt))
        self.mock_object(HNASSSHBackend, 'get_target_iqn',
                         mock.Mock(return_value=iqn))
        self.mock_object(HNASSSHBackend, 'create_target')

        self.driver._get_service_target(self.volume)

    def test_get_service_target_no_more_targets_exception(self):
        iscsi.MAX_HNAS_LUS_PER_TARGET = 4
        lu_info = {'mapped': False, 'id': 1,
                   'tgt': {'alias': 'iscsi-test', 'secret': 'itEpgB5gPefGhW2'}}
        tgt = {'found': True,
               'tgt': {
                   'alias': 'cinder-default', 'secret': 'pxr6U37LZZJBoMc',
                   'iqn': 'iqn.2014-12.10.10.10.10:evstest1.cinder-default',
                   'lus': [
                       {'id': '0', 'name': 'volume-0'},
                       {'id': '1', 'name': 'volume-1'},
                       {'id': '2', 'name': 'volume-2'},
                       {'id': '3', 'name': 'volume-3'}, ],
                   'auth': 'Enabled'}}

        self.mock_object(HNASSSHBackend, 'get_evs',
                         mock.Mock(return_value='1'))
        self.mock_object(HNASSSHBackend, 'check_lu',
                         mock.Mock(return_value=lu_info))
        self.mock_object(HNASSSHBackend, 'check_target',
                         mock.Mock(return_value=tgt))

        self.assertRaises(exception.NoMoreTargets,
                          self.driver._get_service_target, self.volume)

    def test_check_pool_and_fs(self):
        self.mock_object(hnas_utils, 'get_pool',
                         mock.Mock(return_value='default'))
        self.driver._check_pool_and_fs(self.volume, 'fs2')

    def test_check_pool_and_fs_mismatch(self):
        self.mock_object(hnas_utils, 'get_pool',
                         mock.Mock(return_value='default'))

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver._check_pool_and_fs, self.volume,
                          'fs-cinder')

    def test_check_pool_and_fs_host_mismatch(self):
        self.mock_object(hnas_utils, 'get_pool',
                         mock.Mock(return_value='silver'))

        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver._check_pool_and_fs, self.volume,
                          'fs3')

    def test_do_setup(self):
        evs_info = {'172.17.39.132': {'evs_number': 1},
                    '172.17.39.133': {'evs_number': 2},
                    '172.17.39.134': {'evs_number': 3}}

        version_info = {
            'mac': '83-68-96-AA-DA-5D',
            'model': 'HNAS 4040',
            'version': '12.4.3924.11',
            'hardware': 'NAS Platform',
            'serial': 'B1339109',
        }

        self.mock_object(HNASSSHBackend, 'get_fs_info',
                         mock.Mock(return_value=True))
        self.mock_object(HNASSSHBackend, 'get_evs_info',
                         mock.Mock(return_value=evs_info))
        self.mock_object(HNASSSHBackend, 'get_version',
                         mock.Mock(return_value=version_info))

        self.driver.do_setup(None)

        HNASSSHBackend.get_fs_info.assert_called_with('fs2')
        self.assertTrue(HNASSSHBackend.get_evs_info.called)

    def test_do_setup_portal_not_found(self):
        evs_info = {'172.17.48.132': {'evs_number': 1},
                    '172.17.39.133': {'evs_number': 2},
                    '172.17.39.134': {'evs_number': 3}}

        version_info = {
            'mac': '83-68-96-AA-DA-5D',
            'model': 'HNAS 4040',
            'version': '12.4.3924.11',
            'hardware': 'NAS Platform',
            'serial': 'B1339109',
        }

        self.mock_object(HNASSSHBackend, 'get_fs_info',
                         mock.Mock(return_value=True))
        self.mock_object(HNASSSHBackend, 'get_evs_info',
                         mock.Mock(return_value=evs_info))
        self.mock_object(HNASSSHBackend, 'get_version',
                         mock.Mock(return_value=version_info))

        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.do_setup, None)

    def test_do_setup_umounted_filesystem(self):
        self.mock_object(HNASSSHBackend, 'get_fs_info',
                         mock.Mock(return_value=False))

        self.assertRaises(exception.ParameterNotFound, self.driver.do_setup,
                          None)

    def test_initialize_connection(self):
        lu_info = {'mapped': True,
                   'id': 1,
                   'tgt': {'alias': 'iscsi-test',
                           'secret': 'itEpgB5gPefGhW2'}}

        conn = {'lun_name': 'cinder-lu',
                'initiator': 'initiator',
                'hdp': 'fs-cinder',
                'lu_id': '0',
                'iqn': 'iqn.2014-12.10.10.10.10:evstest1.cinder-default',
                'port': 3260}

        connector = {'initiator': 'fake_initiator'}

        self.mock_object(HNASSSHBackend, 'get_evs',
                         mock.Mock(return_value=2))
        self.mock_object(HNASSSHBackend, 'check_lu',
                         mock.Mock(return_value=lu_info))
        self.mock_object(HNASSSHBackend, 'add_iscsi_conn',
                         mock.Mock(return_value=conn))

        self.driver.initialize_connection(self.volume, connector)

        HNASSSHBackend.add_iscsi_conn.assert_called_with(self.volume.name,
                                                         'fs2', '22',
                                                         'iscsi-test',
                                                         connector[
                                                             'initiator'])

    def test_initialize_connection_command_error(self):
        lu_info = {'mapped': True,
                   'id': 1,
                   'tgt': {'alias': 'iscsi-test',
                           'secret': 'itEpgB5gPefGhW2'}}

        connector = {'initiator': 'fake_initiator'}

        self.mock_object(HNASSSHBackend, 'get_evs',
                         mock.Mock(return_value=2))
        self.mock_object(HNASSSHBackend, 'check_lu',
                         mock.Mock(return_value=lu_info))
        self.mock_object(HNASSSHBackend, 'add_iscsi_conn',
                         mock.Mock(side_effect=putils.ProcessExecutionError))

        self.assertRaises(exception.ISCSITargetAttachFailed,
                          self.driver.initialize_connection, self.volume,
                          connector)

    def test_terminate_connection(self):
        connector = {}
        lu_info = {'mapped': True,
                   'id': 1,
                   'tgt': {'alias': 'iscsi-test',
                           'secret': 'itEpgB5gPefGhW2'}}

        self.mock_object(HNASSSHBackend, 'get_evs',
                         mock.Mock(return_value=2))
        self.mock_object(HNASSSHBackend, 'check_lu',
                         mock.Mock(return_value=lu_info))
        self.mock_object(HNASSSHBackend, 'del_iscsi_conn')

        self.driver.terminate_connection(self.volume, connector)

        HNASSSHBackend.del_iscsi_conn.assert_called_with('1',
                                                         'iscsi-test',
                                                         lu_info['id'])

    def test_get_volume_stats(self):
        self.driver.pools = [{'pool_name': 'default',
                              'service_label': 'svc_0',
                              'fs': '172.17.39.132:/fs2'},
                             {'pool_name': 'silver',
                              'service_label': 'svc_1',
                              'fs': '172.17.39.133:/fs3'}]

        fs_cinder = {
            'evs_id': '2',
            'total_size': '250',
            'label': 'fs-cinder',
            'available_size': '228',
            'used_size': '21.4',
            'id': '1025',
            'provisioned_capacity': 0.0
        }

        self.mock_object(HNASSSHBackend, 'get_fs_info',
                         mock.Mock(return_value=fs_cinder))

        stats = self.driver.get_volume_stats(refresh=True)

        self.assertEqual('5.0.0', stats['driver_version'])
        self.assertEqual('Hitachi', stats['vendor_name'])
        self.assertEqual('iSCSI', stats['storage_protocol'])

    def test_create_volume(self):
        version_info = {'mac': '83-68-96-AA-DA-5D'}
        expected_out = {
            'provider_location': version_info['mac'] + '.' + self.volume.name
        }

        self.mock_object(HNASSSHBackend, 'create_lu')
        self.mock_object(HNASSSHBackend, 'get_version',
                         mock.Mock(return_value=version_info))
        out = self.driver.create_volume(self.volume)

        self.assertEqual(expected_out, out)
        HNASSSHBackend.create_lu.assert_called_with('fs2', u'128',
                                                    self.volume.name)

    def test_create_volume_missing_fs(self):
        self.volume.host = 'host1@hnas-iscsi-backend#missing'

        self.assertRaises(exception.ParameterNotFound,
                          self.driver.create_volume, self.volume)

    def test_delete_volume(self):
        self.mock_object(HNASSSHBackend, 'delete_lu')

        self.driver.delete_volume(self.volume)

        HNASSSHBackend.delete_lu.assert_called_once_with(
            self.parsed_xml['fs']['fs2'], self.volume.name)

    def test_extend_volume(self):
        new_size = 200
        self.mock_object(HNASSSHBackend, 'extend_lu')

        self.driver.extend_volume(self.volume, new_size)

        HNASSSHBackend.extend_lu.assert_called_once_with(
            self.parsed_xml['fs']['fs2'], new_size,
            self.volume.name)

    def test_create_cloned_volume(self):
        clone_name = self.volume_clone.name
        version_info = {'mac': '83-68-96-AA-DA-5D'}
        expected_out = {
            'provider_location':
                version_info['mac'] + '.' + self.volume_clone.name
        }

        self.mock_object(HNASSSHBackend, 'create_cloned_lu')
        self.mock_object(HNASSSHBackend, 'get_version',
                         mock.Mock(return_value=version_info))
        self.mock_object(HNASSSHBackend, 'extend_lu')

        out = self.driver.create_cloned_volume(self.volume_clone, self.volume)
        self.assertEqual(expected_out, out)
        HNASSSHBackend.create_cloned_lu.assert_called_with(self.volume.name,
                                                           'fs2',
                                                           clone_name)

    def test_functions_with_pass(self):
        self.driver.check_for_setup_error()
        self.driver.ensure_export(None, self.volume)
        self.driver.create_export(None, self.volume, 'connector')
        self.driver.remove_export(None, self.volume)

    def test_create_snapshot(self):
        lu_info = {'lu_mounted': 'No',
                   'name': 'cinder-lu',
                   'fs_mounted': 'YES',
                   'filesystem': 'FS-Cinder',
                   'path': '/.cinder/cinder-lu.iscsi',
                   'size': 2.0}
        version_info = {'mac': '83-68-96-AA-DA-5D'}
        expected_out = {
            'provider_location': version_info['mac'] + '.' + self.snapshot.name
        }

        self.mock_object(HNASSSHBackend, 'get_existing_lu_info',
                         mock.Mock(return_value=lu_info))
        self.mock_object(volume_types, 'get_volume_type',
                         mock.Mock(return_value=self.volume_type))
        self.mock_object(HNASSSHBackend, 'create_cloned_lu')
        self.mock_object(HNASSSHBackend, 'get_version',
                         mock.Mock(return_value=version_info))

        out = self.driver.create_snapshot(self.snapshot)
        self.assertEqual(expected_out, out)

    def test_delete_snapshot(self):
        lu_info = {'filesystem': 'FS-Cinder'}

        self.mock_object(volume_types, 'get_volume_type',
                         mock.Mock(return_value=self.volume_type))
        self.mock_object(HNASSSHBackend, 'get_existing_lu_info',
                         mock.Mock(return_value=lu_info))
        self.mock_object(HNASSSHBackend, 'delete_lu')

        self.driver.delete_snapshot(self.snapshot)

    def test_create_volume_from_snapshot(self):
        version_info = {'mac': '83-68-96-AA-DA-5D'}
        expected_out = {
            'provider_location': version_info['mac'] + '.' + self.snapshot.name
        }

        self.mock_object(HNASSSHBackend, 'create_cloned_lu')
        self.mock_object(HNASSSHBackend, 'get_version',
                         mock.Mock(return_value=version_info))

        out = self.driver.create_volume_from_snapshot(self.volume,
                                                      self.snapshot)
        self.assertEqual(expected_out, out)
        HNASSSHBackend.create_cloned_lu.assert_called_with(self.snapshot.name,
                                                           'fs2',
                                                           self.volume.name)

    def test_manage_existing_get_size(self):
        existing_vol_ref = {'source-name': 'fs-cinder/volume-cinder'}
        lu_info = {
            'name': 'volume-cinder',
            'comment': None,
            'path': ' /.cinder/volume-cinder',
            'size': 128,
            'filesystem': 'fs-cinder',
            'fs_mounted': 'Yes',
            'lu_mounted': 'Yes'
        }

        self.mock_object(HNASSSHBackend, 'get_existing_lu_info',
                         mock.Mock(return_value=lu_info))

        out = self.driver.manage_existing_get_size(self.volume,
                                                   existing_vol_ref)

        self.assertEqual(lu_info['size'], out)
        HNASSSHBackend.get_existing_lu_info.assert_called_with(
            'volume-cinder', lu_info['filesystem'])

    def test_manage_existing_get_size_no_source_name(self):
        existing_vol_ref = {}

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self.volume,
                          existing_vol_ref)

    def test_manage_existing_get_size_wrong_source_name(self):
        existing_vol_ref = {'source-name': 'fs-cinder/volume/cinder'}

        self.mock_object(HNASSSHBackend, 'get_existing_lu_info',
                         mock.Mock(return_value={}))

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self.volume,
                          existing_vol_ref)

    def test_manage_existing_get_size_volume_not_found(self):
        existing_vol_ref = {'source-name': 'fs-cinder/volume-cinder'}

        self.mock_object(HNASSSHBackend, 'get_existing_lu_info',
                         mock.Mock(return_value={}))

        self.assertRaises(exception.ManageExistingInvalidReference,
                          self.driver.manage_existing_get_size, self.volume,
                          existing_vol_ref)

    def test_manage_existing(self):
        self.volume.volume_type = self.volume_type
        existing_vol_ref = {'source-name': 'fs2/volume-cinder'}
        metadata = {'service_label': 'default'}
        version_info = {'mac': '83-68-96-AA-DA-5D'}
        expected_out = {
            'provider_location': version_info['mac'] + '.' + self.volume.name
        }
        self.mock_object(HNASSSHBackend, 'rename_existing_lu')
        self.mock_object(volume_types, 'get_volume_type_extra_specs',
                         mock.Mock(return_value=metadata))
        self.mock_object(HNASSSHBackend, 'get_version',
                         mock.Mock(return_value=version_info))

        out = self.driver.manage_existing(self.volume, existing_vol_ref)

        self.assertEqual(expected_out, out)
        HNASSSHBackend.rename_existing_lu.assert_called_with('fs2',
                                                             'volume-cinder',
                                                             self.volume.name)

    def test_unmanage(self):
        self.mock_object(HNASSSHBackend, 'rename_existing_lu')

        self.driver.unmanage(self.volume)

        HNASSSHBackend.rename_existing_lu.assert_called_with(
            self.parsed_xml['fs']['fs2'],
            self.volume.name, 'unmanage-' + self.volume.name)
