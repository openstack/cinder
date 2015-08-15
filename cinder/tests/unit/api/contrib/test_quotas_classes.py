# Copyright 2013 Huawei Technologies Co., Ltd
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
Tests for cinder.api.contrib.quota_classes.py
"""


import mock

from lxml import etree
import webob.exc


from cinder.api.contrib import quota_classes
from cinder import context
from cinder import quota
from cinder import test
from cinder.volume import volume_types


QUOTAS = quota.QUOTAS


def make_body(root=True, gigabytes=1000, snapshots=10,
              volumes=10, backups=10,
              backup_gigabytes=1000, per_volume_gigabytes=-1,
              volume_types_faked=None,
              tenant_id='foo'):
    resources = {'gigabytes': gigabytes,
                 'snapshots': snapshots,
                 'volumes': volumes,
                 'backups': backups,
                 'per_volume_gigabytes': per_volume_gigabytes,
                 'backup_gigabytes': backup_gigabytes}
    if not volume_types_faked:
        volume_types_faked = {'fake_type': None}
    for volume_type in volume_types_faked:
        resources['gigabytes_' + volume_type] = -1
        resources['snapshots_' + volume_type] = -1
        resources['volumes_' + volume_type] = -1

    if tenant_id:
        resources['id'] = tenant_id
    if root:
        result = {'quota_class_set': resources}
    else:
        result = resources
    return result


def make_response_body(root=True, ctxt=None, quota_class='foo',
                       request_body=None, tenant_id='foo'):
    resources = {}
    if not ctxt:
        ctxt = context.get_admin_context()
    resources.update(QUOTAS.get_class_quotas(ctxt, quota_class))
    if not request_body and not request_body['quota_class_set']:
        resources.update(request_body['quota_class_set'])

    if tenant_id:
        resources['id'] = tenant_id
    if root:
        result = {'quota_class_set': resources}
    else:
        result = resources
    return result


class QuotaClassSetsControllerTest(test.TestCase):

    def setUp(self):
        super(QuotaClassSetsControllerTest, self).setUp()
        self.controller = quota_classes.QuotaClassSetsController()

        self.ctxt = context.get_admin_context()
        self.req = self.mox.CreateMockAnything()
        self.req.environ = {'cinder.context': self.ctxt}
        self.req.environ['cinder.context'].is_admin = True

    def test_show(self):
        volume_types.create(self.ctxt, 'fake_type')
        result = self.controller.show(self.req, 'foo')
        self.assertDictMatch(result, make_body())

    def test_show_not_authorized(self):
        self.req.environ['cinder.context'].is_admin = False
        self.req.environ['cinder.context'].user_id = 'bad_user'
        self.req.environ['cinder.context'].project_id = 'bad_project'
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          self.req, 'foo')

    def test_update(self):
        volume_types.create(self.ctxt, 'fake_type')
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, tenant_id=None)
        result = self.controller.update(self.req, 'foo', body)
        self.assertDictMatch(result, body)

    @mock.patch('cinder.api.openstack.wsgi.Controller.validate_string_length')
    @mock.patch('cinder.api.openstack.wsgi.Controller.validate_integer')
    def test_update_limit(self, mock_validate_integer, mock_validate):
        mock_validate_integer.return_value = 5
        volume_types.create(self.ctxt, 'fake_type')
        body = make_body(volumes=5)
        result = self.controller.update(self.req, 'foo', body)
        self.assertEqual(5, result['quota_class_set']['volumes'])
        self.assertTrue(mock_validate.called)
        self.assertTrue(mock_validate_integer.called)

    def test_update_wrong_key(self):
        volume_types.create(self.ctxt, 'fake_type')
        body = {'quota_class_set': {'bad': 'bad'}}
        result = self.controller.update(self.req, 'foo', body)
        self.assertDictMatch(result, make_body(tenant_id=None))

    def test_update_invalid_key_value(self):
        body = {'quota_class_set': {'gigabytes': "should_be_int"}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_bad_quota_limit(self):
        body = {'quota_class_set': {'gigabytes': -1000}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_no_admin(self):
        self.req.environ['cinder.context'].is_admin = False
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          self.req, 'foo', make_body(tenant_id=None))

    def test_update_with_more_volume_types(self):
        volume_types.create(self.ctxt, 'fake_type_1')
        volume_types.create(self.ctxt, 'fake_type_2')
        body = {'quota_class_set': {'gigabytes_fake_type_1': 1111,
                                    'volumes_fake_type_2': 2222}}
        result = self.controller.update(self.req, 'foo', body)
        self.assertDictMatch(result, make_response_body(ctxt=self.ctxt,
                                                        quota_class='foo',
                                                        request_body=body,
                                                        tenant_id=None))


class QuotaClassesSerializerTest(test.TestCase):

    def setUp(self):
        super(QuotaClassesSerializerTest, self).setUp()
        self.req = self.mox.CreateMockAnything()
        self.req.environ = {'cinder.context': context.get_admin_context()}

    def test_update_serializer(self):
        serializer = quota_classes.QuotaClassTemplate()
        quota_class_set = make_body(root=False)
        text = serializer.serialize({'quota_class_set': quota_class_set})
        tree = etree.fromstring(text)
        self.assertEqual('quota_class_set', tree.tag)
        self.assertEqual(tree.get('id'), quota_class_set['id'])
        body = make_body(root=False, tenant_id=None)
        for node in tree:
            self.assertIn(node.tag, body)
            self.assertEqual(str(body[node.tag]), node.text)
