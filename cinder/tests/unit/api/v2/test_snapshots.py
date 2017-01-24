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

import ddt
import mock
from oslo_config import cfg
from six.moves import http_client
from six.moves.urllib import parse as urllib
import webob

from cinder.api import common
from cinder.api.v2 import snapshots
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit import utils
from cinder import volume


CONF = cfg.CONF

UUID = '00000000-0000-0000-0000-000000000001'
INVALID_UUID = '00000000-0000-0000-0000-000000000002'


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


@ddt.ddt
class SnapshotApiTest(test.TestCase):
    def setUp(self):
        super(SnapshotApiTest, self).setUp()
        self.controller = snapshots.SnapshotsController()
        self.ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_snapshot_create(self, mock_validate):
        volume = utils.create_volume(self.ctx)
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'
        snapshot = {
            "volume_id": volume.id,
            "force": False,
            "name": snapshot_name,
            "description": snapshot_description
        }

        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v2/snapshots')
        resp_dict = self.controller.create(req, body)

        self.assertIn('snapshot', resp_dict)
        self.assertEqual(snapshot_name, resp_dict['snapshot']['name'])
        self.assertEqual(snapshot_description,
                         resp_dict['snapshot']['description'])
        self.assertTrue(mock_validate.called)
        self.assertIn('updated_at', resp_dict['snapshot'])
        db.volume_destroy(self.ctx, volume.id)

    @ddt.data(True, 'y', 'true', 'trUE', 'yes', '1', 'on', 1, "1         ")
    def test_snapshot_create_force(self, force_param):
        volume = utils.create_volume(self.ctx, status='in-use')
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'
        snapshot = {
            "volume_id": volume.id,
            "force": force_param,
            "name": snapshot_name,
            "description": snapshot_description
        }
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v2/snapshots')
        resp_dict = self.controller.create(req, body)

        self.assertIn('snapshot', resp_dict)
        self.assertEqual(snapshot_name,
                         resp_dict['snapshot']['name'])
        self.assertEqual(snapshot_description,
                         resp_dict['snapshot']['description'])
        self.assertIn('updated_at', resp_dict['snapshot'])

        db.volume_destroy(self.ctx, volume.id)

    @ddt.data(False, 'n', 'false', 'falSE', 'No', '0', 'off', 0)
    def test_snapshot_create_force_failure(self, force_param):
        volume = utils.create_volume(self.ctx, status='in-use')
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'
        snapshot = {
            "volume_id": volume.id,
            "force": force_param,
            "name": snapshot_name,
            "description": snapshot_description
        }
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v2/snapshots')
        self.assertRaises(exception.InvalidVolume,
                          self.controller.create,
                          req,
                          body)

        db.volume_destroy(self.ctx, volume.id)

    @ddt.data("**&&^^%%$$##@@", '-1', 2, '01')
    def test_snapshot_create_invalid_force_param(self, force_param):
        volume = utils.create_volume(self.ctx, status='in-use')
        snapshot_name = 'Snapshot Test Name'
        snapshot_description = 'Snapshot Test Desc'

        snapshot = {
            "volume_id": volume.id,
            "force": force_param,
            "name": snapshot_name,
            "description": snapshot_description
        }
        body = dict(snapshot=snapshot)
        req = fakes.HTTPRequest.blank('/v2/snapshots')
        self.assertRaises(exception.InvalidParameterValue,
                          self.controller.create,
                          req,
                          body)

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
        req = fakes.HTTPRequest.blank('/v2/snapshots')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    @mock.patch.object(volume.api.API, "update_snapshot",
                       side_effect=v2_fakes.fake_snapshot_update)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    @mock.patch('cinder.db.volume_get')
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_snapshot_update(
            self, mock_validate, snapshot_get_by_id, volume_get,
            snapshot_metadata_get, update_snapshot):
        snapshot = {
            'id': UUID,
            'volume_id': fake.VOLUME_ID,
            'status': fields.SnapshotStatus.AVAILABLE,
            'volume_size': 100,
            'display_name': 'Default name',
            'display_description': 'Default description',
            'expected_attrs': ['metadata'],
        }
        ctx = context.RequestContext(fake.PROJECT_ID, fake.USER_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get.return_value = fake_volume_obj

        updates = {
            "name": "Updated Test Name",
        }
        body = {"snapshot": updates}
        req = fakes.HTTPRequest.blank('/v2/snapshots/%s' % UUID)
        res_dict = self.controller.update(req, UUID, body)
        expected = {
            'snapshot': {
                'id': UUID,
                'volume_id': fake.VOLUME_ID,
                'status': fields.SnapshotStatus.AVAILABLE,
                'size': 100,
                'created_at': None,
                'updated_at': None,
                'name': u'Updated Test Name',
                'description': u'Default description',
                'metadata': {},
            }
        }
        self.assertEqual(expected, res_dict)
        self.assertTrue(mock_validate.called)
        self.assertEqual(2, len(self.notifier.notifications))

    def test_snapshot_update_missing_body(self):
        body = {}
        req = fakes.HTTPRequest.blank('/v2/snapshots/%s' % UUID)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, UUID, body)

    def test_snapshot_update_invalid_body(self):
        body = {'name': 'missing top level snapshot key'}
        req = fakes.HTTPRequest.blank('/v2/snapshots/%s' % UUID)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, UUID, body)

    def test_snapshot_update_not_found(self):
        self.mock_object(volume.api.API, "get_snapshot", fake_snapshot_get)
        updates = {
            "name": "Updated Test Name",
        }
        body = {"snapshot": updates}
        req = fakes.HTTPRequest.blank('/v2/snapshots/not-the-uuid')
        self.assertRaises(exception.SnapshotNotFound, self.controller.update,
                          req, 'not-the-uuid', body)

    @mock.patch.object(volume.api.API, "delete_snapshot",
                       side_effect=v2_fakes.fake_snapshot_update)
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
        ctx = context.RequestContext(fake.PROJECT_ID, fake.USER_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj

        snapshot_id = UUID
        req = fakes.HTTPRequest.blank('/v2/snapshots/%s' % snapshot_id)
        resp = self.controller.delete(req, snapshot_id)
        self.assertEqual(http_client.ACCEPTED, resp.status_int)

    def test_snapshot_delete_invalid_id(self):
        self.mock_object(volume.api.API, "delete_snapshot",
                         fake_snapshot_delete)
        snapshot_id = INVALID_UUID
        req = fakes.HTTPRequest.blank('/v2/snapshots/%s' % snapshot_id)
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
        ctx = context.RequestContext(fake.PROJECT_ID, fake.USER_ID, True)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        fake_volume_obj = fake_volume.fake_volume_obj(ctx)
        snapshot_get_by_id.return_value = snapshot_obj
        volume_get_by_id.return_value = fake_volume_obj
        req = fakes.HTTPRequest.blank('/v2/snapshots/%s' % UUID)
        resp_dict = self.controller.show(req, UUID)

        self.assertIn('snapshot', resp_dict)
        self.assertEqual(UUID, resp_dict['snapshot']['id'])
        self.assertIn('updated_at', resp_dict['snapshot'])

    def test_snapshot_show_invalid_id(self):
        snapshot_id = INVALID_UUID
        req = fakes.HTTPRequest.blank('/v2/snapshots/%s' % snapshot_id)
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

        req = fakes.HTTPRequest.blank('/v2/snapshots/detail')
        resp_dict = self.controller.detail(req)

        self.assertIn('snapshots', resp_dict)
        resp_snapshots = resp_dict['snapshots']
        self.assertEqual(1, len(resp_snapshots))
        self.assertIn('updated_at', resp_snapshots[0])

        resp_snapshot = resp_snapshots.pop()
        self.assertEqual(UUID, resp_snapshot['id'])

    @mock.patch.object(db, 'snapshot_get_all_by_project',
                       v2_fakes.fake_snapshot_get_all_by_project)
    @mock.patch.object(db, 'snapshot_get_all',
                       v2_fakes.fake_snapshot_get_all)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_admin_list_snapshots_limited_to_project(self,
                                                     snapshot_metadata_get):
        req = fakes.HTTPRequest.blank('/v2/%s/snapshots' % fake.PROJECT_ID,
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('snapshots', res)
        self.assertEqual(1, len(res['snapshots']))

    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_list_snapshots_with_limit_and_offset(self,
                                                  snapshot_metadata_get):
        def list_snapshots_with_limit_and_offset(snaps, is_admin):
            req = fakes.HTTPRequest.blank('/v2/%s/snapshots?limit=1'
                                          '&offset=1' % fake.PROJECT_ID,
                                          use_admin_context=is_admin)
            res = self.controller.index(req)

            self.assertIn('snapshots', res)
            self.assertEqual(1, len(res['snapshots']))
            self.assertEqual(snaps[1].id, res['snapshots'][0]['id'])
            self.assertIn('updated_at', res['snapshots'][0])

            # Test that we get an empty list with an offset greater than the
            # number of items
            req = fakes.HTTPRequest.blank('/v2/snapshots?limit=1&offset=3')
            self.assertEqual({'snapshots': []}, self.controller.index(req))

        volume, snaps = self._create_db_snapshots(3)
        # admin case
        list_snapshots_with_limit_and_offset(snaps, is_admin=True)
        # non-admin case
        list_snapshots_with_limit_and_offset(snaps, is_admin=False)

    @mock.patch.object(db, 'snapshot_get_all_by_project')
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_list_snpashots_with_wrong_limit_and_offset(self,
                                                        mock_metadata_get,
                                                        mock_snapshot_get_all):
        """Test list with negative and non numeric limit and offset."""
        mock_snapshot_get_all.return_value = []

        # Negative limit
        req = fakes.HTTPRequest.blank('/v2/snapshots?limit=-1&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        # Non numeric limit
        req = fakes.HTTPRequest.blank('/v2/snapshots?limit=a&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        # Negative offset
        req = fakes.HTTPRequest.blank('/v2/snapshots?limit=1&offset=-1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        # Non numeric offset
        req = fakes.HTTPRequest.blank('/v2/snapshots?limit=1&offset=a')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        # Test that we get an exception HTTPBadRequest(400) with an offset
        # greater than the maximum offset value.
        url = '/v2/snapshots?limit=1&offset=323245324356534235'
        req = fakes.HTTPRequest.blank(url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def _assert_list_next(self, expected_query=None, project=fake.PROJECT_ID,
                          **kwargs):
        """Check a page of snapshots list."""
        # Since we are accessing v2 api directly we don't need to specify
        # v2 in the request path, if we did, we'd get /v2/v2 links back
        request_path = '/v2/%s/snapshots' % project
        expected_path = request_path

        # Construct the query if there are kwargs
        if kwargs:
            request_str = request_path + '?' + urllib.urlencode(kwargs)
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
            self.assertTrue(list, type(links))
            next_link = links[0]

            # rel entry must be next
            self.assertIn('rel', next_link)
            self.assertIn('next', next_link['rel'])

            # href entry must have the right path
            self.assertIn('href', next_link)
            href_parts = urllib.urlparse(next_link['href'])
            self.assertEqual(expected_path, href_parts.path)

            # And the query from the next link must match what we were
            # expecting
            params = urllib.parse_qs(href_parts.query)
            self.assertDictEqual(expected_query, params)

        # Make sure we don't have links if we were not expecting them
        else:
            self.assertNotIn('snapshots_links', res)

    def _create_db_snapshots(self, num_snaps):
        volume = utils.create_volume(self.ctx)
        snaps = [utils.create_snapshot(self.ctx,
                                       volume.id,
                                       display_name='snap' + str(i))
                 for i in range(num_snaps)]

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
                       v2_fakes.fake_snapshot_get_all_by_project)
    @mock.patch.object(db, 'snapshot_get_all',
                       v2_fakes.fake_snapshot_get_all)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_admin_list_snapshots_all_tenants(self, snapshot_metadata_get):
        req = fakes.HTTPRequest.blank('/v2/%s/snapshots?all_tenants=1' %
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
                return [v2_fakes.fake_snapshot(fake.VOLUME_ID,
                                               tenant_id='tenant1')]
            else:
                return []

        snapshot_get_all.side_effect = get_all

        req = fakes.HTTPRequest.blank('/v2/%s/snapshots?all_tenants=1'
                                      '&project_id=tenant1' % fake.PROJECT_ID,
                                      use_admin_context=True)
        res = self.controller.index(req)
        self.assertIn('snapshots', res)
        self.assertEqual(1, len(res['snapshots']))

    @mock.patch.object(db, 'snapshot_get_all_by_project',
                       v2_fakes.fake_snapshot_get_all_by_project)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_all_tenants_non_admin_gets_all_tenants(self,
                                                    snapshot_metadata_get):
        req = fakes.HTTPRequest.blank('/v2/%s/snapshots?all_tenants=1' %
                                      fake.PROJECT_ID)
        res = self.controller.index(req)
        self.assertIn('snapshots', res)
        self.assertEqual(1, len(res['snapshots']))

    @mock.patch.object(db, 'snapshot_get_all_by_project',
                       v2_fakes.fake_snapshot_get_all_by_project)
    @mock.patch.object(db, 'snapshot_get_all',
                       v2_fakes.fake_snapshot_get_all)
    @mock.patch('cinder.db.snapshot_metadata_get', return_value=dict())
    def test_non_admin_get_by_project(self, snapshot_metadata_get):
        req = fakes.HTTPRequest.blank('/v2/%s/snapshots' % fake.PROJECT_ID)
        res = self.controller.index(req)
        self.assertIn('snapshots', res)
        self.assertEqual(1, len(res['snapshots']))

    def _create_snapshot_bad_body(self, body):
        req = fakes.HTTPRequest.blank('/v2/%s/snapshots' % fake.PROJECT_ID)
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body)

    def test_create_no_body(self):
        self._create_snapshot_bad_body(body=None)

    def test_create_missing_snapshot(self):
        body = {'foo': {'a': 'b'}}
        self._create_snapshot_bad_body(body=body)

    def test_create_malformed_entity(self):
        body = {'snapshot': 'string'}
        self._create_snapshot_bad_body(body=body)
