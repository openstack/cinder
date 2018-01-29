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

from eventlet import greenthread
import mock
from oslo_utils import importutils

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit import utils as testutils
from cinder.tests.unit.volume.drivers.inspur.instorage import fakes
from cinder.volume import configuration as conf
from cinder.volume.drivers.inspur.instorage import instorage_common
from cinder.volume.drivers.inspur.instorage import instorage_fc
from cinder.volume import volume_types


class InStorageMCSFcDriverTestCase(test.TestCase):

    @mock.patch.object(greenthread, 'sleep')
    def setUp(self, mock_sleep):
        super(InStorageMCSFcDriverTestCase, self).setUp()
        self.fc_driver = fakes.FakeInStorageMCSFcDriver(
            configuration=conf.Configuration(None))
        self._def_flags = {'san_ip': 'hostname',
                           'san_login': 'user',
                           'san_password': 'pass',
                           'instorage_mcs_volpool_name': ['openstack'],
                           'instorage_mcs_localcopy_timeout': 20,
                           'instorage_mcs_localcopy_rate': 49,
                           'instorage_mcs_allow_tenant_qos': True}
        wwpns = ['1234567890123458', '6543210987654323']
        initiator = 'test.initiator.%s' % 123458
        self._connector = {'ip': '1.234.56.78',
                           'host': 'instorage-mcs-test',
                           'wwpns': wwpns,
                           'initiator': initiator}
        self.sim = fakes.FakeInStorage(['openstack'])

        self.fc_driver.set_fake_storage(self.sim)
        self.ctxt = context.get_admin_context()

        self._reset_flags()
        self.ctxt = context.get_admin_context()
        db_driver = self.fc_driver.configuration.db_driver
        self.db = importutils.import_module(db_driver)
        self.fc_driver.db = self.db
        self.fc_driver.do_setup(None)
        self.fc_driver.check_for_setup_error()
        self.fc_driver._assistant.check_lcmapping_interval = 0

    def _set_flag(self, flag, value):
        group = self.fc_driver.configuration.config_group
        self.fc_driver.configuration.set_override(flag, value, group)

    def _reset_flags(self):
        self.fc_driver.configuration.local_conf.reset()
        for k, v in self._def_flags.items():
            self._set_flag(k, v)

    def _create_volume(self, **kwargs):
        pool = fakes.get_test_pool()
        prop = {'host': 'openstack@mcs#%s' % pool,
                'size': 1}
        for p in prop.keys():
            if p not in kwargs:
                kwargs[p] = prop[p]
        vol = testutils.create_volume(self.ctxt, **kwargs)
        self.fc_driver.create_volume(vol)
        return vol

    def _delete_volume(self, volume):
        self.fc_driver.delete_volume(volume)
        self.db.volume_destroy(self.ctxt, volume['id'])

    def _generate_vol_info(self, vol_name, vol_id):
        pool = fakes.get_test_pool()
        prop = {'mdisk_grp_name': pool}
        if vol_name:
            prop.update(volume_name=vol_name,
                        volume_id=vol_id,
                        volume_size=10)
        else:
            prop.update(size=10,
                        volume_type_id=None,
                        mdisk_grp_name=pool,
                        host='openstack@mcs#%s' % pool)
        vol = testutils.create_volume(self.ctxt, **prop)
        return vol

    def _assert_vol_exists(self, name, exists):
        is_vol_defined = self.fc_driver._assistant.is_vdisk_defined(name)
        self.assertEqual(exists, is_vol_defined)

    def test_instorage_get_host_with_fc_connection(self):
        # Create a FC host
        del self._connector['initiator']
        assistant = self.fc_driver._assistant
        host_name = assistant.create_host(self._connector)

        # Remove the first wwpn from connector, and then try get host
        wwpns = self._connector['wwpns']
        wwpns.remove(wwpns[0])
        host_name = assistant.get_host_from_connector(self._connector)

        self.assertIsNotNone(host_name)

    def test_instorage_get_host_with_fc_connection_with_volume(self):
        # create a FC volume
        extra_spec = {'capabilities:storage_protocol': '<in> FC'}
        vol_type_fc = volume_types.create(self.ctxt, 'FC', extra_spec)

        volume_fc = self._generate_vol_info(None, None)
        volume_fc['volume_type_id'] = vol_type_fc['id']

        self.fc_driver.create_volume(volume_fc)

        connector = {'host': 'instorage-mcs-host',
                     'wwnns': ['20000090fa17311e', '20000090fa17311f'],
                     'wwpns': ['ff00000000000000', 'ff00000000000001'],
                     'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aaa'}

        self.fc_driver.initialize_connection(volume_fc, connector)
        # Create a FC host
        assistant = self.fc_driver._assistant

        # tell lsfabric to not return anything
        self.sim.error_injection('lsfabric', 'no_hosts')
        host_name = assistant.get_host_from_connector(
            connector, volume_fc['name'])
        self.assertIsNotNone(host_name)

    def test_instorage_get_host_from_connector_with_lshost_failure2(self):
        self._connector.pop('initiator')
        self._connector['wwpns'] = []  # Clearing will skip over fast-path
        assistant = self.fc_driver._assistant
        # Add a host to the simulator. We don't need it to match the
        # connector since we will force a bad failure for lshost.
        self.sim._cmd_mkhost(name='DifferentHost', hbawwpn='123456')
        # tell lshost to fail badly while called from
        # get_host_from_connector
        self.sim.error_injection('lshost', 'bigger_troubles')
        self.assertRaises(exception.VolumeBackendAPIException,
                          assistant.get_host_from_connector, self._connector)

    def test_instorage_get_host_from_connector_not_found(self):
        self._connector.pop('initiator')
        assistant = self.fc_driver._assistant
        # Create some hosts. The first is not related to the connector and
        # we use the simulator for that. The second is for the connector.
        # We will force the missing_host error for the first host, but
        # then tolerate and find the second host on the slow path normally.
        self.sim._cmd_mkhost(name='instorage-mcs-test-3',
                             hbawwpn='1234567')
        self.sim._cmd_mkhost(name='instorage-mcs-test-2',
                             hbawwpn='2345678')
        self.sim._cmd_mkhost(name='instorage-mcs-test-1',
                             hbawwpn='3456789')
        self.sim._cmd_mkhost(name='A-Different-host', hbawwpn='9345678')
        self.sim._cmd_mkhost(name='B-Different-host', hbawwpn='8345678')
        self.sim._cmd_mkhost(name='C-Different-host', hbawwpn='7345678')

        # tell lsfabric to skip rows so that we skip past fast path
        self.sim.error_injection('lsfabric', 'remove_rows')
        # Run test
        host_name = assistant.get_host_from_connector(self._connector)

        self.assertIsNone(host_name)

    def test_instorage_get_host_from_connector_fast_path(self):
        self._connector.pop('initiator')
        assistant = self.fc_driver._assistant
        # Create two hosts. Our lshost will return the hosts in sorted
        # Order. The extra host will be returned before the target
        # host. If we get detailed lshost info on our host without
        # gettting detailed info on the other host we used the fast path
        self.sim._cmd_mkhost(name='A-DifferentHost', hbawwpn='123456')
        assistant.create_host(self._connector)
        # tell lshost to fail while called from get_host_from_connector
        self.sim.error_injection('lshost', 'fail_fastpath')
        # tell lsfabric to skip rows so that we skip past fast path
        self.sim.error_injection('lsfabric', 'remove_rows')
        # Run test
        host_name = assistant.get_host_from_connector(self._connector)

        self.assertIsNotNone(host_name)
        # Need to assert that lshost was actually called. The way
        # we do that is check that the next simulator error for lshost
        # has not been reset.
        self.assertEqual(self.sim._next_cmd_error['lshost'], 'fail_fastpath',
                         "lshost was not called in the simulator. The "
                         "queued error still remains.")

    def test_instorage_initiator_multiple_wwpns_connected(self):

        # Generate us a test volume
        volume = self._create_volume()

        # Fibre Channel volume type
        extra_spec = {'capabilities:storage_protocol': '<in> FC'}
        vol_type = volume_types.create(self.ctxt, 'FC', extra_spec)

        volume['volume_type_id'] = vol_type['id']

        # Make sure that the volumes have been created
        self._assert_vol_exists(volume['name'], True)

        # Set up one WWPN that won't match and one that will.
        self.fc_driver._state['storage_nodes']['1']['WWPN'] = [
            '123456789ABCDEF0', 'AABBCCDDEEFF0010']

        wwpns = ['ff00000000000000', 'ff00000000000001']
        connector = {'host': 'instorage-mcs-test', 'wwpns': wwpns}

        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_conn_fc_wwpns') as get_mappings:
            mapped_wwpns = ['AABBCCDDEEFF0001', 'AABBCCDDEEFF0002',
                            'AABBCCDDEEFF0010', 'AABBCCDDEEFF0012']
            get_mappings.return_value = mapped_wwpns

            # Initialize the connection
            init_ret = self.fc_driver.initialize_connection(volume, connector)

            # Make sure we return all wwpns which where mapped as part of the
            # connection
            self.assertEqual(mapped_wwpns,
                             init_ret['data']['target_wwn'])

    def test_instorage_mcs_fc_validate_connector(self):
        conn_neither = {'host': 'host'}
        conn_iscsi = {'host': 'host', 'initiator': 'foo'}
        conn_fc = {'host': 'host', 'wwpns': 'bar', 'wwnns': 'foo'}
        conn_both = {'host': 'host', 'initiator': 'foo', 'wwpns': 'bar',
                     'wwnns': 'baz'}

        self.fc_driver.validate_connector(conn_fc)
        self.fc_driver.validate_connector(conn_both)
        self.assertRaises(exception.InvalidConnectorException,
                          self.fc_driver.validate_connector, conn_iscsi)
        self.assertRaises(exception.InvalidConnectorException,
                          self.fc_driver.validate_connector, conn_neither)

    def test_instorage_terminate_fc_connection(self):
        # create a FC volume
        volume_fc = self._create_volume()
        extra_spec = {'capabilities:storage_protocol': '<in> FC'}
        vol_type_fc = volume_types.create(self.ctxt, 'FC', extra_spec)
        volume_fc['volume_type_id'] = vol_type_fc['id']

        connector = {'host': 'instorage-mcs-host',
                     'wwnns': ['20000090fa17311e', '20000090fa17311f'],
                     'wwpns': ['ff00000000000000', 'ff00000000000001'],
                     'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aaa'}

        self.fc_driver.initialize_connection(volume_fc, connector)
        self.fc_driver.terminate_connection(volume_fc, connector)

    @mock.patch.object(instorage_fc.InStorageMCSFCDriver,
                       '_do_terminate_connection')
    def test_instorage_initialize_fc_connection_failure(self, term_conn):
        # create a FC volume
        volume_fc = self._create_volume()
        extra_spec = {'capabilities:storage_protocol': '<in> FC'}
        vol_type_fc = volume_types.create(self.ctxt, 'FC', extra_spec)
        volume_fc['volume_type_id'] = vol_type_fc['id']

        connector = {'host': 'instorage-mcs-host',
                     'wwnns': ['20000090fa17311e', '20000090fa17311f'],
                     'wwpns': ['ff00000000000000', 'ff00000000000001'],
                     'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aaa'}

        self.fc_driver._state['storage_nodes'] = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.fc_driver.initialize_connection,
                          volume_fc, connector)
        term_conn.assert_called_once_with(volume_fc, connector)

    def test_instorage_terminate_fc_connection_multi_attach(self):
        # create a FC volume
        volume_fc = self._create_volume()
        extra_spec = {'capabilities:storage_protocol': '<in> FC'}
        vol_type_fc = volume_types.create(self.ctxt, 'FC', extra_spec)
        volume_fc['volume_type_id'] = vol_type_fc['id']

        connector = {'host': 'instorage-mcs-host',
                     'wwnns': ['20000090fa17311e', '20000090fa17311f'],
                     'wwpns': ['ff00000000000000', 'ff00000000000001'],
                     'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aaa'}
        connector2 = {'host': 'INSTORAGE-MCS-HOST',
                      'wwnns': ['30000090fa17311e', '30000090fa17311f'],
                      'wwpns': ['ffff000000000000', 'ffff000000000001'],
                      'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1bbb'}

        # map and unmap the volume to two hosts normal case
        self.fc_driver.initialize_connection(volume_fc, connector)
        self.fc_driver.initialize_connection(volume_fc, connector2)
        # validate that the host entries are created
        for conn in [connector, connector2]:
            host = self.fc_driver._assistant.get_host_from_connector(conn)
            self.assertIsNotNone(host)
        self.fc_driver.terminate_connection(volume_fc, connector)
        self.fc_driver.terminate_connection(volume_fc, connector2)
        # validate that the host entries are deleted
        for conn in [connector, connector2]:
            host = self.fc_driver._assistant.get_host_from_connector(conn)
            self.assertIsNone(host)
        # map and unmap the volume to two hosts with the mapping gone
        self.fc_driver.initialize_connection(volume_fc, connector)
        self.fc_driver.initialize_connection(volume_fc, connector2)
        # Test multiple attachments case
        host_name = self.fc_driver._assistant.get_host_from_connector(
            connector2)
        self.fc_driver._assistant.unmap_vol_from_host(
            volume_fc['name'], host_name)
        host_name = self.fc_driver._assistant.get_host_from_connector(
            connector2)
        self.assertIsNotNone(host_name)
        with mock.patch.object(instorage_common.InStorageSSH,
                               'rmvdiskhostmap') as rmmap:
            rmmap.side_effect = Exception('boom')
            self.fc_driver.terminate_connection(volume_fc, connector2)
        host_name = self.fc_driver._assistant.get_host_from_connector(
            connector2)
        self.assertIsNone(host_name)
        # Test single attachment case
        self.fc_driver._assistant.unmap_vol_from_host(
            volume_fc['name'], host_name)
        with mock.patch.object(instorage_common.InStorageSSH,
                               'rmvdiskhostmap') as rmmap:
            rmmap.side_effect = Exception('boom')
            self.fc_driver.terminate_connection(volume_fc, connector)
        # validate that the host entries are deleted
        for conn in [connector, connector2]:
            host = self.fc_driver._assistant.get_host_from_connector(conn)
            self.assertIsNone(host)

    def test_instorage_initiator_target_map(self):
        # Generate us a test volume
        volume = self._create_volume()

        # FIbre Channel volume type
        extra_spec = {'capabilities:storage_protocol': '<in> FC'}
        vol_type = volume_types.create(self.ctxt, 'FC', extra_spec)

        volume['volume_type_id'] = vol_type['id']

        # Make sure that the volumes have been created
        self._assert_vol_exists(volume['name'], True)

        wwpns = ['ff00000000000000', 'ff00000000000001']
        connector = {'host': 'instorage-mcs-test', 'wwpns': wwpns}

        # Initialise the connection
        init_ret = self.fc_driver.initialize_connection(volume, connector)

        # Check that the initiator_target_map is as expected
        init_data = {'driver_volume_type': 'fibre_channel',
                     'data': {'initiator_target_map':
                              {'ff00000000000000': ['AABBCCDDEEFF0011'],
                               'ff00000000000001': ['AABBCCDDEEFF0011']},
                              'target_discovered': False,
                              'target_lun': 0,
                              'target_wwn': ['AABBCCDDEEFF0011'],
                              'volume_id': volume['id']
                              }
                     }

        self.assertEqual(init_data, init_ret)

        # Terminate connection
        term_ret = self.fc_driver.terminate_connection(volume, connector)

        # Check that the initiator_target_map is as expected
        term_data = {'driver_volume_type': 'fibre_channel',
                     'data': {'initiator_target_map':
                              {'ff00000000000000': ['5005076802432ADE',
                                                    '5005076802332ADE',
                                                    '5005076802532ADE',
                                                    '5005076802232ADE',
                                                    '5005076802132ADE',
                                                    '5005086802132ADE',
                                                    '5005086802332ADE',
                                                    '5005086802532ADE',
                                                    '5005086802232ADE',
                                                    '5005086802432ADE'],
                               'ff00000000000001': ['5005076802432ADE',
                                                    '5005076802332ADE',
                                                    '5005076802532ADE',
                                                    '5005076802232ADE',
                                                    '5005076802132ADE',
                                                    '5005086802132ADE',
                                                    '5005086802332ADE',
                                                    '5005086802532ADE',
                                                    '5005086802232ADE',
                                                    '5005086802432ADE']}
                              }
                     }

        self.assertItemsEqual(term_data, term_ret)

    def test_instorage_mcs_fc_host_maps(self):
        # Create two volumes to be used in mappings

        ctxt = context.get_admin_context()
        volume1 = self._generate_vol_info(None, None)
        self.fc_driver.create_volume(volume1)
        volume2 = self._generate_vol_info(None, None)
        self.fc_driver.create_volume(volume2)

        # FIbre Channel volume type
        extra_spec = {'capabilities:storage_protocol': '<in> FC'}
        vol_type = volume_types.create(self.ctxt, 'FC', extra_spec)

        expected = {'driver_volume_type': 'fibre_channel',
                    'data': {'target_lun': 0,
                             'target_wwn': ['AABBCCDDEEFF0011'],
                             'target_discovered': False}}

        volume1['volume_type_id'] = vol_type['id']
        volume2['volume_type_id'] = vol_type['id']

        ret = self.fc_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNone(ret)

        # Make sure that the volumes have been created
        self._assert_vol_exists(volume1['name'], True)
        self._assert_vol_exists(volume2['name'], True)

        # Initialize connection from the first volume to a host
        ret = self.fc_driver.initialize_connection(
            volume1, self._connector)
        self.assertEqual(expected['driver_volume_type'],
                         ret['driver_volume_type'])
        for k, v in expected['data'].items():
            self.assertEqual(v, ret['data'][k])

        # Initialize again, should notice it and do nothing
        ret = self.fc_driver.initialize_connection(
            volume1, self._connector)
        self.assertEqual(expected['driver_volume_type'],
                         ret['driver_volume_type'])
        for k, v in expected['data'].items():
            self.assertEqual(v, ret['data'][k])

        # Try to delete the 1st volume (should fail because it is mapped)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.fc_driver.delete_volume,
                          volume1)

        # Check bad output from lsfabric for the 2nd volume
        for error in ['remove_field', 'header_mismatch']:
            self.sim.error_injection('lsfabric', error)
            self.assertRaises(exception.VolumeBackendAPIException,
                              self.fc_driver.initialize_connection,
                              volume2, self._connector)

        with mock.patch.object(instorage_common.InStorageAssistant,
                               'get_conn_fc_wwpns') as conn_fc_wwpns:
            conn_fc_wwpns.return_value = []
            ret = self.fc_driver.initialize_connection(volume2,
                                                       self._connector)

        ret = self.fc_driver.terminate_connection(volume1, self._connector)
        # For the first volume detach, ret['data'] should be empty
        # only ret['driver_volume_type'] returned
        self.assertEqual({}, ret['data'])
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        ret = self.fc_driver.terminate_connection(volume2,
                                                  self._connector)
        self.assertEqual('fibre_channel', ret['driver_volume_type'])
        # wwpn is randomly created
        self.assertNotEqual({}, ret['data'])

        ret = self.fc_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNone(ret)

        # Test no preferred node
        self.sim.error_injection('lsvdisk', 'no_pref_node')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.fc_driver.initialize_connection,
                          volume1, self._connector)

        # Initialize connection from the second volume to the host with no
        # preferred node set if in simulation mode, otherwise, just
        # another initialize connection.
        self.sim.error_injection('lsvdisk', 'blank_pref_node')
        self.fc_driver.initialize_connection(volume2, self._connector)

        # Try to remove connection from host that doesn't exist (should fail)
        conn_no_exist = self._connector.copy()
        conn_no_exist['initiator'] = 'i_dont_exist'
        conn_no_exist['wwpns'] = ['0000000000000000']
        self.assertRaises(exception.VolumeDriverException,
                          self.fc_driver.terminate_connection,
                          volume1,
                          conn_no_exist)

        # Try to remove connection from volume that isn't mapped (should print
        # message but NOT fail)
        unmapped_vol = self._generate_vol_info(None, None)
        self.fc_driver.create_volume(unmapped_vol)
        self.fc_driver.terminate_connection(unmapped_vol, self._connector)
        self.fc_driver.delete_volume(unmapped_vol)

        # Remove the mapping from the 1st volume and delete it
        self.fc_driver.terminate_connection(volume1, self._connector)
        self.fc_driver.delete_volume(volume1)
        self._assert_vol_exists(volume1['name'], False)

        # Make sure our host still exists
        host_name = self.fc_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNotNone(host_name)

        # Remove the mapping from the 2nd volume. The host should
        # be automatically removed because there are no more mappings.
        self.fc_driver.terminate_connection(volume2, self._connector)

        # Check if we successfully terminate connections when the host is not
        # specified
        fake_conn = {'ip': '127.0.0.1', 'initiator': 'iqn.fake'}
        self.fc_driver.initialize_connection(volume2, self._connector)
        host_name = self.fc_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNotNone(host_name)
        self.fc_driver.terminate_connection(volume2, fake_conn)
        host_name = self.fc_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNone(host_name)
        self.fc_driver.delete_volume(volume2)
        self._assert_vol_exists(volume2['name'], False)

        # Delete volume types that we created
        volume_types.destroy(ctxt, vol_type['id'])

        ret = (self.fc_driver._assistant.get_host_from_connector(
            self._connector))
        self.assertIsNone(ret)

    def test_instorage_mcs_fc_multi_host_maps(self):
        # Create a volume to be used in mappings
        ctxt = context.get_admin_context()
        volume = self._generate_vol_info(None, None)
        self.fc_driver.create_volume(volume)

        # Create volume types for protocols
        types = {}
        for protocol in ['FC']:
            opts = {'storage_protocol': '<in> ' + protocol}
            types[protocol] = volume_types.create(ctxt, protocol, opts)

        # Create a connector for the second 'host'
        wwpns = ['1234567890123459', '6543210987654324']
        initiator = 'test.initiator.%s' % 123459
        conn2 = {'ip': '1.234.56.79',
                 'host': 'instorage-mcs-test2',
                 'wwpns': wwpns,
                 'initiator': initiator}

        # Check protocols for FC
        volume['volume_type_id'] = types[protocol]['id']

        # Make sure that the volume has been created
        self._assert_vol_exists(volume['name'], True)

        self.fc_driver.initialize_connection(volume, self._connector)
        self.fc_driver.initialize_connection(volume, conn2)

        self.fc_driver.terminate_connection(volume, conn2)
        self.fc_driver.terminate_connection(volume, self._connector)

    def test_add_vdisk_copy_fc(self):
        # Ensure only FC is available
        self.fc_driver._state['enabled_protocols'] = set(['FC'])
        volume = self._generate_vol_info(None, None)
        self.fc_driver.create_volume(volume)
        self.fc_driver.add_vdisk_copy(volume['name'], 'fake-pool', None)
