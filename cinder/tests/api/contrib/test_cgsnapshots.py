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
Tests for cgsnapshot code.
"""

import json
from xml.dom import minidom

import mock
from oslo_log import log as logging
import webob

from cinder.consistencygroup import api as consistencygroupAPI
from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.api import fakes
from cinder.tests import utils
import cinder.volume


LOG = logging.getLogger(__name__)


class CgsnapshotsAPITestCase(test.TestCase):
    """Test Case for cgsnapshots API."""

    def setUp(self):
        super(CgsnapshotsAPITestCase, self).setUp()
        self.volume_api = cinder.volume.API()
        self.context = context.get_admin_context()
        self.context.project_id = 'fake'
        self.context.user_id = 'fake'

    @staticmethod
    def _create_cgsnapshot(
            name='test_cgsnapshot',
            description='this is a test cgsnapshot',
            consistencygroup_id='1',
            status='creating'):
        """Create a cgsnapshot object."""
        cgsnapshot = {}
        cgsnapshot['user_id'] = 'fake'
        cgsnapshot['project_id'] = 'fake'
        cgsnapshot['consistencygroup_id'] = consistencygroup_id
        cgsnapshot['name'] = name
        cgsnapshot['description'] = description
        cgsnapshot['status'] = status
        return db.cgsnapshot_create(context.get_admin_context(),
                                    cgsnapshot)['id']

    @staticmethod
    def _get_cgsnapshot_attrib(cgsnapshot_id, attrib_name):
        return db.cgsnapshot_get(context.get_admin_context(),
                                 cgsnapshot_id)[attrib_name]

    def test_show_cgsnapshot(self):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        volume_id = utils.create_volume(self.context,
                                        consistencygroup_id=
                                        consistencygroup_id)['id']
        cgsnapshot_id = self._create_cgsnapshot(
            consistencygroup_id=consistencygroup_id)
        LOG.debug('Created cgsnapshot with id %s' % cgsnapshot_id)
        req = webob.Request.blank('/v2/fake/cgsnapshots/%s' %
                                  cgsnapshot_id)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['cgsnapshot']['description'],
                         'this is a test cgsnapshot')
        self.assertEqual(res_dict['cgsnapshot']['name'],
                         'test_cgsnapshot')
        self.assertEqual(res_dict['cgsnapshot']['status'], 'creating')

        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id)
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_show_cgsnapshot_xml_content_type(self):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        volume_id = utils.create_volume(self.context,
                                        consistencygroup_id=
                                        consistencygroup_id)['id']
        cgsnapshot_id = self._create_cgsnapshot(
            consistencygroup_id=consistencygroup_id)
        req = webob.Request.blank('/v2/fake/cgsnapshots/%s' %
                                  cgsnapshot_id)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        cgsnapshot = dom.getElementsByTagName('cgsnapshot')
        name = cgsnapshot.item(0).getAttribute('name')
        self.assertEqual(name.strip(), "test_cgsnapshot")
        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id)
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_show_cgsnapshot_with_cgsnapshot_NotFound(self):
        req = webob.Request.blank('/v2/fake/cgsnapshots/9999')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'CgSnapshot 9999 could not be found.')

    def test_list_cgsnapshots_json(self):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        volume_id = utils.create_volume(self.context,
                                        consistencygroup_id=
                                        consistencygroup_id)['id']
        cgsnapshot_id1 = self._create_cgsnapshot(
            consistencygroup_id=consistencygroup_id)
        cgsnapshot_id2 = self._create_cgsnapshot(
            consistencygroup_id=consistencygroup_id)
        cgsnapshot_id3 = self._create_cgsnapshot(
            consistencygroup_id=consistencygroup_id)

        req = webob.Request.blank('/v2/fake/cgsnapshots')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['cgsnapshots'][0]['id'],
                         cgsnapshot_id1)
        self.assertEqual(res_dict['cgsnapshots'][0]['name'],
                         'test_cgsnapshot')
        self.assertEqual(res_dict['cgsnapshots'][1]['id'],
                         cgsnapshot_id2)
        self.assertEqual(res_dict['cgsnapshots'][1]['name'],
                         'test_cgsnapshot')
        self.assertEqual(res_dict['cgsnapshots'][2]['id'],
                         cgsnapshot_id3)
        self.assertEqual(res_dict['cgsnapshots'][2]['name'],
                         'test_cgsnapshot')

        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id3)
        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id2)
        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id1)
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_list_cgsnapshots_xml(self):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        volume_id = utils.create_volume(self.context,
                                        consistencygroup_id=
                                        consistencygroup_id)['id']
        cgsnapshot_id1 = self._create_cgsnapshot(consistencygroup_id=
                                                 consistencygroup_id)
        cgsnapshot_id2 = self._create_cgsnapshot(consistencygroup_id=
                                                 consistencygroup_id)
        cgsnapshot_id3 = self._create_cgsnapshot(consistencygroup_id=
                                                 consistencygroup_id)

        req = webob.Request.blank('/v2/fake/cgsnapshots')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        cgsnapshot_list = dom.getElementsByTagName('cgsnapshot')

        self.assertEqual(cgsnapshot_list.item(0).getAttribute('id'),
                         cgsnapshot_id1)
        self.assertEqual(cgsnapshot_list.item(1).getAttribute('id'),
                         cgsnapshot_id2)
        self.assertEqual(cgsnapshot_list.item(2).getAttribute('id'),
                         cgsnapshot_id3)

        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id3)
        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id2)
        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id1)
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_list_cgsnapshots_detail_json(self):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        volume_id = utils.create_volume(self.context,
                                        consistencygroup_id=
                                        consistencygroup_id)['id']
        cgsnapshot_id1 = self._create_cgsnapshot(consistencygroup_id=
                                                 consistencygroup_id)
        cgsnapshot_id2 = self._create_cgsnapshot(consistencygroup_id=
                                                 consistencygroup_id)
        cgsnapshot_id3 = self._create_cgsnapshot(consistencygroup_id=
                                                 consistencygroup_id)

        req = webob.Request.blank('/v2/fake/cgsnapshots/detail')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['cgsnapshots'][0]['description'],
                         'this is a test cgsnapshot')
        self.assertEqual(res_dict['cgsnapshots'][0]['name'],
                         'test_cgsnapshot')
        self.assertEqual(res_dict['cgsnapshots'][0]['id'],
                         cgsnapshot_id1)
        self.assertEqual(res_dict['cgsnapshots'][0]['status'],
                         'creating')

        self.assertEqual(res_dict['cgsnapshots'][1]['description'],
                         'this is a test cgsnapshot')
        self.assertEqual(res_dict['cgsnapshots'][1]['name'],
                         'test_cgsnapshot')
        self.assertEqual(res_dict['cgsnapshots'][1]['id'],
                         cgsnapshot_id2)
        self.assertEqual(res_dict['cgsnapshots'][1]['status'],
                         'creating')

        self.assertEqual(res_dict['cgsnapshots'][2]['description'],
                         'this is a test cgsnapshot')
        self.assertEqual(res_dict['cgsnapshots'][2]['name'],
                         'test_cgsnapshot')
        self.assertEqual(res_dict['cgsnapshots'][2]['id'],
                         cgsnapshot_id3)
        self.assertEqual(res_dict['cgsnapshots'][2]['status'],
                         'creating')

        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id3)
        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id2)
        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id1)
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_list_cgsnapshots_detail_xml(self):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        volume_id = utils.create_volume(self.context,
                                        consistencygroup_id=
                                        consistencygroup_id)['id']
        cgsnapshot_id1 = self._create_cgsnapshot(consistencygroup_id=
                                                 consistencygroup_id)
        cgsnapshot_id2 = self._create_cgsnapshot(consistencygroup_id=
                                                 consistencygroup_id)
        cgsnapshot_id3 = self._create_cgsnapshot(consistencygroup_id=
                                                 consistencygroup_id)

        req = webob.Request.blank('/v2/fake/cgsnapshots/detail')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        cgsnapshot_detail = dom.getElementsByTagName('cgsnapshot')

        self.assertEqual(
            cgsnapshot_detail.item(0).getAttribute('description'),
            'this is a test cgsnapshot')
        self.assertEqual(
            cgsnapshot_detail.item(0).getAttribute('name'),
            'test_cgsnapshot')
        self.assertEqual(
            cgsnapshot_detail.item(0).getAttribute('id'),
            cgsnapshot_id1)
        self.assertEqual(
            cgsnapshot_detail.item(0).getAttribute('status'), 'creating')

        self.assertEqual(
            cgsnapshot_detail.item(1).getAttribute('description'),
            'this is a test cgsnapshot')
        self.assertEqual(
            cgsnapshot_detail.item(1).getAttribute('name'),
            'test_cgsnapshot')
        self.assertEqual(
            cgsnapshot_detail.item(1).getAttribute('id'),
            cgsnapshot_id2)
        self.assertEqual(
            cgsnapshot_detail.item(1).getAttribute('status'), 'creating')

        self.assertEqual(
            cgsnapshot_detail.item(2).getAttribute('description'),
            'this is a test cgsnapshot')
        self.assertEqual(
            cgsnapshot_detail.item(2).getAttribute('name'),
            'test_cgsnapshot')
        self.assertEqual(
            cgsnapshot_detail.item(2).getAttribute('id'),
            cgsnapshot_id3)
        self.assertEqual(
            cgsnapshot_detail.item(2).getAttribute('status'), 'creating')

        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id3)
        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id2)
        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id1)
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_create_cgsnapshot_json(self):
        cgsnapshot_id = "1"

        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        utils.create_volume(
            self.context,
            consistencygroup_id=consistencygroup_id)['id']

        body = {"cgsnapshot": {"name": "cg1",
                               "description":
                               "CG Snapshot 1",
                               "consistencygroup_id": consistencygroup_id}}
        req = webob.Request.blank('/v2/fake/cgsnapshots')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        res_dict = json.loads(res.body)
        LOG.info(res_dict)

        self.assertEqual(res.status_int, 202)
        self.assertIn('id', res_dict['cgsnapshot'])

        db.cgsnapshot_destroy(context.get_admin_context(), cgsnapshot_id)

    def test_create_cgsnapshot_with_no_body(self):
        # omit body from the request
        req = webob.Request.blank('/v2/fake/cgsnapshots')
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

    @mock.patch.object(consistencygroupAPI.API, 'create_cgsnapshot',
                       side_effect=exception.InvalidCgSnapshot(
                           reason='invalid cgsnapshot'))
    def test_create_with_invalid_cgsnapshot(self, mock_create_cgsnapshot):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        utils.create_volume(
            self.context,
            consistencygroup_id=consistencygroup_id)['id']

        body = {"cgsnapshot": {"name": "cg1",
                               "description":
                               "CG Snapshot 1",
                               "consistencygroup_id": consistencygroup_id}}
        req = webob.Request.blank('/v2/fake/cgsnapshots')
        req.body = json.dumps(body)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertEqual('Invalid CgSnapshot: invalid cgsnapshot',
                         res_dict['badRequest']['message'])

    @mock.patch.object(consistencygroupAPI.API, 'create_cgsnapshot',
                       side_effect=exception.CgSnapshotNotFound(
                           cgsnapshot_id='invalid_id'))
    def test_create_with_cgsnapshot_not_found(self, mock_create_cgsnapshot):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        utils.create_volume(
            self.context,
            consistencygroup_id=consistencygroup_id)['id']

        body = {"cgsnapshot": {"name": "cg1",
                               "description":
                               "CG Snapshot 1",
                               "consistencygroup_id": consistencygroup_id}}

        req = webob.Request.blank('/v2/fake/cgsnapshots')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(404, res.status_int)
        self.assertEqual(404, res_dict['itemNotFound']['code'])
        self.assertEqual('CgSnapshot invalid_id could not be found.',
                         res_dict['itemNotFound']['message'])

    def test_delete_cgsnapshot_available(self):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        volume_id = utils.create_volume(
            self.context,
            consistencygroup_id=consistencygroup_id)['id']
        cgsnapshot_id = self._create_cgsnapshot(
            consistencygroup_id=consistencygroup_id,
            status='available')
        req = webob.Request.blank('/v2/fake/cgsnapshots/%s' %
                                  cgsnapshot_id)
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        self.assertEqual(self._get_cgsnapshot_attrib(cgsnapshot_id,
                         'status'),
                         'deleting')

        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id)
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_delete_cgsnapshot_with_cgsnapshot_NotFound(self):
        req = webob.Request.blank('/v2/fake/cgsnapshots/9999')
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Cgsnapshot could not be found')

    def test_delete_cgsnapshot_with_Invalidcgsnapshot(self):
        consistencygroup_id = utils.create_consistencygroup(self.context)['id']
        volume_id = utils.create_volume(
            self.context,
            consistencygroup_id=consistencygroup_id)['id']
        cgsnapshot_id = self._create_cgsnapshot(
            consistencygroup_id=consistencygroup_id,
            status='invalid')
        req = webob.Request.blank('/v2/fake/cgsnapshots/%s' %
                                  cgsnapshot_id)
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid cgsnapshot')

        db.cgsnapshot_destroy(context.get_admin_context(),
                              cgsnapshot_id)
        db.volume_destroy(context.get_admin_context(),
                          volume_id)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)
