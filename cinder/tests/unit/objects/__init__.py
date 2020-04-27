#    Copyright 2015 IBM Corp.
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

from oslo_utils import timeutils

from cinder import context
from cinder import exception
from cinder.objects import base as obj_base
from cinder.tests.unit import test


class BaseObjectsTestCase(test.TestCase):
    def setUp(self, *args, **kwargs):
        super(BaseObjectsTestCase, self).setUp(*args, **kwargs)
        self.user_id = 'fake-user'
        self.project_id = 'fake-project'
        self.context = context.RequestContext(self.user_id, self.project_id,
                                              is_admin=False)
        # We only test local right now.
        # TODO(mriedem): Testing remote would be nice...
        self.assertIsNone(obj_base.CinderObject.indirection_api)

    # TODO(mriedem): Replace this with
    # oslo_versionedobjects.fixture.compare_obj when that is in a released
    # version of o.vo.
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            try:
                getattr(obj, field)
            except (AttributeError, exception.CinderException,
                    NotImplementedError):
                # NotImplementedError: ignore "Cannot load 'projects' in the
                # base class" error
                continue

            obj_field = getattr(obj, field)
            if field in ('modified_at', 'created_at', 'updated_at',
                         'deleted_at', 'last_heartbeat') and db[field]:
                test.assertEqual(db[field],
                                 timeutils.normalize_time(obj_field))
            elif isinstance(obj_field, obj_base.ObjectListBase):
                test.assertEqual(db[field], obj_field.objects)
            else:
                test.assertEqual(db[field], obj_field)
