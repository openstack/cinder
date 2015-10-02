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
"""
Tests for NetApp API layer
"""
import ddt
from lxml import etree
import mock
import six
from six.moves import urllib

from cinder import exception
from cinder.i18n import _
from cinder import test
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

        self.assertTrue(mock_invoke.call_args in expected_call_args)

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
        """Tests Value Error on setting non-integer version"""
        self.assertRaises(ValueError, self.root.set_api_version, **params)

    def test_set_api_version_valid(self):
        """Tests Value Error on setting non-integer version"""
        args = {'major': '20', 'minor': 1}

        expected_call_args_list = [mock.call('20'), mock.call(1)]

        mock_invoke = self.mock_object(six, 'text_type',
                                       mock.Mock(return_value='str'))
        self.root.set_api_version(**args)

        self.assertEqual(expected_call_args_list, mock_invoke.call_args_list)

    @ddt.data({'params': {'result': zapi_fakes.FAKE_RESULT_API_ERR_REASON}},
              {'params': {'result': zapi_fakes.FAKE_RESULT_API_ERRNO_INVALID}},
              {'params': {'result': zapi_fakes.FAKE_RESULT_API_ERRNO_VALID}})
    @ddt.unpack
    def test_invoke_successfully_naapi_error(self, params):
        """Tests invoke successfully raising NaApiError"""
        self.mock_object(self.root, 'invoke_elem',
                         mock.Mock(return_value=params['result']))

        self.assertRaises(netapp_api.NaApiError,
                          self.root.invoke_successfully,
                          zapi_fakes.FAKE_NA_ELEMENT)

    def test_invoke_successfully_no_error(self):
        """Tests invoke successfully with no errors"""
        self.mock_object(self.root, 'invoke_elem', mock.Mock(
            return_value=zapi_fakes.FAKE_RESULT_SUCCESS))

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
                         mock.Mock(return_value=zapi_fakes.FAKE_XML_STR))
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
        mock_invoke = self.mock_object(etree, 'XML', mock.Mock(
            return_value='xml'))

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
    def test_invoke_elem_value_error(self, na_element):
        """Tests whether invalid NaElement parameter causes error"""

        self.assertRaises(ValueError, self.root.invoke_elem, na_element)

    def test_invoke_elem_http_error(self):
        """Tests handling of HTTPError"""
        na_element = zapi_fakes.FAKE_NA_ELEMENT
        self.mock_object(self.root, '_create_request', mock.Mock(
            return_value=('abc', zapi_fakes.FAKE_NA_ELEMENT)))
        self.mock_object(netapp_api, 'LOG')
        self.root._opener = zapi_fakes.FAKE_HTTP_OPENER
        self.mock_object(self.root, '_build_opener')
        self.mock_object(self.root._opener, 'open', mock.Mock(
            side_effect=urllib.error.HTTPError(url='', hdrs='',
                                               fp=None, code='401',
                                               msg='httperror')))

        self.assertRaises(netapp_api.NaApiError, self.root.invoke_elem,
                          na_element)

    def test_invoke_elem_unknown_exception(self):
        """Tests handling of Unknown Exception"""
        na_element = zapi_fakes.FAKE_NA_ELEMENT
        self.mock_object(self.root, '_create_request', mock.Mock(
            return_value=('abc', zapi_fakes.FAKE_NA_ELEMENT)))
        self.mock_object(netapp_api, 'LOG')
        self.root._opener = zapi_fakes.FAKE_HTTP_OPENER
        self.mock_object(self.root, '_build_opener')
        self.mock_object(self.root._opener, 'open', mock.Mock(
            side_effect=Exception))

        self.assertRaises(netapp_api.NaApiError, self.root.invoke_elem,
                          na_element)

    def test_invoke_elem_valid(self):
        """Tests the method invoke_elem with valid parameters"""
        na_element = zapi_fakes.FAKE_NA_ELEMENT
        self.root._trace = True
        self.mock_object(self.root, '_create_request', mock.Mock(
            return_value=('abc', zapi_fakes.FAKE_NA_ELEMENT)))
        self.mock_object(netapp_api, 'LOG')
        self.root._opener = zapi_fakes.FAKE_HTTP_OPENER
        self.mock_object(self.root, '_build_opener')
        self.mock_object(self.root, '_get_result', mock.Mock(
            return_value=zapi_fakes.FAKE_NA_ELEMENT))
        opener_mock = self.mock_object(
            self.root._opener, 'open', mock.Mock())
        opener_mock.read.side_effect = ['resp1', 'resp2']

        self.root.invoke_elem(na_element)


class NetAppApiElementTransTests(test.TestCase):
    """Test case for NetApp API element translations."""

    def setUp(self):
        super(NetAppApiElementTransTests, self).setUp()

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
        l = root.get_child_by_name('l')
        self.assertIsInstance(l, netapp_api.NaElement)
        t = root.get_child_by_name('t')
        self.assertIsInstance(t, netapp_api.NaElement)
        for le in l.get_children():
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
        self.mock_object(root, 'get_child_by_name',
                         mock.Mock(return_value=None))
        self.mock_object(root, 'has_attr',
                         mock.Mock(return_value=None))

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
        self.mock_object(root, 'get_child_by_name',
                         mock.Mock(return_value=root))

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
                         mock.Mock(return_value=zapi_fakes.FAKE_INVOKE_DATA))
        mock_invoke = self.mock_object(root, 'add_child_elem')

        root.add_node_with_children('options')

        mock_invoke.assert_called_with(zapi_fakes.FAKE_INVOKE_DATA)

    def test_create_node_with_children(self):
        """Tests adding a child node with its own children"""
        root = netapp_api.NaElement('root')
        self.mock_object(root, 'add_new_child', mock.Mock(return_value='abc'))

        self.assertEqual(zapi_fakes.FAKE_XML1, root.create_node_with_children(
            'options', test1=zapi_fakes.FAKE_XML_STR,
            test2=zapi_fakes.FAKE_XML_STR).to_string())

    def test_add_new_child(self):
        """Tests adding a child node with its own children"""
        root = netapp_api.NaElement('root')
        self.mock_object(netapp_api.NaElement,
                         '_convert_entity_refs',
                         mock.Mock(return_value=zapi_fakes.FAKE_INVOKE_DATA))

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
class NetAppApiInvokeTests(test.TestCase):
    """Test Cases for api request creation and invocation"""

    def setUp(self):
        super(NetAppApiInvokeTests, self).setUp()

    @ddt.data(None, zapi_fakes.FAKE_XML_STR)
    def test_invoke_api_invalid_input(self, na_server):
        """Tests Zapi Invocation Type Error"""
        na_server = None
        api_name = zapi_fakes.FAKE_API_NAME
        invoke_generator = netapp_api.invoke_api(na_server, api_name)

        self.assertRaises(exception.InvalidInput, invoke_generator.next)

    @ddt.data({'params': {'na_server': zapi_fakes.FAKE_NA_SERVER,
                          'api_name': zapi_fakes.FAKE_API_NAME}},
              {'params': {'na_server': zapi_fakes.FAKE_NA_SERVER,
                          'api_name': zapi_fakes.FAKE_API_NAME,
                          'api_family': 'cm',
                          'query': zapi_fakes.FAKE_QUERY,
                          'des_result': zapi_fakes.FAKE_DES_ATTR,
                          'additional_elems': None,
                          'is_iter': True}})
    @ddt.unpack
    def test_invoke_api_valid(self, params):
        """Test invoke_api with valid naserver"""
        self.mock_object(netapp_api, 'create_api_request', mock.Mock(
            return_value='success'))
        self.mock_object(netapp_api.NaServer, 'invoke_successfully',
                         mock.Mock(
                             return_value=netapp_api.NaElement('success')))

        invoke_generator = netapp_api.invoke_api(**params)

        self.assertEqual(netapp_api.NaElement('success').to_string(),
                         next(invoke_generator).to_string())

    def test_create_api_request(self):
        """"Tests creating api request"""
        self.mock_object(netapp_api.NaElement, 'translate_struct')
        self.mock_object(netapp_api.NaElement, 'add_child_elem')

        params = {'api_name': zapi_fakes.FAKE_API_NAME,
                  'query': zapi_fakes.FAKE_QUERY,
                  'des_result': zapi_fakes.FAKE_DES_ATTR,
                  'additional_elems': zapi_fakes.FAKE_XML_STR,
                  'is_iter': True,
                  'tag': 'tag'}

        self.assertEqual(zapi_fakes.FAKE_API_NAME_ELEMENT.to_string(),
                         netapp_api.create_api_request(**params).to_string())
