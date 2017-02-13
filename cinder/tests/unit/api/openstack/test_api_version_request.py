# Copyright 2014 IBM Corp.
# Copyright 2015 Clinton Knight
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

import ddt
import six

from cinder.api.openstack import api_version_request
from cinder import exception
from cinder import test


@ddt.ddt
class APIVersionRequestTests(test.TestCase):

    def test_init(self):

        result = api_version_request.APIVersionRequest()

        self.assertIsNone(result._ver_major)
        self.assertIsNone(result._ver_minor)

    def test_min_version(self):

        self.assertEqual(
            api_version_request.APIVersionRequest(
                api_version_request._MIN_API_VERSION),
            api_version_request.min_api_version())

    def test_max_api_version(self):

        self.assertEqual(
            api_version_request.APIVersionRequest(
                api_version_request._MAX_API_VERSION),
            api_version_request.max_api_version())

    @ddt.data(
        ('1.1', 1, 1),
        ('2.10', 2, 10),
        ('5.234', 5, 234),
        ('12.5', 12, 5),
        ('2.0', 2, 0),
        ('2.200', 2, 200)
    )
    @ddt.unpack
    def test_valid_version_strings(self, version_string, major, minor):

        request = api_version_request.APIVersionRequest(version_string)

        self.assertEqual(major, request._ver_major)
        self.assertEqual(minor, request._ver_minor)

    def test_null_version(self):
        v = api_version_request.APIVersionRequest()
        self.assertFalse(v)

    def test_not_null_version(self):
        v = api_version_request.APIVersionRequest('1.1')
        self.assertTrue(v)

    @ddt.data('2', '200', '2.1.4', '200.23.66.3', '5 .3', '5. 3',
              '5.03', '02.1', '2.001', '', ' 2.1', '2.1 ')
    def test_invalid_version_strings(self, version_string):

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest,
                          version_string)

    def test_cmpkey(self):
        request = api_version_request.APIVersionRequest('1.2')
        self.assertEqual((1, 2), request._cmpkey())

    def test_version_comparisons(self):
        v1 = api_version_request.APIVersionRequest('2.0')
        v2 = api_version_request.APIVersionRequest('2.5')
        v3 = api_version_request.APIVersionRequest('5.23')
        v4 = api_version_request.APIVersionRequest('2.0')
        v_null = api_version_request.APIVersionRequest()

        self.assertLess(v1, v2)
        self.assertLessEqual(v1, v2)
        self.assertGreater(v3, v2)
        self.assertGreaterEqual(v3, v2)
        self.assertNotEqual(v1, v2)
        self.assertEqual(v1, v4)
        self.assertNotEqual(v1, v_null)
        self.assertEqual(v_null, v_null)
        self.assertNotEqual('2.0', v1)

    def test_version_matches(self):
        v1 = api_version_request.APIVersionRequest('2.0')
        v2 = api_version_request.APIVersionRequest('2.5')
        v3 = api_version_request.APIVersionRequest('2.45')
        v4 = api_version_request.APIVersionRequest('3.3')
        v5 = api_version_request.APIVersionRequest('3.23')
        v6 = api_version_request.APIVersionRequest('2.0')
        v7 = api_version_request.APIVersionRequest('3.3')
        v8 = api_version_request.APIVersionRequest('4.0')
        v_null = api_version_request.APIVersionRequest()

        self.assertTrue(v2.matches(v1, v3))
        self.assertTrue(v2.matches(v1, v_null))
        self.assertTrue(v1.matches(v6, v2))
        self.assertTrue(v4.matches(v2, v7))
        self.assertTrue(v4.matches(v_null, v7))
        self.assertTrue(v4.matches(v_null, v8))
        self.assertFalse(v1.matches(v2, v3))
        self.assertFalse(v5.matches(v2, v4))
        self.assertFalse(v2.matches(v3, v1))
        self.assertTrue(v1.matches(v_null, v_null))

        self.assertRaises(ValueError, v_null.matches, v1, v3)

    def test_matches_versioned_method(self):

        request = api_version_request.APIVersionRequest('2.0')

        self.assertRaises(exception.InvalidParameterValue,
                          request.matches_versioned_method,
                          'fake_method')

    def test_get_string(self):
        v1_string = '3.23'
        v1 = api_version_request.APIVersionRequest(v1_string)
        self.assertEqual(v1_string, v1.get_string())

        self.assertRaises(ValueError,
                          api_version_request.APIVersionRequest().get_string)

    @ddt.data(('1', '0'), ('1', '1'))
    @ddt.unpack
    def test_str(self, major, minor):
        request_input = '%s.%s' % (major, minor)
        request = api_version_request.APIVersionRequest(request_input)
        request_string = six.text_type(request)

        self.assertEqual('API Version Request '
                         'Major: %s, Minor: %s' % (major, minor),
                         request_string)
