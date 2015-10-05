# Copyright 2010 OpenStack Foundation
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

from xml.dom import minidom

import mock
from oslo_i18n import fixture as i18n_fixture
from oslo_serialization import jsonutils
import webob.dec

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.i18n import _
from cinder import test


class TestFaults(test.TestCase):
    """Tests covering `cinder.api.openstack.faults:Fault` class."""

    def setUp(self):
        super(TestFaults, self).setUp()
        self.useFixture(i18n_fixture.ToggleLazy(True))

    def _prepare_xml(self, xml_string):
        """Remove characters from string which hinder XML equality testing."""
        xml_string = xml_string.replace("  ", "")
        xml_string = xml_string.replace("\n", "")
        xml_string = xml_string.replace("\t", "")
        return xml_string

    def test_400_fault_json(self):
        """Test fault serialized to JSON via file-extension and/or header."""
        requests = [
            webob.Request.blank('/.json'),
            webob.Request.blank('/', headers={"Accept": "application/json"}),
        ]

        for request in requests:
            fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
            response = request.get_response(fault)

            expected = {
                "badRequest": {
                    "message": "scram",
                    "code": 400,
                },
            }
            actual = jsonutils.loads(response.body)

            self.assertEqual("application/json", response.content_type)
            self.assertEqual(expected, actual)

    def test_413_fault_json(self):
        """Test fault serialized to JSON via file-extension and/or header."""
        requests = [
            webob.Request.blank('/.json'),
            webob.Request.blank('/', headers={"Accept": "application/json"}),
        ]

        for request in requests:
            exc = webob.exc.HTTPRequestEntityTooLarge
            fault = wsgi.Fault(exc(explanation='sorry',
                                   headers={'Retry-After': '4'}))
            response = request.get_response(fault)

            expected = {
                "overLimit": {
                    "message": "sorry",
                    "code": 413,
                    "retryAfter": "4",
                },
            }
            actual = jsonutils.loads(response.body)

            self.assertEqual("application/json", response.content_type)
            self.assertEqual(expected, actual)

    def test_raise(self):
        """Ensure the ability to raise :class:`Fault` in WSGI-ified methods."""
        @webob.dec.wsgify
        def raiser(req):
            raise wsgi.Fault(webob.exc.HTTPNotFound(explanation='whut?'))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual("application/xml", resp.content_type)
        self.assertEqual(404, resp.status_int)
        self.assertIn('whut?', resp.body)

    def test_raise_403(self):
        """Ensure the ability to raise :class:`Fault` in WSGI-ified methods."""
        @webob.dec.wsgify
        def raiser(req):
            raise wsgi.Fault(webob.exc.HTTPForbidden(explanation='whut?'))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual("application/xml", resp.content_type)
        self.assertEqual(403, resp.status_int)
        self.assertNotIn('resizeNotAllowed', resp.body)
        self.assertIn('forbidden', resp.body)

    @mock.patch('cinder.api.openstack.wsgi.i18n.translate')
    def test_raise_http_with_localized_explanation(self, mock_translate):
        params = ('blah', )
        expl = _("String with params: %s") % params

        def _mock_translation(msg, locale):
            return "Mensaje traducido"

        mock_translate.side_effect = _mock_translation

        @webob.dec.wsgify
        def raiser(req):
            raise wsgi.Fault(webob.exc.HTTPNotFound(explanation=expl))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual("application/xml", resp.content_type)
        self.assertEqual(404, resp.status_int)
        self.assertIn(("Mensaje traducido"), resp.body)
        self.stubs.UnsetAll()

    def test_fault_has_status_int(self):
        """Ensure the status_int is set correctly on faults."""
        fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='what?'))
        self.assertEqual(400, fault.status_int)

    def test_xml_serializer(self):
        """Ensure that a v2 request responds with a v2 xmlns."""
        request = webob.Request.blank('/v2',
                                      headers={"Accept": "application/xml"})

        fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
        response = request.get_response(fault)

        self.assertIn(common.XML_NS_V2, response.body)
        self.assertEqual("application/xml", response.content_type)
        self.assertEqual(400, response.status_int)


class FaultsXMLSerializationTestV11(test.TestCase):
    """Tests covering `cinder.api.openstack.faults:Fault` class."""

    def _prepare_xml(self, xml_string):
        xml_string = xml_string.replace("  ", "")
        xml_string = xml_string.replace("\n", "")
        xml_string = xml_string.replace("\t", "")
        return xml_string

    def test_400_fault(self):
        metadata = {'attributes': {"badRequest": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V1)

        fixture = {
            "badRequest": {
                "message": "scram",
                "code": 400,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <badRequest code="400" xmlns="%s">
                    <message>scram</message>
                </badRequest>
            """) % common.XML_NS_V1)

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_413_fault(self):
        metadata = {'attributes': {"overLimit": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V1)

        fixture = {
            "overLimit": {
                "message": "sorry",
                "code": 413,
                "retryAfter": 4,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <overLimit code="413" xmlns="%s">
                    <message>sorry</message>
                    <retryAfter>4</retryAfter>
                </overLimit>
            """) % common.XML_NS_V1)

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_404_fault(self):
        metadata = {'attributes': {"itemNotFound": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V1)

        fixture = {
            "itemNotFound": {
                "message": "sorry",
                "code": 404,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <itemNotFound code="404" xmlns="%s">
                    <message>sorry</message>
                </itemNotFound>
            """) % common.XML_NS_V1)

        self.assertEqual(expected.toxml(), actual.toxml())


class FaultsXMLSerializationTestV2(test.TestCase):
    """Tests covering `cinder.api.openstack.faults:Fault` class."""

    def _prepare_xml(self, xml_string):
        xml_string = xml_string.replace("  ", "")
        xml_string = xml_string.replace("\n", "")
        xml_string = xml_string.replace("\t", "")
        return xml_string

    def test_400_fault(self):
        metadata = {'attributes': {"badRequest": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V2)

        fixture = {
            "badRequest": {
                "message": "scram",
                "code": 400,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <badRequest code="400" xmlns="%s">
                    <message>scram</message>
                </badRequest>
            """) % common.XML_NS_V2)

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_413_fault(self):
        metadata = {'attributes': {"overLimit": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V2)

        fixture = {
            "overLimit": {
                "message": "sorry",
                "code": 413,
                "retryAfter": 4,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <overLimit code="413" xmlns="%s">
                    <message>sorry</message>
                    <retryAfter>4</retryAfter>
                </overLimit>
            """) % common.XML_NS_V2)

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_404_fault(self):
        metadata = {'attributes': {"itemNotFound": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V2)

        fixture = {
            "itemNotFound": {
                "message": "sorry",
                "code": 404,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <itemNotFound code="404" xmlns="%s">
                    <message>sorry</message>
                </itemNotFound>
            """) % common.XML_NS_V2)

        self.assertEqual(expected.toxml(), actual.toxml())
