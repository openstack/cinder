# Copyright (c) 2015 Clinton Knight.  All rights reserved.
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

import sys

from lxml import etree
import mock
import six

from cinder import exception


EONTAPI_EINVAL = '22'
EAPIERROR = '13001'
EAPINOTFOUND = '13005'
ESNAPSHOTNOTALLOWED = '13023'
EVOLUMEOFFLINE = '13042'
EINTERNALERROR = '13114'
EDUPLICATEENTRY = '13130'
EVOLNOTCLONE = '13170'
EVOL_NOT_MOUNTED = '14716'
ESIS_CLONE_NOT_LICENSED = '14956'
EOBJECTNOTFOUND = '15661'
E_VIFMGR_PORT_ALREADY_ASSIGNED_TO_BROADCAST_DOMAIN = '18605'


def mock_netapp_lib(modules):
    """Inject fake netapp_lib module classes."""

    netapp_lib = mock.Mock()
    netapp_lib.api.zapi.zapi.NaElement = NaElement
    netapp_lib.api.zapi.zapi.NaApiError = NaApiError
    netapp_lib.api.zapi.zapi.NaServer = mock.Mock()
    netapp_lib.api.zapi.errors = sys.modules[__name__]
    for module in modules:
        setattr(module, 'netapp_api', netapp_lib.api.zapi.zapi)
        setattr(module, 'netapp_error', netapp_lib.api.zapi.errors)


class NaApiError(exception.CinderException):
    """Fake NetApi API invocation error."""

    def __init__(self, code=None, message=None):
        if not code:
            code = 'unknown'
        if not message:
            message = 'unknown'
        self.code = code
        self.message = message
        super(NaApiError, self).__init__(message=message)


class NaServer(object):
    """Fake XML wrapper class for NetApp Server"""
    def __init__(self, host):
        self._host = host


class NaElement(object):
    """Fake XML wrapper class for NetApp API."""

    def __init__(self, name):
        """Name of the element or etree.Element."""
        if isinstance(name, etree._Element):
            self._element = name
        else:
            self._element = etree.Element(name)

    def get_name(self):
        """Returns the tag name of the element."""
        return self._element.tag

    def set_content(self, text):
        """Set the text string for the element."""
        self._element.text = text

    def get_content(self):
        """Get the text for the element."""
        return self._element.text

    def add_attr(self, name, value):
        """Add the attribute to the element."""
        self._element.set(name, value)

    def add_attrs(self, **attrs):
        """Add multiple attributes to the element."""
        for attr in attrs.keys():
            self._element.set(attr, attrs.get(attr))

    def add_child_elem(self, na_element):
        """Add the child element to the element."""
        if isinstance(na_element, NaElement):
            self._element.append(na_element._element)
            return
        raise

    def get_child_by_name(self, name):
        """Get the child element by the tag name."""
        for child in self._element.iterchildren():
            if child.tag == name or etree.QName(child.tag).localname == name:
                return NaElement(child)
        return None

    def get_child_content(self, name):
        """Get the content of the child."""
        for child in self._element.iterchildren():
            if child.tag == name or etree.QName(child.tag).localname == name:
                return child.text
        return None

    def get_children(self):
        """Get the children for the element."""
        return [NaElement(el) for el in self._element.iterchildren()]

    def has_attr(self, name):
        """Checks whether element has attribute."""
        attributes = self._element.attrib or {}
        return name in attributes.keys()

    def get_attr(self, name):
        """Get the attribute with the given name."""
        attributes = self._element.attrib or {}
        return attributes.get(name)

    def get_attr_names(self):
        """Returns the list of attribute names."""
        attributes = self._element.attrib or {}
        return attributes.keys()

    def add_new_child(self, name, content, convert=False):
        """Add child with tag name and context.

           Convert replaces entity refs to chars.
        """
        child = NaElement(name)
        if convert:
            content = NaElement._convert_entity_refs(content)
        child.set_content(content)
        self.add_child_elem(child)

    @staticmethod
    def _convert_entity_refs(text):
        """Converts entity refs to chars to handle etree auto conversions."""
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        return text

    @staticmethod
    def create_node_with_children(node, **children):
        """Creates and returns named node with children."""
        parent = NaElement(node)
        for child in children.keys():
            parent.add_new_child(child, children.get(child, None))
        return parent

    def add_node_with_children(self, node, **children):
        """Creates named node with children."""
        parent = NaElement.create_node_with_children(node, **children)
        self.add_child_elem(parent)

    def to_string(self, pretty=False, method='xml', encoding='UTF-8'):
        """Prints the element to string."""
        return etree.tostring(self._element, method=method, encoding=encoding,
                              pretty_print=pretty)

    def __getitem__(self, key):
        """Dict getter method for NaElement.

            Returns NaElement list if present,
            text value in case no NaElement node
            children or attribute value if present.
        """

        child = self.get_child_by_name(key)
        if child:
            if child.get_children():
                return child
            else:
                return child.get_content()
        elif self.has_attr(key):
            return self.get_attr(key)
        raise KeyError('No element by given name %s.' % key)

    def __setitem__(self, key, value):
        """Dict setter method for NaElement.

           Accepts dict, list, tuple, str, int, float and long as valid value.
        """
        if key:
            if value:
                if isinstance(value, NaElement):
                    child = NaElement(key)
                    child.add_child_elem(value)
                    self.add_child_elem(child)
                elif isinstance(value, (str, int, float, long)):
                    self.add_new_child(key, six.text_type(value))
                elif isinstance(value, (list, tuple, dict)):
                    child = NaElement(key)
                    child.translate_struct(value)
                    self.add_child_elem(child)
                else:
                    raise TypeError('Not a valid value for NaElement.')
            else:
                self.add_child_elem(NaElement(key))
        else:
            raise KeyError('NaElement name cannot be null.')

    def translate_struct(self, data_struct):
        """Convert list, tuple, dict to NaElement and appends."""

        if isinstance(data_struct, (list, tuple)):
            for el in data_struct:
                if isinstance(el, (list, tuple, dict)):
                    self.translate_struct(el)
                else:
                    self.add_child_elem(NaElement(el))
        elif isinstance(data_struct, dict):
            for k in data_struct.keys():
                child = NaElement(k)
                if isinstance(data_struct[k], (dict, list, tuple)):
                    child.translate_struct(data_struct[k])
                else:
                    if data_struct[k]:
                        child.set_content(six.text_type(data_struct[k]))
                self.add_child_elem(child)
        else:
            raise ValueError('Type cannot be converted into NaElement.')
