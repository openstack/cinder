# Copyright 2010 OpenStack Foundation
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

"""
Test suites for 'common' code used throughout the OpenStack HTTP API.
"""

import mock
from testtools import matchers
import webob
import webob.exc

from cinder.api import common
from cinder import test


NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"


class LimiterTest(test.TestCase):
    """Unit tests for the `cinder.api.common.limited` method.

    This method takes in a list of items and, depending on the 'offset'
    and 'limit' GET params, returns a subset or complete set of the given
    items.
    """

    def setUp(self):
        """Run before each test."""
        super(LimiterTest, self).setUp()
        self.tiny = range(1)
        self.small = range(10)
        self.medium = range(1000)
        self.large = range(10000)

    def test_limiter_offset_zero(self):
        """Test offset key works with 0."""
        req = webob.Request.blank('/?offset=0')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_offset_medium(self):
        """Test offset key works with a medium sized number."""
        req = webob.Request.blank('/?offset=10')
        self.assertEqual(common.limited(self.tiny, req), [])
        self.assertEqual(common.limited(self.small, req), self.small[10:])
        self.assertEqual(common.limited(self.medium, req), self.medium[10:])
        self.assertEqual(common.limited(self.large, req), self.large[10:1010])

    def test_limiter_offset_over_max(self):
        """Test offset key works with a number over 1000 (max_limit)."""
        req = webob.Request.blank('/?offset=1001')
        self.assertEqual(common.limited(self.tiny, req), [])
        self.assertEqual(common.limited(self.small, req), [])
        self.assertEqual(common.limited(self.medium, req), [])
        self.assertEqual(
            common.limited(self.large, req), self.large[1001:2001])

    def test_limiter_offset_blank(self):
        """Test offset key works with a blank offset."""
        req = webob.Request.blank('/?offset=')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_offset_bad(self):
        """Test offset key works with a BAD offset."""
        req = webob.Request.blank(u'/?offset=\u0020aa')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_nothing(self):
        """Test request with no offset or limit."""
        req = webob.Request.blank('/')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_limit_zero(self):
        """Test limit of zero."""
        req = webob.Request.blank('/?limit=0')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_limit_bad(self):
        """Test with a bad limit."""
        req = webob.Request.blank(u'/?limit=hello')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_limit_medium(self):
        """Test limit of 10."""
        req = webob.Request.blank('/?limit=10')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium[:10])
        self.assertEqual(common.limited(self.large, req), self.large[:10])

    def test_limiter_limit_over_max(self):
        """Test limit of 3000."""
        req = webob.Request.blank('/?limit=3000')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_limit_and_offset(self):
        """Test request with both limit and offset."""
        items = range(2000)
        req = webob.Request.blank('/?offset=1&limit=3')
        self.assertEqual(common.limited(items, req), items[1:4])
        req = webob.Request.blank('/?offset=3&limit=0')
        self.assertEqual(common.limited(items, req), items[3:1003])
        req = webob.Request.blank('/?offset=3&limit=1500')
        self.assertEqual(common.limited(items, req), items[3:1003])
        req = webob.Request.blank('/?offset=3000&limit=10')
        self.assertEqual(common.limited(items, req), [])

    def test_limiter_custom_max_limit(self):
        """Test a max_limit other than 1000."""
        items = range(2000)
        req = webob.Request.blank('/?offset=1&limit=3')
        self.assertEqual(
            common.limited(items, req, max_limit=2000), items[1:4])
        req = webob.Request.blank('/?offset=3&limit=0')
        self.assertEqual(
            common.limited(items, req, max_limit=2000), items[3:])
        req = webob.Request.blank('/?offset=3&limit=2500')
        self.assertEqual(
            common.limited(items, req, max_limit=2000), items[3:])
        req = webob.Request.blank('/?offset=3000&limit=10')
        self.assertEqual(common.limited(items, req, max_limit=2000), [])

    def test_limiter_negative_limit(self):
        """Test a negative limit."""
        req = webob.Request.blank('/?limit=-3000')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_negative_offset(self):
        """Test a negative offset."""
        req = webob.Request.blank('/?offset=-30')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)


class PaginationParamsTest(test.TestCase):
    """Unit tests for `cinder.api.common.get_pagination_params` method.

    This method takes in a request object and returns 'marker' and 'limit'
    GET params.
    """

    def test_nonnumerical_limit(self):
        """Test nonnumerical limit param."""
        req = webob.Request.blank('/?limit=hello')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.get_pagination_params, req)

    def test_no_params(self):
        """Test no params."""
        req = webob.Request.blank('/')
        self.assertEqual(common.get_pagination_params(req), {})

    def test_valid_marker(self):
        """Test valid marker param."""
        req = webob.Request.blank(
            '/?marker=263abb28-1de6-412f-b00b-f0ee0c4333c2')
        self.assertEqual(common.get_pagination_params(req),
                         {'marker': '263abb28-1de6-412f-b00b-f0ee0c4333c2'})

    def test_valid_limit(self):
        """Test valid limit param."""
        req = webob.Request.blank('/?limit=10')
        self.assertEqual(common.get_pagination_params(req), {'limit': 10})

    def test_invalid_limit(self):
        """Test invalid limit param."""
        req = webob.Request.blank('/?limit=-2')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.get_pagination_params, req)

    def test_valid_limit_and_marker(self):
        """Test valid limit and marker parameters."""
        marker = '263abb28-1de6-412f-b00b-f0ee0c4333c2'
        req = webob.Request.blank('/?limit=20&marker=%s' % marker)
        self.assertEqual(common.get_pagination_params(req),
                         {'marker': marker, 'limit': 20})


class SortParamUtilsTest(test.TestCase):

    def test_get_sort_params_defaults(self):
        '''Verifies the default sort key and direction.'''
        sort_keys, sort_dirs = common.get_sort_params({})
        self.assertEqual(['created_at'], sort_keys)
        self.assertEqual(['desc'], sort_dirs)

    def test_get_sort_params_override_defaults(self):
        '''Verifies that the defaults can be overriden.'''
        sort_keys, sort_dirs = common.get_sort_params({}, default_key='key1',
                                                      default_dir='dir1')
        self.assertEqual(['key1'], sort_keys)
        self.assertEqual(['dir1'], sort_dirs)

    def test_get_sort_params_single_value_sort_param(self):
        '''Verifies a single sort key and direction.'''
        params = {'sort': 'key1:dir1'}
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1'], sort_keys)
        self.assertEqual(['dir1'], sort_dirs)

    def test_get_sort_params_single_value_old_params(self):
        '''Verifies a single sort key and direction.'''
        params = {'sort_key': 'key1', 'sort_dir': 'dir1'}
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1'], sort_keys)
        self.assertEqual(['dir1'], sort_dirs)

    def test_get_sort_params_single_with_default_sort_param(self):
        '''Verifies a single sort value with a default direction.'''
        params = {'sort': 'key1'}
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1'], sort_keys)
        # Direction should be defaulted
        self.assertEqual(['desc'], sort_dirs)

    def test_get_sort_params_single_with_default_old_params(self):
        '''Verifies a single sort value with a default direction.'''
        params = {'sort_key': 'key1'}
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1'], sort_keys)
        # Direction should be defaulted
        self.assertEqual(['desc'], sort_dirs)

    def test_get_sort_params_multiple_values(self):
        '''Verifies multiple sort parameter values.'''
        params = {'sort': 'key1:dir1,key2:dir2,key3:dir3'}
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['dir1', 'dir2', 'dir3'], sort_dirs)

    def test_get_sort_params_multiple_not_all_dirs(self):
        '''Verifies multiple sort keys without all directions.'''
        params = {'sort': 'key1:dir1,key2,key3:dir3'}
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        # Second key is missing the direction, should be defaulted
        self.assertEqual(['dir1', 'desc', 'dir3'], sort_dirs)

    def test_get_sort_params_multiple_override_default_dir(self):
        '''Verifies multiple sort keys and overriding default direction.'''
        params = {'sort': 'key1:dir1,key2,key3'}
        sort_keys, sort_dirs = common.get_sort_params(params,
                                                      default_dir='foo')
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['dir1', 'foo', 'foo'], sort_dirs)

    def test_get_sort_params_params_modified(self):
        '''Verifies that the input sort parameter are modified.'''
        params = {'sort': 'key1:dir1,key2:dir2,key3:dir3'}
        common.get_sort_params(params)
        self.assertEqual({}, params)

        params = {'sort_dir': 'key1', 'sort_dir': 'dir1'}
        common.get_sort_params(params)
        self.assertEqual({}, params)

    def test_get_sort_params_random_spaces(self):
        '''Verifies that leading and trailing spaces are removed.'''
        params = {'sort': ' key1 : dir1,key2: dir2 , key3 '}
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['dir1', 'dir2', 'desc'], sort_dirs)

    def test_get_params_mix_sort_and_old_params(self):
        '''An exception is raised if both types of sorting params are given.'''
        for params in ({'sort': 'k1', 'sort_key': 'k1'},
                       {'sort': 'k1', 'sort_dir': 'd1'},
                       {'sort': 'k1', 'sort_key': 'k1', 'sort_dir': 'd2'}):
            self.assertRaises(webob.exc.HTTPBadRequest,
                              common.get_sort_params,
                              params)


class MiscFunctionsTest(test.TestCase):

    def test_remove_major_version_from_href(self):
        fixture = 'http://www.testsite.com/v1/images'
        expected = 'http://www.testsite.com/images'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href(self):
        fixture = 'http://www.testsite.com/v1.1/images'
        expected = 'http://www.testsite.com/images'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href_2(self):
        fixture = 'http://www.testsite.com/v1.1/'
        expected = 'http://www.testsite.com/'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href_3(self):
        fixture = 'http://www.testsite.com/v10.10'
        expected = 'http://www.testsite.com'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href_4(self):
        fixture = 'http://www.testsite.com/v1.1/images/v10.5'
        expected = 'http://www.testsite.com/images/v10.5'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href_bad_request(self):
        fixture = 'http://www.testsite.com/1.1/images'
        self.assertRaises(ValueError,
                          common.remove_version_from_href,
                          fixture)

    def test_remove_version_from_href_bad_request_2(self):
        fixture = 'http://www.testsite.com/v/images'
        self.assertRaises(ValueError,
                          common.remove_version_from_href,
                          fixture)

    def test_remove_version_from_href_bad_request_3(self):
        fixture = 'http://www.testsite.com/v1.1images'
        self.assertRaises(ValueError,
                          common.remove_version_from_href,
                          fixture)


class TestCollectionLinks(test.TestCase):
    """Tests the _get_collection_links method."""

    def _validate_next_link(self, href_link_mock, item_count,
                            osapi_max_limit, limit, should_link_exist):
        req = mock.MagicMock()
        href_link_mock.return_value = [{"rel": "next",
                                        "href": "fake_link"}]
        self.flags(osapi_max_limit=osapi_max_limit)
        if limit is None:
            params = mock.PropertyMock(return_value=dict())
            limited_list_size = min(item_count, osapi_max_limit)
        else:
            params = mock.PropertyMock(return_value=dict(limit=limit))
            limited_list_size = min(item_count, osapi_max_limit,
                                    limit)
        limited_list = [{"uuid": str(i)} for i in range(limited_list_size)]
        type(req).params = params
        builder = common.ViewBuilder()
        results = builder._get_collection_links(req, limited_list,
                                                mock.sentinel.coll_key,
                                                item_count, "uuid")
        if should_link_exist:
            href_link_mock.assert_called_once_with(limited_list, "uuid",
                                                   req,
                                                   mock.sentinel.coll_key)
            self.assertThat(results, matchers.HasLength(1))
        else:
            self.assertFalse(href_link_mock.called)
            self.assertThat(results, matchers.HasLength(0))

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_equals_osapi_max_no_limit(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 5
        limit = None
        should_link_exist = False
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_equals_osapi_max_greater_than_limit(self,
                                                       href_link_mock):
        item_count = 5
        osapi_max_limit = 5
        limit = 4
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_equals_osapi_max_equals_limit(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 5
        limit = 5
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_equals_osapi_max_less_than_limit(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 5
        limit = 6
        should_link_exist = False
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_less_than_osapi_max_no_limit(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 7
        limit = None
        should_link_exist = False
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_limit_less_than_items_less_than_osapi_max(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 7
        limit = 4
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_limit_equals_items_less_than_osapi_max(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 7
        limit = 5
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_less_than_limit_less_than_osapi_max(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 7
        limit = 6
        should_link_exist = False
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_less_than_osapi_max_equals_limit(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 7
        limit = 7
        should_link_exist = False
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_less_than_osapi_max_less_than_limit(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 7
        limit = 8
        should_link_exist = False
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_greater_than_osapi_max_no_limit(self, href_link_mock):
        item_count = 5
        osapi_max_limit = 3
        limit = None
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_limit_less_than_items_greater_than_osapi_max(self,
                                                          href_link_mock):
        item_count = 5
        osapi_max_limit = 3
        limit = 2
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_greater_than_osapi_max_equals_limit(self,
                                                       href_link_mock):
        item_count = 5
        osapi_max_limit = 3
        limit = 3
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_greater_than_limit_greater_than_osapi_max(self,
                                                             href_link_mock):
        item_count = 5
        osapi_max_limit = 3
        limit = 4
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_items_equals_limit_greater_than_osapi_max(self,
                                                       href_link_mock):
        item_count = 5
        osapi_max_limit = 3
        limit = 5
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)

    @mock.patch('cinder.api.common.ViewBuilder._generate_next_link')
    def test_limit_greater_than_items_greater_than_osapi_max(self,
                                                             href_link_mock):
        item_count = 5
        osapi_max_limit = 3
        limit = 6
        should_link_exist = True
        self._validate_next_link(href_link_mock, item_count,
                                 osapi_max_limit,
                                 limit, should_link_exist)
