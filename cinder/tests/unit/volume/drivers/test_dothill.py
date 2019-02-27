#    Copyright 2014 Objectif Libre
#    Copyright 2015 DotHill Systems
#    Copyright 2016 Seagate Technology or one of its affiliates
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
"""Unit tests for OpenStack Cinder DotHill driver."""

from defusedxml import lxml as etree
import mock
import requests

from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.volume.drivers.dothill import dothill_client as dothill
from cinder.volume.drivers.dothill import dothill_common
from cinder.volume.drivers.dothill import dothill_fc
from cinder.volume.drivers.dothill import dothill_iscsi
from cinder.zonemanager import utils as fczm_utils

session_key = '12a1626754554a21d85040760c81b'
resp_login = '''<RESPONSE><OBJECT basetype="status" name="status" oid="1">
             <PROPERTY name="response-type">success</PROPERTY>
             <PROPERTY name="response-type-numeric">0</PROPERTY>
             <PROPERTY name="response">12a1626754554a21d85040760c81b</PROPERTY>
             <PROPERTY name="return-code">1</PROPERTY></OBJECT></RESPONSE>'''

resp_fw_ti = '''<RESPONSE><PROPERTY name="sc-fw">T252R07</PROPERTY>
                       <PROPERTY name="return-code">0</PROPERTY></RESPONSE>'''

resp_fw = '''<RESPONSE><PROPERTY name="sc-fw">GLS220R001</PROPERTY>
                       <PROPERTY name="return-code">0</PROPERTY></RESPONSE>'''

resp_system = '''<RESPONSE>
             <PROPERTY name="midplane-serial-number">00C0FFEEEEEE</PROPERTY>
             <PROPERTY name="return-code">0</PROPERTY>
                 </RESPONSE>'''

resp_badlogin = '''<RESPONSE><OBJECT basetype="status" name="status" oid="1">
             <PROPERTY name="response-type">error</PROPERTY>
             <PROPERTY name="response-type-numeric">1</PROPERTY>
             <PROPERTY name="response">Authentication failure</PROPERTY>
             <PROPERTY name="return-code">1</PROPERTY></OBJECT></RESPONSE>'''
response_ok = '''<RESPONSE><OBJECT basetype="status" name="status" oid="1">
              <PROPERTY name="response">some data</PROPERTY>
              <PROPERTY name="return-code">0</PROPERTY>
              </OBJECT></RESPONSE>'''
response_not_ok = '''<RESPONSE><OBJECT basetype="status" name="status" oid="1">
                  <PROPERTY name="response">Error Message</PROPERTY>
                  <PROPERTY name="return-code">1</PROPERTY>
                  </OBJECT></RESPONSE>'''
response_stats_linear = '''<RESPONSE><OBJECT basetype="virtual-disks">
                    <PROPERTY name="size-numeric">3863830528</PROPERTY>
                    <PROPERTY name="freespace-numeric">3863830528</PROPERTY>
                    </OBJECT></RESPONSE>'''
response_stats_virtual = '''<RESPONSE><OBJECT basetype="pools">
                <PROPERTY name="total-size-numeric">3863830528</PROPERTY>
                <PROPERTY name="total-avail-numeric">3863830528</PROPERTY>
                </OBJECT></RESPONSE>'''
response_no_lun = '''<RESPONSE></RESPONSE>'''
response_lun = '''<RESPONSE><OBJECT basetype="host-view-mappings">
               <PROPERTY name="lun">1</PROPERTY></OBJECT>
               <OBJECT basetype="host-view-mappings">
               <PROPERTY name="lun">4</PROPERTY></OBJECT></RESPONSE>'''
response_ports = '''<RESPONSE>
                 <OBJECT basetype="port">
                 <PROPERTY name="port-type">FC</PROPERTY>
                 <PROPERTY name="target-id">id1</PROPERTY>
                 <PROPERTY name="status">Disconnected</PROPERTY></OBJECT>
                 <OBJECT basetype="port">
                 <PROPERTY name="port-type">FC</PROPERTY>
                 <PROPERTY name="target-id">id2</PROPERTY>
                 <PROPERTY name="status">Up</PROPERTY></OBJECT>
                 <OBJECT basetype="port">
                 <PROPERTY name="port-type">iSCSI</PROPERTY>
                 <PROPERTY name="target-id">id3</PROPERTY>
                 <PROPERTY name="%(ip)s" >10.0.0.10</PROPERTY>
                 <PROPERTY name="status">Disconnected</PROPERTY></OBJECT>
                 <OBJECT basetype="port">
                 <PROPERTY name="port-type">iSCSI</PROPERTY>
                 <PROPERTY name="target-id">id4</PROPERTY>
                 <PROPERTY name="%(ip)s" >10.0.0.11</PROPERTY>
                 <PROPERTY name="status">Up</PROPERTY></OBJECT>
                 <OBJECT basetype="port">
                 <PROPERTY name="port-type">iSCSI</PROPERTY>
                 <PROPERTY name="target-id">id5</PROPERTY>
                 <PROPERTY name="%(ip)s" >10.0.0.12</PROPERTY>
                 <PROPERTY name="status">Up</PROPERTY></OBJECT>
                 </RESPONSE>'''

response_ports_linear = response_ports % {'ip': 'primary-ip-address'}
response_ports_virtual = response_ports % {'ip': 'ip-address'}


invalid_xml = '''<RESPONSE></RESPONSE>'''
malformed_xml = '''<RESPONSE>'''
fake_xml = '''<fakexml></fakexml>'''

stats_low_space = {'free_capacity_gb': 10, 'total_capacity_gb': 100}
stats_large_space = {'free_capacity_gb': 90, 'total_capacity_gb': 100}

vol_id = 'fceec30e-98bc-4ce5-85ff-d7309cc17cc2'
test_volume = {'id': vol_id, 'name_id': None,
               'display_name': 'test volume', 'name': 'volume', 'size': 10}
test_retype_volume = {'attach_status': fields.VolumeAttachStatus.DETACHED,
                      'id': vol_id, 'name_id': None,
                      'display_name': 'test volume', 'name': 'volume',
                      'size': 10}
test_host = {'capabilities': {'location_info':
                              'DotHillVolumeDriver:xxxxx:dg02:A'}}
test_snap = {'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
             'volume': {'name_id': None},
             'volume_id': vol_id, 'display_name': 'test volume',
             'name': 'volume', 'volume_size': 10}
encoded_volid = 'v_O7DDpi8TOWF_9cwnMF'
encoded_snapid = 's_O7DDpi8TOWF_9cwnMF'
dest_volume = {'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
               'source_volid': vol_id,
               'display_name': 'test volume', 'name': 'volume', 'size': 10}
dest_volume_larger = {'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                      'name_id': None,
                      'source_volid': vol_id,
                      'display_name': 'test volume',
                      'name': 'volume', 'size': 20}
attached_volume = {'id': vol_id,
                   'display_name': 'test volume', 'name': 'volume',
                   'size': 10, 'status': 'in-use',
                   'attach_status': fields.VolumeAttachStatus.ATTACHED}
attaching_volume = {'id': vol_id,
                    'display_name': 'test volume', 'name': 'volume',
                    'size': 10, 'status': 'attaching',
                    'attach_status': fields.VolumeAttachStatus.ATTACHED}
detached_volume = {'id': vol_id, 'name_id': None,
                   'display_name': 'test volume', 'name': 'volume',
                   'size': 10, 'status': 'available',
                   'attach_status': 'detached'}

connector = {'ip': '10.0.0.2',
             'initiator': 'iqn.1993-08.org.debian:01:222',
             'wwpns': ["111111111111111", "111111111111112"],
             'wwnns': ["211111111111111", "211111111111112"],
             'host': 'fakehost'}
invalid_connector = {'ip': '10.0.0.2',
                     'initiator': '',
                     'wwpns': [],
                     'wwnns': [],
                     'host': 'fakehost'}


class TestDotHillClient(test.TestCase):
    def setUp(self):
        super(TestDotHillClient, self).setUp()
        self.login = 'manage'
        self.passwd = '!manage'
        self.ip = '10.0.0.1'
        self.protocol = 'http'
        self.ssl_verify = False
        self.client = dothill.DotHillClient(self.ip, self.login, self.passwd,
                                            self.protocol, self.ssl_verify)

    @mock.patch('requests.get')
    def test_login(self, mock_requests_get):
        m = mock.Mock()
        mock_requests_get.return_value = m

        m.text.encode.side_effect = [resp_badlogin, resp_badlogin]
        self.assertRaises(exception.DotHillAuthenticationError,
                          self.client.login)

        m.text.encode.side_effect = [resp_login, resp_fw, resp_system]
        self.client.login()
        self.assertEqual(session_key, self.client._session_key)

    def test_build_request_url(self):
        url = self.client._build_request_url('/path')
        self.assertEqual('http://10.0.0.1/api/path', url)
        url = self.client._build_request_url('/path', arg1='val1')
        self.assertEqual('http://10.0.0.1/api/path/arg1/val1', url)
        url = self.client._build_request_url('/path', arg_1='val1')
        self.assertEqual('http://10.0.0.1/api/path/arg-1/val1', url)
        url = self.client._build_request_url('/path', 'arg1')
        self.assertEqual('http://10.0.0.1/api/path/arg1', url)
        url = self.client._build_request_url('/path', 'arg1', arg2='val2')
        self.assertEqual('http://10.0.0.1/api/path/arg2/val2/arg1', url)
        url = self.client._build_request_url('/path', 'arg1', 'arg3',
                                             arg2='val2')
        self.assertEqual('http://10.0.0.1/api/path/arg2/val2/arg1/arg3', url)

    @mock.patch('requests.get')
    def test_request(self, mock_requests_get):
        self.client._session_key = session_key

        m = mock.Mock()
        m.text.encode.side_effect = [response_ok, malformed_xml,
                                     requests.exceptions.
                                     RequestException("error")]
        mock_requests_get.return_value = m
        ret = self.client._api_request('/path')
        self.assertTrue(type(ret) == etree.RestrictedElement)
        self.assertRaises(exception.DotHillConnectionError,
                          self.client._api_request,
                          '/path')
        self.assertRaises(exception.DotHillConnectionError,
                          self.client._api_request,
                          '/path')

    def test_assert_response_ok(self):
        ok_tree = etree.XML(response_ok)
        not_ok_tree = etree.XML(response_not_ok)
        invalid_tree = etree.XML(invalid_xml)
        ret = self.client._assert_response_ok(ok_tree)
        self.assertIsNone(ret)
        self.assertRaises(exception.DotHillRequestError,
                          self.client._assert_response_ok,
                          not_ok_tree)
        self.assertRaises(exception.DotHillRequestError,
                          self.client._assert_response_ok, invalid_tree)

    @mock.patch.object(dothill.DotHillClient, '_request')
    def test_backend_exists(self, mock_request):
        mock_request.side_effect = [exception.DotHillRequestError,
                                    fake_xml]
        self.assertFalse(self.client.backend_exists('backend_name',
                                                    'linear'))
        self.assertTrue(self.client.backend_exists('backend_name',
                                                   'linear'))

    @mock.patch.object(dothill.DotHillClient, '_request')
    def test_backend_stats(self, mock_request):
        stats = {'free_capacity_gb': 1979,
                 'total_capacity_gb': 1979}
        linear = etree.XML(response_stats_linear)
        virtual = etree.XML(response_stats_virtual)
        mock_request.side_effect = [linear, virtual]

        self.assertEqual(stats, self.client.backend_stats('OpenStack',
                                                          'linear'))
        self.assertEqual(stats, self.client.backend_stats('A',
                                                          'virtual'))

    @mock.patch.object(dothill.DotHillClient, '_request')
    def test_get_lun(self, mock_request):
        mock_request.side_effect = [etree.XML(response_no_lun),
                                    etree.XML(response_lun)]
        ret = self.client._get_first_available_lun_for_host("fakehost")
        self.assertEqual(1, ret)
        ret = self.client._get_first_available_lun_for_host("fakehost")
        self.assertEqual(2, ret)

    @mock.patch.object(dothill.DotHillClient, '_request')
    def test_get_ports(self, mock_request):
        mock_request.side_effect = [etree.XML(response_ports)]
        ret = self.client.get_active_target_ports()
        self.assertEqual([{'port-type': 'FC',
                           'target-id': 'id2',
                           'status': 'Up'},
                          {'port-type': 'iSCSI',
                           'target-id': 'id4',
                           'status': 'Up'},
                          {'port-type': 'iSCSI',
                           'target-id': 'id5',
                           'status': 'Up'}], ret)

    @mock.patch.object(dothill.DotHillClient, '_request')
    def test_get_fc_ports(self, mock_request):
        mock_request.side_effect = [etree.XML(response_ports)]
        ret = self.client.get_active_fc_target_ports()
        self.assertEqual(['id2'], ret)

    @mock.patch.object(dothill.DotHillClient, '_request')
    def test_get_iscsi_iqns(self, mock_request):
        mock_request.side_effect = [etree.XML(response_ports)]
        ret = self.client.get_active_iscsi_target_iqns()
        self.assertEqual(['id4', 'id5'], ret)

    @mock.patch.object(dothill.DotHillClient, '_request')
    def test_get_iscsi_portals(self, mock_request):
        portals = {'10.0.0.12': 'Up', '10.0.0.11': 'Up'}
        mock_request.side_effect = [etree.XML(response_ports_linear),
                                    etree.XML(response_ports_virtual)]
        ret = self.client.get_active_iscsi_target_portals()
        self.assertEqual(portals, ret)
        ret = self.client.get_active_iscsi_target_portals()
        self.assertEqual(portals, ret)

    @mock.patch.object(dothill.DotHillClient, '_request')
    def test_delete_snapshot(self, mock_request):
        mock_request.side_effect = [None, None]
        self.client.delete_snapshot('dummy', 'linear')
        mock_request.assert_called_with('/delete/snapshot', 'cleanup', 'dummy')
        self.client.delete_snapshot('dummy', 'paged')
        mock_request.assert_called_with('/delete/snapshot', 'dummy')

    @mock.patch.object(dothill.DotHillClient, '_request')
    def test_list_luns_for_host(self, mock_request):
        mock_request.side_effect = [etree.XML(response_no_lun),
                                    etree.XML(response_lun)]
        self.client._fw = 'T100'
        self.client.list_luns_for_host('dummy')
        mock_request.assert_called_with('/show/host-maps', 'dummy')
        self.client._fw = 'G221'
        self.client.list_luns_for_host('dummy')
        mock_request.assert_called_with('/show/maps/initiator', 'dummy')


class FakeConfiguration1(object):
    dothill_backend_name = 'OpenStack'
    dothill_backend_type = 'linear'
    san_ip = '10.0.0.1'
    san_login = 'manage'
    san_password = '!manage'
    dothill_api_protocol = 'http'

    def safe_get(self, key):
        return 'fakevalue'


class FakeConfiguration2(FakeConfiguration1):
    dothill_iscsi_ips = ['10.0.0.11']
    use_chap_auth = None


class TestFCDotHillCommon(test.TestCase):
    def setUp(self):
        super(TestFCDotHillCommon, self).setUp()
        self.config = FakeConfiguration1()
        self.common = dothill_common.DotHillCommon(self.config)
        self.common.client_login = mock.MagicMock()
        self.common.client_logout = mock.MagicMock()
        self.common.serialNumber = "xxxxx"
        self.common.owner = "A"
        self.connector_element = "wwpns"

    @mock.patch.object(dothill.DotHillClient, 'get_serial_number')
    @mock.patch.object(dothill.DotHillClient, 'get_owner_info')
    @mock.patch.object(dothill.DotHillClient, 'backend_exists')
    def test_do_setup(self, mock_backend_exists,
                      mock_owner_info, mock_serial_number):
        mock_backend_exists.side_effect = [False, True]
        mock_owner_info.return_value = "A"
        mock_serial_number.return_value = "xxxxx"
        self.assertRaises(exception.DotHillInvalidBackend,
                          self.common.do_setup, None)
        self.assertIsNone(self.common.do_setup(None))
        mock_backend_exists.assert_called_with(self.common.backend_name,
                                               self.common.backend_type)
        mock_owner_info.assert_called_with(self.common.backend_name,
                                           self.common.backend_type)

    def test_vol_name(self):
        self.assertEqual(encoded_volid, self.common._get_vol_name(vol_id))
        self.assertEqual(encoded_snapid, self.common._get_snap_name(vol_id))

    def test_check_flags(self):
        class FakeOptions(object):
            def __init__(self, d):
                for k, v in d.items():
                    self.__dict__[k] = v

        options = FakeOptions({'opt1': 'val1', 'opt2': 'val2'})
        required_flags = ['opt1', 'opt2']
        ret = self.common.check_flags(options, required_flags)
        self.assertIsNone(ret)

        options = FakeOptions({'opt1': 'val1', 'opt2': 'val2'})
        required_flags = ['opt1', 'opt2', 'opt3']
        self.assertRaises(exception.Invalid, self.common.check_flags,
                          options, required_flags)

    def test_assert_connector_ok(self):
        self.assertRaises(exception.InvalidInput,
                          self.common._assert_connector_ok, invalid_connector,
                          self.connector_element)
        self.assertIsNone(self.common._assert_connector_ok(
                          connector,
                          self.connector_element))

    @mock.patch.object(dothill.DotHillClient, 'backend_stats')
    def test_update_volume_stats(self, mock_stats):
        mock_stats.side_effect = [exception.DotHillRequestError,
                                  stats_large_space]

        self.assertRaises(exception.Invalid, self.common._update_volume_stats)
        mock_stats.assert_called_with(self.common.backend_name,
                                      self.common.backend_type)
        ret = self.common._update_volume_stats()

        self.assertIsNone(ret)
        self.assertEqual({'driver_version': self.common.VERSION,
                          'pools': [{'QoS_support': False,
                                     'free_capacity_gb': 90,
                                     'location_info':
                                     'DotHillVolumeDriver:xxxxx:OpenStack:A',
                                     'pool_name': 'OpenStack',
                                     'total_capacity_gb': 100}],
                          'storage_protocol': None,
                          'vendor_name': 'DotHill',
                          'multiattach': True,
                          'volume_backend_name': None}, self.common.stats)

    @mock.patch.object(dothill.DotHillClient, 'create_volume')
    def test_create_volume(self, mock_create):
        mock_create.side_effect = [exception.DotHillRequestError, None]

        self.assertRaises(exception.Invalid, self.common.create_volume,
                          test_volume)
        ret = self.common.create_volume(test_volume)
        self.assertIsNone(ret)
        mock_create.assert_called_with(encoded_volid,
                                       "%sGiB" % test_volume['size'],
                                       self.common.backend_name,
                                       self.common.backend_type)

    @mock.patch.object(dothill.DotHillClient, 'delete_volume')
    def test_delete_volume(self, mock_delete):
        not_found_e = exception.DotHillRequestError(
            'The volume was not found on this system.')
        mock_delete.side_effect = [not_found_e, exception.DotHillRequestError,
                                   None]
        self.assertIsNone(self.common.delete_volume(test_volume))
        self.assertRaises(exception.Invalid, self.common.delete_volume,
                          test_volume)
        self.assertIsNone(self.common.delete_volume(test_volume))
        mock_delete.assert_called_with(encoded_volid)

    @mock.patch.object(dothill.DotHillClient, 'copy_volume')
    @mock.patch.object(dothill.DotHillClient, 'backend_stats')
    def test_create_cloned_volume(self, mock_stats, mock_copy):
        mock_stats.side_effect = [stats_low_space, stats_large_space,
                                  stats_large_space]

        self.assertRaises(exception.DotHillNotEnoughSpace,
                          self.common.create_cloned_volume,
                          dest_volume, detached_volume)
        self.assertFalse(mock_copy.called)

        mock_copy.side_effect = [exception.DotHillRequestError, None]
        self.assertRaises(exception.Invalid,
                          self.common.create_cloned_volume,
                          dest_volume, detached_volume)

        ret = self.common.create_cloned_volume(dest_volume, detached_volume)
        self.assertIsNone(ret)

        mock_copy.assert_called_with(encoded_volid,
                                     'vqqqqqqqqqqqqqqqqqqq',
                                     self.common.backend_name,
                                     self.common.backend_type)

    @mock.patch.object(dothill.DotHillClient, 'copy_volume')
    @mock.patch.object(dothill.DotHillClient, 'backend_stats')
    @mock.patch.object(dothill_common.DotHillCommon, 'extend_volume')
    def test_create_cloned_volume_larger(self, mock_extend, mock_stats,
                                         mock_copy):
        mock_stats.side_effect = [stats_low_space, stats_large_space,
                                  stats_large_space]

        self.assertRaises(exception.DotHillNotEnoughSpace,
                          self.common.create_cloned_volume,
                          dest_volume_larger, detached_volume)
        self.assertFalse(mock_copy.called)

        mock_copy.side_effect = [exception.DotHillRequestError, None]
        self.assertRaises(exception.Invalid,
                          self.common.create_cloned_volume,
                          dest_volume_larger, detached_volume)

        ret = self.common.create_cloned_volume(dest_volume_larger,
                                               detached_volume)
        self.assertIsNone(ret)
        mock_copy.assert_called_with(encoded_volid,
                                     'vqqqqqqqqqqqqqqqqqqq',
                                     self.common.backend_name,
                                     self.common.backend_type)
        mock_extend.assert_called_once_with(dest_volume_larger,
                                            dest_volume_larger['size'])

    @mock.patch.object(dothill.DotHillClient, 'get_volume_size')
    @mock.patch.object(dothill.DotHillClient, 'extend_volume')
    @mock.patch.object(dothill.DotHillClient, 'copy_volume')
    @mock.patch.object(dothill.DotHillClient, 'backend_stats')
    def test_create_volume_from_snapshot(self, mock_stats, mock_copy,
                                         mock_extend, mock_get_size):
        mock_stats.side_effect = [stats_low_space, stats_large_space,
                                  stats_large_space]

        self.assertRaises(exception.DotHillNotEnoughSpace,
                          self.common.create_volume_from_snapshot,
                          dest_volume, test_snap)

        mock_copy.side_effect = [exception.DotHillRequestError, None]
        mock_get_size.return_value = test_snap['volume_size']
        self.assertRaises(exception.Invalid,
                          self.common.create_volume_from_snapshot,
                          dest_volume, test_snap)

        ret = self.common.create_volume_from_snapshot(dest_volume_larger,
                                                      test_snap)
        self.assertIsNone(ret)
        mock_copy.assert_called_with('sqqqqqqqqqqqqqqqqqqq',
                                     'vqqqqqqqqqqqqqqqqqqq',
                                     self.common.backend_name,
                                     self.common.backend_type)
        mock_extend.assert_called_with('vqqqqqqqqqqqqqqqqqqq', '10GiB')

    @mock.patch.object(dothill.DotHillClient, 'get_volume_size')
    @mock.patch.object(dothill.DotHillClient, 'extend_volume')
    def test_extend_volume(self, mock_extend, mock_size):
        mock_extend.side_effect = [exception.DotHillRequestError, None]
        mock_size.side_effect = [10, 10]
        self.assertRaises(exception.Invalid, self.common.extend_volume,
                          test_volume, 20)
        ret = self.common.extend_volume(test_volume, 20)
        self.assertIsNone(ret)
        mock_extend.assert_called_with(encoded_volid, '10GiB')

    @mock.patch.object(dothill.DotHillClient, 'create_snapshot')
    def test_create_snapshot(self, mock_create):
        mock_create.side_effect = [exception.DotHillRequestError, None]

        self.assertRaises(exception.Invalid, self.common.create_snapshot,
                          test_snap)
        ret = self.common.create_snapshot(test_snap)
        self.assertIsNone(ret)
        mock_create.assert_called_with(encoded_volid, 'sqqqqqqqqqqqqqqqqqqq')

    @mock.patch.object(dothill.DotHillClient, 'delete_snapshot')
    def test_delete_snapshot(self, mock_delete):
        not_found_e = exception.DotHillRequestError(
            'The volume was not found on this system.')
        mock_delete.side_effect = [not_found_e, exception.DotHillRequestError,
                                   None]

        self.assertIsNone(self.common.delete_snapshot(test_snap))
        self.assertRaises(exception.Invalid, self.common.delete_snapshot,
                          test_snap)
        self.assertIsNone(self.common.delete_snapshot(test_snap))
        mock_delete.assert_called_with('sqqqqqqqqqqqqqqqqqqq',
                                       self.common.backend_type)

    @mock.patch.object(dothill.DotHillClient, 'map_volume')
    def test_map_volume(self, mock_map):
        mock_map.side_effect = [exception.DotHillRequestError, 10]

        self.assertRaises(exception.Invalid, self.common.map_volume,
                          test_volume, connector, self.connector_element)
        lun = self.common.map_volume(test_volume, connector,
                                     self.connector_element)
        self.assertEqual(10, lun)
        mock_map.assert_called_with(encoded_volid,
                                    connector, self.connector_element)

    @mock.patch.object(dothill.DotHillClient, 'unmap_volume')
    def test_unmap_volume(self, mock_unmap):
        mock_unmap.side_effect = [exception.DotHillRequestError, None]

        self.assertRaises(exception.Invalid, self.common.unmap_volume,
                          test_volume, connector, self.connector_element)
        ret = self.common.unmap_volume(test_volume, connector,
                                       self.connector_element)
        self.assertIsNone(ret)
        mock_unmap.assert_called_with(encoded_volid, connector,
                                      self.connector_element)

    @mock.patch.object(dothill.DotHillClient, 'copy_volume')
    @mock.patch.object(dothill.DotHillClient, 'delete_volume')
    @mock.patch.object(dothill.DotHillClient, 'modify_volume_name')
    def test_retype(self, mock_modify, mock_delete, mock_copy):
        mock_copy.side_effect = [exception.DotHillRequestError, None]
        self.assertRaises(exception.Invalid, self.common.migrate_volume,
                          test_retype_volume, test_host)
        ret = self.common.migrate_volume(test_retype_volume, test_host)
        self.assertEqual((True, None), ret)
        ret = self.common.migrate_volume(test_retype_volume,
                                         {'capabilities': {}})
        self.assertEqual((False, None), ret)

    @mock.patch.object(dothill_common.DotHillCommon, '_get_vol_name')
    @mock.patch.object(dothill.DotHillClient, 'modify_volume_name')
    def test_manage_existing(self, mock_modify, mock_volume):
        existing_ref = {'source-name': 'xxxx'}
        mock_modify.side_effect = [exception.DotHillRequestError, None]
        self.assertRaises(exception.Invalid, self.common.manage_existing,
                          test_volume, existing_ref)
        ret = self.common.manage_existing(test_volume, existing_ref)
        self.assertIsNone(ret)

    @mock.patch.object(dothill.DotHillClient, 'get_volume_size')
    def test_manage_existing_get_size(self, mock_volume):
        existing_ref = {'source-name': 'xxxx'}
        mock_volume.side_effect = [exception.DotHillRequestError, 1]
        self.assertRaises(exception.Invalid,
                          self.common.manage_existing_get_size,
                          None, existing_ref)
        ret = self.common.manage_existing_get_size(None, existing_ref)
        self.assertEqual(1, ret)


class TestISCSIDotHillCommon(TestFCDotHillCommon):
    def setUp(self):
        super(TestISCSIDotHillCommon, self).setUp()
        self.connector_element = 'initiator'


class TestDotHillFC(test.TestCase):
    @mock.patch.object(dothill_common.DotHillCommon, 'do_setup')
    def setUp(self, mock_setup):
        super(TestDotHillFC, self).setUp()
        self.vendor_name = 'DotHill'

        mock_setup.return_value = True

        def fake_init(self, *args, **kwargs):
            super(dothill_fc.DotHillFCDriver, self).__init__()
            self.common = None
            self.configuration = FakeConfiguration1()
            self.lookup_service = fczm_utils.create_lookup_service()

        dothill_fc.DotHillFCDriver.__init__ = fake_init
        self.driver = dothill_fc.DotHillFCDriver()
        self.driver.do_setup(None)

    def _test_with_mock(self, mock, method, args, expected=None):
        func = getattr(self.driver, method)
        mock.side_effect = [exception.Invalid(), None]
        self.assertRaises(exception.Invalid, func, *args)
        self.assertEqual(expected, func(*args))

    @mock.patch.object(dothill_common.DotHillCommon, 'create_volume')
    def test_create_volume(self, mock_create):
        self._test_with_mock(mock_create, 'create_volume', [None])

    @mock.patch.object(dothill_common.DotHillCommon,
                       'create_cloned_volume')
    def test_create_cloned_volume(self, mock_create):
        self._test_with_mock(mock_create, 'create_cloned_volume', [None, None])

    @mock.patch.object(dothill_common.DotHillCommon,
                       'create_volume_from_snapshot')
    def test_create_volume_from_snapshot(self, mock_create):
        self._test_with_mock(mock_create, 'create_volume_from_snapshot',
                             [None, None])

    @mock.patch.object(dothill_common.DotHillCommon, 'delete_volume')
    def test_delete_volume(self, mock_delete):
        self._test_with_mock(mock_delete, 'delete_volume', [None])

    @mock.patch.object(dothill_common.DotHillCommon, 'create_snapshot')
    def test_create_snapshot(self, mock_create):
        self._test_with_mock(mock_create, 'create_snapshot', [None])

    @mock.patch.object(dothill_common.DotHillCommon, 'delete_snapshot')
    def test_delete_snapshot(self, mock_delete):
        self._test_with_mock(mock_delete, 'delete_snapshot', [None])

    @mock.patch.object(dothill_common.DotHillCommon, 'extend_volume')
    def test_extend_volume(self, mock_extend):
        self._test_with_mock(mock_extend, 'extend_volume', [None, 10])

    @mock.patch.object(dothill_common.DotHillCommon, 'client_logout')
    @mock.patch.object(dothill_common.DotHillCommon,
                       'get_active_fc_target_ports')
    @mock.patch.object(dothill_common.DotHillCommon, 'map_volume')
    @mock.patch.object(dothill_common.DotHillCommon, 'client_login')
    def test_initialize_connection(self, mock_login, mock_map, mock_ports,
                                   mock_logout):
        mock_login.return_value = None
        mock_logout.return_value = None
        mock_map.side_effect = [exception.Invalid, 1]
        mock_ports.side_effect = [['id1']]

        self.assertRaises(exception.Invalid,
                          self.driver.initialize_connection, test_volume,
                          connector)
        mock_map.assert_called_with(test_volume, connector, 'wwpns')

        ret = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual({'driver_volume_type': 'fibre_channel',
                          'data': {'initiator_target_map': {
                                   '111111111111111': ['id1'],
                                   '111111111111112': ['id1']},
                                   'target_wwn': ['id1'],
                                   'target_lun': 1,
                                   'target_discovered': True}}, ret)

    @mock.patch.object(dothill_common.DotHillCommon, 'unmap_volume')
    @mock.patch.object(dothill.DotHillClient, 'list_luns_for_host')
    def test_terminate_connection(self, mock_list, mock_unmap):
        mock_unmap.side_effect = [1]
        mock_list.side_effect = ['yes']
        actual = {'driver_volume_type': 'fibre_channel', 'data': {}}
        ret = self.driver.terminate_connection(test_volume, connector)
        self.assertEqual(actual, ret)
        mock_unmap.assert_called_with(test_volume, connector, 'wwpns')
        ret = self.driver.terminate_connection(test_volume, connector)
        self.assertEqual(actual, ret)

    @mock.patch.object(dothill_common.DotHillCommon, 'get_volume_stats')
    def test_get_volume_stats(self, mock_stats):
        stats = {'storage_protocol': None,
                 'driver_version': self.driver.VERSION,
                 'volume_backend_name': None,
                 'vendor_name': self.vendor_name,
                 'multiattach': True,
                 'pools': [{'free_capacity_gb': 90,
                            'reserved_percentage': 0,
                            'total_capacity_gb': 100,
                            'QoS_support': False,
                            'location_info': 'xx:xx:xx:xx',
                            'pool_name': 'x'}]}
        mock_stats.side_effect = [exception.Invalid, stats, stats]

        self.assertRaises(exception.Invalid, self.driver.get_volume_stats,
                          False)
        ret = self.driver.get_volume_stats(False)
        self.assertEqual(stats, ret)

        ret = self.driver.get_volume_stats(True)
        self.assertEqual(stats, ret)
        mock_stats.assert_called_with(True)

    @mock.patch.object(dothill_common.DotHillCommon, 'retype')
    def test_retype(self, mock_retype):
        mock_retype.side_effect = [exception.Invalid, True, False]
        args = [None, None, None, None, None]
        self.assertRaises(exception.Invalid, self.driver.retype, *args)
        self.assertTrue(self.driver.retype(*args))
        self.assertFalse(self.driver.retype(*args))

    @mock.patch.object(dothill_common.DotHillCommon, 'manage_existing')
    def test_manage_existing(self, mock_manage_existing):
        self._test_with_mock(mock_manage_existing, 'manage_existing',
                             [None, None])

    @mock.patch.object(dothill_common.DotHillCommon,
                       'manage_existing_get_size')
    def test_manage_size(self, mock_manage_size):
        mock_manage_size.side_effect = [exception.Invalid, 1]
        self.assertRaises(exception.Invalid,
                          self.driver.manage_existing_get_size,
                          None, None)
        self.assertEqual(1, self.driver.manage_existing_get_size(None, None))


class TestDotHillISCSI(TestDotHillFC):
    @mock.patch.object(dothill_common.DotHillCommon, 'do_setup')
    def setUp(self, mock_setup):
        super(TestDotHillISCSI, self).setUp()
        self.vendor_name = 'DotHill'
        mock_setup.return_value = True

        def fake_init(self, *args, **kwargs):
            super(dothill_iscsi.DotHillISCSIDriver, self).__init__()
            self.common = None
            self.configuration = FakeConfiguration2()
            self.iscsi_ips = ['10.0.0.11']

        dothill_iscsi.DotHillISCSIDriver.__init__ = fake_init
        self.driver = dothill_iscsi.DotHillISCSIDriver()
        self.driver.do_setup(None)

    @mock.patch.object(dothill_common.DotHillCommon, 'client_logout')
    @mock.patch.object(dothill_common.DotHillCommon,
                       'get_active_iscsi_target_portals')
    @mock.patch.object(dothill_common.DotHillCommon,
                       'get_active_iscsi_target_iqns')
    @mock.patch.object(dothill_common.DotHillCommon, 'map_volume')
    @mock.patch.object(dothill_common.DotHillCommon, 'client_login')
    def test_initialize_connection(self, mock_login, mock_map, mock_iqns,
                                   mock_portals, mock_logout):
        mock_login.return_value = None
        mock_logout.return_value = None
        mock_map.side_effect = [exception.Invalid, 1]
        self.driver.iscsi_ips = ['10.0.0.11']
        self.driver.initialize_iscsi_ports()
        mock_iqns.side_effect = [['id2']]
        mock_portals.return_value = {'10.0.0.11': 'Up', '10.0.0.12': 'Up'}

        self.assertRaises(exception.Invalid,
                          self.driver.initialize_connection, test_volume,
                          connector)
        mock_map.assert_called_with(test_volume, connector, 'initiator')

        ret = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual({'driver_volume_type': 'iscsi',
                          'data': {'target_iqn': 'id2',
                                   'target_lun': 1,
                                   'target_discovered': True,
                                   'target_portal': '10.0.0.11:3260'}}, ret)

    @mock.patch.object(dothill_common.DotHillCommon, 'unmap_volume')
    def test_terminate_connection(self, mock_unmap):
        mock_unmap.side_effect = [exception.Invalid, 1]

        self.assertRaises(exception.Invalid,
                          self.driver.terminate_connection, test_volume,
                          connector)
        mock_unmap.assert_called_with(test_volume, connector, 'initiator')

        ret = self.driver.terminate_connection(test_volume, connector)
        self.assertIsNone(ret)
