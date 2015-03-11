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

import fixtures
import mock
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import webob
from webob import exc

from cinder.api.contrib import admin_actions
from cinder.brick.local_dev import lvm as brick_lvm
from cinder import context
from cinder import db
from cinder import exception
from cinder import test
from cinder.tests.api import fakes
from cinder.tests.api.v2 import stubs
from cinder.tests import cast_as_call
from cinder.tests import fake_snapshot
from cinder.volume import api as volume_api
from cinder.volume.targets import tgt

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

        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.fixture = self.useFixture(config_fixture.Config(lockutils.CONF))
        self.fixture.config(lock_path=self.tempdir,
                            group='oslo_concurrency')
        self.fixture.config(disable_process_locking=True,
                            group='oslo_concurrency')
        self.flags(rpc_backend='cinder.openstack.common.rpc.impl_fake')

        self.volume_api = volume_api.API()
        cast_as_call.mock_cast_as_call(self.volume_api.volume_rpcapi.client)
        cast_as_call.mock_cast_as_call(self.volume_api.scheduler_rpcapi.client)
        self.stubs.Set(brick_lvm.LVM, '_vg_exists', lambda x: True)
        self.stubs.Set(tgt.TgtAdm,
                       'create_iscsi_target',
                       self._fake_create_iscsi_target)

    def _fake_create_iscsi_target(self, name, tid, lun,
                                  path, chap_auth=None, **kwargs):
        return 1

    def _issue_volume_reset(self, ctx, volume, updated_status):
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = \
            jsonutils.dumps({'os-reset_status': updated_status})
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        return resp

    def _issue_snapshot_reset(self, ctx, snapshot, updated_status):
        req = webob.Request.blank('/v2/fake/snapshots/%s/action' %
                                  snapshot['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = \
            jsonutils.dumps({'os-reset_status': updated_status})
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        return resp

    def _issue_backup_reset(self, ctx, backup, updated_status):
        req = webob.Request.blank('/v2/fake/backups/%s/action' % backup['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = \
            jsonutils.dumps({'os-reset_status': updated_status})
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        return resp

    def test_valid_updates(self):
        vac = admin_actions.VolumeAdminController()

        vac.validate_update({'status': 'creating'})
        vac.validate_update({'status': 'available'})
        vac.validate_update({'status': 'deleting'})
        vac.validate_update({'status': 'error'})
        vac.validate_update({'status': 'error_deleting'})

        vac.validate_update({'attach_status': 'detached'})
        vac.validate_update({'attach_status': 'attached'})

        vac.validate_update({'migration_status': 'migrating'})
        vac.validate_update({'migration_status': 'error'})
        vac.validate_update({'migration_status': 'completing'})
        vac.validate_update({'migration_status': 'none'})
        vac.validate_update({'migration_status': 'starting'})

    def test_reset_attach_status(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'attach_status': 'detached'})

        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'attach_status': 'attached'})

        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['attach_status'], 'attached')

    def test_reset_attach_invalid_status(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'attach_status': 'detached'})

        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'attach_status': 'bogus-status'})

        self.assertEqual(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['attach_status'], 'detached')

    def test_reset_migration_invalid_status(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'migration_status': None})

        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'migration_status': 'bogus-status'})

        self.assertEqual(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['migration_status'], None)

    def test_reset_migration_status(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'migration_status': None})

        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'migration_status': 'migrating'})

        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['migration_status'], 'migrating')

    def test_reset_status_as_admin(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available'})

        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'status': 'error'})

        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['status'], 'error')

    def test_reset_status_as_non_admin(self):
        ctx = context.RequestContext('fake', 'fake')
        volume = db.volume_create(context.get_admin_context(),
                                  {'status': 'error', 'size': 1})

        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'status': 'error'})

        # request is not authorized
        self.assertEqual(resp.status_int, 403)
        volume = db.volume_get(context.get_admin_context(), volume['id'])
        # status is still 'error'
        self.assertEqual(volume['status'], 'error')

    def test_backup_reset_status_as_admin(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available'})
        backup = db.backup_create(ctx, {'status': 'available',
                                        'size': 1,
                                        'volume_id': volume['id']})

        resp = self._issue_backup_reset(ctx,
                                        backup,
                                        {'status': 'error'})

        self.assertEqual(resp.status_int, 202)

    def test_backup_reset_status_as_non_admin(self):
        ctx = context.RequestContext('fake', 'fake')
        backup = db.backup_create(ctx, {'status': 'available',
                                        'size': 1,
                                        'volume_id': "fakeid"})
        resp = self._issue_backup_reset(ctx,
                                        backup,
                                        {'status': 'error'})
        # request is not authorized
        self.assertEqual(resp.status_int, 403)

    def test_backup_reset_status(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1})
        backup = db.backup_create(ctx, {'status': 'available',
                                        'volume_id': volume['id']})

        resp = self._issue_backup_reset(ctx,
                                        backup,
                                        {'status': 'error'})

        self.assertEqual(resp.status_int, 202)

    def test_invalid_status_for_backup(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1})
        backup = db.backup_create(ctx, {'status': 'available',
                                        'volume_id': volume['id']})
        resp = self._issue_backup_reset(ctx,
                                        backup,
                                        {'status': 'restoring'})
        self.assertEqual(resp.status_int, 400)

    def test_malformed_reset_status_body(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available', 'size': 1})

        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'x-status': 'bad'})

        self.assertEqual(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['status'], 'available')

    def test_invalid_status_for_volume(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available', 'size': 1})
        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'status': 'invalid'})

        self.assertEqual(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['status'], 'available')

    def test_reset_status_for_missing_volume(self):
        ctx = context.RequestContext('admin', 'fake', True)
        req = webob.Request.blank('/v2/fake/volumes/%s/action' %
                                  'missing-volume-id')
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dumps({'os-reset_status': {'status':
                                                        'available'}})
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        self.assertEqual(resp.status_int, 404)
        self.assertRaises(exception.NotFound, db.volume_get, ctx,
                          'missing-volume-id')

    def test_reset_attached_status(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1,
                                        'attach_status': 'attached'})

        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'status': 'available',
                                         'attach_status': 'detached'})

        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['attach_status'], 'detached')
        self.assertEqual(volume['status'], 'available')

    def test_invalid_reset_attached_status(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1,
                                        'attach_status': 'detached'})
        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'status': 'available',
                                         'attach_status': 'invalid'})
        self.assertEqual(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['status'], 'available')
        self.assertEqual(volume['attach_status'], 'detached')

    def test_snapshot_reset_status(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1})
        snapshot = db.snapshot_create(ctx, {'status': 'error_deleting',
                                            'volume_id': volume['id']})

        resp = self._issue_snapshot_reset(ctx,
                                          snapshot,
                                          {'status': 'error'})

        self.assertEqual(resp.status_int, 202)
        snapshot = db.snapshot_get(ctx, snapshot['id'])
        self.assertEqual(snapshot['status'], 'error')

    def test_invalid_status_for_snapshot(self):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1})
        snapshot = db.snapshot_create(ctx, {'status': 'available',
                                            'volume_id': volume['id']})

        resp = self._issue_snapshot_reset(ctx,
                                          snapshot,
                                          {'status': 'attaching'})

        self.assertEqual(resp.status_int, 400)
        snapshot = db.snapshot_get(ctx, snapshot['id'])
        self.assertEqual(snapshot['status'], 'available')

    def test_force_delete(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is creating
        volume = db.volume_create(ctx, {'size': 1})
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

    @mock.patch.object(volume_api.API, 'delete_snapshot', return_value=True)
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    @mock.patch.object(db, 'snapshot_get')
    @mock.patch.object(db, 'volume_get')
    def test_force_delete_snapshot(self, volume_get, snapshot_get, get_by_id,
                                   delete_snapshot):
        ctx = context.RequestContext('admin', 'fake', True)
        volume = stubs.stub_volume(1)
        snapshot = stubs.stub_snapshot(1)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(ctx, **snapshot)
        volume_get.return_value = volume
        snapshot_get.return_value = snapshot
        get_by_id.return_value = snapshot_obj

        path = '/v2/fake/snapshots/%s/action' % snapshot['id']
        req = webob.Request.blank(path)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dumps({'os-force_delete': {}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        self.assertEqual(resp.status_int, 202)

    def test_force_detach_instance_attached_volume(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        mountpoint = '/dev/vbd'
        attachment = self.volume_api.attach(ctx, volume, stubs.FAKE_UUID,
                                            None, mountpoint, 'rw')
        # volume is attached
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['status'], 'in-use')
        self.assertEqual(attachment['instance_uuid'], stubs.FAKE_UUID)
        self.assertEqual(attachment['mountpoint'], mountpoint)
        self.assertEqual(attachment['attach_status'], 'attached')
        admin_metadata = volume['volume_admin_metadata']
        self.assertEqual(len(admin_metadata), 2)
        self.assertEqual(admin_metadata[0]['key'], 'readonly')
        self.assertEqual(admin_metadata[0]['value'], 'False')
        self.assertEqual(admin_metadata[1]['key'], 'attached_mode')
        self.assertEqual(admin_metadata[1]['value'], 'rw')
        conn_info = self.volume_api.initialize_connection(ctx,
                                                          volume,
                                                          connector)
        self.assertEqual(conn_info['data']['access_mode'], 'rw')
        # build request to force detach
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request status of 'error'
        req.body = jsonutils.dumps({'os-force_detach':
                                    {'attachment_id': attachment['id']}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        # make request
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        self.assertRaises(exception.VolumeAttachmentNotFound,
                          db.volume_attachment_get,
                          ctx, attachment['id'])

        # status changed to 'available'
        self.assertEqual(volume['status'], 'available')
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
                                        'provider_location': '', 'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.volume_api.initialize_connection(ctx, volume, connector)
        mountpoint = '/dev/vbd'
        host_name = 'fake-host'
        attachment = self.volume_api.attach(ctx, volume, None, host_name,
                                            mountpoint, 'ro')
        # volume is attached
        volume = db.volume_get(ctx, volume['id'])
        self.assertEqual(volume['status'], 'in-use')
        self.assertIsNone(attachment['instance_uuid'])
        self.assertEqual(attachment['attached_host'], host_name)
        self.assertEqual(attachment['mountpoint'], mountpoint)
        self.assertEqual(attachment['attach_status'], 'attached')
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
        req.body = jsonutils.dumps({'os-force_detach':
                                    {'attachment_id': attachment['id']}})
        # attach admin context to request
        req.environ['cinder.context'] = ctx
        # make request
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        self.assertRaises(exception.VolumeAttachmentNotFound,
                          db.volume_attachment_get,
                          ctx, attachment['id'])
        # status changed to 'available'
        self.assertEqual(volume['status'], 'available')
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
                                        'provider_location': '', 'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        conn_info = self.volume_api.initialize_connection(ctx,
                                                          volume, connector)
        self.volume_api.attach(ctx, volume, fakes.get_fake_uuid(), None,
                               '/dev/vbd0', 'rw')
        self.assertEqual(conn_info['data']['access_mode'], 'rw')
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          fakes.get_fake_uuid(),
                          None,
                          '/dev/vdb1',
                          'ro')
        # cleanup
        svc.stop()

    def test_attach_in_used_volume_by_host(self):
        """Test that attaching to an in-use volume fails."""
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        self.volume_api.initialize_connection(ctx, volume, connector)
        self.volume_api.attach(ctx, volume, None, 'fake_host1',
                               '/dev/vbd0', 'rw')
        conn_info = self.volume_api.initialize_connection(ctx,
                                                          volume, connector)
        conn_info['data']['access_mode'] = 'rw'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          None,
                          'fake_host2',
                          '/dev/vbd1',
                          'ro')
        # cleanup
        svc.stop()

    def test_invalid_iscsi_connector(self):
        """Test connector without the initiator (required by iscsi driver)."""
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1})
        connector = {}
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.assertRaises(exception.InvalidInput,
                          self.volume_api.initialize_connection,
                          ctx, volume, connector)
        # cleanup
        svc.stop()

    def test_attach_attaching_volume_with_different_instance(self):
        """Test that attaching volume reserved for another instance fails."""
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1})
        # start service to handle rpc messages for attach requests
        svc = self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        values = {'volume_id': volume['id'],
                  'attach_status': 'attaching',
                  'attach_time': timeutils.utcnow(),
                  'instance_uuid': 'abc123',
                  }
        db.volume_attach(ctx, values)
        db.volume_admin_metadata_update(ctx, volume['id'],
                                        {"attached_mode": 'rw'}, False)
        mountpoint = '/dev/vbd'
        attachment = self.volume_api.attach(ctx, volume,
                                            stubs.FAKE_UUID, None,
                                            mountpoint, 'rw')

        self.assertEqual(stubs.FAKE_UUID, attachment['instance_uuid'])
        self.assertEqual(volume['id'], attachment['volume_id'], volume['id'])
        self.assertEqual('attached', attachment['attach_status'])
        svc.stop()

    def test_attach_attaching_volume_with_different_mode(self):
        """Test that attaching volume reserved for another mode fails."""
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': '', 'size': 1})
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

    def test_migrate_volume_fail_replication(self):
        expected_status = 400
        host = 'test2'
        ctx = context.RequestContext('admin', 'fake', True)
        volume = self._migrate_volume_prep()
        # current status is available
        volume = db.volume_create(ctx,
                                  {'status': 'available',
                                   'host': 'test',
                                   'provider_location': '',
                                   'attach_status': '',
                                   'replication_status': 'active'})
        volume = self._migrate_volume_exec(ctx, volume, host, expected_status)

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
                                  expected_status, expected_id, no_body=False):
        req = webob.Request.blank('/v2/fake/volumes/%s/action' % volume['id'])
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        body = {'new_volume': new_volume['id'], 'error': error}
        if no_body:
            req.body = jsonutils.dumps({'': body})
        else:
            req.body = jsonutils.dumps({'os-migrate_volume_completion': body})
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
        self._migrate_volume_comp_exec(ctx, volume1, volume2, False,
                                       expected_status, expected_id)
        self._migrate_volume_comp_exec(ctx, volume2, volume1, False,
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
        self._migrate_volume_comp_exec(ctx, volume1, volume2, False,
                                       expected_status, expected_id)

    def test_migrate_volume_comp_no_action(self):
        admin_ctx = context.get_admin_context()
        volume = db.volume_create(admin_ctx, {'id': 'fake1'})
        new_volume = db.volume_create(admin_ctx, {'id': 'fake2'})
        expected_status = 400
        expected_id = None
        ctx = context.RequestContext('fake', 'fake')
        self._migrate_volume_comp_exec(ctx, volume, new_volume, False,
                                       expected_status, expected_id, True)

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

    def test_backup_reset_valid_updates(self):
        vac = admin_actions.BackupAdminController()
        vac.validate_update({'status': 'available'})
        vac.validate_update({'status': 'error'})
        self.assertRaises(exc.HTTPBadRequest,
                          vac.validate_update,
                          {'status': 'restoring'})
        self.assertRaises(exc.HTTPBadRequest,
                          vac.validate_update,
                          {'status': 'creating'})
