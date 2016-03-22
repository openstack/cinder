# Copyright (c) 2016 Red Hat, Inc.
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

import mock

from oslo_utils import timeutils

from cinder import objects
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import objects as test_objects


class TestCleanupRequest(test_objects.BaseObjectsTestCase):

    all_fields = ('service_id', 'cluster_name', 'host', 'binary', 'service_id',
                  'is_up', 'disabled', 'resource_id', 'resource_type', 'until')

    default = {'is_up': False}

    def setUp(self):
        super(TestCleanupRequest, self).setUp()

        self.fields = dict(service_id=1, cluster_name='cluster_name',
                           host='host_name', binary='binary_name', is_up=False,
                           resource_id=fake.VOLUME_ID, resource_type='Volume',
                           until=timeutils.utcnow(with_timezone=True),
                           disabled=True)

    def _req_as_dict(self, req):
        return {field: getattr(req, field) for field in self.all_fields}

    def _req_default(self, field):
        return self.default.get(field, None)

    def test_init_all_set(self):
        """Test __init__ when setting all field values."""
        req = objects.CleanupRequest(mock.sentinel.context, **self.fields)
        self.assertDictEqual(self.fields, self._req_as_dict(req))

    def test_init_default(self):
        """Test __init__ when one field is missing."""
        for field in self.fields:
            fields = self.fields.copy()
            del fields[field]
            req = objects.CleanupRequest(mock.sentinel.context, **fields)
            fields[field] = self._req_default(field)
            self.assertDictEqual(fields, self._req_as_dict(req))

    def test_init_defaults(self):
        """Test __init__ when only one field is set."""
        all_defaults = {field: self._req_default(field)
                        for field in self.all_fields}

        for field in self.fields:
            fields = {field: self.fields[field]}
            req = objects.CleanupRequest(mock.sentinel.context, **fields)
            expected = all_defaults.copy()
            expected.update(fields)
            self.assertDictEqual(expected, self._req_as_dict(req))
