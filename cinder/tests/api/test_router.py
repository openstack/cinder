# Copyright 2011 Denali Systems, Inc.
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

from oslo_log import log as logging

from cinder.api.openstack import wsgi
from cinder.api.v1 import router
from cinder.api.v1 import snapshots
from cinder.api.v1 import volumes
from cinder.api import versions
from cinder import test
from cinder.tests.api import fakes


LOG = logging.getLogger(__name__)


class FakeController(object):
    def __init__(self, ext_mgr=None):
        self.ext_mgr = ext_mgr

    def index(self, req):
        obj_type = req.path.split("/")[3]
        return {obj_type: []}

    def detail(self, req):
        obj_type = req.path.split("/")[3]
        return {obj_type: []}


def create_resource(ext_mgr):
    return wsgi.Resource(FakeController(ext_mgr))


class VolumeRouterTestCase(test.TestCase):
    def setUp(self):
        super(VolumeRouterTestCase, self).setUp()
        # NOTE(vish): versions is just returning text so, no need to stub.
        self.stubs.Set(snapshots, 'create_resource', create_resource)
        self.stubs.Set(volumes, 'create_resource', create_resource)
        self.app = router.APIRouter()

    def test_versions(self):
        req = fakes.HTTPRequest.blank('')
        req.method = 'GET'
        req.content_type = 'application/json'
        response = req.get_response(self.app)
        self.assertEqual(302, response.status_int)
        req = fakes.HTTPRequest.blank('/')
        req.method = 'GET'
        req.content_type = 'application/json'
        response = req.get_response(self.app)
        self.assertEqual(200, response.status_int)

    def test_versions_action_args_index(self):
        request_environment = {'PATH_INFO': '/'}
        resource = versions.Versions()
        result = resource.get_action_args(request_environment)
        self.assertEqual(result['action'], 'index')

    def test_versions_action_args_multi(self):
        request_environment = {'PATH_INFO': '/fake/path'}
        resource = versions.Versions()
        result = resource.get_action_args(request_environment)
        self.assertEqual(result['action'], 'multi')

    def test_versions_get_most_recent_update(self):
        res = versions.AtomSerializer()
        fake_date_updated = [
            {"updated": '2012-01-04T11:33:21Z'},
            {"updated": '2012-11-21T11:33:21Z'}
        ]
        result = res._get_most_recent_update(fake_date_updated)
        self.assertEqual('2012-11-21T11:33:21Z', result)

    def test_versions_create_version_entry(self):
        res = versions.AtomSerializer()
        vers = {
            "id": "v2.0",
            "status": "CURRENT",
            "updated": "2012-11-21T11:33:21Z",
            "links": [
                {
                    "rel": "describedby",
                    "type": "application/pdf",
                    "href": "http://jorgew.github.com/block-storage-api/"
                            "content/os-block-storage-1.0.pdf",
                },
            ],
        }
        fake_result = {
            'id': 'http://jorgew.github.com/block-storage-api/'
                  'content/os-block-storage-1.0.pdf',
            'title': 'Version v2.0',
            'updated': '2012-11-21T11:33:21Z',
            'link': {
                'href': 'http://jorgew.github.com/block-storage-api/'
                        'content/os-block-storage-1.0.pdf',
                'type': 'application/pdf',
                'rel': 'describedby'
            },
            'content': 'Version v2.0 CURRENT (2012-11-21T11:33:21Z)'
        }
        result_function = res._create_version_entry(vers)
        result = {}
        for subElement in result_function:
            if subElement.text:
                result[subElement.tag] = subElement.text
            else:
                result[subElement.tag] = subElement.attrib
        self.assertEqual(result, fake_result)

    def test_versions_create_feed(self):
        res = versions.AtomSerializer()
        vers = [
            {
                "id": "v2.0",
                "status": "CURRENT",
                "updated": "2012-11-21T11:33:21Z",
                "links": [
                    {
                        "rel": "describedby",
                        "type": "application/pdf",
                        "href": "http://jorgew.github.com/block-storage-api/"
                                "content/os-block-storage-1.0.pdf",
                    },
                ],
            },
            {
                "id": "v1.0",
                "status": "CURRENT",
                "updated": "2012-01-04T11:33:21Z",
                "links": [
                    {
                        "rel": "describedby",
                        "type": "application/vnd.sun.wadl+xml",
                        "href": "http://docs.rackspacecloud.com/"
                                "servers/api/v1.1/application.wadl",
                    },
                ],
            }
        ]
        result = res._create_feed(vers, "fake_feed_title",
                                  "http://jorgew.github.com/block-storage-api/"
                                  "content/os-block-storage-1.0.pdf")
        fake_data = {
            'id': 'http://jorgew.github.com/block-storage-api/'
                  'content/os-block-storage-1.0.pdf',
            'title': 'fake_feed_title',
            'updated': '2012-11-21T11:33:21Z',
        }
        data = {}
        for subElement in result:
            if subElement.text:
                data[subElement.tag] = subElement.text
        self.assertEqual(data, fake_data)

    def test_versions_multi(self):
        req = fakes.HTTPRequest.blank('/')
        req.method = 'GET'
        req.content_type = 'application/json'
        resource = versions.Versions()
        result = resource.dispatch(resource.multi, req, {})
        ids = [v['id'] for v in result['choices']]
        self.assertEqual(set(ids), set(['v1.0', 'v2.0']))

    def test_versions_multi_disable_v1(self):
        self.flags(enable_v1_api=False)
        req = fakes.HTTPRequest.blank('/')
        req.method = 'GET'
        req.content_type = 'application/json'
        resource = versions.Versions()
        result = resource.dispatch(resource.multi, req, {})
        ids = [v['id'] for v in result['choices']]
        self.assertEqual(set(ids), set(['v2.0']))

    def test_versions_multi_disable_v2(self):
        self.flags(enable_v2_api=False)
        req = fakes.HTTPRequest.blank('/')
        req.method = 'GET'
        req.content_type = 'application/json'
        resource = versions.Versions()
        result = resource.dispatch(resource.multi, req, {})
        ids = [v['id'] for v in result['choices']]
        self.assertEqual(set(ids), set(['v1.0']))

    def test_versions_index(self):
        req = fakes.HTTPRequest.blank('/')
        req.method = 'GET'
        req.content_type = 'application/json'
        resource = versions.Versions()
        result = resource.dispatch(resource.index, req, {})
        ids = [v['id'] for v in result['versions']]
        self.assertEqual(set(ids), set(['v1.0', 'v2.0']))

    def test_versions_index_disable_v1(self):
        self.flags(enable_v1_api=False)
        req = fakes.HTTPRequest.blank('/')
        req.method = 'GET'
        req.content_type = 'application/json'
        resource = versions.Versions()
        result = resource.dispatch(resource.index, req, {})
        ids = [v['id'] for v in result['versions']]
        self.assertEqual(set(ids), set(['v2.0']))

    def test_versions_index_disable_v2(self):
        self.flags(enable_v2_api=False)
        req = fakes.HTTPRequest.blank('/')
        req.method = 'GET'
        req.content_type = 'application/json'
        resource = versions.Versions()
        result = resource.dispatch(resource.index, req, {})
        ids = [v['id'] for v in result['versions']]
        self.assertEqual(set(ids), set(['v1.0']))

    def test_volumes(self):
        req = fakes.HTTPRequest.blank('/fakeproject/volumes')
        req.method = 'GET'
        req.content_type = 'application/json'
        response = req.get_response(self.app)
        self.assertEqual(200, response.status_int)

    def test_volumes_detail(self):
        req = fakes.HTTPRequest.blank('/fakeproject/volumes/detail')
        req.method = 'GET'
        req.content_type = 'application/json'
        response = req.get_response(self.app)
        self.assertEqual(200, response.status_int)

    def test_types(self):
        req = fakes.HTTPRequest.blank('/fakeproject/types')
        req.method = 'GET'
        req.content_type = 'application/json'
        response = req.get_response(self.app)
        self.assertEqual(200, response.status_int)

    def test_snapshots(self):
        req = fakes.HTTPRequest.blank('/fakeproject/snapshots')
        req.method = 'GET'
        req.content_type = 'application/json'
        response = req.get_response(self.app)
        self.assertEqual(200, response.status_int)

    def test_snapshots_detail(self):
        req = fakes.HTTPRequest.blank('/fakeproject/snapshots/detail')
        req.method = 'GET'
        req.content_type = 'application/json'
        response = req.get_response(self.app)
        self.assertEqual(200, response.status_int)
