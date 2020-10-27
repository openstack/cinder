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

import ddt
import fixtures
import iso8601
from oslo_serialization import jsonutils
from oslo_utils import strutils
from oslo_utils import timeutils
import webob

from cinder.api import api_utils
from cinder.api import common
from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.v2.views.volumes import ViewBuilder
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
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit.api.v2 import test_volumes as v2_test_volumes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit.image import fake as fake_image
from cinder.tests.unit import test
from cinder.tests.unit import utils as test_utils
from cinder.volume import api as volume_api
from cinder.volume import api as vol_get

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


@ddt.ddt
class VolumeApiTest(test.TestCase):
    def setUp(self):
        super(VolumeApiTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        fake_image.mock_image_service(self)
        self.controller = volumes.VolumeController(self.ext_mgr)

        self.flags(host='fake')
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)
        # This will be cleaned up by the NestedTempfile fixture in base class
        self.tmp_path = self.useFixture(fixtures.TempDir()).path

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
                                     'volume_type_id': fake.VOLUME_TYPE_ID})
        db.volume_create(self.ctxt, {'display_name': 'test2',
                                     'project_id': fake.PROJECT_ID,
                                     'volume_type_id': fake.VOLUME_TYPE_ID})
        # Create volume in project 2
        db.volume_create(self.ctxt, {'display_name': 'test3',
                                     'project_id': fake.PROJECT2_ID,
                                     'volume_type_id': fake.VOLUME_TYPE_ID})

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

        self.mock_object(ViewBuilder, '_get_volume_type',
                         v2_fakes.fake_volume_type_name_get)
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

        self.mock_object(ViewBuilder, '_get_volume_type',
                         v2_fakes.fake_volume_type_name_get)
        # Request with 'all_tenants' and 'metadata'
        req = fakes.HTTPRequest.blank(
            "/v3/volumes/detail?all_tenants=1"
            "&metadata=%7B%27key_X%27%3A+%27value_X%27%7D")
        ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, False)
        req.environ['cinder.context'] = ctxt
        res_dict = self.controller._get_volumes(req, is_detail=True)
        self.assertEqual(1, len(res_dict['volumes']))
        self.assertEqual(metadata, res_dict['volumes'][0]['metadata'])

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
        create.side_effect = v2_fakes.fake_volume_api_create
        get_snapshot.side_effect = v2_fakes.fake_snapshot_get
        volume_type_get.side_effect = v2_fakes.fake_volume_type_get

        vol = self._vol_in_request_body(
            image_id="b0a599e0-41d7-3582-b260-769f443c862a")

        snapshot_id = fake.SNAPSHOT_ID
        ex = self._expected_vol_from_controller(snapshot_id=snapshot_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        req.headers = mv.get_mv_header(mv.SUPPORT_NOVA_IMAGE)
        req.api_version_request = mv.get_api_version(mv.SUPPORT_NOVA_IMAGE)
        res_dict = self.controller.create(req, body=body)
        self.assertEqual(ex, res_dict)
        context = req.environ['cinder.context']
        get_snapshot.assert_called_once_with(self.controller.volume_api,
                                             context, snapshot_id)
        kwargs = self._expected_volume_api_create_kwargs(
            v2_fakes.fake_snapshot(snapshot_id))
        create.assert_called_once_with(
            self.controller.volume_api, context,
            vol['size'], v2_fakes.DEFAULT_VOL_NAME,
            v2_fakes.DEFAULT_VOL_DESCRIPTION,
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

        vol = v2_test_volumes.VolumeApiTest._vol_in_request_body(
            availability_zone="nova")
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

    def _vol_in_request_body(self,
                             size=v2_fakes.DEFAULT_VOL_SIZE,
                             name=v2_fakes.DEFAULT_VOL_NAME,
                             description=v2_fakes.DEFAULT_VOL_DESCRIPTION,
                             availability_zone=DEFAULT_AZ,
                             snapshot_id=None,
                             source_volid=None,
                             consistencygroup_id=None,
                             volume_type=None,
                             image_ref=None,
                             image_id=None,
                             group_id=None,
                             backup_id=None):
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

    def _expected_vol_from_controller(
            self,
            size=v2_fakes.DEFAULT_VOL_SIZE,
            availability_zone=DEFAULT_AZ,
            description=v2_fakes.DEFAULT_VOL_DESCRIPTION,
            name=v2_fakes.DEFAULT_VOL_NAME,
            consistencygroup_id=None,
            source_volid=None,
            snapshot_id=None,
            metadata=None,
            attachments=None,
            volume_type=v2_fakes.DEFAULT_VOL_TYPE,
            status=v2_fakes.DEFAULT_VOL_STATUS,
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
                   'id': v2_fakes.DEFAULT_VOL_ID,
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
            'multiattach': False,
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
        self.mock_object(volume_api.API, 'get', v2_fakes.fake_volume_get)
        self.mock_object(volume_api.API, "create",
                         v2_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

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
        self.mock_object(volume_api.API, 'get', v2_fakes.fake_volume_get)
        self.mock_object(volume_api.API, "create",
                         v2_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

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
        create.side_effect = v2_fakes.fake_volume_api_create
        get_snapshot.side_effect = v2_fakes.fake_snapshot_get
        volume_type_get.side_effect = v2_fakes.fake_volume_type_get

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
        req = fakes.HTTPRequest.blank('/v3/volumes')
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
            v2_fakes.fake_snapshot(snapshot_id),
            test_group=fake_group,
            req_version=req.api_version_request)
        create.assert_called_once_with(
            self.controller.volume_api, context,
            vol['size'], v2_fakes.DEFAULT_VOL_NAME,
            v2_fakes.DEFAULT_VOL_DESCRIPTION,
            **kwargs)

    @ddt.data(mv.VOLUME_CREATE_FROM_BACKUP,
              mv.get_prior_version(mv.VOLUME_CREATE_FROM_BACKUP))
    @mock.patch.object(db.sqlalchemy.api, '_volume_type_get_full',
                       autospec=True)
    @mock.patch.object(backup_api.API, 'get', autospec=True)
    @mock.patch.object(volume_api.API, 'create', autospec=True)
    def test_volume_creation_from_backup(self, max_ver, create, get_backup,
                                         volume_type_get):
        create.side_effect = v2_fakes.fake_volume_api_create
        get_backup.side_effect = v2_fakes.fake_backup_get
        volume_type_get.side_effect = v2_fakes.fake_volume_type_get

        backup_id = fake.BACKUP_ID
        req = fakes.HTTPRequest.blank('/v3/volumes')
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
            kwargs.update({'backup': v2_fakes.fake_backup_get(None, context,
                                                              backup_id)})
        create.assert_called_once_with(
            self.controller.volume_api, context,
            vol['size'],
            v2_fakes.DEFAULT_VOL_NAME,
            v2_fakes.DEFAULT_VOL_DESCRIPTION,
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
        self.mock_object(volume_api.API, 'get', v2_fakes.fake_volume_api_get)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

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
        mock_latest.side_effect = exception.VolumeSnapshotNotFound(volume_id=
                                                                   'fake_id')
        req = fakes.HTTPRequest.blank('/v3/volumes/fake_id/revert')
        req.headers = mv.get_mv_header(mv.VOLUME_REVERT)
        req.api_version_request = mv.get_api_version(
            mv.VOLUME_REVERT)

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.revert,
                          req, 'fake_id', {'revert': {'snapshot_id':
                                                      'fake_snapshot_id'}})

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

        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.revert,
                          req, 'fake_id', {'revert': {'snapshot_id':
                                                      'fake_snapshot_id'}})

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

        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.revert,
                          req,
                          fake_volume['id'],
                          {'revert': {'snapshot_id': fake_snapshot['id']}})

        # update snapshot's status failed
        mock_update.side_effect = [True, False]

        self.assertRaises(webob.exc.HTTPConflict, self.controller.revert,
                          req, fake_volume['id'], {'revert': {'snapshot_id':
                                                   fake_snapshot['id']}})

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
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.revert,
                          req, fake_volume['id'],
                          {'revert': {'snapshot_id': fake_snapshot['id']}})

    def test_view_get_attachments(self):
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
        attachments = ViewBuilder()._get_attachments(fake_volume, True)

        self.assertEqual(1, len(attachments))
        self.assertEqual(fake.UUID3, attachments[0]['attachment_id'])
        self.assertEqual(fake.UUID4, attachments[0]['volume_id'])
        self.assertEqual(fake.UUID5, attachments[0]['server_id'])
        self.assertEqual('host1', attachments[0]['host_name'])
        self.assertEqual('na', attachments[0]['device'])
        self.assertEqual(att_time, attachments[0]['attached_at'])

        # When admin context is false (non-admin), host_name will be None
        attachments = ViewBuilder()._get_attachments(fake_volume, False)
        self.assertIsNone(attachments[0]['host_name'])

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
