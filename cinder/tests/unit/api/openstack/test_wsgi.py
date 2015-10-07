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

import inspect

import webob

from cinder.api.openstack import wsgi
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes


class RequestTest(test.TestCase):
    def test_content_type_missing(self):
        request = wsgi.Request.blank('/tests/123', method='POST')
        request.body = b"<body />"
        self.assertIsNone(request.get_content_type())

    def test_content_type_unsupported(self):
        request = wsgi.Request.blank('/tests/123', method='POST')
        request.headers["Content-Type"] = "text/html"
        request.body = b"asdf<br />"
        self.assertRaises(exception.InvalidContentType,
                          request.get_content_type)

    def test_content_type_with_charset(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Content-Type"] = "application/json; charset=UTF-8"
        result = request.get_content_type()
        self.assertEqual("application/json", result)

    def test_content_type_from_accept(self):
        for content_type in ('application/xml',
                             'application/vnd.openstack.volume+xml',
                             'application/json',
                             'application/vnd.openstack.volume+json'):
            request = wsgi.Request.blank('/tests/123')
            request.headers["Accept"] = content_type
            result = request.best_match_content_type()
            self.assertEqual(content_type, result)

    def test_content_type_from_accept_best(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = "application/xml, application/json"
        result = request.best_match_content_type()
        self.assertEqual("application/json", result)

        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = ("application/json; q=0.3, "
                                     "application/xml; q=0.9")
        result = request.best_match_content_type()
        self.assertEqual("application/xml", result)

    def test_content_type_from_query_extension(self):
        request = wsgi.Request.blank('/tests/123.xml')
        result = request.best_match_content_type()
        self.assertEqual("application/xml", result)

        request = wsgi.Request.blank('/tests/123.json')
        result = request.best_match_content_type()
        self.assertEqual("application/json", result)

        request = wsgi.Request.blank('/tests/123.invalid')
        result = request.best_match_content_type()
        self.assertEqual("application/json", result)

    def test_content_type_accept_and_query_extension(self):
        request = wsgi.Request.blank('/tests/123.xml')
        request.headers["Accept"] = "application/json"
        result = request.best_match_content_type()
        self.assertEqual("application/xml", result)

    def test_content_type_accept_default(self):
        request = wsgi.Request.blank('/tests/123.unsupported')
        request.headers["Accept"] = "application/unsupported1"
        result = request.best_match_content_type()
        self.assertEqual("application/json", result)

    def test_best_match_language(self):
        # Test that we are actually invoking language negotiation by webob
        request = wsgi.Request.blank('/')
        accepted = 'unknown-lang'
        request.headers = {'Accept-Language': accepted}

        def fake_best_match(self, offers, default_match=None):
            # Match would return None, if requested lang is not found
            return None

        self.stubs.SmartSet(request.accept_language,
                            'best_match', fake_best_match)

        self.assertIsNone(request.best_match_language())
        # If accept-language is not included or empty, match should be None
        request.headers = {'Accept-Language': ''}
        self.assertIsNone(request.best_match_language())
        request.headers.pop('Accept-Language')
        self.assertIsNone(request.best_match_language())

    def test_cache_and_retrieve_resources(self):
        request = wsgi.Request.blank('/foo')
        # Test that trying to retrieve a cached object on
        # an empty cache fails gracefully
        self.assertIsNone(request.cached_resource())
        self.assertIsNone(request.cached_resource_by_id('r-0'))

        resources = []
        for x in range(3):
            resources.append({'id': 'r-%s' % x})

        # Cache an empty list of resources using the default name
        request.cache_resource([])
        self.assertEqual({}, request.cached_resource())
        self.assertIsNone(request.cached_resource('r-0'))
        # Cache some resources
        request.cache_resource(resources[:2])
        # Cache  one resource
        request.cache_resource(resources[2])
        # Cache  a different resource name
        other_resource = {'id': 'o-0'}
        request.cache_resource(other_resource, name='other-resource')

        self.assertEqual(resources[0], request.cached_resource_by_id('r-0'))
        self.assertEqual(resources[1], request.cached_resource_by_id('r-1'))
        self.assertEqual(resources[2], request.cached_resource_by_id('r-2'))
        self.assertIsNone(request.cached_resource_by_id('r-3'))
        self.assertEqual({'r-0': resources[0],
                          'r-1': resources[1],
                          'r-2': resources[2]}, request.cached_resource())
        self.assertEqual(other_resource,
                         request.cached_resource_by_id('o-0',
                                                       name='other-resource'))

    def test_cache_and_retrieve_volumes(self):
        self._test_cache_and_retrieve_resources('volume')

    def test_cache_and_retrieve_volume_types(self):
        self._test_cache_and_retrieve_resources('volume_type')

    def test_cache_and_retrieve_snapshots(self):
        self._test_cache_and_retrieve_resources('snapshot')

    def test_cache_and_retrieve_backups(self):
        self._test_cache_and_retrieve_resources('backup')

    def _test_cache_and_retrieve_resources(self, resource_name):
        """Generic helper for cache tests."""
        cache_all_func = 'cache_db_%ss' % resource_name
        cache_one_func = 'cache_db_%s' % resource_name
        get_db_all_func = 'get_db_%ss' % resource_name
        get_db_one_func = 'get_db_%s' % resource_name

        r = wsgi.Request.blank('/foo')
        resources = []
        for x in range(3):
            resources.append({'id': 'id%s' % x})

        # Store 2
        getattr(r, cache_all_func)(resources[:2])
        # Store 1
        getattr(r, cache_one_func)(resources[2])

        self.assertEqual(resources[0], getattr(r, get_db_one_func)('id0'))
        self.assertEqual(resources[1], getattr(r, get_db_one_func)('id1'))
        self.assertEqual(resources[2], getattr(r, get_db_one_func)('id2'))
        self.assertIsNone(getattr(r, get_db_one_func)('id3'))
        self.assertEqual({'id0': resources[0],
                          'id1': resources[1],
                          'id2': resources[2]}, getattr(r, get_db_all_func)())


class ActionDispatcherTest(test.TestCase):
    def test_dispatch(self):
        serializer = wsgi.ActionDispatcher()
        serializer.create = lambda x: 'pants'
        self.assertEqual('pants', serializer.dispatch({}, action='create'))

    def test_dispatch_action_None(self):
        serializer = wsgi.ActionDispatcher()
        serializer.create = lambda x: 'pants'
        serializer.default = lambda x: 'trousers'
        self.assertEqual('trousers', serializer.dispatch({}, action=None))

    def test_dispatch_default(self):
        serializer = wsgi.ActionDispatcher()
        serializer.create = lambda x: 'pants'
        serializer.default = lambda x: 'trousers'
        self.assertEqual('trousers', serializer.dispatch({}, action='update'))


class DictSerializerTest(test.TestCase):
    def test_dispatch_default(self):
        serializer = wsgi.DictSerializer()
        self.assertEqual('', serializer.serialize({}, 'update'))


class XMLDictSerializerTest(test.TestCase):
    def test_xml(self):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_xml = b'<serversxmlns="asdf"><a>(2,3)</a></servers>'
        serializer = wsgi.XMLDictSerializer(xmlns="asdf")
        result = serializer.serialize(input_dict)
        result = result.replace(b'\n', b'').replace(b' ', b'')
        self.assertEqual(expected_xml, result)


class JSONDictSerializerTest(test.TestCase):
    def test_json(self):
        input_dict = dict(servers=dict(a=(2, 3)))
        expected_json = '{"servers":{"a":[2,3]}}'
        serializer = wsgi.JSONDictSerializer()
        result = serializer.serialize(input_dict)
        result = result.replace('\n', '').replace(' ', '')
        self.assertEqual(expected_json, result)


class TextDeserializerTest(test.TestCase):
    def test_dispatch_default(self):
        deserializer = wsgi.TextDeserializer()
        self.assertEqual({}, deserializer.deserialize({}, 'update'))


class JSONDeserializerTest(test.TestCase):
    def test_json(self):
        data = """{"a": {
                "a1": "1",
                "a2": "2",
                "bs": ["1", "2", "3", {"c": {"c1": "1"}}],
                "d": {"e": "1"},
                "f": "1"}}"""
        as_dict = {
            'body': {
                'a': {
                    'a1': '1',
                    'a2': '2',
                    'bs': ['1', '2', '3', {'c': {'c1': '1'}}],
                    'd': {'e': '1'},
                    'f': '1',
                },
            },
        }
        deserializer = wsgi.JSONDeserializer()
        self.assertEqual(as_dict, deserializer.deserialize(data))


class XMLDeserializerTest(test.TestCase):
    def test_xml(self):
        xml = """
            <a a1="1" a2="2">
              <bs><b>1</b><b>2</b><b>3</b><b><c c1="1"/></b></bs>
              <d><e>1</e></d>
              <f>1</f>
            </a>
            """.strip()
        as_dict = {
            'body': {
                'a': {
                    'a1': '1',
                    'a2': '2',
                    'bs': ['1', '2', '3', {'c': {'c1': '1'}}],
                    'd': {'e': '1'},
                    'f': '1',
                },
            },
        }
        metadata = {'plurals': {'bs': 'b', 'ts': 't'}}
        deserializer = wsgi.XMLDeserializer(metadata=metadata)
        self.assertEqual(as_dict, deserializer.deserialize(xml))

    def test_xml_empty(self):
        xml = """<a></a>"""
        as_dict = {"body": {"a": {}}}
        deserializer = wsgi.XMLDeserializer()
        self.assertEqual(as_dict, deserializer.deserialize(xml))


class MetadataXMLDeserializerTest(test.TestCase):
    def test_xml_meta_parsing_special_character(self):
        """Test XML meta parsing with special characters.

        Test that when a SaxParser splits a string containing special
        characters into multiple childNodes there are no issues extracting
        the text.
        """
        meta_xml_str = """
            <metadata>
                <meta key="key3">value&amp;3</meta>
                <meta key="key2">value2</meta>
                <meta key="key1">value1</meta>
            </metadata>
            """.strip()
        meta_expected = {'key1': 'value1',
                         'key2': 'value2',
                         'key3': 'value&3'}
        meta_deserializer = wsgi.MetadataXMLDeserializer()
        document = wsgi.utils.safe_minidom_parse_string(meta_xml_str)
        root_node = document.childNodes[0]
        meta_extracted = meta_deserializer.extract_metadata(root_node)
        self.assertEqual(meta_expected, meta_extracted)


class ResourceTest(test.TestCase):
    def test_resource_call(self):
        class Controller(object):
            def index(self, req):
                return 'off'

        req = webob.Request.blank('/tests')
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        self.assertEqual(b'off', response.body)
        self.assertEqual(200, response.status_int)

    def test_resource_not_authorized(self):
        class Controller(object):
            def index(self, req):
                raise exception.NotAuthorized()

        req = webob.Request.blank('/tests')
        app = fakes.TestRouter(Controller())
        response = req.get_response(app)
        self.assertEqual(403, response.status_int)

    def test_dispatch(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        method, _extensions = resource.get_method(None, 'index', None, '')
        actual = resource.dispatch(method, None, {'pants': 'off'})
        expected = 'off'
        self.assertEqual(expected, actual)

    def test_get_method_undefined_controller_action(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(AttributeError, resource.get_method,
                          None, 'create', None, '')

    def test_get_method_action_json(self):
        class Controller(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        method, _extensions = resource.get_method(None, 'action',
                                                  'application/json',
                                                  '{"fooAction": true}')
        self.assertEqual(controller._action_foo, method)

    def test_get_method_action_xml(self):
        class Controller(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        method, _extensions = resource.get_method(
            None, 'action', 'application/xml', '<fooAction>true</fooAction>')
        self.assertEqual(controller._action_foo, method)

    def test_get_method_action_bad_body(self):
        class Controller(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(exception.MalformedRequestBody, resource.get_method,
                          None, 'action', 'application/json', '{}')

    def test_get_method_unknown_controller_action(self):
        class Controller(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(KeyError, resource.get_method,
                          None, 'action', 'application/json',
                          '{"barAction": true}')

    def test_get_method_action_method(self):
        class Controller(object):
            def action(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        method, _extensions = resource.get_method(None, 'action',
                                                  'application/xml',
                                                  '<fooAction>true</fooAction')
        self.assertEqual(controller.action, method)

    def test_get_action_args(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        env = {
            'wsgiorg.routing_args': [None, {
                'controller': None,
                'format': None,
                'action': 'update',
                'id': 12,
            }],
        }

        expected = {'action': 'update', 'id': 12}

        self.assertEqual(expected, resource.get_action_args(env))

    def test_get_body_bad_content(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        request = wsgi.Request.blank('/', method='POST')
        request.headers['Content-Type'] = 'application/none'
        request.body = b'foo'

        content_type, body = resource.get_body(request)
        self.assertIsNone(content_type)
        self.assertEqual('', body)

    def test_get_body_no_content_type(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        request = wsgi.Request.blank('/', method='POST')
        request.body = b'foo'

        content_type, body = resource.get_body(request)
        self.assertIsNone(content_type)
        self.assertEqual('', body)

    def test_get_body_no_content_body(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        request = wsgi.Request.blank('/', method='POST')
        request.headers['Content-Type'] = 'application/json'
        request.body = b''

        content_type, body = resource.get_body(request)
        self.assertIsNone(content_type)
        self.assertEqual('', body)

    def test_get_body(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        request = wsgi.Request.blank('/', method='POST')
        request.headers['Content-Type'] = 'application/json'
        request.body = b'foo'

        content_type, body = resource.get_body(request)
        self.assertEqual('application/json', content_type)
        self.assertEqual(b'foo', body)

    def test_deserialize_badtype(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertRaises(exception.InvalidContentType,
                          resource.deserialize,
                          controller.index, 'application/none', 'foo')

    def test_deserialize_default(self):
        class JSONDeserializer(object):
            def deserialize(self, body):
                return 'json'

        class XMLDeserializer(object):
            def deserialize(self, body):
                return 'xml'

        class Controller(object):
            @wsgi.deserializers(xml=XMLDeserializer)
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller, json=JSONDeserializer)

        obj = resource.deserialize(controller.index, 'application/json', 'foo')
        self.assertEqual('json', obj)

    def test_deserialize_decorator(self):
        class JSONDeserializer(object):
            def deserialize(self, body):
                return 'json'

        class XMLDeserializer(object):
            def deserialize(self, body):
                return 'xml'

        class Controller(object):
            @wsgi.deserializers(xml=XMLDeserializer)
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller, json=JSONDeserializer)

        obj = resource.deserialize(controller.index, 'application/xml', 'foo')
        self.assertEqual('xml', obj)

    def test_register_actions(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        class ControllerExtended(wsgi.Controller):
            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

            @wsgi.action('barAction')
            def _action_bar(self, req, id, body):
                return body

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertEqual({}, resource.wsgi_actions)

        extended = ControllerExtended()
        resource.register_actions(extended)
        self.assertEqual({'fooAction': extended._action_foo,
                          'barAction': extended._action_bar, },
                         resource.wsgi_actions)

    def test_register_extensions(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        class ControllerExtended(wsgi.Controller):
            @wsgi.extends
            def index(self, req, resp_obj, pants=None):
                return None

            @wsgi.extends(action='fooAction')
            def _action_foo(self, req, resp, id, body):
                return None

        controller = Controller()
        resource = wsgi.Resource(controller)
        self.assertEqual({}, resource.wsgi_extensions)
        self.assertEqual({}, resource.wsgi_action_extensions)

        extended = ControllerExtended()
        resource.register_extensions(extended)
        self.assertEqual({'index': [extended.index]}, resource.wsgi_extensions)
        self.assertEqual({'fooAction': [extended._action_foo]},
                         resource.wsgi_action_extensions)

    def test_get_method_extensions(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        class ControllerExtended(wsgi.Controller):
            @wsgi.extends
            def index(self, req, resp_obj, pants=None):
                return None

        controller = Controller()
        extended = ControllerExtended()
        resource = wsgi.Resource(controller)
        resource.register_extensions(extended)
        method, extensions = resource.get_method(None, 'index', None, '')
        self.assertEqual(controller.index, method)
        self.assertEqual([extended.index], extensions)

    def test_get_method_action_extensions(self):
        class Controller(wsgi.Controller):
            def index(self, req, pants=None):
                return pants

            @wsgi.action('fooAction')
            def _action_foo(self, req, id, body):
                return body

        class ControllerExtended(wsgi.Controller):
            @wsgi.extends(action='fooAction')
            def _action_foo(self, req, resp_obj, id, body):
                return None

        controller = Controller()
        extended = ControllerExtended()
        resource = wsgi.Resource(controller)
        resource.register_extensions(extended)
        method, extensions = resource.get_method(None, 'action',
                                                 'application/json',
                                                 '{"fooAction": true}')
        self.assertEqual(controller._action_foo, method)
        self.assertEqual([extended._action_foo], extensions)

    def test_get_method_action_whitelist_extensions(self):
        class Controller(wsgi.Controller):
            def index(self, req, pants=None):
                return pants

        class ControllerExtended(wsgi.Controller):
            @wsgi.action('create')
            def _create(self, req, body):
                pass

            @wsgi.action('delete')
            def _delete(self, req, id):
                pass

        controller = Controller()
        extended = ControllerExtended()
        resource = wsgi.Resource(controller)
        resource.register_actions(extended)

        method, extensions = resource.get_method(None, 'create',
                                                 'application/json',
                                                 '{"create": true}')
        self.assertEqual(extended._create, method)
        self.assertEqual([], extensions)

        method, extensions = resource.get_method(None, 'delete', None, None)
        self.assertEqual(extended._delete, method)
        self.assertEqual([], extensions)

    def test_pre_process_extensions_regular(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req, resp_obj):
            called.append(1)
            return None

        def extension2(req, resp_obj):
            called.append(2)
            return None

        extensions = [extension1, extension2]
        response, post = resource.pre_process_extensions(extensions, None, {})
        self.assertEqual([], called)
        self.assertIsNone(response)
        self.assertEqual([extension2, extension1], list(post))

    def test_pre_process_extensions_generator(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req):
            called.append('pre1')
            yield
            called.append('post1')

        def extension2(req):
            called.append('pre2')
            yield
            called.append('post2')

        extensions = [extension1, extension2]
        response, post = resource.pre_process_extensions(extensions, None, {})
        post = list(post)
        self.assertEqual(['pre1', 'pre2'], called)
        self.assertIsNone(response)
        self.assertEqual(2, len(post))
        self.assertTrue(inspect.isgenerator(post[0]))
        self.assertTrue(inspect.isgenerator(post[1]))

        for gen in post:
            try:
                gen.send(None)
            except StopIteration:
                continue

        self.assertEqual(['pre1', 'pre2', 'post2', 'post1'], called)

    def test_pre_process_extensions_generator_response(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req):
            called.append('pre1')
            yield 'foo'

        def extension2(req):
            called.append('pre2')

        extensions = [extension1, extension2]
        response, post = resource.pre_process_extensions(extensions, None, {})
        self.assertEqual(['pre1'], called)
        self.assertEqual('foo', response)
        self.assertEqual([], post)

    def test_post_process_extensions_regular(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req, resp_obj):
            called.append(1)
            return None

        def extension2(req, resp_obj):
            called.append(2)
            return None

        response = resource.post_process_extensions([extension2, extension1],
                                                    None, None, {})
        self.assertEqual([2, 1], called)
        self.assertIsNone(response)

    def test_post_process_extensions_regular_response(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req, resp_obj):
            called.append(1)
            return None

        def extension2(req, resp_obj):
            called.append(2)
            return 'foo'

        response = resource.post_process_extensions([extension2, extension1],
                                                    None, None, {})
        self.assertEqual([2], called)
        self.assertEqual('foo', response)

    def test_post_process_extensions_generator(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req):
            yield
            called.append(1)

        def extension2(req):
            yield
            called.append(2)

        ext1 = extension1(None)
        next(ext1)
        ext2 = extension2(None)
        next(ext2)

        response = resource.post_process_extensions([ext2, ext1],
                                                    None, None, {})

        self.assertEqual([2, 1], called)
        self.assertIsNone(response)

    def test_post_process_extensions_generator_response(self):
        class Controller(object):
            def index(self, req, pants=None):
                return pants

        controller = Controller()
        resource = wsgi.Resource(controller)

        called = []

        def extension1(req):
            yield
            called.append(1)

        def extension2(req):
            yield
            called.append(2)
            yield 'foo'

        ext1 = extension1(None)
        next(ext1)
        ext2 = extension2(None)
        next(ext2)

        response = resource.post_process_extensions([ext2, ext1],
                                                    None, None, {})

        self.assertEqual([2], called)
        self.assertEqual('foo', response)


class ResponseObjectTest(test.TestCase):
    def test_default_code(self):
        robj = wsgi.ResponseObject({})
        self.assertEqual(200, robj.code)

    def test_modified_code(self):
        robj = wsgi.ResponseObject({})
        robj._default_code = 202
        self.assertEqual(202, robj.code)

    def test_override_default_code(self):
        robj = wsgi.ResponseObject({}, code=404)
        self.assertEqual(404, robj.code)

    def test_override_modified_code(self):
        robj = wsgi.ResponseObject({}, code=404)
        robj._default_code = 202
        self.assertEqual(404, robj.code)

    def test_set_header(self):
        robj = wsgi.ResponseObject({})
        robj['Header'] = 'foo'
        self.assertEqual({'header': 'foo'}, robj.headers)

    def test_get_header(self):
        robj = wsgi.ResponseObject({})
        robj['Header'] = 'foo'
        self.assertEqual('foo', robj['hEADER'])

    def test_del_header(self):
        robj = wsgi.ResponseObject({})
        robj['Header'] = 'foo'
        del robj['hEADER']
        self.assertNotIn('header', robj.headers)

    def test_header_isolation(self):
        robj = wsgi.ResponseObject({})
        robj['Header'] = 'foo'
        hdrs = robj.headers
        hdrs['hEADER'] = 'bar'
        self.assertEqual('foo', robj['hEADER'])

    def test_default_serializers(self):
        robj = wsgi.ResponseObject({})
        self.assertEqual({}, robj.serializers)

    def test_bind_serializers(self):
        robj = wsgi.ResponseObject({}, json='foo')
        robj._bind_method_serializers(dict(xml='bar', json='baz'))
        self.assertEqual(dict(xml='bar', json='foo'), robj.serializers)

    def test_get_serializer(self):
        robj = wsgi.ResponseObject({}, json='json', xml='xml', atom='atom')
        for content_type, mtype in wsgi._MEDIA_TYPE_MAP.items():
            _mtype, serializer = robj.get_serializer(content_type)
            self.assertEqual(mtype, serializer)

    def test_get_serializer_defaults(self):
        robj = wsgi.ResponseObject({})
        default_serializers = dict(json='json', xml='xml', atom='atom')
        for content_type, mtype in wsgi._MEDIA_TYPE_MAP.items():
            self.assertRaises(exception.InvalidContentType,
                              robj.get_serializer, content_type)
            _mtype, serializer = robj.get_serializer(content_type,
                                                     default_serializers)
            self.assertEqual(mtype, serializer)

    def test_serialize(self):
        class JSONSerializer(object):
            def serialize(self, obj):
                return 'json'

        class XMLSerializer(object):
            def serialize(self, obj):
                return 'xml'

        class AtomSerializer(object):
            def serialize(self, obj):
                return 'atom'

        robj = wsgi.ResponseObject({}, code=202,
                                   json=JSONSerializer,
                                   xml=XMLSerializer,
                                   atom=AtomSerializer)
        robj['X-header1'] = 'header1'
        robj['X-header2'] = 'header2'

        for content_type, mtype in wsgi._MEDIA_TYPE_MAP.items():
            request = wsgi.Request.blank('/tests/123')
            response = robj.serialize(request, content_type)

            self.assertEqual(content_type, response.headers['Content-Type'])
            self.assertEqual('header1', response.headers['X-header1'])
            self.assertEqual('header2', response.headers['X-header2'])
            self.assertEqual(202, response.status_int)
            self.assertEqual(mtype, response.body.decode('utf-8'))


class ValidBodyTest(test.TestCase):

    def setUp(self):
        super(ValidBodyTest, self).setUp()
        self.controller = wsgi.Controller()

    def test_is_valid_body(self):
        body = {'foo': {}}
        self.assertTrue(self.controller.is_valid_body(body, 'foo'))

    def test_is_valid_body_none(self):
        wsgi.Resource(controller=None)
        self.assertFalse(self.controller.is_valid_body(None, 'foo'))

    def test_is_valid_body_empty(self):
        wsgi.Resource(controller=None)
        self.assertFalse(self.controller.is_valid_body({}, 'foo'))

    def test_is_valid_body_no_entity(self):
        wsgi.Resource(controller=None)
        body = {'bar': {}}
        self.assertFalse(self.controller.is_valid_body(body, 'foo'))

    def test_is_valid_body_malformed_entity(self):
        wsgi.Resource(controller=None)
        body = {'foo': 'bar'}
        self.assertFalse(self.controller.is_valid_body(body, 'foo'))

    def test_validate_string_length_with_name_too_long(self):
        name = 'a' * 256
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_string_length,
                          name, 'Name', min_length=1, max_length=255,
                          remove_whitespaces=False)

    def test_validate_string_length_with_name_contains_white_spaces(
            self):
        body = {'name': 'a' * 255 + "  "}
        self.controller.validate_string_length(
            body['name'], 'name', min_length=1, max_length=255,
            remove_whitespaces=True)

    def test_validate_name_and_description_with_name_too_long(self):
        body = {'name': 'a' * 256}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_name_and_description,
                          body)

    def test_validate_name_and_description_with_desc_too_long(self):
        body = {'description': 'a' * 256}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_name_and_description,
                          body)

    def test_validate_name_and_description_with_name_as_int(self):
        body = {'name': 1234}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_name_and_description,
                          body)

    def test_validate_name_and_description_with_desc_as_int(self):
        body = {'description': 1234}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_name_and_description,
                          body)

    def test_validate_name_and_description_with_name_zero_length(self):
        # NOTE(jdg): We allow zero length names currently, particularly
        # from Nova, changes to this require an API version bump
        body = {'name': ""}
        self.controller.validate_name_and_description(body)
        self.assertEqual('', body['name'])

    def test_validate_name_and_description_with_desc_zero_length(self):
        body = {'description': ""}
        self.controller.validate_name_and_description(body)
        self.assertEqual('', body['description'])

    def test_validate_name_and_description_with_name_contains_white_spaces(
            self):
        body = {'name': 'a' * 255 + "  "}
        self.controller.validate_name_and_description(body)
        self.assertEqual('a' * 255, body['name'])

    def test_validate_integer_greater_than_max_int_limit(self):
        value = (2 ** 31) + 1
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_integer,
                          value, 'limit', min_value=-1, max_value=(2 ** 31))

    def test_validate_integer_less_than_min_int_limit(self):
        value = -12
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_integer,
                          value, 'limit', min_value=-1, max_value=(2 ** 31))

    def test_validate_integer_invalid_limit(self):
        value = "should_be_int"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.validate_integer,
                          value, 'limit', min_value=-1, max_value=(2 ** 31))
