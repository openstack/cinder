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
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import stubs
from cinder.tests.unit import utils
from cinder.volume import api as volume_api


class ConsistencyGroupsAPITestCase(test.TestCase):
    """Test Case for consistency groups API."""

    def setUp(self):
        super(ConsistencyGroupsAPITestCase, self).setUp()
        self.cg_api = cinder.consistencygroup.API()
        self.ctxt = context.RequestContext('fake', 'fake', auth_token=True,
                                           is_admin=True)

    def _create_consistencygroup(
            self,
            ctxt=None,
            name='test_consistencygroup',
            description='this is a test consistency group',
            volume_type_id='123456',
            availability_zone='az1',
            host='fakehost',
            status='creating'):
        """Create a consistency group object."""
        ctxt = ctxt or self.ctxt
        consistencygroup = objects.ConsistencyGroup(ctxt)
        consistencygroup.user_id = 'fake'
        consistencygroup.project_id = 'fake'
        consistencygroup.availability_zone = availability_zone
        consistencygroup.name = name
        consistencygroup.description = description
        consistencygroup.volume_type_id = volume_type_id
        consistencygroup.host = host
        consistencygroup.status = status
        consistencygroup.create()
        return consistencygroup

    def test_show_consistencygroup(self):
        consistencygroup = self._create_consistencygroup()
        req = webob.Request.blank('/v2/fake/consistencygroups/%s' %
                                  consistencygroup.id)
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

        consistencygroup.destroy()

    def test_show_consistencygroup_xml_content_type(self):
        consistencygroup = self._create_consistencygroup()
        req = webob.Request.blank('/v2/fake/consistencygroups/%s' %
                                  consistencygroup.id)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(200, res.status_int)
        dom = minidom.parseString(res.body)
        consistencygroups = dom.getElementsByTagName('consistencygroup')
        name = consistencygroups.item(0).getAttribute('name')
        self.assertEqual("test_consistencygroup", name.strip())
        consistencygroup.destroy()

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
        consistencygroup1 = self._create_consistencygroup()
        consistencygroup2 = self._create_consistencygroup()
        consistencygroup3 = self._create_consistencygroup()

        req = webob.Request.blank('/v2/fake/consistencygroups')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(200, res.status_int)
        self.assertEqual(consistencygroup1.id,
                         res_dict['consistencygroups'][0]['id'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][0]['name'])
        self.assertEqual(consistencygroup2.id,
                         res_dict['consistencygroups'][1]['id'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][1]['name'])
        self.assertEqual(consistencygroup3.id,
                         res_dict['consistencygroups'][2]['id'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][2]['name'])

        consistencygroup1.destroy()
        consistencygroup2.destroy()
        consistencygroup3.destroy()

    def test_list_consistencygroups_xml(self):
        consistencygroup1 = self._create_consistencygroup()
        consistencygroup2 = self._create_consistencygroup()
        consistencygroup3 = self._create_consistencygroup()

        req = webob.Request.blank('/v2/fake/consistencygroups')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(200, res.status_int)
        dom = minidom.parseString(res.body)
        consistencygroup_list = dom.getElementsByTagName('consistencygroup')

        self.assertEqual(consistencygroup1.id,
                         consistencygroup_list.item(0).getAttribute('id'))
        self.assertEqual(consistencygroup2.id,
                         consistencygroup_list.item(1).getAttribute('id'))
        self.assertEqual(consistencygroup3.id,
                         consistencygroup_list.item(2).getAttribute('id'))

        consistencygroup3.destroy()
        consistencygroup2.destroy()
        consistencygroup1.destroy()

    def test_list_consistencygroups_detail_json(self):
        consistencygroup1 = self._create_consistencygroup()
        consistencygroup2 = self._create_consistencygroup()
        consistencygroup3 = self._create_consistencygroup()

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
        self.assertEqual(consistencygroup1.id,
                         res_dict['consistencygroups'][0]['id'])
        self.assertEqual('creating',
                         res_dict['consistencygroups'][0]['status'])

        self.assertEqual('az1',
                         res_dict['consistencygroups'][1]['availability_zone'])
        self.assertEqual('this is a test consistency group',
                         res_dict['consistencygroups'][1]['description'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][1]['name'])
        self.assertEqual(consistencygroup2.id,
                         res_dict['consistencygroups'][1]['id'])
        self.assertEqual('creating',
                         res_dict['consistencygroups'][1]['status'])

        self.assertEqual('az1',
                         res_dict['consistencygroups'][2]['availability_zone'])
        self.assertEqual('this is a test consistency group',
                         res_dict['consistencygroups'][2]['description'])
        self.assertEqual('test_consistencygroup',
                         res_dict['consistencygroups'][2]['name'])
        self.assertEqual(consistencygroup3.id,
                         res_dict['consistencygroups'][2]['id'])
        self.assertEqual('creating',
                         res_dict['consistencygroups'][2]['status'])

        consistencygroup1.destroy()
        consistencygroup2.destroy()
        consistencygroup3.destroy()

    def test_list_consistencygroups_detail_xml(self):
        consistencygroup1 = self._create_consistencygroup()
        consistencygroup2 = self._create_consistencygroup()
        consistencygroup3 = self._create_consistencygroup()

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
            consistencygroup1.id,
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
            consistencygroup2.id,
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
            consistencygroup3.id,
            consistencygroup_detail.item(2).getAttribute('id'))
        self.assertEqual(
            'creating',
            consistencygroup_detail.item(2).getAttribute('status'))

        consistencygroup3.destroy()
        consistencygroup2.destroy()
        consistencygroup1.destroy()

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_create_consistencygroup_json(self, mock_validate):
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
        self.assertTrue(mock_validate.called)

        group_id = res_dict['consistencygroup']['id']
        cg = objects.ConsistencyGroup.get_by_id(context.get_admin_context(),
                                                group_id)
        cg.destroy()

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
        self.assertEqual("Missing required element 'consistencygroup' in "
                         "request body.",
                         res_dict['badRequest']['message'])

    def test_delete_consistencygroup_available(self):
        consistencygroup = self._create_consistencygroup(status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup.id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"force": True}}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        consistencygroup = objects.ConsistencyGroup.get_by_id(
            self.ctxt, consistencygroup.id)
        self.assertEqual(202, res.status_int)
        self.assertEqual('deleting', consistencygroup.status)

        consistencygroup.destroy()

    def test_delete_consistencygroup_with_consistencygroup_NotFound(self):
        req = webob.Request.blank('/v2/fake/consistencygroups/9999/delete')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(None)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(404, res.status_int)
        self.assertEqual(404, res_dict['itemNotFound']['code'])
        self.assertEqual('ConsistencyGroup 9999 could not be found.',
                         res_dict['itemNotFound']['message'])

    def test_delete_consistencygroup_with_Invalidconsistencygroup(self):
        consistencygroup = self._create_consistencygroup(status='invalid')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup.id)
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

        consistencygroup.destroy()

    def test_delete_consistencygroup_no_host(self):
        consistencygroup = self._create_consistencygroup(
            host=None,
            status='error')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup.id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"force": True}}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(202, res.status_int)

        cg = objects.ConsistencyGroup.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            consistencygroup.id)
        self.assertEqual('deleted', cg.status)
        self.assertIsNone(cg.host)

    def test_create_delete_consistencygroup_update_quota(self):
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

        cg = self.cg_api.create(self.ctxt, name, description,
                                fake_type['name'])
        self.cg_api.update_quota.assert_called_once_with(
            self.ctxt, cg, 1)
        self.assertEqual('creating', cg.status)
        self.assertIsNone(cg.host)
        self.cg_api.update_quota.reset_mock()
        cg.status = 'error'
        self.cg_api.delete(self.ctxt, cg)
        self.cg_api.update_quota.assert_called_once_with(
            self.ctxt, cg, -1, self.ctxt.project_id)
        cg = objects.ConsistencyGroup.get_by_id(
            context.get_admin_context(read_deleted='yes'),
            cg.id)
        self.assertEqual('deleted', cg.status)

    def test_delete_consistencygroup_with_invalid_body(self):
        consistencygroup = self._create_consistencygroup(status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup.id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        body = {"invalid_request_element": {"force": False}}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(400, res.status_int)

    def test_delete_consistencygroup_with_invalid_force_value_in_body(self):
        consistencygroup = self._create_consistencygroup(status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup.id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"force": "abcd"}}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(400, res.status_int)

    def test_delete_consistencygroup_with_empty_force_value_in_body(self):
        consistencygroup = self._create_consistencygroup(status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/delete' %
                                  consistencygroup.id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        body = {"consistencygroup": {"force": ""}}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(400, res.status_int)

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

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_update_consistencygroup_success(self, mock_validate):
        volume_type_id = '123456'
        consistencygroup = self._create_consistencygroup(status='available',
                                                         host='test_host')

        remove_volume_id = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id,
            consistencygroup_id=consistencygroup.id)['id']
        remove_volume_id2 = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id,
            consistencygroup_id=consistencygroup.id)['id']

        self.assertEqual('available', consistencygroup.status)

        cg_volumes = db.volume_get_all_by_group(self.ctxt.elevated(),
                                                consistencygroup.id)
        cg_vol_ids = [cg_vol['id'] for cg_vol in cg_volumes]
        self.assertIn(remove_volume_id, cg_vol_ids)
        self.assertIn(remove_volume_id2, cg_vol_ids)

        add_volume_id = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id)['id']
        add_volume_id2 = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id)['id']
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup.id)
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

        consistencygroup = objects.ConsistencyGroup.get_by_id(
            self.ctxt, consistencygroup.id)
        self.assertEqual(202, res.status_int)
        self.assertTrue(mock_validate.called)
        self.assertEqual('updating', consistencygroup.status)

        consistencygroup.destroy()

    def test_update_consistencygroup_add_volume_not_found(self):
        consistencygroup = self._create_consistencygroup(ctxt=self.ctxt,
                                                         status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup.id)
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
               {'group_id': consistencygroup.id})
        self.assertEqual(msg, res_dict['badRequest']['message'])

        consistencygroup.destroy()

    def test_update_consistencygroup_remove_volume_not_found(self):
        consistencygroup = self._create_consistencygroup(ctxt=self.ctxt,
                                                         status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup.id)
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
               {'group_id': consistencygroup.id})
        self.assertEqual(msg, res_dict['badRequest']['message'])

        consistencygroup.destroy()

    def test_update_consistencygroup_empty_parameters(self):
        consistencygroup = self._create_consistencygroup(ctxt=self.ctxt,
                                                         status='available')
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup.id)
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

        consistencygroup.destroy()

    def test_update_consistencygroup_add_volume_invalid_state(self):
        volume_type_id = '123456'
        consistencygroup = self._create_consistencygroup(ctxt=self.ctxt,
                                                         status='available')
        add_volume_id = utils.create_volume(
            self.ctxt,
            volume_type_id=volume_type_id,
            status='wrong_status')['id']
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup.id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        add_volumes = add_volume_id
        body = {"consistencygroup": {"name": "cg1",
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
                'group_id': consistencygroup.id,
                'status': 'wrong_status'})
        self.assertEqual(msg, res_dict['badRequest']['message'])

        consistencygroup.destroy()

    def test_update_consistencygroup_add_volume_invalid_volume_type(self):
        consistencygroup = self._create_consistencygroup(ctxt=self.ctxt,
                                                         status='available')
        wrong_type = 'wrong-volume-type-id'
        add_volume_id = utils.create_volume(
            self.ctxt,
            volume_type_id=wrong_type)['id']
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup.id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        add_volumes = add_volume_id
        body = {"consistencygroup": {"name": "cg1",
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
                'group_id': consistencygroup.id,
                'volume_type': wrong_type})
        self.assertEqual(msg, res_dict['badRequest']['message'])

        consistencygroup.destroy()

    def test_update_consistencygroup_add_volume_already_in_cg(self):
        consistencygroup = self._create_consistencygroup(ctxt=self.ctxt,
                                                         status='available')
        add_volume_id = utils.create_volume(
            self.ctxt,
            consistencygroup_id='some_other_cg')['id']
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup.id)
        req.method = 'PUT'
        req.headers['Content-Type'] = 'application/json'
        add_volumes = add_volume_id
        body = {"consistencygroup": {"name": "cg1",
                                     "description": "",
                                     "add_volumes": add_volumes,
                                     "remove_volumes": None, }}
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertIsNotNone(res_dict['badRequest']['message'])

        consistencygroup.destroy()

    def test_update_consistencygroup_invalid_state(self):
        wrong_status = 'wrong_status'
        consistencygroup = self._create_consistencygroup(status=wrong_status,
                                                         ctxt=self.ctxt)
        req = webob.Request.blank('/v2/fake/consistencygroups/%s/update' %
                                  consistencygroup.id)
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

        consistencygroup.destroy()

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_create_consistencygroup_from_src(self, mock_validate):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)

        consistencygroup = utils.create_consistencygroup(self.ctxt)
        volume_id = utils.create_volume(
            self.ctxt,
            consistencygroup_id=consistencygroup.id)['id']
        cgsnapshot = utils.create_cgsnapshot(
            self.ctxt, consistencygroup_id=consistencygroup.id)
        snapshot = utils.create_snapshot(
            self.ctxt,
            volume_id,
            cgsnapshot_id=cgsnapshot.id,
            status='available')

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": cgsnapshot.id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(202, res.status_int)
        self.assertIn('id', res_dict['consistencygroup'])
        self.assertEqual(test_cg_name, res_dict['consistencygroup']['name'])
        self.assertTrue(mock_validate.called)

        cg_ref = objects.ConsistencyGroup.get_by_id(
            self.ctxt.elevated(), res_dict['consistencygroup']['id'])

        cg_ref.destroy()
        snapshot.destroy()
        db.volume_destroy(self.ctxt.elevated(), volume_id)
        consistencygroup.destroy()
        cgsnapshot.destroy()

    def test_create_consistencygroup_from_src_cg(self):
        self.mock_object(volume_api.API, "create", stubs.stub_volume_create)

        source_cg = utils.create_consistencygroup(self.ctxt)
        volume_id = utils.create_volume(
            self.ctxt,
            consistencygroup_id=source_cg.id)['id']

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "source_cgid": source_cg.id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(202, res.status_int)
        self.assertIn('id', res_dict['consistencygroup'])
        self.assertEqual(test_cg_name, res_dict['consistencygroup']['name'])

        cg = objects.ConsistencyGroup.get_by_id(
            self.ctxt, res_dict['consistencygroup']['id'])
        cg.destroy
        db.volume_destroy(self.ctxt.elevated(), volume_id)
        source_cg.destroy()

    def test_create_consistencygroup_from_src_both_snap_cg(self):
        self.stubs.Set(volume_api.API, "create", stubs.stub_volume_create)

        consistencygroup = utils.create_consistencygroup(self.ctxt)
        volume_id = utils.create_volume(
            self.ctxt,
            consistencygroup_id=consistencygroup.id)['id']
        cgsnapshot_id = utils.create_cgsnapshot(
            self.ctxt,
            consistencygroup_id=consistencygroup.id)['id']
        snapshot = utils.create_snapshot(
            self.ctxt,
            volume_id,
            cgsnapshot_id=cgsnapshot_id,
            status='available')

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": cgsnapshot_id,
                                              "source_cgid":
                                                  consistencygroup.id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertIsNotNone(res_dict['badRequest']['message'])

        snapshot.destroy()
        db.cgsnapshot_destroy(self.ctxt.elevated(), cgsnapshot_id)
        db.volume_destroy(self.ctxt.elevated(), volume_id)
        consistencygroup.destroy()

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
        # Missing 'consistencygroup-from-src' in the body.
        self.assertIsNotNone(res_dict['badRequest']['message'])

    def test_create_consistencygroup_from_src_no_source_id(self):
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
        self.assertIsNotNone(res_dict['badRequest']['message'])

    def test_create_consistencygroup_from_src_no_host(self):
        consistencygroup = utils.create_consistencygroup(self.ctxt, host=None)
        volume_id = utils.create_volume(
            self.ctxt,
            consistencygroup_id=consistencygroup.id)['id']
        cgsnapshot = utils.create_cgsnapshot(
            self.ctxt, consistencygroup_id=consistencygroup.id)
        snapshot = utils.create_snapshot(
            self.ctxt,
            volume_id,
            cgsnapshot_id=cgsnapshot.id,
            status='available')

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": cgsnapshot.id}}
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

        snapshot.destroy()
        db.volume_destroy(self.ctxt.elevated(), volume_id)
        consistencygroup.destroy()
        cgsnapshot.destroy()

    def test_create_consistencygroup_from_src_cgsnapshot_empty(self):
        consistencygroup = utils.create_consistencygroup(self.ctxt)
        volume_id = utils.create_volume(
            self.ctxt,
            consistencygroup_id=consistencygroup.id)['id']
        cgsnapshot = utils.create_cgsnapshot(
            self.ctxt,
            consistencygroup_id=consistencygroup.id)

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": cgsnapshot.id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertIsNotNone(res_dict['badRequest']['message'])

        db.volume_destroy(self.ctxt.elevated(), volume_id)
        consistencygroup.destroy()
        cgsnapshot.destroy()

    def test_create_consistencygroup_from_src_source_cg_empty(self):
        source_cg = utils.create_consistencygroup(self.ctxt)

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "source_cgid": source_cg.id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertIsNotNone(res_dict['badRequest']['message'])

        source_cg.destroy()

    def test_create_consistencygroup_from_src_cgsnapshot_notfound(self):
        consistencygroup = utils.create_consistencygroup(self.ctxt)
        volume_id = utils.create_volume(
            self.ctxt,
            consistencygroup_id=consistencygroup.id)['id']

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": "fake_cgsnap"}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(404, res.status_int)
        self.assertEqual(404, res_dict['itemNotFound']['code'])
        self.assertIsNotNone(res_dict['itemNotFound']['message'])

        db.volume_destroy(self.ctxt.elevated(), volume_id)
        consistencygroup.destroy()

    def test_create_consistencygroup_from_src_source_cg_notfound(self):
        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "source_cgid": "fake_source_cg"}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(404, res.status_int)
        self.assertEqual(404, res_dict['itemNotFound']['code'])
        self.assertIsNotNone(res_dict['itemNotFound']['message'])

    @mock.patch.object(volume_api.API, 'create',
                       side_effect=exception.CinderException(
                           'Create volume failed.'))
    def test_create_consistencygroup_from_src_cgsnapshot_create_volume_failed(
            self, mock_create):
        consistencygroup = utils.create_consistencygroup(self.ctxt)
        volume_id = utils.create_volume(
            self.ctxt,
            consistencygroup_id=consistencygroup.id)['id']
        cgsnapshot = utils.create_cgsnapshot(
            self.ctxt, consistencygroup_id=consistencygroup.id)
        snapshot = utils.create_snapshot(
            self.ctxt,
            volume_id,
            cgsnapshot_id=cgsnapshot.id,
            status='available')

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "cgsnapshot_id": cgsnapshot.id}}
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

        snapshot.destroy()
        db.volume_destroy(self.ctxt.elevated(), volume_id)
        consistencygroup.destroy()
        cgsnapshot.destroy()

    @mock.patch.object(volume_api.API, 'create',
                       side_effect=exception.CinderException(
                           'Create volume failed.'))
    def test_create_consistencygroup_from_src_cg_create_volume_failed(
            self, mock_create):
        source_cg = utils.create_consistencygroup(self.ctxt)
        volume_id = utils.create_volume(
            self.ctxt,
            consistencygroup_id=source_cg.id)['id']

        test_cg_name = 'test cg'
        body = {"consistencygroup-from-src": {"name": test_cg_name,
                                              "description":
                                              "Consistency Group 1",
                                              "source_cgid": source_cg.id}}
        req = webob.Request.blank('/v2/fake/consistencygroups/create_from_src')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertIsNotNone(res_dict['badRequest']['message'])

        db.volume_destroy(self.ctxt.elevated(), volume_id)
        source_cg.destroy()
