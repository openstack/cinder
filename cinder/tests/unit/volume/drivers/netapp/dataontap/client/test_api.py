# Copyright (c) 2014 Ben Swartzlander.  All rights reserved.
# Copyright (c) 2014 Navneet Singh.  All rights reserved.
# Copyright (c) 2014 Clinton Knight.  All rights reserved.
# Copyright (c) 2014 Alex Meade.  All rights reserved.
# Copyright (c) 2014 Bob Callaway.  All rights reserved.
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
"""Tests for NetApp API layer"""

from unittest import mock
import urllib

import ddt
from lxml import etree
from oslo_serialization import jsonutils
from oslo_utils import netutils
import paramiko
import requests
from requests import auth

from cinder import exception
from cinder.i18n import _
from cinder.tests.unit import test
from cinder.tests.unit.volume.drivers.netapp.dataontap.client import (
    fakes as zapi_fakes)
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api


@ddt.ddt
class NetAppApiServerTests(test.TestCase):
    """Test case for NetApp API server methods"""
    def setUp(self):
        self.root = netapp_api.NaServer('127.0.0.1')
        super(NetAppApiServerTests, self).setUp()

    @ddt.data(None, 'ftp')
    def test_set_transport_type_value_error(self, transport_type):
        """Tests setting an invalid transport type"""
        self.assertRaises(ValueError, self.root.set_transport_type,
                          transport_type)

    @ddt.data({'params': {'transport_type': 'http',
                          'server_type_filer': 'filer'}},
              {'params': {'transport_type': 'http',
                          'server_type_filer': 'xyz'}},
              {'params': {'transport_type': 'https',
                          'server_type_filer': 'filer'}},
              {'params': {'transport_type': 'https',
                          'server_type_filer': 'xyz'}})
    @ddt.unpack
    def test_set_transport_type_valid(self, params):
        """Tests setting a valid transport type"""
        self.root._server_type = params['server_type_filer']
        mock_invoke = self.mock_object(self.root, 'set_port')

        self.root.set_transport_type(params['transport_type'])

        expected_call_args = zapi_fakes.FAKE_CALL_ARGS_LIST

        self.assertIn(mock_invoke.call_args, expected_call_args)

    @ddt.data('stor', 'STORE', '')
    def test_set_server_type_value_error(self, server_type):
        """Tests Value Error on setting the wrong server type"""
        self.assertRaises(ValueError, self.root.set_server_type, server_type)

    @ddt.data('!&', '80na', '')
    def test_set_port__value_error(self, port):
        """Tests Value Error on trying to set port with a non-integer"""
        self.assertRaises(ValueError, self.root.set_port, port)

    @ddt.data('!&', '80na', '')
    def test_set_timeout_value_error(self, timeout):
        """Tests Value Error on trying to set port with a non-integer"""
        self.assertRaises(ValueError, self.root.set_timeout, timeout)

    @ddt.data({'params': {'major': 1, 'minor': '20a'}},
              {'params': {'major': '20a', 'minor': 1}},
              {'params': {'major': '!*', 'minor': '20a'}})
    @ddt.unpack
    def test_set_api_version_value_error(self, params):
        """Tests Value Error on setting values incompatible with integer"""
        self.assertRaises(ValueError, self.root.set_api_version, **params)

    def test_set_api_version_valid(self):
        """Tests no Error on setting values compatible with integer"""
        args = {'major': '20', 'minor': 1}

        self.root.set_api_version(**args)

    @ddt.data({'params': {'result': zapi_fakes.FAKE_RESULT_API_ERR_REASON}},
              {'params': {'result': zapi_fakes.FAKE_RESULT_API_ERRNO_INVALID}},
              {'params': {'result': zapi_fakes.FAKE_RESULT_API_ERRNO_VALID}})
    @ddt.unpack
    def test_invoke_successfully_naapi_error(self, params):
        """Tests invoke successfully raising NaApiError"""
        self.mock_object(self.root, 'send_http_request',
                         return_value=params['result'])

        self.assertRaises(netapp_api.NaApiError,
                          self.root.invoke_successfully,
                          zapi_fakes.FAKE_NA_ELEMENT)

    def test_invoke_successfully_no_error(self):
        """Tests invoke successfully with no errors"""
        self.mock_object(self.root, 'send_http_request',
                         return_value=zapi_fakes.FAKE_RESULT_SUCCESS)

        self.assertEqual(zapi_fakes.FAKE_RESULT_SUCCESS.to_string(),
                         self.root.invoke_successfully(
                             zapi_fakes.FAKE_NA_ELEMENT).to_string())

    def test__create_request(self):
        """Tests method _create_request"""
        self.root._ns = zapi_fakes.FAKE_XML_STR
        self.root._api_version = '1.20'
        self.mock_object(self.root, '_enable_tunnel_request')
        self.mock_object(netapp_api.NaElement, 'add_child_elem')
        self.mock_object(netapp_api.NaElement, 'to_string',
                         return_value=zapi_fakes.FAKE_XML_STR)
        mock_invoke = self.mock_object(urllib.request, 'Request')

        self.root._create_request(zapi_fakes.FAKE_NA_ELEMENT, True)

        self.assertTrue(mock_invoke.called)

    @ddt.data({'params': {'server': zapi_fakes.FAKE_NA_SERVER_API_1_5}},
              {'params': {'server': zapi_fakes.FAKE_NA_SERVER_API_1_14}})
    @ddt.unpack
    def test__enable_tunnel_request__value_error(self, params):
        """Tests value errors with creating tunnel request"""

        self.assertRaises(ValueError, params['server']._enable_tunnel_request,
                          'test')

    def test__enable_tunnel_request_valid(self):
        """Tests creating tunnel request with correct values"""
        netapp_elem = zapi_fakes.FAKE_NA_ELEMENT
        server = zapi_fakes.FAKE_NA_SERVER_API_1_20
        mock_invoke = self.mock_object(netapp_elem, 'add_attr')
        expected_call_args = [mock.call('vfiler', 'filer'),
                              mock.call('vfiler', 'server')]

        server._enable_tunnel_request(netapp_elem)

        self.assertEqual(expected_call_args, mock_invoke.call_args_list)

    def test__parse_response__naapi_error(self):
        """Tests NaApiError on no response"""
        self.assertRaises(netapp_api.NaApiError,
                          self.root._parse_response, None)

    def test__parse_response_no_error(self):
        """Tests parse function with appropriate response"""
        mock_invoke = self.mock_object(etree, 'XML', return_value='xml')

        self.root._parse_response(zapi_fakes.FAKE_XML_STR)

        mock_invoke.assert_called_with(zapi_fakes.FAKE_XML_STR)

    def test__build_opener_not_implemented_error(self):
        """Tests whether certificate style authorization raises Exception"""
        self.root._auth_style = 'not_basic_auth'

        self.assertRaises(NotImplementedError, self.root._build_opener)

    def test__build_opener_valid(self):
        """Tests whether build opener works with valid parameters"""
        self.root._auth_style = 'basic_auth'
        mock_invoke = self.mock_object(urllib.request, 'build_opener')

        self.root._build_opener()

        self.assertTrue(mock_invoke.called)

    @ddt.data(None, zapi_fakes.FAKE_XML_STR)
    def test_send_http_request_value_error(self, na_element):
        """Tests whether invalid NaElement parameter causes error"""

        self.assertRaises(ValueError, self.root.send_http_request, na_element)

    def test_send_http_request_http_error(self):
        """Tests handling of HTTPError"""
        na_element = zapi_fakes.FAKE_NA_ELEMENT
        self.mock_object(self.root, '_create_request',
                         return_value=('abc', zapi_fakes.FAKE_NA_ELEMENT))
        self.mock_object(netapp_api, 'LOG')
        self.root._opener = zapi_fakes.FAKE_HTTP_OPENER
        self.mock_object(self.root, '_build_opener')
        self.mock_object(self.root._opener, 'open',
                         side_effect=urllib.error.HTTPError(url='', hdrs='',
                                                            fp=None,
                                                            code='401',
                                                            msg='httperror'))

        self.assertRaises(netapp_api.NaApiError, self.root.send_http_request,
                          na_element)

    def test_send_http_request_unknown_exception(self):
        """Tests handling of Unknown Exception"""
        na_element = zapi_fakes.FAKE_NA_ELEMENT
        self.mock_object(self.root, '_create_request',
                         return_value=('abc', zapi_fakes.FAKE_NA_ELEMENT))
        mock_log = self.mock_object(netapp_api, 'LOG')
        self.root._opener = zapi_fakes.FAKE_HTTP_OPENER
        self.mock_object(self.root, '_build_opener')
        self.mock_object(self.root._opener, 'open', side_effect=Exception)

        self.assertRaises(netapp_api.NaApiError, self.root.send_http_request,
                          na_element)
        self.assertEqual(1, mock_log.exception.call_count)

    def test_send_http_request_valid(self):
        """Tests the method send_http_request with valid parameters"""
        na_element = zapi_fakes.FAKE_NA_ELEMENT
        self.mock_object(self.root, '_create_request',
                         return_value=('abc', zapi_fakes.FAKE_NA_ELEMENT))
        self.mock_object(netapp_api, 'LOG')
        self.root._opener = zapi_fakes.FAKE_HTTP_OPENER
        self.mock_object(self.root, '_build_opener')
        self.mock_object(self.root, '_get_result',
                         return_value=zapi_fakes.FAKE_NA_ELEMENT)
        opener_mock = self.mock_object(self.root._opener, 'open')
        opener_mock.read.side_effect = ['resp1', 'resp2']

        self.root.send_http_request(na_element)

    @ddt.data('192.168.1.0', '127.0.0.1', '0.0.0.0',
              '::ffff:8', 'fdf8:f53b:82e4::53', '2001::1',
              'fe80::200::abcd', '2001:0000:4136:e378:8000:63bf:3fff:fdd2')
    def test__get_url(self, host):
        port = '80'
        root = netapp_api.NaServer(host, port=port)

        protocol = root.TRANSPORT_TYPE_HTTP
        url = root.URL_FILER

        if netutils.is_valid_ipv6(host):
            host = netutils.escape_ipv6(host)

        result = '%s://%s:%s/%s' % (protocol, host, port, url)

        url = root._get_url()

        self.assertEqual(result, url)


class NetAppApiElementTransTests(test.TestCase):
    """Test case for NetApp API element translations."""

    def test_translate_struct_dict_unique_key(self):
        """Tests if dict gets properly converted to NaElements."""
        root = netapp_api.NaElement('root')
        child = {'e1': 'v1', 'e2': 'v2', 'e3': 'v3'}
        root.translate_struct(child)
        self.assertEqual(3, len(root.get_children()))
        self.assertEqual('v1', root.get_child_content('e1'))
        self.assertEqual('v2', root.get_child_content('e2'))
        self.assertEqual('v3', root.get_child_content('e3'))

    def test_translate_struct_dict_nonunique_key(self):
        """Tests if list/dict gets properly converted to NaElements."""
        root = netapp_api.NaElement('root')
        child = [{'e1': 'v1', 'e2': 'v2'}, {'e1': 'v3'}]
        root.translate_struct(child)
        self.assertEqual(3, len(root.get_children()))
        children = root.get_children()
        for c in children:
            if c.get_name() == 'e1':
                self.assertIn(c.get_content(), ['v1', 'v3'])
            else:
                self.assertEqual('v2', c.get_content())

    def test_translate_struct_list(self):
        """Tests if list gets properly converted to NaElements."""
        root = netapp_api.NaElement('root')
        child = ['e1', 'e2']
        root.translate_struct(child)
        self.assertEqual(2, len(root.get_children()))
        self.assertIsNone(root.get_child_content('e1'))
        self.assertIsNone(root.get_child_content('e2'))

    def test_translate_struct_tuple(self):
        """Tests if tuple gets properly converted to NaElements."""
        root = netapp_api.NaElement('root')
        child = ('e1', 'e2')
        root.translate_struct(child)
        self.assertEqual(2, len(root.get_children()))
        self.assertIsNone(root.get_child_content('e1'))
        self.assertIsNone(root.get_child_content('e2'))

    def test_translate_invalid_struct(self):
        """Tests if invalid data structure raises exception."""
        root = netapp_api.NaElement('root')
        child = 'random child element'
        self.assertRaises(ValueError, root.translate_struct, child)

    def test_setter_builtin_types(self):
        """Tests str, int, float get converted to NaElement."""
        root = netapp_api.NaElement('root')
        root['e1'] = 'v1'
        root['e2'] = 1
        root['e3'] = 2.0
        root['e4'] = 8
        self.assertEqual(4, len(root.get_children()))
        self.assertEqual('v1', root.get_child_content('e1'))
        self.assertEqual('1', root.get_child_content('e2'))
        self.assertEqual('2.0', root.get_child_content('e3'))
        self.assertEqual('8', root.get_child_content('e4'))

    def test_setter_na_element(self):
        """Tests na_element gets appended as child."""
        root = netapp_api.NaElement('root')
        root['e1'] = netapp_api.NaElement('nested')
        self.assertEqual(1, len(root.get_children()))
        e1 = root.get_child_by_name('e1')
        self.assertIsInstance(e1, netapp_api.NaElement)
        self.assertIsInstance(e1.get_child_by_name('nested'),
                              netapp_api.NaElement)

    def test_setter_child_dict(self):
        """Tests dict is appended as child to root."""
        root = netapp_api.NaElement('root')
        root['d'] = {'e1': 'v1', 'e2': 'v2'}
        e1 = root.get_child_by_name('d')
        self.assertIsInstance(e1, netapp_api.NaElement)
        sub_ch = e1.get_children()
        self.assertEqual(2, len(sub_ch))
        for c in sub_ch:
            self.assertIn(c.get_name(), ['e1', 'e2'])
            if c.get_name() == 'e1':
                self.assertEqual('v1', c.get_content())
            else:
                self.assertEqual('v2', c.get_content())

    def test_setter_child_list_tuple(self):
        """Tests list/tuple are appended as child to root."""
        root = netapp_api.NaElement('root')
        root['l'] = ['l1', 'l2']
        root['t'] = ('t1', 't2')
        l_element = root.get_child_by_name('l')
        self.assertIsInstance(l_element, netapp_api.NaElement)
        t = root.get_child_by_name('t')
        self.assertIsInstance(t, netapp_api.NaElement)
        for le in l_element.get_children():
            self.assertIn(le.get_name(), ['l1', 'l2'])
        for te in t.get_children():
            self.assertIn(te.get_name(), ['t1', 't2'])

    def test_setter_no_value(self):
        """Tests key with None value."""
        root = netapp_api.NaElement('root')
        root['k'] = None
        self.assertIsNone(root.get_child_content('k'))

    def test_setter_invalid_value(self):
        """Tests invalid value raises exception."""
        root = netapp_api.NaElement('root')
        try:
            root['k'] = netapp_api.NaServer('localhost')
        except Exception as e:
            if not isinstance(e, TypeError):
                self.fail(_('Error not a TypeError.'))

    def test_setter_invalid_key(self):
        """Tests invalid value raises exception."""
        root = netapp_api.NaElement('root')
        try:
            root[None] = 'value'
        except Exception as e:
            if not isinstance(e, KeyError):
                self.fail(_('Error not a KeyError.'))

    def test_getter_key_error(self):
        """Tests invalid key raises exception"""
        root = netapp_api.NaElement('root')
        self.mock_object(root, 'get_child_by_name', return_value=None)
        self.mock_object(root, 'has_attr', return_value=None)

        self.assertRaises(KeyError,
                          netapp_api.NaElement.__getitem__,
                          root, '123')

    def test_getter_na_element_list(self):
        """Tests returning NaElement list"""
        root = netapp_api.NaElement('root')
        root['key'] = ['val1', 'val2']

        self.assertEqual(root.get_child_by_name('key').get_name(),
                         root.__getitem__('key').get_name())

    def test_getter_child_text(self):
        """Tests NaElement having no children"""
        root = netapp_api.NaElement('root')
        root.set_content('FAKE_CONTENT')
        self.mock_object(root, 'get_child_by_name', return_value=root)

        self.assertEqual('FAKE_CONTENT',
                         root.__getitem__('root'))

    def test_getter_child_attr(self):
        """Tests invalid key raises exception"""
        root = netapp_api.NaElement('root')
        root.add_attr('val', 'FAKE_VALUE')

        self.assertEqual('FAKE_VALUE',
                         root.__getitem__('val'))

    def test_add_node_with_children(self):
        """Tests adding a child node with its own children"""
        root = netapp_api.NaElement('root')
        self.mock_object(netapp_api.NaElement,
                         'create_node_with_children',
                         return_value=zapi_fakes.FAKE_INVOKE_DATA)
        mock_invoke = self.mock_object(root, 'add_child_elem')

        root.add_node_with_children('options')

        mock_invoke.assert_called_with(zapi_fakes.FAKE_INVOKE_DATA)

    def test_create_node_with_children(self):
        """Tests adding a child node with its own children"""
        root = netapp_api.NaElement('root')
        self.mock_object(root, 'add_new_child', return_value='abc')

        result_xml = str(root.create_node_with_children(
            'options', test1=zapi_fakes.FAKE_XML_STR,
            test2=zapi_fakes.FAKE_XML_STR))

        # No ordering is guaranteed for elements in this XML.
        self.assertTrue(result_xml.startswith("<options>"), result_xml)
        self.assertIn("<test1>abc</test1>", result_xml)
        self.assertIn("<test2>abc</test2>", result_xml)
        self.assertTrue(result_xml.rstrip().endswith("</options>"), result_xml)

    def test_add_new_child(self):
        """Tests adding a child node with its own children"""
        root = netapp_api.NaElement('root')
        self.mock_object(netapp_api.NaElement,
                         '_convert_entity_refs',
                         return_value=zapi_fakes.FAKE_INVOKE_DATA)

        root.add_new_child('options', zapi_fakes.FAKE_INVOKE_DATA)

        self.assertEqual(zapi_fakes.FAKE_XML2, root.to_string())

    def test_get_attr_names_empty_attr(self):
        """Tests _elements.attrib being empty"""
        root = netapp_api.NaElement('root')

        self.assertEqual([], root.get_attr_names())

    def test_get_attr_names(self):
        """Tests _elements.attrib being non-empty"""
        root = netapp_api.NaElement('root')
        root.add_attr('attr1', 'a1')
        root.add_attr('attr2', 'a2')

        self.assertEqual(['attr1', 'attr2'], root.get_attr_names())


@ddt.ddt
class SSHUtilTests(test.TestCase):
    """Test Cases for SSH API invocation."""

    def setUp(self):
        super(SSHUtilTests, self).setUp()
        self.mock_object(netapp_api.SSHUtil, '_init_ssh_pool')
        self.sshutil = netapp_api.SSHUtil('127.0.0.1',
                                          'fake_user',
                                          'fake_password')

    def test_execute_command(self):
        ssh = mock.Mock(paramiko.SSHClient)
        stdin, stdout, stderr = self._mock_ssh_channel_files(
            paramiko.ChannelFile)
        self.mock_object(ssh, 'exec_command',
                         return_value=(stdin, stdout, stderr))

        wait_on_stdout = self.mock_object(self.sshutil, '_wait_on_stdout')
        stdout_read = self.mock_object(stdout, 'read', return_value='')
        self.sshutil.execute_command(ssh, 'ls')

        wait_on_stdout.assert_called_once_with(stdout,
                                               netapp_api.SSHUtil.RECV_TIMEOUT)
        stdout_read.assert_called_once_with()

    def test_execute_read_exception(self):
        ssh = mock.Mock(paramiko.SSHClient)
        exec_command = self.mock_object(ssh, 'exec_command')
        exec_command.side_effect = paramiko.SSHException('Failure')
        wait_on_stdout = self.mock_object(self.sshutil, '_wait_on_stdout')

        self.assertRaises(paramiko.SSHException,
                          self.sshutil.execute_command, ssh, 'ls')
        wait_on_stdout.assert_not_called()

    @ddt.data(b'Password:',
              b'Password: ',
              b'Password: \n\n',
              b'Fake response \r\n Password: \n\n')
    def test_execute_command_with_prompt(self, response):
        ssh = mock.Mock(paramiko.SSHClient)
        stdin, stdout, stderr = self._mock_ssh_channel_files(paramiko.Channel)
        stdout_read = self.mock_object(stdout.channel, 'recv',
                                       return_value=response)
        stdin_write = self.mock_object(stdin, 'write')
        self.mock_object(ssh, 'exec_command',
                         return_value=(stdin, stdout, stderr))

        wait_on_stdout = self.mock_object(self.sshutil, '_wait_on_stdout')
        self.sshutil.execute_command_with_prompt(ssh, 'sudo ls',
                                                 'Password:', 'easypass')

        wait_on_stdout.assert_called_once_with(stdout,
                                               netapp_api.SSHUtil.RECV_TIMEOUT)
        stdout_read.assert_called_once_with(999)
        stdin_write.assert_called_once_with('easypass' + '\n')

    def test_execute_command_unexpected_response(self):
        ssh = mock.Mock(paramiko.SSHClient)
        stdin, stdout, stderr = self._mock_ssh_channel_files(paramiko.Channel)
        stdout_read = self.mock_object(stdout.channel, 'recv',
                                       return_value=b'bad response')
        self.mock_object(ssh, 'exec_command',
                         return_value=(stdin, stdout, stderr))

        wait_on_stdout = self.mock_object(self.sshutil, '_wait_on_stdout')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.sshutil.execute_command_with_prompt,
                          ssh, 'sudo ls', 'Password:', 'easypass')

        wait_on_stdout.assert_called_once_with(stdout,
                                               netapp_api.SSHUtil.RECV_TIMEOUT)
        stdout_read.assert_called_once_with(999)

    def test_wait_on_stdout(self):
        stdout = mock.Mock()
        stdout.channel = mock.Mock(paramiko.Channel)

        exit_status = self.mock_object(stdout.channel, 'exit_status_ready',
                                       return_value=False)
        self.sshutil._wait_on_stdout(stdout, 1)
        exit_status.assert_any_call()
        self.assertGreater(exit_status.call_count, 2)

    def _mock_ssh_channel_files(self, channel):
        stdin = mock.Mock()
        stdin.channel = mock.Mock(channel)
        stdout = mock.Mock()
        stdout.channel = mock.Mock(channel)
        stderr = mock.Mock()
        stderr.channel = mock.Mock(channel)
        return stdin, stdout, stderr


@ddt.ddt
class NetAppRestApiServerTests(test.TestCase):
    """Test case for NetApp REST API server methods."""
    def setUp(self):
        self.rest_client = netapp_api.RestNaServer('127.0.0.1')
        super(NetAppRestApiServerTests, self).setUp()

    @ddt.data(None, 'my_cert')
    def test__init__ssl_verify(self, ssl_cert_path):
        client = netapp_api.RestNaServer('127.0.0.1',
                                         ssl_cert_path=ssl_cert_path)

        if ssl_cert_path:
            self.assertEqual(ssl_cert_path, client._ssl_verify)
        else:
            self.assertTrue(client._ssl_verify)

    @ddt.data(None, 'ftp')
    def test_set_transport_type_value_error(self, transport_type):
        self.assertRaises(ValueError, self.rest_client.set_transport_type,
                          transport_type)

    @ddt.data('http', 'https')
    def test_set_transport_type_valid(self, transport_type):
        """Tests setting a valid transport type"""
        self.rest_client.set_transport_type(transport_type)
        self.assertEqual(self.rest_client._protocol, transport_type)

    @ddt.data('!&', '80na', '')
    def test_set_port__value_error(self, port):
        self.assertRaises(ValueError, self.rest_client.set_port, port)

    @ddt.data(
        {'port': None, 'protocol': 'http', 'expected_port': '80'},
        {'port': None, 'protocol': 'https', 'expected_port': '443'},
        {'port': '111', 'protocol': None, 'expected_port': '111'}
    )
    @ddt.unpack
    def test_set_port(self, port, protocol, expected_port):
        self.rest_client._protocol = protocol

        self.rest_client.set_port(port=port)

        self.assertEqual(expected_port, self.rest_client._port)

    @ddt.data('!&', '80na', '')
    def test_set_timeout_value_error(self, timeout):
        self.assertRaises(ValueError, self.rest_client.set_timeout, timeout)

    @ddt.data({'params': {'major': 1, 'minor': '20a'}},
              {'params': {'major': '20a', 'minor': 1}},
              {'params': {'major': '!*', 'minor': '20a'}})
    @ddt.unpack
    def test_set_api_version_value_error(self, params):
        self.assertRaises(ValueError, self.rest_client.set_api_version,
                          **params)

    def test_set_api_version_valid(self):
        args = {'major': '20', 'minor': 1}

        self.rest_client.set_api_version(**args)

        self.assertEqual(self.rest_client._api_major_version, 20)
        self.assertEqual(self.rest_client._api_minor_version, 1)
        self.assertEqual(self.rest_client._api_version, "20.1")

    def test_invoke_successfully_naapi_error(self):
        self.mock_object(self.rest_client, '_build_headers', return_value={})
        self.mock_object(self.rest_client, '_get_base_url', return_value='')
        self.mock_object(self.rest_client, 'send_http_request',
                         return_value=(10, zapi_fakes.ERROR_RESPONSE_REST))

        self.assertRaises(netapp_api.NaApiError,
                          self.rest_client.invoke_successfully,
                          zapi_fakes.FAKE_ACTION_ENDPOINT, 'get')

    @ddt.data(None, {'fields': 'fake_fields'})
    def test_invoke_successfully(self, query):
        mock_build_header = self.mock_object(
            self.rest_client, '_build_headers',
            return_value=zapi_fakes.FAKE_HEADERS)
        mock_base = self.mock_object(
            self.rest_client, '_get_base_url',
            return_value=zapi_fakes.FAKE_BASE_ENDPOINT)
        mock_add_query = self.mock_object(
            self.rest_client, '_add_query_params_to_url',
            return_value=zapi_fakes.FAKE_ACTION_ENDPOINT)
        http_code = 200
        mock_send_http = self.mock_object(
            self.rest_client, 'send_http_request',
            return_value=(http_code, zapi_fakes.NO_RECORDS_RESPONSE_REST))

        code, response = self.rest_client.invoke_successfully(
            zapi_fakes.FAKE_ACTION_ENDPOINT, 'get', body=zapi_fakes.FAKE_BODY,
            query=query, enable_tunneling=True)

        self.assertEqual(response, zapi_fakes.NO_RECORDS_RESPONSE_REST)
        self.assertEqual(code, http_code)
        mock_build_header.assert_called_once_with(True)
        mock_base.assert_called_once_with()
        self.assertEqual(bool(query), mock_add_query.called)
        mock_send_http.assert_called_once_with(
            'get',
            zapi_fakes.FAKE_BASE_ENDPOINT + zapi_fakes.FAKE_ACTION_ENDPOINT,
            zapi_fakes.FAKE_BODY, zapi_fakes.FAKE_HEADERS)

    @ddt.data(
        {'error': requests.HTTPError(), 'raised': netapp_api.NaApiError},
        {'error': Exception, 'raised': netapp_api.NaApiError})
    @ddt.unpack
    def test_send_http_request_http_error(self, error, raised):
        self.mock_object(netapp_api, 'LOG')
        self.mock_object(self.rest_client, '_build_session')
        self.rest_client._session = mock.Mock()
        self.mock_object(
            self.rest_client, '_get_request_method', mock.Mock(
                return_value=mock.Mock(side_effect=error)))

        self.assertRaises(raised, self.rest_client.send_http_request,
                          'get', zapi_fakes.FAKE_ACTION_ENDPOINT,
                          zapi_fakes.FAKE_BODY, zapi_fakes.FAKE_HEADERS)

    @ddt.data(
        {
            'resp_content': zapi_fakes.NO_RECORDS_RESPONSE_REST,
            'body': zapi_fakes.FAKE_BODY,
            'timeout': 10,
        },
        {
            'resp_content': zapi_fakes.NO_RECORDS_RESPONSE_REST,
            'body': zapi_fakes.FAKE_BODY,
            'timeout': None,
        },
        {
            'resp_content': zapi_fakes.NO_RECORDS_RESPONSE_REST,
            'body': None,
            'timeout': None,
        },
        {
            'resp_content': None,
            'body': None,
            'timeout': None,
        }
    )
    @ddt.unpack
    def test_send_http_request(self, resp_content, body, timeout):
        if timeout:
            self.rest_client._timeout = timeout
        self.mock_object(netapp_api, 'LOG')
        mock_json_dumps = self.mock_object(
            jsonutils, 'dumps', mock.Mock(return_value='fake_dump_body'))
        mock_build_session = self.mock_object(
            self.rest_client, '_build_session')
        _mock_session = mock.Mock()
        self.rest_client._session = _mock_session
        response = mock.Mock()
        response.content = resp_content
        response.status_code = 10
        mock_post = mock.Mock(return_value=response)
        mock_get_request_method = self.mock_object(
            self.rest_client, '_get_request_method', mock.Mock(
                return_value=mock_post))
        mock_json_loads = self.mock_object(
            jsonutils, 'loads',
            mock.Mock(return_value='fake_loads_response'))

        code, res = self.rest_client.send_http_request(
            'post', zapi_fakes.FAKE_ACTION_ENDPOINT,
            body, zapi_fakes.FAKE_HEADERS)

        expected_res = 'fake_loads_response' if resp_content else {}
        self.assertEqual(expected_res, res)
        self.assertEqual(10, code)
        self.assertEqual(bool(body), mock_json_dumps.called)
        self.assertEqual(bool(resp_content), mock_json_loads.called)
        mock_build_session.assert_called_once_with(zapi_fakes.FAKE_HEADERS)
        mock_get_request_method.assert_called_once_with('post', _mock_session)
        expected_data = 'fake_dump_body' if body else {}
        if timeout:
            mock_post.assert_called_once_with(
                zapi_fakes.FAKE_ACTION_ENDPOINT, data=expected_data,
                timeout=timeout)
        else:
            mock_post.assert_called_once_with(zapi_fakes.FAKE_ACTION_ENDPOINT,
                                              data=expected_data)

    @ddt.data(
        {'host': '192.168.1.0', 'port': '80', 'protocol': 'http'},
        {'host': '0.0.0.0', 'port': '443', 'protocol': 'https'},
        {'host': '::ffff:8', 'port': '80', 'protocol': 'http'},
        {'host': 'fdf8:f53b:82e4::53', 'port': '443', 'protocol': 'https'})
    @ddt.unpack
    def test__get_base_url(self, host, port, protocol):
        client = netapp_api.RestNaServer(host, port=port,
                                         transport_type=protocol)
        expected_host = f'[{host}]' if ':' in host else host
        expected_url = '%s://%s:%s/api/' % (protocol, expected_host, port)

        url = client._get_base_url()

        self.assertEqual(expected_url, url)

    def test__add_query_params_to_url(self):
        formatted_url = self.rest_client._add_query_params_to_url(
            zapi_fakes.FAKE_ACTION_ENDPOINT, zapi_fakes.FAKE_HTTP_QUERY)

        expected_formatted_url = zapi_fakes.FAKE_ACTION_ENDPOINT
        expected_formatted_url += zapi_fakes.FAKE_FORMATTED_HTTP_QUERY
        self.assertEqual(expected_formatted_url, formatted_url)

    @ddt.data('post', 'get', 'put', 'delete', 'patch')
    def test_get_request_method(self, method):
        _mock_session = mock.Mock()
        _mock_session.post = mock.Mock()
        _mock_session.get = mock.Mock()
        _mock_session.put = mock.Mock()
        _mock_session.delete = mock.Mock()
        _mock_session.patch = mock.Mock()

        res = self.rest_client._get_request_method(method, _mock_session)

        expected_method = getattr(_mock_session, method)
        self.assertEqual(expected_method, res)

    def test__str__(self):
        fake_host = 'fake_host'
        client = netapp_api.RestNaServer(fake_host)

        expected_str = "server: %s" % fake_host
        self.assertEqual(expected_str, str(client))

    def test_get_transport_type(self):
        expected_protocol = 'fake_protocol'
        self.rest_client._protocol = expected_protocol

        res = self.rest_client.get_transport_type()

        self.assertEqual(expected_protocol, res)

    @ddt.data(None, ('1', '0'))
    def test_get_api_version(self, api_version):
        if api_version:
            self.rest_client._api_version = str(api_version)
            (self.rest_client._api_major_version, _) = api_version
            (_, self.rest_client._api_minor_version) = api_version

        res = self.rest_client.get_api_version()

        self.assertEqual(api_version, res)

    @ddt.data(None, '9.10')
    def test_get_ontap_version(self, ontap_version):
        if ontap_version:
            self.rest_client._ontap_version = ontap_version

        res = self.rest_client.get_ontap_version()

        self.assertEqual(ontap_version, res)

    def test_set_vserver(self):
        expected_vserver = 'fake_vserver'
        self.rest_client.set_vserver(expected_vserver)

        self.assertEqual(expected_vserver, self.rest_client._vserver)

    def test_get_vserver(self):
        expected_vserver = 'fake_vserver'
        self.rest_client._vserver = expected_vserver

        res = self.rest_client.get_vserver()

        self.assertEqual(expected_vserver, res)

    def test__build_session(self):
        fake_session = mock.Mock()
        mock_requests_session = self.mock_object(
            requests, 'Session', mock.Mock(return_value=fake_session))
        mock_auth = self.mock_object(
            self.rest_client, '_create_basic_auth_handler',
            mock.Mock(return_value='fake_auth'))
        self.rest_client._ssl_verify = 'fake_ssl'

        self.rest_client._build_session(zapi_fakes.FAKE_HEADERS)

        self.assertEqual(fake_session, self.rest_client._session)
        self.assertEqual('fake_auth', self.rest_client._session.auth)
        self.assertEqual('fake_ssl', self.rest_client._session.verify)
        self.assertEqual(zapi_fakes.FAKE_HEADERS,
                         self.rest_client._session.headers)
        mock_requests_session.assert_called_once_with()
        mock_auth.assert_called_once_with()

    @ddt.data(True, False)
    def test__build_headers(self, enable_tunneling):
        self.rest_client._vserver = zapi_fakes.VSERVER_NAME

        res = self.rest_client._build_headers(enable_tunneling)

        expected = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        if enable_tunneling:
            expected["X-Dot-SVM-Name"] = zapi_fakes.VSERVER_NAME
        self.assertEqual(expected, res)

    def test__create_basic_auth_handler(self):
        username = 'fake_username'
        password = 'fake_password'
        client = netapp_api.RestNaServer('10.1.1.1', username=username,
                                         password=password)

        res = client._create_basic_auth_handler()

        expected = auth.HTTPBasicAuth(username, password)
        self.assertEqual(expected.__dict__, res.__dict__)
