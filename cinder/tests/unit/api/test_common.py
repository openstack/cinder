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

import ddt
import mock
from testtools import matchers
import webob
import webob.exc

from oslo_config import cfg

from cinder.api import common
from cinder import test


NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
CONF = cfg.CONF

TINY = list(range(1))
SMALL = list(range(10))
MEDIUM = list(range(1000))
LARGE = list(range(10000))
ITEMS = list(range(2000))


@ddt.ddt
class LimiterTest(test.TestCase):
    """Unit tests for the `cinder.api.common.limited` method.

    This method takes in a list of items and, depending on the 'offset'
    and 'limit' GET params, returns a subset or complete set of the given
    items.
    """
    @ddt.data('/?offset=', '/?offset=123456789012346456',
              u'/?offset=\u0020aa', '/?offset=-30',
              u'/?limit=hello', '/?limit=-3000',
              '/?offset=30034522235674530&limit=10')
    def test_limiter_bad_offset_or_limit_values(self, value):
        """Test limiter with bad offset or limit values

        This test includes next test cases:
        1) Offset key works with a blank offset;
        2) Offset key works with a offset out of range;
        3) Offset key works with a BAD offset;
        4) Offset value is negative;
        5) Limit value is bad;
        6) Limit value is negative value.
        7) With both offset and limit;
        """
        req = webob.Request.blank(value)
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, SMALL, req)

    @ddt.data(
        ({'req': '/?offset=0', 'values': ((TINY, TINY),
         (SMALL, SMALL),
         (MEDIUM, MEDIUM),
         (LARGE[:1000], LARGE))}),
        ({'req': '/?offset=10', 'values': (([], TINY),
         (SMALL[10:], SMALL),
         (MEDIUM[10:], MEDIUM),
         (LARGE[10:1010], LARGE))}),
        ({'req': '/?offset=1001', 'values': (([], TINY),
         ([], SMALL),
         ([], MEDIUM),
         (LARGE[1001:2001], LARGE))}),
        ({'req': '/', 'values': ((TINY, TINY),
         (SMALL, SMALL),
         (MEDIUM, MEDIUM),
         (LARGE[:1000], LARGE))}),
        ({'req': '/?limit=0', 'values': ((TINY, TINY),
         (SMALL, SMALL),
         (MEDIUM, MEDIUM),
         (LARGE[:1000], LARGE))}),
        ({'req': '/?limit=10', 'values': ((TINY, TINY),
         (SMALL, SMALL),
         (MEDIUM[:10], MEDIUM),
         (LARGE[:10], LARGE))}),
        ({'req': '/?limit=3000', 'values': ((TINY, TINY),
         (SMALL, SMALL),
         (MEDIUM, MEDIUM),
         (LARGE[:1000], LARGE))}))
    @ddt.unpack
    def test_limiter(self, req, values):
        """Test limited method with different input parameters.

        This test includes next test cases:
        1) Test offset key works with 0;
        2) Test offset key works with a medium sized number;
        3) Test offset key works with a number over 1000 (max_limit);
        4) Test request with no offset or limit;
        5) Test limit of zero;
        6) Test limit of 10;
        7) Test limit of 3000;
        """
        req = webob.Request.blank(req)
        for expected, value, in values:
            self.assertEqual(expected, common.limited(value, req))

    @ddt.data(('/?offset=1&limit=3', 1, 4),
              ('/?offset=3&limit=0', 3, 1003),
              ('/?offset=3&limit=1500', 3, 1003),
              ('/?offset=3000&limit=10', 0, 0),
              ('/?offset=1&limit=3', 1, 4, 2000),
              ('/?offset=3&limit=0', 3, None, 2000),
              ('/?offset=3&limit=2500', 3, None, 2000),
              ('/?offset=3000&limit=10', 0, 0, 2000))
    @ddt.unpack
    def test_limiter_with_offset_limit_max_limit(self, req,
                                                 slice_start,
                                                 slice_end,
                                                 max_limit=None):
        """Test with both parameters offset and limit and custom max_limit."""
        # NOTE(mdovgal): using 0 as slice_start and slice_end we will
        # get empty list as a result
        # [3:None] equal to [3:]
        req = webob.Request.blank(req)
        self.assertEqual(ITEMS[slice_start:slice_end], common.limited(ITEMS,
                         req, max_limit=max_limit))


class PaginationParamsTest(test.TestCase):
    """Unit tests for `cinder.api.common.get_pagination_params` method.

    This method takes in a request object and returns 'marker' and 'limit'
    GET params.
    """

    def test_nonnumerical_limit(self):
        """Test nonnumerical limit param."""
        req = webob.Request.blank('/?limit=hello')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.get_pagination_params,
            req.GET.copy())

    @mock.patch.object(common, 'CONF')
    def test_no_params(self, mock_cfg):
        """Test no params."""
        mock_cfg.osapi_max_limit = 100
        req = webob.Request.blank('/')
        expected = (None, 100, 0)
        self.assertEqual(expected,
                         common.get_pagination_params(req.GET.copy()))

    def test_valid_marker(self):
        """Test valid marker param."""
        marker = '263abb28-1de6-412f-b00b-f0ee0c4333c2'
        req = webob.Request.blank('/?marker=' + marker)
        expected = (marker, CONF.osapi_max_limit, 0)
        self.assertEqual(expected,
                         common.get_pagination_params(req.GET.copy()))

    def test_valid_limit(self):
        """Test valid limit param."""
        req = webob.Request.blank('/?limit=10')
        expected = (None, 10, 0)
        self.assertEqual(expected,
                         common.get_pagination_params(req.GET.copy()))

    def test_invalid_limit(self):
        """Test invalid limit param."""
        req = webob.Request.blank('/?limit=-2')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.get_pagination_params,
            req.GET.copy())

    def test_valid_limit_and_marker(self):
        """Test valid limit and marker parameters."""
        marker = '263abb28-1de6-412f-b00b-f0ee0c4333c2'
        req = webob.Request.blank('/?limit=20&marker=%s' % marker)
        expected = (marker, 20, 0)
        self.assertEqual(expected,
                         common.get_pagination_params(req.GET.copy()))


@ddt.ddt
class SortParamUtilsTest(test.TestCase):

    @ddt.data(({'params': {}}, ['created_at'], ['desc']),
              ({'params': {}, 'default_key': 'key1', 'default_dir': 'dir1'},
               ['key1'], ['dir1']),
              ({'params': {'sort': 'key1:dir1'}}, ['key1'], ['dir1']),
              ({'params': {'sort_key': 'key1', 'sort_dir': 'dir1'}},
               ['key1'], ['dir1']),
              ({'params': {'sort': 'key1'}}, ['key1'], ['desc']),
              ({'params': {'sort': 'key1:dir1,key2:dir2,key3:dir3'}},
               ['key1', 'key2', 'key3'], ['dir1', 'dir2', 'dir3']),
              ({'params': {'sort': 'key1:dir1,key2,key3:dir3'}},
               ['key1', 'key2', 'key3'], ['dir1', 'desc', 'dir3']),
              ({'params': {'sort': 'key1:dir1,key2,key3'},
                'default_dir': 'foo'},
               ['key1', 'key2', 'key3'], ['dir1', 'foo', 'foo']),
              ({'params': {'sort': ' key1 : dir1,key2: dir2 , key3 '}},
               ['key1', 'key2', 'key3'], ['dir1', 'dir2', 'desc']))
    @ddt.unpack
    def test_get_sort_params(self, parameters, expected_keys, expected_dirs):
        """Test for get sort parameters method

        This test includes next test cases:
        1) Verifies the default sort key and direction.
        2) Verifies that the defaults can be overridden.
        3) Verifies a single sort key and direction.
        4) Verifies a single sort key and direction.
        5) Verifies a single sort value with a default direction.
        6) Verifies multiple sort parameter values.
        7) Verifies multiple sort keys without all directions.
        8) Verifies multiple sort keys and overriding default direction.
        9) Verifies that leading and trailing spaces are removed.
        """
        sort_keys, sort_dirs = common.get_sort_params(**parameters)
        self.assertEqual(expected_keys, sort_keys)
        self.assertEqual(expected_dirs, sort_dirs)

    def test_get_sort_params_params_modified(self):
        """Verifies that the input sort parameter are modified."""
        params = {'sort': 'key1:dir1,key2:dir2,key3:dir3'}
        common.get_sort_params(params)
        self.assertEqual({}, params)

        params = {'sort_key': 'key1', 'sort_dir': 'dir1'}
        common.get_sort_params(params)
        self.assertEqual({}, params)

    def test_get_params_mix_sort_and_old_params(self):
        """An exception is raised if both types of sorting params are given."""
        for params in ({'sort': 'k1', 'sort_key': 'k1'},
                       {'sort': 'k1', 'sort_dir': 'd1'},
                       {'sort': 'k1', 'sort_key': 'k1', 'sort_dir': 'd2'}):
            self.assertRaises(webob.exc.HTTPBadRequest,
                              common.get_sort_params,
                              params)


@ddt.ddt
class MiscFunctionsTest(test.TestCase):

    @ddt.data(('http://cinder.example.com/v1/images',
               'http://cinder.example.com/images'),
              ('http://cinder.example.com/v1.1/images',
               'http://cinder.example.com/images'),
              ('http://cinder.example.com/v1.1/',
               'http://cinder.example.com/'),
              ('http://cinder.example.com/v10.10',
               'http://cinder.example.com'),
              ('http://cinder.example.com/v1.1/images/v10.5',
               'http://cinder.example.com/images/v10.5'),
              ('http://cinder.example.com/cinder/v2',
               'http://cinder.example.com/cinder'))
    @ddt.unpack
    def test_remove_version_from_href(self, fixture, expected):
        """Test for removing version from href

        This test conatins following test-cases:
        1) remove major version from href
        2-5) remove version from href
        6) remove version from href version not trailing domain
        """
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(expected, actual)

    @ddt.data('http://cinder.example.com/1.1/images',
              'http://cinder.example.com/v/images',
              'http://cinder.example.com/v1.1images')
    def test_remove_version_from_href_bad_request(self, fixture):
        self.assertRaises(ValueError,
                          common.remove_version_from_href,
                          fixture)


@ddt.ddt
class TestCollectionLinks(test.TestCase):
    """Tests the _get_collection_links method."""

    def _validate_next_link(self, item_count, osapi_max_limit, limit,
                            should_link_exist):
        req = webob.Request.blank('/?limit=%s' % limit if limit else '/')
        link_return = [{"rel": "next", "href": "fake_link"}]
        self.flags(osapi_max_limit=osapi_max_limit)
        if limit is None:
            limited_list_size = min(item_count, osapi_max_limit)
        else:
            limited_list_size = min(item_count, osapi_max_limit, limit)
        limited_list = [{"uuid": str(i)} for i in range(limited_list_size)]
        builder = common.ViewBuilder()

        def get_pagination_params(params, max_limit=CONF.osapi_max_limit,
                                  original_call=common.get_pagination_params):
            return original_call(params, max_limit)

        def _get_limit_param(params, max_limit=CONF.osapi_max_limit,
                             original_call=common._get_limit_param):
            return original_call(params, max_limit)

        with mock.patch.object(common, 'get_pagination_params',
                               get_pagination_params), \
                mock.patch.object(common, '_get_limit_param',
                                  _get_limit_param), \
                mock.patch.object(common.ViewBuilder, '_generate_next_link',
                                  return_value=link_return) as href_link_mock:
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

    @ddt.data((5, 5, True), (5, 5, True, 4), (5, 5, True, 5),
              (5, 5, True, 6), (5, 7, False), (5, 7, True, 4),
              (5, 7, True, 5), (5, 7, False, 6), (5, 7, False, 7),
              (5, 7, False, 8), (5, 3, True), (5, 3, True, 2),
              (5, 3, True, 3), (5, 3, True, 4), (5, 3, True, 5),
              (5, 3, True, 6))
    @ddt.unpack
    def test_items(self, item_count, osapi_max_limit,
                   should_link_exist, limit=None):
        """Test

        1) Items count equals osapi_max_limit without limit;
        2) Items count equals osapi_max_limit and greater than limit;
        3) Items count equals osapi_max_limit and equals limit;
        4) Items count equals osapi_max_limit and less than limit;
        5) Items count less than osapi_max_limit without limit;
        6) Limit less than items count and less than osapi_max_limit;
        7) Limit equals items count and less than osapi_max_limit;
        8) Items count less than limit and less than osapi_max_limit;
        9) Items count less than osapi_max_limit and equals limit;
        10) Items count less than osapi_max_limit and less than limit;
        11) Items count greater than osapi_max_limit without limit;
        12) Limit less than items count and greater than osapi_max_limit;
        13) Items count greater than osapi_max_limit and equals limit;
        14) Items count greater than limit and greater than osapi_max_limit;
        15) Items count equals limit and greater than osapi_max_limit;
        16) Limit greater than items count and greater than osapi_max_limit;
        """
        self._validate_next_link(item_count, osapi_max_limit, limit,
                                 should_link_exist)


@ddt.ddt
class GeneralFiltersTest(test.TestCase):

    @ddt.data({'filters': {'volume': ['key1', 'key2']},
               'resource': 'volume',
               'expected': {'volume': ['key1', 'key2']}},
              {'filters': {'volume': ['key1', 'key2']},
               'resource': 'snapshot',
               'expected': {}},
              {'filters': {'volume': ['key1', 'key2']},
               'resource': None,
               'expected': {'volume': ['key1', 'key2']}})
    @ddt.unpack
    def test_get_enabled_resource_filters(self, filters, resource, expected):
        with mock.patch('cinder.api.common._FILTERS_COLLECTION', filters):
            result = common.get_enabled_resource_filters(resource)
            self.assertEqual(expected, result)

    @ddt.data({'filters': {'key1': 'value1'},
               'is_admin': False,
               'result': {'fake_resource': ['key1']},
               'expected': {'key1': 'value1'},
               'resource': 'fake_resource'},
              {'filters': {'key1': 'value1', 'key2': 'value2'},
               'is_admin': False,
               'result': {'fake_resource': ['key1']},
               'expected': None,
               'resource': 'fake_resource'},
              {'filters': {'key1': 'value1',
                           'all_tenants': 'value2',
                           'key3': 'value3'},
               'is_admin': True,
               'result': {'fake_resource': []},
               'expected': {'key1': 'value1',
                            'all_tenants': 'value2',
                            'key3': 'value3'},
               'resource': 'fake_resource'},
              {'filters': {'key1': 'value1',
                           'all_tenants': 'value2',
                           'key3': 'value3'},
               'is_admin': True,
               'result': {'pool': []},
               'expected': None,
               'resource': 'pool'})
    @ddt.unpack
    @mock.patch('cinder.api.common.get_enabled_resource_filters')
    def test_reject_invalid_filters(self, mock_get, filters,
                                    is_admin, result, expected, resource):
        class FakeContext(object):
            def __init__(self, admin):
                self.is_admin = admin

        fake_context = FakeContext(is_admin)
        mock_get.return_value = result
        if expected:
            common.reject_invalid_filters(fake_context,
                                          filters, resource)
            self.assertEqual(expected, filters)
        else:
            self.assertRaises(
                webob.exc.HTTPBadRequest,
                common.reject_invalid_filters, fake_context,
                filters, resource)

    @ddt.data({'filters': {'name': 'value1'},
               'is_admin': False,
               'result': {'fake_resource': ['name']},
               'expected': {'name': 'value1'}},
              {'filters': {'name~': 'value1'},
               'is_admin': False,
               'result': {'fake_resource': ['name']},
               'expected': None},
              {'filters': {'name': 'value1'},
               'is_admin': False,
               'result': {'fake_resource': ['name~']},
               'expected': {'name': 'value1'}},
              {'filters': {'name~': 'value1'},
               'is_admin': False,
               'result': {'fake_resource': ['name~']},
               'expected': {'name~': 'value1'}}
              )
    @ddt.unpack
    @mock.patch('cinder.api.common.get_enabled_resource_filters')
    def test_reject_invalid_filters_like_operator_enabled(
            self, mock_get, filters, is_admin, result, expected):
        class FakeContext(object):
            def __init__(self, admin):
                self.is_admin = admin

        fake_context = FakeContext(is_admin)
        mock_get.return_value = result
        if expected:
            common.reject_invalid_filters(fake_context,
                                          filters, 'fake_resource', True)
            self.assertEqual(expected, filters)
        else:
            self.assertRaises(
                webob.exc.HTTPBadRequest,
                common.reject_invalid_filters, fake_context,
                filters, 'fake_resource')

    @ddt.data({'resource': 'volume',
               'expected': ["name", "status", "metadata",
                            "bootable", "migration_status",
                            "availability_zone", "group_id"]},
              {'resource': 'backup',
               'expected': ["name", "status", "volume_id"]},
              {'resource': 'snapshot',
               'expected': ["name", "status", "volume_id", "metadata"]},
              {'resource': 'group_snapshot',
               'expected': ["status", "group_id"]},
              {'resource': 'attachment',
               'expected': ["volume_id", "status", "instance_id",
                            "attach_status"]},
              {'resource': 'message',
               'expected': ["resource_uuid", "resource_type", "event_id",
                            "request_id", "message_level"]},
              {'resource': 'pool', 'expected': ["name", "volume_type"]})
    @ddt.unpack
    def test_filter_keys_exists(self, resource, expected):
        result = common.get_enabled_resource_filters(resource)
        self.assertEqual(expected, result[resource])

    @ddt.data({'resource': 'group',
               'filters': {'name~': 'value'},
               'expected': {'name~': 'value'}},
              {'resource': 'snapshot',
               'filters': {'status~': 'value'},
               'expected': {'status~': 'value'}},
              {'resource': 'volume',
               'filters': {'name~': 'value',
                           'description~': 'value'},
               'expected': {'display_name~': 'value',
                            'display_description~': 'value'}},
              {'resource': 'backup',
               'filters': {'name~': 'value',
                           'description~': 'value'},
               'expected': {'display_name~': 'value',
                            'display_description~': 'value'}},
              )
    @ddt.unpack
    def test_convert_filter_attributes(self, resource, filters, expected):
        common.convert_filter_attributes(filters, resource)
        self.assertEqual(expected, filters)


@ddt.ddt
class LinkPrefixTest(test.TestCase):

    @ddt.data((["http://192.168.0.243:24/", "http://127.0.0.1/volume"],
               "http://127.0.0.1/volume"),
              (["http://foo.x.com/v1", "http://new.prefix.com"],
               "http://new.prefix.com/v1"),
              (["http://foo.x.com/v1",
                "http://new.prefix.com:20455/new_extra_prefix"],
               "http://new.prefix.com:20455/new_extra_prefix/v1"))
    @ddt.unpack
    def test_update_link_prefix(self, update_args, expected):
        vb = common.ViewBuilder()
        result = vb._update_link_prefix(*update_args)
        self.assertEqual(expected, result)


class RequestUrlTest(test.TestCase):
    def test_get_request_url_no_forward(self):
        app_url = 'http://127.0.0.1/v2;param?key=value#frag'
        request = type('', (), {
            'application_url': app_url,
            'headers': {}
        })
        result = common.get_request_url(request)
        self.assertEqual(app_url, result)

    def test_get_request_url_forward(self):
        request = type('', (), {
            'application_url': 'http://127.0.0.1/v2;param?key=value#frag',
            'headers': {'X-Forwarded-Host': '192.168.0.243:24'}
        })
        result = common.get_request_url(request)
        self.assertEqual('http://192.168.0.243:24/v2;param?key=value#frag',
                         result)
