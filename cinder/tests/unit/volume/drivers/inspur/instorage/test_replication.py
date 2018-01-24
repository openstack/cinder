# Copyright 2017 Inspur Corp.
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
"""
Tests for the Inspur InStorage volume driver.
"""

import json

from eventlet import greenthread
import mock
from oslo_utils import importutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as testutils
from cinder import utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.inspur.instorage import (
    replication as instorage_rep)
from cinder.volume.drivers.inspur.instorage import instorage_common
from cinder.volume.drivers.inspur.instorage import instorage_const
from cinder.volume import volume_types

from cinder.tests.unit.volume.drivers.inspur.instorage import fakes


class InStorageMCSReplicationTestCase(test.TestCase):

    def setUp(self):
        super(InStorageMCSReplicationTestCase, self).setUp()

        def _run_ssh_aux(cmd, check_exit_code=True, attempts=1):
            utils.check_ssh_injection(cmd)
            if len(cmd) > 2 and cmd[1] == 'lssystem':
                cmd[1] = 'lssystem_aux'
            ret = self.sim.execute_command(cmd, check_exit_code)
            return ret
        aux_connect_patcher = mock.patch(
            'cinder.volume.drivers.inspur.instorage.'
            'replication.InStorageMCSReplicationManager._run_ssh')
        self.aux_ssh_mock = aux_connect_patcher.start()
        self.addCleanup(aux_connect_patcher.stop)
        self.aux_ssh_mock.side_effect = _run_ssh_aux

        self.driver = fakes.FakeInStorageMCSISCSIDriver(
            configuration=conf.Configuration(None))
        self.rep_target = {"backend_id": "mcs_aux_target_1",
                           "san_ip": "192.168.10.22",
                           "san_login": "admin",
                           "san_password": "admin",
                           "pool_name": fakes.get_test_pool()}
        self.fake_target = {"backend_id": "mcs_id_target",
                            "san_ip": "192.168.10.23",
                            "san_login": "admin",
                            "san_password": "admin",
                            "pool_name": fakes.get_test_pool()}
        self._def_flags = {'san_ip': '192.168.10.21',
                           'san_login': 'user',
                           'san_password': 'pass',
                           'instorage_mcs_volpool_name': fakes.MCS_POOLS,
                           'replication_device': [self.rep_target]}
        wwpns = ['1234567890123451', '6543210987654326']
        initiator = 'test.initiator.%s' % 123451
        self._connector = {'ip': '1.234.56.78',
                           'host': 'instorage-mcs-test',
                           'wwpns': wwpns,
                           'initiator': initiator}
        self.sim = fakes.FakeInStorage(fakes.MCS_POOLS)

        self.driver.set_fake_storage(self.sim)
        self.ctxt = context.get_admin_context()

        self._reset_flags()
        self.ctxt = context.get_admin_context()
        db_driver = self.driver.configuration.db_driver
        self.db = importutils.import_module(db_driver)
        self.driver.db = self.db

        self.driver.do_setup(None)
        self.driver.check_for_setup_error()
        self._create_test_volume_types()

        self.mock_object(greenthread, 'sleep')

    def _set_flag(self, flag, value):
        group = self.driver.configuration.config_group
        self.driver.configuration.set_override(flag, value, group)

    def _reset_flags(self):
        self.driver.configuration.local_conf.reset()
        for k, v in self._def_flags.items():
            self._set_flag(k, v)
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])

    def _assert_vol_exists(self, name, exists):
        is_vol_defined = self.driver._assistant.is_vdisk_defined(name)
        self.assertEqual(exists, is_vol_defined)

    def _generate_vol_info(self, vol_name, vol_id, vol_type=None):
        pool = fakes.get_test_pool()
        volume_type = self.non_replica_type
        if vol_type:
            volume_type = vol_type
        if vol_name:
            prop = {'volume_name': vol_name,
                    'volume_id': vol_id,
                    'volume_size': 10,
                    'mdisk_grp_name': pool}
        else:
            prop = {'size': 10,
                    'mdisk_grp_name': pool,
                    'host': 'openstack@mcs#%s' % pool,
                    'volume_type_id': volume_type['id']}
        vol = testutils.create_volume(self.ctxt, **prop)
        return vol

    def _generate_snapshot_info(self, vol):
        snap = testutils.create_snapshot(self.ctxt, vol.id)
        return snap

    def _create_replica_volume_type(self, enable,
                                    rep_type=instorage_const.SYNC):
        # Generate a volume type for volume repliation.
        if enable:
            if rep_type == instorage_const.SYNC:
                spec = {'replication_enabled': '<is> True',
                        'replication_type': '<in> sync'}
                type_name = 'rep_sync'
            else:
                spec = {'replication_enabled': '<is> True',
                        'replication_type': '<in> async'}
                type_name = 'rep_async'
        else:
            spec = {'replication_enabled': '<is> False'}
            type_name = "non_rep"

        db_rep_type = testutils.create_volume_type(self.ctxt,
                                                   name=type_name,
                                                   extra_specs=spec)
        rep_type = volume_types.get_volume_type(self.ctxt, db_rep_type.id)

        return rep_type

    def _create_test_volume_types(self):
        self.mm_type = self._create_replica_volume_type(
            True, rep_type=instorage_const.SYNC)
        self.gm_type = self._create_replica_volume_type(
            True, rep_type=instorage_const.ASYNC)
        self.non_replica_type = self._create_replica_volume_type(False)

    def _create_test_volume(self, rep_type):
        volume = self._generate_vol_info(None, None, rep_type)
        model_update = self.driver.create_volume(volume)
        return volume, model_update

    def _get_vdisk_uid(self, vdisk_name):
        vdisk_properties, _err = self.sim._cmd_lsvdisk(obj=vdisk_name,
                                                       delim='!')
        for row in vdisk_properties.split('\n'):
            words = row.split('!')
            if words[0] == 'vdisk_UID':
                return words[1]
        return None

    def test_instorage_do_replication_setup_error(self):
        fake_targets = [self.rep_target, self.rep_target]
        self.driver.configuration.set_override('replication_device',
                                               [{"backend_id":
                                                 "mcs_id_target"}])
        self.assertRaises(exception.InvalidInput,
                          self.driver._do_replication_setup)

        self.driver.configuration.set_override('replication_device',
                                               fake_targets)
        self.assertRaises(exception.InvalidInput,
                          self.driver._do_replication_setup)

        self.driver._active_backend_id = 'fake_id'
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.assertRaises(exception.InvalidInput,
                          self.driver._do_replication_setup)

        self.driver._active_backend_id = None

        self.driver._do_replication_setup()
        self.assertEqual(self.rep_target, self.driver._replica_target)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'replication_licensed')
    def test_instorage_setup_replication(self,
                                         replication_licensed):
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver._active_backend_id = None
        replication_licensed.side_effect = [False, True, True, True]

        self.driver._get_instorage_config()
        self.assertEqual(self.driver._assistant,
                         self.driver._local_backend_assistant)
        self.assertFalse(self.driver._replica_enabled)

        self.driver._get_instorage_config()
        self.assertEqual(self.rep_target, self.driver._replica_target)
        self.assertTrue(self.driver._replica_enabled)

        self.driver._active_backend_id = self.rep_target['backend_id']
        self.driver._get_instorage_config()
        self.assertEqual(self.driver._assistant,
                         self.driver._aux_backend_assistant)
        self.assertTrue(self.driver._replica_enabled)

        self.driver._active_backend_id = None
        self.driver._get_instorage_config()

    def test_instorage_create_volume_with_mirror_replication(self):
        # Set replication target.
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create sync copy replication.
        volume, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])
        self._validate_replic_vol_creation(volume)
        self.driver.delete_volume(volume)
        self._validate_replic_vol_deletion(volume)

        # Create async copy replication.
        volume, model_update = self._create_test_volume(self.gm_type)
        self.assertEqual('enabled', model_update['replication_status'])
        self._validate_replic_vol_creation(volume)
        self.driver.delete_volume(volume)
        self._validate_replic_vol_deletion(volume)

    def _validate_replic_vol_creation(self, volume):
        # Create sync copy volume
        self._assert_vol_exists(volume['name'], True)
        self._assert_vol_exists(
            instorage_const.REPLICA_AUX_VOL_PREFIX + volume['name'], True)

        rel_info = self.driver._assistant.get_relationship_info(volume['name'])
        self.assertIsNotNone(rel_info)
        vol_rep_type = rel_info['copy_type']
        rep_type = self.driver._get_volume_replicated_type(self.ctxt, volume)
        self.assertEqual(vol_rep_type, rep_type)

        self.assertEqual('master', rel_info['primary'])
        self.assertEqual(volume['name'], rel_info['master_vdisk_name'])
        self.assertEqual(
            instorage_const.REPLICA_AUX_VOL_PREFIX + volume['name'],
            rel_info['aux_vdisk_name'])
        self.assertEqual('inconsistent_copying', rel_info['state'])

        self.sim._rc_state_transition('wait', rel_info)
        self.assertEqual('consistent_synchronized', rel_info['state'])

    def _validate_replic_vol_deletion(self, volume):
        self._assert_vol_exists(volume['name'], False)
        self._assert_vol_exists(
            instorage_const.REPLICA_AUX_VOL_PREFIX + volume['name'], False)
        rel_info = self.driver._assistant.get_relationship_info(volume['name'])
        self.assertIsNone(rel_info)

    def test_instorage_create_snapshot_volume_with_mirror_replica(self):
        # Set replication target
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create sync copy replication volume.
        vol1, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        snap = self._generate_snapshot_info(vol1)
        self.driver.create_snapshot(snap)

        vol2 = self._generate_vol_info(None, None, self.mm_type)
        model_update = self.driver.create_volume_from_snapshot(vol2, snap)
        self.assertEqual('enabled', model_update['replication_status'])
        self._validate_replic_vol_creation(vol2)

        self.driver.delete_snapshot(snap)
        self.driver.delete_volume(vol1)
        self.driver.delete_volume(vol2)

    def test_instorage_create_cloned_volume_with_mirror_replica(self):
        # Set replication target
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create a source sync copy replication volume.
        src_volume, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        volume = self._generate_vol_info(None, None, self.mm_type)

        # Create a cloned volume from source volume.
        model_update = self.driver.create_cloned_volume(volume, src_volume)
        self.assertEqual('enabled', model_update['replication_status'])
        self._validate_replic_vol_creation(volume)

        self.driver.delete_volume(src_volume)
        self.driver.delete_volume(volume)

    def test_instorage_retype_from_mirror_to_none_replication(self):
        # Set replication target
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)
        host = {'host': 'openstack@mcs#openstack'}

        volume, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        diff, _equal = volume_types.volume_types_diff(
            self.ctxt, self.mm_type['id'], self.gm_type['id'])
        # Change the mirror type
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.retype, self.ctxt,
                          volume, self.gm_type, diff, host)

        diff, _equal = volume_types.volume_types_diff(
            self.ctxt, self.non_replica_type['id'], self.mm_type['id'])
        # Disable replica
        retyped, model_update = self.driver.retype(
            self.ctxt, volume, self.non_replica_type, diff, host)
        self.assertEqual('disabled', model_update['replication_status'])
        self._assert_vol_exists(
            instorage_const.REPLICA_AUX_VOL_PREFIX + volume['name'], False)

        self.driver.delete_volume(volume)
        self._assert_vol_exists(volume['name'], False)
        rel_info = self.driver._assistant.get_relationship_info(volume['name'])
        self.assertIsNone(rel_info)

    def test_instorage_retype_from_none_to_mirror_replication(self):
        # Set replication target
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)
        host = {'host': 'openstack@mcs#openstack'}

        diff, _equal = volume_types.volume_types_diff(
            self.ctxt, self.non_replica_type['id'], self.mm_type['id'])

        volume, model_update = self._create_test_volume(self.non_replica_type)
        self.assertIsNone(model_update)

        # Enable replica
        retyped, model_update = self.driver.retype(
            self.ctxt, volume, self.mm_type, diff, host)
        volume['volume_type_id'] = self.mm_type['id']
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         model_update['replication_status'])
        self._validate_replic_vol_creation(volume)

        self.driver.delete_volume(volume)

    def test_instorage_extend_volume_replication(self):
        # Set replication target.
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create sync copy replication.
        volume, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        self.driver.extend_volume(volume, '13')
        attrs = self.driver._assistant.get_vdisk_attributes(volume['name'])
        vol_size = int(attrs['capacity']) / units.Gi
        self.assertAlmostEqual(vol_size, 13)

        attrs = self.driver._aux_backend_assistant.get_vdisk_attributes(
            instorage_const.REPLICA_AUX_VOL_PREFIX + volume['name'])
        vol_size = int(attrs['capacity']) / units.Gi
        self.assertAlmostEqual(vol_size, 13)

        self.driver.delete_volume(volume)
        self._validate_replic_vol_deletion(volume)

    def test_instorage_manage_existing_mismatch_with_volume_replication(self):
        # Set replication target.
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create replication volume.
        rep_volume, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual(fields.ReplicationStatus.ENABLED,
                         model_update['replication_status'])

        # Create non-replication volume.
        non_rep_volume, model_update = self._create_test_volume(
            self.non_replica_type)

        new_volume = self._generate_vol_info(None, None)

        ref = {'source-name': rep_volume['name']}
        new_volume['volume_type_id'] = self.non_replica_type['id']
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)

        ref = {'source-name': non_rep_volume['name']}
        new_volume['volume_type_id'] = self.mm_type['id']
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)

        ref = {'source-name': rep_volume['name']}
        new_volume['volume_type_id'] = self.gm_type['id']
        self.assertRaises(exception.ManageExistingVolumeTypeMismatch,
                          self.driver.manage_existing, new_volume, ref)
        self.driver.delete_volume(rep_volume)
        self.driver.delete_volume(new_volume)

    def test_instorage_manage_existing_with_volume_replication(self):
        # Set replication target.
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create replication volume.
        rep_volume, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        uid_of_master = self._get_vdisk_uid(rep_volume['name'])
        uid_of_aux = self._get_vdisk_uid(
            instorage_const.REPLICA_AUX_VOL_PREFIX + rep_volume['name'])

        new_volume = self._generate_vol_info(None, None, self.mm_type)
        ref = {'source-name': rep_volume['name']}
        self.driver.manage_existing(new_volume, ref)

        # Check the uid of the volume which has been renamed.
        uid_of_master_volume = self._get_vdisk_uid(new_volume['name'])
        uid_of_aux_volume = self._get_vdisk_uid(
            instorage_const.REPLICA_AUX_VOL_PREFIX + new_volume['name'])
        self.assertEqual(uid_of_master, uid_of_master_volume)
        self.assertEqual(uid_of_aux, uid_of_aux_volume)

        self.driver.delete_volume(rep_volume)

    def test_instorage_delete_volume_with_mirror_replication(self):
        # Set replication target.
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create sync copy replication.
        volume, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])
        self._validate_replic_vol_creation(volume)

        # Delete volume in non-failover state
        self.driver.delete_volume(volume)
        self._validate_replic_vol_deletion(volume)

        non_replica_vol, model_update = self._create_test_volume(
            self.non_replica_type)
        self.assertIsNone(model_update)

        volumes = [volume, non_replica_vol]
        # Delete volume in failover state
        self.driver.failover_host(
            self.ctxt, volumes, self.rep_target['backend_id'])
        # Delete non-replicate volume in a failover state
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.delete_volume,
                          non_replica_vol)

        # Delete replicate volume in failover state
        self.driver.delete_volume(volume)
        self._validate_replic_vol_deletion(volume)
        self.driver.failover_host(
            self.ctxt, volumes, 'default')
        self.driver.delete_volume(non_replica_vol)
        self._assert_vol_exists(non_replica_vol['name'], False)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'delete_vdisk')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'delete_relationship')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_relationship_info')
    def test_delete_target_volume(self, get_relationship_info,
                                  delete_relationship,
                                  delete_vdisk):
        # Set replication target.
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)
        fake_name = 'volume-%s' % fake.VOLUME_ID
        get_relationship_info.return_value = {'aux_vdisk_name':
                                              fake_name}
        self.driver._assistant.delete_rc_volume(fake_name)
        get_relationship_info.assert_called_once_with(fake_name)
        delete_relationship.assert_called_once_with(fake_name)
        delete_vdisk.assert_called_once_with(fake_name, False)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'delete_vdisk')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'delete_relationship')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_relationship_info')
    def test_delete_target_volume_no_relationship(self, get_relationship_info,
                                                  delete_relationship,
                                                  delete_vdisk):
        # Set replication target.
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)
        fake_name = 'volume-%s' % fake.VOLUME_ID
        get_relationship_info.return_value = None
        self.driver._assistant.delete_rc_volume(fake_name)
        get_relationship_info.assert_called_once_with(fake_name)
        self.assertFalse(delete_relationship.called)
        self.assertTrue(delete_vdisk.called)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'delete_vdisk')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'delete_relationship')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_relationship_info')
    def test_delete_target_volume_fail(self, get_relationship_info,
                                       delete_relationship,
                                       delete_vdisk):
        fake_id = fake.VOLUME_ID
        fake_name = 'volume-%s' % fake_id
        get_relationship_info.return_value = {'aux_vdisk_name':
                                              fake_name}
        delete_vdisk.side_effect = Exception
        self.assertRaises(exception.VolumeDriverException,
                          self.driver._assistant.delete_rc_volume,
                          fake_name)
        get_relationship_info.assert_called_once_with(fake_name)
        delete_relationship.assert_called_once_with(fake_name)

    def test_instorage_failover_host_backend_error(self):
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create sync copy replication.
        mm_vol, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        volumes = [mm_vol]

        self.driver._replica_enabled = False
        self.assertRaises(exception.UnableToFailOver,
                          self.driver.failover_host,
                          self.ctxt, volumes, self.rep_target['backend_id'])
        self.driver._replica_enabled = True
        self.assertRaises(exception.InvalidReplicationTarget,
                          self.driver.failover_host,
                          self.ctxt, volumes, self.fake_target['backend_id'])

        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_system_info') as get_sys_info:
            get_sys_info.side_effect = [
                exception.VolumeBackendAPIException(data='CMMVC6071E'),
                exception.VolumeBackendAPIException(data='CMMVC6071E')]
            self.assertRaises(exception.UnableToFailOver,
                              self.driver.failover_host,
                              self.ctxt, volumes,
                              self.rep_target['backend_id'])

            self.driver._active_backend_id = self.rep_target['backend_id']
            self.assertRaises(exception.UnableToFailOver,
                              self.driver.failover_host,
                              self.ctxt, volumes, 'default')
        self.driver.delete_volume(mm_vol)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_relationship_info')
    def test_failover_volume_relationship_error(self, get_relationship_info):
        # Create async copy replication.
        gm_vol, model_update = self._create_test_volume(self.gm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        get_relationship_info.side_effect = [None,
                                             exception.VolumeDriverException]
        expected_list = [{'updates': {'replication_status':
                                      fields.ReplicationStatus.FAILOVER_ERROR,
                                      'status': 'error'},
                          'volume_id': gm_vol.id}
                         ]
        volumes_update = self.driver._failover_replica_volumes(self.ctxt,
                                                               [gm_vol])
        self.assertEqual(expected_list, volumes_update)

        volumes_update = self.driver._failover_replica_volumes(self.ctxt,
                                                               [gm_vol])
        self.assertEqual(expected_list, volumes_update)

    @mock.patch.object(instorage_common.InStorageMCSCommonDriver,
                       '_update_volume_stats')
    @mock.patch.object(instorage_common.InStorageMCSCommonDriver,
                       '_update_instorage_state')
    def test_instorage_failover_host_replica_volumes(self,
                                                     update_instorage_state,
                                                     update_volume_stats):
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create sync copy replication.
        mm_vol, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        # Create async replication volume.
        gm_vol, model_update = self._create_test_volume(self.gm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        volumes = [mm_vol, gm_vol]
        expected_list = [{'updates': {'replication_status': 'failed-over'},
                          'volume_id': mm_vol['id']},
                         {'updates': {'replication_status': 'failed-over'},
                          'volume_id': gm_vol['id']}
                         ]

        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, self.rep_target['backend_id'])
        self.assertEqual(self.rep_target['backend_id'], target_id)
        self.assertEqual(expected_list, volume_list)

        self.assertEqual(self.driver._active_backend_id, target_id)
        self.assertEqual(self.driver._aux_backend_assistant,
                         self.driver._assistant)
        self.assertEqual([self.driver._replica_target['pool_name']],
                         self.driver._get_backend_pools())
        self.assertTrue(update_instorage_state.called)
        self.assertTrue(update_volume_stats.called)

        self.driver.delete_volume(mm_vol)
        self.driver.delete_volume(gm_vol)

        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, None)
        self.assertEqual(self.rep_target['backend_id'], target_id)
        self.assertEqual([], volume_list)

    @mock.patch.object(instorage_common.InStorageMCSCommonDriver,
                       '_update_volume_stats')
    @mock.patch.object(instorage_common.InStorageMCSCommonDriver,
                       '_update_instorage_state')
    def test_instorage_failover_host_normal_volumes(self,
                                                    update_instorage_state,
                                                    update_volume_stats):
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create sync copy replication.
        mm_vol, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])
        mm_vol['status'] = 'in-use'

        # Create non-replication volume.
        non_replica_vol, model_update = self._create_test_volume(
            self.non_replica_type)
        self.assertIsNone(model_update)
        non_replica_vol['status'] = 'error'

        volumes = [mm_vol, non_replica_vol]

        rep_data1 = json.dumps({'previous_status': mm_vol['status']})
        rep_data2 = json.dumps({'previous_status': non_replica_vol['status']})
        expected_list = [{'updates': {'status': 'error',
                                      'replication_driver_data': rep_data1},
                          'volume_id': mm_vol['id']},
                         {'updates': {'status': 'error',
                                      'replication_driver_data': rep_data2},
                          'volume_id': non_replica_vol['id']},
                         ]

        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, self.rep_target['backend_id'])
        self.assertEqual(self.rep_target['backend_id'], target_id)
        self.assertEqual(expected_list, volume_list)

        self.assertEqual(self.driver._active_backend_id, target_id)
        self.assertEqual(self.driver._aux_backend_assistant,
                         self.driver._assistant)
        self.assertEqual([self.driver._replica_target['pool_name']],
                         self.driver._get_backend_pools())
        self.assertTrue(update_instorage_state.called)
        self.assertTrue(update_volume_stats.called)

        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, None)
        self.assertEqual(self.rep_target['backend_id'], target_id)
        self.assertEqual([], volume_list)
        # Delete non-replicate volume in a failover state
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.delete_volume,
                          non_replica_vol)
        self.driver.failover_host(self.ctxt, volumes, 'default')
        self.driver.delete_volume(mm_vol)
        self.driver.delete_volume(non_replica_vol)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'switch_relationship')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'stop_relationship')
    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_relationship_info')
    def test_failover_host_by_force_access(self, get_relationship_info,
                                           stop_relationship,
                                           switch_relationship):
        replica_obj = self.driver._get_replica_obj(instorage_const.SYNC)
        fake_vol_info = {'vol_id': '21345678-1234-5678-1234-567812345683',
                         'vol_name': 'fake-volume'}
        fake_vol = self._generate_vol_info(**fake_vol_info)
        target_vol = instorage_const.REPLICA_AUX_VOL_PREFIX + fake_vol['name']
        context = mock.Mock
        get_relationship_info.side_effect = [{
            'aux_vdisk_name': 'replica-12345678-1234-5678-1234-567812345678',
            'name': 'RC_name'}]
        switch_relationship.side_effect = exception.VolumeDriverException
        replica_obj.failover_volume_host(context, fake_vol)
        get_relationship_info.assert_called_once_with(target_vol)
        switch_relationship.assert_called_once_with('RC_name')
        stop_relationship.assert_called_once_with(target_vol, access=True)

    @mock.patch.object(instorage_common.InStorageMCSCommonDriver,
                       '_update_volume_stats')
    @mock.patch.object(instorage_common.InStorageMCSCommonDriver,
                       '_update_instorage_state')
    def test_instorage_failback_replica_volumes(self,
                                                update_instorage_state,
                                                update_volume_stats):
        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create sync copy replication.
        mm_vol, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        # Create async copy replication.
        gm_vol, model_update = self._create_test_volume(self.gm_type)
        self.assertEqual('enabled', model_update['replication_status'])

        volumes = [gm_vol, mm_vol]
        failover_expect = [{'updates': {'replication_status': 'failed-over'},
                            'volume_id': gm_vol['id']},
                           {'updates': {'replication_status': 'failed-over'},
                            'volume_id': mm_vol['id']}
                           ]

        failback_expect = [{'updates': {'replication_status': 'enabled',
                                        'status': 'available'},
                            'volume_id': gm_vol['id']},
                           {'updates': {'replication_status': 'enabled',
                                        'status': 'available'},
                            'volume_id': mm_vol['id']},
                           ]
        # Already failback
        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, 'default')
        self.assertIsNone(target_id)
        self.assertEqual([], volume_list)

        # fail over operation
        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, self.rep_target['backend_id'])
        self.assertEqual(self.rep_target['backend_id'], target_id)
        self.assertEqual(failover_expect, volume_list)
        self.assertTrue(update_instorage_state.called)
        self.assertTrue(update_volume_stats.called)

        # fail back operation
        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, 'default')
        self.assertEqual('default', target_id)
        self.assertEqual(failback_expect, volume_list)
        self.assertIsNone(self.driver._active_backend_id)
        self.assertEqual(fakes.MCS_POOLS, self.driver._get_backend_pools())
        self.assertTrue(update_instorage_state.called)
        self.assertTrue(update_volume_stats.called)
        self.driver.delete_volume(mm_vol)
        self.driver.delete_volume(gm_vol)

    @mock.patch.object(instorage_common.InStorageMCSCommonDriver,
                       '_update_volume_stats')
    @mock.patch.object(instorage_common.InStorageMCSCommonDriver,
                       '_update_instorage_state')
    def test_instorage_failback_normal_volumes(self,
                                               update_instorage_state,
                                               update_volume_stats):

        self.driver.configuration.set_override('replication_device',
                                               [self.rep_target])
        self.driver.do_setup(self.ctxt)

        # Create sync copy replication.
        mm_vol, model_update = self._create_test_volume(self.mm_type)
        self.assertEqual('enabled', model_update['replication_status'])
        mm_vol['status'] = 'in-use'

        # Create non-replication volume.
        non_replica_vol1, model_update = self._create_test_volume(
            self.non_replica_type)
        self.assertIsNone(model_update)
        non_replica_vol2, model_update = self._create_test_volume(
            self.non_replica_type)
        self.assertIsNone(model_update)
        non_replica_vol1['status'] = 'error'
        non_replica_vol2['status'] = 'available'

        volumes = [mm_vol, non_replica_vol1, non_replica_vol2]

        rep_data0 = json.dumps({'previous_status': mm_vol['status']})
        rep_data1 = json.dumps({'previous_status': non_replica_vol1['status']})
        rep_data2 = json.dumps({'previous_status': non_replica_vol2['status']})
        failover_expect = [{'updates': {'status': 'error',
                                        'replication_driver_data': rep_data0},
                            'volume_id': mm_vol['id']},
                           {'updates': {'status': 'error',
                                        'replication_driver_data': rep_data1},
                            'volume_id': non_replica_vol1['id']},
                           {'updates': {'status': 'error',
                                        'replication_driver_data': rep_data2},
                            'volume_id': non_replica_vol2['id']}]
        failback_expect = [{'updates': {'status': 'in-use',
                                        'replication_driver_data': ''},
                            'volume_id': mm_vol['id']},
                           {'updates': {'status': 'error',
                                        'replication_driver_data': ''},
                            'volume_id': non_replica_vol1['id']},
                           {'updates': {'status': 'available',
                                        'replication_driver_data': ''},
                            'volume_id': non_replica_vol2['id']}]
        # Already failback
        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, 'default')
        self.assertIsNone(target_id)
        self.assertEqual([], volume_list)

        # fail over operation
        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, self.rep_target['backend_id'])
        self.assertEqual(self.rep_target['backend_id'], target_id)
        self.assertEqual(failover_expect, volume_list)
        self.assertTrue(update_instorage_state.called)
        self.assertTrue(update_volume_stats.called)

        # fail back operation
        mm_vol['replication_driver_data'] = json.dumps(
            {'previous_status': 'in-use'})
        non_replica_vol1['replication_driver_data'] = json.dumps(
            {'previous_status': 'error'})
        non_replica_vol2['replication_driver_data'] = json.dumps(
            {'previous_status': 'available'})
        target_id, volume_list = self.driver.failover_host(
            self.ctxt, volumes, 'default')
        self.assertEqual('default', target_id)
        self.assertEqual(failback_expect, volume_list)
        self.assertIsNone(self.driver._active_backend_id)
        self.assertEqual(fakes.MCS_POOLS, self.driver._get_backend_pools())
        self.assertTrue(update_instorage_state.called)
        self.assertTrue(update_volume_stats.called)
        self.driver.delete_volume(mm_vol)
        self.driver.delete_volume(non_replica_vol1)
        self.driver.delete_volume(non_replica_vol2)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_system_info')
    @mock.patch.object(instorage_rep.InStorageMCSReplicationManager,
                       '_partnership_validate_create')
    def test_establish_partnership_with_local_sys(self, partnership_create,
                                                  get_system_info):
        get_system_info.side_effect = [{'system_name': 'instorage-mcs-sim'},
                                       {'system_name': 'instorage-mcs-sim'}]

        rep_mgr = self.driver._get_replica_mgr()
        rep_mgr.establish_target_partnership()
        self.assertFalse(partnership_create.called)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_system_info')
    def test_establish_target_partnership(self, get_system_info):
        source_system_name = 'instorage-mcs-sim'
        target_system_name = 'aux-mcs-sim'

        get_system_info.side_effect = [{'system_name': source_system_name},
                                       {'system_name': target_system_name}]

        rep_mgr = self.driver._get_replica_mgr()
        rep_mgr.establish_target_partnership()
        partner_info = self.driver._assistant.get_partnership_info(
            source_system_name)
        self.assertIsNotNone(partner_info)
        self.assertEqual(source_system_name, partner_info['name'])

        partner_info = self.driver._assistant.get_partnership_info(
            source_system_name)
        self.assertIsNotNone(partner_info)
        self.assertEqual(source_system_name, partner_info['name'])

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'start_relationship')
    def test_sync_replica_volumes_with_aux(self, start_relationship):
        # Create sync copy replication.
        mm_vol = self._generate_vol_info(None, None, self.mm_type)
        tgt_volume = instorage_const.REPLICA_AUX_VOL_PREFIX + mm_vol['name']

        volumes = [mm_vol]
        fake_info = {'volume': 'fake',
                     'master_vdisk_name': 'fake',
                     'aux_vdisk_name': 'fake'}
        sync_state = {'state': instorage_const.REP_CONSIS_SYNC,
                      'primary': 'fake'}
        sync_state.update(fake_info)
        disconn_state = {'state': instorage_const.REP_IDL_DISC,
                         'primary': 'master'}
        disconn_state.update(fake_info)
        stop_state = {'state': instorage_const.REP_CONSIS_STOP,
                      'primary': 'aux'}
        stop_state.update(fake_info)

        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_relationship_info',
                               mock.Mock(return_value=None)):
            self.driver._sync_with_aux(self.ctxt, volumes)
            self.assertFalse(start_relationship.called)

        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_relationship_info',
                               mock.Mock(return_value=sync_state)):
            self.driver._sync_with_aux(self.ctxt, volumes)
            self.assertFalse(start_relationship.called)

        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_relationship_info',
                               mock.Mock(return_value=disconn_state)):
            self.driver._sync_with_aux(self.ctxt, volumes)
            start_relationship.assert_called_once_with(tgt_volume)

        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_relationship_info',
                               mock.Mock(return_value=stop_state)):
            self.driver._sync_with_aux(self.ctxt, volumes)
            start_relationship.assert_called_with(tgt_volume,
                                                  primary='aux')
        self.driver.delete_volume(mm_vol)

    @mock.patch.object(instorage_common.InStorageAssistant,
                       'get_relationship_info')
    @mock.patch('oslo_service.loopingcall.FixedIntervalLoopingCall',
                new=testutils.ZeroIntervalLoopingCall)
    def test_wait_replica_vol_ready(self, get_relationship_info):
        # Create sync copy replication.
        mm_vol = self._generate_vol_info(None, None, self.mm_type)
        fake_info = {'volume': 'fake',
                     'master_vdisk_name': 'fake',
                     'aux_vdisk_name': 'fake',
                     'primary': 'fake'}
        sync_state = {'state': instorage_const.REP_CONSIS_SYNC}
        sync_state.update(fake_info)
        disconn_state = {'state': instorage_const.REP_IDL_DISC}
        disconn_state.update(fake_info)
        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_relationship_info',
                               mock.Mock(return_value=None)):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver._wait_replica_vol_ready,
                              self.ctxt, mm_vol)

        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_relationship_info',
                               mock.Mock(return_value=sync_state)):
            self.driver._wait_replica_vol_ready(self.ctxt, mm_vol)

        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_relationship_info',
                               mock.Mock(return_value=disconn_state)):
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.driver._wait_replica_vol_ready,
                              self.ctxt, mm_vol)
