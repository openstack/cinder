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

from cinder.objects import fields
from cinder import test


class FakeFieldType(fields.FieldType):
    def coerce(self, obj, attr, value):
        return '*%s*' % value

    def to_primitive(self, obj, attr, value):
        return '!%s!' % value

    def from_primitive(self, obj, attr, value):
        return value[1:-1]


class TestField(test.TestCase):
    def setUp(self):
        super(TestField, self).setUp()
        self.field = fields.Field(FakeFieldType())
        self.coerce_good_values = [('foo', '*foo*')]
        self.coerce_bad_values = []
        self.to_primitive_values = [('foo', '!foo!')]
        self.from_primitive_values = [('!foo!', 'foo')]

    def test_coerce_good_values(self):
        for in_val, out_val in self.coerce_good_values:
            self.assertEqual(out_val, self.field.coerce('obj', 'attr', in_val))

    def test_coerce_bad_values(self):
        for in_val in self.coerce_bad_values:
            self.assertRaises((TypeError, ValueError),
                              self.field.coerce, 'obj', 'attr', in_val)

    def test_to_primitive(self):
        for in_val, prim_val in self.to_primitive_values:
            self.assertEqual(prim_val, self.field.to_primitive('obj', 'attr',
                                                               in_val))

    def test_from_primitive(self):
        class ObjectLikeThing(object):
            _context = 'context'

        for prim_val, out_val in self.from_primitive_values:
            self.assertEqual(out_val, self.field.from_primitive(
                ObjectLikeThing, 'attr', prim_val))

    def test_stringify(self):
        self.assertEqual('123', self.field.stringify(123))


class TestBackupStatus(TestField):
    def setUp(self):
        super(TestBackupStatus, self).setUp()
        self.field = fields.BackupStatusField()
        self.coerce_good_values = [('error', 'error'),
                                   ('error_deleting', 'error_deleting'),
                                   ('creating', 'creating'),
                                   ('available', 'available'),
                                   ('deleting', 'deleting'),
                                   ('deleted', 'deleted'),
                                   ('restoring', 'restoring')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'error'", self.field.stringify('error'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'not_a_status')


class TestConsistencyGroupStatus(TestField):
    def setUp(self):
        super(TestConsistencyGroupStatus, self).setUp()
        self.field = fields.ConsistencyGroupStatusField()
        self.coerce_good_values = [('error', 'error'),
                                   ('available', 'available'),
                                   ('creating', 'creating'),
                                   ('deleting', 'deleting'),
                                   ('deleted', 'deleted'),
                                   ('updating', 'updating'),
                                   ('in-use', 'in-use'),
                                   ('error_deleting', 'error_deleting')]
        self.coerce_bad_values = ['acme']
        self.to_primitive_values = self.coerce_good_values[0:1]
        self.from_primitive_values = self.coerce_good_values[0:1]

    def test_stringify(self):
        self.assertEqual("'error'", self.field.stringify('error'))

    def test_stringify_invalid(self):
        self.assertRaises(ValueError, self.field.stringify, 'not_a_status')
