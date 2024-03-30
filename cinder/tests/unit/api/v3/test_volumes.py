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
import json
from unittest import mock
import urllib

import ddt
import fixtures
import iso8601
from oslo_config import cfg
from oslo_serialization import jsonutils
from oslo_utils import strutils
from oslo_utils import timeutils
import webob

from cinder.api import api_utils
from cinder.api import common
from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.v3.views import volumes as view
from cinder.api.v3 import volumes
from cinder.backup import api as backup_api
from cinder.common import constants as cinder_constants
from cinder import context
from cinder import db
from cinder import exception
from cinder.group import api as group_api
from cinder import objects
from cinder.objects import fields
from cinder.policies import volumes as policy
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v3 import fakes as v3_fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_volume
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils
from cinder.volume import api as volume_api
from cinder.volume import api as vol_get

CONF = cfg.CONF

DEFAULT_AZ = "zone1:host1"
# DDT data for testing whether an 'encryption_key_id' should appear in a
# volume's or backup's details (also used by test_backups.py).
ENCRYPTION_KEY_ID_IN_DETAILS = {
    'expected_in_details': True,
    'encryption_key_id': fake.ENCRYPTION_KEY_ID,
    'version': mv.ENCRYPTION_KEY_ID_IN_DETAILS,
}, {
    # No encryption ID to display
    'expected_in_details': False,
    'encryption_key_id': None,
    'version': mv.ENCRYPTION_KEY_ID_IN_DETAILS,
}, {
    # Fixed key ID should not be displayed
    'expected_in_details': False,
    'encryption_key_id': cinder_constants.FIXED_KEY_ID,
    'version': mv.ENCRYPTION_KEY_ID_IN_DETAILS,
}, {
    # Unsupported microversion
    'expected_in_details': False,
    'encryption_key_id': fake.ENCRYPTION_KEY_ID,
    'version': mv.get_prior_version(mv.ENCRYPTION_KEY_ID_IN_DETAILS),
}


class BaseVolumeTest(test.TestCase):
    def setUp(self):
        super().setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        fake_image.mock_image_service(self)
        self.controller = volumes.VolumeController(self.ext_mgr)

        self.flags(host='fake')

        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        # This will be cleaned up by the NestedTempfile fixture in base class
        self.tmp_path = self.useFixture(fixtures.TempDir()).path

    @classmethod
    def _vol_in_request_body(
        cls,
        size=v3_fakes.DEFAULT_VOL_SIZE,
        name=v3_fakes.DEFAULT_VOL_NAME,
        description=v3_fakes.DEFAULT_VOL_DESCRIPTION,
        availability_zone=DEFAULT_AZ,
        snapshot_id=None,
        source_volid=None,
        consistencygroup_id=None,
        volume_type=None,
        image_ref=None,
        image_id=None,
        group_id=None,
        backup_id=None,
    ):
        vol = {"size": size,
               "name": name,
               "description": description,
               "availability_zone": availability_zone,
               "snapshot_id": snapshot_id,
               "source_volid": source_volid,
               "consistencygroup_id": consistencygroup_id,
               "volume_type": volume_type,
               "group_id": group_id,
               }

        if image_id is not None:
            vol['image_id'] = image_id
        elif image_ref is not None:
            vol['imageRef'] = image_ref
        elif backup_id is not None:
            vol['backup_id'] = backup_id

        return vol


@ddt.ddt
class VolumeApiTest(BaseVolumeTest):
    def test_check_volume_filters_called(self):
        # Clear the filters collection to make sure the filters collection
        # cache can be reloaded using tmp filter file.
        common._FILTERS_COLLECTION = None
        with mock.patch.object(vol_get.API,
                               'check_volume_filters') as volume_get:
            req = fakes.HTTPRequest.blank('/v3/volumes?bootable=True')
            req.method = 'GET'
            req.content_type = 'application/json'
            req.headers = mv.get_mv_header(mv.BASE_VERSION)
            req.environ['cinder.context'].is_admin = True

            tmp_filter_file = self.tmp_path + '/resource_filters_tests.json'
            self.override_config('resource_query_filters_file',
                                 tmp_filter_file)
            with open(tmp_filter_file, 'w') as f:
                f.write(json.dumps({"volume": ['bootable']}))
            self.controller.index(req)
            filters = req.params.copy()

            volume_get.assert_called_with(filters, False)
        # Reset the CONF.resource_query_filters_file and clear the filters
        # collection to avoid leaking other cases, and it will be re-loaded
        # from CONF.resource_query_filters_file in next call.
        self._reset_filter_file()

    def test_check_volume_filters_strict_called(self):
        # Clear the filters collection to make sure the filters collection
        # cache can be reloaded using tmp filter file.
        common._FILTERS_COLLECTION = None
        with mock.patch.object(vol_get.API,
                               'check_volume_filters') as volume_get:
            req = fakes.HTTPRequest.blank('/v3/volumes?bootable=True')
            req.method = 'GET'
            req.content_type = 'application/json'
            req.headers = mv.get_mv_header(mv.VOLUME_LIST_BOOTABLE)
            req.environ['cinder.context'].is_admin = True
            req.api_version_request = mv.get_api_version(
                mv.VOLUME_LIST_BOOTABLE)

            tmp_filter_file = self.tmp_path + '/resource_filters_tests.json'
            self.override_config('resource_query_filters_file',
                                 tmp_filter_file)
            with open(tmp_filter_file, 'w') as f:
                f.write(json.dumps({"volume": ['bootable']}))
            self.controller.index(req)
            filters = req.params.copy()

            volume_get.assert_called_with(filters, True)
        # Reset the CONF.resource_query_filters_file and clear the filters
        # collection to avoid leaking other cases, and it will be re-loaded
        # from CONF.resource_query_filters_file in next call.
        self._reset_filter_file()

    def _create_volume_with_glance_metadata(self):
        basetime = timeutils.utcnow()
        td = datetime.timedelta(minutes=1)

        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1',
                                            'created_at': basetime - 3 * td,
                                            'updated_at': basetime - 2 * td,
                                            'project_id':
                                            self.ctxt.project_id,
                                            'volume_type_id':
                                                fake.VOLUME_TYPE_ID,
                                            'id': fake.VOLUME_ID})
        db.volume_glance_metadata_create(self.ctxt, vol1.id, 'image_name',
                                         'imageTestOne')
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'created_at': basetime - td,
                                            'updated_at': basetime,
                                            'project_id':
                                            self.ctxt.project_id,
                                            'volume_type_id':
                                                fake.VOLUME_TYPE_ID,
                                            'id': fake.VOLUME2_ID})
        db.volume_glance_metadata_create(self.ctxt, vol2.id, 'image_name',
                                         'imageTestTwo')
        db.volume_glance_metadata_create(self.ctxt, vol2.id, 'disk_format',
                                         'qcow2')
        return [vol1, vol2]

    def _create_volume_with_group(self):
        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1',
                                            'project_id':
                                            self.ctxt.project_id,
                                            'group_id':
                                            fake.GROUP_ID,
                                            'volume_type_id':
                                                fake.VOLUME_TYPE_ID})
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'project_id':
                                            self.ctxt.project_id,
                                            'group_id':
                                            fake.GROUP2_ID,
                                            'volume_type_id':
                                                fake.VOLUME_TYPE_ID})
        return [vol1, vol2]

    def _create_multiple_volumes_with_different_project(self):
        # Create volumes in project 1
        db.volume_create(self.ctxt, {'display_name': 'test1',
                                     'project_id': fake.PROJECT_ID,
                                     'volume_type_id': fake.VOLUME_TYPE_ID,
                                     'id': fake.VOLUME_ID})
        db.volume_create(self.ctxt, {'display_name': 'test2',
                                     'project_id': fake.PROJECT_ID,
                                     'volume_type_id': fake.VOLUME_TYPE_ID,
                                     'id': fake.VOLUME2_ID})
        # Create volume in project 2
        db.volume_create(self.ctxt, {'display_name': 'test3',
                                     'project_id': fake.PROJECT2_ID,
                                     'volume_type_id': fake.VOLUME_TYPE_ID,
                                     'id': fake.VOLUME3_ID})

    def test_volume_index_filter_by_glance_metadata(self):
        vols = self._create_volume_with_glance_metadata()
        req = fakes.HTTPRequest.blank("/v3/volumes?glance_metadata="
                                      "{'image_name': 'imageTestOne'}")
        req.headers = mv.get_mv_header(mv.VOLUME_LIST_GLANCE_METADATA)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_LIST_GLANCE_METADATA)
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(vols[0].id, volumes[0]['id'])

    def test_volume_index_filter_by_glance_metadata_in_unsupport_version(self):
        self._create_volume_with_glance_metadata()
        req = fakes.HTTPRequest.blank("/v3/volumes?glance_metadata="
                                      "{'image_name': 'imageTestOne'}")
        req.headers = mv.get_mv_header(mv.BASE_VERSION)
        req.api_version_request = mv.get_api_version(mv.BASE_VERSION)
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(2, len(volumes))

    def test_volume_index_filter_by_group_id(self):
        vols = self._create_volume_with_group()
        req = fakes.HTTPRequest.blank(("/v3/volumes?group_id=%s") %
                                      fake.GROUP_ID)
        req.headers = mv.get_mv_header(mv.VOLUME_LIST_GROUP)
        req.api_version_request = mv.get_api_version(mv.VOLUME_LIST_GROUP)
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(vols[0].id, volumes[0]['id'])

    @ddt.data('volumes', 'volumes/detail')
    def test_list_volume_with_count_param_version_not_matched(self, action):
        self._create_multiple_volumes_with_different_project()

        is_detail = True if 'detail' in action else False
        req = fakes.HTTPRequest.blank("/v3/%s?with_count=True" % action)
        req.headers = mv.get_mv_header(
            mv.get_prior_version(mv.SUPPORT_COUNT_INFO))
        req.api_version_request = mv.get_api_version(
            mv.get_prior_version(mv.SUPPORT_COUNT_INFO))
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._get_volumes(req, is_detail=is_detail)
        self.assertNotIn('count', res_dict)

    @ddt.data({'method': 'volumes',
               'display_param': 'True'},
              {'method': 'volumes',
               'display_param': 'False'},
              {'method': 'volumes',
               'display_param': '1'},
              {'method': 'volumes/detail',
               'display_param': 'True'},
              {'method': 'volumes/detail',
               'display_param': 'False'},
              {'method': 'volumes/detail',
               'display_param': '1'}
              )
    @ddt.unpack
    def test_list_volume_with_count_param(self, method, display_param):
        self._create_multiple_volumes_with_different_project()

        self.mock_object(view.ViewBuilder, '_get_volume_type',
                         v3_fakes.fake_volume_type_name_get)
        is_detail = True if 'detail' in method else False
        show_count = strutils.bool_from_string(display_param, strict=True)
        # Request with 'with_count' and 'limit'
        req = fakes.HTTPRequest.blank(
            "/v3/%s?with_count=%s&limit=1" % (method, display_param))
        req.headers = mv.get_mv_header(mv.SUPPORT_COUNT_INFO)
        req.api_version_request = mv.get_api_version(mv.SUPPORT_COUNT_INFO)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._get_volumes(req, is_detail=is_detail)
        self.assertEqual(1, len(res_dict['volumes']))
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
        res_dict = self.controller._get_volumes(req, is_detail=is_detail)
        self.assertEqual(2, len(res_dict['volumes']))
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
        res_dict = self.controller._get_volumes(req, is_detail=is_detail)
        self.assertEqual(3, len(res_dict['volumes']))
        if show_count:
            self.assertEqual(3, res_dict['count'])
        else:
            self.assertNotIn('count', res_dict)

    def test_list_volume_with_multiple_filters(self):
        metadata = {'key_X': 'value_X'}
        self._create_multiple_volumes_with_different_project()
        test_utils.create_volume(self.ctxt, metadata=metadata)

        self.mock_object(view.ViewBuilder, '_get_volume_type',
                         v3_fakes.fake_volume_type_name_get)
        # Request with 'all_tenants' and 'metadata'
        req = fakes.HTTPRequest.blank(
            "/v3/volumes/detail?all_tenants=1"
            "&metadata=%7B%27key_X%27%3A+%27value_X%27%7D")
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._get_volumes(req, is_detail=True)
        self.assertEqual(1, len(res_dict['volumes']))
        self.assertEqual(metadata, res_dict['volumes'][0]['metadata'])

    def test_list_volume_with_filter_and_paginate(self):
        self._create_multiple_volumes_with_different_project()
        test_utils.create_volume(self.ctxt)

        self.mock_object(view.ViewBuilder, '_get_volume_type',
                         v3_fakes.fake_volume_type_name_get)

        req = fakes.HTTPRequest.blank(
            "/v3/volumes/detail?all_tenants=1"
            "&sort=bootable:asc&with_count=True&limit=5"
            "&marker=" + fake.VOLUME_ID)
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._get_volumes(req, is_detail=True)
        self.assertEqual(2, len(res_dict['volumes']))

    def test_volume_index_filter_by_group_id_in_unsupport_version(self):
        self._create_volume_with_group()
        req = fakes.HTTPRequest.blank(("/v3/volumes?group_id=%s") %
                                      fake.GROUP_ID)
        req.headers = mv.get_mv_header(mv.BACKUP_UPDATE)
        req.api_version_request = mv.get_api_version(mv.BACKUP_UPDATE)
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(2, len(volumes))

    @ddt.data(('true', 0), ('false', 1))
    @ddt.unpack
    def test_volume_list_with_quota_filter(self, use_quota, expected_index):
        volumes = (test_utils.create_volume(self.ctxt, host='test_host1',
                                            cluster_name='cluster1',
                                            volume_type_id=None,
                                            use_quota=True,
                                            availability_zone='nova1'),
                   test_utils.create_volume(self.ctxt, host='test_host2',
                                            cluster_name='cluster2',
                                            volume_type_id=None,
                                            use_quota=False,
                                            availability_zone='nova2'))
        req = fakes.HTTPRequest.blank(
            '/v3/volumes?consumes_quota=%s' % use_quota, version=mv.USE_QUOTA)
        res_dict = self.controller.detail(req)
        self.assertEqual(1, len(res_dict['volumes']))
        self.assertEqual(volumes[expected_index].id,
                         res_dict['volumes'][0]['id'])

    def test_volume_list_without_quota_filter(self):
        num_vols = 4
        vol_ids = set()
        # Half of the volumes will use quota, the other half won't
        for i in range(num_vols):
            vol = test_utils.create_volume(self.ctxt,
                                           use_quota=bool(i % 2),
                                           host='test_host',
                                           cluster_name='cluster',
                                           volume_type_id=None,
                                           availability_zone='nova1')
            vol_ids.add(vol.id)
        req = fakes.HTTPRequest.blank('/v3/volumes', version=mv.USE_QUOTA)
        res_dict = self.controller.detail(req)

        res_vol_ids = {v['id'] for v in res_dict['volumes']}
        self.assertEqual(num_vols, len(res_vol_ids))
        self.assertEqual(vol_ids, res_vol_ids)

    def _fake_volumes_summary_request(self,
                                      version=mv.VOLUME_SUMMARY,
                                      all_tenant=False,
                                      is_admin=False):
        req_url = '/v3/volumes/summary'
        if all_tenant:
            req_url += '?all_tenants=True'
        req = fakes.HTTPRequest.blank(req_url, use_admin_context=is_admin)
        req.headers = mv.get_mv_header(version)
        req.api_version_request = mv.get_api_version(version)
        return req

    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get_full',
                       autospec=True)
    @mock.patch.object(volume_api.API, 'get_snapshot', autospec=True)
    @mock.patch.object(volume_api.API, 'create', autospec=True)
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create_with_snapshot_image(self, mock_validate, create,
                                               get_snapshot, volume_type_get):
        create.side_effect = v3_fakes.fake_volume_api_create
        get_snapshot.side_effect = v3_fakes.fake_snapshot_get
        volume_type_get.side_effect = v3_fakes.fake_volume_type_get

        vol = self._vol_in_request_body(
            image_id="b0a599e0-41d7-3582-b260-769f443c862a")

        snapshot_id = fake.SNAPSHOT_ID
        ex = self._expected_vol_from_controller(snapshot_id=snapshot_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/%s/volumes' % fake.PROJECT_ID)
        req.headers = mv.get_mv_header(mv.SUPPORT_NOVA_IMAGE)
        req.api_version_request = mv.get_api_version(mv.SUPPORT_NOVA_IMAGE)
        res_dict = self.controller.create(req, body=body)
        self.assertEqual(ex, res_dict)
        context = req.environ['cinder.context']
        get_snapshot.assert_called_once_with(self.controller.volume_api,
                                             context, snapshot_id)
        kwargs = self._expected_volume_api_create_kwargs(
            v3_fakes.fake_snapshot(snapshot_id))
        create.assert_called_once_with(
            self.controller.volume_api, context,
            vol['size'], v3_fakes.DEFAULT_VOL_NAME,
            v3_fakes.DEFAULT_VOL_DESCRIPTION,
            **kwargs)

    def test_volumes_summary_in_unsupport_version(self):
        """Function call to test summary volumes API in unsupported version"""
        req = self._fake_volumes_summary_request(
            version=mv.get_prior_version(mv.VOLUME_SUMMARY))
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
                          self.controller.summary, req)

    def test_volumes_summary_in_supported_version(self):
        """Function call to test the summary volumes API for version v3."""
        req = self._fake_volumes_summary_request()
        res_dict = self.controller.summary(req)
        expected = {'volume-summary': {'total_size': 0.0, 'total_count': 0}}
        self.assertEqual(expected, res_dict)

        vol = self._vol_in_request_body(availability_zone="nova")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        res_dict = self.controller.create(req, body=body)

        req = self._fake_volumes_summary_request()
        res_dict = self.controller.summary(req)
        expected = {'volume-summary': {'total_size': 1.0, 'total_count': 1}}
        self.assertEqual(expected, res_dict)

    @ddt.data(
        (mv.get_prior_version(mv.VOLUME_SUMMARY_METADATA),
         {'volume-summary': {'total_size': 0.0,
                             'total_count': 0}}),
        (mv.VOLUME_SUMMARY_METADATA, {'volume-summary': {'total_size': 0.0,
                                                         'total_count': 0,
                                                         'metadata': {}}}))
    @ddt.unpack
    def test_volume_summary_empty(self, summary_api_version, expect_result):
        req = self._fake_volumes_summary_request(version=summary_api_version)
        res_dict = self.controller.summary(req)
        self.assertEqual(expect_result, res_dict)

    @ddt.data(
        (mv.get_prior_version(mv.VOLUME_SUMMARY_METADATA),
         {'volume-summary': {'total_size': 2,
                             'total_count': 2}}),
        (mv.VOLUME_SUMMARY_METADATA,
         {'volume-summary': {'total_size': 2,
                             'total_count': 2,
                             'metadata': {
                                 'name': ['test_name1', 'test_name2'],
                                 'age': ['test_age']}}}))
    @ddt.unpack
    def test_volume_summary_return_metadata(self, summary_api_version,
                                            expect_result):
        test_utils.create_volume(self.ctxt, metadata={'name': 'test_name1',
                                                      'age': 'test_age'})
        test_utils.create_volume(self.ctxt, metadata={'name': 'test_name2',
                                                      'age': 'test_age'})
        ctxt2 = context.RequestContext(fake.USER_ID, fake.PROJECT2_ID, True)
        test_utils.create_volume(ctxt2, metadata={'name': 'test_name3'})

        req = self._fake_volumes_summary_request(version=summary_api_version)
        res_dict = self.controller.summary(req)
        self.assertEqual(expect_result, res_dict)

    @ddt.data(
        (mv.get_prior_version(mv.VOLUME_SUMMARY_METADATA),
            {'volume-summary': {'total_size': 2,
                                'total_count': 2}}),
        (mv.VOLUME_SUMMARY_METADATA,
            {'volume-summary': {'total_size': 2,
                                'total_count': 2,
                                'metadata': {
                                    'name': ['test_name1', 'test_name2'],
                                    'age': ['test_age']}}}))
    @ddt.unpack
    def test_volume_summary_return_metadata_all_tenant(
            self, summary_api_version, expect_result):
        test_utils.create_volume(self.ctxt, metadata={'name': 'test_name1',
                                                      'age': 'test_age'})
        ctxt2 = context.RequestContext(fake.USER_ID, fake.PROJECT2_ID, True)
        test_utils.create_volume(ctxt2, metadata={'name': 'test_name2',
                                                  'age': 'test_age'})

        req = self._fake_volumes_summary_request(version=summary_api_version,
                                                 all_tenant=True,
                                                 is_admin=True)
        res_dict = self.controller.summary(req)
        self.assertEqual(expect_result, res_dict)

    def _expected_vol_from_controller(
            self,
            size=v3_fakes.DEFAULT_VOL_SIZE,
            availability_zone=DEFAULT_AZ,
            description=v3_fakes.DEFAULT_VOL_DESCRIPTION,
            name=v3_fakes.DEFAULT_VOL_NAME,
            consistencygroup_id=None,
            source_volid=None,
            snapshot_id=None,
            metadata=None,
            attachments=None,
            volume_type=v3_fakes.DEFAULT_VOL_TYPE,
            status=v3_fakes.DEFAULT_VOL_STATUS,
            with_migration_status=False,
            group_id=None,
            req_version=None):
        metadata = metadata or {}
        attachments = attachments or []
        volume = {'volume':
                  {'attachments': attachments,
                   'availability_zone': availability_zone,
                   'bootable': 'false',
                   'consistencygroup_id': consistencygroup_id,
                   'group_id': group_id,
                   'created_at': datetime.datetime(
                       1900, 1, 1, 1, 1, 1, tzinfo=iso8601.UTC),
                   'updated_at': datetime.datetime(
                       1900, 1, 1, 1, 1, 1, tzinfo=iso8601.UTC),
                   'description': description,
                   'id': v3_fakes.DEFAULT_VOL_ID,
                   'links':
                   [{'href': 'http://localhost/v3/%s/volumes/%s' % (
                             fake.PROJECT_ID, fake.VOLUME_ID),
                     'rel': 'self'},
                    {'href': 'http://localhost/%s/volumes/%s' % (
                             fake.PROJECT_ID, fake.VOLUME_ID),
                     'rel': 'bookmark'}],
                   'metadata': metadata,
                   'name': name,
                   'replication_status': 'disabled',
                   'multiattach': False,
                   'size': size,
                   'snapshot_id': snapshot_id,
                   'source_volid': source_volid,
                   'status': status,
                   'user_id': fake.USER_ID,
                   'volume_type': volume_type,
                   'encrypted': False}}

        if with_migration_status:
            volume['volume']['migration_status'] = None

        # Remove group_id if max version is less than GROUP_VOLUME.
        if req_version and req_version.matches(
                None, mv.get_prior_version(mv.GROUP_VOLUME)):
            volume['volume'].pop('group_id')

        return volume

    def _expected_volume_api_create_kwargs(self, snapshot=None,
                                           availability_zone=DEFAULT_AZ,
                                           source_volume=None,
                                           test_group=None,
                                           req_version=None):
        volume = {
            'metadata': None,
            'snapshot': snapshot,
            'source_volume': source_volume,
            'consistencygroup': None,
            'availability_zone': availability_zone,
            'scheduler_hints': None,
            'group': test_group,
        }

        # Remove group_id if max version is less than GROUP_VOLUME.
        if req_version and req_version.matches(
                None, mv.get_prior_version(mv.GROUP_VOLUME)):
            volume.pop('group')

        return volume

    @ddt.data((mv.GROUP_VOLUME,
               {'display_name': ' test name ',
                'display_description': ' test desc ',
                'size': 1}),
              (mv.get_prior_version(mv.GROUP_VOLUME),
               {'name': ' test name ',
                'description': ' test desc ',
                'size': 1}),
              ('3.0',
               {'name': 'test name',
                'description': 'test desc',
                'size': 1,
                'user_id': 'teapot',
                'project_id': 'kettle',
                'status': 'confused'}))
    @ddt.unpack
    def test_volume_create(self, max_ver, volume_body):
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_get)
        self.mock_object(volume_api.API, "create",
                         v3_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes')
        req.api_version_request = mv.get_api_version(max_ver)

        body = {'volume': volume_body}
        res_dict = self.controller.create(req, body=body)
        ex = self._expected_vol_from_controller(
            req_version=req.api_version_request, name='test name',
            description='test desc')
        self.assertEqual(ex['volume']['name'],
                         res_dict['volume']['name'])
        self.assertEqual(ex['volume']['description'],
                         res_dict['volume']['description'])

    def test_volume_create_extra_params(self):
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_get)
        self.mock_object(volume_api.API, "create",
                         v3_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes')
        req.api_version_request = mv.get_api_version(
            mv.SUPPORT_VOLUME_SCHEMA_CHANGES)

        body = {'volume': {
                'name': 'test name',
                'description': 'test desc',
                'size': 1,
                'user_id': 'teapot',
                'project_id': 'kettle',
                'status': 'confused'}}
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          req, body=body)

    @ddt.data(mv.get_prior_version(mv.VOLUME_DELETE_FORCE),
              mv.VOLUME_DELETE_FORCE)
    @mock.patch('cinder.context.RequestContext.authorize')
    def test_volume_delete_with_force(self, request_version, mock_authorize):
        mock_delete = self.mock_object(volume_api.API, "delete")
        self.mock_object(volume_api.API, 'get', return_value="fake_volume")

        req = fakes.HTTPRequest.blank('/v3/volumes/fake_id?force=True')
        req.api_version_request = mv.get_api_version(request_version)
        self.controller.delete(req, 'fake_id')
        context = req.environ['cinder.context']
        if request_version == mv.VOLUME_DELETE_FORCE:
            mock_authorize.assert_called_with(policy.FORCE_DELETE_POLICY,
                                              target_obj="fake_volume")
            mock_delete.assert_called_with(context,
                                           "fake_volume",
                                           cascade=False,
                                           force=True)
        else:
            mock_authorize.assert_not_called()
            mock_delete.assert_called_with(context,
                                           "fake_volume",
                                           cascade=False,
                                           force=False)

    @ddt.data(mv.GROUP_SNAPSHOTS, mv.get_prior_version(mv.GROUP_SNAPSHOTS))
    @mock.patch.object(group_api.API, 'get')
    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get_full',
                       autospec=True)
    @mock.patch.object(volume_api.API, 'get_snapshot', autospec=True)
    @mock.patch.object(volume_api.API, 'create', autospec=True)
    def test_volume_creation_from_snapshot(self, max_ver, create, get_snapshot,
                                           volume_type_get, group_get):
        create.side_effect = v3_fakes.fake_volume_api_create
        get_snapshot.side_effect = v3_fakes.fake_snapshot_get
        volume_type_get.side_effect = v3_fakes.fake_volume_type_get

        fake_group = {
            'id': fake.GROUP_ID,
            'group_type_id': fake.GROUP_TYPE_ID,
            'name': 'fake_group'
        }
        group_get.return_value = fake_group

        snapshot_id = fake.SNAPSHOT_ID
        vol = self._vol_in_request_body(snapshot_id=snapshot_id,
                                        group_id=fake.GROUP_ID)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/%s/volumes' % fake.PROJECT_ID)
        req.api_version_request = mv.get_api_version(max_ver)
        res_dict = self.controller.create(req, body=body)
        ex = self._expected_vol_from_controller(
            snapshot_id=snapshot_id,
            req_version=req.api_version_request)
        self.assertEqual(ex, res_dict)

        context = req.environ['cinder.context']
        get_snapshot.assert_called_once_with(self.controller.volume_api,
                                             context, snapshot_id)

        kwargs = self._expected_volume_api_create_kwargs(
            v3_fakes.fake_snapshot(snapshot_id),
            test_group=fake_group,
            req_version=req.api_version_request)
        create.assert_called_once_with(
            self.controller.volume_api, context,
            vol['size'], v3_fakes.DEFAULT_VOL_NAME,
            v3_fakes.DEFAULT_VOL_DESCRIPTION,
            **kwargs)

    @ddt.data(mv.VOLUME_CREATE_FROM_BACKUP,
              mv.get_prior_version(mv.VOLUME_CREATE_FROM_BACKUP))
    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get_full',
                       autospec=True)
    @mock.patch.object(backup_api.API, 'get', autospec=True)
    @mock.patch.object(volume_api.API, 'create', autospec=True)
    def test_volume_creation_from_backup(self, max_ver, create, get_backup,
                                         volume_type_get):
        create.side_effect = v3_fakes.fake_volume_api_create
        get_backup.side_effect = v3_fakes.fake_backup_get
        volume_type_get.side_effect = v3_fakes.fake_volume_type_get

        backup_id = fake.BACKUP_ID
        req = fakes.HTTPRequest.blank('/v3/%s/volumes' % fake.PROJECT_ID)
        req.api_version_request = mv.get_api_version(max_ver)
        if max_ver == mv.VOLUME_CREATE_FROM_BACKUP:
            vol = self._vol_in_request_body(backup_id=backup_id)
        else:
            vol = self._vol_in_request_body()
        body = {"volume": vol}
        res_dict = self.controller.create(req, body=body)
        ex = self._expected_vol_from_controller(
            req_version=req.api_version_request)
        self.assertEqual(ex, res_dict)

        context = req.environ['cinder.context']
        kwargs = self._expected_volume_api_create_kwargs(
            req_version=req.api_version_request)
        if max_ver >= mv.VOLUME_CREATE_FROM_BACKUP:
            get_backup.assert_called_once_with(self.controller.backup_api,
                                               context, backup_id)
            kwargs.update({'backup': v3_fakes.fake_backup_get(None, context,
                                                              backup_id)})
        create.assert_called_once_with(
            self.controller.volume_api, context,
            vol['size'],
            v3_fakes.DEFAULT_VOL_NAME,
            v3_fakes.DEFAULT_VOL_DESCRIPTION,
            **kwargs)

    def test_volume_creation_with_scheduler_hints(self):
        vol = self._vol_in_request_body(availability_zone=None)
        vol.pop('group_id')
        body = {"volume": vol,
                "OS-SCH-HNT:scheduler_hints": {
                    'different_host': [fake.UUID1, fake.UUID2]}}
        req = webob.Request.blank('/v3/%s/volumes' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.ctxt))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(HTTPStatus.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['volume'])

    @ddt.data('fake_host', '', 1234, '          ')
    def test_volume_creation_invalid_scheduler_hints(self, invalid_hints):
        vol = self._vol_in_request_body()
        vol.pop('group_id')
        body = {"volume": vol,
                "OS-SCH-HNT:scheduler_hints": {
                    'different_host': invalid_hints}}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(exception.ValidationError, self.controller.create,
                          req, body=body)

    @ddt.data({'size': 'a'},
              {'size': ''},
              {'size': 0},
              {'size': 2 ** 31})
    def test_volume_creation_fails_with_invalid_parameters(
            self, vol_body):
        body = {"volume": vol_body}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(exception.ValidationError, self.controller.create,
                          req, body=body)

    def test_volume_creation_fails_with_additional_properties(self):
        body = {"volume": {"size": 1, "user_id": fake.USER_ID,
                           "project_id": fake.PROJECT_ID}}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        req.api_version_request = mv.get_api_version(
            mv.SUPPORT_VOLUME_SCHEMA_CHANGES)
        self.assertRaises(exception.ValidationError, self.controller.create,
                          req, body=body)

    def test_volume_update_without_vol_data(self):
        body = {"volume": {}}
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        req.api_version_request = mv.get_api_version(
            mv.SUPPORT_VOLUME_SCHEMA_CHANGES)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, fake.VOLUME_ID, body=body)

    @ddt.data({'s': 'ea895e29-8485-4930-bbb8-c5616a309c0e'},
              ['ea895e29-8485-4930-bbb8-c5616a309c0e'],
              42)
    def test_volume_creation_fails_with_invalid_snapshot_type(self, value):
        snapshot_id = value
        vol = self._vol_in_request_body(snapshot_id=snapshot_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        # Raise 400 when snapshot has not uuid type.
        self.assertRaises(exception.ValidationError, self.controller.create,
                          req, body=body)

    @ddt.data({'source_volid': 1},
              {'source_volid': []},
              {'consistencygroup_id': 1},
              {'consistencygroup_id': []})
    def test_volume_creation_fails_with_invalid_uuids(self, updated_uuids):
        vol = self._vol_in_request_body()
        vol.update(updated_uuids)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        # Raise 400 for resource requested with invalid uuids.
        self.assertRaises(exception.ValidationError, self.controller.create,
                          req, body=body)

    @ddt.data(mv.get_prior_version(mv.RESOURCE_FILTER), mv.RESOURCE_FILTER,
              mv.LIKE_FILTER)
    @mock.patch.object(volume_api.API, 'check_volume_filters', mock.Mock())
    @mock.patch.object(api_utils, 'add_visible_admin_metadata', mock.Mock())
    @mock.patch('cinder.api.common.reject_invalid_filters')
    def test_list_volume_with_general_filter(self, version, mock_update):
        req = fakes.HTTPRequest.blank('/v3/volumes', version=version)
        self.controller.index(req)
        if version >= mv.RESOURCE_FILTER:
            support_like = True if version == mv.LIKE_FILTER else False
            mock_update.assert_called_once_with(req.environ['cinder.context'],
                                                mock.ANY, 'volume',
                                                support_like)

    @ddt.data({'admin': True, 'version': mv.VOLUME_DETAIL_PROVIDER_ID},
              {'admin': False, 'version': mv.VOLUME_DETAIL_PROVIDER_ID},
              {'admin': True,
               'version': mv.get_prior_version(mv.VOLUME_DETAIL_PROVIDER_ID)},
              {'admin': False,
               'version': mv.get_prior_version(mv.VOLUME_DETAIL_PROVIDER_ID)})
    @ddt.unpack
    def test_volume_show_provider_id(self, admin, version):
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_api_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID,
                                      version=version)
        if admin:
            admin_ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                               True)
            req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        req_version = req.api_version_request
        # provider_id is in view if min version is greater than or equal to
        # VOLUME_DETAIL_PROVIDER_ID for admin.
        if req_version.matches(mv.VOLUME_DETAIL_PROVIDER_ID, None) and admin:
            self.assertIn('provider_id', res_dict['volume'])
        else:
            self.assertNotIn('provider_id', res_dict['volume'])

    @ddt.data(*ENCRYPTION_KEY_ID_IN_DETAILS)
    @ddt.unpack
    def test_volume_show_with_encryption_key_id(self,
                                                expected_in_details,
                                                encryption_key_id,
                                                version):
        volume = test_utils.create_volume(self.ctxt,
                                          testcase_instance=self,
                                          volume_type_id=None,
                                          encryption_key_id=encryption_key_id)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % volume.id,
                                      version=version)
        volume_details = self.controller.show(req, volume.id)['volume']

        if expected_in_details:
            self.assertIn('encryption_key_id', volume_details)
        else:
            self.assertNotIn('encryption_key_id', volume_details)

    @ddt.data(
        (True, True, mv.USE_QUOTA),
        (True, False, mv.USE_QUOTA),
        (False, True, mv.get_prior_version(mv.USE_QUOTA)),
        (False, False, mv.get_prior_version(mv.USE_QUOTA)),
    )
    @ddt.unpack
    def test_volume_show_with_use_quota(self, present, value, microversion):
        volume = test_utils.create_volume(self.ctxt,
                                          volume_type_id=None,
                                          use_quota=value)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % volume.id,
                                      version=microversion)
        volume_details = self.controller.show(req, volume.id)['volume']

        if present:
            self.assertIs(value, volume_details['consumes_quota'])
        else:
            self.assertNotIn('consumes_quota', volume_details)

    def _fake_create_volume(self, size=1):
        vol = {
            'display_name': 'fake_volume1',
            'status': 'available',
            'size': size
        }
        volume = objects.Volume(context=self.ctxt, **vol)
        volume.create()
        return volume

    def _fake_create_snapshot(self, volume_id, volume_size=1):
        snap = {
            'display_name': 'fake_snapshot1',
            'status': 'available',
            'volume_id': volume_id,
            'volume_size': volume_size
        }
        snapshot = objects.Snapshot(context=self.ctxt, **snap)
        snapshot.create()
        return snapshot

    @mock.patch.object(objects.Volume, 'get_latest_snapshot')
    @mock.patch.object(volume_api.API, 'get_volume')
    def test_volume_revert_with_snapshot_not_found(self, mock_volume,
                                                   mock_latest):
        fake_volume = self._fake_create_volume()
        mock_volume.return_value = fake_volume
        mock_latest.side_effect = exception.VolumeSnapshotNotFound(
            volume_id='fake_id')
        req = fakes.HTTPRequest.blank('/v3/volumes/fake_id/revert')
        req.headers = mv.get_mv_header(mv.VOLUME_REVERT)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_REVERT)

        body = {'revert': {'snapshot_id': 'fake_snapshot_id'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.revert,
                          req, 'fake_id', body=body)

    @mock.patch.object(objects.Volume, 'get_latest_snapshot')
    @mock.patch.object(volume_api.API, 'get_volume')
    def test_volume_revert_with_snapshot_not_match(self, mock_volume,
                                                   mock_latest):
        fake_volume = self._fake_create_volume()
        mock_volume.return_value = fake_volume
        fake_snapshot = self._fake_create_snapshot(fake.UUID1)
        mock_latest.return_value = fake_snapshot
        req = fakes.HTTPRequest.blank('/v3/volumes/fake_id/revert')
        req.headers = mv.get_mv_header(mv.VOLUME_REVERT)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_REVERT)

        body = {'revert': {'snapshot_id': 'fake_snapshot_id'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.revert,
                          req, 'fake_id', body=body)

    @mock.patch.object(objects.Volume, 'get_latest_snapshot')
    @mock.patch('cinder.objects.base.'
                'CinderPersistentObject.update_single_status_where')
    @mock.patch.object(volume_api.API, 'get_volume')
    def test_volume_revert_update_status_failed(self,
                                                mock_volume,
                                                mock_update,
                                                mock_latest):
        fake_volume = self._fake_create_volume()
        fake_snapshot = self._fake_create_snapshot(fake_volume['id'])
        mock_volume.return_value = fake_volume
        mock_latest.return_value = fake_snapshot
        req = fakes.HTTPRequest.blank('/v3/volumes/%s/revert'
                                      % fake_volume['id'])
        req.headers = mv.get_mv_header(mv.VOLUME_REVERT)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_REVERT)
        req.environ['cinder.context'] = self.ctxt
        # update volume's status failed
        mock_update.side_effect = [False, True]

        body = {'revert': {'snapshot_id': fake_snapshot['id']}}
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.revert,
                          req,
                          fake_volume['id'],
                          body=body)

        # update snapshot's status failed
        mock_update.side_effect = [True, False]

        body = {'revert': {'snapshot_id': fake_snapshot['id']}}
        self.assertRaises(webob.exc.HTTPConflict, self.controller.revert,
                          req, fake_volume['id'], body=body)

    @mock.patch.object(objects.Volume, 'get_latest_snapshot')
    @mock.patch.object(volume_api.API, 'get_volume')
    def test_volume_revert_with_not_equal_size(self, mock_volume,
                                               mock_latest):
        fake_volume = self._fake_create_volume(size=2)
        fake_snapshot = self._fake_create_snapshot(fake_volume['id'],
                                                   volume_size=1)
        mock_volume.return_value = fake_volume
        mock_latest.return_value = fake_snapshot
        req = fakes.HTTPRequest.blank('/v3/volumes/%s/revert'
                                      % fake_volume['id'])
        req.headers = mv.get_mv_header(mv.VOLUME_REVERT)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_REVERT)
        body = {'revert': {'snapshot_id': fake_snapshot['id']}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.revert,
                          req, fake_volume['id'],
                          body=body)

    def test_view_get_attachments(self):
        req = fakes.HTTPRequest.blank('/v3/volumes')
        context = req.environ['cinder.context']
        fake_volume = self._fake_create_volume()
        fake_volume['attach_status'] = fields.VolumeAttachStatus.ATTACHING
        att_time = datetime.datetime(2017, 8, 31, 21, 55, 7,
                                     tzinfo=iso8601.UTC)
        a1 = {
            'id': fake.UUID1,
            'volume_id': fake.UUID2,
            'instance': None,
            'attached_host': None,
            'mountpoint': None,
            'attach_time': None,
            'attach_status': fields.VolumeAttachStatus.ATTACHING
        }
        a2 = {
            'id': fake.UUID3,
            'volume_id': fake.UUID4,
            'instance_uuid': fake.UUID5,
            'attached_host': 'host1',
            'mountpoint': 'na',
            'attach_time': att_time,
            'attach_status': fields.VolumeAttachStatus.ATTACHED
        }
        attachment1 = objects.VolumeAttachment(self.ctxt, **a1)
        attachment2 = objects.VolumeAttachment(self.ctxt, **a2)
        atts = {'objects': [attachment1, attachment2]}
        attachments = objects.VolumeAttachmentList(self.ctxt, **atts)

        fake_volume['volume_attachment'] = attachments

        # get_attachments should only return attachments with the
        # attached status = ATTACHED
        context.is_admin = True
        attachments = view.ViewBuilder()._get_attachments(fake_volume, context)

        self.assertEqual(1, len(attachments))
        self.assertEqual(fake.UUID3, attachments[0]['attachment_id'])
        self.assertEqual(fake.UUID4, attachments[0]['volume_id'])
        self.assertEqual(fake.UUID5, attachments[0]['server_id'])
        self.assertEqual('host1', attachments[0]['host_name'])
        self.assertEqual('na', attachments[0]['device'])
        self.assertEqual(att_time, attachments[0]['attached_at'])

        # When admin context is false (non-admin), host_name will be None
        context.is_admin = False
        attachments = view.ViewBuilder()._get_attachments(fake_volume, context)
        self.assertIsNone(attachments[0]['host_name'])

        # When the request is coming from another service (glance),
        # We should be able to see 'host_name'
        context.roles.append('service')
        attachments = view.ViewBuilder()._get_attachments(fake_volume, context)
        self.assertEqual('host1', attachments[0]['host_name'])

    @ddt.data(('created_at=gt:', 0), ('created_at=lt:', 2))
    @ddt.unpack
    def test_volume_index_filter_by_created_at_with_gt_and_lt(self, change,
                                                              expect_result):
        self._create_volume_with_glance_metadata()
        change_time = timeutils.utcnow() + datetime.timedelta(minutes=1)
        req = fakes.HTTPRequest.blank(("/v3/volumes?%s%s") %
                                      (change, change_time))
        req.environ['cinder.context'] = self.ctxt
        req.headers = mv.get_mv_header(mv.VOLUME_TIME_COMPARISON_FILTER)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_TIME_COMPARISON_FILTER)
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(expect_result, len(volumes))

    @ddt.data(('updated_at=gt:', 0), ('updated_at=lt:', 1))
    @ddt.unpack
    def test_vol_filter_by_updated_at_with_gt_and_lt(self, change, result):
        vols = self._create_volume_with_glance_metadata()
        change_time = vols[1].updated_at
        req = fakes.HTTPRequest.blank(("/v3/volumes?%s%s") %
                                      (change, change_time))
        req.environ['cinder.context'] = self.ctxt
        req.headers = mv.get_mv_header(mv.VOLUME_TIME_COMPARISON_FILTER)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_TIME_COMPARISON_FILTER)
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(result, len(volumes))

    @ddt.data(('updated_at=eq:', 1, fake.VOLUME2_ID),
              ('updated_at=neq:', 1, fake.VOLUME_ID))
    @ddt.unpack
    def test_vol_filter_by_updated_at_with_eq_and_neq(self, change, result,
                                                      expected_volume_id):
        vols = self._create_volume_with_glance_metadata()
        change_time = vols[1].updated_at
        req = fakes.HTTPRequest.blank(("/v3/volumes?%s%s") %
                                      (change, change_time))
        req.environ['cinder.context'] = self.ctxt
        req.headers = mv.get_mv_header(mv.VOLUME_TIME_COMPARISON_FILTER)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_TIME_COMPARISON_FILTER)
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(result, len(volumes))
        self.assertEqual(expected_volume_id, volumes[0]['id'])

    @ddt.data('created_at', 'updated_at')
    def test_volume_filter_by_time_with_invaild_time(self, change):
        self._create_volume_with_glance_metadata()
        change_time = '123'
        req = fakes.HTTPRequest.blank(("/v3/volumes?%s=%s") %
                                      (change, change_time))
        req.environ['cinder.context'] = self.ctxt
        req.headers = mv.get_mv_header(mv.VOLUME_TIME_COMPARISON_FILTER)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_TIME_COMPARISON_FILTER)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index, req)

    def test_volume_index_filter_by_time_with_lte_and_gte(self):
        vols = self._create_volume_with_glance_metadata()
        change_since = vols[1].updated_at
        change_before = timeutils.utcnow() + datetime.timedelta(minutes=1)
        req = fakes.HTTPRequest.blank(("/v3/volumes?updated_at=lte:%s&"
                                       "updated_at=gte:%s") %
                                      (change_before, change_since))
        req.environ['cinder.context'] = self.ctxt
        req.headers = mv.get_mv_header(mv.VOLUME_TIME_COMPARISON_FILTER)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_TIME_COMPARISON_FILTER)
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(vols[1].id, volumes[0]['id'])

    def test_create_volume_with_multiattach_param(self):
        """Tests creating a volume with multiattach=True but no multiattach

        volume type.

        This test verifies that providing the multiattach parameter will error
        out the request since it is removed and the recommended way is to
        create a multiattach volume using a multiattach volume type.
        """
        req = fakes.HTTPRequest.blank('/v3/volumes')

        body = {'volume': {
                'name': 'test name',
                'description': 'test desc',
                'size': 1,
                'multiattach': True}}
        exc = self.assertRaises(webob.exc.HTTPBadRequest,
                                self.controller.create,
                                req, body=body)
        self.assertIn("multiattach parameter has been removed",
                      exc.explanation)


@ddt.ddt
class VolumeApiTestNoMicroversion(BaseVolumeTest):

    def setUp(self):
        super().setUp()

        self.mock_object(objects.VolumeType, 'get_by_id',
                         self.fake_volume_type_get)
        self.mock_object(view.ViewBuilder, '_get_volume_type',
                         v3_fakes.fake_volume_type_name_get)

    def fake_volume_type_get(self, context, id, *args, **kwargs):
        return {'id': id,
                'name': 'vol_type_name',
                'description': 'A fake volume type',
                'is_public': True,
                'projects': [],
                'extra_specs': {},
                'created_at': None,
                'deleted_at': None,
                'updated_at': None,
                'qos_specs_id': fake.QOS_SPEC_ID,
                'deleted': False}

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create(self, mock_validate):
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_get)
        self.mock_object(volume_api.API, "create",
                         v3_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        vol = self._vol_in_request_body()
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        res_dict = self.controller.create(req, body=body)
        ex = self._expected_vol_from_controller()
        self.assertEqual(ex, res_dict)
        self.assertTrue(mock_validate.called)

    @mock.patch.object(db, 'volume_get_all', v3_fakes.fake_volume_get_all)
    @mock.patch.object(db, 'service_get_all',
                       return_value=v3_fakes.fake_service_get_all_by_topic(
                           None, None),
                       autospec=True)
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create_with_type(self, mock_validate, mock_service_get):
        db_vol_type = db.volume_type_get_by_name(context.get_admin_context(),
                                                 '__DEFAULT__')

        vol = self._vol_in_request_body(volume_type="FakeTypeName")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        # Raise 404 when type name isn't valid
        self.assertRaises(exception.VolumeTypeNotFoundByName,
                          self.controller.create, req, body=body)

        # Use correct volume type name
        vol = self._vol_in_request_body(volume_type=CONF.default_volume_type)
        body.update(dict(volume=vol))
        res_dict = self.controller.create(req, body=body)
        volume_id = res_dict['volume']['id']
        self.assertEqual(1, len(res_dict))

        # Use correct volume type id
        vol = self._vol_in_request_body(volume_type=db_vol_type['id'])
        body.update(dict(volume=vol))
        res_dict = self.controller.create(req, body=body)
        volume_id = res_dict['volume']['id']
        self.assertEqual(1, len(res_dict))

        vol_db = v3_fakes.create_volume(
            volume_id,
            volume_type={'name': db_vol_type['name']})
        vol_obj = fake_volume.fake_volume_obj(context.get_admin_context(),
                                              **vol_db)
        self.mock_object(volume_api.API, 'get_all',
                         return_value=objects.VolumeList(objects=[vol_obj]))
        # NOTE(geguileo): This is required because common get_by_id method in
        # cinder.db.sqlalchemy.api caches the real get method.
        db.sqlalchemy.api._GET_METHODS = {}
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)
        req = fakes.HTTPRequest.blank('/v3/volumes/detail')
        res_dict = self.controller.detail(req)
        self.assertTrue(mock_validate.called)

    @classmethod
    def _vol_in_request_body(cls,
                             size=v3_fakes.DEFAULT_VOL_SIZE,
                             name=v3_fakes.DEFAULT_VOL_NAME,
                             description=v3_fakes.DEFAULT_VOL_DESCRIPTION,
                             availability_zone=DEFAULT_AZ,
                             snapshot_id=None,
                             source_volid=None,
                             consistencygroup_id=None,
                             volume_type=None,
                             image_ref=None,
                             image_id=None):
        vol = {"size": size,
               "name": name,
               "description": description,
               "availability_zone": availability_zone,
               "snapshot_id": snapshot_id,
               "source_volid": source_volid,
               "consistencygroup_id": consistencygroup_id,
               "volume_type": volume_type,
               }

        if image_id is not None:
            vol['image_id'] = image_id
        elif image_ref is not None:
            vol['imageRef'] = image_ref

        return vol

    def _expected_vol_from_controller(
            self,
            size=v3_fakes.DEFAULT_VOL_SIZE,
            availability_zone=DEFAULT_AZ,
            description=v3_fakes.DEFAULT_VOL_DESCRIPTION,
            name=v3_fakes.DEFAULT_VOL_NAME,
            consistencygroup_id=None,
            source_volid=None,
            snapshot_id=None,
            metadata=None,
            attachments=None,
            volume_type=v3_fakes.DEFAULT_VOL_TYPE,
            status=v3_fakes.DEFAULT_VOL_STATUS,
            with_migration_status=False,
            multiattach=False):
        metadata = metadata or {}
        attachments = attachments or []
        volume = {'volume':
                  {'attachments': attachments,
                   'availability_zone': availability_zone,
                   'bootable': 'false',
                   'consistencygroup_id': consistencygroup_id,
                   'created_at': datetime.datetime(
                       1900, 1, 1, 1, 1, 1, tzinfo=iso8601.UTC),
                   'updated_at': datetime.datetime(
                       1900, 1, 1, 1, 1, 1, tzinfo=iso8601.UTC),
                   'description': description,
                   'id': v3_fakes.DEFAULT_VOL_ID,
                   'links':
                   [{'href': 'http://localhost/v3/volumes/%s' % (
                             fake.VOLUME_ID),
                     'rel': 'self'},
                    {'href': 'http://localhost/volumes/%s' % (
                             fake.VOLUME_ID),
                     'rel': 'bookmark'}],
                   'metadata': metadata,
                   'name': name,
                   'replication_status': 'disabled',
                   'multiattach': multiattach,
                   'size': size,
                   'snapshot_id': snapshot_id,
                   'source_volid': source_volid,
                   'status': status,
                   'user_id': fake.USER_ID,
                   'volume_type': volume_type,
                   'encrypted': False}}

        if with_migration_status:
            volume['volume']['migration_status'] = None

        return volume

    def _expected_volume_api_create_kwargs(self, snapshot=None,
                                           availability_zone=DEFAULT_AZ,
                                           source_volume=None):
        return {'metadata': None,
                'snapshot': snapshot,
                'source_volume': source_volume,
                'group': None,
                'consistencygroup': None,
                'availability_zone': availability_zone,
                'scheduler_hints': None,
                }

    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get_full',
                       autospec=True)
    @mock.patch.object(volume_api.API, 'get_snapshot', autospec=True)
    @mock.patch.object(volume_api.API, 'create', autospec=True)
    def test_volume_creation_from_snapshot(self, create, get_snapshot,
                                           volume_type_get):
        create.side_effect = v3_fakes.fake_volume_api_create
        get_snapshot.side_effect = v3_fakes.fake_snapshot_get
        volume_type_get.side_effect = v3_fakes.fake_volume_type_get

        snapshot_id = fake.SNAPSHOT_ID
        vol = self._vol_in_request_body(snapshot_id=snapshot_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        res_dict = self.controller.create(req, body=body)

        ex = self._expected_vol_from_controller(snapshot_id=snapshot_id)
        self.assertEqual(ex, res_dict)

        context = req.environ['cinder.context']
        get_snapshot.assert_called_once_with(self.controller.volume_api,
                                             context, snapshot_id)

        kwargs = self._expected_volume_api_create_kwargs(
            v3_fakes.fake_snapshot(snapshot_id))
        create.assert_called_once_with(
            self.controller.volume_api, context,
            vol['size'], v3_fakes.DEFAULT_VOL_NAME,
            v3_fakes.DEFAULT_VOL_DESCRIPTION,
            **kwargs)

    @mock.patch.object(volume_api.API, 'get_snapshot', autospec=True)
    def test_volume_creation_fails_with_invalid_snapshot(self, get_snapshot):

        get_snapshot.side_effect = v3_fakes.fake_snapshot_get

        snapshot_id = fake.WILL_NOT_BE_FOUND_ID
        vol = self._vol_in_request_body(snapshot_id=snapshot_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        # Raise 404 when snapshot cannot be found.
        self.assertRaises(exception.SnapshotNotFound, self.controller.create,
                          req, body=body)
        context = req.environ['cinder.context']
        get_snapshot.assert_called_once_with(self.controller.volume_api,
                                             context, snapshot_id)

    @ddt.data({'s': 'ea895e29-8485-4930-bbb8-c5616a309c0e'},
              ['ea895e29-8485-4930-bbb8-c5616a309c0e'],
              42)
    def test_volume_creation_fails_with_invalid_snapshot_type(self, value):
        snapshot_id = value
        vol = self._vol_in_request_body(snapshot_id=snapshot_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        # Raise 400 when snapshot has not uuid type.
        self.assertRaises(exception.ValidationError, self.controller.create,
                          req, body=body)

    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get_full',
                       autospec=True)
    @mock.patch.object(volume_api.API, 'get_volume', autospec=True)
    @mock.patch.object(volume_api.API, 'create', autospec=True)
    def test_volume_creation_from_source_volume(self, create, get_volume,
                                                volume_type_get):
        get_volume.side_effect = v3_fakes.fake_volume_api_get
        create.side_effect = v3_fakes.fake_volume_api_create
        volume_type_get.side_effect = v3_fakes.fake_volume_type_get

        source_volid = '2f49aa3a-6aae-488d-8b99-a43271605af6'
        vol = self._vol_in_request_body(source_volid=source_volid)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        res_dict = self.controller.create(req, body=body)

        ex = self._expected_vol_from_controller(source_volid=source_volid)
        self.assertEqual(ex, res_dict)

        context = req.environ['cinder.context']
        get_volume.assert_called_once_with(self.controller.volume_api,
                                           context, source_volid)

        db_vol = v3_fakes.create_volume(source_volid)
        vol_obj = fake_volume.fake_volume_obj(context, **db_vol)
        kwargs = self._expected_volume_api_create_kwargs(
            source_volume=vol_obj)
        create.assert_called_once_with(
            self.controller.volume_api, context,
            vol['size'], v3_fakes.DEFAULT_VOL_NAME,
            v3_fakes.DEFAULT_VOL_DESCRIPTION,
            **kwargs)

    @mock.patch.object(volume_api.API, 'get_volume', autospec=True)
    def test_volume_creation_fails_with_invalid_source_volume(self,
                                                              get_volume):

        get_volume.side_effect = v3_fakes.fake_volume_get_notfound

        source_volid = fake.VOLUME_ID
        vol = self._vol_in_request_body(source_volid=source_volid)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        # Raise 404 when source volume cannot be found.
        self.assertRaises(exception.VolumeNotFound, self.controller.create,
                          req, body=body)

        context = req.environ['cinder.context']
        get_volume.assert_called_once_with(self.controller.volume_api,
                                           context, source_volid)

    @ddt.data({'source_volid': 1},
              {'source_volid': []},
              {'consistencygroup_id': 1},
              {'consistencygroup_id': []})
    def test_volume_creation_fails_with_invalid_uuids(self, updated_uuids):
        vol = self._vol_in_request_body()
        vol.update(updated_uuids)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        # Raise 400 for resource requested with invalid uuids.
        self.assertRaises(exception.ValidationError, self.controller.create,
                          req, body=body)

    @mock.patch.object(group_api.API, 'get', autospec=True)
    def test_volume_creation_fails_with_invalid_consistency_group(self,
                                                                  get_cg):

        get_cg.side_effect = v3_fakes.fake_consistencygroup_get_notfound

        consistencygroup_id = '4f49aa3a-6aae-488d-8b99-a43271605af6'
        vol = self._vol_in_request_body(
            consistencygroup_id=consistencygroup_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        # Raise 404 when consistency group is not found.
        self.assertRaises(exception.GroupNotFound,
                          self.controller.create, req, body=body)

        context = req.environ['cinder.context']
        get_cg.assert_called_once_with(self.controller.group_api,
                                       context, consistencygroup_id)

    def test_volume_creation_fails_with_bad_size(self):
        vol = self._vol_in_request_body(size="")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          req,
                          body=body)

    def test_volume_creation_fails_with_bad_availability_zone(self):
        vol = self._vol_in_request_body(availability_zone="zonen:hostn")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(exception.InvalidAvailabilityZone,
                          self.controller.create,
                          req, body=body)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create_with_image_ref(self, mock_validate):
        self.mock_object(volume_api.API, "create",
                         v3_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        vol = self._vol_in_request_body(
            availability_zone="nova",
            image_ref="c905cedb-7281-47e4-8a62-f26bc5fc4c77")
        ex = self._expected_vol_from_controller(availability_zone="nova")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        res_dict = self.controller.create(req, body=body)
        self.assertEqual(ex, res_dict)
        self.assertTrue(mock_validate.called)

    def test_volume_create_with_image_ref_is_integer(self):
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_ref=1234)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          req,
                          body=body)

    def test_volume_create_with_image_ref_not_uuid_format(self):
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)
        self.mock_object(fake_image._FakeImageService,
                         "detail",
                         v3_fakes.fake_image_service_detail)
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_ref="12345")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    def test_volume_create_with_image_ref_with_empty_string(self):
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)
        self.mock_object(fake_image._FakeImageService,
                         "detail",
                         v3_fakes.fake_image_service_detail)
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_ref="")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create_with_image_id(self, mock_validate):
        self.mock_object(volume_api.API, "create",
                         v3_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        vol = self._vol_in_request_body(
            availability_zone="nova",
            image_id="c905cedb-7281-47e4-8a62-f26bc5fc4c77")
        ex = self._expected_vol_from_controller(availability_zone="nova")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        res_dict = self.controller.create(req, body=body)
        self.assertEqual(ex, res_dict)
        self.assertTrue(mock_validate.called)

    def test_volume_create_with_image_id_is_integer(self):
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_id=1234)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          req,
                          body=body)

    def test_volume_create_with_image_id_not_uuid_format(self):
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)
        self.mock_object(fake_image._FakeImageService,
                         "detail",
                         v3_fakes.fake_image_service_detail)
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_id="12345")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    def test_volume_create_with_image_id_with_empty_string(self):
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)
        self.mock_object(fake_image._FakeImageService,
                         "detail",
                         v3_fakes.fake_image_service_detail)
        vol = self._vol_in_request_body(availability_zone="cinder",
                                        image_id="")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create_with_image_name(self, mock_validate):
        self.mock_object(volume_api.API, "create",
                         v3_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)
        self.mock_object(fake_image._FakeImageService,
                         "detail",
                         v3_fakes.fake_image_service_detail)

        test_id = "Fedora-x86_64-20-20140618-sda"
        vol = self._vol_in_request_body(availability_zone="nova",
                                        image_ref=test_id)
        ex = self._expected_vol_from_controller(availability_zone="nova")
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        res_dict = self.controller.create(req, body=body)
        self.assertEqual(ex, res_dict)

    def test_volume_create_with_image_name_has_multiple(self):
        self.mock_object(db, 'volume_get', v3_fakes.fake_volume_get_db)
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)
        self.mock_object(fake_image._FakeImageService,
                         "detail",
                         v3_fakes.fake_image_service_detail)

        test_id = "multi"
        vol = self._vol_in_request_body(availability_zone="nova",
                                        image_ref=test_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.create,
                          req,
                          body=body)

    def test_volume_create_with_image_name_no_match(self):
        self.mock_object(db, 'volume_get', v3_fakes.fake_volume_get_db)
        self.mock_object(volume_api.API, "create", v3_fakes.fake_volume_create)
        self.mock_object(fake_image._FakeImageService,
                         "detail",
                         v3_fakes.fake_image_service_detail)

        test_id = "MissingName"
        vol = self._vol_in_request_body(availability_zone="nova",
                                        image_ref=test_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    @ddt.data({'a' * 256: 'a'},
              {'a': 'a' * 256},
              {'': 'a'},
              {'a': None})
    def test_volume_create_with_invalid_metadata(self, value):
        vol = self._vol_in_request_body()
        vol['metadata'] = value
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')

        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          req,
                          body=body)

    @ddt.data({"name": "Updated Test Name",
               "description": "Updated Test Description"},
              {"name": "      test name   ",
               "description": "    test description   "})
    def test_volume_update(self, body):
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_api_get)
        self.mock_object(volume_api.API, "update", v3_fakes.fake_volume_update)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)
        updates = {
            "name": body['name'],
            "description": body['description']
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertEqual(0, len(self.notifier.notifications))
        name = updates["name"].strip()
        description = updates["description"].strip()
        expected = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ, name=name,
            description=description,
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        res_dict = self.controller.update(req, fake.VOLUME_ID, body=body)
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_update_deprecation(self, mock_validate):
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_api_get)
        self.mock_object(volume_api.API, "update", v3_fakes.fake_volume_update)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        updates = {
            "display_name": "Updated Test Name",
            "display_description": "Updated Test Description",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, fake.VOLUME_ID, body=body)
        expected = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ, name="Updated Test Name",
            description="Updated Test Description",
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_update_deprecation_key_priority(self, mock_validate):
        """Test current update keys have priority over deprecated keys."""
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_api_get)
        self.mock_object(volume_api.API, "update", v3_fakes.fake_volume_update)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        updates = {
            "name": "New Name",
            "description": "New Description",
            "display_name": "Not Shown Name",
            "display_description": "Not Shown Description",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, fake.VOLUME_ID, body=body)
        expected = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ,
            name="New Name", description="New Description",
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_update_metadata(self, mock_validate):
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_api_get)
        self.mock_object(volume_api.API, "update", v3_fakes.fake_volume_update)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        updates = {
            "metadata": {"qos_max_iops": '2000'}
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertEqual(0, len(self.notifier.notifications))
        res_dict = self.controller.update(req, fake.VOLUME_ID, body=body)
        expected = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ,
            metadata={'attached_mode': 'rw', 'readonly': 'False',
                      'qos_max_iops': '2000'})
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_update_with_admin_metadata(self, mock_validate):
        self.mock_object(volume_api.API, "update", v3_fakes.fake_volume_update)

        volume = v3_fakes.create_volume(fake.VOLUME_ID)
        del volume['name']
        del volume['volume_type']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)

        db.volume_admin_metadata_update(context.get_admin_context(),
                                        fake.VOLUME_ID,
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)
        values = {'volume_id': fake.VOLUME_ID, }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], fake.INSTANCE_ID, None, '/')
        attach_tmp = db.volume_attachment_get(context.get_admin_context(),
                                              attachment['id'])
        volume_tmp = db.volume_get(context.get_admin_context(), fake.VOLUME_ID)
        updates = {
            "name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertEqual(0, len(self.notifier.notifications))
        admin_ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.update(req, fake.VOLUME_ID, body=body)
        expected = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ,
            status='in-use', name='Updated Test Name',
            attachments=[{'id': fake.VOLUME_ID,
                          'attachment_id': attachment['id'],
                          'volume_id': v3_fakes.DEFAULT_VOL_ID,
                          'server_id': fake.INSTANCE_ID,
                          'host_name': None,
                          'device': '/',
                          'attached_at': attach_tmp['attach_time'].replace(
                              tzinfo=iso8601.UTC),
                          }],
            volume_type=fake.VOLUME_TYPE_NAME,
            metadata={'key': 'value', 'readonly': 'True'},
            with_migration_status=True)
        expected['volume']['updated_at'] = volume_tmp['updated_at'].replace(
            tzinfo=iso8601.UTC)
        self.assertEqual(expected, res_dict)
        self.assertEqual(2, len(self.notifier.notifications))
        self.assertTrue(mock_validate.called)

    @ddt.data({'a' * 256: 'a'},
              {'a': 'a' * 256},
              {'': 'a'},
              {'a': None})
    @mock.patch.object(volume_api.API, 'get',
                       side_effect=v3_fakes.fake_volume_api_get, autospec=True)
    def test_volume_update_with_invalid_metadata(self, value, get):
        updates = {
            "metadata": value
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)

        self.assertRaises(exception.ValidationError,
                          self.controller.update,
                          req, fake.VOLUME_ID, body=body)

    def test_update_empty_body(self):
        body = {}
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertRaises(exception.ValidationError,
                          self.controller.update,
                          req, fake.VOLUME_ID, body=body)

    def test_update_invalid_body(self):
        body = {
            'name': 'missing top level volume key'
        }
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertRaises(exception.ValidationError,
                          self.controller.update,
                          req, fake.VOLUME_ID, body=body)

    @ddt.data({'name': 'a' * 256},
              {'description': 'a' * 256},
              {'display_name': 'a' * 256},
              {'display_description': 'a' * 256})
    def test_update_exceeds_length_name_description(self, vol):
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        body = {'volume': vol}
        self.assertRaises(exception.InvalidInput,
                          self.controller.update,
                          req, fake.VOLUME_ID, body=body)

    def test_update_not_found(self):
        self.mock_object(volume_api.API, "get",
                         v3_fakes.fake_volume_get_notfound)
        updates = {
            "name": "Updated Test Name",
        }
        body = {"volume": updates}
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertRaises(exception.VolumeNotFound,
                          self.controller.update,
                          req, fake.VOLUME_ID, body=body)

    def test_volume_list_summary(self):
        self.mock_object(volume_api.API, 'get_all',
                         v3_fakes.fake_volume_api_get_all_by_project)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/%s/volumes' % fake.PROJECT_ID)
        res_dict = self.controller.index(req)
        expected = {
            'volumes': [
                {
                    'name': v3_fakes.DEFAULT_VOL_NAME,
                    'id': fake.VOLUME_ID,
                    'links': [
                        {
                            'href': 'http://localhost/v3/%s/volumes/%s' % (
                                    fake.PROJECT_ID, fake.VOLUME_ID),
                            'rel': 'self'
                        },
                        {
                            'href': 'http://localhost/%s/volumes/%s' % (
                                    fake.PROJECT_ID, fake.VOLUME_ID),
                            'rel': 'bookmark'
                        }
                    ],
                }
            ]
        }
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volumes
        self.assertEqual(1, len(req.cached_resource()))

    def test_volume_list_detail(self):
        self.mock_object(volume_api.API, 'get_all',
                         v3_fakes.fake_volume_api_get_all_by_project)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/detail')
        res_dict = self.controller.detail(req)
        exp_vol = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ,
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        expected = {'volumes': [exp_vol['volume']]}
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volumes
        self.assertEqual(1, len(req.cached_resource()))

    def test_volume_list_detail_with_admin_metadata(self):
        volume = v3_fakes.create_volume(fake.VOLUME_ID)
        del volume['name']
        del volume['volume_type']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)
        db.volume_admin_metadata_update(context.get_admin_context(),
                                        fake.VOLUME_ID,
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)
        values = {'volume_id': fake.VOLUME_ID, }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], fake.INSTANCE_ID, None, '/')
        attach_tmp = db.volume_attachment_get(context.get_admin_context(),
                                              attachment['id'])
        volume_tmp = db.volume_get(context.get_admin_context(), fake.VOLUME_ID)

        req = fakes.HTTPRequest.blank('/v3/volumes/detail')
        admin_ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.detail(req)
        exp_vol = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ,
            status="in-use", volume_type=fake.VOLUME_TYPE_NAME,
            attachments=[{'attachment_id': attachment['id'],
                          'device': '/',
                          'server_id': fake.INSTANCE_ID,
                          'host_name': None,
                          'id': fake.VOLUME_ID,
                          'volume_id': v3_fakes.DEFAULT_VOL_ID,
                          'attached_at': attach_tmp['attach_time'].replace(
                              tzinfo=iso8601.UTC),
                          }],
            metadata={'key': 'value', 'readonly': 'True'},
            with_migration_status=True)
        exp_vol['volume']['updated_at'] = volume_tmp['updated_at'].replace(
            tzinfo=iso8601.UTC)
        expected = {'volumes': [exp_vol['volume']]}
        self.assertEqual(expected, res_dict)

    def test_volume_list_detail_host_name_admin_non_admin(self):
        fake_host = 'fake_host'
        volume = v3_fakes.create_volume(fake.VOLUME_ID)
        del volume['name']
        del volume['volume_type']
        db.volume_create(context.get_admin_context(), volume)
        values = {'volume_id': fake.VOLUME_ID, }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], fake.INSTANCE_ID, fake_host, '/')
        db.volume_attachment_get(context.get_admin_context(),
                                 attachment['id'])

        req = fakes.HTTPRequest.blank('/v3/volumes/detail')
        res_dict = self.controller.detail(req)
        # host_name will always be None for non-admins
        self.assertIsNone(
            res_dict['volumes'][0]['attachments'][0]['host_name'])

        admin_ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.detail(req)
        # correct host_name is returned for admins
        self.assertEqual(fake_host,
                         res_dict['volumes'][0]['attachments'][0]['host_name']
                         )

    def test_volume_index_with_marker(self):
        def fake_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_keys=None, sort_dirs=None,
                                           filters=None,
                                           viewable_admin_meta=False,
                                           offset=0):
            return [
                v3_fakes.create_volume(fake.VOLUME_ID, display_name='vol1'),
                v3_fakes.create_volume(fake.VOLUME2_ID, display_name='vol2'),
            ]
        self.mock_object(db, 'volume_get_all_by_project',
                         fake_volume_get_all_by_project)
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_get)

        req = fakes.HTTPRequest.blank('/v3/volumes?marker=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(2, len(volumes))
        self.assertEqual(fake.VOLUME_ID, volumes[0]['id'])
        self.assertEqual(fake.VOLUME2_ID, volumes[1]['id'])

    def test_volume_index_limit(self):
        self.mock_object(db, 'volume_get_all_by_project',
                         v3_fakes.fake_volume_get_all_by_project)
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_get)

        req = fakes.HTTPRequest.blank('/v3/%s/volumes'
                                      '?limit=1&name=foo'
                                      '&sort=id1:asc' % fake.PROJECT_ID)
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))

        # Ensure that the next link is correctly formatted, it should
        # contain the same limit, filter, and sort information as the
        # original request as well as a marker; this ensures that the
        # caller can simply use the "next" link and that they do not
        # need to manually insert the limit and sort information.
        links = res_dict['volumes_links']
        self.assertEqual('next', links[0]['rel'])
        href_parts = urllib.parse.urlparse(links[0]['href'])
        self.assertEqual('/v3/%s/volumes' % fake.PROJECT_ID, href_parts.path)
        params = urllib.parse.parse_qs(href_parts.query)
        self.assertEqual(str(volumes[0]['id']), params['marker'][0])
        self.assertEqual('1', params['limit'][0])
        self.assertEqual('foo', params['name'][0])
        self.assertEqual('id1:asc', params['sort'][0])

    def test_volume_index_limit_negative(self):
        req = fakes.HTTPRequest.blank('/v3/volumes?limit=-1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

    def test_volume_index_limit_non_int(self):
        req = fakes.HTTPRequest.blank('/v3/volumes?limit=a')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

    def test_volume_index_limit_marker(self):
        self.mock_object(db, 'volume_get_all_by_project',
                         v3_fakes.fake_volume_get_all_by_project)
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_get)

        req = fakes.HTTPRequest.blank('/v3/volumes?marker=1&limit=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(fake.VOLUME_ID, volumes[0]['id'])

    def _create_db_volumes(self, num_volumes):
        volumes = [
            test_utils.create_volume(self.ctxt, display_name='vol%s' % i)
            for i in range(num_volumes)
        ]
        for vol in volumes:
            self.addCleanup(db.volume_destroy, self.ctxt, vol.id)
        volumes.reverse()
        return volumes

    def test_volume_index_limit_offset(self):
        created_volumes = self._create_db_volumes(2)
        req = fakes.HTTPRequest.blank('/v3/volumes?limit=2&offset=1')
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(created_volumes[1].id, volumes[0]['id'])

        req = fakes.HTTPRequest.blank('/v3/volumes?limit=-1&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        req = fakes.HTTPRequest.blank('/v3/volumes?limit=a&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

        # Test that we get an exception HTTPBadRequest(400) with an offset
        # greater than the maximum offset value.
        url = '/v3/volumes?limit=2&offset=43543564546567575'
        req = fakes.HTTPRequest.blank(url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index,
                          req)

    def test_volume_detail_with_marker(self):
        def fake_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_keys=None, sort_dirs=None,
                                           filters=None,
                                           viewable_admin_meta=False,
                                           offset=0):
            return [
                v3_fakes.create_volume(fake.VOLUME_ID, display_name='vol1'),
                v3_fakes.create_volume(fake.VOLUME2_ID, display_name='vol2'),
            ]
        self.mock_object(db, 'volume_get_all_by_project',
                         fake_volume_get_all_by_project)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/detail?marker=1')
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(2, len(volumes))
        self.assertEqual(fake.VOLUME_ID, volumes[0]['id'])
        self.assertEqual(fake.VOLUME2_ID, volumes[1]['id'])

    def test_volume_detail_limit(self):
        self.mock_object(db, 'volume_get_all_by_project',
                         v3_fakes.fake_volume_get_all_by_project)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)
        req = fakes.HTTPRequest.blank('/v3/%s/volumes/detail?limit=1'
                                      % fake.PROJECT_ID)
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))

        # Ensure that the next link is correctly formatted
        links = res_dict['volumes_links']
        self.assertEqual('next', links[0]['rel'])
        href_parts = urllib.parse.urlparse(links[0]['href'])
        self.assertEqual('/v3/%s/volumes/detail' % fake.PROJECT_ID,
                         href_parts.path)
        params = urllib.parse.parse_qs(href_parts.query)
        self.assertIn('marker', params)
        self.assertEqual('1', params['limit'][0])

    def test_volume_detail_limit_negative(self):
        req = fakes.HTTPRequest.blank('/v3/volumes/detail?limit=-1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail,
                          req)

    def test_volume_detail_limit_non_int(self):
        req = fakes.HTTPRequest.blank('/v3/volumes/detail?limit=a')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail,
                          req)

    def test_volume_detail_limit_marker(self):
        self.mock_object(db, 'volume_get_all_by_project',
                         v3_fakes.fake_volume_get_all_by_project)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/detail?marker=1&limit=1')
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(fake.VOLUME_ID, volumes[0]['id'])

    def test_volume_detail_limit_offset(self):
        created_volumes = self._create_db_volumes(2)
        req = fakes.HTTPRequest.blank('/v3/volumes/detail?limit=2&offset=1')
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(created_volumes[1].id, volumes[0]['id'])

        req = fakes.HTTPRequest.blank('/v3/volumes/detail?limit=2&offset=1',
                                      use_admin_context=True)
        res_dict = self.controller.detail(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(created_volumes[1].id, volumes[0]['id'])

        req = fakes.HTTPRequest.blank('/v3/volumes/detail?limit=-1&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail,
                          req)

        req = fakes.HTTPRequest.blank('/v3/volumes/detail?limit=a&offset=1')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail,
                          req)

        url = '/v3/volumes/detail?limit=2&offset=4536546546546467'
        req = fakes.HTTPRequest.blank(url)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail,
                          req)

    def test_volume_with_limit_zero(self):
        def fake_volume_get_all(context, marker, limit, **kwargs):
            return []
        self.mock_object(db, 'volume_get_all', fake_volume_get_all)
        req = fakes.HTTPRequest.blank('/v3/volumes?limit=0')
        res_dict = self.controller.index(req)
        expected = {'volumes': []}
        self.assertEqual(expected, res_dict)

    def _validate_next_link(self, detailed, item_count, osapi_max_limit, limit,
                            should_link_exist):
        keys_fns = (('volumes', self.controller.index),
                    ('volumes/detail', self.controller.detail))
        key, fn = keys_fns[detailed]

        req_string = '/v3/%s?all_tenants=1' % key
        if limit:
            req_string += '&limit=%s' % limit
        req = fakes.HTTPRequest.blank(req_string, use_admin_context=True)

        link_return = [{"rel": "next", "href": "fake_link"}]
        self.flags(osapi_max_limit=osapi_max_limit)

        def get_pagination_params(params, max_limit=CONF.osapi_max_limit,
                                  original_call=common.get_pagination_params):
            return original_call(params, max_limit)

        def _get_limit_param(params, max_limit=CONF.osapi_max_limit,
                             original_call=common._get_limit_param):
            return original_call(params, max_limit)

        with mock.patch.object(common, 'get_pagination_params',
                               get_pagination_params), \
                mock.patch.object(common, '_get_limit_param',
                                  _get_limit_param), \
                mock.patch.object(common.ViewBuilder, '_generate_next_link',
                                  return_value=link_return):
            res_dict = fn(req)
            self.assertEqual(item_count, len(res_dict['volumes']))
            self.assertEqual(should_link_exist, 'volumes_links' in res_dict)

    def test_volume_default_limit(self):
        self._create_db_volumes(3)

        # Verify both the index and detail queries
        for detailed in (True, False):
            # Number of volumes less than max, do not include
            self._validate_next_link(detailed, item_count=3, osapi_max_limit=4,
                                     limit=None, should_link_exist=False)

            # Number of volumes equals the max, next link will be included
            self._validate_next_link(detailed, item_count=3, osapi_max_limit=3,
                                     limit=None, should_link_exist=True)

            # Number of volumes more than the max, include next link
            self._validate_next_link(detailed, item_count=2, osapi_max_limit=2,
                                     limit=None, should_link_exist=True)

            # Limit lower than max but doesn't limit, no next link
            self._validate_next_link(detailed, item_count=3, osapi_max_limit=5,
                                     limit=4, should_link_exist=False)

            # Limit lower than max and limits, we have next link
            self._validate_next_link(detailed, item_count=2, osapi_max_limit=4,
                                     limit=2, should_link_exist=True)

            # Limit higher than max and max limits, we have next link
            self._validate_next_link(detailed, item_count=2, osapi_max_limit=2,
                                     limit=4, should_link_exist=True)

            # Limit higher than max but none of them limiting, no next link
            self._validate_next_link(detailed, item_count=3, osapi_max_limit=4,
                                     limit=5, should_link_exist=False)

    def test_volume_list_default_filters(self):
        """Tests that the default filters from volume.api.API.get_all are set.

        1. 'no_migration_status'=True for non-admins and get_all_by_project is
        invoked.
        2. 'no_migration_status' is not included for admins.
        3. When 'all_tenants' is not specified, then it is removed and
        get_all_by_project is invoked for admins.
        3. When 'all_tenants' is specified, then it is removed and get_all
        is invoked for admins.
        """
        # Non-admin, project function should be called with no_migration_status
        def fake_volume_get_all_by_project(context, project_id, marker, limit,
                                           sort_keys=None, sort_dirs=None,
                                           filters=None,
                                           viewable_admin_meta=False,
                                           offset=0):
            self.assertTrue(filters['no_migration_targets'])
            self.assertNotIn('all_tenants', filters)
            return [v3_fakes.create_volume(fake.VOLUME_ID,
                                           display_name='vol1')]

        def fake_volume_get_all(context, marker, limit,
                                sort_keys=None, sort_dirs=None,
                                filters=None,
                                viewable_admin_meta=False, offset=0):
            return []
        self.mock_object(db, 'volume_get_all_by_project',
                         fake_volume_get_all_by_project)
        self.mock_object(db, 'volume_get_all', fake_volume_get_all)

        # all_tenants does not matter for non-admin
        for params in ['', '?all_tenants=1']:
            req = fakes.HTTPRequest.blank('/v3/volumes%s' % params)
            resp = self.controller.index(req)
            self.assertEqual(1, len(resp['volumes']))
            self.assertEqual('vol1', resp['volumes'][0]['name'])

        # Admin, all_tenants is not set, project function should be called
        # without no_migration_status
        def fake_volume_get_all_by_project2(context, project_id, marker, limit,
                                            sort_keys=None, sort_dirs=None,
                                            filters=None,
                                            viewable_admin_meta=False,
                                            offset=0):
            self.assertNotIn('no_migration_targets', filters)
            return [v3_fakes.create_volume(fake.VOLUME_ID,
                                           display_name='vol2')]

        def fake_volume_get_all2(context, marker, limit,
                                 sort_keys=None, sort_dirs=None,
                                 filters=None,
                                 viewable_admin_meta=False, offset=0):
            return []
        self.mock_object(db, 'volume_get_all_by_project',
                         fake_volume_get_all_by_project2)
        self.mock_object(db, 'volume_get_all', fake_volume_get_all2)

        req = fakes.HTTPRequest.blank('/v3/volumes', use_admin_context=True)
        resp = self.controller.index(req)
        self.assertEqual(1, len(resp['volumes']))
        self.assertEqual('vol2', resp['volumes'][0]['name'])

        # Admin, all_tenants is set, get_all function should be called
        # without no_migration_status
        def fake_volume_get_all_by_project3(context, project_id, marker, limit,
                                            sort_keys=None, sort_dirs=None,
                                            filters=None,
                                            viewable_admin_meta=False,
                                            offset=0):
            return []

        def fake_volume_get_all3(context, marker, limit,
                                 sort_keys=None, sort_dirs=None,
                                 filters=None,
                                 viewable_admin_meta=False, offset=0):
            self.assertNotIn('no_migration_targets', filters)
            self.assertNotIn('all_tenants', filters)
            return [v3_fakes.create_volume(fake.VOLUME3_ID,
                                           display_name='vol3')]
        self.mock_object(db, 'volume_get_all_by_project',
                         fake_volume_get_all_by_project3)
        self.mock_object(db, 'volume_get_all', fake_volume_get_all3)

        req = fakes.HTTPRequest.blank('/v3/volumes?all_tenants=1',
                                      use_admin_context=True)
        resp = self.controller.index(req)
        self.assertEqual(1, len(resp['volumes']))
        self.assertEqual('vol3', resp['volumes'][0]['name'])

    def test_volume_show(self):
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_api_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        expected = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ,
            metadata={'attached_mode': 'rw', 'readonly': 'False'})
        self.assertEqual(expected, res_dict)
        # Finally test that we cached the returned volume
        self.assertIsNotNone(req.cached_resource_by_id(fake.VOLUME_ID))

    def test_volume_show_no_attachments(self):
        def fake_volume_get(self, context, volume_id, **kwargs):
            vol = v3_fakes.create_volume(
                volume_id, attach_status=fields.VolumeAttachStatus.DETACHED)
            return fake_volume.fake_volume_obj(context, **vol)

        def fake_volume_admin_metadata_get(context, volume_id, **kwargs):
            return v3_fakes.fake_volume_admin_metadata_get(
                context, volume_id,
                attach_status=fields.VolumeAttachStatus.DETACHED)

        self.mock_object(volume_api.API, 'get', fake_volume_get)
        self.mock_object(db, 'volume_admin_metadata_get',
                         fake_volume_admin_metadata_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        expected = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ,
            metadata={'readonly': 'False'})

        self.assertEqual(expected, res_dict)

    def test_volume_show_no_volume(self):
        self.mock_object(volume_api.API, "get",
                         v3_fakes.fake_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertRaises(exception.VolumeNotFound, self.controller.show,
                          req, 1)
        # Finally test that nothing was cached
        self.assertIsNone(req.cached_resource_by_id(fake.VOLUME_ID))

    def test_volume_show_with_admin_metadata(self):
        volume = v3_fakes.create_volume(fake.VOLUME_ID)
        del volume['name']
        del volume['volume_type']
        volume['metadata'] = {'key': 'value'}
        db.volume_create(context.get_admin_context(), volume)
        db.volume_admin_metadata_update(context.get_admin_context(),
                                        fake.VOLUME_ID,
                                        {"readonly": "True",
                                         "invisible_key": "invisible_value"},
                                        False)
        values = {'volume_id': fake.VOLUME_ID, }
        attachment = db.volume_attach(context.get_admin_context(), values)
        db.volume_attached(context.get_admin_context(),
                           attachment['id'], fake.INSTANCE_ID, None, '/')
        attach_tmp = db.volume_attachment_get(context.get_admin_context(),
                                              attachment['id'])
        volume_tmp = db.volume_get(context.get_admin_context(), fake.VOLUME_ID)
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        admin_ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        req.environ['cinder.context'] = admin_ctx
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        expected = self._expected_vol_from_controller(
            availability_zone=v3_fakes.DEFAULT_AZ,
            volume_type=fake.VOLUME_TYPE_NAME, status='in-use',
            attachments=[{'id': fake.VOLUME_ID,
                          'attachment_id': attachment['id'],
                          'volume_id': v3_fakes.DEFAULT_VOL_ID,
                          'server_id': fake.INSTANCE_ID,
                          'host_name': None,
                          'device': '/',
                          'attached_at': attach_tmp['attach_time'].replace(
                              tzinfo=iso8601.UTC),
                          }],
            metadata={'key': 'value', 'readonly': 'True'},
            with_migration_status=True)
        expected['volume']['updated_at'] = volume_tmp['updated_at'].replace(
            tzinfo=iso8601.UTC)
        self.assertEqual(expected, res_dict)

    def test_volume_show_with_encrypted_volume(self):
        def fake_volume_get(self, context, volume_id, **kwargs):
            vol = v3_fakes.create_volume(volume_id,
                                         encryption_key_id=fake.KEY_ID)
            return fake_volume.fake_volume_obj(context, **vol)

        self.mock_object(volume_api.API, 'get', fake_volume_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        self.assertTrue(res_dict['volume']['encrypted'])

    def test_volume_show_with_unencrypted_volume(self):
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_api_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        self.assertEqual(False, res_dict['volume']['encrypted'])

    def test_volume_show_with_error_managing_deleting(self):
        def fake_volume_get(self, context, volume_id, **kwargs):
            vol = v3_fakes.create_volume(volume_id,
                                         status='error_managing_deleting')
            return fake_volume.fake_volume_obj(context, **vol)

        self.mock_object(volume_api.API, 'get', fake_volume_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v3_fakes.fake_volume_type_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        res_dict = self.controller.show(req, fake.VOLUME_ID)
        self.assertEqual('deleting', res_dict['volume']['status'])

    @mock.patch.object(volume_api.API, 'delete', v3_fakes.fake_volume_delete)
    @mock.patch.object(volume_api.API, 'get', v3_fakes.fake_volume_get)
    def test_volume_delete(self):
        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        resp = self.controller.delete(req, fake.VOLUME_ID)
        self.assertEqual(HTTPStatus.ACCEPTED, resp.status_int)

    def test_volume_delete_attached(self):
        def fake_volume_attached(self, context, volume,
                                 force=False, cascade=False):
            raise exception.VolumeAttached(volume_id=volume['id'])
        self.mock_object(volume_api.API, "delete", fake_volume_attached)
        self.mock_object(volume_api.API, 'get', v3_fakes.fake_volume_get)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        exp = self.assertRaises(exception.VolumeAttached,
                                self.controller.delete,
                                req, 1)
        expect_msg = "Volume 1 is still attached, detach volume first."
        self.assertEqual(expect_msg, str(exp))

    def test_volume_delete_no_volume(self):
        self.mock_object(volume_api.API, "get",
                         v3_fakes.fake_volume_get_notfound)

        req = fakes.HTTPRequest.blank('/v3/volumes/%s' % fake.VOLUME_ID)
        self.assertRaises(exception.VolumeNotFound, self.controller.delete,
                          req, 1)

    def test_admin_list_volumes_limited_to_project(self):
        self.mock_object(db, 'volume_get_all_by_project',
                         v3_fakes.fake_volume_get_all_by_project)

        req = fakes.HTTPRequest.blank('/v3/%s/volumes' % fake.PROJECT_ID,
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    @mock.patch.object(db, 'volume_get_all', v3_fakes.fake_volume_get_all)
    @mock.patch.object(db, 'volume_get_all_by_project',
                       v3_fakes.fake_volume_get_all_by_project)
    def test_admin_list_volumes_all_tenants(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/volumes?all_tenants=1' % fake.PROJECT_ID,
            use_admin_context=True)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(3, len(res['volumes']))

    @mock.patch.object(db, 'volume_get_all', v3_fakes.fake_volume_get_all)
    @mock.patch.object(db, 'volume_get_all_by_project',
                       v3_fakes.fake_volume_get_all_by_project)
    @mock.patch.object(volume_api.API, 'get', v3_fakes.fake_volume_get)
    def test_all_tenants_non_admin_gets_all_tenants(self):
        req = fakes.HTTPRequest.blank(
            '/v3/%s/volumes?all_tenants=1' % fake.PROJECT_ID)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    @mock.patch.object(db, 'volume_get_all_by_project',
                       v3_fakes.fake_volume_get_all_by_project)
    @mock.patch.object(volume_api.API, 'get', v3_fakes.fake_volume_get)
    def test_non_admin_get_by_project(self):
        req = fakes.HTTPRequest.blank('/v3/%s/volumes' % fake.PROJECT_ID)
        res = self.controller.index(req)
        self.assertIn('volumes', res)
        self.assertEqual(1, len(res['volumes']))

    def _create_volume_bad_request(self, body):
        req = fakes.HTTPRequest.blank('/v3/%s/volumes' % fake.PROJECT_ID)
        req.method = 'POST'

        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)

    def test_create_no_body(self):
        self._create_volume_bad_request(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._create_volume_bad_request(body=body)

    def test_create_malformed_entity(self):
        body = {'volume': 'string'}
        self._create_volume_bad_request(body=body)

    def _test_get_volumes_by_name(self, get_all, display_name):
        qs = urllib.parse.urlencode({'name': display_name})
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'display_name': display_name},
            viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_string(self, get_all):
        """Test to get a volume with an alpha-numeric display name."""
        self._test_get_volumes_by_name(get_all, 'Volume-573108026')

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_double_quoted_string(self, get_all):
        """Test to get a volume with a double-quoted display name."""
        self._test_get_volumes_by_name(get_all, '"Volume-573108026"')

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_single_quoted_string(self, get_all):
        """Test to get a volume with a single-quoted display name."""
        self._test_get_volumes_by_name(get_all, "'Volume-573108026'")

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_quote_in_between_string(self, get_all):
        """Test to get a volume with a quote in between the display name."""
        self._test_get_volumes_by_name(get_all, 'Volu"me-573108026')

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_mixed_quoted_string(self, get_all):
        """Test to get a volume with a mix of single and double quotes. """
        # The display name starts with a single quote and ends with a
        # double quote
        self._test_get_volumes_by_name(get_all, '\'Volume-573108026"')

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_true(self, get_all):
        qs = urllib.parse.urlencode(
            {'name': 'Volume-573108026', 'bootable': 'true'}
        )
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'display_name': 'Volume-573108026', 'bootable': True},
            viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_false(self, get_all):
        qs = urllib.parse.urlencode(
            {'name': 'Volume-573108026', 'bootable': 'false'}
        )
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'display_name': 'Volume-573108026', 'bootable': False},
            viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_list(self, get_all):
        qs = urllib.parse.urlencode({
            'availability_zone': "['az0', 'az1', 'az2']",
        })
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'availability_zone': ['az0', 'az1', 'az2']},
            viewable_admin_meta=True,
            offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_expression(self, get_all):
        qs = urllib.parse.urlencode({'name': "d-"})
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'display_name': 'd-'}, viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_status(self, get_all):
        qs = urllib.parse.urlencode({'status': 'available'})
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'status': 'available'}, viewable_admin_meta=True,
            offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_metadata(self, get_all):
        qs = urllib.parse.urlencode({'metadata': "{'fake_key': 'fake_value'}"})
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'metadata': {'fake_key': 'fake_value'}},
            viewable_admin_meta=True, offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_availability_zone(self, get_all):
        qs = urllib.parse.urlencode({'availability_zone': 'nova'})
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'availability_zone': 'nova'}, viewable_admin_meta=True,
            offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_bootable(self, get_all):
        qs = urllib.parse.urlencode({'bootable': 'true'})
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'bootable': True}, viewable_admin_meta=True,
            offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_filter_with_invalid_filter(self, get_all):
        qs = urllib.parse.urlencode(
            {'availability_zone': 'nova', 'invalid_filter': 'invalid'})
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_keys=['created_at'], sort_dirs=['desc'],
            filters={'availability_zone': 'nova'}, viewable_admin_meta=True,
            offset=0)

    @mock.patch('cinder.volume.api.API.get_all')
    def test_get_volumes_sort_by_name(self, get_all):
        """Name in client means display_name in database."""
        qs = urllib.parse.urlencode({'sort': 'name'})
        req = fakes.HTTPRequest.blank('/v3/volumes' + '?' + qs)
        ctxt = req.environ['cinder.context']
        self.controller._view_builder.detail_list = mock.Mock()
        self.controller._get_volumes(req, True)
        get_all.assert_called_once_with(
            ctxt, None, CONF.osapi_max_limit,
            sort_dirs=['desc'], viewable_admin_meta=True,
            sort_keys=['display_name'], filters={}, offset=0)

    def test_get_volume_filter_options_using_config(self):
        filter_list = ["name", "status", "metadata", "bootable",
                       "migration_status", "availability_zone", "group_id"]
        # Clear the filters collection to make sure the filters collection
        # cache can be reloaded using tmp filter file.
        common._FILTERS_COLLECTION = None
        tmp_filter_file = self.tmp_path + '/resource_filters_tests.json'
        self.override_config('resource_query_filters_file', tmp_filter_file)
        with open(tmp_filter_file, 'w') as f:
            f.write(json.dumps({"volume": filter_list}))
        self.assertEqual(filter_list,
                         self.controller._get_volume_filter_options())
        # Reset the CONF.resource_query_filters_file and clear the filters
        # collection to avoid leaking other cases, and it will be re-loaded
        # from CONF.resource_query_filters_file in next call.
        self._reset_filter_file()
