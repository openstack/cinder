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

import webob

# needed for stubs to work
import cinder.backup
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
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

    def tearDown(self):
        super(BackupsAPITestCase, self).tearDown()

    @staticmethod
    def _create_backup(volume_id=1,
                       display_name='test_backup',
                       display_description='this is a test backup',
                       container='volumebackups',
                       status='creating',
                       size=0, object_count=0):
        """Create a backup object."""
        backup = {}
        backup['volume_id'] = volume_id
        backup['user_id'] = 'fake'
        backup['project_id'] = 'fake'
        backup['host'] = 'testhost'
        backup['availability_zone'] = 'az1'
        backup['display_name'] = display_name
        backup['display_description'] = display_description
        backup['container'] = container
        backup['status'] = status
        backup['fail_reason'] = ''
        backup['size'] = size
        backup['object_count'] = object_count
        return db.backup_create(context.get_admin_context(), backup)['id']

    @staticmethod
    def _get_backup_attrib(backup_id, attrib_name):
        return db.backup_get(context.get_admin_context(),
                             backup_id)[attrib_name]

    @staticmethod
    def _stub_service_get_all_by_topic(context, topic):
        return [{'availability_zone': "fake_az", 'host': 'test_host',
                 'disabled': 0, 'updated_at': timeutils.utcnow()}]

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

    def test_create_backup_json(self):
        self.stubs.Set(cinder.db, 'service_get_all_by_topic',
                       self._stub_service_get_all_by_topic)

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

        db.volume_destroy(context.get_admin_context(), volume_id)

    def test_create_backup_xml(self):
        self.stubs.Set(cinder.db, 'service_get_all_by_topic',
                       self._stub_service_get_all_by_topic)
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

    def test_create_backup_WithOUT_enabled_backup_service(self):
        # need an enabled backup service available
        def stub_empty_service_get_all_by_topic(ctxt, topic):
            return []

        self.stubs.Set(cinder.db, 'service_get_all_by_topic',
                       stub_empty_service_get_all_by_topic)
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

    def test_is_backup_service_enabled(self):
        def empty_service(ctxt, topic):
            return []

        test_host = 'test_host'
        alt_host = 'strange_host'

        #service host not match with volume's host
        def host_not_match(context, topic):
            return [{'availability_zone': "fake_az", 'host': alt_host,
                     'disabled': 0, 'updated_at': timeutils.utcnow()}]

        #service az not match with volume's az
        def az_not_match(context, topic):
            return [{'availability_zone': "strange_az", 'host': test_host,
                     'disabled': 0, 'updated_at': timeutils.utcnow()}]

        #service disabled
        def disabled_service(context, topic):
            return [{'availability_zone': "fake_az", 'host': test_host,
                     'disabled': 1, 'updated_at': timeutils.utcnow()}]

        #dead service that last reported at 20th centry
        def dead_service(context, topic):
            return [{'availability_zone': "fake_az", 'host': alt_host,
                     'disabled': 0, 'updated_at': '1989-04-16 02:55:44'}]

        #first service's host not match but second one works.
        def multi_services(context, topic):
            return [{'availability_zone': "fake_az", 'host': alt_host,
                     'disabled': 0, 'updated_at': timeutils.utcnow()},
                    {'availability_zone': "fake_az", 'host': test_host,
                     'disabled': 0, 'updated_at': timeutils.utcnow()}]

        volume_id = utils.create_volume(self.context, size=2,
                                        host=test_host)['id']
        volume = self.volume_api.get(context.get_admin_context(), volume_id)

        #test empty service
        self.stubs.Set(cinder.db, 'service_get_all_by_topic', empty_service)
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        #test host not match service
        self.stubs.Set(cinder.db, 'service_get_all_by_topic', host_not_match)
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        #test az not match service
        self.stubs.Set(cinder.db, 'service_get_all_by_topic', az_not_match)
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        #test disabled service
        self.stubs.Set(cinder.db, 'service_get_all_by_topic', disabled_service)
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        #test dead service
        self.stubs.Set(cinder.db, 'service_get_all_by_topic', dead_service)
        self.assertEqual(self.backup_api._is_backup_service_enabled(volume,
                                                                    test_host),
                         False)

        #test multi services and the last service matches
        self.stubs.Set(cinder.db, 'service_get_all_by_topic', multi_services)
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

    def test_restore_backup_volume_id_unspecified(self):

        # intercept volume creation to ensure created volume
        # has status of available
        def fake_volume_api_create(cls, context, size, name, description):
            volume_id = utils.create_volume(self.context, size=size)['id']
            return db.volume_get(context, volume_id)

        self.stubs.Set(cinder.volume.API, 'create',
                       fake_volume_api_create)

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

    def test_restore_backup_with_InvalidInput(self):

        def fake_backup_api_restore_throwing_InvalidInput(cls, context,
                                                          backup_id,
                                                          volume_id):
            msg = _("Invalid input")
            raise exception.InvalidInput(reason=msg)

        self.stubs.Set(cinder.backup.API, 'restore',
                       fake_backup_api_restore_throwing_InvalidInput)

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

    def test_restore_backup_with_VolumeSizeExceedsAvailableQuota(self):

        def fake_backup_api_restore_throwing_VolumeSizeExceedsAvailableQuota(
                cls, context, backup_id, volume_id):
            raise exception.VolumeSizeExceedsAvailableQuota(requested='2',
                                                            consumed='2',
                                                            quota='3')

        self.stubs.Set(
            cinder.backup.API,
            'restore',
            fake_backup_api_restore_throwing_VolumeSizeExceedsAvailableQuota)

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
                         'Gigabytes quota. Requested 2G, quota is 3G and '
                         '2G has been consumed.')

    def test_restore_backup_with_VolumeLimitExceeded(self):

        def fake_backup_api_restore_throwing_VolumeLimitExceeded(cls,
                                                                 context,
                                                                 backup_id,
                                                                 volume_id):
            raise exception.VolumeLimitExceeded(allowed=1)

        self.stubs.Set(cinder.backup.API, 'restore',
                       fake_backup_api_restore_throwing_VolumeLimitExceeded)

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
