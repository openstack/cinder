# Copyright 2012 OpenStack Foundation
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
import mock
from oslo_serialization import jsonutils
import webob

from cinder.api.contrib import extended_snapshot_attributes
from cinder import context
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume


UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'


def _get_default_snapshot_param():
    return {'id': UUID1,
            'volume_id': 12,
            'status': 'available',
            'volume_size': 100,
            'created_at': None,
            'display_name': 'Default name',
            'display_description': 'Default description',
            'project_id': 'fake',
            'progress': '0%',
            'expected_attrs': ['metadata']}


def fake_snapshot_get(self, context, snapshot_id):
    param = _get_default_snapshot_param()
    return param


def fake_snapshot_get_all(self, context, search_opts=None):
    param = _get_default_snapshot_param()
    return [param]


class ExtendedSnapshotAttributesTest(test.TestCase):
    content_type = 'application/json'
    prefix = 'os-extended-snapshot-attributes:'

    def setUp(self):
        super(ExtendedSnapshotAttributesTest, self).setUp()

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app())
        return res

    def _get_snapshot(self, body):
        return jsonutils.loads(body).get('snapshot')

    def _get_snapshots(self, body):
        return jsonutils.loads(body).get('snapshots')

    def assertSnapshotAttributes(self, snapshot, project_id, progress):
        self.assertEqual(project_id,
                         snapshot.get('%sproject_id' % self.prefix))
        self.assertEqual(progress, snapshot.get('%sprogress' % self.prefix))

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_show(self, snapshot_get_by_id, volume_get_by_id,
                  snapshot_metadata_get):
        ctx = context.RequestContext('fake', 'fake', auth_token=True)
        snapshot = _get_default_snapshot_param()
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj

        url = '/v2/fake/snapshots/%s' % UUID1
        res = self._make_request(url)

        self.assertEqual(200, res.status_int)
        self.assertSnapshotAttributes(self._get_snapshot(res.body),
                                      project_id='fake',
                                      progress='0%')

    def test_detail(self):
        url = '/v2/fake/snapshots/detail'
        res = self._make_request(url)

        self.assertEqual(200, res.status_int)
        for snapshot in self._get_snapshots(res.body):
            self.assertSnapshotAttributes(snapshot,
                                          project_id='fake',
                                          progress='0%')


class ExtendedSnapshotAttributesXmlTest(ExtendedSnapshotAttributesTest):
    content_type = 'application/xml'
    ext = extended_snapshot_attributes
    prefix = '{%s}' % ext.Extended_snapshot_attributes.namespace

    def _get_snapshot(self, body):
        return etree.XML(body)

    def _get_snapshots(self, body):
        return etree.XML(body).getchildren()
