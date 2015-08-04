# Copyright (c) 2013 OpenStack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Tests for cinder.api.urlmap.py
"""

from cinder.api import urlmap
from cinder import test


class TestParseFunctions(test.TestCase):
    def test_unquote_header_value_without_quotes(self):
        arg = 'TestString'
        result = urlmap.unquote_header_value(arg)
        self.assertEqual(arg, result)

    def test_unquote_header_value_with_quotes(self):
        result = urlmap.unquote_header_value('"TestString"')
        self.assertEqual('TestString', result)

    def test_parse_list_header(self):
        arg = 'token, "quoted value"'
        result = urlmap.parse_list_header(arg)
        self.assertEqual(['token', 'quoted value'], result)

    def test_parse_options_header(self):
        result = urlmap.parse_options_header('Content-Type: text/html;'
                                             ' mimetype=text/html')
        self.assertEqual(('Content-Type:', {'mimetype': 'text/html'}), result)

    def test_parse_options_header_without_value(self):
        result = urlmap.parse_options_header(None)
        self.assertEqual(('', {}), result)


class TestAccept(test.TestCase):
    def test_best_match_ValueError(self):
        arg = 'text/html; q=some_invalud_value'
        accept = urlmap.Accept(arg)
        self.assertEqual((None, {}), accept.best_match(['text/html']))

    def test_best_match(self):
        arg = '*/*; q=0.7, application/json; q=0.7, text/html; q=-0.8'
        accept = urlmap.Accept(arg)
        self.assertEqual(('application/json', {'q': '0.7'}),
                         accept.best_match(['application/json',
                                            'application/xml', 'text/html']))

    def test_match_mask_one_asterisk(self):
        arg = 'text/*; q=0.7'
        accept = urlmap.Accept(arg)
        self.assertEqual(('text/html', {'q': '0.7'}),
                         accept.best_match(['text/html']))

    def test_match_mask_two_asterisk(self):
        arg = '*/*; q=0.7'
        accept = urlmap.Accept(arg)
        self.assertEqual(('text/html', {'q': '0.7'}),
                         accept.best_match(['text/html']))

    def test_match_mask_no_asterisk(self):
        arg = 'application/json; q=0.7'
        accept = urlmap.Accept(arg)
        self.assertEqual((None, {}), accept.best_match(['text/html']))

    def test_content_type_params(self):
        arg = "application/xml; q=0.1, application/json; q=0.2," \
              " text/html; q=0.3"
        accept = urlmap.Accept(arg)
        self.assertEqual({'q': '0.2'},
                         accept.content_type_params('application/json'))

    def test_content_type_params_wrong_content_type(self):
        arg = 'application/xml; q=0.1, text/html; q=0.1'
        accept = urlmap.Accept(arg)
        self.assertEqual({}, accept.content_type_params('application/json'))


class TestUrlMapFactory(test.TestCase):
    def setUp(self):
        super(TestUrlMapFactory, self).setUp()
        self.global_conf = {'not_found_app': 'app_global',
                            'domain hoobar.com port 10 /': 'some_app_global'}
        self.loader = self.mox.CreateMockAnything()

    def test_not_found_app_in_local_conf(self):
        local_conf = {'not_found_app': 'app_local',
                      'domain foobar.com port 20 /': 'some_app_local'}
        self.loader.get_app('app_local', global_conf=self.global_conf).\
            AndReturn('app_local_loader')
        self.loader.get_app('some_app_local', global_conf=self.global_conf).\
            AndReturn('some_app_loader')
        self.mox.ReplayAll()
        expected_urlmap = urlmap.URLMap(not_found_app='app_local_loader')
        expected_urlmap['http://foobar.com:20'] = 'some_app_loader'
        self.assertEqual(expected_urlmap,
                         urlmap.urlmap_factory(self.loader, self.global_conf,
                                               **local_conf))

    def test_not_found_app_not_in_local_conf(self):
        local_conf = {'domain foobar.com port 20 /': 'some_app_local'}
        self.loader.get_app('app_global', global_conf=self.global_conf).\
            AndReturn('app_global_loader')
        self.loader.get_app('some_app_local', global_conf=self.global_conf).\
            AndReturn('some_app_returned_by_loader')
        self.mox.ReplayAll()
        expected_urlmap = urlmap.URLMap(not_found_app='app_global_loader')
        expected_urlmap['http://foobar.com:20'] = 'some_app_returned'\
                                                  '_by_loader'
        self.assertEqual(expected_urlmap,
                         urlmap.urlmap_factory(self.loader, self.global_conf,
                                               **local_conf))

    def test_not_found_app_is_none(self):
        local_conf = {'not_found_app': None,
                      'domain foobar.com port 20 /': 'some_app_local'}
        self.loader.get_app('some_app_local', global_conf=self.global_conf).\
            AndReturn('some_app_returned_by_loader')
        self.mox.ReplayAll()
        expected_urlmap = urlmap.URLMap(not_found_app=None)
        expected_urlmap['http://foobar.com:20'] = 'some_app_returned'\
                                                  '_by_loader'
        self.assertEqual(expected_urlmap,
                         urlmap.urlmap_factory(self.loader, self.global_conf,
                                               **local_conf))


class TestURLMap(test.TestCase):
    def setUp(self):
        super(TestURLMap, self).setUp()
        self.urlmap = urlmap.URLMap()
        self.input_environ = {'HTTP_ACCEPT': "application/json;"
                              "version=9.0", 'REQUEST_METHOD': "GET",
                              'CONTENT_TYPE': 'application/xml',
                              'SCRIPT_NAME': '/scriptname',
                              'PATH_INFO': "/resource.xml"}
        self.environ = {'HTTP_ACCEPT': "application/json;"
                        "version=9.0", 'REQUEST_METHOD': "GET",
                        'CONTENT_TYPE': 'application/xml',
                        'SCRIPT_NAME': '/scriptname/app_url',
                        'PATH_INFO': "/resource.xml"}

    def test_match_with_applications(self):
        self.urlmap[('http://10.20.30.40:50', '/path/somepath')] = 'app'
        self.assertEqual((None, None),
                         self.urlmap._match('20.30.40.50', '20',
                                            'path/somepath'))

    def test_match_without_applications(self):
        self.assertEqual((None, None),
                         self.urlmap._match('host', 20, 'app_url/somepath'))

    def test_match_path_info_equals_app_url(self):
        self.urlmap[('http://20.30.40.50:60', '/app_url/somepath')] = 'app'
        self.assertEqual(('app', '/app_url/somepath'),
                         self.urlmap._match('http://20.30.40.50', '60',
                                            '/app_url/somepath'))

    def test_match_path_info_equals_app_url_many_app(self):
        self.urlmap[('http://20.30.40.50:60', '/path')] = 'app1'
        self.urlmap[('http://20.30.40.50:60', '/path/somepath')] = 'app2'
        self.urlmap[('http://20.30.40.50:60', '/path/somepath/elsepath')] = \
            'app3'
        self.assertEqual(('app3', '/path/somepath/elsepath'),
                         self.urlmap._match('http://20.30.40.50', '60',
                                            '/path/somepath/elsepath'))

    def test_set_script_name(self):
        app = self.mox.CreateMockAnything()
        start_response = self.mox.CreateMockAnything()
        app.__call__(self.environ, start_response).AndReturn('value')
        self.mox.ReplayAll()
        wrap = self.urlmap._set_script_name(app, '/app_url')
        self.assertEqual('value', wrap(self.input_environ, start_response))

    def test_munge_path(self):
        app = self.mox.CreateMockAnything()
        start_response = self.mox.CreateMockAnything()
        app.__call__(self.environ, start_response).AndReturn('value')
        self.mox.ReplayAll()
        wrap = self.urlmap._munge_path(app, '/app_url/resource.xml',
                                       '/app_url')
        self.assertEqual('value', wrap(self.input_environ, start_response))

    def test_content_type_strategy_without_version(self):
        self.assertEqual(None,
                         self.urlmap._content_type_strategy('host', 20,
                                                            self.environ))

    def test_content_type_strategy_with_version(self):
        environ = {'HTTP_ACCEPT': "application/vnd.openstack.melange+xml;"
                   "version=9.0", 'REQUEST_METHOD': "GET",
                   'PATH_INFO': "/resource.xml",
                   'CONTENT_TYPE': 'application/xml; version=2.0'}
        self.urlmap[('http://10.20.30.40:50', '/v2.0')] = 'app'
        self.mox.StubOutWithMock(self.urlmap, '_set_script_name')
        self.urlmap._set_script_name('app', '/v2.0').AndReturn('value')
        self.mox.ReplayAll()
        self.assertEqual('value',
                         self.urlmap._content_type_strategy(
                             'http://10.20.30.40', '50', environ))

    def test_path_strategy_wrong_path_info(self):
        self.assertEqual((None, None, None),
                         self.urlmap._path_strategy('http://10.20.30.40', '50',
                                                    '/resource'))

    def test_path_strategy_mime_type_only(self):
        self.assertEqual(('application/xml', None, None),
                         self.urlmap._path_strategy('http://10.20.30.40', '50',
                                                    '/resource.xml'))

    def test_path_strategy(self):
        self.urlmap[('http://10.20.30.40:50', '/path/elsepath/')] = 'app'
        self.mox.StubOutWithMock(self.urlmap, '_munge_path')
        self.urlmap._munge_path('app', '/path/elsepath/resource.xml',
                                '/path/elsepath').AndReturn('value')
        self.mox.ReplayAll()
        self.assertEqual(
            ('application/xml', 'value', '/path/elsepath'),
            self.urlmap._path_strategy('http://10.20.30.40', '50',
                                       '/path/elsepath/resource.xml'))

    def test_path_strategy_wrong_mime_type(self):
        self.urlmap[('http://10.20.30.40:50', '/path/elsepath/')] = 'app'
        self.mox.StubOutWithMock(self.urlmap, '_munge_path')
        self.urlmap._munge_path('app', '/path/elsepath/resource.abc',
                                '/path/elsepath').AndReturn('value')
        self.mox.ReplayAll()
        self.assertEqual(
            (None, 'value', '/path/elsepath'),
            self.urlmap._path_strategy('http://10.20.30.40', '50',
                                       '/path/elsepath/resource.abc'))

    def test_accept_strategy_version_not_in_params(self):
        environ = {'HTTP_ACCEPT': "application/xml; q=0.1, application/json; "
                   "q=0.2", 'REQUEST_METHOD': "GET",
                   'PATH_INFO': "/resource.xml",
                   'CONTENT_TYPE': 'application/xml; version=2.0'}
        self.assertEqual(('application/xml', None),
                         self.urlmap._accept_strategy('http://10.20.30.40',
                                                      '50',
                                                      environ,
                                                      ['application/xml']))

    def test_accept_strategy_version(self):
        environ = {'HTTP_ACCEPT': "application/xml; q=0.1; version=1.0,"
                   "application/json; q=0.2; version=2.0",
                   'REQUEST_METHOD': "GET", 'PATH_INFO': "/resource.xml",
                   'CONTENT_TYPE': 'application/xml; version=2.0'}
        self.urlmap[('http://10.20.30.40:50', '/v1.0')] = 'app'
        self.mox.StubOutWithMock(self.urlmap, '_set_script_name')
        self.urlmap._set_script_name('app', '/v1.0').AndReturn('value')
        self.mox.ReplayAll()
        self.assertEqual(('application/xml', 'value'),
                         self.urlmap._accept_strategy('http://10.20.30.40',
                                                      '50',
                                                      environ,
                                                      ['application/xml']))
