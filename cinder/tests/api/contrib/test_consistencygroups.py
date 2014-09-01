# Copyright (C) 2012 - 2014 EMC Corporation.
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

"""
Tests for consistency group code.
"""

import json
from xml.dom import minidom

import webob

from cinder import context
from cinder import db
from cinder import test
from cinder.tests.api import fakes
import cinder.volume


class ConsistencyGroupsAPITestCase(test.TestCase):
    """Test Case for consistency groups API."""

    def setUp(self):
        super(ConsistencyGroupsAPITestCase, self).setUp()
        self.volume_api = cinder.volume.API()
        self.context = context.get_admin_context()
        self.context.project_id = 'fake'
        self.context.user_id = 'fake'

    @staticmethod
    def _create_consistencygroup(
            name='test_consistencygroup',
            description='this is a test consistency group',
            volume_type_id='123456',
            availability_zone='az1',
            status='creating'):
        """Create a consistency group object."""
        consistencygroup = {}
        consistencygroup['user_id'] = 'fake'
        consistencygroup['project_id'] = 'fake'
        consistencygroup['availability_zone'] = availability_zone
        consistencygroup['name'] = name
        consistencygroup['description'] = description
        consistencygroup['volume_type_id'] = volume_type_id
        consistencygroup['status'] = status
        consistencygroup['host'] = 'fakehost'
        return db.consistencygroup_create(
            context.get_admin_context(),
            consistencygroup)['id']

    @staticmethod
    def _get_consistencygroup_attrib(consistencygroup_id, attrib_name):
        return db.consistencygroup_get(context.get_admin_context(),
                                       consistencygroup_id)[attrib_name]

    def test_show_consistencygroup(self):
        consistencygroup_id = self._create_consistencygroup()
        req = webob.Request.blank('/v2/fake/consistencygroups/%s' %
                                  consistencygroup_id)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['consistencygroup']['availability_zone'],
                         'az1')
        self.assertEqual(res_dict['consistencygroup']['description'],
                         'this is a test consistency group')
        self.assertEqual(res_dict['consistencygroup']['name'],
                         'test_consistencygroup')
        self.assertEqual(res_dict['consistencygroup']['status'], 'creating')

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_show_consistencygroup_xml_content_type(self):
        consistencygroup_id = self._create_consistencygroup()
        req = webob.Request.blank('/v2/fake/consistencygroups/%s' %
                                  consistencygroup_id)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        consistencygroup = dom.getElementsByTagName('consistencygroup')
        name = consistencygroup.item(0).getAttribute('name')
        self.assertEqual(name.strip(), "test_consistencygroup")
        db.consistencygroup_destroy(
            context.get_admin_context(),
            consistencygroup_id)

    def test_show_consistencygroup_with_consistencygroup_NotFound(self):
        req = webob.Request.blank('/v2/fake/consistencygroups/9999')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'ConsistencyGroup 9999 could not be found.')

    def test_list_consistencygroups_json(self):
        consistencygroup_id1 = self._create_consistencygroup()
        consistencygroup_id2 = self._create_consistencygroup()
        consistencygroup_id3 = self._create_consistencygroup()

        req = webob.Request.blank('/v2/fake/consistencygroups')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['consistencygroups'][0]['id'],
                         consistencygroup_id1)
        self.assertEqual(res_dict['consistencygroups'][0]['name'],
                         'test_consistencygroup')
        self.assertEqual(res_dict['consistencygroups'][1]['id'],
                         consistencygroup_id2)
        self.assertEqual(res_dict['consistencygroups'][1]['name'],
                         'test_consistencygroup')
        self.assertEqual(res_dict['consistencygroups'][2]['id'],
                         consistencygroup_id3)
        self.assertEqual(res_dict['consistencygroups'][2]['name'],
                         'test_consistencygroup')

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id3)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id2)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id1)

    def test_list_consistencygroups_xml(self):
        consistencygroup_id1 = self._create_consistencygroup()
        consistencygroup_id2 = self._create_consistencygroup()
        consistencygroup_id3 = self._create_consistencygroup()

        req = webob.Request.blank('/v2/fake/consistencygroups')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        consistencygroup_list = dom.getElementsByTagName('consistencygroup')

        self.assertEqual(consistencygroup_list.item(0).getAttribute('id'),
                         consistencygroup_id1)
        self.assertEqual(consistencygroup_list.item(1).getAttribute('id'),
                         consistencygroup_id2)
        self.assertEqual(consistencygroup_list.item(2).getAttribute('id'),
                         consistencygroup_id3)

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id3)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id2)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id1)

    def test_list_consistencygroups_detail_json(self):
        consistencygroup_id1 = self._create_consistencygroup()
        consistencygroup_id2 = self._create_consistencygroup()
        consistencygroup_id3 = self._create_consistencygroup()

        req = webob.Request.blank('/v2/fake/consistencygroups/detail')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['consistencygroups'][0]['availability_zone'],
                         'az1')
        self.assertEqual(res_dict['consistencygroups'][0]['description'],
                         'this is a test consistency group')
        self.assertEqual(res_dict['consistencygroups'][0]['name'],
                         'test_consistencygroup')
        self.assertEqual(res_dict['consistencygroups'][0]['id'],
                         consistencygroup_id1)
        self.assertEqual(res_dict['consistencygroups'][0]['status'],
                         'creating')

        self.assertEqual(res_dict['consistencygroups'][1]['availability_zone'],
                         'az1')
        self.assertEqual(res_dict['consistencygroups'][1]['description'],
                         'this is a test consistency group')
        self.assertEqual(res_dict['consistencygroups'][1]['name'],
                         'test_consistencygroup')
        self.assertEqual(res_dict['consistencygroups'][1]['id'],
                         consistencygroup_id2)
        self.assertEqual(res_dict['consistencygroups'][1]['status'],
                         'creating')

        self.assertEqual(res_dict['consistencygroups'][2]['availability_zone'],
                         'az1')
        self.assertEqual(res_dict['consistencygroups'][2]['description'],
                         'this is a test consistency group')
        self.assertEqual(res_dict['consistencygroups'][2]['name'],
                         'test_consistencygroup')
        self.assertEqual(res_dict['consistencygroups'][2]['id'],
                         consistencygroup_id3)
        self.assertEqual(res_dict['consistencygroups'][2]['status'],
                         'creating')

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id3)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id2)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id1)

    def test_list_consistencygroups_detail_xml(self):
        consistencygroup_id1 = self._create_consistencygroup()
        consistencygroup_id2 = self._create_consistencygroup()
        consistencygroup_id3 = self._create_consistencygroup()

        req = webob.Request.blank('/v2/fake/consistencygroups/detail')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        consistencygroup_detail = dom.getElementsByTagName('consistencygroup')

        self.assertEqual(
            consistencygroup_detail.item(0).getAttribute('availability_zone'),
            'az1')
        self.assertEqual(
            consistencygroup_detail.item(0).getAttribute('description'),
            'this is a test consistency group')
        self.assertEqual(
            consistencygroup_detail.item(0).getAttribute('name'),
            'test_consistencygroup')
        self.assertEqual(
            consistencygroup_detail.item(0).getAttribute('id'),
            consistencygroup_id1)
        self.assertEqual(
            consistencygroup_detail.item(0).getAttribute('status'), 'creating')

        self.assertEqual(
            consistencygroup_detail.item(1).getAttribute('availability_zone'),
            'az1')
        self.assertEqual(
            consistencygroup_detail.item(1).getAttribute('description'),
            'this is a test consistency group')
        self.assertEqual(
            consistencygroup_detail.item(1).getAttribute('name'),
            'test_consistencygroup')
        self.assertEqual(
            consistencygroup_detail.item(1).getAttribute('id'),
            consistencygroup_id2)
        self.assertEqual(
            consistencygroup_detail.item(1).getAttribute('status'), 'creating')

        self.assertEqual(
            consistencygroup_detail.item(2).getAttribute('availability_zone'),
            'az1')
        self.assertEqual(
            consistencygroup_detail.item(2).getAttribute('description'),
            'this is a test consistency group')
        self.assertEqual(
            consistencygroup_detail.item(2).getAttribute('name'),
            'test_consistencygroup')
        self.assertEqual(
            consistencygroup_detail.item(2).getAttribute('id'),
            consistencygroup_id3)
        self.assertEqual(
            consistencygroup_detail.item(2).getAttribute('status'), 'creating')

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id3)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id2)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id1)

    def test_create_consistencygroup_json(self):
        group_id = "1"
        body = {"consistencygroup": {"name": "cg1",
                                     "description":
                                     "Consistency Group 1", }}
        req = webob.Request.blank('/v2/fake/consistencygroups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 202)
        self.assertIn('id', res_dict['consistencygroup'])

        db.consistencygroup_destroy(context.get_admin_context(), group_id)

    def test_create_consistencygroup_with_no_body(self):
        # omit body from the request
        req = webob.Request.blank('/v2/fake/consistencygroups')
        req.body = json.dumps(None)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'The server could not comply with the request since'
                         ' it is either malformed or otherwise incorrect.')

    def test_delete_consistencygroup_available(self):
        consistencygroup_id = self._create_consistencygroup(status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"force": True}}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        self.assertEqual(self._get_consistencygroup_attrib(consistencygroup_id,
                         'status'),
                         'deleting')

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_delete_consistencygroup_with_consistencygroup_NotFound(self):
        req = webob.Request.blank('/v2/fake/consistencygroups/9999/delete')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(None)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Consistency group could not be found')

    def test_delete_consistencygroup_with_Invalidconsistencygroup(self):
        consistencygroup_id = self._create_consistencygroup(status='invalid')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"force": False}}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid consistency group')

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)
