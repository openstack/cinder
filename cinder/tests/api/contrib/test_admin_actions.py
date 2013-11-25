# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import ast
import os
import shutil
import tempfile
import webob

from oslo.config import cfg

from cinder.brick.local_dev import lvm as brick_lvm
from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import jsonutils
from cinder.openstack.common import timeutils
from cinder import test
from cinder.tests.api import fakes
from cinder.tests.api.v2 import stubs
from cinder.volume import api as volume_api

CONF = cfg.CONF


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


class AdminActionsTest(test.TestCase):

    def setUp(self):
        super(AdminActionsTest, self).setUp()
        self.tempdir = tempfile.mkdtemp()
        self.flags(rpc_backend='cinder.openstack.common.rpc.impl_fake')
        self.flags(lock_path=self.tempdir)
        self.volume_api = volume_api.API()
        self.stubs.Set(brick_lvm.LVM, '_vg_exists', lambda x: True)

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        super(AdminActionsTest, self).tearDown()

    def test_reset_status_as_admin(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available'})
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request status of 'error'
        req.body = jsonutils.dumps({'os-reset_status': {'status': 'error'}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        # status changed to 'error'
        self.assertEqual(volume['status'], 'error')

    def test_reset_status_as_non_admin(self):
        # current status is 'error'
        volume = db.volume_create(context.get_admin_context(),
                                  {'status': 'error'})
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request changing status to available
        req.body = jsonutils.dumps({'os-reset_status': {'status':
                                                        'available'}})
        # non-admin context
        req.environ['cinder.context'] = context.RequestContext('fake', 'fake')
        resp = req.get_response(app())
        # request is not authorized
        self.assertEqual(resp.status_int, 403)
        volume = db.volume_get(context.get_admin_context(), volume['id'])
        # status is still 'error'
        self.assertEqual(volume['status'], 'error')

    def test_malformed_reset_status_body(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available'})
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # malformed request body
        req.body = jsonutils.dumps({'os-reset_status': {'x-status': 'bad'}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # bad request
        self.assertEqual(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        # status is still 'available'
        self.assertEqual(volume['status'], 'available')

    def test_invalid_status_for_volume(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available'})
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # 'invalid' is not a valid status
        req.body = jsonutils.dumps({'os-reset_status': {'status': 'invalid'}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # bad request
        self.assertEqual(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        # status is still 'available'
        self.assertEqual(volume['status'], 'available')

    def test_reset_status_for_missing_volume(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # missing-volume-id
        req = webob.Request.blank('/v2/fake/volumes/%s/action' %
                                  'missing-volume-id')
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # malformed request body
        req.body = jsonutils.dumps({'os-reset_status': {'status':
                                                        'available'}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # not found
        self.assertEqual(resp.status_int, 404)
        self.assertRaises(exception.NotFound, db.volume_get, ctx,
                          'missing-volume-id')

    def test_reset_attached_status(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available',
                                        'attach_status': 'attached'})
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request update attach_status to detached
        body = {'os-reset_status': {'status': 'available',
                                    'attach_status': 'detached'}}
        req.body = jsonutils.dumps(body)
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        # attach_status changed to 'detached'
        self.assertEqual(volume['attach_status'], 'detached')
        # status un-modified
        self.assertEqual(volume['status'], 'available')

    def test_invalid_reset_attached_status(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available',
                                        'attach_status': 'detached'})
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # 'invalid' is not a valid attach_status
        body = {'os-reset_status': {'status': 'available',
                                    'attach_status': 'invalid'}}
        req.body = jsonutils.dumps(body)
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # bad request
        self.assertEqual(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        # status and attach_status un-modified
        self.assertEqual(volume['status'], 'available')
        self.assertEqual(volume['attach_status'], 'detached')

    def test_snapshot_reset_status(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # snapshot in 'error_deleting'
        volume = db.volume_create(ctx, {})
        snapshot = db.snapshot_create(ctx, {'status': 'error_deleting',
                                            'volume_id': volume['id']})
        req = webob.Request.blank('/v2/fake/snapshots/%s/action' %
                                  snapshot['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request status of 'error'
        req.body = jsonutils.dumps({'os-reset_status': {'status': 'error'}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 202)
        snapshot = db.snapshot_get(ctx, snapshot['id'])
        # status changed to 'error'
        self.assertEqual(snapshot['status'], 'error')

    def test_invalid_status_for_snapshot(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # snapshot in 'available'
        volume = db.volume_create(ctx, {})
        snapshot = db.snapshot_create(ctx, {'status': 'available',
                                            'volume_id': volume['id']})
        req = webob.Request.blank('/v2/fake/snapshots/%s/action' %
                                  snapshot['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # 'attaching' is not a valid status for snapshots
        req.body = jsonutils.dumps({'os-reset_status': {'status':
                                                        'attaching'}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 400)
        snapshot = db.snapshot_get(ctx, snapshot['id'])
        # status is still 'available'
        self.assertEqual(snapshot['status'], 'available')

    def test_force_delete(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is creating
        volume = db.volume_create(ctx, {'status': 'creating'})
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dumps({'os-force_delete': {}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 202)
        # volume is deleted
        self.assertRaises(exception.NotFound, db.volume_get, ctx, volume['id'])

    def test_force_delete_snapshot(self):
        self.stubs.Set(os.path, 'exists', lambda x: True)
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is creating
        volume = db.volume_create(ctx, {'host': 'test'})
        snapshot = db.snapshot_create(ctx, {'status': 'creating',
                                            'volume_size': 1,
                                            'volume_id': volume['id']})
        path = '/v2/fake/snapshots/%s/action' % snapshot['id']
        req = webob.Request.blank(path)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dumps({'os-force_delete': {}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        # start service to handle rpc.cast for 'delete snapshot'
        svc = self.start_service('volume', host='test')
        # make request
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 202)
        # snapshot is deleted
        self.assertRaises(exception.NotFound, db.snapshot_get, ctx,
                          snapshot['id'])
        # cleanup
        svc.stop()

    def test_force_detach_instance_attached_volume(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        mountpoint = '/dev/vbd'
        self.volume_api.attach(ctx, volume, stubs.FAKE_UUID, None,
                               mountpoint, 'rw')
        # volume is attached
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['status'], 'in-use')
        self.assertEqual(volume['instance_uuid'], stubs.FAKE_UUID)
        self.assertIsNone(volume['attached_host'])
        self.assertEqual(volume['mountpoint'], mountpoint)
        self.assertEqual(volume['attach_status'], 'attached')
        admin_metadata = volume['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'False')
        self.assertEqual(admin_metadata[1]['key'], 'attached_mode')
        self.assertEqual(admin_metadata[1]['value'], 'rw')
        conn_info = self.volume_api.initialize_connection(ctx,
                                                          volume, connector)
        self.assertEqual(conn_info['data']['access_mode'], 'rw')
        # build request to force detach
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request status of 'error'
        req.body = jsonutils.dumps({'os-force_detach': None})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        # make request
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        # status changed to 'available'
        self.assertEqual(volume['status'], 'available')
        self.assertIsNone(volume['instance_uuid'])
        self.assertIsNone(volume['attached_host'])
        self.assertIsNone(volume['mountpoint'])
        self.assertEqual(volume['attach_status'], 'detached')
        admin_metadata = volume['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 1)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'False')
        # cleanup
        svc.stop()

    def test_force_detach_host_attached_volume(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        mountpoint = '/dev/vbd'
        host_name = 'fake-host'
        self.volume_api.attach(ctx, volume, None, host_name, mountpoint, 'ro')
        # volume is attached
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['status'], 'in-use')
        self.assertIsNone(volume['instance_uuid'])
        self.assertEqual(volume['attached_host'], host_name)
        self.assertEqual(volume['mountpoint'], mountpoint)
        self.assertEqual(volume['attach_status'], 'attached')
        admin_metadata = volume['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'False')
        self.assertEqual(admin_metadata[1]['key'], 'attached_mode')
        self.assertEqual(admin_metadata[1]['value'], 'ro')
        conn_info = self.volume_api.initialize_connection(ctx,
                                                          volume, connector)
        self.assertEqual(conn_info['data']['access_mode'], 'ro')
        # build request to force detach
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request status of 'error'
        req.body = jsonutils.dumps({'os-force_detach': None})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        # make request
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        # status changed to 'available'
        self.assertEqual(volume['status'], 'available')
        self.assertIsNone(volume['instance_uuid'])
        self.assertIsNone(volume['attached_host'])
        self.assertIsNone(volume['mountpoint'])
        self.assertEqual(volume['attach_status'], 'detached')
        admin_metadata = volume['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 1)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'False')
        # cleanup
        svc.stop()

    def test_attach_in_used_volume_by_instance(self):
        """Test that attaching to an in-use volume fails."""
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        mountpoint = '/dev/vbd'
        self.volume_api.attach(ctx, volume, stubs.FAKE_UUID, None,
                               mountpoint, 'rw')
        conn_info = self.volume_api.initialize_connection(ctx,
                                                          volume, connector)
        self.assertEqual(conn_info['data']['access_mode'], 'rw')
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          fakes.get_fake_uuid(),
                          None,
                          mountpoint,
                          'rw')
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          fakes.get_fake_uuid(),
                          None,
                          mountpoint,
                          'ro')
        # cleanup
        svc.stop()

    def test_attach_in_used_volume_by_host(self):
        """Test that attaching to an in-use volume fails."""
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        mountpoint = '/dev/vbd'
        host_name = 'fake_host'
        self.volume_api.attach(ctx, volume, None, host_name, mountpoint, 'rw')
        conn_info = self.volume_api.initialize_connection(ctx,
                                                          volume, connector)
        conn_info['data']['access_mode'] = 'rw'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          None,
                          host_name,
                          mountpoint,
                          'rw')
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          None,
                          host_name,
                          mountpoint,
                          'ro')
        # cleanup
        svc.stop()

    def test_invalid_iscsi_connector(self):
        """Test connector without the initiator (required by iscsi driver)."""
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        connector = {}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.volume_api.initialize_connection,
                          ctx, volume, connector)
        # cleanup
        svc.stop()

    def test_attach_attaching_volume_with_different_instance(self):
        """Test that attaching volume reserved for another instance fails."""
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        values = {'status': 'attaching',
                  'instance_uuid': fakes.get_fake_uuid()}
        db.volume_update(ctx, volume['id'], values)
        mountpoint = '/dev/vbd'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          stubs.FAKE_UUID,
                          None,
                          mountpoint,
                          'rw')
        # cleanup
        svc.stop()

    def test_attach_attaching_volume_with_different_mode(self):
        """Test that attaching volume reserved for another mode fails."""
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        values = {'status': 'attaching',
                  'instance_uuid': fakes.get_fake_uuid()}
        db.volume_update(ctx, volume['id'], values)
        db.volume_admin_metadata_update(ctx, volume['id'],
                                        {"attached_mode": 'rw'}, False)
        mountpoint = '/dev/vbd'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          values['instance_uuid'],
                          None,
                          mountpoint,
                          'ro')
        # cleanup
        svc.stop()

    def _migrate_volume_prep(self):
        admin_ctx = context.get_admin_context()
        # create volume's current host and the destination host
        db.service_create(admin_ctx,
                          {'host': 'test',
                           'topic': CONF.volume_topic,
                           'created_at': timeutils.utcnow()})
        db.service_create(admin_ctx,
                          {'host': 'test2',
                           'topic': CONF.volume_topic,
                           'created_at': timeutils.utcnow()})
        # current status is available
        volume = db.volume_create(admin_ctx,
                                  {'status': 'available',
                                   'host': 'test',
                                   'provider_location': '',
                                   'attach_status': ''})
        return volume

    def _migrate_volume_exec(self, ctx, volume, host, expected_status,
                             force_host_copy=False):
        admin_ctx = context.get_admin_context()
        # build request to migrate to host
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        body = {'os-migrate_volume': {'host': host,
                                      'force_host_copy': force_host_copy}}
        req.body = jsonutils.dumps(body)
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # verify status
        self.assertEqual(resp.status_int, expected_status)
        volume = db.volume_get(admin_ctx, volume['id'])
        return volume

    def test_migrate_volume_success(self):
        expected_status = 202
        host = 'test2'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_prep()
        volume = self._migrate_volume_exec(ctx, volume, host, expected_status)
        self.assertEqual(volume['migration_status'], 'starting')

    def test_migrate_volume_as_non_admin(self):
        expected_status = 403
        host = 'test2'
        ctx = context.RequestContext('fake', 'fake')
        volume = self._migrate_volume_prep()
        self._migrate_volume_exec(ctx, volume, host, expected_status)

    def test_migrate_volume_without_host_parameter(self):
        expected_status = 400
        host = 'test3'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_prep()
        # build request to migrate without host
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        body = {'os-migrate_volume': {'host': host,
                                      'force_host_copy': False}}
        req.body = jsonutils.dumps(body)
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # verify status
        self.assertEqual(resp.status_int, expected_status)

    def test_migrate_volume_host_no_exist(self):
        expected_status = 400
        host = 'test3'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_prep()
        self._migrate_volume_exec(ctx, volume, host, expected_status)

    def test_migrate_volume_same_host(self):
        expected_status = 400
        host = 'test'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_prep()
        self._migrate_volume_exec(ctx, volume, host, expected_status)

    def test_migrate_volume_migrating(self):
        expected_status = 400
        host = 'test2'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_prep()
        model_update = {'migration_status': 'migrating'}
        volume = db.volume_update(ctx, volume['id'], model_update)
        self._migrate_volume_exec(ctx, volume, host, expected_status)

    def test_migrate_volume_with_snap(self):
        expected_status = 400
        host = 'test2'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_prep()
        db.snapshot_create(ctx, {'volume_id': volume['id']})
        self._migrate_volume_exec(ctx, volume, host, expected_status)

    def test_migrate_volume_bad_force_host_copy1(self):
        expected_status = 400
        host = 'test2'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_prep()
        self._migrate_volume_exec(ctx, volume, host, expected_status,
                                  force_host_copy='foo')

    def test_migrate_volume_bad_force_host_copy2(self):
        expected_status = 400
        host = 'test2'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_prep()
        self._migrate_volume_exec(ctx, volume, host, expected_status,
                                  force_host_copy=1)

    def _migrate_volume_comp_exec(self, ctx, volume, new_volume, error,
                                  expected_status, expected_id):
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        body_dict = {'new_volume': new_volume['id'], 'error': error}
        req.body = jsonutils.dumps({'os-migrate_volume_completion': body_dict})
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        resp_dict = ast.literal_eval(resp.body)
        # verify status
        self.assertEqual(resp.status_int, expected_status)
        if expected_id:
            self.assertEqual(resp_dict['save_volume_id'], expected_id)
        else:
            self.assertNotIn('save_volume_id', resp_dict)

    def test_migrate_volume_comp_as_non_admin(self):
        admin_ctx = context.get_admin_context()
        volume = db.volume_create(admin_ctx, {'id': 'fake1'})
        new_volume = db.volume_create(admin_ctx, {'id': 'fake2'})
        expected_status = 403
        expected_id = None
        ctx = context.RequestContext('fake', 'fake')
        volume = self._migrate_volume_comp_exec(ctx, volume, new_volume, False,
                                                expected_status, expected_id)

    def test_migrate_volume_comp_no_mig_status(self):
        admin_ctx = context.get_admin_context()
        volume1 = db.volume_create(admin_ctx, {'id': 'fake1',
                                               'migration_status': 'foo'})
        volume2 = db.volume_create(admin_ctx, {'id': 'fake2',
                                               'migration_status': None})
        expected_status = 400
        expected_id = None
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_comp_exec(ctx, volume1, volume2, False,
                                                expected_status, expected_id)
        volume = self._migrate_volume_comp_exec(ctx, volume2, volume1, False,
                                                expected_status, expected_id)

    def test_migrate_volume_comp_bad_mig_status(self):
        admin_ctx = context.get_admin_context()
        volume1 = db.volume_create(admin_ctx,
                                   {'id': 'fake1',
                                    'migration_status': 'migrating'})
        volume2 = db.volume_create(admin_ctx,
                                   {'id': 'fake2',
                                    'migration_status': 'target:foo'})
        expected_status = 400
        expected_id = None
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_comp_exec(ctx, volume1, volume2, False,
                                                expected_status, expected_id)

    def test_migrate_volume_comp_from_nova(self):
        admin_ctx = context.get_admin_context()
        volume = db.volume_create(admin_ctx,
                                  {'id': 'fake1',
                                   'status': 'in-use',
                                   'host': 'test',
                                   'migration_status': None,
                                   'attach_status': 'attached'})
        new_volume = db.volume_create(admin_ctx,
                                      {'id': 'fake2',
                                       'status': 'available',
                                       'host': 'test',
                                       'migration_status': None,
                                       'attach_status': 'detached'})
        expected_status = 200
        expected_id = 'fake2'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_comp_exec(ctx, volume, new_volume, False,
                                                expected_status, expected_id)
