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

from cinder.api import extensions
from cinder.api.openstack import api_version_request as api_version
from cinder.api.v3 import volumes
from cinder import context
from cinder import db
from cinder import exception
from cinder.group import api as group_api
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import stubs
from cinder.tests.unit.api.v2 import test_volumes as v2_test_volumes
from cinder.tests.unit import fake_constants as fake
from cinder.volume import api as volume_api
from cinder.volume import api as vol_get

version_header_name = 'OpenStack-API-Version'

DEFAULT_AZ = "zone1:host1"


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
            req.api_version_request = api_version.max_api_version()

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

    def _create_volume_with_consistency_group(self):
        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1',
                                            'project_id':
                                            self.ctxt.project_id,
                                            'consistencygroup_id':
                                            fake.CONSISTENCY_GROUP_ID})
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'project_id':
                                            self.ctxt.project_id,
                                            'consistencygroup_id':
                                            fake.CONSISTENCY_GROUP2_ID})
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
        vols = self._create_volume_with_consistency_group()
        req = fakes.HTTPRequest.blank(("/v3/volumes?group_id=%s") %
                                      fake.CONSISTENCY_GROUP_ID)
        req.headers["OpenStack-API-Version"] = "volume 3.10"
        req.api_version_request = api_version.APIVersionRequest('3.10')
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(1, len(volumes))
        self.assertEqual(vols[0].id, volumes[0]['id'])

    def test_volume_index_filter_by_group_id_in_unsupport_version(self):
        self._create_volume_with_consistency_group()
        req = fakes.HTTPRequest.blank(("/v3/volumes?group_id=%s") %
                                      fake.CONSISTENCY_GROUP2_ID)
        req.headers["OpenStack-API-Version"] = "volume 3.9"
        req.api_version_request = api_version.APIVersionRequest('3.9')
        req.environ['cinder.context'] = self.ctxt
        res_dict = self.controller.index(req)
        volumes = res_dict['volumes']
        self.assertEqual(2, len(volumes))

    def _fake_volumes_summary_request(self, version='3.12'):
        req = fakes.HTTPRequest.blank('/v3/volumes/summary')
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

    def _vol_in_request_body(self,
                             size=stubs.DEFAULT_VOL_SIZE,
                             name=stubs.DEFAULT_VOL_NAME,
                             description=stubs.DEFAULT_VOL_DESCRIPTION,
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
            size=stubs.DEFAULT_VOL_SIZE,
            availability_zone=DEFAULT_AZ,
            description=stubs.DEFAULT_VOL_DESCRIPTION,
            name=stubs.DEFAULT_VOL_NAME,
            consistencygroup_id=None,
            source_volid=None,
            snapshot_id=None,
            metadata=None,
            attachments=None,
            volume_type=stubs.DEFAULT_VOL_TYPE,
            status=stubs.DEFAULT_VOL_STATUS,
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
                   'id': stubs.DEFAULT_VOL_ID,
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
        self.mock_object(volume_api.API, 'get', stubs.stub_volume_get)
        self.mock_object(volume_api.API, "create",
                         stubs.stub_volume_api_create)
        self.mock_object(db.sqlalchemy.api, '_volume_type_get_full',
                         stubs.stub_volume_type_get)

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
        create.side_effect = stubs.stub_volume_api_create
        get_snapshot.side_effect = stubs.stub_snapshot_get
        volume_type_get.side_effect = stubs.stub_volume_type_get
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
            stubs.stub_snapshot(snapshot_id),
            test_group=fake_group,
            req_version=req.api_version_request)
        create.assert_called_once_with(self.controller.volume_api, context,
                                       vol['size'], stubs.DEFAULT_VOL_NAME,
                                       stubs.DEFAULT_VOL_DESCRIPTION, **kwargs)
