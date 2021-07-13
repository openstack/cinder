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
"""Tests for the Inspur InStorage volume driver."""

from unittest import mock

from eventlet import greenthread
import six

from cinder import context
import cinder.db
from cinder import exception
from cinder.tests.unit import test
from cinder.tests.unit import utils as testutils
from cinder.tests.unit.volume.drivers.inspur.instorage import fakes
from cinder.volume import configuration as conf
from cinder.volume.drivers.inspur.instorage import instorage_iscsi
from cinder.volume import volume_types


class InStorageMCSISCSIDriverTestCase(test.TestCase):
    def setUp(self):
        super(InStorageMCSISCSIDriverTestCase, self).setUp()
        self.mock_object(greenthread, 'sleep')
        self.iscsi_driver = fakes.FakeInStorageMCSISCSIDriver(
            configuration=conf.Configuration(None))
        self._def_flags = {'san_ip': 'hostname',
                           'san_login': 'user',
                           'san_password': 'pass',
                           'instorage_mcs_volpool_name': ['openstack'],
                           'instorage_mcs_localcopy_timeout': 20,
                           'instorage_mcs_localcopy_rate': 49,
                           'instorage_mcs_allow_tenant_qos': True}
        wwpns = ['1234567890123456', '6543210987654321']
        initiator = 'test.initiator.%s' % 123456
        self._connector = {'ip': '1.234.56.78',
                           'host': 'instorage-mcs-test',
                           'wwpns': wwpns,
                           'initiator': initiator}
        self.sim = fakes.FakeInStorage(['openstack'])

        self.iscsi_driver.set_fake_storage(self.sim)
        self.ctxt = context.get_admin_context()

        self._reset_flags()
        self.ctxt = context.get_admin_context()
        self.db = cinder.db
        self.iscsi_driver.db = self.db
        self.iscsi_driver.do_setup(None)
        self.iscsi_driver.check_for_setup_error()
        self.iscsi_driver._assistant.check_lcmapping_interval = 0

    def _set_flag(self, flag, value):
        group = self.iscsi_driver.configuration.config_group
        self.iscsi_driver.configuration.set_override(flag, value, group)

    def _reset_flags(self):
        self.iscsi_driver.configuration.local_conf.reset()
        for k, v in self._def_flags.items():
            self._set_flag(k, v)

    def _create_volume(self, **kwargs):
        pool = fakes.get_test_pool()
        prop = {'host': 'openstack@mcs#%s' % pool,
                'size': 1,
                'volume_type_id': self.vt['id']}
        for p in prop.keys():
            if p not in kwargs:
                kwargs[p] = prop[p]
        vol = testutils.create_volume(self.ctxt, **kwargs)
        self.iscsi_driver.create_volume(vol)
        return vol

    def _delete_volume(self, volume):
        self.iscsi_driver.delete_volume(volume)
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
        is_vol_defined = self.iscsi_driver._assistant.is_vdisk_defined(name)
        self.assertEqual(exists, is_vol_defined)

    def test_instorage_mcs_iscsi_validate_connector(self):
        conn_neither = {'host': 'host'}
        conn_iscsi = {'host': 'host', 'initiator': 'foo'}
        conn_fc = {'host': 'host', 'wwpns': 'bar'}
        conn_both = {'host': 'host', 'initiator': 'foo', 'wwpns': 'bar'}

        self.iscsi_driver._state['enabled_protocols'] = set(['iSCSI'])
        self.iscsi_driver.validate_connector(conn_iscsi)
        self.iscsi_driver.validate_connector(conn_both)
        self.assertRaises(exception.InvalidConnectorException,
                          self.iscsi_driver.validate_connector, conn_fc)
        self.assertRaises(exception.InvalidConnectorException,
                          self.iscsi_driver.validate_connector, conn_neither)

        self.iscsi_driver._state['enabled_protocols'] = set(['iSCSI', 'FC'])
        self.iscsi_driver.validate_connector(conn_iscsi)
        self.iscsi_driver.validate_connector(conn_both)
        self.assertRaises(exception.InvalidConnectorException,
                          self.iscsi_driver.validate_connector, conn_neither)

    def test_instorage_terminate_iscsi_connection(self):
        # create a iSCSI volume
        volume_iSCSI = self._create_volume()
        extra_spec = {'capabilities:storage_protocol': '<in> iSCSI'}
        vol_type_iSCSI = volume_types.create(self.ctxt, 'iSCSI', extra_spec)
        volume_iSCSI['volume_type_id'] = vol_type_iSCSI['id']

        connector = {'host': 'instorage-mcs-host',
                     'wwnns': ['20000090fa17311e', '20000090fa17311f'],
                     'wwpns': ['ff00000000000000', 'ff00000000000001'],
                     'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aaa'}

        self.iscsi_driver.initialize_connection(volume_iSCSI, connector)
        self.iscsi_driver.terminate_connection(volume_iSCSI, connector)

    @mock.patch.object(instorage_iscsi.InStorageMCSISCSIDriver,
                       '_do_terminate_connection')
    def test_instorage_initialize_iscsi_connection_failure(self, term_conn):
        # create a iSCSI volume
        volume_iSCSI = self._create_volume()
        extra_spec = {'capabilities:storage_protocol': '<in> iSCSI'}
        vol_type_iSCSI = volume_types.create(self.ctxt, 'iSCSI', extra_spec)
        volume_iSCSI['volume_type_id'] = vol_type_iSCSI['id']

        connector = {'host': 'instorage-mcs-host',
                     'wwnns': ['20000090fa17311e', '20000090fa17311f'],
                     'wwpns': ['ff00000000000000', 'ff00000000000001'],
                     'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aaa'}

        self.iscsi_driver._state['storage_nodes'] = {}
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.iscsi_driver.initialize_connection,
                          volume_iSCSI, connector)
        term_conn.assert_called_once_with(volume_iSCSI, connector)

    def test_instorage_initialize_iscsi_connection_multihost(self):
        connector_a = {'host': 'instorage-mcs-host-a',
                       'wwnns': ['20000090fa17311e', '20000090fa17311f'],
                       'wwpns': ['ff00000000000000', 'ff00000000000001'],
                       'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aaa'}
        # host-volume map return value
        exp_path_a = {'driver_volume_type': 'iscsi',
                      'data': {'target_discovered': False,
                               'target_iqn':
                                   'iqn.1982-01.com.inspur:1234.sim.node1',
                               'target_portal': '1.234.56.78:3260',
                               'target_lun': 0,
                               'auth_method': 'CHAP',
                               'discovery_auth_method': 'CHAP'}}

        connector_b = {'host': 'instorage-mcs-host-b',
                       'wwnns': ['30000090fa17311e', '30000090fa17311f'],
                       'wwpns': ['ff00000000000002', 'ff00000000000003'],
                       'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aab'}
        # host-volume map return value
        exp_path_b = {'driver_volume_type': 'iscsi',
                      'data': {'target_discovered': False,
                               'target_iqn':
                                   'iqn.1982-01.com.inspur:1234.sim.node1',
                               'target_portal': '1.234.56.78:3260',
                               'target_lun': 1,
                               'auth_method': 'CHAP',
                               'discovery_auth_method': 'CHAP'}}

        volume_iSCSI = self._create_volume()
        extra_spec = {'capabilities:storage_protocol': '<in> iSCSI'}
        vol_type_iSCSI = volume_types.create(self.ctxt, 'iSCSI', extra_spec)
        volume_iSCSI['volume_type_id'] = vol_type_iSCSI['id']

        # Make sure that the volumes have been created
        self._assert_vol_exists(volume_iSCSI['name'], True)

        # check that the hosts not exist
        ret = self.iscsi_driver._assistant.get_host_from_connector(
            connector_a)
        self.assertIsNone(ret)
        ret = self.iscsi_driver._assistant.get_host_from_connector(
            connector_b)
        self.assertIsNone(ret)

        # Initialize connection to map volume to host a
        ret = self.iscsi_driver.initialize_connection(
            volume_iSCSI, connector_a)
        self.assertEqual(exp_path_a['driver_volume_type'],
                         ret['driver_volume_type'])

        # check host-volume map return value
        for k, v in exp_path_a['data'].items():
            self.assertEqual(v, ret['data'][k])

        ret = self.iscsi_driver._assistant.get_host_from_connector(
            connector_a)
        self.assertIsNotNone(ret)

        # Initialize connection to map volume to host b
        ret = self.iscsi_driver.initialize_connection(
            volume_iSCSI, connector_b)
        self.assertEqual(exp_path_b['driver_volume_type'],
                         ret['driver_volume_type'])

        # check the return value
        for k, v in exp_path_b['data'].items():
            self.assertEqual(v, ret['data'][k])

        ret = self.iscsi_driver._assistant.get_host_from_connector(
            connector_b)
        self.assertIsNotNone(ret)

    def test_instorage_initialize_iscsi_connection_single_path(self):
        # Test the return value for _get_iscsi_properties

        connector = {'host': 'instorage-mcs-host',
                     'wwnns': ['20000090fa17311e', '20000090fa17311f'],
                     'wwpns': ['ff00000000000000', 'ff00000000000001'],
                     'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aaa'}
        # Expected single path host-volume map return value
        exp_s_path = {'driver_volume_type': 'iscsi',
                      'data': {'target_discovered': False,
                               'target_iqn':
                                   'iqn.1982-01.com.inspur:1234.sim.node1',
                               'target_portal': '1.234.56.78:3260',
                               'target_lun': 0,
                               'auth_method': 'CHAP',
                               'discovery_auth_method': 'CHAP'}}

        volume_iSCSI = self._create_volume()
        extra_spec = {'capabilities:storage_protocol': '<in> iSCSI'}
        vol_type_iSCSI = volume_types.create(self.ctxt, 'iSCSI', extra_spec)
        volume_iSCSI['volume_type_id'] = vol_type_iSCSI['id']

        # Make sure that the volumes have been created
        self._assert_vol_exists(volume_iSCSI['name'], True)

        # Check case where no hosts exist
        ret = self.iscsi_driver._assistant.get_host_from_connector(
            connector)
        self.assertIsNone(ret)

        # Initialize connection to map volume to a host
        ret = self.iscsi_driver.initialize_connection(
            volume_iSCSI, connector)
        self.assertEqual(exp_s_path['driver_volume_type'],
                         ret['driver_volume_type'])

        # Check the single path host-volume map return value
        for k, v in exp_s_path['data'].items():
            self.assertEqual(v, ret['data'][k])

        ret = self.iscsi_driver._assistant.get_host_from_connector(
            connector)
        self.assertIsNotNone(ret)

    def test_instorage_initialize_iscsi_connection_multipath(self):
        # Test the return value for _get_iscsi_properties

        connector = {'host': 'instorage-mcs-host',
                     'wwnns': ['20000090fa17311e', '20000090fa17311f'],
                     'wwpns': ['ff00000000000000', 'ff00000000000001'],
                     'initiator': 'iqn.1993-08.org.debian:01:eac5ccc1aaa',
                     'multipath': True}

        # Expected multipath host-volume map return value
        exp_m_path = {'driver_volume_type': 'iscsi',
                      'data': {'target_discovered': False,
                               'target_iqn':
                                   'iqn.1982-01.com.inspur:1234.sim.node1',
                               'target_portal': '1.234.56.78:3260',
                               'target_lun': 0,
                               'target_iqns': [
                                   'iqn.1982-01.com.inspur:1234.sim.node1',
                                   'iqn.1982-01.com.inspur:1234.sim.node1',
                                   'iqn.1982-01.com.inspur:1234.sim.node2'],
                               'target_portals':
                                   ['1.234.56.78:3260',
                                    '1.234.56.80:3260',
                                    '1.234.56.79:3260'],
                               'target_luns': [0, 0, 0],
                               'auth_method': 'CHAP',
                               'discovery_auth_method': 'CHAP'}}

        volume_iSCSI = self._create_volume()
        extra_spec = {'capabilities:storage_protocol': '<in> iSCSI'}
        vol_type_iSCSI = volume_types.create(self.ctxt, 'iSCSI', extra_spec)
        volume_iSCSI['volume_type_id'] = vol_type_iSCSI['id']

        # Check case where no hosts exist
        ret = self.iscsi_driver._assistant.get_host_from_connector(
            connector)
        self.assertIsNone(ret)

        # Initialize connection to map volume to a host
        ret = self.iscsi_driver.initialize_connection(
            volume_iSCSI, connector)
        self.assertEqual(exp_m_path['driver_volume_type'],
                         ret['driver_volume_type'])

        # Check the multipath host-volume map return value
        for k, v in exp_m_path['data'].items():
            if k in ('target_iqns', 'target_portals'):
                # These are randomly ordered lists
                six.assertCountEqual(self, v, ret['data'][k])
            else:
                self.assertEqual(v, ret['data'][k])

        ret = self.iscsi_driver._assistant.get_host_from_connector(
            connector)
        self.assertIsNotNone(ret)

    def test_instorage_mcs_iscsi_host_maps(self):
        # Create two volumes to be used in mappings

        ctxt = context.get_admin_context()
        volume1 = self._generate_vol_info(None, None)
        self.iscsi_driver.create_volume(volume1)
        volume2 = self._generate_vol_info(None, None)
        self.iscsi_driver.create_volume(volume2)

        # Create volume types that we created
        types = {}
        for protocol in ['iSCSI']:
            opts = {'storage_protocol': '<in> ' + protocol}
            types[protocol] = volume_types.create(ctxt, protocol, opts)

        expected = {'iSCSI': {'driver_volume_type': 'iscsi',
                              'data': {'target_discovered': False,
                                       'target_iqn':
                                       'iqn.1982-01.com.inspur:1234.sim.node1',
                                       'target_portal': '1.234.56.78:3260',
                                       'target_lun': 0,
                                       'auth_method': 'CHAP',
                                       'discovery_auth_method': 'CHAP'}}}

        volume1['volume_type_id'] = types[protocol]['id']
        volume2['volume_type_id'] = types[protocol]['id']

        # Check case where no hosts exist
        ret = self.iscsi_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNone(ret)

        # Make sure that the volumes have been created
        self._assert_vol_exists(volume1['name'], True)
        self._assert_vol_exists(volume2['name'], True)

        # Initialize connection from the first volume to a host
        ret = self.iscsi_driver.initialize_connection(
            volume1, self._connector)
        self.assertEqual(expected[protocol]['driver_volume_type'],
                         ret['driver_volume_type'])
        for k, v in expected[protocol]['data'].items():
            self.assertEqual(v, ret['data'][k])

        # Initialize again, should notice it and do nothing
        ret = self.iscsi_driver.initialize_connection(
            volume1, self._connector)
        self.assertEqual(expected[protocol]['driver_volume_type'],
                         ret['driver_volume_type'])
        for k, v in expected[protocol]['data'].items():
            self.assertEqual(v, ret['data'][k])

        # Try to delete the 1st volume (should fail because it is mapped)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.iscsi_driver.delete_volume,
                          volume1)

        ret = self.iscsi_driver.terminate_connection(volume1,
                                                     self._connector)
        ret = self.iscsi_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNone(ret)

        # Check cases with no auth set for host
        for auth_enabled in [True, False]:
            for host_exists in ['yes-auth', 'yes-noauth', 'no']:
                self._set_flag('instorage_mcs_iscsi_chap_enabled',
                               auth_enabled)
                case = 'en' + six.text_type(
                    auth_enabled) + 'ex' + six.text_type(host_exists)
                conn_na = {'initiator': 'test:init:%s' % 56789,
                           'ip': '11.11.11.11',
                           'host': 'host-%s' % case}
                if host_exists.startswith('yes'):
                    self.sim._add_host_to_list(conn_na)
                    if host_exists == 'yes-auth':
                        kwargs = {'chapsecret': 'foo',
                                  'obj': conn_na['host']}
                        self.sim._cmd_chhost(**kwargs)
                volume1['volume_type_id'] = types['iSCSI']['id']

                init_ret = self.iscsi_driver.initialize_connection(volume1,
                                                                   conn_na)
                host_name = self.sim._host_in_list(conn_na['host'])
                chap_ret = (
                    self.iscsi_driver._assistant.get_chap_secret_for_host(
                        host_name))
                if auth_enabled or host_exists == 'yes-auth':
                    self.assertIn('auth_password', init_ret['data'])
                    self.assertIsNotNone(chap_ret)
                else:
                    self.assertNotIn('auth_password', init_ret['data'])
                    self.assertIsNone(chap_ret)
                self.iscsi_driver.terminate_connection(volume1, conn_na)
        self._set_flag('instorage_mcs_iscsi_chap_enabled', True)

        # Test no preferred node
        self.sim.error_injection('lsvdisk', 'no_pref_node')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.iscsi_driver.initialize_connection,
                          volume1, self._connector)

        # Initialize connection from the second volume to the host with no
        # preferred node set if in simulation mode, otherwise, just
        # another initialize connection.
        self.sim.error_injection('lsvdisk', 'blank_pref_node')
        self.iscsi_driver.initialize_connection(volume2, self._connector)

        # Try to remove connection from host that doesn't exist (should fail)
        conn_no_exist = self._connector.copy()
        conn_no_exist['initiator'] = 'i_dont_exist'
        conn_no_exist['wwpns'] = ['0000000000000000']
        self.assertRaises(exception.VolumeDriverException,
                          self.iscsi_driver.terminate_connection,
                          volume1,
                          conn_no_exist)

        # Try to remove connection from volume that isn't mapped (should print
        # message but NOT fail)
        unmapped_vol = self._generate_vol_info(None, None)
        self.iscsi_driver.create_volume(unmapped_vol)
        self.iscsi_driver.terminate_connection(unmapped_vol, self._connector)
        self.iscsi_driver.delete_volume(unmapped_vol)

        # Remove the mapping from the 1st volume and delete it
        self.iscsi_driver.terminate_connection(volume1, self._connector)
        self.iscsi_driver.delete_volume(volume1)
        self._assert_vol_exists(volume1['name'], False)

        # Make sure our host still exists
        host_name = self.iscsi_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNotNone(host_name)

        # Remove the mapping from the 2nd volume. The host should
        # be automatically removed because there are no more mappings.
        self.iscsi_driver.terminate_connection(volume2, self._connector)

        # Check if we successfully terminate connections when the host is not
        # specified
        fake_conn = {'ip': '127.0.0.1', 'initiator': 'iqn.fake'}
        self.iscsi_driver.initialize_connection(volume2, self._connector)
        host_name = self.iscsi_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNotNone(host_name)
        self.iscsi_driver.terminate_connection(volume2, fake_conn)
        host_name = self.iscsi_driver._assistant.get_host_from_connector(
            self._connector)
        self.assertIsNone(host_name)
        self.iscsi_driver.delete_volume(volume2)
        self._assert_vol_exists(volume2['name'], False)

        # Delete volume types that we created
        for protocol in ['iSCSI']:
            volume_types.destroy(ctxt, types[protocol]['id'])

        # Check if our host still exists (it should not)
        ret = (self.iscsi_driver._assistant.get_host_from_connector(
            self._connector))
        self.assertIsNone(ret)

    def test_add_vdisk_copy_iscsi(self):
        # Ensure only iSCSI is available
        self.iscsi_driver._state['enabled_protocols'] = set(['iSCSI'])
        volume = self._generate_vol_info(None, None)
        self.iscsi_driver.create_volume(volume)
        self.iscsi_driver.add_vdisk_copy(volume['name'], 'fake-pool', None)
