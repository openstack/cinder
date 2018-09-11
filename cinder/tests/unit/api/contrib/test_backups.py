# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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
Tests for Backup code.
"""

import ddt
import mock
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import six
from six.moves import http_client
import webob

from cinder.api.contrib import backups
from cinder.api import microversions as mv
from cinder.api.openstack import api_version_request as api_version
# needed for stubs to work
import cinder.backup
from cinder.backup import api as backup_api
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils
# needed for stubs to work
import cinder.volume

NUM_ELEMENTS_IN_BACKUP = 17


@ddt.ddt
class BackupsAPITestCase(test.TestCase):
    """Test Case for backups API."""

    def setUp(self):
        super(BackupsAPITestCase, self).setUp()
        self.volume_api = cinder.volume.API()
        self.backup_api = cinder.backup.API()
        self.context = context.get_admin_context()
        self.context.project_id = fake.PROJECT_ID
        self.context.user_id = fake.USER_ID
        self.user_context = context.RequestContext(
            fake.USER_ID, fake.PROJECT_ID, auth_token=True)
        self.controller = backups.BackupsController()
        self.patch('cinder.objects.service.Service._get_minimum_version',
                   return_value=None)

    @staticmethod
    def _get_backup_attrib(backup_id, attrib_name):
        return db.backup_get(context.get_admin_context(),
                             backup_id)[attrib_name]

    @ddt.data(False, True)
    def test_show_backup(self, backup_from_snapshot):
        volume = utils.create_volume(self.context, size=5, status='creating')
        snapshot = None
        snapshot_id = None
        if backup_from_snapshot:
            snapshot = utils.create_snapshot(self.context,
                                             volume.id)
            snapshot_id = snapshot.id
        backup = utils.create_backup(self.context, volume.id,
                                     snapshot_id=snapshot_id,
                                     container='volumebackups',
                                     size=1,
                                     availability_zone='az1')
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual('az1', res_dict['backup']['availability_zone'])
        self.assertEqual('volumebackups', res_dict['backup']['container'])
        self.assertEqual('This is a test backup',
                         res_dict['backup']['description'])
        self.assertEqual('test_backup', res_dict['backup']['name'])
        self.assertEqual(backup.id, res_dict['backup']['id'])
        self.assertEqual(22, res_dict['backup']['object_count'])
        self.assertEqual(1, res_dict['backup']['size'])
        self.assertEqual(fields.BackupStatus.CREATING,
                         res_dict['backup']['status'])
        self.assertEqual(volume.id, res_dict['backup']['volume_id'])
        self.assertFalse(res_dict['backup']['is_incremental'])
        self.assertFalse(res_dict['backup']['has_dependent_backups'])
        self.assertEqual(snapshot_id, res_dict['backup']['snapshot_id'])
        self.assertIn('updated_at', res_dict['backup'])

        if snapshot:
            snapshot.destroy()
        backup.destroy()
        volume.destroy()

    def test_show_backup_return_metadata(self):
        volume = utils.create_volume(self.context, size=5, status='creating')
        backup = utils.create_backup(self.context, volume.id,
                                     metadata={"test_key": "test_value"})
        req = webob.Request.blank('/v3/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'GET'
        req.headers = mv.get_mv_header(mv.BACKUP_METADATA)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual({"test_key": "test_value"},
                         res_dict['backup']['metadata'])
        volume.destroy()
        backup.destroy()

    def test_show_backup_with_backup_NotFound(self):
        req = webob.Request.blank('/v2/%s/backups/%s' % (
            fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'GET'
        req.headers = mv.get_mv_header(mv.BACKUP_METADATA)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Backup %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

    def test_list_backups_json(self):
        backup1 = utils.create_backup(self.context)
        backup2 = utils.create_backup(self.context)
        backup3 = utils.create_backup(self.context)

        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(3, len(res_dict['backups'][0]))
        self.assertEqual(backup3.id, res_dict['backups'][0]['id'])
        self.assertEqual('test_backup', res_dict['backups'][0]['name'])
        self.assertEqual(3, len(res_dict['backups'][1]))
        self.assertEqual(backup2.id, res_dict['backups'][1]['id'])
        self.assertEqual('test_backup', res_dict['backups'][1]['name'])
        self.assertEqual(3, len(res_dict['backups'][2]))
        self.assertEqual(backup1.id, res_dict['backups'][2]['id'])
        self.assertEqual('test_backup', res_dict['backups'][2]['name'])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_with_limit(self):
        backup1 = utils.create_backup(self.context)
        backup2 = utils.create_backup(self.context)
        backup3 = utils.create_backup(self.context)

        req = webob.Request.blank('/v2/%s/backups?limit=2' % fake.PROJECT_ID)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(2, len(res_dict['backups']))
        self.assertEqual(3, len(res_dict['backups'][0]))
        self.assertEqual(backup3.id, res_dict['backups'][0]['id'])
        self.assertEqual('test_backup', res_dict['backups'][0]['name'])
        self.assertEqual(3, len(res_dict['backups'][1]))
        self.assertEqual(backup2.id, res_dict['backups'][1]['id'])
        self.assertEqual('test_backup', res_dict['backups'][1]['name'])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_with_offset_out_of_range(self):
        url = '/v2/%s/backups?offset=252452434242342434' % fake.PROJECT_ID
        req = webob.Request.blank(url)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    def test_list_backups_with_marker(self):
        backup1 = utils.create_backup(self.context)
        backup2 = utils.create_backup(self.context)
        backup3 = utils.create_backup(self.context)
        url = '/v2/%s/backups?marker=%s' % (fake.PROJECT_ID, backup3.id)
        req = webob.Request.blank(url)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(2, len(res_dict['backups']))
        self.assertEqual(3, len(res_dict['backups'][0]))
        self.assertEqual(backup2.id, res_dict['backups'][0]['id'])
        self.assertEqual('test_backup', res_dict['backups'][0]['name'])
        self.assertEqual(3, len(res_dict['backups'][1]))
        self.assertEqual(backup1.id, res_dict['backups'][1]['id'])
        self.assertEqual('test_backup', res_dict['backups'][1]['name'])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_with_limit_and_marker(self):
        backup1 = utils.create_backup(self.context)
        backup2 = utils.create_backup(self.context)
        backup3 = utils.create_backup(self.context)

        url = ('/v2/%s/backups?limit=1&marker=%s' % (fake.PROJECT_ID,
                                                     backup3.id))
        req = webob.Request.blank(url)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(1, len(res_dict['backups']))
        self.assertEqual(3, len(res_dict['backups'][0]))
        self.assertEqual(backup2.id, res_dict['backups'][0]['id'])
        self.assertEqual('test_backup', res_dict['backups'][0]['name'])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_detail_json(self):
        backup1 = utils.create_backup(self.context, availability_zone='az1',
                                      container='volumebackups', size=1)
        backup2 = utils.create_backup(self.context, availability_zone='az1',
                                      container='volumebackups', size=1)
        backup3 = utils.create_backup(self.context, availability_zone='az1',
                                      container='volumebackups', size=1)

        req = webob.Request.blank('/v2/%s/backups/detail' % fake.PROJECT_ID)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(NUM_ELEMENTS_IN_BACKUP, len(res_dict['backups'][0]))
        self.assertEqual('az1', res_dict['backups'][0]['availability_zone'])
        self.assertEqual('volumebackups',
                         res_dict['backups'][0]['container'])
        self.assertEqual('This is a test backup',
                         res_dict['backups'][0]['description'])
        self.assertEqual('test_backup',
                         res_dict['backups'][0]['name'])
        self.assertEqual(backup3.id, res_dict['backups'][0]['id'])
        self.assertEqual(22, res_dict['backups'][0]['object_count'])
        self.assertEqual(1, res_dict['backups'][0]['size'])
        self.assertEqual(fields.BackupStatus.CREATING,
                         res_dict['backups'][0]['status'])
        self.assertEqual(fake.VOLUME_ID, res_dict['backups'][0]['volume_id'])
        self.assertIn('updated_at', res_dict['backups'][0])

        self.assertEqual(NUM_ELEMENTS_IN_BACKUP, len(res_dict['backups'][1]))
        self.assertEqual('az1', res_dict['backups'][1]['availability_zone'])
        self.assertEqual('volumebackups',
                         res_dict['backups'][1]['container'])
        self.assertEqual('This is a test backup',
                         res_dict['backups'][1]['description'])
        self.assertEqual('test_backup',
                         res_dict['backups'][1]['name'])
        self.assertEqual(backup2.id, res_dict['backups'][1]['id'])
        self.assertEqual(22, res_dict['backups'][1]['object_count'])
        self.assertEqual(1, res_dict['backups'][1]['size'])
        self.assertEqual(fields.BackupStatus.CREATING,
                         res_dict['backups'][1]['status'])
        self.assertEqual(fake.VOLUME_ID, res_dict['backups'][1]['volume_id'])
        self.assertIn('updated_at', res_dict['backups'][1])

        self.assertEqual(NUM_ELEMENTS_IN_BACKUP, len(res_dict['backups'][2]))
        self.assertEqual('az1', res_dict['backups'][2]['availability_zone'])
        self.assertEqual('volumebackups', res_dict['backups'][2]['container'])
        self.assertEqual('This is a test backup',
                         res_dict['backups'][2]['description'])
        self.assertEqual('test_backup',
                         res_dict['backups'][2]['name'])
        self.assertEqual(backup1.id, res_dict['backups'][2]['id'])
        self.assertEqual(22, res_dict['backups'][2]['object_count'])
        self.assertEqual(1, res_dict['backups'][2]['size'])
        self.assertEqual(fields.BackupStatus.CREATING,
                         res_dict['backups'][2]['status'])
        self.assertEqual(fake.VOLUME_ID, res_dict['backups'][2]['volume_id'])
        self.assertIn('updated_at', res_dict['backups'][2])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_detail_return_metadata(self):
        backup1 = utils.create_backup(self.context, size=1,
                                      metadata={'key1': 'value1'})
        backup2 = utils.create_backup(self.context, size=1,
                                      metadata={'key2': 'value2'})
        backup3 = utils.create_backup(self.context, size=1)

        req = webob.Request.blank('/v3/%s/backups/detail' % fake.PROJECT_ID)
        req.method = 'GET'
        req.headers = mv.get_mv_header(mv.BACKUP_METADATA)
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual({'key1': 'value1'},
                         res_dict['backups'][2]['metadata'])
        self.assertEqual({'key2': 'value2'},
                         res_dict['backups'][1]['metadata'])
        self.assertEqual({},
                         res_dict['backups'][0]['metadata'])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_detail_using_filters(self):
        backup1 = utils.create_backup(self.context, display_name='test2')
        backup2 = utils.create_backup(self.context,
                                      status=fields.BackupStatus.AVAILABLE)
        backup3 = utils.create_backup(self.context, volume_id=fake.VOLUME3_ID)

        req = webob.Request.blank('/v2/%s/backups/detail?name=test2' %
                                  fake.PROJECT_ID)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(1, len(res_dict['backups']))
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(backup1.id, res_dict['backups'][0]['id'])

        req = webob.Request.blank('/v2/%s/backups/detail?status=available' %
                                  fake.PROJECT_ID)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(1, len(res_dict['backups']))
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(backup2.id, res_dict['backups'][0]['id'])

        req = webob.Request.blank('/v2/%s/backups/detail?volume_id=%s' % (
            fake.PROJECT_ID, fake.VOLUME3_ID))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(1, len(res_dict['backups']))
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(backup3.id, res_dict['backups'][0]['id'])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_detail_with_limit_and_sort_args(self):
        backup1 = utils.create_backup(self.context)
        backup2 = utils.create_backup(self.context)
        backup3 = utils.create_backup(self.context)
        url = ('/v2/%s/backups/detail?limit=2&sort_key=created_at'
               '&sort_dir=desc' % fake.PROJECT_ID)
        req = webob.Request.blank(url)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(2, len(res_dict['backups']))
        self.assertEqual(NUM_ELEMENTS_IN_BACKUP, len(res_dict['backups'][0]))
        self.assertEqual(backup3.id, res_dict['backups'][0]['id'])
        self.assertEqual(NUM_ELEMENTS_IN_BACKUP, len(res_dict['backups'][1]))
        self.assertEqual(backup2.id, res_dict['backups'][1]['id'])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_detail_with_marker(self):
        backup1 = utils.create_backup(self.context)
        backup2 = utils.create_backup(self.context)
        backup3 = utils.create_backup(self.context)

        url = ('/v2/%s/backups/detail?marker=%s' % (
            fake.PROJECT_ID, backup3.id))
        req = webob.Request.blank(url)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(2, len(res_dict['backups']))
        self.assertEqual(NUM_ELEMENTS_IN_BACKUP, len(res_dict['backups'][0]))
        self.assertEqual(backup2.id, res_dict['backups'][0]['id'])
        self.assertEqual(NUM_ELEMENTS_IN_BACKUP, len(res_dict['backups'][1]))
        self.assertEqual(backup1.id, res_dict['backups'][1]['id'])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_detail_with_limit_and_marker(self):
        backup1 = utils.create_backup(self.context)
        backup2 = utils.create_backup(self.context)
        backup3 = utils.create_backup(self.context)

        url = ('/v2/%s/backups/detail?limit=1&marker=%s' % (
            fake.PROJECT_ID, backup3.id))
        req = webob.Request.blank(url)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(1, len(res_dict['backups']))
        self.assertEqual(NUM_ELEMENTS_IN_BACKUP, len(res_dict['backups'][0]))
        self.assertEqual(backup2.id, res_dict['backups'][0]['id'])

        backup3.destroy()
        backup2.destroy()
        backup1.destroy()

    def test_list_backups_detail_with_offset_out_of_range(self):
        url = ('/v2/%s/backups/detail?offset=234534543657634523' %
               fake.PROJECT_ID)
        req = webob.Request.blank(url)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)

    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_json(self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=5)

        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['backup'])
        _mock_service_get_all.assert_called_once_with(mock.ANY,
                                                      disabled=False,
                                                      topic='cinder-backup')

        volume.destroy()

    @ddt.data({"backup": {"description": "   sample description",
                          "name": "   test name"}},
              {"backup": {"description": "sample description   ",
                          "name": "test   "}},
              {"backup": {"description": " sample description ",
                          "name": "  test  "}})
    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_name_description_with_leading_trailing_spaces(
            self, body, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': fake.BACKUP_ID}]

        volume = utils.create_volume(self.context, size=5)
        body['backup']['volume_id'] = volume.id
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        # create backup call doesn't return 'description' in response so get
        # the created backup to assert name and description
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, res_dict['backup']['id']))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(body['backup']['name'].strip(),
                         res_dict['backup']['name'])
        self.assertEqual(body['backup']['description'].strip(),
                         res_dict['backup']['description'])
        volume.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_with_metadata(self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=1)
        # Create a backup with metadata
        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "nightlybackups",
                           'metadata': {'test_key': 'test_value'}
                           }
                }
        req = webob.Request.blank('/v3/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers = mv.get_mv_header(mv.BACKUP_METADATA)
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)
        # Get the new backup
        req = webob.Request.blank('/v3/%s/backups/%s' % (
                                  fake.PROJECT_ID, res_dict['backup']['id']))
        req.method = 'GET'
        req.headers = mv.get_mv_header(mv.BACKUP_METADATA)
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual({'test_key': 'test_value'},
                         res_dict['backup']['metadata'])

        volume.destroy()

    @mock.patch('cinder.objects.Service.is_up', mock.Mock(return_value=True))
    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_with_availability_zone(self, _mock_service_get_all):
        vol_az = 'az1'
        backup_svc_az = 'az2'
        _mock_service_get_all.return_value = [
            {'availability_zone': backup_svc_az, 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, availability_zone=vol_az,
                                     size=1)
        # Create a backup with metadata
        body = {'backup': {'name': 'nightly001',
                           'volume_id': volume.id,
                           'container': 'nightlybackups',
                           'availability_zone': backup_svc_az}}
        req = webob.Request.blank('/v3/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers = mv.get_mv_header(mv.BACKUP_AZ)
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        self.assertEqual(202, res.status_code)

        res_dict = jsonutils.loads(res.body)
        backup = objects.Backup.get_by_id(self.context,
                                          res_dict['backup']['id'])
        self.assertEqual(backup_svc_az, backup.availability_zone)

    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_inuse_no_force(self,
                                          _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=5, status='in-use')

        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertIsNotNone(res_dict['badRequest']['message'])

        volume.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_inuse_force(self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=5, status='in-use')
        backup = utils.create_backup(self.context, volume.id,
                                     status=fields.BackupStatus.AVAILABLE,
                                     size=1, availability_zone='az1',
                                     host='testhost')
        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "nightlybackups",
                           "force": True,
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['backup'])
        _mock_service_get_all.assert_called_once_with(mock.ANY,
                                                      disabled=False,
                                                      topic='cinder-backup')

        backup.destroy()
        volume.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_snapshot_json(self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=5, status='available')

        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['backup'])
        _mock_service_get_all.assert_called_once_with(mock.ANY,
                                                      disabled=False,
                                                      topic='cinder-backup')

        volume.destroy()

    def test_create_backup_snapshot_with_inconsistent_volume(self):
        volume = utils.create_volume(self.context, size=5, status='available')
        volume2 = utils.create_volume(self.context, size=5, status='available')
        snapshot = utils.create_snapshot(self.context, volume.id,
                                         status='available')

        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume2.id,
                           "snapshot_id": snapshot.id,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertIsNotNone(res_dict['badRequest']['message'])

        snapshot.destroy()
        volume2.destroy()
        volume.destroy()

    def test_create_backup_with_invalid_snapshot(self):
        volume = utils.create_volume(self.context, size=5, status='available')
        snapshot = utils.create_snapshot(self.context, volume.id,
                                         status='error')
        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "snapshot_id": snapshot.id,
                           "volume_id": volume.id,
                           }
                }

        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertIsNotNone(res_dict['badRequest']['message'])

        volume.destroy()
        snapshot.destroy()

    def test_create_backup_with_non_existent_snapshot(self):
        volume = utils.create_volume(self.context, size=5, status='restoring')
        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "snapshot_id": fake.SNAPSHOT_ID,
                           "volume_id": volume.id,
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertIsNotNone(res_dict['itemNotFound']['message'])

        volume.destroy()

    def test_create_backup_with_invalid_container(self):
        volume = utils.create_volume(self.context, size=5, status='available')
        body = {"backup": {"display_name": "nightly001",
                           "display_description": "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "a" * 256
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.environ['cinder.context'] = self.context
        req.api_version_request = api_version.APIVersionRequest()
        req.api_version_request = api_version.APIVersionRequest("2.0")
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          req,
                          body=body)

    @mock.patch('cinder.db.service_get_all')
    @ddt.data(False, True)
    def test_create_backup_delta(self, backup_from_snapshot,
                                 _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=5)
        snapshot = None
        if backup_from_snapshot:
            snapshot = utils.create_snapshot(self.context,
                                             volume.id,
                                             status=
                                             fields.SnapshotStatus.AVAILABLE)
            snapshot_id = snapshot.id
            body = {"backup": {"name": "nightly001",
                               "description":
                               "Nightly Backup 03-Sep-2012",
                               "volume_id": volume.id,
                               "container": "nightlybackups",
                               "incremental": True,
                               "snapshot_id": snapshot_id,
                               }
                    }
        else:
            body = {"backup": {"name": "nightly001",
                               "description":
                               "Nightly Backup 03-Sep-2012",
                               "volume_id": volume.id,
                               "container": "nightlybackups",
                               "incremental": True,
                               }
                    }
        backup = utils.create_backup(self.context, volume.id,
                                     status=fields.BackupStatus.AVAILABLE,
                                     size=1, availability_zone='az1',
                                     host='testhost')

        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['backup'])
        _mock_service_get_all.assert_called_once_with(mock.ANY,
                                                      disabled=False,
                                                      topic='cinder-backup')

        backup.destroy()
        if snapshot:
            snapshot.destroy()
        volume.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_create_incremental_backup_invalid_status(
            self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=5)

        backup = utils.create_backup(self.context, volume.id,
                                     availability_zone='az1', size=1,
                                     host='testhost')
        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "nightlybackups",
                           "incremental": True,
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: The parent backup must be '
                         'available for incremental backup.',
                         res_dict['badRequest']['message'])

        backup.destroy()
        volume.destroy()

    def test_create_backup_with_no_body(self):
        # omit body from the request
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.body = jsonutils.dump_as_bytes(None)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual("None is not of type 'object'",
                         res_dict['badRequest']['message'])

    def test_create_backup_with_body_KeyError(self):
        # omit volume_id from body
        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertIn("'volume_id' is a required property",
                      res_dict['badRequest']['message'])

    def test_create_backup_with_VolumeNotFound(self):
        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": fake.WILL_NOT_BE_FOUND_ID,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Volume %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

    def test_create_backup_with_invalid_volume_id_format(self):
        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": 'not a uuid',
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertIn("'not a uuid' is not a 'uuid'",
                      res_dict['badRequest']['message'])

    def test_create_backup_with_InvalidVolume(self):
        # need to create the volume referenced below first
        volume = utils.create_volume(self.context, size=5, status='restoring')
        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])

    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_WithOUT_enabled_backup_service(
            self,
            _mock_service_get_all):
        # need an enabled backup service available
        _mock_service_get_all.return_value = []

        volume = utils.create_volume(self.context, size=2)
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "nightlybackups",
                           }
                }
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.SERVICE_UNAVAILABLE, res.status_int)
        self.assertEqual(http_client.SERVICE_UNAVAILABLE,
                         res_dict['serviceUnavailable']['code'])
        self.assertEqual('Service cinder-backup could not be found.',
                         res_dict['serviceUnavailable']['message'])

        volume.refresh()
        self.assertEqual('available', volume.status)

    @mock.patch('cinder.db.service_get_all')
    def test_create_incremental_backup_invalid_no_full(
            self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=5, status='available')

        body = {"backup": {"name": "nightly001",
                           "description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume.id,
                           "container": "nightlybackups",
                           "incremental": True,
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: No backups available to do '
                         'an incremental backup.',
                         res_dict['badRequest']['message'])

        volume.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_with_null_validate(self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=5)

        body = {"backup": {"name": None,
                           "description": None,
                           "volume_id": volume.id,
                           "container": "Nonebackups",
                           "snapshot_id": None,
                           }
                }
        req = webob.Request.blank('/v2/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['backup'])
        _mock_service_get_all.assert_called_once_with(mock.ANY,
                                                      disabled=False,
                                                      topic='cinder-backup')
        volume.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_create_backup_with_metadata_null_validate(
            self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'fake_az', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        volume = utils.create_volume(self.context, size=1)

        body = {"backup": {"volume_id": volume.id,
                           "container": "Nonebackups",
                           "metadata": None,
                           }
                }
        req = webob.Request.blank('/v3/%s/backups' % fake.PROJECT_ID)
        req.method = 'POST'
        req.headers = mv.get_mv_header(mv.BACKUP_METADATA)
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertIn('id', res_dict['backup'])
        _mock_service_get_all.assert_called_once_with(mock.ANY,
                                                      disabled=False,
                                                      topic='cinder-backup')
        volume.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_is_backup_service_enabled(self, _mock_service_get_all):

        testhost = 'test_host'
        alt_host = 'strange_host'
        empty_service = []
        # service host not match with volume's host
        host_not_match = [{'availability_zone': 'fake_az', 'host': alt_host,
                           'disabled': 0, 'updated_at': timeutils.utcnow(),
                           'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]
        # service az not match with volume's az
        az_not_match = [{'availability_zone': 'strange_az', 'host': testhost,
                         'disabled': 0, 'updated_at': timeutils.utcnow(),
                         'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e'}]
        # service disabled
        disabled_service = []

        # dead service that last reported at 20th century
        dead_service = [{'availability_zone': 'fake_az', 'host': alt_host,
                         'disabled': 0, 'updated_at': '1989-04-16 02:55:44',
                        'uuid': '6d91e7f5-ca17-4e3b-bf4f-19ca77166dd7'}]

        # first service's host not match but second one works.
        multi_services = [{'availability_zone': 'fake_az', 'host': alt_host,
                           'disabled': 0, 'updated_at': timeutils.utcnow(),
                           'uuid': '18417850-2ca9-43d1-9619-ae16bfb0f655'},
                          {'availability_zone': 'fake_az', 'host': testhost,
                           'disabled': 0, 'updated_at': timeutils.utcnow(),
                           'uuid': 'f838f35c-4035-464f-9792-ce60e390c13d'}]

        # Setup mock to run through the following service cases
        _mock_service_get_all.side_effect = [empty_service,
                                             host_not_match,
                                             az_not_match,
                                             disabled_service,
                                             dead_service,
                                             multi_services]

        volume = utils.create_volume(self.context, size=2, host=testhost)

        # test empty service
        self.assertEqual(False,
                         self.backup_api._is_backup_service_enabled(
                             volume.availability_zone,
                             testhost))

        # test host not match service
        self.assertEqual(False,
                         self.backup_api._is_backup_service_enabled(
                             volume.availability_zone,
                             testhost))

        # test az not match service
        self.assertEqual(False,
                         self.backup_api._is_backup_service_enabled(
                             volume.availability_zone,
                             testhost))

        # test disabled service
        self.assertEqual(False,
                         self.backup_api._is_backup_service_enabled(
                             volume.availability_zone,
                             testhost))

        # test dead service
        self.assertEqual(False,
                         self.backup_api._is_backup_service_enabled(
                             volume.availability_zone,
                             testhost))

        # test multi services and the last service matches
        self.assertTrue(self.backup_api._is_backup_service_enabled(
                        volume.availability_zone,
                        testhost))

    @mock.patch('cinder.db.service_get_all')
    def test_get_available_backup_service(self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost1',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'},
            {'availability_zone': 'az2', 'host': 'testhost2',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e'},
            {'availability_zone': 'az2', 'host': 'testhost3',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': '6d91e7f5-ca17-4e3b-bf4f-19ca77166dd7'}, ]
        actual_host = self.backup_api._get_available_backup_service_host(
            None, 'az1')
        self.assertEqual('testhost1', actual_host)
        actual_host = self.backup_api._get_available_backup_service_host(
            'testhost2', 'az2')
        self.assertIn(actual_host, ['testhost2', 'testhost3'])
        actual_host = self.backup_api._get_available_backup_service_host(
            'testhost4', 'az1')
        self.assertEqual('testhost1', actual_host)

    @mock.patch('cinder.db.service_get_all')
    def test_get_available_backup_service_with_same_host(
            self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost1',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'},
            {'availability_zone': 'az2', 'host': 'testhost2',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': '4200b32b-0bf9-436c-86b2-0675f6ac218e'}, ]
        self.override_config('backup_use_same_host', True)
        actual_host = self.backup_api._get_available_backup_service_host(
            None, 'az1')
        self.assertEqual('testhost1', actual_host)
        actual_host = self.backup_api._get_available_backup_service_host(
            'testhost2', 'az2')
        self.assertEqual('testhost2', actual_host)
        self.assertRaises(exception.ServiceNotFound,
                          self.backup_api._get_available_backup_service_host,
                          'testhost4', 'az1')

    @mock.patch('cinder.db.service_get_all')
    def test_delete_backup_available(self, _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     availability_zone='az1', host='testhost')
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        backup.refresh()
        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(fields.BackupStatus.DELETING,
                         backup.status)

        backup.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_delete_delta_backup(self,
                                 _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     availability_zone='az1', host='testhost')
        delta = utils.create_backup(self.context,
                                    status=fields.BackupStatus.AVAILABLE,
                                    incremental=True,
                                    availability_zone='az1', host='testhost')
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, delta.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        delta.refresh()
        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(fields.BackupStatus.DELETING,
                         delta.status)

        delta.destroy()
        backup.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_delete_backup_error(self,
                                 _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.ERROR,
                                     availability_zone='az1', host='testhost')
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        backup.refresh()
        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(fields.BackupStatus.DELETING,
                         backup.status)

        backup.destroy()

    def test_delete_backup_with_backup_NotFound(self):
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Backup %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

    def test_delete_backup_with_InvalidBackup(self):
        backup = utils.create_backup(self.context)
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: Backup status must be '
                         'available or error',
                         res_dict['badRequest']['message'])

        backup.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_delete_backup_with_InvalidBackup2(self,
                                               _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]
        volume = utils.create_volume(self.context, size=5)
        backup = utils.create_backup(self.context, volume.id,
                                     status=fields.BackupStatus.AVAILABLE)
        delta_backup = utils.create_backup(
            self.context,
            status=fields.BackupStatus.AVAILABLE, incremental=True,
            parent_id=backup.id)

        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: Incremental backups '
                         'exist for this backup.',
                         res_dict['badRequest']['message'])

        delta_backup.destroy()
        backup.destroy()

    @mock.patch('cinder.db.service_get_all')
    def test_delete_backup_service_down(self,
                                        _mock_service_get_all):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost',
             'disabled': 0, 'updated_at': '1775-04-19 05:00:00',
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]
        backup = utils.create_backup(self.context, status='available')
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        self.assertEqual(http_client.NOT_FOUND, res.status_int)

        backup.destroy()

    @mock.patch('cinder.backup.manager.BackupManager.is_working')
    @mock.patch('cinder.db.service_get_all')
    def test_delete_backup_service_is_none_and_is_not_working(
            self, _mock_service_get_all, _mock_backup_is_working):
        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]
        _mock_backup_is_working.return_value = False
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     availability_zone='az1', host='testhost',
                                     service=None)
        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        self.assertEqual(http_client.ACCEPTED, res.status_int)

    @mock.patch('cinder.backup.api.API._get_available_backup_service_host')
    def test_restore_backup_volume_id_specified_json(
            self, _mock_get_backup_host):
        _mock_get_backup_host.return_value = 'testhost'
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     size=1, host='testhost')
        # need to create the volume referenced below first
        volume_name = 'test1'
        volume = utils.create_volume(self.context, size=5,
                                     display_name=volume_name)

        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(backup.id, res_dict['restore']['backup_id'])
        self.assertEqual(volume.id, res_dict['restore']['volume_id'])
        self.assertEqual(volume_name, res_dict['restore']['volume_name'])

    def test_restore_backup_with_no_body(self):
        # omit body from the request
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE)

        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.body = jsonutils.dump_as_bytes(None)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual("None is not of type 'object'",
                         res_dict['badRequest']['message'])

        backup.destroy()

    def test_restore_backup_with_body_KeyError(self):
        # omit restore from body
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE)

        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
            fake.PROJECT_ID, backup.id))
        body = {"restore": {'': ''}}
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))

        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])

        self.assertIn("Additional properties are not allowed ",
                      res_dict['badRequest']['message'])
        self.assertIn("'' was unexpected)",
                      res_dict['badRequest']['message'])

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.volume.api.API.create')
    def test_restore_backup_volume_id_unspecified(
            self, _mock_volume_api_create, _mock_service_get_all):
        # intercept volume creation to ensure created volume
        # has status of available
        def fake_volume_api_create(context, size, name, description):
            volume_id = utils.create_volume(self.context, size=size).id
            return db.volume_get(context, volume_id)

        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]
        _mock_volume_api_create.side_effect = fake_volume_api_create

        backup = utils.create_backup(self.context, size=5,
                                     status=fields.BackupStatus.AVAILABLE,
                                     availability_zone='az1', host='testhost')

        body = {"restore": {}}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(backup.id, res_dict['restore']['backup_id'])

    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.volume.api.API.create')
    def test_restore_backup_name_specified(self,
                                           _mock_volume_api_create,
                                           _mock_service_get_all):
        # Intercept volume creation to ensure created volume
        # has status of available
        def fake_volume_api_create(context, size, name, description):
            volume_id = utils.create_volume(self.context, size=size,
                                            display_name=name).id
            return db.volume_get(context, volume_id)

        _mock_volume_api_create.side_effect = fake_volume_api_create
        _mock_service_get_all.return_value = [
            {'availability_zone': 'az1', 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow(),
             'uuid': 'a3a593da-7f8d-4bb7-8b4c-f2bc1e0b4824'}]

        backup = utils.create_backup(self.context, size=5,
                                     status=fields.BackupStatus.AVAILABLE,
                                     availability_zone='az1', host='testhost')

        body = {"restore": {'name': 'vol-01'}}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' %
                                  (fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        description = 'auto-created_from_restore_from_backup'
        # Assert that we have indeed passed on the name parameter
        _mock_volume_api_create.assert_called_once_with(
            mock.ANY,
            5,
            body['restore']['name'],
            description)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(backup.id, res_dict['restore']['backup_id'])

    @mock.patch('cinder.backup.api.API._get_available_backup_service_host')
    def test_restore_backup_name_volume_id_specified(
            self, _mock_get_backup_host):
        _mock_get_backup_host.return_value = 'testhost'
        backup = utils.create_backup(self.context, size=5,
                                     status=fields.BackupStatus.AVAILABLE)
        orig_vol_name = "vol-00"
        volume = utils.create_volume(self.context, size=5,
                                     display_name=orig_vol_name)
        body = {"restore": {'name': 'vol-01', 'volume_id': volume.id}}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(backup.id, res_dict['restore']['backup_id'])
        self.assertEqual(volume.id, res_dict['restore']['volume_id'])
        restored_vol = db.volume_get(self.context,
                                     res_dict['restore']['volume_id'])
        # Ensure that the original volume name wasn't overridden
        self.assertEqual(orig_vol_name, restored_vol['display_name'])

    @mock.patch('cinder.backup.api.API._get_available_backup_service_host')
    def test_restore_backup_with_null_validate(self, _mock_get_backup_host):
        _mock_get_backup_host.return_value = 'testhost'
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     size=1, host='testhost')
        # need to create the volume referenced below first
        volume = utils.create_volume(self.context, size=1)

        body = {"restore": {"name": None,
                            "volume_id": volume.id}}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(backup.id, res_dict['restore']['backup_id'])

    @mock.patch('cinder.backup.api.API.restore')
    def test_restore_backup_with_InvalidInput(self,
                                              _mock_volume_api_restore):

        msg = _("Invalid input")
        _mock_volume_api_restore.side_effect = \
            exception.InvalidInput(reason=msg)

        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE)
        # need to create the volume referenced below first
        volume = utils.create_volume(self.context, size=0)
        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid input received: Invalid input',
                         res_dict['badRequest']['message'])

    def test_restore_backup_with_InvalidVolume(self):
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE)
        # need to create the volume referenced below first
        volume = utils.create_volume(self.context, size=5, status='attaching')

        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid volume: Volume to be restored to must '
                         'be available',
                         res_dict['badRequest']['message'])

        volume.destroy()
        backup.destroy()

    def test_restore_backup_with_InvalidBackup(self):
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.RESTORING)
        # need to create the volume referenced below first
        volume = utils.create_volume(self.context, size=5)

        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: Backup status must be available',
                         res_dict['badRequest']['message'])

        volume.destroy()
        backup.destroy()

    def test_restore_backup_with_BackupNotFound(self):
        # need to create the volume referenced below first
        volume = utils.create_volume(self.context, size=5)

        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' %
                                  (fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Backup %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

        volume.destroy()

    def test_restore_backup_with_VolumeNotFound(self):
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE)

        body = {"restore": {"volume_id": fake.WILL_NOT_BE_FOUND_ID, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Volume %s could not be found.' %
                         fake.WILL_NOT_BE_FOUND_ID,
                         res_dict['itemNotFound']['message'])

        backup.destroy()

    @mock.patch('cinder.backup.api.API.restore')
    def test_restore_backup_with_VolumeSizeExceedsAvailableQuota(
            self,
            _mock_backup_restore):

        _mock_backup_restore.side_effect = \
            exception.VolumeSizeExceedsAvailableQuota(requested='2',
                                                      consumed='2',
                                                      quota='3')

        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE)
        # need to create the volume referenced below first
        volume = utils.create_volume(self.context, size=5)

        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.REQUEST_ENTITY_TOO_LARGE, res.status_int)
        self.assertEqual(http_client.REQUEST_ENTITY_TOO_LARGE,
                         res_dict['overLimit']['code'])
        self.assertEqual('Requested volume or snapshot exceeds allowed '
                         'gigabytes quota. Requested 2G, quota is 3G and '
                         '2G has been consumed.',
                         res_dict['overLimit']['message'])

    @mock.patch('cinder.backup.api.API.restore')
    def test_restore_backup_with_VolumeLimitExceeded(self,
                                                     _mock_backup_restore):

        _mock_backup_restore.side_effect = \
            exception.VolumeLimitExceeded(allowed=1)

        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE)
        # need to create the volume referenced below first
        volume = utils.create_volume(self.context, size=5)

        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.REQUEST_ENTITY_TOO_LARGE, res.status_int)
        self.assertEqual(http_client.REQUEST_ENTITY_TOO_LARGE,
                         res_dict['overLimit']['code'])
        self.assertEqual("Maximum number of volumes allowed (1) exceeded for"
                         " quota 'volumes'.", res_dict['overLimit']['message'])

    def test_restore_backup_to_undersized_volume(self):
        backup_size = 10
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     size=backup_size)
        # need to create the volume referenced below first
        volume_size = 5
        volume = utils.create_volume(self.context, size=volume_size)

        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid volume: volume size %d is too '
                         'small to restore backup of size %d.'
                         % (volume_size, backup_size),
                         res_dict['badRequest']['message'])

        volume.destroy()
        backup.destroy()

    @mock.patch('cinder.backup.api.API._get_available_backup_service_host')
    def test_restore_backup_to_oversized_volume(self, _mock_get_backup_host):
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     size=10)
        _mock_get_backup_host.return_value = 'testhost'
        # need to create the volume referenced below first
        volume_name = 'test1'
        volume = utils.create_volume(self.context, size=15,
                                     display_name=volume_name)

        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(backup.id, res_dict['restore']['backup_id'])
        self.assertEqual(volume.id, res_dict['restore']['volume_id'])
        self.assertEqual(volume_name, res_dict['restore']['volume_name'])

        volume.destroy()
        backup.destroy()

    @mock.patch('cinder.backup.rpcapi.BackupAPI.restore_backup')
    @mock.patch('cinder.backup.api.API._get_available_backup_service_host')
    def test_restore_backup_with_different_host(self, _mock_get_backup_host,
                                                mock_restore_backup):
        volume_name = 'test1'
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     size=10, host='HostA')
        volume = utils.create_volume(self.context, size=10,
                                     host='HostB@BackendB#PoolB',
                                     display_name=volume_name)

        _mock_get_backup_host.return_value = 'testhost'
        body = {"restore": {"volume_id": volume.id, }}
        req = webob.Request.blank('/v2/%s/backups/%s/restore' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.ACCEPTED, res.status_int)
        self.assertEqual(backup.id, res_dict['restore']['backup_id'])
        self.assertEqual(volume.id, res_dict['restore']['volume_id'])
        self.assertEqual(volume_name, res_dict['restore']['volume_name'])
        mock_restore_backup.assert_called_once_with(mock.ANY, u'testhost',
                                                    mock.ANY, volume.id)
        # Manually check if restore_backup was called with appropriate backup.
        self.assertEqual(backup.id, mock_restore_backup.call_args[0][2].id)

        volume.destroy()
        backup.destroy()

    def test_export_record_as_non_admin(self):
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     size=10)
        req = webob.Request.blank('/v2/%s/backups/%s/export_record' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        # request is not authorized
        self.assertEqual(http_client.FORBIDDEN, res.status_int)

    @mock.patch('cinder.backup.api.API._get_available_backup_service_host')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.export_record')
    def test_export_backup_record_id_specified_json(self,
                                                    _mock_export_record_rpc,
                                                    _mock_get_backup_host):
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE,
                                     size=10)
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'
        _mock_export_record_rpc.return_value = \
            {'backup_service': backup_service,
             'backup_url': backup_url}
        _mock_get_backup_host.return_value = 'testhost'
        req = webob.Request.blank('/v2/%s/backups/%s/export_record' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        # verify that request is successful
        self.assertEqual(http_client.OK, res.status_int)
        self.assertEqual(backup_service,
                         res_dict['backup-record']['backup_service'])
        self.assertEqual(backup_url,
                         res_dict['backup-record']['backup_url'])
        backup.destroy()

    def test_export_record_with_bad_backup_id(self):

        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        backup_id = fake.WILL_NOT_BE_FOUND_ID
        req = webob.Request.blank('/v2/%s/backups/%s/export_record' %
                                  (fake.PROJECT_ID, backup_id))
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.NOT_FOUND, res.status_int)
        self.assertEqual(http_client.NOT_FOUND,
                         res_dict['itemNotFound']['code'])
        self.assertEqual('Backup %s could not be found.' % backup_id,
                         res_dict['itemNotFound']['message'])

    def test_export_record_for_unavailable_backup(self):

        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.RESTORING)
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        req = webob.Request.blank('/v2/%s/backups/%s/export_record' %
                                  (fake.PROJECT_ID, backup.id))
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: Backup status must be available '
                         'and not restoring.',
                         res_dict['badRequest']['message'])
        backup.destroy()

    @mock.patch('cinder.backup.api.API._get_available_backup_service_host')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.export_record')
    def test_export_record_with_unavailable_service(self,
                                                    _mock_export_record_rpc,
                                                    _mock_get_backup_host):
        msg = 'fake unavailable service'
        _mock_export_record_rpc.side_effect = \
            exception.InvalidBackup(reason=msg)
        _mock_get_backup_host.return_value = 'testhost'
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE)
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        req = webob.Request.blank('/v2/%s/backups/%s/export_record' %
                                  (fake.PROJECT_ID, backup.id))
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: %s' % msg,
                         res_dict['badRequest']['message'])
        backup.destroy()

    def test_import_record_as_non_admin(self):
        backup_service = 'fake'
        backup_url = 'fake'
        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        # request is not authorized
        self.assertEqual(http_client.FORBIDDEN, res.status_int)

    @mock.patch.object(quota.QUOTAS, 'commit')
    @mock.patch.object(quota.QUOTAS, 'rollback')
    @mock.patch.object(quota.QUOTAS, 'reserve')
    @mock.patch('cinder.backup.api.API._list_backup_hosts')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.import_record')
    def test_import_record_volume_id_specified_json(self,
                                                    _mock_import_record_rpc,
                                                    _mock_list_services,
                                                    mock_reserve,
                                                    mock_rollback,
                                                    mock_commit):
        utils.replace_obj_loader(self, objects.Backup)
        mock_reserve.return_value = "fake_reservation"
        project_id = fake.PROJECT_ID
        backup_service = 'fake'
        ctx = context.RequestContext(fake.USER_ID, project_id, is_admin=True)
        backup = objects.Backup(ctx, id=fake.BACKUP_ID, user_id=fake.USER_ID,
                                project_id=project_id,
                                size=1,
                                status=fields.BackupStatus.AVAILABLE)
        backup_url = backup.encode_record()
        _mock_import_record_rpc.return_value = None
        _mock_list_services.return_value = [backup_service]

        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)

        # verify that request is successful
        self.assertEqual(http_client.CREATED, res.status_int)
        self.assertIn('id', res_dict['backup'])
        self.assertEqual(fake.BACKUP_ID, res_dict['backup']['id'])

        # Verify that entry in DB is as expected
        db_backup = objects.Backup.get_by_id(ctx, fake.BACKUP_ID)
        self.assertEqual(ctx.project_id, db_backup.project_id)
        self.assertEqual(ctx.user_id, db_backup.user_id)
        self.assertEqual(backup_api.IMPORT_VOLUME_ID, db_backup.volume_id)
        self.assertEqual(fields.BackupStatus.CREATING, db_backup.status)
        mock_reserve.assert_called_with(
            ctx, backups=1, backup_gigabytes=1)
        mock_commit.assert_called_with(ctx, "fake_reservation")

    @mock.patch.object(quota.QUOTAS, 'commit')
    @mock.patch.object(quota.QUOTAS, 'rollback')
    @mock.patch.object(quota.QUOTAS, 'reserve')
    @mock.patch('cinder.backup.api.API._list_backup_hosts')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.import_record')
    def test_import_record_volume_id_exists_deleted(self,
                                                    _mock_import_record_rpc,
                                                    _mock_list_services,
                                                    mock_reserve,
                                                    mock_rollback,
                                                    mock_commit,
                                                    ):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        mock_reserve.return_value = 'fake_reservation'
        utils.replace_obj_loader(self, objects.Backup)

        # Original backup belonged to a different user_id and project_id
        backup = objects.Backup(ctx, id=fake.BACKUP_ID, user_id=fake.USER2_ID,
                                project_id=fake.PROJECT2_ID,
                                size=1,
                                status=fields.BackupStatus.AVAILABLE)
        backup_url = backup.encode_record()

        # Deleted DB entry has project_id and user_id set to fake
        backup_del = utils.create_backup(self.context, fake.VOLUME_ID,
                                         status=fields.BackupStatus.DELETED)
        backup_service = 'fake'
        _mock_import_record_rpc.return_value = None
        _mock_list_services.return_value = [backup_service]

        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)

        # verify that request is successful
        self.assertEqual(http_client.CREATED, res.status_int)
        self.assertIn('id', res_dict['backup'])
        self.assertEqual(fake.BACKUP_ID, res_dict['backup']['id'])

        # Verify that entry in DB is as expected, with new project and user_id
        db_backup = objects.Backup.get_by_id(ctx, fake.BACKUP_ID)
        self.assertEqual(ctx.project_id, db_backup.project_id)
        self.assertEqual(ctx.user_id, db_backup.user_id)
        self.assertEqual(backup_api.IMPORT_VOLUME_ID, db_backup.volume_id)
        self.assertEqual(fields.BackupStatus.CREATING, db_backup.status)
        mock_reserve.assert_called_with(ctx, backups=1, backup_gigabytes=1)
        mock_commit.assert_called_with(ctx, "fake_reservation")

        backup_del.destroy()

    @mock.patch('cinder.backup.api.API._list_backup_hosts')
    def test_import_record_with_no_backup_services(self,
                                                   _mock_list_services):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'
        _mock_list_services.return_value = []

        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.SERVICE_UNAVAILABLE, res.status_int)
        self.assertEqual(http_client.SERVICE_UNAVAILABLE,
                         res_dict['serviceUnavailable']['code'])
        self.assertEqual('Service %s could not be found.'
                         % backup_service,
                         res_dict['serviceUnavailable']['message'])

    @mock.patch('cinder.backup.api.API._list_backup_hosts')
    def test_import_backup_with_wrong_backup_url(self, _mock_list_services):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'
        _mock_list_services.return_value = ['no-match1', 'no-match2']
        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual("Invalid input received: Can't parse backup record.",
                         res_dict['badRequest']['message'])

    @mock.patch.object(quota.QUOTAS, 'commit')
    @mock.patch.object(quota.QUOTAS, 'rollback')
    @mock.patch.object(quota.QUOTAS, 'reserve')
    @mock.patch('cinder.backup.api.API._list_backup_hosts')
    def test_import_backup_with_existing_backup_record(self,
                                                       _mock_list_services,
                                                       mock_reserve,
                                                       mock_rollback,
                                                       mock_commit):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        mock_reserve.return_value = "fake_reservation"
        backup = utils.create_backup(self.context, fake.VOLUME_ID, size=1)
        backup_service = 'fake'
        backup_url = backup.encode_record()
        _mock_list_services.return_value = ['no-match1', 'no-match2']
        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: Backup already exists in database.',
                         res_dict['badRequest']['message'])
        mock_reserve.assert_called_with(
            ctx, backups=1, backup_gigabytes=1)
        mock_rollback.assert_called_with(ctx, "fake_reservation")
        backup.destroy()

    @mock.patch.object(quota.QUOTAS, 'commit')
    @mock.patch.object(quota.QUOTAS, 'rollback')
    @mock.patch.object(quota.QUOTAS, 'reserve')
    @mock.patch('cinder.backup.api.API._list_backup_hosts')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.import_record')
    def test_import_backup_with_missing_backup_services(self,
                                                        mock_reserve,
                                                        mock_rollback,
                                                        mock_commit,
                                                        _mock_import_record,
                                                        _mock_list_services):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        backup = utils.create_backup(self.context, fake.VOLUME_ID,
                                     status=fields.BackupStatus.DELETED)
        backup_service = 'fake'
        backup_url = backup.encode_record()
        _mock_list_services.return_value = ['no-match1', 'no-match2']
        _mock_import_record.side_effect = \
            exception.ServiceNotFound(service_id='fake')
        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.SERVICE_UNAVAILABLE, res.status_int)
        self.assertEqual(http_client.SERVICE_UNAVAILABLE,
                         res_dict['serviceUnavailable']['code'])
        self.assertEqual('Service %s could not be found.' % backup_service,
                         res_dict['serviceUnavailable']['message'])

        backup.destroy()

    def test_import_record_with_missing_body_elements(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'

        # test with no backup_service
        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {'backup_url': backup_url}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        if six.PY3:
            self.assertEqual(
                "Invalid input for field/attribute backup-record. "
                "Value: {'backup_url': 'fake'}. 'backup_service' "
                "is a required property",
                res_dict['badRequest']['message'])
        else:
            self.assertEqual(
                "Invalid input for field/attribute backup-record. "
                "Value: {u'backup_url': u'fake'}. 'backup_service' "
                "is a required property",
                res_dict['badRequest']['message'])

        # test with no backup_url
        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {'backup_service': backup_service}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        if six.PY3:
            self.assertEqual(
                "Invalid input for field/attribute backup-record. "
                "Value: {'backup_service': 'fake'}. 'backup_url' "
                "is a required property",
                res_dict['badRequest']['message'])
        else:
            self.assertEqual(
                "Invalid input for field/attribute backup-record. "
                "Value: {u'backup_service': u'fake'}. 'backup_url' "
                "is a required property",
                res_dict['badRequest']['message'])

        # test with no backup_url and backup_url
        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        body = {'backup-record': {}}
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual(
            "Invalid input for field/attribute backup-record. "
            "Value: {}. 'backup_service' is a required property",
            res_dict['badRequest']['message'])

    def test_import_record_with_no_body(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                     is_admin=True)

        req = webob.Request.blank('/v2/%s/backups/import_record' %
                                  fake.PROJECT_ID)
        req.body = jsonutils.dump_as_bytes(None)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = jsonutils.loads(res.body)
        # verify that request is successful
        self.assertEqual(http_client.BAD_REQUEST, res.status_int)
        self.assertEqual(http_client.BAD_REQUEST,
                         res_dict['badRequest']['code'])
        self.assertEqual("None is not of type 'object'",
                         res_dict['badRequest']['message'])

    @mock.patch('cinder.backup.rpcapi.BackupAPI.check_support_to_force_delete',
                return_value=False)
    def test_force_delete_with_not_supported_operation(self,
                                                       mock_check_support):
        backup = utils.create_backup(self.context,
                                     status=fields.BackupStatus.AVAILABLE)
        self.assertRaises(exception.NotSupportedOperation,
                          self.backup_api.delete, self.context, backup, True)

    @ddt.data(False, True)
    def test_show_incremental_backup(self, backup_from_snapshot):
        volume = utils.create_volume(self.context, size=5)
        parent_backup = utils.create_backup(
            self.context, volume.id, status=fields.BackupStatus.AVAILABLE,
            num_dependent_backups=1)
        backup = utils.create_backup(self.context, volume.id,
                                     status=fields.BackupStatus.AVAILABLE,
                                     incremental=True,
                                     parent_id=parent_backup.id,
                                     num_dependent_backups=1)
        snapshot = None
        snapshot_id = None
        if backup_from_snapshot:
            snapshot = utils.create_snapshot(self.context,
                                             volume.id)
            snapshot_id = snapshot.id
        child_backup = utils.create_backup(
            self.context, volume.id, status=fields.BackupStatus.AVAILABLE,
            incremental=True, parent_id=backup.id, snapshot_id=snapshot_id)

        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, backup.id))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertTrue(res_dict['backup']['is_incremental'])
        self.assertTrue(res_dict['backup']['has_dependent_backups'])
        self.assertIsNone(res_dict['backup']['snapshot_id'])

        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, parent_backup.id))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertFalse(res_dict['backup']['is_incremental'])
        self.assertTrue(res_dict['backup']['has_dependent_backups'])
        self.assertIsNone(res_dict['backup']['snapshot_id'])

        req = webob.Request.blank('/v2/%s/backups/%s' % (
                                  fake.PROJECT_ID, child_backup.id))
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(
            fake_auth_context=self.user_context))
        res_dict = jsonutils.loads(res.body)

        self.assertEqual(http_client.OK, res.status_int)
        self.assertTrue(res_dict['backup']['is_incremental'])
        self.assertFalse(res_dict['backup']['has_dependent_backups'])
        self.assertEqual(snapshot_id, res_dict['backup']['snapshot_id'])

        child_backup.destroy()
        backup.destroy()
        parent_backup.destroy()
        if snapshot:
            snapshot.destroy()
        volume.destroy()
