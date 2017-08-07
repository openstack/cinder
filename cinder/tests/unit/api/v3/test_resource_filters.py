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
Tests for resource filters API.
"""

import ddt
import mock
import six

from cinder.api.v3 import resource_filters as v3_filters
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake

FILTERS_MICRO_VERSION = '3.33'


@ddt.ddt
class ResourceFiltersAPITestCase(test.TestCase):
    """Test Case for filter API."""

    def setUp(self):
        super(ResourceFiltersAPITestCase, self).setUp()
        self.controller = v3_filters.ResourceFiltersController()

    @ddt.data({'filters': {'volume': ['key1']},
               'resource': 'volume',
               'expected_filters': [{'resource': 'volume',
                                     'filters': ['key1']}]},
              {'filters': {'volume': ['key1'], 'snapshot': ['key2']},
               'resource': None,
               'expected_filters': [{'resource': 'volume',
                                     'filters': ['key1']},
                                    {'resource': 'snapshot',
                                     'filters': ['key2']}]},
              {'filters': {'volume': ['key1', 'key2']},
               'resource': 'snapshot',
               'expected_filters': []})
    @ddt.unpack
    def test_get_allowed_filters(self, filters, resource, expected_filters):
        request_url = '/v3/%s/resource_filters' % fake.PROJECT_ID
        if resource is not None:
            request_url += '?resource=%s' % resource
        req = fakes.HTTPRequest.blank(request_url,
                                      version=FILTERS_MICRO_VERSION)

        with mock.patch('cinder.api.common._FILTERS_COLLECTION', filters):
            result = self.controller.index(req)
            six.assertCountEqual(self,
                                 list(six.viewkeys(result)),
                                 ['resource_filters'])
            six.assertCountEqual(self,
                                 expected_filters,
                                 result['resource_filters'])
