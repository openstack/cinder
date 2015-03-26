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

import contextlib
import copy
import datetime

import mock
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import six
from testtools import matchers

from cinder import context
from cinder import exception
from cinder import objects
from cinder.objects import base
from cinder.objects import fields
from cinder import test
from cinder.tests import fake_notifier


class MyOwnedObject(base.CinderPersistentObject, base.CinderObject):
    VERSION = '1.0'
    fields = {'baz': fields.Field(fields.Integer())}


class MyObj(base.CinderPersistentObject, base.CinderObject,
            base.CinderObjectDictCompat):
    VERSION = '1.6'
    fields = {'foo': fields.Field(fields.Integer(), default=1),
              'bar': fields.Field(fields.String()),
              'missing': fields.Field(fields.String()),
              'readonly': fields.Field(fields.Integer(), read_only=True),
              'rel_object': fields.ObjectField('MyOwnedObject', nullable=True),
              'rel_objects': fields.ListOfObjectsField('MyOwnedObject',
                                                       nullable=True),
              }

    @staticmethod
    def _from_db_object(context, obj, db_obj):
        self = MyObj()
        self.foo = db_obj['foo']
        self.bar = db_obj['bar']
        self.missing = db_obj['missing']
        self.readonly = 1
        return self

    def obj_load_attr(self, attrname):
        setattr(self, attrname, 'loaded!')

    @base.remotable_classmethod
    def query(cls, context):
        obj = cls(context=context, foo=1, bar='bar')
        obj.obj_reset_changes()
        return obj

    @base.remotable
    def marco(self, context):
        return 'polo'

    @base.remotable
    def _update_test(self, context):
        if context.project_id == 'alternate':
            self.bar = 'alternate-context'
        else:
            self.bar = 'updated'

    @base.remotable
    def save(self, context):
        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context):
        self.foo = 321
        self.bar = 'refreshed'
        self.obj_reset_changes()

    @base.remotable
    def modify_save_modify(self, context):
        self.bar = 'meow'
        self.save()
        self.foo = 42
        self.rel_object = MyOwnedObject(baz=42)

    def obj_make_compatible(self, primitive, target_version):
        super(MyObj, self).obj_make_compatible(primitive, target_version)
        # NOTE(danms): Simulate an older version that had a different
        # format for the 'bar' attribute
        if target_version == '1.1' and 'bar' in primitive:
            primitive['bar'] = 'old%s' % primitive['bar']


class MyObjDiffVers(MyObj):
    VERSION = '1.5'

    @classmethod
    def obj_name(cls):
        return 'MyObj'


class MyObj2(object):
    @classmethod
    def obj_name(cls):
        return 'MyObj'

    @base.remotable_classmethod
    def query(cls, *args, **kwargs):
        pass


class RandomMixInWithNoFields(object):
    """Used to test object inheritance using a mixin that has no fields."""
    pass


class TestSubclassedObject(RandomMixInWithNoFields, MyObj):
    fields = {'new_field': fields.Field(fields.String())}


class TestMetaclass(test.TestCase):
    def test_obj_tracking(self):

        @six.add_metaclass(base.CinderObjectMetaclass)
        class NewBaseClass(object):
            VERSION = '1.0'
            fields = {}

            @classmethod
            def obj_name(cls):
                return cls.__name__

        class Fake1TestObj1(NewBaseClass):
            @classmethod
            def obj_name(cls):
                return 'fake1'

        class Fake1TestObj2(Fake1TestObj1):
            pass

        class Fake1TestObj3(Fake1TestObj1):
            VERSION = '1.1'

        class Fake2TestObj1(NewBaseClass):
            @classmethod
            def obj_name(cls):
                return 'fake2'

        class Fake1TestObj4(Fake1TestObj3):
            VERSION = '1.2'

        class Fake2TestObj2(Fake2TestObj1):
            VERSION = '1.1'

        class Fake1TestObj5(Fake1TestObj1):
            VERSION = '1.1'

        # Newest versions first in the list. Duplicate versions take the
        # newest object.
        expected = {'fake1': [Fake1TestObj4, Fake1TestObj5, Fake1TestObj2],
                    'fake2': [Fake2TestObj2, Fake2TestObj1]}
        self.assertEqual(expected, NewBaseClass._obj_classes)
        # The following should work, also.
        self.assertEqual(expected, Fake1TestObj1._obj_classes)
        self.assertEqual(expected, Fake1TestObj2._obj_classes)
        self.assertEqual(expected, Fake1TestObj3._obj_classes)
        self.assertEqual(expected, Fake1TestObj4._obj_classes)
        self.assertEqual(expected, Fake1TestObj5._obj_classes)
        self.assertEqual(expected, Fake2TestObj1._obj_classes)
        self.assertEqual(expected, Fake2TestObj2._obj_classes)

    def test_field_checking(self):
        def create_class(field):
            class TestField(base.CinderObject):
                VERSION = '1.5'
                fields = {'foo': field()}
            return TestField

        create_class(fields.BooleanField)
        self.assertRaises(exception.ObjectFieldInvalid,
                          create_class, fields.Boolean)
        self.assertRaises(exception.ObjectFieldInvalid,
                          create_class, int)


class TestObjToPrimitive(test.TestCase):

    def test_obj_to_primitive_list(self):
        class MyObjElement(base.CinderObject):
            fields = {'foo': fields.IntegerField()}

            def __init__(self, foo):
                super(MyObjElement, self).__init__()
                self.foo = foo

        class MyList(base.ObjectListBase, base.CinderObject):
            fields = {'objects': fields.ListOfObjectsField('MyObjElement')}

        mylist = MyList()
        mylist.objects = [MyObjElement(1), MyObjElement(2), MyObjElement(3)]
        self.assertEqual([1, 2, 3],
                         [x['foo'] for x in base.obj_to_primitive(mylist)])

    def test_obj_to_primitive_dict(self):
        myobj = MyObj(foo=1, bar='foo')
        self.assertEqual({'foo': 1, 'bar': 'foo'},
                         base.obj_to_primitive(myobj))

    def test_obj_to_primitive_recursive(self):
        class MyList(base.ObjectListBase, base.CinderObject):
            fields = {'objects': fields.ListOfObjectsField('MyObj')}

        mylist = MyList(objects=[MyObj(), MyObj()])
        for i, value in enumerate(mylist):
            value.foo = i
        self.assertEqual([{'foo': 0}, {'foo': 1}],
                         base.obj_to_primitive(mylist))


class TestObjMakeList(test.TestCase):

    def test_obj_make_list(self):
        class MyList(base.ObjectListBase, base.CinderObject):
            pass

        db_objs = [{'foo': 1, 'bar': 'baz', 'missing': 'banana'},
                   {'foo': 2, 'bar': 'bat', 'missing': 'apple'},
                   ]
        mylist = base.obj_make_list('ctxt', MyList(), MyObj, db_objs)
        self.assertEqual(2, len(mylist))
        self.assertEqual('ctxt', mylist._context)
        for index, item in enumerate(mylist):
            self.assertEqual(db_objs[index]['foo'], item.foo)
            self.assertEqual(db_objs[index]['bar'], item.bar)
            self.assertEqual(db_objs[index]['missing'], item.missing)


def compare_obj(test, obj, db_obj, subs=None, allow_missing=None,
                comparators=None):
    """Compare a CinderObject and a dict-like database object.

    This automatically converts TZ-aware datetimes and iterates over
    the fields of the object.

    :param:test: The TestCase doing the comparison
    :param:obj: The CinderObject to examine
    :param:db_obj: The dict-like database object to use as reference
    :param:subs: A dict of objkey=dbkey field substitutions
    :param:allow_missing: A list of fields that may not be in db_obj
    :param:comparators: Map of comparator functions to use for certain fields
    """

    if subs is None:
        subs = {}
    if allow_missing is None:
        allow_missing = []
    if comparators is None:
        comparators = {}

    for key in obj.fields:
        if key in allow_missing and not obj.obj_attr_is_set(key):
            continue
        obj_val = getattr(obj, key)
        db_key = subs.get(key, key)
        db_val = db_obj[db_key]
        if isinstance(obj_val, datetime.datetime):
            obj_val = obj_val.replace(tzinfo=None)

        if key in comparators:
            comparator = comparators[key]
            comparator(db_val, obj_val)
        else:
            test.assertEqual(db_val, obj_val)


class _BaseTestCase(test.TestCase):
    def setUp(self):
        super(_BaseTestCase, self).setUp()
        self.remote_object_calls = list()
        self.user_id = 'fake-user'
        self.project_id = 'fake-project'
        self.context = context.RequestContext(self.user_id, self.project_id)
        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

    def compare_obj(self, obj, db_obj, subs=None, allow_missing=None,
                    comparators=None):
        compare_obj(self, obj, db_obj, subs=subs, allow_missing=allow_missing,
                    comparators=comparators)

    def json_comparator(self, expected, obj_val):
        # json-ify an object field for comparison with its db str
        # equivalent
        self.assertEqual(expected, jsonutils.dumps(obj_val))

    def str_comparator(self, expected, obj_val):
        """Compare an object field to a string in the db by performing
        a simple coercion on the object field value.
        """
        self.assertEqual(expected, str(obj_val))

    def assertNotIsInstance(self, obj, cls, msg=None):
        """Python < v2.7 compatibility.  Assert 'not isinstance(obj, cls)."""
        try:
            f = super(_BaseTestCase, self).assertNotIsInstance
        except AttributeError:
            self.assertThat(obj,
                            matchers.Not(matchers.IsInstance(cls)),
                            message=msg or '')
        else:
            f(obj, cls, msg=msg)


class _LocalTest(_BaseTestCase):
    def setUp(self):
        super(_LocalTest, self).setUp()
        # Just in case
        base.CinderObject.indirection_api = None

    def assertRemotes(self):
        self.assertEqual(self.remote_object_calls, [])


@contextlib.contextmanager
def things_temporarily_local():
    _api = base.CinderObject.indirection_api
    base.CinderObject.indirection_api = None
    yield
    base.CinderObject.indirection_api = _api


class _TestObject(object):
    def test_object_attrs_in_init(self):
        # Now check the test one in this file. Should be newest version
        self.assertEqual('1.6', objects.MyObj.VERSION)

    def test_hydration_type_error(self):
        primitive = {'cinder_object.name': 'MyObj',
                     'cinder_object.namespace': 'cinder',
                     'cinder_object.version': '1.5',
                     'cinder_object.data': {'foo': 'a'}}
        self.assertRaises(ValueError, MyObj.obj_from_primitive, primitive)

    def test_hydration(self):
        primitive = {'cinder_object.name': 'MyObj',
                     'cinder_object.namespace': 'cinder',
                     'cinder_object.version': '1.5',
                     'cinder_object.data': {'foo': 1}}
        real_method = MyObj._obj_from_primitive

        def _obj_from_primitive(*args):
            return real_method(*args)

        with mock.patch.object(MyObj, '_obj_from_primitive') as ofp:
            ofp.side_effect = _obj_from_primitive
            obj = MyObj.obj_from_primitive(primitive)
            ofp.assert_called_once_with(None, '1.5', primitive)
        self.assertEqual(obj.foo, 1)

    def test_hydration_version_different(self):
        primitive = {'cinder_object.name': 'MyObj',
                     'cinder_object.namespace': 'cinder',
                     'cinder_object.version': '1.2',
                     'cinder_object.data': {'foo': 1}}
        obj = MyObj.obj_from_primitive(primitive)
        self.assertEqual(obj.foo, 1)
        self.assertEqual('1.2', obj.VERSION)

    def test_hydration_bad_ns(self):
        primitive = {'cinder_object.name': 'MyObj',
                     'cinder_object.namespace': 'foo',
                     'cinder_object.version': '1.5',
                     'cinder_object.data': {'foo': 1}}
        self.assertRaises(exception.UnsupportedObjectError,
                          MyObj.obj_from_primitive, primitive)

    def test_hydration_additional_unexpected_stuff(self):
        primitive = {'cinder_object.name': 'MyObj',
                     'cinder_object.namespace': 'cinder',
                     'cinder_object.version': '1.5.1',
                     'cinder_object.data': {
                         'foo': 1,
                         'unexpected_thing': 'foobar'}}
        obj = MyObj.obj_from_primitive(primitive)
        self.assertEqual(1, obj.foo)
        self.assertFalse(hasattr(obj, 'unexpected_thing'))
        # NOTE(danms): If we call obj_from_primitive() directly
        # with a version containing .z, we'll get that version
        # in the resulting object. In reality, when using the
        # serializer, we'll get that snipped off (tested
        # elsewhere)
        self.assertEqual('1.5.1', obj.VERSION)

    def test_dehydration(self):
        expected = {'cinder_object.name': 'MyObj',
                    'cinder_object.namespace': 'cinder',
                    'cinder_object.version': '1.6',
                    'cinder_object.data': {'foo': 1}}
        obj = MyObj(foo=1)
        obj.obj_reset_changes()
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_object_property(self):
        obj = MyObj(foo=1)
        self.assertEqual(obj.foo, 1)

    def test_object_property_type_error(self):
        obj = MyObj()

        def fail():
            obj.foo = 'a'
        self.assertRaises(ValueError, fail)

    def test_object_dict_syntax(self):
        obj = MyObj(foo=123, bar='bar')
        self.assertEqual(obj['foo'], 123)
        self.assertEqual(sorted(obj.items(), key=lambda x: x[0]),
                         [('bar', 'bar'), ('foo', 123)])
        self.assertEqual(sorted(list(obj.iteritems()), key=lambda x: x[0]),
                         [('bar', 'bar'), ('foo', 123)])

    def test_load(self):
        obj = MyObj()
        self.assertEqual(obj.bar, 'loaded!')

    def test_load_in_base(self):
        class Foo(base.CinderObject):
            fields = {'foobar': fields.Field(fields.Integer())}
        obj = Foo()
        with self.assertRaisesRegex(NotImplementedError, ".*foobar.*"):
            obj.foobar

    def test_loaded_in_primitive(self):
        obj = MyObj(foo=1)
        obj.obj_reset_changes()
        self.assertEqual(obj.bar, 'loaded!')
        expected = {'cinder_object.name': 'MyObj',
                    'cinder_object.namespace': 'cinder',
                    'cinder_object.version': '1.6',
                    'cinder_object.changes': ['bar'],
                    'cinder_object.data': {'foo': 1,
                                           'bar': 'loaded!'}}
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_changes_in_primitive(self):
        obj = MyObj(foo=123)
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        primitive = obj.obj_to_primitive()
        self.assertIn('cinder_object.changes', primitive)
        obj2 = MyObj.obj_from_primitive(primitive)
        self.assertEqual(obj2.obj_what_changed(), set(['foo']))
        obj2.obj_reset_changes()
        self.assertEqual(obj2.obj_what_changed(), set())

    def test_obj_class_from_name(self):
        obj = base.CinderObject.obj_class_from_name('MyObj', '1.5')
        self.assertEqual('1.5', obj.VERSION)

    def test_obj_class_from_name_latest_compatible(self):
        obj = base.CinderObject.obj_class_from_name('MyObj', '1.1')
        self.assertEqual('1.6', obj.VERSION)

    def test_unknown_objtype(self):
        self.assertRaises(exception.UnsupportedObjectError,
                          base.CinderObject.obj_class_from_name, 'foo', '1.0')

    def test_obj_class_from_name_supported_version(self):
        error = None
        try:
            base.CinderObject.obj_class_from_name('MyObj', '1.25')
        except exception.IncompatibleObjectVersion as error:
            pass

        self.assertIsNotNone(error)
        self.assertEqual('1.6', error.kwargs['supported'])

    def test_with_alternate_context(self):
        ctxt1 = context.RequestContext('foo', 'foo')
        ctxt2 = context.RequestContext('bar', 'alternate')
        obj = MyObj.query(ctxt1)
        obj._update_test(ctxt2)
        self.assertEqual(obj.bar, 'alternate-context')
        self.assertRemotes()

    def test_orphaned_object(self):
        obj = MyObj.query(self.context)
        obj._context = None
        self.assertRaises(exception.OrphanedObjectError,
                          obj._update_test)
        self.assertRemotes()

    def test_changed_1(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj._update_test(self.context)
        self.assertEqual(obj.obj_what_changed(), set(['foo', 'bar']))
        self.assertEqual(obj.foo, 123)
        self.assertRemotes()

    def test_changed_2(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.save()
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 123)
        self.assertRemotes()

    def test_changed_3(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.refresh()
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 321)
        self.assertEqual(obj.bar, 'refreshed')
        self.assertRemotes()

    def test_changed_4(self):
        obj = MyObj.query(self.context)
        obj.bar = 'something'
        self.assertEqual(obj.obj_what_changed(), set(['bar']))
        obj.modify_save_modify(self.context)
        self.assertEqual(obj.obj_what_changed(), set(['foo', 'rel_object']))
        self.assertEqual(obj.foo, 42)
        self.assertEqual(obj.bar, 'meow')
        self.assertIsInstance(obj.rel_object, MyOwnedObject)
        self.assertRemotes()

    def test_changed_with_sub_object(self):
        class ParentObject(base.CinderObject):
            fields = {'foo': fields.IntegerField(),
                      'bar': fields.ObjectField('MyObj'),
                      }
        obj = ParentObject()
        self.assertEqual(set(), obj.obj_what_changed())
        obj.foo = 1
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        bar = MyObj()
        obj.bar = bar
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())
        obj.obj_reset_changes()
        self.assertEqual(set(), obj.obj_what_changed())
        bar.foo = 1
        self.assertEqual(set(['bar']), obj.obj_what_changed())

    def test_static_result(self):
        obj = MyObj.query(self.context)
        self.assertEqual(obj.bar, 'bar')
        result = obj.marco()
        self.assertEqual(result, 'polo')
        self.assertRemotes()

    def test_updates(self):
        obj = MyObj.query(self.context)
        self.assertEqual(obj.foo, 1)
        obj._update_test()
        self.assertEqual(obj.bar, 'updated')
        self.assertRemotes()

    def test_base_attributes(self):
        dt = datetime.datetime(1955, 11, 5)
        obj = MyObj(created_at=dt, updated_at=dt, deleted_at=None,
                    deleted=False)
        expected = {'cinder_object.name': 'MyObj',
                    'cinder_object.namespace': 'cinder',
                    'cinder_object.version': '1.6',
                    'cinder_object.changes':
                        ['created_at', 'deleted', 'deleted_at', 'updated_at'],
                    'cinder_object.data':
                        {'created_at': timeutils.isotime(dt),
                         'updated_at': timeutils.isotime(dt),
                         'deleted_at': None,
                         'deleted': False,
                         }
                    }
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_contains(self):
        obj = MyObj()
        self.assertNotIn('foo', obj)
        obj.foo = 1
        self.assertIn('foo', obj)
        self.assertNotIn('does_not_exist', obj)

    def test_obj_attr_is_set(self):
        obj = MyObj(foo=1)
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertFalse(obj.obj_attr_is_set('bar'))
        self.assertRaises(AttributeError, obj.obj_attr_is_set, 'bang')

    def test_get(self):
        obj = MyObj(foo=1)
        # Foo has value, should not get the default
        self.assertEqual(1, obj.get('foo', 2))
        # Foo has value, should return the value without error
        self.assertEqual(1, obj.get('foo'))
        # Bar is not loaded, so we should get the default
        self.assertEqual('not-loaded', obj.get('bar', 'not-loaded'))
        # Bar without a default should lazy-load
        self.assertEqual('loaded!', obj.get('bar'))
        # Bar now has a default, but loaded value should be returned
        self.assertEqual('loaded!', obj.get('bar', 'not-loaded'))
        # Invalid attribute should return None
        self.assertEqual(None, obj.get('nothing'))

    def test_object_inheritance(self):
        base_fields = base.CinderPersistentObject.fields.keys()
        myobj_fields = (['foo', 'bar', 'missing',
                         'readonly', 'rel_object', 'rel_objects'] +
                        base_fields)
        myobj3_fields = ['new_field']
        self.assertTrue(issubclass(TestSubclassedObject, MyObj))
        self.assertEqual(len(myobj_fields), len(MyObj.fields))
        self.assertEqual(set(myobj_fields), set(MyObj.fields.keys()))
        self.assertEqual(len(myobj_fields) + len(myobj3_fields),
                         len(TestSubclassedObject.fields))
        self.assertEqual(set(myobj_fields) | set(myobj3_fields),
                         set(TestSubclassedObject.fields.keys()))

    def test_obj_as_admin(self):
        obj = MyObj(context=self.context)

        def fake(*args, **kwargs):
            self.assertTrue(obj._context.is_admin)

        with mock.patch.object(obj, 'obj_reset_changes') as mock_fn:
            mock_fn.side_effect = fake
            with obj.obj_as_admin():
                obj.save()
            self.assertTrue(mock_fn.called)

        self.assertFalse(obj._context.is_admin)

    def test_obj_as_admin_orphaned(self):
        def testme():
            obj = MyObj()
            with obj.obj_as_admin():
                pass
        self.assertRaises(exception.OrphanedObjectError, testme)

    def test_get_changes(self):
        obj = MyObj()
        self.assertEqual({}, obj.obj_get_changes())
        obj.foo = 123
        self.assertEqual({'foo': 123}, obj.obj_get_changes())
        obj.bar = 'test'
        self.assertEqual({'foo': 123, 'bar': 'test'}, obj.obj_get_changes())
        obj.obj_reset_changes()
        self.assertEqual({}, obj.obj_get_changes())

    def test_obj_fields(self):
        class TestObj(base.CinderObject):
            fields = {'foo': fields.Field(fields.Integer())}
            obj_extra_fields = ['bar']

            @property
            def bar(self):
                return 'this is bar'

        obj = TestObj()
        self.assertEqual(['foo', 'bar'], obj.obj_fields)

    def test_obj_constructor(self):
        obj = MyObj(context=self.context, foo=123, bar='abc')
        self.assertEqual(123, obj.foo)
        self.assertEqual('abc', obj.bar)
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())

    def test_obj_read_only(self):
        obj = MyObj(context=self.context, foo=123, bar='abc')
        obj.readonly = 1
        self.assertRaises(exception.ReadOnlyFieldError, setattr,
                          obj, 'readonly', 2)

    def test_obj_repr(self):
        obj = MyObj(foo=123)
        self.assertEqual('MyObj(bar=<?>,created_at=<?>,deleted=<?>,'
                         'deleted_at=<?>,foo=123,missing=<?>,readonly=<?>,'
                         'rel_object=<?>,rel_objects=<?>,updated_at=<?>)',
                         repr(obj))

    def test_obj_make_obj_compatible(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(rel_object=subobj)
        obj.obj_relationships = {
            'rel_object': [('1.5', '1.1'), ('1.7', '1.2')],
        }
        primitive = obj.obj_to_primitive()['cinder_object.data']
        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive), '1.8',
                                         'rel_object')
            self.assertFalse(mock_compat.called)

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive),
                                         '1.7', 'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['cinder_object.data'], '1.2')
            self.assertEqual('1.2',
                             primitive['rel_object']['cinder_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive),
                                         '1.6', 'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['cinder_object.data'], '1.1')
            self.assertEqual('1.1',
                             primitive['rel_object']['cinder_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive), '1.5',
                                         'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['cinder_object.data'], '1.1')
            self.assertEqual('1.1',
                             primitive['rel_object']['cinder_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            _prim = copy.copy(primitive)
            obj._obj_make_obj_compatible(_prim, '1.4', 'rel_object')
            self.assertFalse(mock_compat.called)
            self.assertNotIn('rel_object', _prim)

    def test_obj_make_compatible_hits_sub_objects(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(foo=123, rel_object=subobj)
        obj.obj_relationships = {'rel_object': [('1.0', '1.0')]}
        with mock.patch.object(obj, '_obj_make_obj_compatible') as mock_compat:
            obj.obj_make_compatible({'rel_object': 'foo'}, '1.10')
            mock_compat.assert_called_once_with({'rel_object': 'foo'}, '1.10',
                                                'rel_object')

    def test_obj_make_compatible_skips_unset_sub_objects(self):
        obj = MyObj(foo=123)
        obj.obj_relationships = {'rel_object': [('1.0', '1.0')]}
        with mock.patch.object(obj, '_obj_make_obj_compatible') as mock_compat:
            obj.obj_make_compatible({'rel_object': 'foo'}, '1.10')
            self.assertFalse(mock_compat.called)

    def test_obj_make_compatible_complains_about_missing_rules(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(foo=123, rel_object=subobj)
        obj.obj_relationships = {}
        self.assertRaises(exception.ObjectActionError,
                          obj.obj_make_compatible, {}, '1.0')

    def test_obj_make_compatible_handles_list_of_objects(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(rel_objects=[subobj])
        obj.obj_relationships = {'rel_objects': [('1.0', '1.123')]}

        def fake_make_compat(primitive, version):
            self.assertEqual('1.123', version)
            self.assertIn('baz', primitive)

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_mc:
            mock_mc.side_effect = fake_make_compat
            obj.obj_to_primitive('1.0')
            self.assertTrue(mock_mc.called)


class TestObject(_LocalTest, _TestObject):
    def test_set_defaults(self):
        obj = MyObj()
        obj.obj_set_defaults('foo')
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertEqual(1, obj.foo)

    def test_set_defaults_no_default(self):
        obj = MyObj()
        self.assertRaises(exception.ObjectActionError,
                          obj.obj_set_defaults, 'bar')

    def test_set_all_defaults(self):
        obj = MyObj()
        obj.obj_set_defaults()
        self.assertEqual(set(['deleted', 'foo']), obj.obj_what_changed())
        self.assertEqual(1, obj.foo)


class TestObjectListBase(test.TestCase):
    def test_list_like_operations(self):
        class MyElement(base.CinderObject):
            fields = {'foo': fields.IntegerField()}

            def __init__(self, foo):
                super(MyElement, self).__init__()
                self.foo = foo

        class Foo(base.ObjectListBase, base.CinderObject):
            fields = {'objects': fields.ListOfObjectsField('MyElement')}

        objlist = Foo(context='foo',
                      objects=[MyElement(1), MyElement(2), MyElement(3)])
        self.assertEqual(list(objlist), objlist.objects)
        self.assertEqual(len(objlist), 3)
        self.assertIn(objlist.objects[0], objlist)
        self.assertEqual(list(objlist[:1]), [objlist.objects[0]])
        self.assertEqual(objlist[:1]._context, 'foo')
        self.assertEqual(objlist[2], objlist.objects[2])
        self.assertEqual(objlist.count(objlist.objects[0]), 1)
        self.assertEqual(objlist.index(objlist.objects[1]), 1)
        objlist.sort(key=lambda x: x.foo, reverse=True)
        self.assertEqual([3, 2, 1],
                         [x.foo for x in objlist])

    def test_serialization(self):
        class Foo(base.ObjectListBase, base.CinderObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        class Bar(base.CinderObject):
            fields = {'foo': fields.Field(fields.String())}

        obj = Foo(objects=[])
        for i in 'abc':
            bar = Bar(foo=i)
            obj.objects.append(bar)

        obj2 = base.CinderObject.obj_from_primitive(obj.obj_to_primitive())
        self.assertFalse(obj is obj2)
        self.assertEqual([x.foo for x in obj],
                         [y.foo for y in obj2])

    def test_list_changes(self):
        class Foo(base.ObjectListBase, base.CinderObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        class Bar(base.CinderObject):
            fields = {'foo': fields.StringField()}

        obj = Foo(objects=[])
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.objects.append(Bar(foo='test'))
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.obj_reset_changes()
        # This should still look dirty because the child is dirty
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.objects[0].obj_reset_changes()
        # This should now look clean because the child is clean
        self.assertEqual(set(), obj.obj_what_changed())

    def test_initialize_objects(self):
        class Foo(base.ObjectListBase, base.CinderObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        class Bar(base.CinderObject):
            fields = {'foo': fields.StringField()}

        obj = Foo()
        self.assertEqual([], obj.objects)
        self.assertEqual(set(), obj.obj_what_changed())

    def test_obj_repr(self):
        class Foo(base.ObjectListBase, base.CinderObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        class Bar(base.CinderObject):
            fields = {'uuid': fields.StringField()}

        obj = Foo(objects=[Bar(uuid='fake-uuid')])
        self.assertEqual('Foo(objects=[Bar(fake-uuid)])', repr(obj))


class TestObjectSerializer(_BaseTestCase):
    def test_serialize_entity_primitive(self):
        ser = base.CinderObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.serialize_entity(None, thing))

    def test_deserialize_entity_primitive(self):
        ser = base.CinderObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.deserialize_entity(None, thing))

    def _test_deserialize_entity_newer(self, obj_version, backported_to,
                                       my_version='1.6'):
        ser = base.CinderObjectSerializer()
        ser._conductor = mock.Mock()
        ser._conductor.object_backport.return_value = 'backported'

        class MyTestObj(MyObj):
            VERSION = my_version

        obj = MyTestObj()
        obj.VERSION = obj_version
        primitive = obj.obj_to_primitive()
        ser.deserialize_entity(self.context, primitive)
        if backported_to is None:
            self.assertFalse(ser._conductor.object_backport.called)

    def test_deserialize_entity_newer_revision_does_not_backport_zero(self):
        self._test_deserialize_entity_newer('1.6.0', None)

    def test_deserialize_entity_newer_revision_does_not_backport(self):
        self._test_deserialize_entity_newer('1.6.1', None)

    def test_deserialize_dot_z_with_extra_stuff(self):
        primitive = {'cinder_object.name': 'MyObj',
                     'cinder_object.namespace': 'cinder',
                     'cinder_object.version': '1.6.1',
                     'cinder_object.data': {
                         'foo': 1,
                         'unexpected_thing': 'foobar'}}
        ser = base.CinderObjectSerializer()
        obj = ser.deserialize_entity(self.context, primitive)
        self.assertEqual(1, obj.foo)
        self.assertFalse(hasattr(obj, 'unexpected_thing'))
        # NOTE(danms): The serializer is where the logic lives that
        # avoids backports for cases where only a .z difference in
        # the received object version is detected. As a result, we
        # end up with a version of what we expected, effectively the
        # .0 of the object.
        self.assertEqual('1.6', obj.VERSION)

    def test_object_serialization(self):
        ser = base.CinderObjectSerializer()
        obj = MyObj()
        primitive = ser.serialize_entity(self.context, obj)
        self.assertIn('cinder_object.name', primitive)
        obj2 = ser.deserialize_entity(self.context, primitive)
        self.assertIsInstance(obj2, MyObj)
        self.assertEqual(self.context, obj2._context)

    def test_object_serialization_iterables(self):
        ser = base.CinderObjectSerializer()
        obj = MyObj()
        for iterable in (list, tuple, set):
            thing = iterable([obj])
            primitive = ser.serialize_entity(self.context, thing)
            self.assertEqual(1, len(primitive))
            for item in primitive:
                self.assertNotIsInstance(item, base.CinderObject)
            thing2 = ser.deserialize_entity(self.context, primitive)
            self.assertEqual(1, len(thing2))
            for item in thing2:
                self.assertIsInstance(item, MyObj)
        # dict case
        thing = {'key': obj}
        primitive = ser.serialize_entity(self.context, thing)
        self.assertEqual(1, len(primitive))
        for item in primitive.itervalues():
            self.assertNotIsInstance(item, base.CinderObject)
        thing2 = ser.deserialize_entity(self.context, primitive)
        self.assertEqual(1, len(thing2))
        for item in thing2.itervalues():
            self.assertIsInstance(item, MyObj)

        # object-action updates dict case
        thing = {'foo': obj.obj_to_primitive()}
        primitive = ser.serialize_entity(self.context, thing)
        self.assertEqual(thing, primitive)
        thing2 = ser.deserialize_entity(self.context, thing)
        self.assertIsInstance(thing2['foo'], base.CinderObject)
