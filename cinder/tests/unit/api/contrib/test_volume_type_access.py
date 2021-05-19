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
from http import HTTPStatus
from unittest import mock

import webob

from cinder.api.contrib import volume_type_access as type_access
from cinder.api.v3 import types
from cinder import context
from cinder import db
from cinder import exception
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


def generate_type(type_id, is_public):
    return {
        'id': type_id,
        'name': 'test',
        'deleted': False,
        'created_at': datetime.datetime(2012, 1, 1, 1, 1, 1, 1),
        'updated_at': None,
        'deleted_at': None,
        'is_public': bool(is_public)
    }


VOLUME_TYPES = {
    fake.VOLUME_TYPE_ID: generate_type(fake.VOLUME_TYPE_ID, True),
    fake.VOLUME_TYPE2_ID: generate_type(fake.VOLUME_TYPE2_ID, True),
    fake.VOLUME_TYPE3_ID: generate_type(fake.VOLUME_TYPE3_ID, False),
    fake.VOLUME_TYPE4_ID: generate_type(fake.VOLUME_TYPE4_ID, False)}

PROJ1_UUID = fake.PROJECT_ID
PROJ2_UUID = fake.PROJECT2_ID
PROJ3_UUID = fake.PROJECT3_ID

ACCESS_LIST = [{'volume_type_id': fake.VOLUME_TYPE3_ID,
                'project_id': PROJ2_UUID},
               {'volume_type_id': fake.VOLUME_TYPE3_ID,
                'project_id': PROJ3_UUID},
               {'volume_type_id': fake.VOLUME_TYPE4_ID,
                'project_id': PROJ3_UUID}]


def fake_volume_type_get(context, id, inactive=False, expected_fields=None):
    vol = VOLUME_TYPES[id]
    if expected_fields and 'projects' in expected_fields:
        vol['projects'] = [a['project_id']
                           for a in ACCESS_LIST if a['volume_type_id'] == id]
    return vol


def _has_type_access(type_id, project_id):
    for access in ACCESS_LIST:
        if access['volume_type_id'] == type_id and \
           access['project_id'] == project_id:
            return True
    return False


def fake_volume_type_get_all(context, inactive=False, filters=None,
                             marker=None, limit=None, sort_keys=None,
                             sort_dirs=None, offset=None, list_result=False):
    if filters is None or filters['is_public'] is None:
        if list_result:
            return list(VOLUME_TYPES.values())
        return VOLUME_TYPES
    res = {}
    for k, v in VOLUME_TYPES.items():
        if filters['is_public'] and _has_type_access(k, context.project_id):
            res.update({k: v})
            continue
        if v['is_public'] == filters['is_public']:
            res.update({k: v})
    if list_result:
        return list(res.values())
    return res


class FakeResponse(object):
    obj = {'volume_type': {'id': fake.VOLUME_TYPE_ID},
           'volume_types': [
               {'id': fake.VOLUME_TYPE_ID},
               {'id': fake.VOLUME_TYPE3_ID}]}

    def attach(self, **kwargs):
        pass


class FakeRequest(object):
    environ = {"cinder.context": context.get_admin_context()}

    def cached_resource_by_id(self, resource_id, name=None):
        return VOLUME_TYPES[resource_id]


class VolumeTypeAccessTest(test.TestCase):

    def setUp(self):
        super(VolumeTypeAccessTest, self).setUp()
        self.type_controller = types.VolumeTypesController()
        self.type_access_controller = type_access.VolumeTypeAccessController()
        self.type_action_controller = type_access.VolumeTypeActionController()
        self.req = FakeRequest()
        self.context = self.req.environ['cinder.context']
        self.mock_object(db, 'volume_type_get',
                         fake_volume_type_get)
        self.mock_object(db, 'volume_type_get_all',
                         fake_volume_type_get_all)

    def assertVolumeTypeListEqual(self, expected, observed):
        self.assertEqual(len(expected), len(observed))
        expected = sorted(expected, key=lambda item: item['id'])
        observed = sorted(observed, key=lambda item: item['id'])
        for d1, d2 in zip(expected, observed):
            self.assertEqual(d1['id'], d2['id'])

    def test_list_type_access_public(self):
        """Querying os-volume-type-access on public type should return 404."""
        req = fakes.HTTPRequest.blank('/v3/%s/types/os-volume-type-access' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True)
        self.assertRaises(exception.VolumeTypeAccessNotFound,
                          self.type_access_controller.index,
                          req, fake.VOLUME_TYPE2_ID)

    def test_list_type_access_private(self):
        expected = {'volume_type_access': [
            {'volume_type_id': fake.VOLUME_TYPE3_ID,
             'project_id': PROJ2_UUID},
            {'volume_type_id': fake.VOLUME_TYPE3_ID,
             'project_id': PROJ3_UUID}]}
        result = self.type_access_controller.index(self.req,
                                                   fake.VOLUME_TYPE3_ID)
        self.assertEqual(expected, result)

    def test_list_with_no_context(self):
        req = fakes.HTTPRequest.blank('/v3/flavors/%s/flavors' %
                                      fake.PROJECT_ID)

        def fake_authorize(context, target=None, action=None):
            raise exception.PolicyNotAuthorized(action='index')
        with mock.patch('cinder.context.RequestContext.authorize',
                        fake_authorize):
            self.assertRaises(exception.PolicyNotAuthorized,
                              self.type_access_controller.index,
                              req, fake.PROJECT_ID)

    def test_list_type_with_admin_default_proj1(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE_ID},
                                     {'id': fake.VOLUME_TYPE2_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID,
                                      use_admin_context=True)
        req.environ['cinder.context'].project_id = PROJ1_UUID
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_list_type_with_admin_default_proj2(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE_ID},
                                     {'id': fake.VOLUME_TYPE2_ID},
                                     {'id': fake.VOLUME_TYPE3_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % PROJ2_UUID,
                                      use_admin_context=True)
        req.environ['cinder.context'].project_id = PROJ2_UUID
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_list_type_with_admin_ispublic_true(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE_ID},
                                     {'id': fake.VOLUME_TYPE2_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types?is_public=true' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True)
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_list_type_with_admin_ispublic_false(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE3_ID},
                                     {'id': fake.VOLUME_TYPE4_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types?is_public=false' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True)
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_list_type_with_admin_ispublic_false_proj2(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE3_ID},
                                     {'id': fake.VOLUME_TYPE4_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types?is_public=false' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True)
        req.environ['cinder.context'].project_id = PROJ2_UUID
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_list_type_with_admin_ispublic_none(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE_ID},
                                     {'id': fake.VOLUME_TYPE2_ID},
                                     {'id': fake.VOLUME_TYPE3_ID},
                                     {'id': fake.VOLUME_TYPE4_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types?is_public=none' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True)
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_list_type_with_no_admin_default(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE_ID},
                                     {'id': fake.VOLUME_TYPE2_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types' % fake.PROJECT_ID,
                                      use_admin_context=False)
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_list_type_with_no_admin_ispublic_true(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE_ID},
                                     {'id': fake.VOLUME_TYPE2_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types?is_public=true' %
                                      fake.PROJECT_ID,
                                      use_admin_context=False)
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_list_type_with_no_admin_ispublic_false(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE_ID},
                                     {'id': fake.VOLUME_TYPE2_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types?is_public=false' %
                                      fake.PROJECT_ID,
                                      use_admin_context=False)
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_list_type_with_no_admin_ispublic_none(self):
        expected = {'volume_types': [{'id': fake.VOLUME_TYPE_ID},
                                     {'id': fake.VOLUME_TYPE2_ID}]}
        req = fakes.HTTPRequest.blank('/v3/%s/types?is_public=none' %
                                      fake.PROJECT_ID,
                                      use_admin_context=False)
        result = self.type_controller.index(req)
        self.assertVolumeTypeListEqual(expected['volume_types'],
                                       result['volume_types'])

    def test_show(self):
        resp = FakeResponse()
        self.type_action_controller.show(self.req, resp, fake.VOLUME_TYPE_ID)
        self.assertEqual({'id': fake.VOLUME_TYPE_ID,
                          'os-volume-type-access:is_public': True},
                         resp.obj['volume_type'])

    def test_detail(self):
        resp = FakeResponse()
        self.type_action_controller.detail(self.req, resp)
        self.assertEqual(
            [{'id': fake.VOLUME_TYPE_ID,
              'os-volume-type-access:is_public': True},
             {'id': fake.VOLUME_TYPE3_ID,
              'os-volume-type-access:is_public': False}],
            resp.obj['volume_types'])

    def test_create(self):
        resp = FakeResponse()
        self.type_action_controller.create(self.req, {}, resp)
        self.assertEqual({'id': fake.VOLUME_TYPE_ID,
                          'os-volume-type-access:is_public': True},
                         resp.obj['volume_type'])

    def test_add_project_access(self):
        def fake_add_volume_type_access(context, type_id, project_id):
            self.assertEqual(fake.VOLUME_TYPE4_ID, type_id, "type_id")
            self.assertEqual(PROJ2_UUID, project_id, "project_id")
        self.mock_object(db, 'volume_type_access_add',
                         fake_add_volume_type_access)
        body = {'addProjectAccess': {'project': PROJ2_UUID}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_TYPE3_ID),
            use_admin_context=True)
        result = self.type_action_controller._addProjectAccess(
            req, fake.VOLUME_TYPE4_ID, body=body)
        self.assertEqual(HTTPStatus.ACCEPTED, result.status_code)

    def test_add_project_access_with_no_admin_user(self):
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_TYPE3_ID),
            use_admin_context=False)
        body = {'addProjectAccess': {'project': PROJ2_UUID}}
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.type_action_controller._addProjectAccess,
                          req, fake.VOLUME_TYPE3_ID, body=body)

    def test_add_project_access_with_already_added_access(self):
        def fake_add_volume_type_access(context, type_id, project_id):
            raise exception.VolumeTypeAccessExists(volume_type_id=type_id,
                                                   project_id=project_id)
        self.mock_object(db, 'volume_type_access_add',
                         fake_add_volume_type_access)
        body = {'addProjectAccess': {'project': PROJ2_UUID}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_TYPE3_ID), use_admin_context=True)
        self.assertRaises(webob.exc.HTTPConflict,
                          self.type_action_controller._addProjectAccess,
                          req, fake.VOLUME_TYPE3_ID, body=body)

    def test_remove_project_access_with_bad_access(self):
        def fake_remove_volume_type_access(context, type_id, project_id):
            raise exception.VolumeTypeAccessNotFound(volume_type_id=type_id,
                                                     project_id=project_id)
        self.mock_object(db, 'volume_type_access_remove',
                         fake_remove_volume_type_access)
        body = {'removeProjectAccess': {'project': PROJ2_UUID}}
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_TYPE3_ID), use_admin_context=True)
        self.assertRaises(exception.VolumeTypeAccessNotFound,
                          self.type_action_controller._removeProjectAccess,
                          req, fake.VOLUME_TYPE4_ID, body=body)

    def test_remove_project_access_with_no_admin_user(self):
        req = fakes.HTTPRequest.blank('/v3/%s/types/%s/action' % (
            fake.PROJECT_ID, fake.VOLUME_TYPE3_ID), use_admin_context=False)
        body = {'removeProjectAccess': {'project': PROJ2_UUID}}
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.type_action_controller._removeProjectAccess,
                          req, fake.VOLUME_TYPE3_ID, body=body)
