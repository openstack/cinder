#    Copyright 2015 Red Hat, Inc.
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

import datetime
import uuid

from iso8601 import iso8601
from oslo_versionedobjects import fields

from cinder.objects import base
from cinder.tests.unit import objects as test_objects


@base.CinderObjectRegistry.register
class TestObject(base.CinderObject):
    fields = {
        'scheduled_at': base.fields.DateTimeField(nullable=True),
        'uuid': base.fields.UUIDField(),
        'text': base.fields.StringField(nullable=True),
    }


class TestCinderObject(test_objects.BaseObjectsTestCase):
    """Tests methods from CinderObject."""

    def setUp(self):
        super(TestCinderObject, self).setUp()
        self.obj = TestObject(
            scheduled_at=None,
            uuid=uuid.uuid4(),
            text='text')
        self.obj.obj_reset_changes()

    def test_cinder_obj_get_changes_no_changes(self):
        self.assertDictEqual({}, self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_other_changes(self):
        self.obj.text = 'text2'
        self.assertDictEqual({'text': 'text2'},
                             self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_datetime_no_tz(self):
        now = datetime.datetime.utcnow()
        self.obj.scheduled_at = now
        self.assertDictEqual({'scheduled_at': now},
                             self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_datetime_tz_utc(self):
        now_tz = iso8601.parse_date('2015-06-26T22:00:01Z')
        now = now_tz.replace(tzinfo=None)
        self.obj.scheduled_at = now_tz
        self.assertDictEqual({'scheduled_at': now},
                             self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_datetime_tz_non_utc_positive(self):
        now_tz = iso8601.parse_date('2015-06-26T22:00:01+01')
        now = now_tz.replace(tzinfo=None) - datetime.timedelta(hours=1)
        self.obj.scheduled_at = now_tz
        self.assertDictEqual({'scheduled_at': now},
                             self.obj.cinder_obj_get_changes())

    def test_cinder_obj_get_changes_datetime_tz_non_utc_negative(self):
        now_tz = iso8601.parse_date('2015-06-26T10:00:01-05')
        now = now_tz.replace(tzinfo=None) + datetime.timedelta(hours=5)
        self.obj.scheduled_at = now_tz
        self.assertDictEqual({'scheduled_at': now},
                             self.obj.cinder_obj_get_changes())


class TestCinderComparableObject(test_objects.BaseObjectsTestCase):
    def test_comparable_objects(self):
        @base.CinderObjectRegistry.register
        class MyComparableObj(base.CinderObject,
                              base.CinderObjectDictCompat,
                              base.CinderComparableObject):
            fields = {'foo': fields.Field(fields.Integer())}

        class NonVersionedObject(object):
            pass

        obj1 = MyComparableObj(foo=1)
        obj2 = MyComparableObj(foo=1)
        obj3 = MyComparableObj(foo=2)
        obj4 = NonVersionedObject()
        self.assertTrue(obj1 == obj2)
        self.assertFalse(obj1 == obj3)
        self.assertFalse(obj1 == obj4)
        self.assertNotEqual(obj1, None)
