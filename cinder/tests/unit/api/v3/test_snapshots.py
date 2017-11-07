# Copyright 2016 EMC Corporation
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

import ddt
import mock
from oslo_utils import strutils

from cinder.api import microversions as mv
from cinder.api.v3 import snapshots
from cinder import context
from cinder import exception
from cinder.objects import fields
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils as test_utils
from cinder import volume

UUID = '00000000-0000-0000-0000-000000000001'
INVALID_UUID = '00000000-0000-0000-0000-000000000002'


def fake_get(self, context, *args, **kwargs):
    vol = {'id': fake.VOLUME_ID,
           'size': 100,
           'name': 'fake',
           'host': 'fake-host',
           'status': 'available',
           'encryption_key_id': None,
           'volume_type_id': None,
           'migration_status': None,
           'availability_zone': 'fake-zone',
           'attach_status': 'detached',
           'metadata': {}}
    return fake_volume.fake_volume_obj(context, **vol)


def create_snapshot_query_with_metadata(metadata_query_string,
                                        api_microversion):
    """Helper to create metadata querystring with microversion"""
    req = fakes.HTTPRequest.blank('/v3/snapshots?metadata=' +
                                  metadata_query_string)
    req.headers = mv.get_mv_header(api_microversion)
    req.api_version_request = mv.get_api_version(api_microversion)

    return req


@ddt.ddt
class SnapshotApiTest(test.TestCase):
    def setUp(self):
        super(SnapshotApiTest, self).setUp()
        self.mock_object(volume.api.API, 'get', fake_get)
        self.mock_object(scheduler_rpcapi.SchedulerAPI, 'create_snapshot')
        self.controller = snapshots.SnapshotsController()
        self.ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

    @ddt.data(mv.GROUP_SNAPSHOTS,
              mv.get_prior_version(mv.GROUP_SNAPSHOTS),
              mv.SNAPSHOT_LIST_USER_ID)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_snapshot_show(self, max_ver, snapshot_get_by_id, volume_get_by_id,
                           snapshot_metadata_get):
        snapshot = {
            'id': UUID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.AVAILABLE,
            'volume_size': 100,
            'display_name': 'Default name',
            'display_description': 'Default description',
            'expected_attrs': ['metadata'],
            'group_snapshot_id': None,
        }
        ctx = context.RequestContext(fake.PROJECT_ID, fake.USER_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % UUID)
        req.api_version_request = mv.get_api_version(max_ver)
        resp_dict = self.controller.show(req, UUID)

        self.assertIn('snapshot', resp_dict)
        self.assertEqual(UUID, resp_dict['snapshot']['id'])
        self.assertIn('updated_at', resp_dict['snapshot'])
        if max_ver == mv.SNAPSHOT_LIST_USER_ID:
            self.assertIn('user_id', resp_dict['snapshot'])
        elif max_ver == mv.GROUP_SNAPSHOTS:
            self.assertIn('group_snapshot_id', resp_dict['snapshot'])
            self.assertNotIn('user_id', resp_dict['snapshot'])
        else:
            self.assertNotIn('group_snapshot_id', resp_dict['snapshot'])
            self.assertNotIn('user_id', resp_dict['snapshot'])

    def test_snapshot_show_invalid_id(self):
        snapshot_id = INVALID_UUID
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % snapshot_id)
        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.show, req, snapshot_id)

    def _create_snapshot(self, name=None, metadata=None):
        """Creates test snapshopt with provided metadata"""
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        snap = {"volume_id": fake.VOLUME_ID,
                "display_name": name or "Volume Test Name",
                "description": "Volume Test Desc"
                }
        if metadata:
            snap["metadata"] = metadata
        body = {"snapshot": snap}
        self.controller.create(req, body=body)

    @ddt.data(('host', 'test_host1', True), ('cluster_name', 'cluster1', True),
              ('availability_zone', 'nova1', False))
    @ddt.unpack
    def test_snapshot_list_with_filter(self, filter_name, filter_value,
                                       is_admin_user):
        volume1 = test_utils.create_volume(self.ctx, host='test_host1',
                                           cluster_name='cluster1',
                                           availability_zone='nova1')
        volume2 = test_utils.create_volume(self.ctx, host='test_host2',
                                           cluster_name='cluster2',
                                           availability_zone='nova2')
        snapshot1 = test_utils.create_snapshot(self.ctx, volume1.id)
        test_utils.create_snapshot(self.ctx, volume2.id)

        url = '/v3/snapshots?%s=%s' % (filter_name, filter_value)
        # Generic filtering is introduced since '3,31' and we add
        # 'availability_zone' support by using generic filtering.
        req = fakes.HTTPRequest.blank(url, use_admin_context=is_admin_user,
                                      version=mv.RESOURCE_FILTER)
        res_dict = self.controller.detail(req)

        self.assertEqual(1, len(res_dict['snapshots']))
        self.assertEqual(snapshot1.id, res_dict['snapshots'][0]['id'])

    def _create_multiple_snapshots_with_different_project(self):
        volume1 = test_utils.create_volume(self.ctx,
                                           project=fake.PROJECT_ID)
        volume2 = test_utils.create_volume(self.ctx,
                                           project=fake.PROJECT2_ID)
        test_utils.create_snapshot(
            context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True),
            volume1.id)
        test_utils.create_snapshot(
            context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True),
            volume1.id)
        test_utils.create_snapshot(
            context.RequestContext(fake.USER_ID, fake.PROJECT2_ID, True),
            volume2.id)

    @ddt.data('snapshots', 'snapshots/detail')
    def test_list_snapshot_with_count_param_version_not_matched(self, action):
        self._create_multiple_snapshots_with_different_project()

        is_detail = True if 'detail' in action else False
        req = fakes.HTTPRequest.blank("/v3/%s?with_count=True" % action)
        req.headers = mv.get_mv_header(
            mv.get_prior_version(mv.SUPPORT_COUNT_INFO))
        req.api_version_request = mv.get_api_version(
            mv.get_prior_version(mv.SUPPORT_COUNT_INFO))
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._items(req, is_detail=is_detail)
        self.assertNotIn('count', res_dict)

    @ddt.data({'method': 'snapshots',
               'display_param': 'True'},
              {'method': 'snapshots',
               'display_param': 'False'},
              {'method': 'snapshots',
               'display_param': '1'},
              {'method': 'snapshots/detail',
               'display_param': 'True'},
              {'method': 'snapshots/detail',
               'display_param': 'False'},
              {'method': 'snapshots/detail',
               'display_param': '1'}
              )
    @ddt.unpack
    def test_list_snapshot_with_count_param(self, method, display_param):
        self._create_multiple_snapshots_with_different_project()

        is_detail = True if 'detail' in method else False
        show_count = strutils.bool_from_string(display_param, strict=True)
        # Request with 'with_count' and 'limit'
        req = fakes.HTTPRequest.blank(
            "/v3/%s?with_count=%s&limit=1" % (method, display_param))
        req.headers = mv.get_mv_header(mv.SUPPORT_COUNT_INFO)
        req.api_version_request = mv.get_api_version(mv.SUPPORT_COUNT_INFO)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._items(req, is_detail=is_detail)
        self.assertEqual(1, len(res_dict['snapshots']))
        if show_count:
            self.assertEqual(2, res_dict['count'])
        else:
            self.assertNotIn('count', res_dict)

        # Request with 'with_count'
        req = fakes.HTTPRequest.blank(
            "/v3/%s?with_count=%s" % (method, display_param))
        req.headers = mv.get_mv_header(mv.SUPPORT_COUNT_INFO)
        req.api_version_request = mv.get_api_version(mv.SUPPORT_COUNT_INFO)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._items(req, is_detail=is_detail)
        self.assertEqual(2, len(res_dict['snapshots']))
        if show_count:
            self.assertEqual(2, res_dict['count'])
        else:
            self.assertNotIn('count', res_dict)

        # Request with admin context and 'all_tenants'
        req = fakes.HTTPRequest.blank(
            "/v3/%s?with_count=%s&all_tenants=1" % (method, display_param))
        req.headers = mv.get_mv_header(mv.SUPPORT_COUNT_INFO)
        req.api_version_request = mv.get_api_version(mv.SUPPORT_COUNT_INFO)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._items(req, is_detail=is_detail)
        self.assertEqual(3, len(res_dict['snapshots']))
        if show_count:
            self.assertEqual(3, res_dict['count'])
        else:
            self.assertNotIn('count', res_dict)

    @mock.patch('cinder.objects.volume.Volume.refresh')
    def test_snapshot_list_with_sort_name(self, mock_refresh):
        self._create_snapshot(name='test1')
        self._create_snapshot(name='test2')

        req = fakes.HTTPRequest.blank(
            '/v3/snapshots?sort_key=name',
            version=mv.get_prior_version(mv.SNAPSHOT_SORT))
        self.assertRaises(exception.InvalidInput, self.controller.detail, req)

        req = fakes.HTTPRequest.blank('/v3/snapshots?sort_key=name',
                                      version=mv.SNAPSHOT_SORT)
        res_dict = self.controller.detail(req)
        self.assertEqual(2, len(res_dict['snapshots']))
        self.assertEqual('test2', res_dict['snapshots'][0]['name'])
        self.assertEqual('test1', res_dict['snapshots'][1]['name'])

    @mock.patch('cinder.objects.volume.Volume.refresh')
    def test_snapshot_list_with_one_metadata_in_filter(self, mock_refresh):
        # Create snapshot with metadata key1: value1
        metadata = {"key1": "val1"}
        self._create_snapshot(metadata=metadata)

        # Create request with metadata filter key1: value1
        req = create_snapshot_query_with_metadata(
            '{"key1":"val1"}', mv.SNAPSHOT_LIST_METADATA_FILTER)

        # query controller with above request
        res_dict = self.controller.detail(req)

        # verify 1 snapshot is returned
        self.assertEqual(1, len(res_dict['snapshots']))

        # verify if the medadata of the returned snapshot is key1: value1
        self.assertDictEqual({"key1": "val1"}, res_dict['snapshots'][0][
            'metadata'])

        # Create request with metadata filter key2: value2
        req = create_snapshot_query_with_metadata(
            '{"key2":"val2"}', mv.SNAPSHOT_LIST_METADATA_FILTER)

        # query controller with above request
        res_dict = self.controller.detail(req)

        # verify no snapshot is returned
        self.assertEqual(0, len(res_dict['snapshots']))

    @mock.patch('cinder.objects.volume.Volume.refresh')
    def test_snapshot_list_with_multiple_metadata_in_filter(self,
                                                            mock_refresh):
        # Create snapshot with metadata key1: value1, key11: value11
        metadata = {"key1": "val1", "key11": "val11"}
        self._create_snapshot(metadata=metadata)

        # Create request with metadata filter key1: value1, key11: value11
        req = create_snapshot_query_with_metadata(
            '{"key1":"val1", "key11":"val11"}',
            mv.SNAPSHOT_LIST_METADATA_FILTER)

        # query controller with above request
        res_dict = self.controller.detail(req)

        # verify 1 snapshot is returned
        self.assertEqual(1, len(res_dict['snapshots']))

        # verify if the medadata of the returned snapshot is key1: value1
        self.assertDictEqual({"key1": "val1", "key11": "val11"}, res_dict[
            'snapshots'][0]['metadata'])

        # Create request with metadata filter key1: value1
        req = create_snapshot_query_with_metadata(
            '{"key1":"val1"}', mv.SNAPSHOT_LIST_METADATA_FILTER)

        # query controller with above request
        res_dict = self.controller.detail(req)

        # verify 1 snapshot is returned
        self.assertEqual(1, len(res_dict['snapshots']))

        # verify if the medadata of the returned snapshot is key1: value1
        self.assertDictEqual({"key1": "val1", "key11": "val11"}, res_dict[
            'snapshots'][0]['metadata'])

        # Create request with metadata filter key2: value2
        req = create_snapshot_query_with_metadata(
            '{"key2":"val2"}', mv.SNAPSHOT_LIST_METADATA_FILTER)

        # query controller with above request
        res_dict = self.controller.detail(req)

        # verify no snapshot is returned
        self.assertEqual(0, len(res_dict['snapshots']))

    @ddt.data(mv.get_prior_version(mv.RESOURCE_FILTER),
              mv.RESOURCE_FILTER,
              mv.LIKE_FILTER)
    @mock.patch('cinder.api.common.reject_invalid_filters')
    def test_snapshot_list_with_general_filter(self, version, mock_update):
        url = '/v3/%s/snapshots' % fake.PROJECT_ID
        req = fakes.HTTPRequest.blank(url,
                                      version=version,
                                      use_admin_context=False)
        self.controller.index(req)

        if version != mv.get_prior_version(mv.RESOURCE_FILTER):
            support_like = True if version == mv.LIKE_FILTER else False
            mock_update.assert_called_once_with(req.environ['cinder.context'],
                                                mock.ANY, 'snapshot',
                                                support_like)

    @mock.patch('cinder.objects.volume.Volume.refresh')
    def test_snapshot_list_with_metadata_unsupported_microversion(
            self, mock_refresh):
        # Create snapshot with metadata key1: value1
        metadata = {"key1": "val1"}
        self._create_snapshot(metadata=metadata)

        # Create request with metadata filter key2: value2
        req = create_snapshot_query_with_metadata(
            '{"key2":"val2"}',
            mv.get_prior_version(mv.SNAPSHOT_LIST_METADATA_FILTER))

        # query controller with above request
        res_dict = self.controller.detail(req)

        # verify some snapshot is returned
        self.assertNotEqual(0, len(res_dict['snapshots']))
