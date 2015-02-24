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

import mock
import webob

import cinder.consistencygroup
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import test
from cinder.tests.api import fakes
from cinder.tests.api.v2 import stubs
from cinder.tests import utils
from cinder.volume import api as volume_api


class ConsistencyGroupsAPITestCase(test.TestCase):
    """Test Case for consistency groups API."""

    def setUp(self):
        super(ConsistencyGroupsAPITestCase, self).setUp()
        self.cg_api = cinder.consistencygroup.API()

    @staticmethod
    def _create_consistencygroup(
            name='test_consistencygroup',
            description='this is a test consistency group',
            volume_type_id='123456',
            availability_zone='az1',
            host='fakehost',
            status='creating'):
        """Create a consistency group object."""
        consistencygroup = {}
        consistencygroup['user_id'] = 'fake'
        consistencygroup['project_id'] = 'fake'
        consistencygroup['availability_zone'] = availability_zone
        consistencygroup['name'] = name
        consistencygroup['description'] = description
        consistencygroup['volume_type_id'] = volume_type_id
        consistencygroup['host'] = host
        consistencygroup['status'] = status
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

        self.assertEqual(200, res.status_int)
        self.assertEqual('az1',
                         res_dict['consistencygroup']['availability_zone'])
        self.assertEqual('this is a test consistency group',
                         res_dict['consistencygroup']['description'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroup']['name'])
        self.assertEqual('creating',
                         res_dict['consistencygroup']['status'])

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
        self.assertEqual(200, res.status_int)
        dom = minidom.parseString(res.body)
        consistencygroup = dom.getElementsByTagName('consistencygroup')
        name = consistencygroup.item(0).getAttribute('name')
        self.assertEqual("test_consistencygroup", name.strip())
        db.consistencygroup_destroy(
            context.get_admin_context(),
            consistencygroup_id)

    def test_show_consistencygroup_with_consistencygroup_NotFound(self):
        req = webob.Request.blank('/v2/fake/consistencygroups/9999')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(404, res.status_int)
        self.assertEqual(404, res_dict['itemNotFound']['code'])
        self.assertEqual('ConsistencyGroup 9999 could not be found.',
                         res_dict['itemNotFound']['message'])

    def test_list_consistencygroups_json(self):
        consistencygroup_id1 = self._create_consistencygroup()
        consistencygroup_id2 = self._create_consistencygroup()
        consistencygroup_id3 = self._create_consistencygroup()

        req = webob.Request.blank('/v2/fake/consistencygroups')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(200, res.status_int)
        self.assertEqual(consistencygroup_id1,
                         res_dict['consistencygroups'][0]['id'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][0]['name'])
        self.assertEqual(consistencygroup_id2,
                         res_dict['consistencygroups'][1]['id'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][1]['name'])
        self.assertEqual(consistencygroup_id3,
                         res_dict['consistencygroups'][2]['id'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][2]['name'])

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

        self.assertEqual(200, res.status_int)
        dom = minidom.parseString(res.body)
        consistencygroup_list = dom.getElementsByTagName('consistencygroup')

        self.assertEqual(consistencygroup_id1,
                         consistencygroup_list.item(0).getAttribute('id'))
        self.assertEqual(consistencygroup_id2,
                         consistencygroup_list.item(1).getAttribute('id'))
        self.assertEqual(consistencygroup_id3,
                         consistencygroup_list.item(2).getAttribute('id'))

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

        self.assertEqual(200, res.status_int)
        self.assertEqual('az1',
                         res_dict['consistencygroups'][0]['availability_zone'])
        self.assertEqual('this is a test consistency group',
                         res_dict['consistencygroups'][0]['description'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][0]['name'])
        self.assertEqual(consistencygroup_id1,
                         res_dict['consistencygroups'][0]['id'])
        self.assertEqual('creating',
                         res_dict['consistencygroups'][0]['status'])

        self.assertEqual('az1',
                         res_dict['consistencygroups'][1]['availability_zone'])
        self.assertEqual('this is a test consistency group',
                         res_dict['consistencygroups'][1]['description'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][1]['name'])
        self.assertEqual(consistencygroup_id2,
                         res_dict['consistencygroups'][1]['id'])
        self.assertEqual('creating',
                         res_dict['consistencygroups'][1]['status'])

        self.assertEqual('az1',
                         res_dict['consistencygroups'][2]['availability_zone'])
        self.assertEqual('this is a test consistency group',
                         res_dict['consistencygroups'][2]['description'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][2]['name'])
        self.assertEqual(consistencygroup_id3,
                         res_dict['consistencygroups'][2]['id'])
        self.assertEqual('creating',
                         res_dict['consistencygroups'][2]['status'])

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

        self.assertEqual(200, res.status_int)
        dom = minidom.parseString(res.body)
        consistencygroup_detail = dom.getElementsByTagName('consistencygroup')

        self.assertEqual(
            'az1',
            consistencygroup_detail.item(0).getAttribute('availability_zone'))
        self.assertEqual(
            'this is a test consistency group',
            consistencygroup_detail.item(0).getAttribute('description'))
        self.assertEqual(
            'test_consistencygroup',
            consistencygroup_detail.item(0).getAttribute('name'))
        self.assertEqual(
            consistencygroup_id1,
            consistencygroup_detail.item(0).getAttribute('id'))
        self.assertEqual(
            'creating',
            consistencygroup_detail.item(0).getAttribute('status'))

        self.assertEqual(
            'az1',
            consistencygroup_detail.item(1).getAttribute('availability_zone'))
        self.assertEqual(
            'this is a test consistency group',
            consistencygroup_detail.item(1).getAttribute('description'))
        self.assertEqual(
            'test_consistencygroup',
            consistencygroup_detail.item(1).getAttribute('name'))
        self.assertEqual(
            consistencygroup_id2,
            consistencygroup_detail.item(1).getAttribute('id'))
        self.assertEqual(
            'creating',
            consistencygroup_detail.item(1).getAttribute('status'))

        self.assertEqual(
            'az1',
            consistencygroup_detail.item(2).getAttribute('availability_zone'))
        self.assertEqual(
            'this is a test consistency group',
            consistencygroup_detail.item(2).getAttribute('description'))
        self.assertEqual(
            'test_consistencygroup',
            consistencygroup_detail.item(2).getAttribute('name'))
        self.assertEqual(
            consistencygroup_id3,
            consistencygroup_detail.item(2).getAttribute('id'))
        self.assertEqual(
            'creating',
            consistencygroup_detail.item(2).getAttribute('status'))

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id3)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id2)
        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id1)

    def test_create_consistencygroup_json(self):
        group_id = "1"

        # Create volume type
        vol_type = 'test'
        db.volume_type_create(context.get_admin_context(),
                              {'name': vol_type, 'extra_specs': {}})

        body = {"consistencygroup": {"name": "cg1",
                                     "volume_types": vol_type,
                                     "description":
                                     "Consistency Group 1", }}
        req = webob.Request.blank('/v2/fake/consistencygroups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(202, res.status_int)
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

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertEqual('The server could not comply with the request since'
                         ' it is either malformed or otherwise incorrect.',
                         res_dict['badRequest']['message'])

    def test_delete_consistencygroup_available(self):
        consistencygroup_id = self._create_consistencygroup(status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"force": True}}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(202, res.status_int)
        self.assertEqual('deleting',
                         self._get_consistencygroup_attrib(consistencygroup_id,
                                                           'status'))

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_delete_consistencygroup_with_consistencygroup_NotFound(self):
        req = webob.Request.blank('/v2/fake/consistencygroups/9999/delete')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(None)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(404, res.status_int)
        self.assertEqual(404, res_dict['itemNotFound']['code'])
        self.assertEqual('Consistency group 9999 could not be found.',
                         res_dict['itemNotFound']['message'])

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

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = (_('Invalid ConsistencyGroup: Consistency group status must be '
                 'available or error, but current status is: invalid'))
        self.assertEqual(msg, res_dict['badRequest']['message'])

        db.consistencygroup_destroy(context.get_admin_context(),
                                    consistencygroup_id)

    def test_delete_consistencygroup_no_host(self):
        consistencygroup_id = self._create_consistencygroup(
            host=None,
            status='error')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"force": True}}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

        cg = db.consistencygroup_get(
            context.get_admin_context(read_deleted='yes'),
            consistencygroup_id)
        self.assertEqual(cg['status'], 'deleted')
        self.assertEqual(cg['host'], None)

    def test_create_delete_consistencygroup_update_quota(self):
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        name = 'mycg'
        description = 'consistency group 1'
        fake_type = {'id': '1', 'name': 'fake_type'}
        self.stubs.Set(db, 'volume_types_get_by_name_or_id',
                       mock.Mock(return_value=[fake_type]))
        self.stubs.Set(self.cg_api,
                       '_cast_create_consistencygroup',
                       mock.Mock())
        self.stubs.Set(self.cg_api, 'update_quota',
                       mock.Mock())

        cg = self.cg_api.create(ctxt, name, description, fake_type['name'])
        self.cg_api.update_quota.assert_called_once_with(
            ctxt, cg['id'], 1)
        self.assertEqual(cg['status'], 'creating')
        self.assertEqual(cg['host'], None)
        self.cg_api.update_quota.reset_mock()

        cg['status'] = 'error'
        self.cg_api.delete(ctxt, cg)
        self.cg_api.update_quota.assert_called_once_with(
            ctxt, cg['id'], -1, ctxt.project_id)
        cg = db.consistencygroup_get(
            context.get_admin_context(read_deleted='yes'),
            cg['id'])
        self.assertEqual(cg['status'], 'deleted')

    def test_create_consistencygroup_failed_no_volume_type(self):
        name = 'cg1'
        body = {"consistencygroup": {"name": name,
                                     "description":
                                     "Consistency Group 1", }}
        req = webob.Request.blank('/v2/fake/consistencygroups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = (_('volume_types must be provided to create '
                 'consistency group %s.') % name)
        self.assertEqual(msg, res_dict['badRequest']['message'])

    def test_update_consistencygroup_success(self):
        volume_type_id = '123456'
        ctxt = context.RequestContext('fake', 'fake')
        consistencygroup_id = self._create_consistencygroup(status='available',
                                                            host='test_host')
        remove_volume_id = utils.create_volume(
            ctxt,
            volume_type_id=volume_type_id,
            consistencygroup_id=consistencygroup_id)['id']
        remove_volume_id2 = utils.create_volume(
            ctxt,
            volume_type_id=volume_type_id,
            consistencygroup_id=consistencygroup_id)['id']

        self.assertEqual('available',
                         self._get_consistencygroup_attrib(consistencygroup_id,
                                                           'status'))

        cg_volumes = db.volume_get_all_by_group(ctxt.elevated(),
                                                consistencygroup_id)
        cg_vol_ids = [cg_vol['id'] for cg_vol in cg_volumes]
        self.assertIn(remove_volume_id, cg_vol_ids)
        self.assertIn(remove_volume_id2, cg_vol_ids)

        add_volume_id = utils.create_volume(
            ctxt,
            volume_type_id=volume_type_id)['id']
        add_volume_id2 = utils.create_volume(
            ctxt,
            volume_type_id=volume_type_id)['id']
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        name = 'newcg'
        description = 'New Consistency Group Description'
        add_volumes = add_volume_id + "," + add_volume_id2
        remove_volumes = remove_volume_id + "," + remove_volume_id2
        body = {"consistencygroup": {"name": name,
                                     "description": description,
                                     "add_volumes": add_volumes,
                                     "remove_volumes": remove_volumes, }}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(202, res.status_int)
        self.assertEqual('updating',
                         self._get_consistencygroup_attrib(consistencygroup_id,
                                                           'status'))

        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    def test_update_consistencygroup_add_volume_not_found(self):
        ctxt = context.RequestContext('fake', 'fake')
        consistencygroup_id = self._create_consistencygroup(status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"name": None,
                                     "description": None,
                                     "add_volumes": "fake-volume-uuid",
                                     "remove_volumes": None, }}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = (_("Invalid volume: Cannot add volume fake-volume-uuid "
                 "to consistency group %(group_id)s because volume cannot "
                 "be found.") %
               {'group_id': consistencygroup_id})
        self.assertEqual(msg, res_dict['badRequest']['message'])

        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    def test_update_consistencygroup_remove_volume_not_found(self):
        ctxt = context.RequestContext('fake', 'fake')
        consistencygroup_id = self._create_consistencygroup(status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"name": None,
                                     "description": "new description",
                                     "add_volumes": None,
                                     "remove_volumes": "fake-volume-uuid", }}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = (_("Invalid volume: Cannot remove volume fake-volume-uuid "
                 "from consistency group %(group_id)s because it is not "
                 "in the group.") %
               {'group_id': consistencygroup_id})
        self.assertEqual(msg, res_dict['badRequest']['message'])

        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    def test_update_consistencygroup_empty_parameters(self):
        ctxt = context.RequestContext('fake', 'fake')
        consistencygroup_id = self._create_consistencygroup(status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"name": "",
                                     "description": "",
                                     "add_volumes": None,
                                     "remove_volumes": None, }}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertEqual('Name, description, add_volumes, and remove_volumes '
                         'can not be all empty in the request body.',
                         res_dict['badRequest']['message'])

        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    def test_update_consistencygroup_add_volume_invalid_state(self):
        volume_type_id = '123456'
        ctxt = context.RequestContext('fake', 'fake')
        consistencygroup_id = self._create_consistencygroup(status='available')
        add_volume_id = utils.create_volume(
            ctxt,
            volume_type_id=volume_type_id,
            status='wrong_status')['id']
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        add_volumes = add_volume_id
        body = {"consistencygroup": {"name": "",
                                     "description": "",
                                     "add_volumes": add_volumes,
                                     "remove_volumes": None, }}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = (_("Invalid volume: Cannot add volume %(volume_id)s "
                 "to consistency group %(group_id)s because volume is in an "
                 "invalid state: %(status)s. Valid states are: ('available', "
                 "'in-use').") %
               {'volume_id': add_volume_id,
                'group_id': consistencygroup_id,
                'status': 'wrong_status'})
        self.assertEqual(msg, res_dict['badRequest']['message'])

        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    def test_update_consistencygroup_add_volume_invalid_volume_type(self):
        ctxt = context.RequestContext('fake', 'fake')
        consistencygroup_id = self._create_consistencygroup(status='available')
        wrong_type = 'wrong-volume-type-id'
        add_volume_id = utils.create_volume(
            ctxt,
            volume_type_id=wrong_type)['id']
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        add_volumes = add_volume_id
        body = {"consistencygroup": {"name": "",
                                     "description": "",
                                     "add_volumes": add_volumes,
                                     "remove_volumes": None, }}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = (_("Invalid volume: Cannot add volume %(volume_id)s "
                 "to consistency group %(group_id)s because volume type "
                 "%(volume_type)s is not supported by the group.") %
               {'volume_id': add_volume_id,
                'group_id': consistencygroup_id,
                'volume_type': wrong_type})
        self.assertEqual(msg, res_dict['badRequest']['message'])

        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    def test_update_consistencygroup_invalid_state(self):
        ctxt = context.RequestContext('fake', 'fake')
        wrong_status = 'wrong_status'
        consistencygroup_id = self._create_consistencygroup(
            status=wrong_status)
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup_id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"name": "new name",
                                     "description": None,
                                     "add_volumes": None,
                                     "remove_volumes": None, }}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = _("Invalid ConsistencyGroup: Consistency group status must be "
                "available, but current status is: %s.") % wrong_status
        self.assertEqual(msg, res_dict['badRequest']['message'])

        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    def test_create_consistencygroup_from_src(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)

        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        consistencygroup_id = utils.create_consistencygroup(ctxt)['id']
        volume_id = utils.create_volume(
            ctxt,
            consistencygroup_id=consistencygroup_id)['id']
        cgsnapshot_id = utils.create_cgsnapshot(
            ctxt,
            consistencygroup_id=consistencygroup_id)['id']
        snapshot_id = utils.create_snapshot(
            ctxt,
            volume_id,
            cgsnapshot_id=cgsnapshot_id,
            status='available')['id']

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": cgsnapshot_id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(202, res.status_int)
        self.assertIn('id', res_dict['consistencygroup'])
        self.assertEqual(test_cg_name, res_dict['consistencygroup']['name'])

        db.consistencygroup_destroy(ctxt.elevated(),
                                    res_dict['consistencygroup']['id'])
        db.snapshot_destroy(ctxt.elevated(), snapshot_id)
        db.cgsnapshot_destroy(ctxt.elevated(), cgsnapshot_id)
        db.volume_destroy(ctxt.elevated(), volume_id)
        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    def test_create_consistencygroup_from_src_invalid_body(self):
        name = 'cg1'
        body = {"invalid": {"name": name,
                            "description":
                            "Consistency Group 1", }}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = (_('The server could not comply with the request since '
                 'it is either malformed or otherwise incorrect.'))
        self.assertEqual(msg, res_dict['badRequest']['message'])

    def test_create_consistencygroup_from_src_no_cgsnapshot_id(self):
        name = 'cg1'
        body = {"consistencygroup-from-src": {"name": name,
                                              "description":
                                              "Consistency Group 1", }}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = (_('Cgsnapshot id must be provided to create '
                 'consistency group %s from source.') % name)
        self.assertEqual(msg, res_dict['badRequest']['message'])

    def test_create_consistencygroup_from_src_no_host(self):
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        consistencygroup_id = utils.create_consistencygroup(
            ctxt,
            host=None)['id']
        volume_id = utils.create_volume(
            ctxt,
            consistencygroup_id=consistencygroup_id)['id']
        cgsnapshot_id = utils.create_cgsnapshot(
            ctxt,
            consistencygroup_id=consistencygroup_id)['id']
        snapshot_id = utils.create_snapshot(
            ctxt,
            volume_id,
            cgsnapshot_id=cgsnapshot_id,
            status='available')['id']

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": cgsnapshot_id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = _('Invalid ConsistencyGroup: No host to create consistency '
                'group')
        self.assertIn(msg, res_dict['badRequest']['message'])

        db.snapshot_destroy(ctxt.elevated(), snapshot_id)
        db.cgsnapshot_destroy(ctxt.elevated(), cgsnapshot_id)
        db.volume_destroy(ctxt.elevated(), volume_id)
        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    def test_create_consistencygroup_from_src_cgsnapshot_empty(self):
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        consistencygroup_id = utils.create_consistencygroup(
            ctxt)['id']
        volume_id = utils.create_volume(
            ctxt,
            consistencygroup_id=consistencygroup_id)['id']
        cgsnapshot_id = utils.create_cgsnapshot(
            ctxt,
            consistencygroup_id=consistencygroup_id)['id']

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": cgsnapshot_id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = _("Invalid ConsistencyGroup: Cgsnahost is empty. No "
                "consistency group will be created.")
        self.assertIn(msg, res_dict['badRequest']['message'])

        db.cgsnapshot_destroy(ctxt.elevated(), cgsnapshot_id)
        db.volume_destroy(ctxt.elevated(), volume_id)
        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)

    @mock.patch.object(volume_api.API, 'create',
                       side_effect=exception.CinderException(
                           'Create volume failed.'))
    def test_create_consistencygroup_from_src_create_volume_failed(
            self, mock_create):
        ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        consistencygroup_id = utils.create_consistencygroup(ctxt)['id']
        volume_id = utils.create_volume(
            ctxt,
            consistencygroup_id=consistencygroup_id)['id']
        cgsnapshot_id = utils.create_cgsnapshot(
            ctxt,
            consistencygroup_id=consistencygroup_id)['id']
        snapshot_id = utils.create_snapshot(
            ctxt,
            volume_id,
            cgsnapshot_id=cgsnapshot_id,
            status='available')['id']

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": cgsnapshot_id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        msg = _("Create volume failed.")
        self.assertEqual(msg, res_dict['badRequest']['message'])

        db.snapshot_destroy(ctxt.elevated(), snapshot_id)
        db.cgsnapshot_destroy(ctxt.elevated(), cgsnapshot_id)
        db.volume_destroy(ctxt.elevated(), volume_id)
        db.consistencygroup_destroy(ctxt.elevated(), consistencygroup_id)
