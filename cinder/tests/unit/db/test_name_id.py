# Copyright 2013 IBM Corp.
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

"""Tests for volume name_id."""

from oslo_config import cfg

from cinder import context
from cinder import db
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as testutils


CONF = cfg.CONF


class NameIDsTestCase(test.TestCase):
    """Test cases for naming volumes with name_id."""

    def setUp(self):
        super(NameIDsTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID)

    def test_name_id_same(self):
        """New volume should have same 'id' and 'name_id'."""
        vol_ref = testutils.create_volume(self.ctxt, size=1)
        self.assertEqual(vol_ref['name_id'], vol_ref['id'])
        expected_name = CONF.volume_name_template % vol_ref['id']
        self.assertEqual(expected_name, vol_ref['name'])

    def test_name_id_diff(self):
        """Change name ID to mimic volume after migration."""
        vol_ref = testutils.create_volume(self.ctxt, size=1,
                                          _name_id=fake.VOLUME2_ID)
        vol_ref = db.volume_get(self.ctxt, vol_ref['id'])
        expected_name = CONF.volume_name_template % fake.VOLUME2_ID
        self.assertEqual(expected_name, vol_ref['name'])

    def test_name_id_snapshot_volume_name(self):
        """Make sure snapshot['volume_name'] is updated."""
        vol_ref = testutils.create_volume(self.ctxt, size=1,
                                          _name_id=fake.VOLUME2_ID)
        snap_ref = testutils.create_snapshot(self.ctxt, vol_ref['id'])
        expected_name = CONF.volume_name_template % fake.VOLUME2_ID
        self.assertEqual(expected_name, snap_ref['volume_name'])
