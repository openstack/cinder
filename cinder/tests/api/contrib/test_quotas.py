#
# Copyright 2013 OpenStack Foundation
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
Tests for cinder.api.contrib.quotas.py
"""

from lxml import etree
import webob.exc


from cinder.api.contrib import quotas
from cinder import context
from cinder import db
from cinder import test


def make_body(root=True, gigabytes=1000, snapshots=10,
              volumes=10, backups=10, backup_gigabytes=1000,
              tenant_id='foo'):
    resources = {'gigabytes': gigabytes,
                 'snapshots': snapshots,
                 'volumes': volumes,
                 'backups': backups,
                 'backup_gigabytes': backup_gigabytes}
    # need to consider preexisting volume types as well
    volume_types = db.volume_type_get_all(context.get_admin_context())
    for volume_type in volume_types:
        resources['gigabytes_' + volume_type] = -1
        resources['snapshots_' + volume_type] = -1
        resources['volumes_' + volume_type] = -1

    if tenant_id:
        resources['id'] = tenant_id
    if root:
        result = {'quota_set': resources}
    else:
        result = resources
    return result


class QuotaSetsControllerTest(test.TestCase):

    def setUp(self):
        super(QuotaSetsControllerTest, self).setUp()
        self.controller = quotas.QuotaSetsController()

        self.req = self.mox.CreateMockAnything()
        self.req.environ = {'cinder.context': context.get_admin_context()}
        self.req.environ['cinder.context'].is_admin = True

    def test_defaults(self):
        result = self.controller.defaults(self.req, 'foo')
        self.assertDictMatch(result, make_body())

    def test_show(self):
        result = self.controller.show(self.req, 'foo')
        self.assertDictMatch(result, make_body())

    def test_show_not_authorized(self):
        self.req.environ['cinder.context'].is_admin = False
        self.req.environ['cinder.context'].user_id = 'bad_user'
        self.req.environ['cinder.context'].project_id = 'bad_project'
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.show,
                          self.req, 'foo')

    def test_update(self):
        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5, tenant_id=None)
        result = self.controller.update(self.req, 'foo', body)
        self.assertDictMatch(result, body)

    def test_update_wrong_key(self):
        body = {'quota_set': {'bad': 'bad'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_invalid_key_value(self):
        body = {'quota_set': {'gigabytes': "should_be_int"}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_multi_value_with_bad_data(self):
        orig_quota = self.controller.show(self.req, 'foo')
        body = make_body(gigabytes=2000, snapshots=15, volumes="should_be_int",
                         backups=5, tenant_id=None)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)
        # Verify that quota values are not updated in db
        new_quota = self.controller.show(self.req, 'foo')
        self.assertDictMatch(orig_quota, new_quota)

    def test_update_bad_quota_limit(self):
        body = {'quota_set': {'gigabytes': -1000}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_no_admin(self):
        self.req.environ['cinder.context'].is_admin = False
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.update,
                          self.req, 'foo', make_body(tenant_id=None))

    def test_update_without_quota_set_field(self):
        body = {'fake_quota_set': {'gigabytes': 100}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_update_empty_body(self):
        body = {}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          self.req, 'foo', body)

    def test_delete(self):
        result_show = self.controller.show(self.req, 'foo')
        self.assertDictMatch(result_show, make_body())

        body = make_body(gigabytes=2000, snapshots=15,
                         volumes=5, backups=5,
                         backup_gigabytes=1000, tenant_id=None)
        result_update = self.controller.update(self.req, 'foo', body)
        self.assertDictMatch(result_update, body)

        self.controller.delete(self.req, 'foo')

        result_show_after = self.controller.show(self.req, 'foo')
        self.assertDictMatch(result_show, result_show_after)

    def test_delete_no_admin(self):
        self.req.environ['cinder.context'].is_admin = False
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          self.req, 'test')


class QuotaSerializerTest(test.TestCase):

    def setUp(self):
        super(QuotaSerializerTest, self).setUp()
        self.req = self.mox.CreateMockAnything()
        self.req.environ = {'cinder.context': context.get_admin_context()}

    def test_update_serializer(self):
        serializer = quotas.QuotaTemplate()
        quota_set = make_body(root=False)
        text = serializer.serialize({'quota_set': quota_set})
        tree = etree.fromstring(text)
        self.assertEqual(tree.tag, 'quota_set')
        self.assertEqual(tree.get('id'), quota_set['id'])
        body = make_body(root=False, tenant_id=None)
        for node in tree:
            self.assertIn(node.tag, body)
            self.assertEqual(str(body[node.tag]), node.text)
