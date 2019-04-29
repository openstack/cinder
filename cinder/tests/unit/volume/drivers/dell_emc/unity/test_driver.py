# Copyright (c) 2016 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import functools
import unittest
from unittest import mock

from cinder.objects import fields
from cinder.tests.unit.volume.drivers.dell_emc.unity \
    import fake_exception as ex
from cinder.tests.unit.volume.drivers.dell_emc.unity import test_adapter
from cinder.volume import configuration as conf
from cinder.volume.drivers.dell_emc.unity import driver


########################
#
#   Start of Mocks
#
########################

class MockAdapter(object):
    def __init__(self):
        self.is_setup = False

    def do_setup(self, driver_object, configuration):
        self.is_setup = True
        raise ex.AdapterSetupError()

    @staticmethod
    def create_volume(volume):
        return volume

    @staticmethod
    def create_volume_from_snapshot(volume, snapshot):
        return volume

    @staticmethod
    def create_cloned_volume(volume, src_vref):
        return volume

    @staticmethod
    def extend_volume(volume, new_size):
        volume.size = new_size

    @staticmethod
    def delete_volume(volume):
        volume.exists = False

    @staticmethod
    def create_snapshot(snapshot):
        snapshot.exists = True
        return snapshot

    @staticmethod
    def delete_snapshot(snapshot):
        snapshot.exists = False

    @staticmethod
    def initialize_connection(volume, connector):
        return {'volume': volume, 'connector': connector}

    @staticmethod
    def terminate_connection(volume, connector):
        return {'volume': volume, 'connector': connector}

    @staticmethod
    def update_volume_stats():
        return {'stats': 123}

    @staticmethod
    def manage_existing(volume, existing_ref):
        volume.managed = True
        return volume

    @staticmethod
    def manage_existing_get_size(volume, existing_ref):
        volume.managed = True
        volume.size = 7
        return volume

    @staticmethod
    def get_pool_name(volume):
        return 'pool_0'

    @staticmethod
    def initialize_connection_snapshot(snapshot, connector):
        return {'snapshot': snapshot, 'connector': connector}

    @staticmethod
    def terminate_connection_snapshot(snapshot, connector):
        return {'snapshot': snapshot, 'connector': connector}

    @staticmethod
    def restore_snapshot(volume, snapshot):
        return True

    @staticmethod
    def migrate_volume(volume, host):
        return True, {}

    @staticmethod
    def create_group(group):
        return group

    @staticmethod
    def delete_group(group):
        return group

    @staticmethod
    def update_group(group, add_volumes, remove_volumes):
        return group, add_volumes, remove_volumes

    @staticmethod
    def create_group_from_snap(group, volumes, group_snapshot, snapshots):
        return group, volumes, group_snapshot, snapshots

    @staticmethod
    def create_cloned_group(group, volumes, source_group, source_vols):
        return group, volumes, source_group, source_vols

    @staticmethod
    def create_group_snapshot(group_snapshot, snapshots):
        return group_snapshot, snapshots

    @staticmethod
    def delete_group_snapshot(group_snapshot):
        return group_snapshot

    def failover(self, volumes, secondary_id=None, groups=None):
        return {'volumes': volumes,
                'secondary_id': secondary_id,
                'groups': groups}

    @staticmethod
    def enable_replication(context, group, volumes):
        if volumes and group:
            return {'replication_status':
                    fields.ReplicationStatus.ENABLED}, None
        return {}, None

    @staticmethod
    def disable_replication(context, group, volumes):
        if volumes and group:
            return {'replication_status':
                    fields.ReplicationStatus.DISABLED}, None
        return {}, None

    @staticmethod
    def failover_replication(context, group, volumes,
                             secondary_backend_id):
        group_update = {}
        volumes_update = []
        if volumes and group and secondary_backend_id:
            group_update = {'replication_status':
                            fields.ReplicationStatus.FAILED_OVER}
            for volume in volumes:
                volume_update = {
                    'id': volume.id,
                    'replication_status':
                        fields.ReplicationStatus.FAILED_OVER}
                volumes_update.append(volume_update)
            return group_update, volumes_update
        return group_update, None

    def retype(self, ctxt, volume, new_type, diff, host):
        return True


class MockReplicationManager(object):
    def __init__(self):
        self.active_adapter = MockAdapter()

    def do_setup(self, d):
        if isinstance(d, driver.UnityDriver):
            raise ex.ReplicationManagerSetupError()


########################
#
#   Start of Tests
#
########################


patch_check_cg = mock.patch(
    'cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
    side_effect=lambda g: not g.id.endswith('_generic'))


class UnityDriverTest(unittest.TestCase):
    @staticmethod
    def get_volume():
        return test_adapter.MockOSResource(provider_location='id^lun_43',
                                           id='id_43')

    @staticmethod
    def get_volumes():
        volumes = []
        for number in ['50', '51', '52', '53']:
            volume = test_adapter.MockOSResource(
                provider_location='id^lun_' + number, id='id_' + number)
            volumes.append(volume)
        return volumes

    @staticmethod
    def get_generic_group():
        return test_adapter.MockOSResource(name='group_name_generic',
                                           id='group_id_generic')

    @staticmethod
    def get_cg():
        return test_adapter.MockOSResource(name='group_name_cg',
                                           id='group_id_cg')

    @classmethod
    def get_snapshot(cls):
        return test_adapter.MockOSResource(volume=cls.get_volume())

    @classmethod
    def get_generic_group_snapshot(cls):
        return test_adapter.MockOSResource(group=cls.get_generic_group(),
                                           id='group_snapshot_id_generic')

    @classmethod
    def get_cg_group_snapshot(cls):
        return test_adapter.MockOSResource(group=cls.get_cg(),
                                           id='group_snapshot_id_cg')

    @staticmethod
    def get_context():
        return None

    @staticmethod
    def get_connector():
        return {'host': 'host1'}

    def setUp(self):
        self.config = conf.Configuration(None)
        self.driver = driver.UnityDriver(configuration=self.config)
        self.driver.replication_manager = MockReplicationManager()

    def test_default_initialize(self):
        config = conf.Configuration(None)
        iscsi_driver = driver.UnityDriver(configuration=config)
        self.assertListEqual([], config.unity_storage_pool_names)
        self.assertListEqual([], config.unity_io_ports)
        self.assertTrue(config.san_thin_provision)
        self.assertEqual('', config.san_ip)
        self.assertEqual('admin', config.san_login)
        self.assertEqual('', config.san_password)
        self.assertEqual('', config.san_private_key)
        self.assertEqual('', config.san_clustername)
        self.assertEqual(22, config.san_ssh_port)
        self.assertEqual(False, config.san_is_local)
        self.assertEqual(30, config.ssh_conn_timeout)
        self.assertEqual(1, config.ssh_min_pool_conn)
        self.assertEqual(5, config.ssh_max_pool_conn)
        self.assertEqual('iSCSI', iscsi_driver.protocol)
        self.assertIsNone(iscsi_driver.active_backend_id)

    def test_initialize_with_active_backend_id(self):
        config = conf.Configuration(None)
        iscsi_driver = driver.UnityDriver(configuration=config,
                                          active_backend_id='secondary_unity')
        self.assertEqual('secondary_unity', iscsi_driver.active_backend_id)

    def test_fc_initialize(self):
        config = conf.Configuration(None)
        config.storage_protocol = 'fc'
        fc_driver = driver.UnityDriver(configuration=config)
        self.assertEqual('FC', fc_driver.protocol)

    def test_do_setup(self):
        def f():
            self.driver.do_setup(None)

        self.assertRaises(ex.ReplicationManagerSetupError, f)

    def test_create_volume(self):
        volume = self.get_volume()
        self.assertEqual(volume, self.driver.create_volume(volume))

    def test_create_volume_from_snapshot(self):
        volume = self.get_volume()
        snap = self.get_snapshot()
        self.assertEqual(
            volume, self.driver.create_volume_from_snapshot(volume, snap))

    def test_create_cloned_volume(self):
        volume = self.get_volume()
        self.assertEqual(
            volume, self.driver.create_cloned_volume(volume, None))

    def test_extend_volume(self):
        volume = self.get_volume()
        self.driver.extend_volume(volume, 6)
        self.assertEqual(6, volume.size)

    def test_delete_volume(self):
        volume = self.get_volume()
        self.driver.delete_volume(volume)
        self.assertFalse(volume.exists)

    def test_migrate_volume(self):
        volume = self.get_volume()
        ret = self.driver.migrate_volume(self.get_context(),
                                         volume,
                                         'HostA@BackendB#PoolC')
        self.assertEqual((True, {}), ret)

    def test_retype_volume(self):
        volume = self.get_volume()
        new_type = {'name': u'type01', 'qos_specs_id': 'test_qos_id',
                    'extra_specs': {},
                    'id': u'd67c4480-a61b-44c0-a58b-24c0357cadeb'}
        diff = None
        ret = self.driver.retype(self.get_context(),
                                 volume, new_type, diff,
                                 'HostA@BackendB#PoolC')
        self.assertTrue(ret)

    def test_create_snapshot(self):
        snapshot = self.get_snapshot()
        self.driver.create_snapshot(snapshot)
        self.assertTrue(snapshot.exists)

    def test_delete_snapshot(self):
        snapshot = self.get_snapshot()
        self.driver.delete_snapshot(snapshot)
        self.assertFalse(snapshot.exists)

    def test_ensure_export(self):
        self.assertIsNone(self.driver.ensure_export(
            self.get_context(), self.get_volume()))

    def test_create_export(self):
        self.assertIsNone(self.driver.create_export(
            self.get_context(), self.get_volume(), self.get_connector()))

    def test_remove_export(self):
        self.assertIsNone(self.driver.remove_export(
            self.get_context(), self.get_volume()))

    def test_check_for_export(self):
        self.assertIsNone(self.driver.check_for_export(
            self.get_context(), self.get_volume()))

    def test_initialize_connection(self):
        volume = self.get_volume()
        connector = self.get_connector()
        conn_info = self.driver.initialize_connection(volume, connector)
        self.assertEqual(volume, conn_info['volume'])
        self.assertEqual(connector, conn_info['connector'])

    def test_terminate_connection(self):
        volume = self.get_volume()
        connector = self.get_connector()
        conn_info = self.driver.terminate_connection(volume, connector)
        self.assertEqual(volume, conn_info['volume'])
        self.assertEqual(connector, conn_info['connector'])

    def test_update_volume_stats(self):
        stats = self.driver.get_volume_stats(True)
        self.assertEqual(123, stats['stats'])
        self.assertEqual(self.driver.VERSION, stats['driver_version'])
        self.assertEqual(self.driver.VENDOR, stats['vendor_name'])

    def test_manage_existing(self):
        volume = self.driver.manage_existing(self.get_volume(), None)
        self.assertTrue(volume.managed)

    def test_manage_existing_get_size(self):
        volume = self.driver.manage_existing_get_size(self.get_volume(), None)
        self.assertTrue(volume.managed)
        self.assertEqual(7, volume.size)

    def test_get_pool(self):
        self.assertEqual('pool_0', self.driver.get_pool(self.get_volume()))

    def test_unmanage(self):
        ret = self.driver.unmanage(None)
        self.assertIsNone(ret)

    def test_backup_use_temp_snapshot(self):
        self.assertTrue(self.driver.backup_use_temp_snapshot())

    def test_initialize_connection_snapshot(self):
        snapshot = self.get_snapshot()
        conn_info = self.driver.initialize_connection_snapshot(
            snapshot, self.get_connector())
        self.assertEqual(snapshot, conn_info['snapshot'])

    def test_terminate_connection_snapshot(self):
        snapshot = self.get_snapshot()
        conn_info = self.driver.terminate_connection_snapshot(
            snapshot, self.get_connector())
        self.assertEqual(snapshot, conn_info['snapshot'])

    def test_restore_snapshot(self):
        snapshot = self.get_snapshot()
        volume = self.get_volume()
        r = self.driver.revert_to_snapshot(None, volume, snapshot)
        self.assertTrue(r)

    @patch_check_cg
    def test_operate_generic_group_not_implemented(self, _):
        group = self.get_generic_group()
        context = self.get_context()

        for func in (self.driver.create_group, self.driver.update_group):
            self.assertRaises(NotImplementedError,
                              functools.partial(func, context, group))

        volumes = [self.get_volume()]
        for func in (self.driver.delete_group,
                     self.driver.create_group_from_src):
            self.assertRaises(NotImplementedError,
                              functools.partial(func, context, group, volumes))

        group_snap = self.get_generic_group_snapshot()
        volume_snaps = [self.get_snapshot()]
        for func in (self.driver.create_group_snapshot,
                     self.driver.delete_group_snapshot):
            self.assertRaises(NotImplementedError,
                              functools.partial(func, context, group_snap,
                                                volume_snaps))

    @patch_check_cg
    def test_create_group_cg(self, _):
        cg = self.get_cg()
        ret = self.driver.create_group(self.get_context(), cg)
        self.assertEqual(ret, cg)

    @patch_check_cg
    def test_delete_group_cg(self, _):
        cg = self.get_cg()
        volumes = [self.get_volume()]
        ret = self.driver.delete_group(self.get_context(), cg, volumes)
        self.assertEqual(ret, cg)

    @patch_check_cg
    def test_update_group_cg(self, _):
        cg = self.get_cg()
        volumes = [self.get_volume()]
        ret = self.driver.update_group(self.get_context(), cg,
                                       add_volumes=volumes)
        self.assertEqual(ret[0], cg)
        self.assertListEqual(ret[1], volumes)
        self.assertIsNone(ret[2])

    @patch_check_cg
    def test_create_group_from_src_group(self, _):
        cg = self.get_cg()
        volumes = [self.get_volume()]
        source_group = cg
        ret = self.driver.create_group_from_src(self.get_context(), cg,
                                                volumes,
                                                source_group=source_group)
        self.assertEqual(ret[0], cg)
        self.assertListEqual(ret[1], volumes)
        self.assertEqual(ret[2], source_group)
        self.assertIsNone(ret[3])

    @patch_check_cg
    def test_create_group_from_src_group_snapshot(self, _):
        cg = self.get_cg()
        volumes = [self.get_volume()]
        cg_snap = self.get_cg_group_snapshot()
        ret = self.driver.create_group_from_src(self.get_context(), cg,
                                                volumes,
                                                group_snapshot=cg_snap)
        self.assertEqual(ret[0], cg)
        self.assertListEqual(ret[1], volumes)
        self.assertEqual(ret[2], cg_snap)
        self.assertIsNone(ret[3])

    @patch_check_cg
    def test_create_group_snapshot_cg(self, _):
        cg_snap = self.get_cg_group_snapshot()
        ret = self.driver.create_group_snapshot(self.get_context(), cg_snap,
                                                None)
        self.assertEqual(ret[0], cg_snap)
        self.assertIsNone(ret[1])

    @patch_check_cg
    def test_delete_group_snapshot_cg(self, _):
        cg_snap = self.get_cg_group_snapshot()
        ret = self.driver.delete_group_snapshot(self.get_context(), cg_snap,
                                                None)
        self.assertEqual(ret, cg_snap)

    def test_failover_host(self):
        volume = self.get_volume()
        called = self.driver.failover_host(None, [volume],
                                           secondary_id='secondary_unity',
                                           groups=None)
        self.assertListEqual(called['volumes'], [volume])
        self.assertEqual('secondary_unity', called['secondary_id'])
        self.assertIsNone(called['groups'])

    def test_enable_replication(self):
        cg = self.get_cg()
        volumes = self.get_volumes()
        result = self.driver.enable_replication(None, cg, volumes)
        self.assertEqual(result,
                         ({'replication_status':
                          fields.ReplicationStatus.ENABLED},
                          None))

    def test_disable_replication(self):
        cg = self.get_cg()
        volumes = self.get_volumes()
        result = self.driver.disable_replication(None, cg, volumes)
        self.assertEqual(result,
                         ({'replication_status':
                          fields.ReplicationStatus.DISABLED},
                          None))

    def test_failover_replication(self):
        cg = self.get_cg()
        volumes = self.get_volumes()
        result = self.driver.failover_replication(
            None, cg, volumes, 'test_secondary_id')
        volumes = [{'id': 'id_50', 'replication_status': 'failed-over'},
                   {'id': 'id_51', 'replication_status': 'failed-over'},
                   {'id': 'id_52', 'replication_status': 'failed-over'},
                   {'id': 'id_53', 'replication_status': 'failed-over'}]

        self.assertEqual(result,
                         ({'replication_status':
                          fields.ReplicationStatus.FAILED_OVER},
                          volumes))
