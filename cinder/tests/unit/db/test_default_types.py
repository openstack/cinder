# Copyright 2020 Red Hat, Inc.
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

"""Tests for default volume types."""

from cinder import context
from cinder import db
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


class DefaultVolumeTypesTestCase(test.TestCase):
    """DB tests for default volume types."""

    def setUp(self):
        super(DefaultVolumeTypesTestCase, self).setUp()
        self.ctxt = context.RequestContext(user_id=fake.USER_ID,
                                           project_id=fake.PROJECT_ID,
                                           is_admin=True)

    def test_default_type_set(self):
        default_type = db.project_default_volume_type_set(
            self.ctxt, fake.VOLUME_TYPE_ID, fake.PROJECT_ID)
        self.assertEqual(fake.PROJECT_ID, default_type.project_id)
        self.assertEqual(fake.VOLUME_TYPE_ID, default_type.volume_type_id)
        db.project_default_volume_type_unset(self.ctxt,
                                             default_type.project_id)

    def test_default_type_get(self):
        db.project_default_volume_type_set(self.ctxt, fake.VOLUME_TYPE_ID,
                                           fake.PROJECT_ID)
        default_type = db.project_default_volume_type_get(
            self.ctxt, project_id=fake.PROJECT_ID)
        self.assertEqual(fake.PROJECT_ID, default_type.project_id)
        self.assertEqual(fake.VOLUME_TYPE_ID, default_type.volume_type_id)
        db.project_default_volume_type_unset(self.ctxt,
                                             default_type.project_id)

    def test_get_all_projects_by_default_type(self):
        db.project_default_volume_type_set(self.ctxt, fake.VOLUME_TYPE_ID,
                                           fake.PROJECT_ID)
        default_type = db.get_all_projects_with_default_type(
            self.ctxt, volume_type_id=fake.VOLUME_TYPE_ID)
        self.assertEqual(1, len(default_type))
        self.assertEqual(fake.PROJECT_ID, default_type[0].project_id)

    def test_default_type_get_all(self):
        db.project_default_volume_type_set(self.ctxt, fake.VOLUME_TYPE_ID,
                                           fake.PROJECT_ID)
        db.project_default_volume_type_set(self.ctxt, fake.VOLUME_TYPE2_ID,
                                           fake.PROJECT2_ID)
        default_types = db.project_default_volume_type_get(self.ctxt)
        self.assertEqual(2, len(default_types))
        db.project_default_volume_type_unset(self.ctxt,
                                             default_types[0].project_id)
        db.project_default_volume_type_unset(self.ctxt,
                                             default_types[1].project_id)

    def test_default_type_delete(self):
        db.project_default_volume_type_set(self.ctxt, fake.VOLUME_TYPE_ID,
                                           fake.PROJECT_ID)
        default_types = db.project_default_volume_type_get(self.ctxt)
        self.assertEqual(1, len(default_types))
        db.project_default_volume_type_unset(self.ctxt,
                                             default_types[0].project_id)
        default_types = db.project_default_volume_type_get(self.ctxt)
        self.assertEqual(0, len(default_types))

    def test_default_type_update(self):
        default_type = db.project_default_volume_type_set(
            self.ctxt, fake.VOLUME_TYPE_ID, fake.PROJECT_ID)
        self.assertEqual(fake.PROJECT_ID, default_type.project_id)
        self.assertEqual(fake.VOLUME_TYPE_ID, default_type.volume_type_id)

        # update to type 2
        db.project_default_volume_type_set(self.ctxt, fake.VOLUME_TYPE2_ID,
                                           fake.PROJECT_ID)
        default_type = db.project_default_volume_type_get(
            self.ctxt, project_id=fake.PROJECT_ID)
        self.assertEqual(fake.PROJECT_ID, default_type.project_id)
        self.assertEqual(fake.VOLUME_TYPE2_ID, default_type.volume_type_id)

        # update to type 3
        db.project_default_volume_type_set(self.ctxt, fake.VOLUME_TYPE3_ID,
                                           fake.PROJECT_ID)
        default_type = db.project_default_volume_type_get(
            self.ctxt, project_id=fake.PROJECT_ID)
        self.assertEqual(fake.PROJECT_ID, default_type.project_id)
        self.assertEqual(fake.VOLUME_TYPE3_ID, default_type.volume_type_id)

        # back to original
        db.project_default_volume_type_set(self.ctxt, fake.VOLUME_TYPE_ID,
                                           fake.PROJECT_ID)
        default_type = db.project_default_volume_type_get(
            self.ctxt, project_id=fake.PROJECT_ID)
        self.assertEqual(fake.PROJECT_ID, default_type.project_id)
        self.assertEqual(fake.VOLUME_TYPE_ID, default_type.volume_type_id)

        db.project_default_volume_type_unset(self.ctxt,
                                             default_type.project_id)
