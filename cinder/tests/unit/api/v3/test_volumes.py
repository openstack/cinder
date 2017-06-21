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
import ddt
import iso8601

import mock
import webob

from cinder.api import extensions
from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import volumes
from cinder import context
from cinder import db
from cinder import exception
from cinder.group import api as group_api
from cinder import objects
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import fakes as v2_fakes
from cinder.tests.unit.api.v2 import test_volumes as v2_test_volumes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils as test_utils
from cinder import utils
from cinder.volume import api as volume_api
from cinder.volume import api as vol_get

version_header_name = 'OpenStack-API-Version'

DEFAULT_AZ = "zone1:host1"
REVERT_TO_SNAPSHOT_VERSION = '3.40'


@ddt.ddt
class VolumeApiTest(test.TestCase):
    def setUp(self):
        super(VolumeApiTest, self).setUp()
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = volumes.VolumeController(self.ext_mgr)

        self.flags(host='fake')
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

    def test_check_volume_filters_called(self):
        with mock.patch.object(vol_get.API,
                               'check_volume_filters') as volume_get:
            req = fakes.HTTPRequest.blank('/v3/volumes?bootable=True')
            req.method = 'GET'
            req.content_type = 'application/json'
            req.headers = {version_header_name: 'volume 3.0'}
            req.environ['cinder.context'].is_admin = True

            self.override_config('query_volume_filters', 'bootable')
            self.controller.index(req)
            filters = req.params.copy()

            volume_get.assert_called_with(filters, False)

    def test_check_volume_filters_strict_called(self):

        with mock.patch.object(vol_get.API,
                               'check_volume_filters') as volume_get:
            req = fakes.HTTPRequest.blank('/v3/volumes?bootable=True')
            req.method = 'GET'
            req.content_type = 'application/json'
            req.headers = {version_header_name: 'volume 3.2'}
            req.environ['cinder.context'].is_admin = True
            req.api_version_request = api_version.APIVersionRequest('3.29')

            self.override_config('query_volume_filters', 'bootable')
            self.controller.index(req)
            filters = req.params.copy()

            volume_get.assert_called_with(filters, True)

    def _create_volume_with_glance_metadata(self):
        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1',
                                            'project_id':
                                            self.ctxt.project_id})
        db.volume_glance_metadata_create(self.ctxt, vol1.id, 'image_name',
                                         'imageTestOne')
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'project_id':
                                            self.ctxt.project_id})
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
                                            fake.GROUP_ID})
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'project_id':
                                            self.ctxt.project_id,
                                            'group_id':
                                            fake.GROUP2_ID})
        return [vol1, vol2]

    def test_volume_index_filter_by_glance_metadata(self):
        vols = self._create_volume_with_glance_metadata()
        req = fakes.HTTPRequest.blank("/v3/volumes?glance_metadata="
                                      "{'image_name': 'imageTestOne'}")
        req.headers["OpenStack-API-Version"] = "volume 3.4"
        req.api_version_request = api_version.APIVersionRequest('3.4')
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(vols[0].id, volumes[0]['id'])

    def test_volume_index_filter_by_glance_metadata_in_unsupport_version(self):
        self._create_volume_with_glance_metadata()
        req = fakes.HTTPRequest.blank("/v3/volumes?glance_metadata="
                                      "{'image_name': 'imageTestOne'}")
        req.headers["OpenStack-API-Version"] = "volume 3.0"
        req.api_version_request = api_version.APIVersionRequest('3.0')
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(2, len(volumes))

    def test_volume_index_filter_by_group_id(self):
        vols = self._create_volume_with_group()
        req = fakes.HTTPRequest.blank(("/v3/volumes?group_id=%s") %
                                      fake.GROUP_ID)
        req.headers["OpenStack-API-Version"] = "volume 3.10"
        req.api_version_request = api_version.APIVersionRequest('3.10')
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(vols[0].id, volumes[0]['id'])

    def test_volume_index_filter_by_group_id_in_unsupport_version(self):
        self._create_volume_with_group()
        req = fakes.HTTPRequest.blank(("/v3/volumes?group_id=%s") %
                                      fake.GROUP_ID)
        req.headers["OpenStack-API-Version"] = "volume 3.9"
        req.api_version_request = api_version.APIVersionRequest('3.9')
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(2, len(volumes))

    def _fake_volumes_summary_request(self, version='3.12', all_tenant=False,
                                      is_admin=False):
        req_url = '/v3/volumes/summary'
        if all_tenant:
            req_url += '?all_tenants=True'
        req = fakes.HTTPRequest.blank(req_url, use_admin_context=is_admin)
        req.headers = {'OpenStack-API-Version': 'volume ' + version}
        req.api_version_request = api_version.APIVersionRequest(version)
        return req

    def test_volumes_summary_in_unsupport_version(self):
        """Function call to test summary volumes API in unsupported version"""
        req = self._fake_volumes_summary_request(version='3.7')
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
        res_dict = self.controller.create(req, body)

        req = self._fake_volumes_summary_request()
        res_dict = self.controller.summary(req)
        expected = {'volume-summary': {'total_size': 1.0, 'total_count': 1}}
        self.assertEqual(expected, res_dict)

    @ddt.data(
        ('3.35', {'volume-summary': {'total_size': 0.0,
                                     'total_count': 0}}),
        ('3.36', {'volume-summary': {'total_size': 0.0,
                                     'total_count': 0,
                                     'metadata': {}}}))
    @ddt.unpack
    def test_volume_summary_empty(self, summary_api_version, expect_result):
        req = self._fake_volumes_summary_request(version=summary_api_version)
        res_dict = self.controller.summary(req)
        self.assertEqual(expect_result, res_dict)

    @ddt.data(
        ('3.35', {'volume-summary': {'total_size': 2,
                                     'total_count': 2}}),
        ('3.36', {'volume-summary': {'total_size': 2,
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
        ('3.35', {'volume-summary': {'total_size': 2,
                                     'total_count': 2}}),
        ('3.36', {'volume-summary': {'total_size': 2,
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
                             source_replica=None,
                             consistencygroup_id=None,
                             volume_type=None,
                             image_ref=None,
                             image_id=None,
                             group_id=None):
        vol = {"size": size,
               "name": name,
               "description": description,
               "availability_zone": availability_zone,
               "snapshot_id": snapshot_id,
               "source_volid": source_volid,
               "source_replica": source_replica,
               "consistencygroup_id": consistencygroup_id,
               "volume_type": volume_type,
               "group_id": group_id,
               }

        if image_id is not None:
            vol['image_id'] = image_id
        elif image_ref is not None:
            vol['imageRef'] = image_ref

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
                       1900, 1, 1, 1, 1, 1, tzinfo=iso8601.iso8601.Utc()),
                   'updated_at': datetime.datetime(
                       1900, 1, 1, 1, 1, 1, tzinfo=iso8601.iso8601.Utc()),
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

        # Remove group_id if max version is less than 3.13.
        if req_version and req_version.matches(None, "3.12"):
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
            'source_replica': None,
            'consistencygroup': None,
            'availability_zone': availability_zone,
            'scheduler_hints': None,
            'multiattach': False,
            'group': test_group,
        }

        # Remove group_id if max version is less than 3.13.
        if req_version and req_version.matches(None, "3.12"):
            volume.pop('group')

        return volume

    @ddt.data('3.13', '3.12')
    @mock.patch(
        'cinder.api.openstack.wsgi.Controller.validate_name_and_description')
    def test_volume_create(self, max_ver, mock_validate):
        self.mock_object(volume_api.API, 'get', v2_fakes.fake_volume_get)
        self.mock_object(volume_api.API, "create",
                         v2_fakes.fake_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         v2_fakes.fake_volume_type_get)

        vol = self._vol_in_request_body()
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        req.api_version_request = api_version.APIVersionRequest(max_ver)
        res_dict = self.controller.create(req, body)
        ex = self._expected_vol_from_controller(
            req_version=req.api_version_request)
        self.assertEqual(ex, res_dict)
        self.assertTrue(mock_validate.called)

    @ddt.data('3.14', '3.13')
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
        req.api_version_request = api_version.APIVersionRequest(max_ver)
        res_dict = self.controller.create(req, body)
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
        create.assert_called_once_with(self.controller.volume_api, context,
                                       vol['size'], v2_fakes.DEFAULT_VOL_NAME,
                                       v2_fakes.DEFAULT_VOL_DESCRIPTION,
                                       **kwargs)

    @ddt.data({'s': 'ea895e29-8485-4930-bbb8-c5616a309c0e'},
              ['ea895e29-8485-4930-bbb8-c5616a309c0e'],
              42)
    def test_volume_creation_fails_with_invalid_snapshot_type(self, value):
        snapshot_id = value
        vol = self._vol_in_request_body(snapshot_id=snapshot_id)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v3/volumes')
        # Raise 400 when snapshot has not uuid type.
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body)

    @ddt.data({'source_volid': 1},
              {'source_volid': []},
              {'source_replica': 1},
              {'source_replica': []},
              {'consistencygroup_id': 1},
              {'consistencygroup_id': []})
    def test_volume_creation_fails_with_invalid_uuids(self, updated_uuids):
        vol = self._vol_in_request_body()
        vol.update(updated_uuids)
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank('/v2/volumes')
        # Raise 400 for resource requested with invalid uuids.
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, body)

    @ddt.data('3.30', '3.31', '3.34')
    @mock.patch.object(volume_api.API, 'check_volume_filters', mock.Mock())
    @mock.patch.object(utils, 'add_visible_admin_metadata', mock.Mock())
    @mock.patch('cinder.api.common.reject_invalid_filters')
    def test_list_volume_with_general_filter(self, version, mock_update):
        req = fakes.HTTPRequest.blank('/v3/volumes', version=version)
        self.controller.index(req)
        if version != '3.30':
            support_like = True if version == '3.34' else False
            mock_update.assert_called_once_with(req.environ['cinder.context'],
                                                mock.ANY, 'volume',
                                                support_like)

    @ddt.data({'admin': True, 'version': '3.21'},
              {'admin': False, 'version': '3.21'},
              {'admin': True, 'version': '3.20'},
              {'admin': False, 'version': '3.20'})
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
        # 3.21 for admin.
        if req_version.matches("3.21", None) and admin:
            self.assertIn('provider_id', res_dict['volume'])
        else:
            self.assertNotIn('provider_id', res_dict['volume'])

    def _fake_create_volume(self):
        vol = {
            'display_name': 'fake_volume1',
            'status': 'available'
        }
        volume = objects.Volume(context=self.ctxt, **vol)
        volume.create()
        return volume

    def _fake_create_snapshot(self, volume_id):
        snap = {
            'display_name': 'fake_snapshot1',
            'status': 'available',
            'volume_id': volume_id
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
        req.headers = {'OpenStack-API-Version':
                       'volume %s' % REVERT_TO_SNAPSHOT_VERSION}
        req.api_version_request = api_version.APIVersionRequest(
            REVERT_TO_SNAPSHOT_VERSION)

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
        req.headers = {'OpenStack-API-Version':
                       'volume %s' % REVERT_TO_SNAPSHOT_VERSION}
        req.api_version_request = api_version.APIVersionRequest(
            REVERT_TO_SNAPSHOT_VERSION)

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
        req.headers = {'OpenStack-API-Version':
                       'volume %s' % REVERT_TO_SNAPSHOT_VERSION}
        req.api_version_request = api_version.APIVersionRequest(
            REVERT_TO_SNAPSHOT_VERSION)
        # update volume's status failed
        mock_update.side_effect = [False, True]

        self.assertRaises(webob.exc.HTTPConflict, self.controller.revert,
                          req, fake_volume['id'], {'revert': {'snapshot_id':
                                                   fake_snapshot['id']}})

        # update snapshot's status failed
        mock_update.side_effect = [True, False]

        self.assertRaises(webob.exc.HTTPConflict, self.controller.revert,
                          req, fake_volume['id'], {'revert': {'snapshot_id':
                                                   fake_snapshot['id']}})
