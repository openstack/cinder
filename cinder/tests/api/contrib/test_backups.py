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

import json
from xml.dom import minidom

import mock
from oslo_log import log as logging
from oslo_utils import timeutils
import webob

# needed for stubs to work
import cinder.backup
from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import test
from cinder.tests.api import fakes
from cinder.tests import utils
# needed for stubs to work
import cinder.volume


LOG = logging.getLogger(__name__)


class BackupsAPITestCase(test.TestCase):
    """Test Case for backups API."""

    def setUp(self):
        super(BackupsAPITestCase, self).setUp()
        self.volume_api = cinder.volume.API()
        self.backup_api = cinder.backup.API()
        self.context = context.get_admin_context()
        self.context.project_id = 'fake'
        self.context.user_id = 'fake'

    @staticmethod
    def _create_backup(volume_id=1,
                       display_name='test_backup',
                       display_description='this is a test backup',
                       container='volumebackups',
                       status='creating',
                       snapshot=False,
                       incremental=False,
                       parent_id=None,
                       size=0, object_count=0, host='testhost'):
        """Create a backup object."""
        backup = {}
        backup['volume_id'] = volume_id
        backup['user_id'] = 'fake'
        backup['project_id'] = 'fake'
        backup['host'] = host
        backup['availability_zone'] = 'az1'
        backup['display_name'] = display_name
        backup['display_description'] = display_description
        backup['container'] = container
        backup['status'] = status
        backup['fail_reason'] = ''
        backup['size'] = size
        backup['object_count'] = object_count
        backup['snapshot'] = snapshot
        backup['incremental'] = incremental
        backup['parent_id'] = parent_id
        return db.backup_create(context.get_admin_context(), backup)['id']

    @staticmethod
    def _get_backup_attrib(backup_id, attrib_name):
        return db.backup_get(context.get_admin_context(),
                             backup_id)[attrib_name]

    def test_show_backup(self):
        volume_id = utils.create_volume(self.context, size=5,
                                        status='creating')['id']
        backup_id = self._create_backup(volume_id)
        LOG.debug('Created backup with id %s' % backup_id)
        req = webob.Request.blank('/v2/fake/backups/%s' %
                                  backup_id)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['backup']['availability_zone'], 'az1')
        self.assertEqual(res_dict['backup']['container'], 'volumebackups')
        self.assertEqual(res_dict['backup']['description'],
                         'this is a test backup')
        self.assertEqual(res_dict['backup']['name'], 'test_backup')
        self.assertEqual(res_dict['backup']['id'], backup_id)
        self.assertEqual(res_dict['backup']['object_count'], 0)
        self.assertEqual(res_dict['backup']['size'], 0)
        self.assertEqual(res_dict['backup']['status'], 'creating')
        self.assertEqual(res_dict['backup']['volume_id'], volume_id)

        db.backup_destroy(context.get_admin_context(), backup_id)
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_show_backup_xml_content_type(self):
        volume_id = utils.create_volume(self.context, size=5,
                                        status='creating')['id']
        backup_id = self._create_backup(volume_id)
        req = webob.Request.blank('/v2/fake/backups/%s' % backup_id)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        backup = dom.getElementsByTagName('backup')
        name = backup.item(0).getAttribute('name')
        container_name = backup.item(0).getAttribute('container')
        self.assertEqual(container_name.strip(), "volumebackups")
        self.assertEqual(name.strip(), "test_backup")
        db.backup_destroy(context.get_admin_context(), backup_id)
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_show_backup_with_backup_NotFound(self):
        req = webob.Request.blank('/v2/fake/backups/9999')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Backup 9999 could not be found.')

    def test_list_backups_json(self):
        backup_id1 = self._create_backup()
        backup_id2 = self._create_backup()
        backup_id3 = self._create_backup()

        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res_dict['backups'][0]), 3)
        self.assertEqual(res_dict['backups'][0]['id'], backup_id1)
        self.assertEqual(res_dict['backups'][0]['name'], 'test_backup')
        self.assertEqual(len(res_dict['backups'][1]), 3)
        self.assertEqual(res_dict['backups'][1]['id'], backup_id2)
        self.assertEqual(res_dict['backups'][1]['name'], 'test_backup')
        self.assertEqual(len(res_dict['backups'][2]), 3)
        self.assertEqual(res_dict['backups'][2]['id'], backup_id3)
        self.assertEqual(res_dict['backups'][2]['name'], 'test_backup')

        db.backup_destroy(context.get_admin_context(), backup_id3)
        db.backup_destroy(context.get_admin_context(), backup_id2)
        db.backup_destroy(context.get_admin_context(), backup_id1)

    def test_list_backups_xml(self):
        backup_id1 = self._create_backup()
        backup_id2 = self._create_backup()
        backup_id3 = self._create_backup()

        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        backup_list = dom.getElementsByTagName('backup')

        self.assertEqual(backup_list.item(0).attributes.length, 2)
        self.assertEqual(backup_list.item(0).getAttribute('id'),
                         backup_id1)
        self.assertEqual(backup_list.item(1).attributes.length, 2)
        self.assertEqual(backup_list.item(1).getAttribute('id'),
                         backup_id2)
        self.assertEqual(backup_list.item(2).attributes.length, 2)
        self.assertEqual(backup_list.item(2).getAttribute('id'),
                         backup_id3)

        db.backup_destroy(context.get_admin_context(), backup_id3)
        db.backup_destroy(context.get_admin_context(), backup_id2)
        db.backup_destroy(context.get_admin_context(), backup_id1)

    def test_list_backups_detail_json(self):
        backup_id1 = self._create_backup()
        backup_id2 = self._create_backup()
        backup_id3 = self._create_backup()

        req = webob.Request.blank('/v2/fake/backups/detail')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res_dict['backups'][0]), 12)
        self.assertEqual(res_dict['backups'][0]['availability_zone'], 'az1')
        self.assertEqual(res_dict['backups'][0]['container'],
                         'volumebackups')
        self.assertEqual(res_dict['backups'][0]['description'],
                         'this is a test backup')
        self.assertEqual(res_dict['backups'][0]['name'],
                         'test_backup')
        self.assertEqual(res_dict['backups'][0]['id'], backup_id1)
        self.assertEqual(res_dict['backups'][0]['object_count'], 0)
        self.assertEqual(res_dict['backups'][0]['size'], 0)
        self.assertEqual(res_dict['backups'][0]['status'], 'creating')
        self.assertEqual(res_dict['backups'][0]['volume_id'], '1')

        self.assertEqual(len(res_dict['backups'][1]), 12)
        self.assertEqual(res_dict['backups'][1]['availability_zone'], 'az1')
        self.assertEqual(res_dict['backups'][1]['container'],
                         'volumebackups')
        self.assertEqual(res_dict['backups'][1]['description'],
                         'this is a test backup')
        self.assertEqual(res_dict['backups'][1]['name'],
                         'test_backup')
        self.assertEqual(res_dict['backups'][1]['id'], backup_id2)
        self.assertEqual(res_dict['backups'][1]['object_count'], 0)
        self.assertEqual(res_dict['backups'][1]['size'], 0)
        self.assertEqual(res_dict['backups'][1]['status'], 'creating')
        self.assertEqual(res_dict['backups'][1]['volume_id'], '1')

        self.assertEqual(len(res_dict['backups'][2]), 12)
        self.assertEqual(res_dict['backups'][2]['availability_zone'], 'az1')
        self.assertEqual(res_dict['backups'][2]['container'],
                         'volumebackups')
        self.assertEqual(res_dict['backups'][2]['description'],
                         'this is a test backup')
        self.assertEqual(res_dict['backups'][2]['name'],
                         'test_backup')
        self.assertEqual(res_dict['backups'][2]['id'], backup_id3)
        self.assertEqual(res_dict['backups'][2]['object_count'], 0)
        self.assertEqual(res_dict['backups'][2]['size'], 0)
        self.assertEqual(res_dict['backups'][2]['status'], 'creating')
        self.assertEqual(res_dict['backups'][2]['volume_id'], '1')

        db.backup_destroy(context.get_admin_context(), backup_id3)
        db.backup_destroy(context.get_admin_context(), backup_id2)
        db.backup_destroy(context.get_admin_context(), backup_id1)

    def test_list_backups_detail_using_filters(self):
        backup_id1 = self._create_backup(display_name='test2')
        backup_id2 = self._create_backup(status='available')
        backup_id3 = self._create_backup(volume_id=4321)

        req = webob.Request.blank('/v2/fake/backups/detail?name=test2')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(len(res_dict['backups']), 1)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['backups'][0]['id'], backup_id1)

        req = webob.Request.blank('/v2/fake/backups/detail?status=available')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(len(res_dict['backups']), 1)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['backups'][0]['id'], backup_id2)

        req = webob.Request.blank('/v2/fake/backups/detail?volume_id=4321')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(len(res_dict['backups']), 1)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['backups'][0]['id'], backup_id3)

        db.backup_destroy(context.get_admin_context(), backup_id3)
        db.backup_destroy(context.get_admin_context(), backup_id2)
        db.backup_destroy(context.get_admin_context(), backup_id1)

    def test_list_backups_detail_xml(self):
        backup_id1 = self._create_backup()
        backup_id2 = self._create_backup()
        backup_id3 = self._create_backup()

        req = webob.Request.blank('/v2/fake/backups/detail')
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        backup_detail = dom.getElementsByTagName('backup')

        self.assertEqual(backup_detail.item(0).attributes.length, 11)
        self.assertEqual(
            backup_detail.item(0).getAttribute('availability_zone'), 'az1')
        self.assertEqual(
            backup_detail.item(0).getAttribute('container'), 'volumebackups')
        self.assertEqual(
            backup_detail.item(0).getAttribute('description'),
            'this is a test backup')
        self.assertEqual(
            backup_detail.item(0).getAttribute('name'), 'test_backup')
        self.assertEqual(
            backup_detail.item(0).getAttribute('id'), backup_id1)
        self.assertEqual(
            int(backup_detail.item(0).getAttribute('object_count')), 0)
        self.assertEqual(
            int(backup_detail.item(0).getAttribute('size')), 0)
        self.assertEqual(
            backup_detail.item(0).getAttribute('status'), 'creating')
        self.assertEqual(
            int(backup_detail.item(0).getAttribute('volume_id')), 1)

        self.assertEqual(backup_detail.item(1).attributes.length, 11)
        self.assertEqual(
            backup_detail.item(1).getAttribute('availability_zone'), 'az1')
        self.assertEqual(
            backup_detail.item(1).getAttribute('container'), 'volumebackups')
        self.assertEqual(
            backup_detail.item(1).getAttribute('description'),
            'this is a test backup')
        self.assertEqual(
            backup_detail.item(1).getAttribute('name'), 'test_backup')
        self.assertEqual(
            backup_detail.item(1).getAttribute('id'), backup_id2)
        self.assertEqual(
            int(backup_detail.item(1).getAttribute('object_count')), 0)
        self.assertEqual(
            int(backup_detail.item(1).getAttribute('size')), 0)
        self.assertEqual(
            backup_detail.item(1).getAttribute('status'), 'creating')
        self.assertEqual(
            int(backup_detail.item(1).getAttribute('volume_id')), 1)

        self.assertEqual(backup_detail.item(2).attributes.length, 11)
        self.assertEqual(
            backup_detail.item(2).getAttribute('availability_zone'), 'az1')
        self.assertEqual(
            backup_detail.item(2).getAttribute('container'), 'volumebackups')
        self.assertEqual(
            backup_detail.item(2).getAttribute('description'),
            'this is a test backup')
        self.assertEqual(
            backup_detail.item(2).getAttribute('name'), 'test_backup')
        self.assertEqual(
            backup_detail.item(2).getAttribute('id'), backup_id3)
        self.assertEqual(
            int(backup_detail.item(2).getAttribute('object_count')), 0)
        self.assertEqual(
            int(backup_detail.item(2).getAttribute('size')), 0)
        self.assertEqual(
            backup_detail.item(2).getAttribute('status'), 'creating')
        self.assertEqual(
            int(backup_detail.item(2).getAttribute('volume_id')), 1)

        db.backup_destroy(context.get_admin_context(), backup_id3)
        db.backup_destroy(context.get_admin_context(), backup_id2)
        db.backup_destroy(context.get_admin_context(), backup_id1)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_create_backup_json(self, _mock_service_get_all_by_topic):
        _mock_service_get_all_by_topic.return_value = [
            {'availability_zone': "fake_az", 'host': 'test_host',
             'disabled': 0, 'updated_at': timeutils.utcnow()}]

        volume_id = utils.create_volume(self.context, size=5)['id']

        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume_id,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        res_dict = json.loads(res.body)
        LOG.info(res_dict)

        self.assertEqual(res.status_int, 202)
        self.assertIn('id', res_dict['backup'])
        self.assertTrue(_mock_service_get_all_by_topic.called)

        db.volume_destroy(context.get_admin_context(), volume_id)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_create_backup_snapshot_json(self, _mock_service_get_all_by_topic):
        _mock_service_get_all_by_topic.return_value = [
            {'availability_zone': "fake_az", 'host': 'test_host',
             'disabled': 0, 'updated_at': timeutils.utcnow()}]

        volume_id = utils.create_volume(self.context, size=5,
                                        status='available')['id']

        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume_id,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        res_dict = json.loads(res.body)
        LOG.info(res_dict)
        self.assertEqual(res.status_int, 202)
        self.assertIn('id', res_dict['backup'])
        self.assertTrue(_mock_service_get_all_by_topic.called)

        db.volume_destroy(context.get_admin_context(), volume_id)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_create_backup_xml(self, _mock_service_get_all_by_topic):
        _mock_service_get_all_by_topic.return_value = [
            {'availability_zone': "fake_az", 'host': 'test_host',
             'disabled': 0, 'updated_at': timeutils.utcnow()}]

        volume_id = utils.create_volume(self.context, size=2)['id']

        req = webob.Request.blank('/v2/fake/backups')
        req.body = ('<backup display_name="backup-001" '
                    'display_description="Nightly Backup" '
                    'volume_id="%s" container="Container001"/>' % volume_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        dom = minidom.parseString(res.body)
        backup = dom.getElementsByTagName('backup')
        self.assertTrue(backup.item(0).hasAttribute('id'))
        self.assertTrue(_mock_service_get_all_by_topic.called)

        db.volume_destroy(context.get_admin_context(), volume_id)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_create_backup_delta(self, _mock_service_get_all_by_topic):
        _mock_service_get_all_by_topic.return_value = [
            {'availability_zone': "fake_az", 'host': 'test_host',
             'disabled': 0, 'updated_at': timeutils.utcnow()}]

        volume_id = utils.create_volume(self.context, size=5)['id']

        backup_id = self._create_backup(volume_id, status="available")
        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume_id,
                           "container": "nightlybackups",
                           "incremental": True,
                           }
                }
        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        LOG.info(res_dict)

        self.assertEqual(202, res.status_int)
        self.assertIn('id', res_dict['backup'])
        self.assertTrue(_mock_service_get_all_by_topic.called)

        db.backup_destroy(context.get_admin_context(), backup_id)
        db.volume_destroy(context.get_admin_context(), volume_id)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_create_incremental_backup_invalid_status(
            self, _mock_service_get_all_by_topic):
        _mock_service_get_all_by_topic.return_value = [
            {'availability_zone': "fake_az", 'host': 'test_host',
             'disabled': 0, 'updated_at': timeutils.utcnow()}]

        volume_id = utils.create_volume(self.context, size=5)['id']

        backup_id = self._create_backup(volume_id)
        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume_id,
                           "container": "nightlybackups",
                           "incremental": True,
                           }
                }
        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        LOG.info(res_dict)

        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: The parent backup must be '
                         'available for incremental backup.',
                         res_dict['badRequest']['message'])

        db.backup_destroy(context.get_admin_context(), backup_id)
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_create_backup_with_no_body(self):
        # omit body from the request
        req = webob.Request.blank('/v2/fake/backups')
        req.body = json.dumps(None)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'The server could not comply with the request since'
                         ' it is either malformed or otherwise incorrect.')

    def test_create_backup_with_body_KeyError(self):
        # omit volume_id from body
        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Incorrect request body format')

    def test_create_backup_with_VolumeNotFound(self):
        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": 9999,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Volume 9999 could not be found.')

    def test_create_backup_with_InvalidVolume(self):
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=5,
                                        status='restoring')['id']
        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume_id,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid volume: Volume to be backed up must'
                         ' be available')

    def test_create_backup_with_InvalidVolume2(self):
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=5,
                                        status='in-use')['id']
        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume_id,
                           "container": "nightlybackups",
                           }
                }
        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid volume: Volume to be backed up must'
                         ' be available')

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_create_backup_WithOUT_enabled_backup_service(
            self,
            _mock_service_get_all_by_topic):
        # need an enabled backup service available
        _mock_service_get_all_by_topic.return_value = []

        volume_id = utils.create_volume(self.context, size=2)['id']
        req = webob.Request.blank('/v2/fake/backups')
        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume_id,
                           "container": "nightlybackups",
                           }
                }
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        req.body = json.dumps(body)

        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 500)
        self.assertEqual(res_dict['computeFault']['code'], 500)
        self.assertEqual(res_dict['computeFault']['message'],
                         'Service cinder-backup could not be found.')

        volume = self.volume_api.get(context.get_admin_context(), volume_id)
        self.assertEqual(volume['status'], 'available')

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_create_incremental_backup_invalid_no_full(
            self, _mock_service_get_all_by_topic):
        _mock_service_get_all_by_topic.return_value = [
            {'availability_zone': "fake_az", 'host': 'test_host',
             'disabled': 0, 'updated_at': timeutils.utcnow()}]

        volume_id = utils.create_volume(self.context, size=5,
                                        status='available')['id']

        body = {"backup": {"display_name": "nightly001",
                           "display_description":
                           "Nightly Backup 03-Sep-2012",
                           "volume_id": volume_id,
                           "container": "nightlybackups",
                           "incremental": True,
                           }
                }
        req = webob.Request.blank('/v2/fake/backups')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        LOG.info(res_dict)

        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: No backups available to do '
                         'an incremental backup.',
                         res_dict['badRequest']['message'])

        db.volume_destroy(context.get_admin_context(), volume_id)

    @mock.patch('cinder.db.service_get_all_by_topic')
    def test_is_backup_service_enabled(self, _mock_service_get_all_by_topic):

        test_host = 'test_host'
        alt_host = 'strange_host'
        empty_service = []
        # service host not match with volume's host
        host_not_match = [{'availability_zone': "fake_az", 'host': alt_host,
                           'disabled': 0, 'updated_at': timeutils.utcnow()}]
        # service az not match with volume's az
        az_not_match = [{'availability_zone': "strange_az", 'host': test_host,
                         'disabled': 0, 'updated_at': timeutils.utcnow()}]
        # service disabled
        disabled_service = []

        # dead service that last reported at 20th century
        dead_service = [{'availability_zone': "fake_az", 'host': alt_host,
                         'disabled': 0, 'updated_at': '1989-04-16 02:55:44'}]

        # first service's host not match but second one works.
        multi_services = [{'availability_zone': "fake_az", 'host': alt_host,
                           'disabled': 0, 'updated_at': timeutils.utcnow()},
                          {'availability_zone': "fake_az", 'host': test_host,
                           'disabled': 0, 'updated_at': timeutils.utcnow()}]

        # Setup mock to run through the following service cases
        _mock_service_get_all_by_topic.side_effect = [empty_service,
                                                      host_not_match,
                                                      az_not_match,
                                                      disabled_service,
                                                      dead_service,
                                                      multi_services]

        volume_id = utils.create_volume(self.context, size=2,
                                        host=test_host)['id']
        volume = self.volume_api.get(context.get_admin_context(), volume_id)

        # test empty service
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        # test host not match service
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        # test az not match service
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        # test disabled service
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        # test dead service
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        # test multi services and the last service matches
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         True)

    def test_delete_backup_available(self):
        backup_id = self._create_backup(status='available')
        req = webob.Request.blank('/v2/fake/backups/%s' %
                                  backup_id)
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        self.assertEqual(self._get_backup_attrib(backup_id, 'status'),
                         'deleting')

        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_delete_delta_backup(self):
        backup_id = self._create_backup(status='available')
        delta_id = self._create_backup(status='available',
                                       incremental=True)
        req = webob.Request.blank('/v2/fake/backups/%s' %
                                  delta_id)
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(202, res.status_int)
        self.assertEqual('deleting',
                         self._get_backup_attrib(delta_id, 'status'))

        db.backup_destroy(context.get_admin_context(), delta_id)
        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_delete_backup_error(self):
        backup_id = self._create_backup(status='error')
        req = webob.Request.blank('/v2/fake/backups/%s' %
                                  backup_id)
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        self.assertEqual(self._get_backup_attrib(backup_id, 'status'),
                         'deleting')

        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_delete_backup_with_backup_NotFound(self):
        req = webob.Request.blank('/v2/fake/backups/9999')
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Backup 9999 could not be found.')

    def test_delete_backup_with_InvalidBackup(self):
        backup_id = self._create_backup()
        req = webob.Request.blank('/v2/fake/backups/%s' %
                                  backup_id)
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid backup: Backup status must be '
                         'available or error')

        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_delete_backup_with_InvalidBackup2(self):
        volume_id = utils.create_volume(self.context, size=5)['id']
        backup_id = self._create_backup(volume_id, status="available")
        delta_backup_id = self._create_backup(status='available',
                                              incremental=True,
                                              parent_id=backup_id)

        req = webob.Request.blank('/v2/fake/backups/%s' %
                                  backup_id)
        req.method = 'DELETE'
        req.headers['Content-Type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)
        self.assertEqual(400, res.status_int)
        self.assertEqual(400, res_dict['badRequest']['code'])
        self.assertEqual('Invalid backup: Incremental backups '
                         'exist for this backup.',
                         res_dict['badRequest']['message'])

        db.backup_destroy(context.get_admin_context(), delta_backup_id)
        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_restore_backup_volume_id_specified_json(self):
        backup_id = self._create_backup(status='available')
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=5)['id']

        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 202)
        self.assertEqual(res_dict['restore']['backup_id'], backup_id)
        self.assertEqual(res_dict['restore']['volume_id'], volume_id)

    def test_restore_backup_volume_id_specified_xml(self):
        backup_id = self._create_backup(status='available')
        volume_id = utils.create_volume(self.context, size=2)['id']

        req = webob.Request.blank('/v2/fake/backups/%s/restore' % backup_id)
        req.body = '<restore volume_id="%s"/>' % volume_id
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app())

        self.assertEqual(res.status_int, 202)
        dom = minidom.parseString(res.body)
        restore = dom.getElementsByTagName('restore')
        self.assertEqual(restore.item(0).getAttribute('backup_id'),
                         backup_id)
        self.assertEqual(restore.item(0).getAttribute('volume_id'), volume_id)

        db.backup_destroy(context.get_admin_context(), backup_id)
        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_restore_backup_with_no_body(self):
        # omit body from the request
        backup_id = self._create_backup(status='available')

        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)
        req.body = json.dumps(None)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Incorrect request body format')

        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_restore_backup_with_body_KeyError(self):
        # omit restore from body
        backup_id = self._create_backup(status='available')

        req = webob.Request.blank('/v2/fake/backups/%s/restore' % backup_id)
        body = {"": {}}
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.headers['Accept'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())

        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Incorrect request body format')

    @mock.patch('cinder.volume.API.create')
    def test_restore_backup_volume_id_unspecified(self,
                                                  _mock_volume_api_create):

        # intercept volume creation to ensure created volume
        # has status of available
        def fake_volume_api_create(context, size, name, description):
            volume_id = utils.create_volume(self.context, size=size)['id']
            return db.volume_get(context, volume_id)

        _mock_volume_api_create.side_effect = fake_volume_api_create

        backup_id = self._create_backup(size=5, status='available')

        body = {"restore": {}}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 202)
        self.assertEqual(res_dict['restore']['backup_id'], backup_id)

    @mock.patch('cinder.backup.API.restore')
    def test_restore_backup_with_InvalidInput(self,
                                              _mock_volume_api_restore):

        msg = _("Invalid input")
        _mock_volume_api_restore.side_effect = \
            exception.InvalidInput(reason=msg)

        backup_id = self._create_backup(status='available')
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=0)['id']
        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid input received: Invalid input')

    def test_restore_backup_with_InvalidVolume(self):
        backup_id = self._create_backup(status='available')
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=5,
                                        status='attaching')['id']

        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid volume: Volume to be restored to must '
                         'be available')

        db.volume_destroy(context.get_admin_context(), volume_id)
        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_restore_backup_with_InvalidBackup(self):
        backup_id = self._create_backup(status='restoring')
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=5)['id']

        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid backup: Backup status must be available')

        db.volume_destroy(context.get_admin_context(), volume_id)
        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_restore_backup_with_BackupNotFound(self):
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=5)['id']

        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/9999/restore')
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Backup 9999 could not be found.')

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_restore_backup_with_VolumeNotFound(self):
        backup_id = self._create_backup(status='available')

        body = {"restore": {"volume_id": "9999", }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Volume 9999 could not be found.')

        db.backup_destroy(context.get_admin_context(), backup_id)

    @mock.patch('cinder.backup.API.restore')
    def test_restore_backup_with_VolumeSizeExceedsAvailableQuota(
            self,
            _mock_backup_restore):

        _mock_backup_restore.side_effect = \
            exception.VolumeSizeExceedsAvailableQuota(requested='2',
                                                      consumed='2',
                                                      quota='3')

        backup_id = self._create_backup(status='available')
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=5)['id']

        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 413)
        self.assertEqual(res_dict['overLimit']['code'], 413)
        self.assertEqual(res_dict['overLimit']['message'],
                         'Requested volume or snapshot exceeds allowed '
                         'gigabytes quota. Requested 2G, quota is 3G and '
                         '2G has been consumed.')

    @mock.patch('cinder.backup.API.restore')
    def test_restore_backup_with_VolumeLimitExceeded(self,
                                                     _mock_backup_restore):

        _mock_backup_restore.side_effect = \
            exception.VolumeLimitExceeded(allowed=1)

        backup_id = self._create_backup(status='available')
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=5)['id']

        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 413)
        self.assertEqual(res_dict['overLimit']['code'], 413)
        self.assertEqual(res_dict['overLimit']['message'],
                         'Maximum number of volumes allowed (1) exceeded')

    def test_restore_backup_to_undersized_volume(self):
        backup_size = 10
        backup_id = self._create_backup(status='available', size=backup_size)
        # need to create the volume referenced below first
        volume_size = 5
        volume_id = utils.create_volume(self.context, size=volume_size)['id']

        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid volume: volume size %d is too '
                         'small to restore backup of size %d.'
                         % (volume_size, backup_size))

        db.volume_destroy(context.get_admin_context(), volume_id)
        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_restore_backup_to_oversized_volume(self):
        backup_id = self._create_backup(status='available', size=10)
        # need to create the volume referenced below first
        volume_id = utils.create_volume(self.context, size=15)['id']

        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 202)
        self.assertEqual(res_dict['restore']['backup_id'], backup_id)
        self.assertEqual(res_dict['restore']['volume_id'], volume_id)

        db.volume_destroy(context.get_admin_context(), volume_id)
        db.backup_destroy(context.get_admin_context(), backup_id)

    @mock.patch('cinder.backup.rpcapi.BackupAPI.restore_backup')
    def test_restore_backup_with_different_host(self, mock_restore_backup):
        backup_id = self._create_backup(status='available', size=10,
                                        host='HostA@BackendB#PoolA')
        volume_id = utils.create_volume(self.context, size=10,
                                        host='HostB@BackendB#PoolB')['id']

        body = {"restore": {"volume_id": volume_id, }}
        req = webob.Request.blank('/v2/fake/backups/%s/restore' %
                                  backup_id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 202)
        self.assertEqual(res_dict['restore']['backup_id'], backup_id)
        self.assertEqual(res_dict['restore']['volume_id'], volume_id)
        mock_restore_backup.assert_called_once_with(mock.ANY,
                                                    'HostB',
                                                    backup_id,
                                                    volume_id)

        db.volume_destroy(context.get_admin_context(), volume_id)
        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_export_record_as_non_admin(self):
        backup_id = self._create_backup(status='available', size=10)
        req = webob.Request.blank('/v2/fake/backups/%s/export_record' %
                                  backup_id)
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app())
        # request is not authorized
        self.assertEqual(res.status_int, 403)

    @mock.patch('cinder.backup.rpcapi.BackupAPI.export_record')
    def test_export_backup_record_id_specified_json(self,
                                                    _mock_export_record_rpc):
        backup_id = self._create_backup(status='available', size=10)
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'
        _mock_export_record_rpc.return_value = \
            {'backup_service': backup_service,
             'backup_url': backup_url}
        req = webob.Request.blank('/v2/fake/backups/%s/export_record' %
                                  backup_id)
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        # verify that request is successful
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res_dict['backup-record']['backup_service'],
                         backup_service)
        self.assertEqual(res_dict['backup-record']['backup_url'],
                         backup_url)
        db.backup_destroy(context.get_admin_context(), backup_id)

    @mock.patch('cinder.backup.rpcapi.BackupAPI.export_record')
    def test_export_record_backup_id_specified_xml(self,
                                                   _mock_export_record_rpc):
        backup_id = self._create_backup(status='available', size=10)
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'
        _mock_export_record_rpc.return_value = \
            {'backup_service': backup_service,
             'backup_url': backup_url}
        req = webob.Request.blank('/v2/fake/backups/%s/export_record' %
                                  backup_id)
        req.method = 'GET'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        self.assertEqual(res.status_int, 200)
        dom = minidom.parseString(res.body)
        export = dom.getElementsByTagName('backup-record')
        self.assertEqual(export.item(0).getAttribute('backup_service'),
                         backup_service)
        self.assertEqual(export.item(0).getAttribute('backup_url'),
                         backup_url)

        # db.backup_destroy(context.get_admin_context(), backup_id)

    def test_export_record_with_bad_backup_id(self):

        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        backup_id = 'bad_id'
        req = webob.Request.blank('/v2/fake/backups/%s/export_record' %
                                  backup_id)
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 404)
        self.assertEqual(res_dict['itemNotFound']['code'], 404)
        self.assertEqual(res_dict['itemNotFound']['message'],
                         'Backup %s could not be found.' % backup_id)

    def test_export_record_for_unavailable_backup(self):

        backup_id = self._create_backup(status='restoring')
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        req = webob.Request.blank('/v2/fake/backups/%s/export_record' %
                                  backup_id)
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid backup: Backup status must be available '
                         'and not restoring.')
        db.backup_destroy(context.get_admin_context(), backup_id)

    @mock.patch('cinder.backup.rpcapi.BackupAPI.export_record')
    def test_export_record_with_unavailable_service(self,
                                                    _mock_export_record_rpc):
        msg = 'fake unavailable service'
        _mock_export_record_rpc.side_effect = \
            exception.InvalidBackup(reason=msg)
        backup_id = self._create_backup(status='available')
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        req = webob.Request.blank('/v2/fake/backups/%s/export_record' %
                                  backup_id)
        req.method = 'GET'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)

        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Invalid backup: %s' % msg)
        db.backup_destroy(context.get_admin_context(), backup_id)

    def test_import_record_as_non_admin(self):
        backup_service = 'fake'
        backup_url = 'fake'
        req = webob.Request.blank('/v2/fake/backups/import_record')
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = json.dumps(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app())
        # request is not authorized
        self.assertEqual(res.status_int, 403)

    @mock.patch('cinder.backup.api.API._list_backup_services')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.import_record')
    def test_import_record_volume_id_specified_json(self,
                                                    _mock_import_record_rpc,
                                                    _mock_list_services):
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'
        _mock_import_record_rpc.return_value = \
            {'display_name': 'fake',
             'display_description': 'fake',
             'container': 'fake',
             'size': 1,
             'service_metadata': 'fake',
             'service': 'fake',
             'object_count': 1,
             'status': 'available',
             'availability_zone': 'fake'}
        _mock_list_services.return_value = ['fake']

        req = webob.Request.blank('/v2/fake/backups/import_record')
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = json.dumps(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        # verify that request is successful
        self.assertEqual(res.status_int, 201)
        self.assertTrue('id' in res_dict['backup'])

    @mock.patch('cinder.backup.api.API._list_backup_services')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.import_record')
    def test_import_record_volume_id_specified_xml(self,
                                                   _mock_import_record_rpc,
                                                   _mock_list_services):
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'
        _mock_import_record_rpc.return_value = \
            {'display_name': 'fake',
             'display_description': 'fake',
             'container': 'fake',
             'size': 1,
             'service_metadata': 'fake',
             'service': 'fake',
             'object_count': 1,
             'status': 'available',
             'availability_zone': 'fake'}
        _mock_list_services.return_value = ['fake']

        req = webob.Request.blank('/v2/fake/backups/import_record')
        req.body = ('<backup-record backup_service="%(backup_service)s" '
                    'backup_url="%(backup_url)s"/>') \
            % {'backup_url': backup_url,
               'backup_service': backup_service}

        req.method = 'POST'
        req.headers['Content-Type'] = 'application/xml'
        req.headers['Accept'] = 'application/xml'
        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))

        self.assertEqual(res.status_int, 201)
        dom = minidom.parseString(res.body)
        backup = dom.getElementsByTagName('backup')
        self.assertTrue(backup.item(0).hasAttribute('id'))

    @mock.patch('cinder.backup.api.API._list_backup_services')
    def test_import_record_with_no_backup_services(self,
                                                   _mock_list_services):
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'
        _mock_list_services.return_value = []

        req = webob.Request.blank('/v2/fake/backups/import_record')
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = json.dumps(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 500)
        self.assertEqual(res_dict['computeFault']['code'], 500)
        self.assertEqual(res_dict['computeFault']['message'],
                         'Service %s could not be found.'
                         % backup_service)

    @mock.patch('cinder.backup.api.API._list_backup_services')
    @mock.patch('cinder.backup.rpcapi.BackupAPI.import_record')
    def test_import_backup_with_missing_backup_services(self,
                                                        _mock_import_record,
                                                        _mock_list_services):
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'
        _mock_list_services.return_value = ['no-match1', 'no-match2']
        _mock_import_record.side_effect = \
            exception.ServiceNotFound(service_id='fake')
        req = webob.Request.blank('/v2/fake/backups/import_record')
        body = {'backup-record': {'backup_service': backup_service,
                                  'backup_url': backup_url}}
        req.body = json.dumps(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 500)
        self.assertEqual(res_dict['computeFault']['code'], 500)
        self.assertEqual(res_dict['computeFault']['message'],
                         'Service %s could not be found.'
                         % backup_service)

    def test_import_record_with_missing_body_elements(self):
        ctx = context.RequestContext('admin', 'fake', is_admin=True)
        backup_service = 'fake'
        backup_url = 'fake'

        # test with no backup_service
        req = webob.Request.blank('/v2/fake/backups/import_record')
        body = {'backup-record': {'backup_url': backup_url}}
        req.body = json.dumps(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Incorrect request body format.')

        # test with no backup_url
        req = webob.Request.blank('/v2/fake/backups/import_record')
        body = {'backup-record': {'backup_service': backup_service}}
        req.body = json.dumps(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Incorrect request body format.')

        # test with no backup_url and backup_url
        req = webob.Request.blank('/v2/fake/backups/import_record')
        body = {'backup-record': {}}
        req.body = json.dumps(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Incorrect request body format.')

    def test_import_record_with_no_body(self):
        ctx = context.RequestContext('admin', 'fake', is_admin=True)

        req = webob.Request.blank('/v2/fake/backups/import_record')
        req.body = json.dumps(None)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'

        res = req.get_response(fakes.wsgi_app(fake_auth_context=ctx))
        res_dict = json.loads(res.body)
        # verify that request is successful
        self.assertEqual(res.status_int, 400)
        self.assertEqual(res_dict['badRequest']['code'], 400)
        self.assertEqual(res_dict['badRequest']['message'],
                         'Incorrect request body format.')
