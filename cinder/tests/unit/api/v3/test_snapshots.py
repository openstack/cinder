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

import datetime
from http import HTTPStatus
from unittest import mock
import urllib.parse
from zoneinfo import ZoneInfo

import ddt
from oslo_config import cfg
from oslo_utils import strutils
import webob
from webob import exc

from cinder.api import common
from cinder.api import microversions as mv
from cinder.api.v3 import snapshots
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v3 import fakes as v3_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils
from cinder import volume

CONF = cfg.CONF

UUID = '00000000-0000-0000-0000-000000000001'
INVALID_UUID = '00000000-0000-0000-0000-000000000002'


def fake_volume_get(self, context, *args, **kwargs):
    vol = {'id': fake.VOLUME_ID,
           'size': 100,
           'name': 'fake',
           'host': 'fake-host',
           'status': 'available',
           'encryption_key_id': None,
           'migration_status': None,
           'availability_zone': 'fake-zone',
           'attach_status': 'detached',
           'metadata': {},
           'volume_type_id': fake.VOLUME_TYPE_ID}
    return fake_volume.fake_volume_obj(context, **vol)


def _get_default_snapshot_param():
    return {
        'id': UUID,
        'volume_id': fake.VOLUME_ID,
        'status': fields.SnapshotStatus.AVAILABLE,
        'volume_size': 100,
        'created_at': None,
        'updated_at': None,
        'user_id': 'bcb7746c7a41472d88a1ffac89ba6a9b',
        'project_id': '7ffe17a15c724e2aa79fc839540aec15',
        'display_name': 'Default name',
        'display_description': 'Default description',
        'deleted': None,
        'volume': {'availability_zone': 'test_zone'}
    }


def fake_snapshot_delete(self, context, snapshot):
    if snapshot['id'] != UUID:
        raise exception.SnapshotNotFound(snapshot['id'])


def fake_snapshot_get(self, context, snapshot_id):
    if snapshot_id != UUID:
        raise exception.SnapshotNotFound(snapshot_id)

    param = _get_default_snapshot_param()
    return param


def fake_snapshot_get_all(self, context, search_opts=None):
    param = _get_default_snapshot_param()
    return [param]


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
        super().setUp()
        self.mock_object(volume.api.API, 'get', fake_volume_get)
        self.mock_object(db.sqlalchemy.api, 'volume_type_get',
                         v3_fakes.fake_volume_type_get)
        self.patch('cinder.quota.QUOTAS.reserve')
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
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(self.ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % UUID)
        req.environ['cinder.context'] = self.ctx
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

    @ddt.data(
        (True, True, mv.USE_QUOTA),
        (True, False, mv.USE_QUOTA),
        (False, True, mv.get_prior_version(mv.USE_QUOTA)),
        (False, False, mv.get_prior_version(mv.USE_QUOTA)),
    )
    @ddt.unpack
    def test_snapshot_show_with_use_quota(self, present, value, microversion):
        volume = test_utils.create_volume(self.ctx, host='test_host1',
                                          cluster_name='cluster1',
                                          availability_zone='nova1')
        snapshot = test_utils.create_snapshot(self.ctx, volume.id,
                                              use_quota=value)

        url = '/v3/snapshots?%s' % snapshot.id
        req = fakes.HTTPRequest.blank(url, version=microversion)
        res_dict = self.controller.show(req, snapshot.id)['snapshot']
        if present:
            self.assertIs(value, res_dict['consumes_quota'])
        else:
            self.assertNotIn('consumes_quota', res_dict)

    def test_snapshot_show_invalid_id(self):
        snapshot_id = INVALID_UUID
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % snapshot_id)
        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.show, req, snapshot_id)

    def _create_snapshot(self, name=None, metadata=None):
        """Creates test snapshopt with provided metadata"""
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        req.environ['cinder.context'] = self.ctx
        snap = {"volume_id": fake.VOLUME_ID,
                "display_name": name or "Volume Test Name",
                "description": "Volume Test Desc"
                }
        if metadata:
            snap["metadata"] = metadata
        body = {"snapshot": snap}
        self.controller.create(req, body=body)

    @ddt.data(('host', 'test_host1', True, mv.RESOURCE_FILTER),
              ('cluster_name', 'cluster1', True, mv.RESOURCE_FILTER),
              ('availability_zone', 'nova1', False, mv.RESOURCE_FILTER),
              ('consumes_quota', 'true', False, mv.USE_QUOTA))
    @ddt.unpack
    def test_snapshot_list_with_filter(self, filter_name, filter_value,
                                       is_admin_user, microversion):
        volume1 = test_utils.create_volume(self.ctx, host='test_host1',
                                           cluster_name='cluster1',
                                           availability_zone='nova1')
        volume2 = test_utils.create_volume(self.ctx, host='test_host2',
                                           cluster_name='cluster2',
                                           availability_zone='nova2')
        snapshot1 = test_utils.create_snapshot(self.ctx, volume1.id,
                                               use_quota=True)
        test_utils.create_snapshot(self.ctx, volume2.id, use_quota=False)

        url = '/v3/snapshots?%s=%s' % (filter_name, filter_value)
        # Generic filtering is introduced since '3,31' and we add
        # 'availability_zone' support by using generic filtering.
        req = fakes.HTTPRequest.blank(url, use_admin_context=is_admin_user,
                                      version=microversion)
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

    @mock.patch('cinder.volume.api.API.create_snapshot')
    def test_snapshot_create_allow_in_use(self, mock_create):
        req = create_snapshot_query_with_metadata(
            '{"key2": "val2"}',
            mv.SNAPSHOT_IN_USE)

        body = {'snapshot': {'volume_id': fake.VOLUME_ID}}

        self.controller.create(req, body=body)
        self.assertIn('allow_in_use', mock_create.call_args_list[0][1])
        self.assertTrue(mock_create.call_args_list[0][1]['allow_in_use'])

    @mock.patch('cinder.volume.api.API.create_snapshot')
    def test_snapshot_create_allow_in_use_negative(self, mock_create):
        req = create_snapshot_query_with_metadata(
            '{"key2": "val2"}',
            mv.get_prior_version(mv.SNAPSHOT_IN_USE))

        body = {'snapshot': {'volume_id': fake.VOLUME_ID}}

        self.controller.create(req, body=body)
        self.assertNotIn('allow_in_use', mock_create.call_args_list[0][1])

    @ddt.data(False, 'false', 'f', 'no', 'n', '0', 'off')
    @mock.patch('cinder.volume.api.API.create_snapshot')
    def test_snapshot_create_force_false(self, force_flag, mock_create):
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'
        snapshot = {
            "volume_id": fake.VOLUME_ID,
            "force": force_flag,
            "name": snapshot_name,
            "description": snapshot_description
        }

        body = dict(snapshot=snapshot)
        req = create_snapshot_query_with_metadata(
            '{"key2": "val2"}',
            mv.SNAPSHOT_IN_USE)
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)
        mock_create.assert_not_called()

        # prevent regression -- shouldn't raise for pre-mv-3.66
        req = create_snapshot_query_with_metadata(
            '{"key2": "val2"}',
            mv.get_prior_version(mv.SNAPSHOT_IN_USE))
        self.controller.create(req, body=body)
        # ... but also shouldn't allow an in-use snapshot
        self.assertNotIn('allow_in_use', mock_create.call_args_list[0][1])


@ddt.ddt
class SnapshotApiTestNoMicroversion(test.TestCase):
    def setUp(self):
        super().setUp()
        self.mock_object(scheduler_rpcapi.SchedulerAPI, 'create_snapshot')
        self.controller = snapshots.SnapshotsController()
        self.ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

    def test_snapshot_create(self):
        volume = test_utils.create_volume(self.ctx, volume_type_id=None)
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'
        snapshot = {
            "volume_id": volume.id,
            "force": False,
            "name": snapshot_name,
            "description": snapshot_description
        }

        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        resp_dict = self.controller.create(req, body=body)

        self.assertIn('snapshot', resp_dict)
        self.assertEqual(snapshot_name, resp_dict['snapshot']['name'])
        self.assertEqual(snapshot_description,
                         resp_dict['snapshot']['description'])
        self.assertIn('updated_at', resp_dict['snapshot'])
        db.volume_destroy(self.ctx, volume.id)

    def test_snapshot_create_with_null_validate(self):
        volume = test_utils.create_volume(self.ctx, volume_type_id=None)
        snapshot = {
            "volume_id": volume.id,
            "force": False,
            "name": None,
            "description": None
        }

        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        resp_dict = self.controller.create(req, body=body)

        self.assertIn('snapshot', resp_dict)
        self.assertIsNone(resp_dict['snapshot']['name'])
        self.assertIsNone(resp_dict['snapshot']['description'])
        db.volume_destroy(self.ctx, volume.id)

    @ddt.data(True, 'y', 'true', 'yes', '1', 'on')
    def test_snapshot_create_force(self, force_param):
        volume = test_utils.create_volume(
            self.ctx, status='in-use', volume_type_id=None)
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'
        snapshot = {
            "volume_id": volume.id,
            "force": force_param,
            "name": snapshot_name,
            "description": snapshot_description
        }
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        resp_dict = self.controller.create(req, body=body)

        self.assertIn('snapshot', resp_dict)
        self.assertEqual(snapshot_name,
                         resp_dict['snapshot']['name'])
        self.assertEqual(snapshot_description,
                         resp_dict['snapshot']['description'])
        self.assertIn('updated_at', resp_dict['snapshot'])

        db.volume_destroy(self.ctx, volume.id)

    @ddt.data(False, 'n', 'false', 'No', '0', 'off')
    def test_snapshot_create_force_failure(self, force_param):
        volume = test_utils.create_volume(
            self.ctx, status='in-use', volume_type_id=None)
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'
        snapshot = {
            "volume_id": volume.id,
            "force": force_param,
            "name": snapshot_name,
            "description": snapshot_description
        }
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        self.assertRaises(exception.InvalidVolume,
                          self.controller.create,
                          req,
                          body=body)

        db.volume_destroy(self.ctx, volume.id)

    @ddt.data("**&&^^%%$$##@@", '-1', 2, '01', 'falSE', 0, 'trUE', 1,
              "1         ")
    def test_snapshot_create_invalid_force_param(self, force_param):
        volume = test_utils.create_volume(
            self.ctx, status='available', volume_type_id=None)
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'

        snapshot = {
            "volume_id": volume.id,
            "force": force_param,
            "name": snapshot_name,
            "description": snapshot_description
        }
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          req,
                          body=body)

        db.volume_destroy(self.ctx, volume.id)

    def test_snapshot_create_without_volume_id(self):
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'
        body = {
            "snapshot": {
                "force": True,
                "name": snapshot_name,
                "description": snapshot_description
            }
        }
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)

    @ddt.data({"snapshot": {"description": "   sample description",
                            "name": "   test"}},
              {"snapshot": {"description": "sample description   ",
                            "name": "test   "}},
              {"snapshot": {"description": " sample description ",
                            "name": "  test name  "}})
    def test_snapshot_create_with_leading_trailing_spaces(self, body):
        volume = test_utils.create_volume(self.ctx, volume_type_id=None)
        body['snapshot']['volume_id'] = volume.id
        req = fakes.HTTPRequest.blank('/v3/snapshots')
        resp_dict = self.controller.create(req, body=body)

        self.assertEqual(body['snapshot']['display_name'].strip(),
                         resp_dict['snapshot']['name'])
        self.assertEqual(body['snapshot']['description'].strip(),
                         resp_dict['snapshot']['description'])
        db.volume_destroy(self.ctx, volume.id)

    @mock.patch.object(volume.api.API, "update_snapshot",
                       side_effect=v3_fakes.fake_snapshot_update)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.db.volume_get')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_snapshot_update(
            self, snapshot_get_by_id, volume_get,
            snapshot_metadata_get, update_snapshot):
        snapshot = {
            'id': UUID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.AVAILABLE,
            'created_at': "2014-01-01 00:00:00",
            'volume_size': 100,
            'display_name': 'Default name',
            'display_description': 'Default description',
            'expected_attrs': ['metadata'],
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(self.ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get.return_value = fake_volume_obj

        updates = {
            "name": "Updated Test Name",
        }
        body = {"snapshot": updates}
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % UUID)
        req.environ['cinder.context'] = self.ctx
        res_dict = self.controller.update(req, UUID, body=body)
        expected = {
            'snapshot': {
                'id': UUID,
                'volume_id': fake.VOLUME_ID,
                'status': fields.SnapshotStatus.AVAILABLE,
                'size': 100,
                'created_at': datetime.datetime(
                    2014, 1, 1, 0, 0, 0, tzinfo=ZoneInfo('UTC'),
                ),
                'updated_at': None,
                'name': u'Updated Test Name',
                'description': u'Default description',
                'metadata': {},
            }
        }
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))

    @mock.patch.object(volume.api.API, "update_snapshot",
                       side_effect=v3_fakes.fake_snapshot_update)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.db.volume_get')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_snapshot_update_with_null_validate(
            self, snapshot_get_by_id, volume_get,
            snapshot_metadata_get, update_snapshot):
        snapshot = {
            'id': UUID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.AVAILABLE,
            'created_at': "2014-01-01 00:00:00",
            'volume_size': 100,
            'name': 'Default name',
            'description': 'Default description',
            'expected_attrs': ['metadata'],
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(self.ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get.return_value = fake_volume_obj

        updates = {
            "name": None,
            "description": None,
        }
        body = {"snapshot": updates}
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % UUID)
        req.environ['cinder.context'] = self.ctx
        res_dict = self.controller.update(req, UUID, body=body)

        self.assertEqual(fields.SnapshotStatus.AVAILABLE,
                         res_dict['snapshot']['status'])
        self.assertIsNone(res_dict['snapshot']['name'])
        self.assertIsNone(res_dict['snapshot']['description'])

    def test_snapshot_update_missing_body(self):
        body = {}
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % UUID)
        self.assertRaises(exception.ValidationError,
                          self.controller.update, req, UUID, body=body)

    def test_snapshot_update_invalid_body(self):
        body = {'name': 'missing top level snapshot key'}
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % UUID)
        self.assertRaises(exception.ValidationError,
                          self.controller.update, req, UUID, body=body)

    def test_snapshot_update_not_found(self):
        self.mock_object(volume.api.API, "get_snapshot", fake_snapshot_get)
        updates = {
            "name": "Updated Test Name",
        }
        body = {"snapshot": updates}
        req = fakes.HTTPRequest.blank('/v3/snapshots/not-the-uuid')
        self.assertRaises(exception.SnapshotNotFound, self.controller.update,
                          req, 'not-the-uuid', body=body)

    @mock.patch.object(volume.api.API, "update_snapshot",
                       side_effect=v3_fakes.fake_snapshot_update)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.db.volume_get')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_snapshot_update_with_leading_trailing_spaces(
            self, snapshot_get_by_id, volume_get,
            snapshot_metadata_get, update_snapshot):
        snapshot = {
            'id': UUID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.AVAILABLE,
            'created_at': "2018-01-14 00:00:00",
            'volume_size': 100,
            'display_name': 'Default name',
            'display_description': 'Default description',
            'expected_attrs': ['metadata'],
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(self.ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get.return_value = fake_volume_obj

        updates = {
            "name": "     test     ",
            "description": "     test     "
        }
        body = {"snapshot": updates}
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % UUID)
        req.environ['cinder.context'] = self.ctx
        res_dict = self.controller.update(req, UUID, body=body)
        expected = {
            'snapshot': {
                'id': UUID,
                'volume_id': fake.VOLUME_ID,
                'status': fields.SnapshotStatus.AVAILABLE,
                'size': 100,
                'created_at': datetime.datetime(2018, 1, 14, 0, 0, 0,
                                                tzinfo=ZoneInfo('UTC')),
                'updated_at': None,
                'name': u'test',
                'description': u'test',
                'metadata': {},
            }
        }
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))

    @mock.patch.object(volume.api.API, "delete_snapshot",
                       side_effect=v3_fakes.fake_snapshot_update)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_snapshot_delete(self, snapshot_get_by_id, volume_get_by_id,
                             snapshot_metadata_get, delete_snapshot):
        snapshot = {
            'id': UUID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.AVAILABLE,
            'volume_size': 100,
            'display_name': 'Default name',
            'display_description': 'Default description',
            'expected_attrs': ['metadata'],
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(self.ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj

        snapshot_id = UUID
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % snapshot_id)
        req.environ['cinder.context'] = self.ctx
        resp = self.controller.delete(req, snapshot_id)
        self.assertEqual(HTTPStatus.ACCEPTED, resp.status_int)

    def test_snapshot_delete_invalid_id(self):
        self.mock_object(volume.api.API, "delete_snapshot",
                         fake_snapshot_delete)
        snapshot_id = INVALID_UUID
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % snapshot_id)
        self.assertRaises(exception.SnapshotNotFound, self.controller.delete,
                          req, snapshot_id)

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    def test_snapshot_show(self, snapshot_get_by_id, volume_get_by_id,
                           snapshot_metadata_get):
        snapshot = {
            'id': UUID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.AVAILABLE,
            'volume_size': 100,
            'display_name': 'Default name',
            'display_description': 'Default description',
            'expected_attrs': ['metadata'],
        }
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(self.ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % UUID)
        req.environ['cinder.context'] = self.ctx
        resp_dict = self.controller.show(req, UUID)

        self.assertIn('snapshot', resp_dict)
        self.assertEqual(UUID, resp_dict['snapshot']['id'])
        self.assertIn('updated_at', resp_dict['snapshot'])

    def test_snapshot_show_invalid_id(self):
        snapshot_id = INVALID_UUID
        req = fakes.HTTPRequest.blank('/v3/snapshots/%s' % snapshot_id)
        self.assertRaises(exception.SnapshotNotFound,
                          self.controller.show, req, snapshot_id)

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.objects.Volume.get_by_id')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    @mock.patch('cinder.volume.api.API.get_all_snapshots')
    def test_snapshot_detail(self, get_all_snapshots, snapshot_get_by_id,
                             volume_get_by_id, snapshot_metadata_get):
        snapshot = {
            'id': UUID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.AVAILABLE,
            'volume_size': 100,
            'display_name': 'Default name',
            'display_description': 'Default description',
            'expected_attrs': ['metadata']
        }
        ctx = context.RequestContext(fake.PROJECT_ID, fake.USER_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj
        snapshots = objects.SnapshotList(objects=[snapshot_obj])
        get_all_snapshots.return_value = snapshots

        req = fakes.HTTPRequest.blank('/v3/snapshots/detail')
        resp_dict = self.controller.detail(req)

        self.assertIn('snapshots', resp_dict)
        resp_snapshots = resp_dict['snapshots']
        self.assertEqual(1, len(resp_snapshots))
        self.assertIn('updated_at', resp_snapshots[0])

        resp_snapshot = resp_snapshots.pop()
        self.assertEqual(UUID, resp_snapshot['id'])

    @mock.patch.object(db, 'snapshot_get_all_by_project',
                       v3_fakes.fake_snapshot_get_all_by_project)
    @mock.patch.object(db, 'snapshot_get_all',
                       v3_fakes.fake_snapshot_get_all)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_admin_list_snapshots_limited_to_project(self,
                                                     snapshot_metadata_get):
        req = fakes.HTTPRequest.blank('/v3/%s/snapshots' % fake.PROJECT_ID,
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('snapshots', res)
        self.assertEqual(1, len(res['snapshots']))

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_list_snapshots_with_limit_and_offset(self,
                                                  snapshot_metadata_get):
        def list_snapshots_with_limit_and_offset(snaps, is_admin):
            req = fakes.HTTPRequest.blank('/v3/%s/snapshots?limit=1'
                                          '&offset=1' % fake.PROJECT_ID,
                                          use_admin_context=is_admin)
            res = self.controller.index(req)

            self.assertIn('snapshots', res)
            self.assertEqual(1, len(res['snapshots']))
            self.assertEqual(snaps[1].id, res['snapshots'][0]['id'])
            self.assertIn('updated_at', res['snapshots'][0])

            # Test that we get an empty list with an offset greater than the
            # number of items
            req = fakes.HTTPRequest.blank('/v3/snapshots?limit=1&offset=3')
            self.assertEqual({'snapshots': []}, self.controller.index(req))

        volume, snaps = self._create_db_snapshots(3)
        # admin case
        list_snapshots_with_limit_and_offset(snaps, is_admin=True)
        # non-admin case
        list_snapshots_with_limit_and_offset(snaps, is_admin=False)

    @mock.patch.object(db, 'snapshot_get_all_by_project')
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_list_snapshots_with_wrong_limit_and_offset(self,
                                                        mock_metadata_get,
                                                        mock_snapshot_get_all):
        """Test list with negative and non numeric limit and offset."""
        mock_snapshot_get_all.return_value = []

        # Negative limit
        req = fakes.HTTPRequest.blank('/v3/snapshots?limit=-1&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        # Non numeric limit
        req = fakes.HTTPRequest.blank('/v3/snapshots?limit=a&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        # Negative offset
        req = fakes.HTTPRequest.blank('/v3/snapshots?limit=1&offset=-1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        # Non numeric offset
        req = fakes.HTTPRequest.blank('/v3/snapshots?limit=1&offset=a')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        # Test that we get an exception HTTPBadRequest(400) with an offset
        # greater than the maximum offset value.
        url = '/v3/snapshots?limit=1&offset=323245324356534235'
        req = fakes.HTTPRequest.blank(url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def _assert_list_next(self, expected_query=None, project=fake.PROJECT_ID,
                          **kwargs):
        """Check a page of snapshots list."""
        # Since we are accessing v2 api directly we don't need to specify
        # v2 in the request path, if we did, we'd get /v3/v2 links back
        request_path = '/v3/%s/snapshots' % project
        expected_path = request_path

        # Construct the query if there are kwargs
        if kwargs:
            request_str = request_path + '?' + urllib.parse.urlencode(kwargs)
        else:
            request_str = request_path

        # Make the request
        req = fakes.HTTPRequest.blank(request_str)
        res = self.controller.index(req)

        # We only expect to have a next link if there is an actual expected
        # query.
        if expected_query:
            # We must have the links
            self.assertIn('snapshots_links', res)
            links = res['snapshots_links']

            # Must be a list of links, even if we only get 1 back
            self.assertIsInstance(links, list)
            next_link = links[0]

            # rel entry must be next
            self.assertIn('rel', next_link)
            self.assertIn('next', next_link['rel'])

            # href entry must have the right path
            self.assertIn('href', next_link)
            href_parts = urllib.parse.urlparse(next_link['href'])
            self.assertEqual(expected_path, href_parts.path)

            # And the query from the next link must match what we were
            # expecting
            params = urllib.parse.parse_qs(href_parts.query)
            self.assertDictEqual(expected_query, params)

        # Make sure we don't have links if we were not expecting them
        else:
            self.assertNotIn('snapshots_links', res)

    def _create_db_snapshots(self, num_snaps):
        volume = test_utils.create_volume(self.ctx, volume_type_id=None)
        snaps = [
            test_utils.create_snapshot(
                self.ctx, volume.id, display_name='snap' + str(i)
            ) for i in range(num_snaps)
        ]

        self.addCleanup(db.volume_destroy, self.ctx, volume.id)
        for snap in snaps:
            self.addCleanup(db.snapshot_destroy, self.ctx, snap.id)

        snaps.reverse()
        return volume, snaps

    def test_list_snapshots_next_link_default_limit(self):
        """Test that snapshot list pagination is limited by osapi_max_limit."""
        volume, snaps = self._create_db_snapshots(3)

        # NOTE(geguileo): Since cinder.api.common.limited has already been
        # imported his argument max_limit already has a default value of 1000
        # so it doesn't matter that we change it to 2.  That's why we need to
        # mock it and send it current value.  We still need to set the default
        # value because other sections of the code use it, for example
        # _get_collection_links
        CONF.set_default('osapi_max_limit', 2)

        def get_pagination_params(params, max_limit=CONF.osapi_max_limit,
                                  original_call=common.get_pagination_params):
            return original_call(params, max_limit)

        def _get_limit_param(params, max_limit=CONF.osapi_max_limit,
                             original_call=common._get_limit_param):
            return original_call(params, max_limit)

        with mock.patch.object(common, 'get_pagination_params',
                               get_pagination_params), \
                mock.patch.object(common, '_get_limit_param',
                                  _get_limit_param):
            # The link from the first page should link to the second
            self._assert_list_next({'marker': [snaps[1].id]})

            # Second page should have no next link
            self._assert_list_next(marker=snaps[1].id)

    def test_list_snapshots_next_link_with_limit(self):
        """Test snapshot list pagination with specific limit."""
        volume, snaps = self._create_db_snapshots(2)

        # The link from the first page should link to the second
        self._assert_list_next({'limit': ['1'], 'marker': [snaps[0].id]},
                               limit=1)

        # Even though there are no more elements, we should get a next element
        # per specification.
        expected = {'limit': ['1'], 'marker': [snaps[1].id]}
        self._assert_list_next(expected, limit=1, marker=snaps[0].id)

        # When we go beyond the number of elements there should be no more
        # next links
        self._assert_list_next(limit=1, marker=snaps[1].id)

    @mock.patch.object(db, 'snapshot_get_all_by_project',
                       v3_fakes.fake_snapshot_get_all_by_project)
    @mock.patch.object(db, 'snapshot_get_all',
                       v3_fakes.fake_snapshot_get_all)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_admin_list_snapshots_all_tenants(self, snapshot_metadata_get):
        req = fakes.HTTPRequest.blank('/v3/%s/snapshots?all_tenants=1' %
                                      fake.PROJECT_ID,
                                      use_admin_context=True)
        res = self.controller.index(req)
        self.assertIn('snapshots', res)
        self.assertEqual(3, len(res['snapshots']))

    @mock.patch.object(db, 'snapshot_get_all')
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_admin_list_snapshots_by_tenant_id(self, snapshot_metadata_get,
                                               snapshot_get_all):
        def get_all(context, filters=None, marker=None, limit=None,
                    sort_keys=None, sort_dirs=None, offset=None):
            if 'project_id' in filters and 'tenant1' in filters['project_id']:
                return [v3_fakes.fake_snapshot(fake.VOLUME_ID,
                                               tenant_id='tenant1')]
            else:
                return []

        snapshot_get_all.side_effect = get_all

        req = fakes.HTTPRequest.blank('/v3/%s/snapshots?all_tenants=1'
                                      '&project_id=tenant1' % fake.PROJECT_ID,
                                      use_admin_context=True)
        res = self.controller.index(req)
        self.assertIn('snapshots', res)
        self.assertEqual(1, len(res['snapshots']))

    @mock.patch.object(db, 'snapshot_get_all_by_project',
                       v3_fakes.fake_snapshot_get_all_by_project)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_all_tenants_non_admin_gets_all_tenants(self,
                                                    snapshot_metadata_get):
        req = fakes.HTTPRequest.blank('/v3/%s/snapshots?all_tenants=1' %
                                      fake.PROJECT_ID)
        res = self.controller.index(req)
        self.assertIn('snapshots', res)
        self.assertEqual(1, len(res['snapshots']))

    @mock.patch.object(db, 'snapshot_get_all_by_project',
                       v3_fakes.fake_snapshot_get_all_by_project)
    @mock.patch.object(db, 'snapshot_get_all',
                       v3_fakes.fake_snapshot_get_all)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_non_admin_get_by_project(self, snapshot_metadata_get):
        req = fakes.HTTPRequest.blank('/v3/%s/snapshots' % fake.PROJECT_ID)
        res = self.controller.index(req)
        self.assertIn('snapshots', res)
        self.assertEqual(1, len(res['snapshots']))

    def _create_snapshot_bad_body(self, body):
        req = fakes.HTTPRequest.blank('/v3/%s/snapshots' % fake.PROJECT_ID)
        req.method = 'POST'

        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)

    def test_create_no_body(self):
        self._create_snapshot_bad_body(body=None)

    def test_create_missing_snapshot(self):
        body = {'foo': {'a': 'b'}}
        self._create_snapshot_bad_body(body=body)

    def test_create_malformed_entity(self):
        body = {'snapshot': 'string'}
        self._create_snapshot_bad_body(body=body)
