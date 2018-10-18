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

import unittest

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
    def do_setup(self, driver_object, configuration):
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


########################
#
#   Start of Tests
#
########################


class UnityDriverTest(unittest.TestCase):
    @staticmethod
    def get_volume():
        return test_adapter.MockOSResource(provider_location='id^lun_43',
                                           id='id_43')

    @classmethod
    def get_snapshot(cls):
        return test_adapter.MockOSResource(volume=cls.get_volume())

    @staticmethod
    def get_context():
        return None

    @staticmethod
    def get_connector():
        return {'host': 'host1'}

    def setUp(self):
        self.config = conf.Configuration(None)
        self.driver = driver.UnityDriver(configuration=self.config)
        self.driver.adapter = MockAdapter()

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

    def test_fc_initialize(self):
        config = conf.Configuration(None)
        config.storage_protocol = 'fc'
        fc_driver = driver.UnityDriver(configuration=config)
        self.assertEqual('FC', fc_driver.protocol)

    def test_do_setup(self):
        def f():
            self.driver.do_setup(None)

        self.assertRaises(ex.AdapterSetupError, f)

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
