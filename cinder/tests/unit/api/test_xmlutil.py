# Copyright 2011 OpenStack Foundation
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

from lxml import etree

from cinder.api import xmlutil
from cinder import test


class SelectorTest(test.TestCase):
    obj_for_test = {'test': {'name': 'test',
                             'values': [1, 2, 3],
                             'attrs': {'foo': 1,
                                       'bar': 2,
                                       'baz': 3, }, }, }

    def test_empty_selector(self):
        sel = xmlutil.Selector()
        self.assertEqual(0, len(sel.chain))
        self.assertEqual(self.obj_for_test, sel(self.obj_for_test))

    def test_dict_selector(self):
        sel = xmlutil.Selector('test')
        self.assertEqual(1, len(sel.chain))
        self.assertEqual('test', sel.chain[0])
        self.assertEqual(self.obj_for_test['test'],
                         sel(self.obj_for_test))

    def test_datum_selector(self):
        sel = xmlutil.Selector('test', 'name')
        self.assertEqual(2, len(sel.chain))
        self.assertEqual('test', sel.chain[0])
        self.assertEqual('name', sel.chain[1])
        self.assertEqual('test', sel(self.obj_for_test))

    def test_list_selector(self):
        sel = xmlutil.Selector('test', 'values', 0)
        self.assertEqual(3, len(sel.chain))
        self.assertEqual('test', sel.chain[0])
        self.assertEqual('values', sel.chain[1])
        self.assertEqual(0, sel.chain[2])
        self.assertEqual(1, sel(self.obj_for_test))

    def test_items_selector(self):
        sel = xmlutil.Selector('test', 'attrs', xmlutil.get_items)
        self.assertEqual(3, len(sel.chain))
        self.assertEqual(xmlutil.get_items, sel.chain[2])
        for key, val in sel(self.obj_for_test):
            self.assertEqual(self.obj_for_test['test']['attrs'][key], val)

    def test_missing_key_selector(self):
        sel = xmlutil.Selector('test2', 'attrs')
        self.assertIsNone(sel(self.obj_for_test))
        self.assertRaises(KeyError, sel, self.obj_for_test, True)

    def test_constant_selector(self):
        sel = xmlutil.ConstantSelector('Foobar')
        self.assertEqual('Foobar', sel.value)
        self.assertEqual('Foobar', sel(self.obj_for_test))


class TemplateElementTest(test.TestCase):
    def test_element_initial_attributes(self):
        # Create a template element with some attributes
        elem = xmlutil.TemplateElement('test', attrib=dict(a=1, b=2, c=3),
                                       c=4, d=5, e=6)

        # Verify all the attributes are as expected
        expected = dict(a=1, b=2, c=4, d=5, e=6)
        for k, v in expected.items():
            self.assertEqual(v, elem.attrib[k].chain[0])

    def test_element_get_attributes(self):
        expected = dict(a=1, b=2, c=3)

        # Create a template element with some attributes
        elem = xmlutil.TemplateElement('test', attrib=expected)

        # Verify that get() retrieves the attributes
        for k, v in expected.items():
            self.assertEqual(v, elem.get(k).chain[0])

    def test_element_set_attributes(self):
        attrs = dict(a=None, b='foo', c=xmlutil.Selector('foo', 'bar'))

        # Create a bare template element with no attributes
        elem = xmlutil.TemplateElement('test')

        # Set the attribute values
        for k, v in attrs.items():
            elem.set(k, v)

        # Now verify what got set
        self.assertEqual(1, len(elem.attrib['a'].chain))
        self.assertEqual('a', elem.attrib['a'].chain[0])
        self.assertEqual(1, len(elem.attrib['b'].chain))
        self.assertEqual('foo', elem.attrib['b'].chain[0])
        self.assertEqual(attrs['c'], elem.attrib['c'])

    def test_element_attribute_keys(self):
        attrs = dict(a=1, b=2, c=3, d=4)
        expected = set(attrs.keys())

        # Create a template element with some attributes
        elem = xmlutil.TemplateElement('test', attrib=attrs)

        # Now verify keys
        self.assertEqual(expected, set(elem.keys()))

    def test_element_attribute_items(self):
        expected = dict(a=xmlutil.Selector(1),
                        b=xmlutil.Selector(2),
                        c=xmlutil.Selector(3))
        keys = set(expected.keys())

        # Create a template element with some attributes
        elem = xmlutil.TemplateElement('test', attrib=expected)

        # Now verify items
        for k, v in elem.items():
            self.assertEqual(expected[k], v)
            keys.remove(k)

        # Did we visit all keys?
        self.assertEqual(0, len(keys))

    def test_element_selector_none(self):
        # Create a template element with no selector
        elem = xmlutil.TemplateElement('test')

        self.assertEqual(0, len(elem.selector.chain))

    def test_element_selector_string(self):
        # Create a template element with a string selector
        elem = xmlutil.TemplateElement('test', selector='test')

        self.assertEqual(1, len(elem.selector.chain))
        self.assertEqual('test', elem.selector.chain[0])

    def test_element_selector(self):
        sel = xmlutil.Selector('a', 'b')

        # Create a template element with an explicit selector
        elem = xmlutil.TemplateElement('test', selector=sel)

        self.assertEqual(sel, elem.selector)

    def test_element_subselector_none(self):
        # Create a template element with no subselector
        elem = xmlutil.TemplateElement('test')

        self.assertIsNone(elem.subselector)

    def test_element_subselector_string(self):
        # Create a template element with a string subselector
        elem = xmlutil.TemplateElement('test', subselector='test')

        self.assertEqual(1, len(elem.subselector.chain))
        self.assertEqual('test', elem.subselector.chain[0])

    def test_element_subselector(self):
        sel = xmlutil.Selector('a', 'b')

        # Create a template element with an explicit subselector
        elem = xmlutil.TemplateElement('test', subselector=sel)

        self.assertEqual(sel, elem.subselector)

    def test_element_append_child(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Make sure the element starts off empty
        self.assertEqual(0, len(elem))

        # Create a child element
        child = xmlutil.TemplateElement('child')

        # Append the child to the parent
        elem.append(child)

        # Verify that the child was added
        self.assertEqual(1, len(elem))
        self.assertEqual(child, elem[0])
        self.assertIn('child', elem)
        self.assertEqual(child, elem['child'])

        # Ensure that multiple children of the same name are rejected
        child2 = xmlutil.TemplateElement('child')
        self.assertRaises(KeyError, elem.append, child2)

    def test_element_extend_children(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Make sure the element starts off empty
        self.assertEqual(0, len(elem))

        # Create a few children
        children = [xmlutil.TemplateElement('child1'),
                    xmlutil.TemplateElement('child2'),
                    xmlutil.TemplateElement('child3'), ]

        # Extend the parent by those children
        elem.extend(children)

        # Verify that the children were added
        self.assertEqual(3, len(elem))
        for idx in range(len(elem)):
            self.assertEqual(children[idx], elem[idx])
            self.assertIn(children[idx].tag, elem)
            self.assertEqual(children[idx], elem[children[idx].tag])

        # Ensure that multiple children of the same name are rejected
        children2 = [xmlutil.TemplateElement('child4'),
                     xmlutil.TemplateElement('child1'), ]
        self.assertRaises(KeyError, elem.extend, children2)

        # Also ensure that child4 was not added
        self.assertEqual(3, len(elem))
        self.assertEqual('child3', elem[-1].tag)

    def test_element_insert_child(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Make sure the element starts off empty
        self.assertEqual(0, len(elem))

        # Create a few children
        children = [xmlutil.TemplateElement('child1'),
                    xmlutil.TemplateElement('child2'),
                    xmlutil.TemplateElement('child3'), ]

        # Extend the parent by those children
        elem.extend(children)

        # Create a child to insert
        child = xmlutil.TemplateElement('child4')

        # Insert it
        elem.insert(1, child)

        # Ensure the child was inserted in the right place
        self.assertEqual(4, len(elem))
        children.insert(1, child)
        for idx in range(len(elem)):
            self.assertEqual(children[idx], elem[idx])
            self.assertIn(children[idx].tag, elem)
            self.assertEqual(children[idx], elem[children[idx].tag])

        # Ensure that multiple children of the same name are rejected
        child2 = xmlutil.TemplateElement('child2')
        self.assertRaises(KeyError, elem.insert, 2, child2)

    def test_element_remove_child(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Make sure the element starts off empty
        self.assertEqual(0, len(elem))

        # Create a few children
        children = [xmlutil.TemplateElement('child1'),
                    xmlutil.TemplateElement('child2'),
                    xmlutil.TemplateElement('child3'), ]

        # Extend the parent by those children
        elem.extend(children)

        # Create a test child to remove
        child = xmlutil.TemplateElement('child2')

        # Try to remove it
        self.assertRaises(ValueError, elem.remove, child)

        # Ensure that no child was removed
        self.assertEqual(3, len(elem))

        # Now remove a legitimate child
        elem.remove(children[1])

        # Ensure that the child was removed
        self.assertEqual(2, len(elem))
        self.assertEqual(children[0], elem[0])
        self.assertEqual(children[2], elem[1])
        self.assertNotIn('child2', elem)

        # Ensure the child cannot be retrieved by name
        def get_key(elem, key):
            return elem[key]
        self.assertRaises(KeyError, get_key, elem, 'child2')

    def test_element_text(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Ensure that it has no text
        self.assertIsNone(elem.text)

        # Try setting it to a string and ensure it becomes a selector
        elem.text = 'test'
        self.assertTrue(hasattr(elem.text, 'chain'))
        self.assertEqual(1, len(elem.text.chain))
        self.assertEqual('test', elem.text.chain[0])

        # Try resetting the text to None
        elem.text = None
        self.assertIsNone(elem.text)

        # Now make up a selector and try setting the text to that
        sel = xmlutil.Selector()
        elem.text = sel
        self.assertEqual(sel, elem.text)

        # Finally, try deleting the text and see what happens
        del elem.text
        self.assertIsNone(elem.text)

    def test_apply_attrs(self):
        # Create a template element
        attrs = dict(attr1=xmlutil.ConstantSelector(1),
                     attr2=xmlutil.ConstantSelector(2))
        tmpl_elem = xmlutil.TemplateElement('test', attrib=attrs)

        # Create an etree element
        elem = etree.Element('test')

        # Apply the template to the element
        tmpl_elem.apply(elem, None)

        # Now, verify the correct attributes were set
        for k, v in elem.items():
            self.assertEqual(str(attrs[k].value), v)

    def test_apply_text(self):
        # Create a template element
        tmpl_elem = xmlutil.TemplateElement('test')
        tmpl_elem.text = xmlutil.ConstantSelector(1)

        # Create an etree element
        elem = etree.Element('test')

        # Apply the template to the element
        tmpl_elem.apply(elem, None)

        # Now, verify the text was set
        self.assertEqual(str(tmpl_elem.text.value), elem.text)

    def test__render(self):
        attrs = dict(attr1=xmlutil.ConstantSelector(1),
                     attr2=xmlutil.ConstantSelector(2),
                     attr3=xmlutil.ConstantSelector(3))

        # Create a master template element
        master_elem = xmlutil.TemplateElement('test', attr1=attrs['attr1'])

        # Create a couple of slave template element
        slave_elems = [xmlutil.TemplateElement('test', attr2=attrs['attr2']),
                       xmlutil.TemplateElement('test', attr3=attrs['attr3']), ]

        # Try the render
        elem = master_elem._render(None, None, slave_elems, None)

        # Verify the particulars of the render
        self.assertEqual('test', elem.tag)
        self.assertEqual(0, len(elem.nsmap))
        for k, v in elem.items():
            self.assertEqual(str(attrs[k].value), v)

        # Create a parent for the element to be rendered
        parent = etree.Element('parent')

        # Try the render again...
        elem = master_elem._render(parent, None, slave_elems, dict(a='foo'))

        # Verify the particulars of the render
        self.assertEqual(1, len(parent))
        self.assertEqual(parent[0], elem)
        self.assertEqual(1, len(elem.nsmap))
        self.assertEqual('foo', elem.nsmap['a'])

    def test_render(self):
        # Create a template element
        tmpl_elem = xmlutil.TemplateElement('test')
        tmpl_elem.text = xmlutil.Selector()

        # Create the object we're going to render
        obj = ['elem1', 'elem2', 'elem3', 'elem4']

        # Try a render with no object
        elems = tmpl_elem.render(None, None)
        self.assertEqual(0, len(elems))

        # Try a render with one object
        elems = tmpl_elem.render(None, 'foo')
        self.assertEqual(1, len(elems))
        self.assertEqual('foo', elems[0][0].text)
        self.assertEqual('foo', elems[0][1])

        # Now, try rendering an object with multiple entries
        parent = etree.Element('parent')
        elems = tmpl_elem.render(parent, obj)
        self.assertEqual(4, len(elems))

        # Check the results
        for idx in range(len(obj)):
            self.assertEqual(obj[idx], elems[idx][0].text)
            self.assertEqual(obj[idx], elems[idx][1])

    def test_subelement(self):
        # Try the SubTemplateElement constructor
        parent = xmlutil.SubTemplateElement(None, 'parent')
        self.assertEqual('parent', parent.tag)
        self.assertEqual(0, len(parent))

        # Now try it with a parent element
        child = xmlutil.SubTemplateElement(parent, 'child')
        self.assertEqual('child', child.tag)
        self.assertEqual(1, len(parent))
        self.assertEqual(parent[0], child)

    def test_wrap(self):
        # These are strange methods, but they make things easier
        elem = xmlutil.TemplateElement('test')
        self.assertEqual(elem, elem.unwrap())
        self.assertEqual(elem, elem.wrap().root)

    def test_dyntag(self):
        obj = ['a', 'b', 'c']

        # Create a template element with a dynamic tag
        tmpl_elem = xmlutil.TemplateElement(xmlutil.Selector())

        # Try the render
        parent = etree.Element('parent')
        elems = tmpl_elem.render(parent, obj)

        # Verify the particulars of the render
        self.assertEqual(len(obj), len(elems))
        for idx in range(len(obj)):
            self.assertEqual(obj[idx], elems[idx][0].tag)


class TemplateTest(test.TestCase):
    def test_wrap(self):
        # These are strange methods, but they make things easier
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.Template(elem)
        self.assertEqual(elem, tmpl.unwrap())
        self.assertEqual(tmpl, tmpl.wrap())

    def test__siblings(self):
        # Set up a basic template
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.Template(elem)

        # Check that we get the right siblings
        siblings = tmpl._siblings()
        self.assertEqual(1, len(siblings))
        self.assertEqual(elem, siblings[0])

    def test__splitTagName(self):
        test_cases = [
            ('a', ['a']),
            ('a:b', ['a', 'b']),
            ('{http://test.com}a:b', ['{http://test.com}a', 'b']),
            ('a:b{http://test.com}:c', ['a', 'b{http://test.com}', 'c']),
        ]

        for test_case, expected in test_cases:
            result = xmlutil.TemplateElement._splitTagName(test_case)
            self.assertEqual(expected, result)

    def test__nsmap(self):
        # Set up a basic template
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.Template(elem, nsmap=dict(a="foo"))

        # Check out that we get the right namespace dictionary
        nsmap = tmpl._nsmap()
        self.assertNotEqual(id(nsmap), id(tmpl.nsmap))
        self.assertEqual(1, len(nsmap))
        self.assertEqual('foo', nsmap['a'])

    def test_master_attach(self):
        # Set up a master template
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.MasterTemplate(elem, 1)

        # Make sure it has a root but no slaves
        self.assertEqual(elem, tmpl.root)
        self.assertEqual(0, len(tmpl.slaves))

        # Try to attach an invalid slave
        bad_elem = xmlutil.TemplateElement('test2')
        self.assertRaises(ValueError, tmpl.attach, bad_elem)
        self.assertEqual(0, len(tmpl.slaves))

        # Try to attach an invalid and a valid slave
        good_elem = xmlutil.TemplateElement('test')
        self.assertRaises(ValueError, tmpl.attach, good_elem, bad_elem)
        self.assertEqual(0, len(tmpl.slaves))

        # Try to attach an inapplicable template
        class InapplicableTemplate(xmlutil.Template):
            def apply(self, master):
                return False
        inapp_tmpl = InapplicableTemplate(good_elem)
        tmpl.attach(inapp_tmpl)
        self.assertEqual(0, len(tmpl.slaves))

        # Now try attaching an applicable template
        tmpl.attach(good_elem)
        self.assertEqual(1, len(tmpl.slaves))
        self.assertEqual(good_elem, tmpl.slaves[0].root)

    def test_master_copy(self):
        # Construct a master template
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.MasterTemplate(elem, 1, nsmap=dict(a='foo'))

        # Give it a slave
        slave = xmlutil.TemplateElement('test')
        tmpl.attach(slave)

        # Construct a copy
        copy = tmpl.copy()

        # Check to see if we actually managed a copy
        self.assertNotEqual(tmpl, copy)
        self.assertEqual(tmpl.root, copy.root)
        self.assertEqual(tmpl.version, copy.version)
        self.assertEqual(id(tmpl.nsmap), id(copy.nsmap))
        self.assertNotEqual(id(tmpl.slaves), id(copy.slaves))
        self.assertEqual(len(tmpl.slaves), len(copy.slaves))
        self.assertEqual(tmpl.slaves[0], copy.slaves[0])

    def test_slave_apply(self):
        # Construct a master template
        elem = xmlutil.TemplateElement('test')
        master = xmlutil.MasterTemplate(elem, 3)

        # Construct a slave template with applicable minimum version
        slave = xmlutil.SlaveTemplate(elem, 2)
        self.assertTrue(slave.apply(master))

        # Construct a slave template with equal minimum version
        slave = xmlutil.SlaveTemplate(elem, 3)
        self.assertTrue(slave.apply(master))

        # Construct a slave template with inapplicable minimum version
        slave = xmlutil.SlaveTemplate(elem, 4)
        self.assertFalse(slave.apply(master))

        # Construct a slave template with applicable version range
        slave = xmlutil.SlaveTemplate(elem, 2, 4)
        self.assertTrue(slave.apply(master))

        # Construct a slave template with low version range
        slave = xmlutil.SlaveTemplate(elem, 1, 2)
        self.assertFalse(slave.apply(master))

        # Construct a slave template with high version range
        slave = xmlutil.SlaveTemplate(elem, 4, 5)
        self.assertFalse(slave.apply(master))

        # Construct a slave template with matching version range
        slave = xmlutil.SlaveTemplate(elem, 3, 3)
        self.assertTrue(slave.apply(master))

    def test__serialize(self):
        # Our test object to serialize
        obj = {'test': {'name': 'foobar',
                        'values': [1, 2, 3, 4],
                        'attrs': {'a': 1,
                                  'b': 2,
                                  'c': 3,
                                  'd': 4, },
                        'image': {'name': 'image_foobar', 'id': 42, }, }, }

        # Set up our master template
        root = xmlutil.TemplateElement('test', selector='test',
                                       name='name')
        value = xmlutil.SubTemplateElement(root, 'value', selector='values')
        value.text = xmlutil.Selector()
        attrs = xmlutil.SubTemplateElement(root, 'attrs', selector='attrs')
        xmlutil.SubTemplateElement(attrs, 'attr', selector=xmlutil.get_items,
                                   key=0, value=1)
        master = xmlutil.MasterTemplate(root, 1, nsmap=dict(f='foo'))

        # Set up our slave template
        root_slave = xmlutil.TemplateElement('test', selector='test')
        image = xmlutil.SubTemplateElement(root_slave, 'image',
                                           selector='image', id='id')
        image.text = xmlutil.Selector('name')
        slave = xmlutil.SlaveTemplate(root_slave, 1, nsmap=dict(b='bar'))

        # Attach the slave to the master...
        master.attach(slave)

        # Try serializing our object
        siblings = master._siblings()
        nsmap = master._nsmap()
        result = master._serialize(None, obj, siblings, nsmap)

        # Now we get to manually walk the element tree...
        self.assertEqual('test', result.tag)
        self.assertEqual(2, len(result.nsmap))
        self.assertEqual('foo', result.nsmap['f'])
        self.assertEqual('bar', result.nsmap['b'])
        self.assertEqual(result.get('name'), obj['test']['name'])
        for idx, val in enumerate(obj['test']['values']):
            self.assertEqual('value', result[idx].tag)
            self.assertEqual(str(val), result[idx].text)
        idx += 1
        self.assertEqual('attrs', result[idx].tag)
        for attr in result[idx]:
            self.assertEqual('attr', attr.tag)
            self.assertEqual(str(obj['test']['attrs'][attr.get('key')]),
                             attr.get('value'))
        idx += 1
        self.assertEqual('image', result[idx].tag)
        self.assertEqual(str(obj['test']['image']['id']),
                         result[idx].get('id'))
        self.assertEqual(obj['test']['image']['name'], result[idx].text)

    def test_serialize_with_delimiter(self):
        # Our test object to serialize
        obj = {'test': {'scope0:key1': 'Value1',
                        'scope0:scope1:key2': 'Value2',
                        'scope0:scope1:scope2:key3': 'Value3'
                        }}

        # Set up our master template
        root = xmlutil.TemplateElement('test', selector='test')
        key1 = xmlutil.SubTemplateElement(root, 'scope0:key1',
                                          selector='scope0:key1')
        key1.text = xmlutil.Selector()
        key2 = xmlutil.SubTemplateElement(root, 'scope0:scope1:key2',
                                          selector='scope0:scope1:key2')
        key2.text = xmlutil.Selector()
        key3 = xmlutil.SubTemplateElement(root, 'scope0:scope1:scope2:key3',
                                          selector='scope0:scope1:scope2:key3')
        key3.text = xmlutil.Selector()
        serializer = xmlutil.MasterTemplate(root, 1)
        expected_xml = (b"<?xmlversion='1.0'encoding='UTF-8'?><test>"
                        b"<scope0><key1>Value1</key1><scope1>"
                        b"<key2>Value2</key2><scope2><key3>Value3</key3>"
                        b"</scope2></scope1></scope0></test>")
        result = serializer.serialize(obj)
        result = result.replace(b'\n', b'').replace(b' ', b'')
        self.assertEqual(expected_xml, result)


class MasterTemplateBuilder(xmlutil.TemplateBuilder):
    def construct(self):
        elem = xmlutil.TemplateElement('test')
        return xmlutil.MasterTemplate(elem, 1)


class SlaveTemplateBuilder(xmlutil.TemplateBuilder):
    def construct(self):
        elem = xmlutil.TemplateElement('test')
        return xmlutil.SlaveTemplate(elem, 1)


class TemplateBuilderTest(test.TestCase):
    def test_master_template_builder(self):
        # Make sure the template hasn't been built yet
        self.assertIsNone(MasterTemplateBuilder._tmpl)

        # Now, construct the template
        tmpl1 = MasterTemplateBuilder()

        # Make sure that there is a template cached...
        self.assertIsNotNone(MasterTemplateBuilder._tmpl)

        # Make sure it wasn't what was returned...
        self.assertNotEqual(MasterTemplateBuilder._tmpl, tmpl1)

        # Make sure it doesn't get rebuilt
        cached = MasterTemplateBuilder._tmpl
        tmpl2 = MasterTemplateBuilder()
        self.assertEqual(MasterTemplateBuilder._tmpl, cached)

        # Make sure we're always getting fresh copies
        self.assertNotEqual(tmpl1, tmpl2)

        # Make sure we can override the copying behavior
        tmpl3 = MasterTemplateBuilder(False)
        self.assertEqual(MasterTemplateBuilder._tmpl, tmpl3)

    def test_slave_template_builder(self):
        # Make sure the template hasn't been built yet
        self.assertIsNone(SlaveTemplateBuilder._tmpl)

        # Now, construct the template
        tmpl1 = SlaveTemplateBuilder()

        # Make sure there is a template cached...
        self.assertIsNotNone(SlaveTemplateBuilder._tmpl)

        # Make sure it was what was returned...
        self.assertEqual(SlaveTemplateBuilder._tmpl, tmpl1)

        # Make sure it doesn't get rebuilt
        tmpl2 = SlaveTemplateBuilder()
        self.assertEqual(SlaveTemplateBuilder._tmpl, tmpl1)

        # Make sure we're always getting the cached copy
        self.assertEqual(tmpl1, tmpl2)


class MiscellaneousXMLUtilTests(test.TestCase):
    def test_make_flat_dict(self):
        expected_xml = (b"<?xml version='1.0' encoding='UTF-8'?>\n"
                        b'<wrapper><a>foo</a></wrapper>')
        root = xmlutil.make_flat_dict('wrapper')
        tmpl = xmlutil.MasterTemplate(root, 1)
        result = tmpl.serialize(dict(wrapper=dict(a='foo')))
        self.assertEqual(expected_xml, result)
