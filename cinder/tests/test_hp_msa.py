#    (c) Copyright 2014 Objectif Libre
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

"""Unit tests for OpenStack Cinder HP MSA driver."""

import urllib2

import lxml.etree as etree
import mock

from cinder import exception
from cinder import test
from cinder.volume.drivers.san.hp import hp_msa_client as msa
from cinder.volume.drivers.san.hp import hp_msa_common
from cinder.volume.drivers.san.hp import hp_msa_fc


session_key = 'JSESS0004eb8a82b08fd5'
resp_login = '''<RESPONSE><OBJECT basetype="status" name="status" oid="1">
             <PROPERTY name="response-type">success</PROPERTY>
             <PROPERTY name="response-type-numeric">0</PROPERTY>
             <PROPERTY name="response">JSESS0004eb8a82b08fd5</PROPERTY>
             <PROPERTY name="return-code">1</PROPERTY></OBJECT></RESPONSE>'''
resp_badlogin = '''<RESPONSE><OBJECT basetype="status" name="status" oid="1">
                </OBJECT></RESPONSE>'''

response_ok = '''<RESPONSE><OBJECT basetype="status" name="status" oid="1">
              <PROPERTY name="response">some data</PROPERTY>
              <PROPERTY name="return-code">0</PROPERTY></OBJECT></RESPONSE>'''
response_not_ok = '''<RESPONSE><OBJECT basetype="status" name="status" oid="1">
                  <PROPERTY name="response">Error Message</PROPERTY>
                  <PROPERTY name="return-code">1</PROPERTY>
                  </OBJECT></RESPONSE>'''
response_stats = '''<RESPONSE><OBJECT basetype="virtual-disks">
                 <PROPERTY name="size-numeric">1756381184</PROPERTY>
                 <PROPERTY name="freespace-numeric">756381184</PROPERTY>
                 </OBJECT></RESPONSE>'''
response_no_lun = '''<RESPONSE></RESPONSE>'''
response_lun = '''<RESPONSE><OBJECT basetype="host-view-mappings">
               <PROPERTY name="lun">1</PROPERTY></OBJECT>
               <OBJECT basetype="host-view-mappings">
               <PROPERTY name="lun">3</PROPERTY></OBJECT></RESPONSE>'''
response_ports = '''<RESPONSE><OBJECT basetype="port">
                 <PROPERTY name="port-type">FC</PROPERTY>
                 <PROPERTY name="target-id">id1</PROPERTY>
                 <PROPERTY name="status">Up</PROPERTY></OBJECT>
                 <OBJECT basetype="port">
                 <PROPERTY name="port-type">FC</PROPERTY>
                 <PROPERTY name="target-id">id2</PROPERTY>
                 <PROPERTY name="status">Disconnected</PROPERTY></OBJECT>
                 <OBJECT basetype="port">
                 <PROPERTY name="port-type">iSCSI</PROPERTY>
                 <PROPERTY name="target-id">id3</PROPERTY>
                 <PROPERTY name="status">Up</PROPERTY></OBJECT></RESPONSE>'''
invalid_xml = '''<RESPONSE></RESPONSE>'''
malformed_xml = '''<RESPONSE>'''
fake_xml = '''<fakexml></fakexml>'''

stats_low_space = {'free_capacity_gb': 10, 'total_capacity_gb': 100}
stats_large_space = {'free_capacity_gb': 90, 'total_capacity_gb': 100}

vol_id = 'ecffc30f-98cb-4cf5-85ee-d7309cc17cd2'
test_volume = {'id': vol_id,
               'display_name': 'test volume', 'name': 'volume', 'size': 10}
test_snap = {'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'volume_id': vol_id,
             'display_name': 'test volume', 'name': 'volume', 'size': 10}
encoded_volid = 'v7P_DD5jLTPWF7tcwnMF'
encoded_snapid = 's7P_DD5jLTPWF7tcwnMF'
dest_volume = {'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
               'source_volid': vol_id,
               'display_name': 'test volume', 'name': 'volume', 'size': 10}
attached_volume = {'id': vol_id,
                   'display_name': 'test volume', 'name': 'volume',
                   'size': 10, 'status': 'in-use',
                   'attach_status': 'attached'}
attaching_volume = {'id': vol_id,
                    'display_name': 'test volume', 'name': 'volume',
                    'size': 10, 'status': 'attaching',
                    'attach_status': 'attached'}
detached_volume = {'id': vol_id,
                   'display_name': 'test volume', 'name': 'volume',
                   'size': 10, 'status': 'available',
                   'attach_status': 'detached'}

connector = {'ip': '10.0.0.2',
             'initiator': 'iqn.1993-08.org.debian:01:222',
             'wwpns': ["111111111111111", "111111111111112"],
             'wwnns': ["211111111111111", "211111111111112"],
             'host': 'fakehost'}
invalid_connector = {'ip': '10.0.0.2',
                     'initiator': 'iqn.1993-08.org.debian:01:222',
                     'wwpns': [],
                     'wwnns': [],
                     'host': 'fakehost'}


class TestHPMSAClient(test.TestCase):
    def setUp(self):
        super(TestHPMSAClient, self).setUp()
        self.login = 'manage'
        self.passwd = '!manage'
        self.ip = '10.0.0.1'
        self.client = msa.HPMSAClient(self.ip, self.login, self.passwd)

    @mock.patch('urllib2.urlopen')
    def test_login(self, mock_url_open):
        m = mock.Mock()
        m.read.side_effect = [resp_login]
        mock_url_open.return_value = m
        self.client.login()
        self.assertEqual(self.client._session_key, session_key)

        m.read.side_effect = [resp_badlogin]
        self.assertRaises(msa.HPMSAAuthenticationError,
                          self.client.login)

    def test_build_request_url(self):
        url = self.client._build_request_url('/path', None)
        self.assertEqual(url, 'http://10.0.0.1/api/path')
        url = self.client._build_request_url('/path', None, arg1='val1')
        self.assertEqual(url, 'http://10.0.0.1/api/path/arg1/val1')
        url = self.client._build_request_url('/path', 'arg1')
        self.assertEqual(url, 'http://10.0.0.1/api/path/arg1')
        url = self.client._build_request_url('/path', 'arg1', arg2='val2')
        self.assertEqual(url, 'http://10.0.0.1/api/path/arg2/val2/arg1')
        url = self.client._build_request_url('/path', ['arg1', 'arg3'],
                                             arg2='val2')
        self.assertEqual(url, 'http://10.0.0.1/api/path/arg2/val2/arg1/arg3')

    @mock.patch('urllib2.urlopen')
    def test_request(self, mock_url_open):
        self.client._session_key = session_key

        m = mock.Mock()
        m.read.side_effect = [response_ok, malformed_xml,
                              urllib2.URLError("error")]
        mock_url_open.return_value = m
        ret = self.client._request('/path', None)
        self.assertTrue(type(ret) == etree._Element)
        self.assertRaises(msa.HPMSAConnectionError, self.client._request,
                          '/path', None)
        self.assertRaises(msa.HPMSAConnectionError, self.client._request,
                          '/path', None)

    def test_assert_response_ok(self):
        ok_tree = etree.XML(response_ok)
        not_ok_tree = etree.XML(response_not_ok)
        invalid_tree = etree.XML(invalid_xml)
        ret = self.client._assert_response_ok(ok_tree)
        self.assertEqual(ret, None)
        self.assertRaises(msa.HPMSARequestError,
                          self.client._assert_response_ok, not_ok_tree)
        self.assertRaises(msa.HPMSARequestError,
                          self.client._assert_response_ok, invalid_tree)

    @mock.patch.object(msa.HPMSAClient, '_request')
    def test_vdisk_exists(self, mock_request):
        mock_request.side_effect = [msa.HPMSARequestError,
                                    fake_xml]

        self.assertEqual(self.client.vdisk_exists('vdisk'), False)
        self.assertEqual(self.client.vdisk_exists('vdisk'), True)

    @mock.patch.object(msa.HPMSAClient, '_request')
    def test_vdisk_stats(self, mock_request):
        mock_request.return_value = etree.XML(response_stats)
        ret = self.client.vdisk_stats('OpenStack')
        self.assertEqual(ret, {'free_capacity_gb': 387,
                               'total_capacity_gb': 899})
        mock_request.assert_called_with('/show/vdisks', 'OpenStack')

    @mock.patch.object(msa.HPMSAClient, '_request')
    def test_get_lun(self, mock_request):
        mock_request.side_effect = [etree.XML(response_no_lun),
                                    etree.XML(response_lun)]
        ret = self.client._get_first_available_lun_for_host("fakehost")
        self.assertEqual(ret, 1)
        ret = self.client._get_first_available_lun_for_host("fakehost")
        self.assertEqual(ret, 2)

    @mock.patch.object(msa.HPMSAClient, '_request')
    def test_get_ports(self, mock_request):
        mock_request.side_effect = [etree.XML(response_ports)]
        ret = self.client.get_active_target_ports()
        self.assertEqual(ret, [{'port-type': 'FC',
                                'target-id': 'id1',
                                'status': 'Up'},
                               {'port-type': 'iSCSI',
                                'target-id': 'id3',
                                'status': 'Up'}])

    @mock.patch.object(msa.HPMSAClient, '_request')
    def test_get_fc_ports(self, mock_request):
        mock_request.side_effect = [etree.XML(response_ports)]
        ret = self.client.get_active_fc_target_ports()
        self.assertEqual(ret, ['id1'])


class FakeConfiguration(object):
    msa_vdisk = 'OpenStack'
    san_ip = '10.0.0.1'
    san_login = 'manage'
    san_password = '!manage'

    def safe_get(self, key):
        return 'fakevalue'


class TestHPMSACommon(test.TestCase):
    def setUp(self):
        super(TestHPMSACommon, self).setUp()
        self.config = FakeConfiguration()
        self.common = hp_msa_common.HPMSACommon(self.config)

    @mock.patch.object(msa.HPMSAClient, 'vdisk_exists')
    @mock.patch.object(msa.HPMSAClient, 'logout')
    @mock.patch.object(msa.HPMSAClient, 'login')
    def test_do_setup(self, mock_login, mock_logout, mock_vdisk_exists):
        mock_login.side_effect = [msa.HPMSAConnectionError,
                                  msa.HPMSAAuthenticationError,
                                  None, None]
        mock_vdisk_exists.side_effect = [False, True]
        mock_logout.return_value = None

        self.assertRaises(exception.HPMSAConnectionError,
                          self.common.do_setup, None)
        self.assertRaises(exception.HPMSAConnectionError,
                          self.common.do_setup, None)
        self.assertRaises(exception.HPMSAInvalidVDisk, self.common.do_setup,
                          None)
        mock_vdisk_exists.assert_called_with(self.config.msa_vdisk)
        self.assertEqual(self.common.do_setup(None), None)
        mock_vdisk_exists.assert_called_with(self.config.msa_vdisk)
        mock_logout.assert_called_with()

    def test_vol_name(self):
        self.assertEqual(self.common._get_vol_name(vol_id), encoded_volid)
        self.assertEqual(self.common._get_snap_name(vol_id),
                         encoded_snapid)

    def test_check_flags(self):
        class FakeOptions():
            def __init__(self, d):
                for k, v in d.items():
                    self.__dict__[k] = v

        options = FakeOptions({'opt1': 'val1', 'opt2': 'val2'})
        required_flags = ['opt1', 'opt2']
        ret = self.common.check_flags(options, required_flags)
        self.assertEqual(ret, None)

        options = FakeOptions({'opt1': 'val1', 'opt3': 'val3'})
        required_flags = ['opt1', 'opt2']
        self.assertEqual(ret, None)

        options = FakeOptions({'opt1': 'val1', 'opt2': 'val2'})
        required_flags = ['opt1', 'opt2', 'opt3']
        self.assertRaises(exception.Invalid, self.common.check_flags,
                          options, required_flags)

    def test_assert_connector_ok(self):
        self.assertRaises(exception.InvalidInput,
                          self.common._assert_connector_ok, invalid_connector)
        self.assertIsNone(self.common._assert_connector_ok(connector))

    @mock.patch.object(msa.HPMSAClient, 'vdisk_stats')
    def test_update_volume_stats(self, mock_stats):
        mock_stats.side_effect = [msa.HPMSARequestError,
                                  stats_large_space]

        self.assertRaises(exception.Invalid, self.common._update_volume_stats)
        mock_stats.assert_called_with(self.config.msa_vdisk)
        ret = self.common._update_volume_stats()
        self.assertEqual(ret, None)
        self.assertEqual(self.common.stats,
                         {'storage_protocol': None,
                          'vendor_name': 'Hewlett-Packard',
                          'driver_version': self.common.VERSION,
                          'volume_backend_name': None,
                          'free_capacity_gb': 90,
                          'reserved_percentage': 0,
                          'total_capacity_gb': 100,
                          'QoS_support': False})

    @mock.patch.object(msa.HPMSAClient, 'create_volume')
    def test_create_volume(self, mock_create):
        mock_create.side_effect = [msa.HPMSARequestError, None]

        self.assertRaises(exception.Invalid, self.common.create_volume,
                          test_volume)
        ret = self.common.create_volume(test_volume)
        self.assertEqual(ret, None)
        mock_create.assert_called_with(self.common.config.msa_vdisk,
                                       encoded_volid,
                                       "%sGB" % test_volume['size'])

    @mock.patch.object(msa.HPMSAClient, 'delete_volume')
    def test_delete_volume(self, mock_delete):
        not_found_e = msa.HPMSARequestError(
            'The volume was not found on this system.')
        mock_delete.side_effect = [not_found_e, msa.HPMSARequestError,
                                   None]

        self.assertEqual(self.common.delete_volume(test_volume), None)
        self.assertRaises(exception.Invalid, self.common.delete_volume,
                          test_volume)
        self.assertEqual(self.common.delete_volume(test_volume), None)
        mock_delete.assert_called_with(encoded_volid)

    @mock.patch.object(msa.HPMSAClient, 'copy_volume')
    @mock.patch.object(msa.HPMSAClient, 'vdisk_stats')
    def test_create_cloned_volume(self, mock_stats, mock_copy):
        mock_stats.side_effect = [stats_low_space, stats_large_space,
                                  stats_large_space]

        self.assertRaises(exception.HPMSANotEnoughSpace,
                          self.common.create_cloned_volume,
                          dest_volume, detached_volume)
        self.assertFalse(mock_copy.called)

        mock_copy.side_effect = [msa.HPMSARequestError, None]
        self.assertRaises(exception.Invalid,
                          self.common.create_cloned_volume,
                          dest_volume, detached_volume)

        ret = self.common.create_cloned_volume(dest_volume, detached_volume)
        self.assertEqual(ret, None)

        mock_copy.assert_called_with(encoded_volid,
                                     'vqqqqqqqqqqqqqqqqqqq',
                                     self.common.config.msa_vdisk)

    @mock.patch.object(msa.HPMSAClient, 'copy_volume')
    @mock.patch.object(msa.HPMSAClient, 'vdisk_stats')
    def test_create_volume_from_snapshot(self, mock_stats, mock_copy):
        mock_stats.side_effect = [stats_low_space, stats_large_space,
                                  stats_large_space]

        self.assertRaises(exception.HPMSANotEnoughSpace,
                          self.common.create_volume_from_snapshot,
                          dest_volume, test_snap)

        mock_copy.side_effect = [msa.HPMSARequestError, None]
        self.assertRaises(exception.Invalid,
                          self.common.create_volume_from_snapshot,
                          dest_volume, test_snap)

        ret = self.common.create_volume_from_snapshot(dest_volume, test_snap)
        self.assertEqual(ret, None)
        mock_copy.assert_called_with('sqqqqqqqqqqqqqqqqqqq',
                                     'vqqqqqqqqqqqqqqqqqqq',
                                     self.common.config.msa_vdisk)

    @mock.patch.object(msa.HPMSAClient, 'extend_volume')
    def test_extend_volume(self, mock_extend):
        mock_extend.side_effect = [msa.HPMSARequestError, None]

        self.assertRaises(exception.Invalid, self.common.extend_volume,
                          test_volume, 20)
        ret = self.common.extend_volume(test_volume, 20)
        self.assertEqual(ret, None)
        mock_extend.assert_called_with(encoded_volid, '10GB')

    @mock.patch.object(msa.HPMSAClient, 'create_snapshot')
    def test_create_snapshot(self, mock_create):
        mock_create.side_effect = [msa.HPMSARequestError, None]

        self.assertRaises(exception.Invalid, self.common.create_snapshot,
                          test_snap)
        ret = self.common.create_snapshot(test_snap)
        self.assertEqual(ret, None)
        mock_create.assert_called_with(encoded_volid, 'sqqqqqqqqqqqqqqqqqqq')

    @mock.patch.object(msa.HPMSAClient, 'delete_snapshot')
    def test_delete_snapshot(self, mock_delete):
        not_found_e = msa.HPMSARequestError(
            'The volume was not found on this system.')
        mock_delete.side_effect = [not_found_e, msa.HPMSARequestError,
                                   None]

        self.assertEqual(self.common.delete_snapshot(test_snap), None)
        self.assertRaises(exception.Invalid, self.common.delete_snapshot,
                          test_snap)
        self.assertEqual(self.common.delete_snapshot(test_snap), None)
        mock_delete.assert_called_with('sqqqqqqqqqqqqqqqqqqq')

    @mock.patch.object(msa.HPMSAClient, 'map_volume')
    def test_map_volume(self, mock_map):
        mock_map.side_effect = [msa.HPMSARequestError, 10]

        self.assertRaises(exception.Invalid, self.common.map_volume,
                          test_volume, connector)
        lun = self.common.map_volume(test_volume, connector)
        self.assertEqual(lun, 10)
        mock_map.assert_called_with(encoded_volid, connector['wwpns'])

    @mock.patch.object(msa.HPMSAClient, 'unmap_volume')
    def test_unmap_volume(self, mock_unmap):
        mock_unmap.side_effect = [msa.HPMSARequestError, None]

        self.assertRaises(exception.Invalid, self.common.unmap_volume,
                          test_volume, connector)
        ret = self.common.unmap_volume(test_volume, connector)
        self.assertEqual(ret, None)
        mock_unmap.assert_called_with(encoded_volid, connector['wwpns'])


class TestHPMSAFC(test.TestCase):
    @mock.patch.object(hp_msa_common.HPMSACommon, 'do_setup')
    def setUp(self, mock_setup):
        super(TestHPMSAFC, self).setUp()

        mock_setup.return_value = True

        def fake_init(self, *args, **kwargs):
            super(hp_msa_fc.HPMSAFCDriver, self).__init__()
            self.common = None
            self.configuration = FakeConfiguration()

        hp_msa_fc.HPMSAFCDriver.__init__ = fake_init
        self.driver = hp_msa_fc.HPMSAFCDriver()
        self.driver.do_setup(None)
        self.driver.common.client_login = mock.MagicMock(return_value=None)
        self.driver.common.client_logout = mock.MagicMock(return_value=None)

    def _test_with_mock(self, mock, method, args, expected=None):
        func = getattr(self.driver, method)
        mock.side_effect = [exception.Invalid(), None]
        self.assertRaises(exception.Invalid, func, *args)
        self.assertEqual(expected, func(*args))

    @mock.patch.object(hp_msa_common.HPMSACommon, 'create_volume')
    def test_create_volume(self, mock_create):
        self._test_with_mock(mock_create, 'create_volume', [None],
                             {'metadata': None})

    @mock.patch.object(hp_msa_common.HPMSACommon,
                       'create_cloned_volume')
    def test_create_cloned_volume(self, mock_create):
        self._test_with_mock(mock_create, 'create_cloned_volume', [None, None],
                             {'metadata': None})

    @mock.patch.object(hp_msa_common.HPMSACommon,
                       'create_volume_from_snapshot')
    def test_create_volume_from_snapshot(self, mock_create):
        self._test_with_mock(mock_create, 'create_volume_from_snapshot',
                             [None, None], None)

    @mock.patch.object(hp_msa_common.HPMSACommon, 'delete_volume')
    def test_delete_volume(self, mock_delete):
        self._test_with_mock(mock_delete, 'delete_volume', [None])

    @mock.patch.object(hp_msa_common.HPMSACommon, 'create_snapshot')
    def test_create_snapshot(self, mock_create):
        self._test_with_mock(mock_create, 'create_snapshot', [None])

    @mock.patch.object(hp_msa_common.HPMSACommon, 'delete_snapshot')
    def test_delete_snapshot(self, mock_delete):
        self._test_with_mock(mock_delete, 'delete_snapshot', [None])

    @mock.patch.object(hp_msa_common.HPMSACommon, 'extend_volume')
    def test_extend_volume(self, mock_extend):
        self._test_with_mock(mock_extend, 'extend_volume', [None, 10])

    @mock.patch.object(hp_msa_common.HPMSACommon, 'client_logout')
    @mock.patch.object(hp_msa_common.HPMSACommon,
                       'get_active_fc_target_ports')
    @mock.patch.object(hp_msa_common.HPMSACommon, 'map_volume')
    @mock.patch.object(hp_msa_common.HPMSACommon, 'client_login')
    def test_initialize_connection(self, mock_login, mock_map, mock_ports,
                                   mock_logout):
        mock_login.return_value = None
        mock_logout.return_value = None
        mock_map.side_effect = [exception.Invalid, 1]
        mock_ports.side_effect = [['id1']]

        self.assertRaises(exception.Invalid,
                          self.driver.initialize_connection, test_volume,
                          connector)
        mock_map.assert_called_with(test_volume, connector)

        ret = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(ret, {'driver_volume_type': 'fibre_channel',
                               'data': {'target_wwn': ['id1'],
                                        'target_lun': 1,
                                        'target_discovered': True}})
        mock_ports.assert_called_once()

    @mock.patch.object(hp_msa_common.HPMSACommon, 'client_logout')
    @mock.patch.object(hp_msa_common.HPMSACommon, 'unmap_volume')
    @mock.patch.object(hp_msa_common.HPMSACommon, 'client_login')
    def test_terminate_connection(self, mock_login, mock_unmap, mock_logout):
        mock_login.return_value = None
        mock_logout.return_value = None
        mock_unmap.side_effect = [exception.Invalid, 1]

        self.assertRaises(exception.Invalid,
                          self.driver.terminate_connection, test_volume,
                          connector)
        mock_unmap.assert_called_with(test_volume, connector)

        ret = self.driver.terminate_connection(test_volume, connector)
        self.assertEqual(ret, None)

    @mock.patch.object(hp_msa_common.HPMSACommon, 'client_logout')
    @mock.patch.object(hp_msa_common.HPMSACommon, 'get_volume_stats')
    @mock.patch.object(hp_msa_common.HPMSACommon, 'client_login')
    def test_get_volume_stats(self, mock_login, mock_stats, mock_logout):
        stats = {'storage_protocol': None,
                 'driver_version': self.driver.VERSION,
                 'volume_backend_name': None,
                 'free_capacity_gb': 90,
                 'reserved_percentage': 0,
                 'total_capacity_gb': 100,
                 'QoS_support': False}
        mock_stats.side_effect = [exception.Invalid, stats, stats]

        self.assertRaises(exception.Invalid, self.driver.get_volume_stats,
                          False)
        ret = self.driver.get_volume_stats(False)
        self.assertEqual(ret, {'storage_protocol': 'FC',
                               'driver_version': self.driver.VERSION,
                               'volume_backend_name': 'fakevalue',
                               'free_capacity_gb': 90,
                               'reserved_percentage': 0,
                               'total_capacity_gb': 100,
                               'QoS_support': False})

        ret = self.driver.get_volume_stats(True)
        self.assertEqual(ret, {'storage_protocol': 'FC',
                               'driver_version': self.driver.VERSION,
                               'volume_backend_name': 'fakevalue',
                               'free_capacity_gb': 90,
                               'reserved_percentage': 0,
                               'total_capacity_gb': 100,
                               'QoS_support': False})
        mock_stats.assert_called_with(True)
