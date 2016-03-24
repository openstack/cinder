# Copyright 2016 Intel Corp.
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

"""Tests for volume type."""

from cinder import context
from cinder import db
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.volume import volume_types


class VolumeTypeTestCase(test.TestCase):
    """Test cases for volume type."""

    def setUp(self):
        super(VolumeTypeTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID,
                                           is_admin = True)

    def test_volume_type_update(self):
        vol_type_ref = volume_types.create(self.ctxt, 'fake volume type')
        updates = dict(name = 'test_volume_type_update',
                       description = None,
                       is_public = None)
        updated_vol_type = db.volume_type_update(
            self.ctxt, vol_type_ref.id, updates)
        self.assertEqual('test_volume_type_update', updated_vol_type.name)
        volume_types.destroy(self.ctxt, vol_type_ref.id)
