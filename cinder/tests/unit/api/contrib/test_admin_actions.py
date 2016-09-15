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

import fixtures
import mock
from oslo_concurrency import lockutils
from oslo_config import fixture as config_fixture
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import webob
from webob import exc

from cinder.api.contrib import admin_actions
from cinder.backup import rpcapi as backup_rpcapi
from cinder.common import constants
from cinder import context
from cinder import db
from cinder import exception
from cinder import objects
from cinder.objects import base as obj_base
from cinder.objects import fields
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import test
from cinder.tests.unit.api.contrib import test_backups
from cinder.tests.unit.api import fakes
from cinder.tests.unit.api.v2 import stubs
from cinder.tests.unit import cast_as_call
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import fake_snapshot
from cinder.volume import api as volume_api
from cinder.volume import rpcapi


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


class BaseAdminTest(test.TestCase):
    def setUp(self):
        super(BaseAdminTest, self).setUp()
        self.volume_api = volume_api.API()
        # admin context
        self.ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

    def _create_volume(self, context, updates=None):
        db_volume = {'status': 'available',
                     'host': 'test',
                     'availability_zone': 'fake_zone',
                     'attach_status': 'detached'}
        if updates:
            db_volume.update(updates)

        volume = objects.Volume(context=context, **db_volume)
        volume.create()
        return volume


class AdminActionsTest(BaseAdminTest):
    def setUp(self):
        super(AdminActionsTest, self).setUp()

        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.fixture = self.useFixture(config_fixture.Config(lockutils.CONF))
        self.fixture.config(lock_path=self.tempdir,
                            group='oslo_concurrency')
        self.fixture.config(disable_process_locking=True,
                            group='oslo_concurrency')
        self.flags(rpc_backend='cinder.openstack.common.rpc.impl_fake')

        cast_as_call.mock_cast_as_call(self.volume_api.volume_rpcapi.client)
        cast_as_call.mock_cast_as_call(self.volume_api.scheduler_rpcapi.client)

        # start service to handle rpc messages for attach requests
        self.svc = self.start_service('volume', host='test')
        self.patch(
            'cinder.objects.Service.get_minimum_obj_version',
            return_value=obj_base.OBJ_VERSIONS.get_current())

        def _get_minimum_rpc_version_mock(ctxt, binary):
            binary_map = {
                'cinder-volume': rpcapi.VolumeAPI,
                'cinder-backup': backup_rpcapi.BackupAPI,
                'cinder-scheduler': scheduler_rpcapi.SchedulerAPI,
            }
            return binary_map[binary].RPC_API_VERSION

        self.patch('cinder.objects.Service.get_minimum_rpc_version',
                   side_effect=_get_minimum_rpc_version_mock)

    def tearDown(self):
        self.svc.stop()
        super(AdminActionsTest, self).tearDown()

    def _issue_volume_reset(self, ctx, volume, updated_status):
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, volume['id']))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes({'os-reset_status': updated_status})
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        return resp

    def _issue_snapshot_reset(self, ctx, snapshot, updated_status):
        req = webob.Request.blank('/v2/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, snapshot.id))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes({'os-reset_status': updated_status})
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        return resp

    def _issue_backup_reset(self, ctx, backup, updated_status):
        req = webob.Request.blank('/v2/%s/backups/%s/action' % (
            fake.PROJECT_ID, backup['id']))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes({'os-reset_status': updated_status})
        req.environ['cinder.context'] = ctx
        with mock.patch(
                'cinder.backup.api.API._get_available_backup_service_host') \
                as mock_get_backup_host:
            mock_get_backup_host.return_value = 'testhost'
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
        volume = db.volume_create(self.ctx, {'attach_status': 'detached'})

        resp = self._issue_volume_reset(self.ctx,
                                        volume,
                                        {'attach_status': 'attached'})

        self.assertEqual(202, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        self.assertEqual('attached', volume['attach_status'])

    def test_reset_attach_invalid_status(self):
        volume = db.volume_create(self.ctx, {'attach_status': 'detached'})

        resp = self._issue_volume_reset(self.ctx,
                                        volume,
                                        {'attach_status': 'bogus-status'})

        self.assertEqual(400, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        self.assertEqual('detached', volume['attach_status'])

    def test_reset_migration_invalid_status(self):
        volume = db.volume_create(self.ctx, {'migration_status': None})

        resp = self._issue_volume_reset(self.ctx,
                                        volume,
                                        {'migration_status': 'bogus-status'})

        self.assertEqual(400, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        self.assertIsNone(volume['migration_status'])

    def test_reset_migration_status(self):
        volume = db.volume_create(self.ctx, {'migration_status': None})

        resp = self._issue_volume_reset(self.ctx,
                                        volume,
                                        {'migration_status': 'migrating'})

        self.assertEqual(202, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        self.assertEqual('migrating', volume['migration_status'])

    def test_reset_status_as_admin(self):
        volume = db.volume_create(self.ctx, {'status': 'available'})

        resp = self._issue_volume_reset(self.ctx,
                                        volume,
                                        {'status': 'error'})

        self.assertEqual(202, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        self.assertEqual('error', volume['status'])

    def test_reset_status_as_non_admin(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        volume = db.volume_create(self.ctx,
                                  {'status': 'error', 'size': 1})

        resp = self._issue_volume_reset(ctx,
                                        volume,
                                        {'status': 'error'})

        # request is not authorized
        self.assertEqual(403, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        # status is still 'error'
        self.assertEqual('error', volume['status'])

    def test_backup_reset_status_as_admin(self):
        volume = db.volume_create(self.ctx, {'status': 'available',
                                             'user_id': fake.USER_ID,
                                             'project_id': fake.PROJECT_ID})
        backup = db.backup_create(self.ctx,
                                  {'status': fields.BackupStatus.AVAILABLE,
                                   'size': 1,
                                   'volume_id': volume['id'],
                                   'user_id': fake.USER_ID,
                                   'project_id': fake.PROJECT_ID,
                                   'host': 'test'})

        resp = self._issue_backup_reset(self.ctx,
                                        backup,
                                        {'status': fields.BackupStatus.ERROR})

        self.assertEqual(202, resp.status_int)

    def test_backup_reset_status_as_non_admin(self):
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        backup = db.backup_create(ctx, {'status': 'available',
                                        'size': 1,
                                        'volume_id': "fakeid",
                                        'host': 'test'})
        resp = self._issue_backup_reset(ctx,
                                        backup,
                                        {'status': fields.BackupStatus.ERROR})
        # request is not authorized
        self.assertEqual(403, resp.status_int)

    def test_backup_reset_status(self):
        volume = db.volume_create(self.ctx,
                                  {'status': 'available', 'host': 'test',
                                   'provider_location': '', 'size': 1})
        backup = db.backup_create(self.ctx,
                                  {'status': fields.BackupStatus.AVAILABLE,
                                   'volume_id': volume['id'],
                                   'user_id': fake.USER_ID,
                                   'project_id': fake.PROJECT_ID,
                                   'host': 'test'})

        resp = self._issue_backup_reset(self.ctx,
                                        backup,
                                        {'status': fields.BackupStatus.ERROR})

        self.assertEqual(202, resp.status_int)

    def test_invalid_status_for_backup(self):
        volume = db.volume_create(self.ctx,
                                  {'status': 'available', 'host': 'test',
                                   'provider_location': '', 'size': 1})
        backup = db.backup_create(self.ctx, {'status': 'available',
                                             'volume_id': volume['id']})
        resp = self._issue_backup_reset(self.ctx,
                                        backup,
                                        {'status': 'restoring'})
        self.assertEqual(400, resp.status_int)

    def test_backup_reset_status_with_invalid_backup(self):
        volume = db.volume_create(self.ctx,
                                  {'status': 'available', 'host': 'test',
                                   'provider_location': '', 'size': 1})
        backup = db.backup_create(self.ctx,
                                  {'status': fields.BackupStatus.AVAILABLE,
                                   'volume_id': volume['id'],
                                   'user_id': fake.USER_ID,
                                   'project_id': fake.PROJECT_ID})

        backup['id'] = fake.BACKUP_ID
        resp = self._issue_backup_reset(self.ctx,
                                        backup,
                                        {'status': fields.BackupStatus.ERROR})

        # Should raise 404 if backup doesn't exist.
        self.assertEqual(404, resp.status_int)

    def test_malformed_reset_status_body(self):
        volume = db.volume_create(self.ctx, {'status': 'available', 'size': 1})

        resp = self._issue_volume_reset(self.ctx,
                                        volume,
                                        {'x-status': 'bad'})

        self.assertEqual(400, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        self.assertEqual('available', volume['status'])

    def test_invalid_status_for_volume(self):
        volume = db.volume_create(self.ctx, {'status': 'available', 'size': 1})
        resp = self._issue_volume_reset(self.ctx,
                                        volume,
                                        {'status': 'invalid'})

        self.assertEqual(400, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        self.assertEqual('available', volume['status'])

    def test_reset_status_for_missing_volume(self):
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, fake.WILL_NOT_BE_FOUND_ID))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        body = {'os-reset_status': {'status': 'available'}}
        req.body = jsonutils.dump_as_bytes(body)
        req.environ['cinder.context'] = self.ctx
        resp = req.get_response(app())
        self.assertEqual(404, resp.status_int)
        self.assertRaises(exception.NotFound, db.volume_get, self.ctx,
                          fake.WILL_NOT_BE_FOUND_ID)

    def test_reset_attached_status(self):
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})
        self.volume_api.reserve_volume(self.ctx, volume)
        mountpoint = '/dev/vdb'
        attachment = self.volume_api.attach(self.ctx, volume, fake.INSTANCE_ID,
                                            None, mountpoint, 'rw')
        # volume is attached
        volume = db.volume_get(self.ctx.elevated(), volume['id'])
        attachment = db.volume_attachment_get(self.ctx, attachment['id'])

        self.assertEqual('in-use', volume['status'])
        self.assertEqual('attached', volume['attach_status'])
        self.assertEqual(fake.INSTANCE_ID, attachment['instance_uuid'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual('attached', attachment['attach_status'])
        admin_metadata = volume['volume_admin_metadata']
        self.assertEqual(2, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('False', admin_metadata[0]['value'])
        self.assertEqual('attached_mode', admin_metadata[1]['key'])
        self.assertEqual('rw', admin_metadata[1]['value'])

        # Reset attach_status
        resp = self._issue_volume_reset(self.ctx,
                                        volume,
                                        {'status': 'available',
                                         'attach_status': 'detached'})
        # request is accepted
        self.assertEqual(202, resp.status_int)

        # volume is detached
        volume = db.volume_get(self.ctx, volume['id'])
        self.assertEqual('detached', volume['attach_status'])
        self.assertEqual('available', volume['status'])
        admin_metadata = volume['volume_admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('readonly', admin_metadata[0]['key'])
        self.assertEqual('False', admin_metadata[0]['value'])
        self.assertRaises(exception.VolumeAttachmentNotFound,
                          db.volume_attachment_get,
                          self.ctx, attachment['id'])

    def test_invalid_reset_attached_status(self):
        volume = db.volume_create(self.ctx,
                                  {'status': 'available', 'host': 'test',
                                   'provider_location': '', 'size': 1,
                                   'attach_status': 'detached'})
        resp = self._issue_volume_reset(self.ctx,
                                        volume,
                                        {'status': 'available',
                                         'attach_status': 'invalid'})
        self.assertEqual(400, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        self.assertEqual('available', volume['status'])
        self.assertEqual('detached', volume['attach_status'])

    def test_snapshot_reset_status(self):
        volume = db.volume_create(self.ctx,
                                  {'status': 'available', 'host': 'test',
                                   'provider_location': '', 'size': 1,
                                   'availability_zone': 'test',
                                   'attach_status': 'detached'})
        kwargs = {
            'volume_id': volume['id'],
            'cgsnapshot_id': None,
            'user_id': self.ctx.user_id,
            'project_id': self.ctx.project_id,
            'status': fields.SnapshotStatus.ERROR_DELETING,
            'progress': '0%',
            'volume_size': volume['size'],
            'metadata': {}
        }
        snapshot = objects.Snapshot(context=self.ctx, **kwargs)
        snapshot.create()
        self.addCleanup(snapshot.destroy)

        resp = self._issue_snapshot_reset(self.ctx, snapshot,
                                          {'status':
                                           fields.SnapshotStatus.ERROR})

        self.assertEqual(202, resp.status_int)
        snapshot = objects.Snapshot.get_by_id(self.ctx, snapshot['id'])
        self.assertEqual(fields.SnapshotStatus.ERROR, snapshot.status)

    def test_invalid_status_for_snapshot(self):
        volume = db.volume_create(self.ctx,
                                  {'status': 'available', 'host': 'test',
                                   'provider_location': '', 'size': 1})
        snapshot = objects.Snapshot(self.ctx,
                                    status=fields.SnapshotStatus.AVAILABLE,
                                    volume_id=volume['id'])
        snapshot.create()
        self.addCleanup(snapshot.destroy)

        resp = self._issue_snapshot_reset(self.ctx, snapshot,
                                          {'status': 'attaching'})

        self.assertEqual(400, resp.status_int)
        self.assertEqual(fields.SnapshotStatus.AVAILABLE, snapshot.status)

    def test_force_delete(self):
        # current status is creating
        volume = self._create_volume(self.ctx, {'size': 1, 'host': None})
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, volume['id']))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes({'os-force_delete': {}})
        # attach admin context to request
        req.environ['cinder.context'] = self.ctx
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(202, resp.status_int)
        # volume is deleted
        self.assertRaises(exception.NotFound, objects.Volume.get_by_id,
                          self.ctx, volume.id)

    @mock.patch.object(volume_api.API, 'delete_snapshot', return_value=True)
    @mock.patch('cinder.objects.Snapshot.get_by_id')
    @mock.patch.object(db, 'snapshot_get')
    @mock.patch.object(db, 'volume_get')
    def test_force_delete_snapshot(self, volume_get, snapshot_get, get_by_id,
                                   delete_snapshot):
        volume = stubs.stub_volume(fake.VOLUME_ID)
        snapshot = stubs.stub_snapshot(fake.SNAPSHOT_ID)
        snapshot_obj = fake_snapshot.fake_snapshot_obj(self.ctx, **snapshot)
        volume_get.return_value = volume
        snapshot_get.return_value = snapshot
        get_by_id.return_value = snapshot_obj

        path = '/v2/%s/snapshots/%s/action' % (
            fake.PROJECT_ID, snapshot['id'])
        req = webob.Request.blank(path)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes({'os-force_delete': {}})
        # attach admin context to request
        req.environ['cinder.context'] = self.ctx
        resp = req.get_response(app())
        self.assertEqual(202, resp.status_int)

    def _migrate_volume_prep(self):
        # create volume's current host and the destination host
        db.service_create(self.ctx,
                          {'host': 'test',
                           'topic': constants.VOLUME_TOPIC,
                           'created_at': timeutils.utcnow()})
        db.service_create(self.ctx,
                          {'host': 'test2',
                           'topic': constants.VOLUME_TOPIC,
                           'created_at': timeutils.utcnow()})
        # current status is available
        volume = self._create_volume(self.ctx)
        return volume

    def _migrate_volume_exec(self, ctx, volume, host, expected_status,
                             force_host_copy=False):
        # build request to migrate to host
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, volume['id']))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        body = {'os-migrate_volume': {'host': host,
                                      'force_host_copy': force_host_copy}}
        req.body = jsonutils.dump_as_bytes(body)
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        # verify status
        self.assertEqual(expected_status, resp.status_int)
        volume = db.volume_get(self.ctx, volume['id'])
        return volume

    def test_migrate_volume_success(self):
        expected_status = 202
        host = 'test2'
        volume = self._migrate_volume_prep()
        volume = self._migrate_volume_exec(self.ctx, volume, host,
                                           expected_status)
        self.assertEqual('starting', volume['migration_status'])

    def test_migrate_volume_fail_replication(self):
        expected_status = 400
        host = 'test2'
        volume = self._migrate_volume_prep()
        # current status is available
        volume = self._create_volume(self.ctx,
                                     {'provider_location': '',
                                      'attach_status': '',
                                      'replication_status': 'active'})
        volume = self._migrate_volume_exec(self.ctx, volume, host,
                                           expected_status)

    def test_migrate_volume_as_non_admin(self):
        expected_status = 403
        host = 'test2'
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        volume = self._migrate_volume_prep()
        self._migrate_volume_exec(ctx, volume, host, expected_status)

    def test_migrate_volume_without_host_parameter(self):
        expected_status = 400
        host = 'test3'
        volume = self._migrate_volume_prep()
        # build request to migrate without host
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, volume['id']))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        body = {'os-migrate_volume': {'host': host,
                                      'force_host_copy': False}}
        req.body = jsonutils.dump_as_bytes(body)
        req.environ['cinder.context'] = self.ctx
        resp = req.get_response(app())
        # verify status
        self.assertEqual(expected_status, resp.status_int)

    def test_migrate_volume_host_no_exist(self):
        expected_status = 400
        host = 'test3'
        volume = self._migrate_volume_prep()
        self._migrate_volume_exec(self.ctx, volume, host, expected_status)

    def test_migrate_volume_same_host(self):
        expected_status = 400
        host = 'test'
        volume = self._migrate_volume_prep()
        self._migrate_volume_exec(self.ctx, volume, host, expected_status)

    def test_migrate_volume_migrating(self):
        expected_status = 400
        host = 'test2'
        volume = self._migrate_volume_prep()
        model_update = {'migration_status': 'migrating'}
        volume = db.volume_update(self.ctx, volume['id'], model_update)
        self._migrate_volume_exec(self.ctx, volume, host, expected_status)

    def test_migrate_volume_with_snap(self):
        expected_status = 400
        host = 'test2'
        volume = self._migrate_volume_prep()
        snap = objects.Snapshot(self.ctx, volume_id=volume['id'])
        snap.create()
        self.addCleanup(snap.destroy)
        self._migrate_volume_exec(self.ctx, volume, host, expected_status)

    def test_migrate_volume_bad_force_host_copy(self):
        expected_status = 400
        host = 'test2'
        volume = self._migrate_volume_prep()
        self._migrate_volume_exec(self.ctx, volume, host, expected_status,
                                  force_host_copy='foo')

    def _migrate_volume_comp_exec(self, ctx, volume, new_volume, error,
                                  expected_status, expected_id, no_body=False):
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, volume['id']))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        body = {'new_volume': new_volume['id'], 'error': error}
        if no_body:
            body = {'': body}
        else:
            body = {'os-migrate_volume_completion': body}
        req.body = jsonutils.dump_as_bytes(body)
        req.environ['cinder.context'] = ctx
        resp = req.get_response(app())
        resp_dict = resp.json
        # verify status
        self.assertEqual(expected_status, resp.status_int)
        if expected_id:
            self.assertEqual(expected_id, resp_dict['save_volume_id'])
        else:
            self.assertNotIn('save_volume_id', resp_dict)

    def test_migrate_volume_comp_as_non_admin(self):
        volume = db.volume_create(self.ctx, {'id': fake.VOLUME_ID})
        new_volume = db.volume_create(self.ctx, {'id': fake.VOLUME2_ID})
        expected_status = 403
        expected_id = None
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        self._migrate_volume_comp_exec(ctx, volume, new_volume, False,
                                       expected_status, expected_id)

    def test_migrate_volume_comp_no_mig_status(self):
        volume1 = self._create_volume(self.ctx, {'migration_status': 'foo'})
        volume2 = self._create_volume(self.ctx, {'migration_status': None})

        expected_status = 400
        expected_id = None
        self._migrate_volume_comp_exec(self.ctx, volume1, volume2, False,
                                       expected_status, expected_id)
        self._migrate_volume_comp_exec(self.ctx, volume2, volume1, False,
                                       expected_status, expected_id)

    def test_migrate_volume_comp_bad_mig_status(self):
        volume1 = self._create_volume(self.ctx,
                                      {'migration_status': 'migrating'})
        volume2 = self._create_volume(self.ctx,
                                      {'migration_status': 'target:foo'})
        expected_status = 400
        expected_id = None
        self._migrate_volume_comp_exec(self.ctx, volume1, volume2, False,
                                       expected_status, expected_id)

    def test_migrate_volume_comp_no_action(self):
        volume = db.volume_create(self.ctx, {'id': fake.VOLUME_ID})
        new_volume = db.volume_create(self.ctx, {'id': fake.VOLUME2_ID})
        expected_status = 400
        expected_id = None
        ctx = context.RequestContext(fake.USER_ID, fake.PROJECT_ID)
        self._migrate_volume_comp_exec(ctx, volume, new_volume, False,
                                       expected_status, expected_id, True)

    def test_migrate_volume_comp_from_nova(self):
        volume = self._create_volume(self.ctx, {'status': 'in-use',
                                                'migration_status': None,
                                                'attach_status': 'attached'})
        new_volume = self._create_volume(self.ctx,
                                         {'migration_status': None,
                                          'attach_status': 'detached'})
        expected_status = 200
        expected_id = new_volume.id
        self._migrate_volume_comp_exec(self.ctx, volume, new_volume, False,
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

    @mock.patch('cinder.backup.rpcapi.BackupAPI.delete_backup', mock.Mock())
    @mock.patch('cinder.db.service_get_all')
    @mock.patch('cinder.backup.api.API._check_support_to_force_delete')
    def _force_delete_backup_util(self, test_status, mock_check_support,
                                  mock_service_get_all):
        mock_service_get_all.return_value = [
            {'availability_zone': "az1", 'host': 'testhost',
             'disabled': 0, 'updated_at': timeutils.utcnow()}]
        # admin context
        mock_check_support.return_value = True
        # current status is dependent on argument: test_status.
        id = test_backups.BackupsAPITestCase._create_backup(status=test_status)
        req = webob.Request.blank('/v2/%s/backups/%s/action' % (
            fake.PROJECT_ID, id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes({'os-force_delete': {}})
        req.environ['cinder.context'] = self.ctx
        res = req.get_response(app())

        self.assertEqual(202, res.status_int)
        self.assertEqual(
            'deleting',
            test_backups.BackupsAPITestCase._get_backup_attrib(id, 'status'))
        db.backup_destroy(self.ctx, id)

    def test_delete_backup_force_when_creating(self):
        self._force_delete_backup_util('creating')

    def test_delete_backup_force_when_deleting(self):
        self._force_delete_backup_util('deleting')

    def test_delete_backup_force_when_restoring(self):
        self._force_delete_backup_util('restoring')

    def test_delete_backup_force_when_available(self):
        self._force_delete_backup_util('available')

    def test_delete_backup_force_when_error(self):
        self._force_delete_backup_util('error')

    def test_delete_backup_force_when_error_deleting(self):
        self._force_delete_backup_util('error_deleting')

    @mock.patch('cinder.backup.rpcapi.BackupAPI.check_support_to_force_delete',
                return_value=False)
    def test_delete_backup_force_when_not_supported(self, mock_check_support):
        # admin context
        self.override_config('backup_driver', 'cinder.backup.drivers.ceph')
        id = test_backups.BackupsAPITestCase._create_backup()
        req = webob.Request.blank('/v2/%s/backups/%s/action' % (
            fake.PROJECT_ID, id))
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = jsonutils.dump_as_bytes({'os-force_delete': {}})
        req.environ['cinder.context'] = self.ctx
        res = req.get_response(app())
        self.assertEqual(405, res.status_int)


class AdminActionsAttachDetachTest(BaseAdminTest):
    def setUp(self):
        super(AdminActionsAttachDetachTest, self).setUp()
        # start service to handle rpc messages for attach requests
        self.svc = self.start_service('volume', host='test')

    def tearDown(self):
        self.svc.stop()
        super(AdminActionsAttachDetachTest, self).tearDown()

    def test_force_detach_instance_attached_volume(self):
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}

        self.volume_api.reserve_volume(self.ctx, volume)
        mountpoint = '/dev/vbd'
        attachment = self.volume_api.attach(self.ctx, volume, fake.INSTANCE_ID,
                                            None, mountpoint, 'rw')
        # volume is attached
        volume = objects.Volume.get_by_id(self.ctx, volume.id)
        self.assertEqual('in-use', volume.status)
        self.assertEqual(fake.INSTANCE_ID, attachment['instance_uuid'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual('attached', attachment['attach_status'])
        admin_metadata = volume.admin_metadata
        self.assertEqual(2, len(admin_metadata))
        self.assertEqual('False', admin_metadata['readonly'])
        self.assertEqual('rw', admin_metadata['attached_mode'])
        conn_info = self.volume_api.initialize_connection(self.ctx,
                                                          volume,
                                                          connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])
        # build request to force detach
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, volume.id))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request status of 'error'
        body = {'os-force_detach': {'attachment_id': attachment['id'],
                                    'connector': connector}}
        req.body = jsonutils.dump_as_bytes(body)
        # attach admin context to request
        req.environ['cinder.context'] = self.ctx
        # make request
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(202, resp.status_int)
        volume.refresh()
        self.assertRaises(exception.VolumeAttachmentNotFound,
                          db.volume_attachment_get,
                          self.ctx, attachment['id'])

        # status changed to 'available'
        self.assertEqual('available', volume.status)
        admin_metadata = volume.admin_metadata
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('False', admin_metadata['readonly'])

    def test_force_detach_host_attached_volume(self):
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}

        self.volume_api.initialize_connection(self.ctx, volume, connector)
        mountpoint = '/dev/vbd'
        host_name = 'fake-host'
        attachment = self.volume_api.attach(self.ctx, volume, None, host_name,
                                            mountpoint, 'ro')
        # volume is attached
        volume.refresh()
        self.assertEqual('in-use', volume.status)
        self.assertIsNone(attachment['instance_uuid'])
        self.assertEqual(host_name, attachment['attached_host'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual('attached', attachment['attach_status'])
        admin_metadata = volume.admin_metadata
        self.assertEqual(2, len(admin_metadata))
        self.assertEqual('False', admin_metadata['readonly'])
        self.assertEqual('ro', admin_metadata['attached_mode'])
        conn_info = self.volume_api.initialize_connection(self.ctx,
                                                          volume, connector)
        self.assertEqual('ro', conn_info['data']['access_mode'])
        # build request to force detach
        req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
            fake.PROJECT_ID, volume.id))
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        # request status of 'error'
        body = {'os-force_detach': {'attachment_id': attachment['id'],
                                    'connector': connector}}
        req.body = jsonutils.dump_as_bytes(body)
        # attach admin context to request
        req.environ['cinder.context'] = self.ctx
        # make request
        resp = req.get_response(app())
        # request is accepted
        self.assertEqual(202, resp.status_int)
        volume.refresh()
        self.assertRaises(exception.VolumeAttachmentNotFound,
                          db.volume_attachment_get,
                          self.ctx, attachment['id'])
        # status changed to 'available'
        self.assertEqual('available', volume['status'])
        admin_metadata = volume['admin_metadata']
        self.assertEqual(1, len(admin_metadata))
        self.assertEqual('False', admin_metadata['readonly'])

    def test_volume_force_detach_raises_remote_error(self):
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}

        self.volume_api.reserve_volume(self.ctx, volume)
        mountpoint = '/dev/vbd'
        attachment = self.volume_api.attach(self.ctx, volume, fake.INSTANCE_ID,
                                            None, mountpoint, 'rw')
        # volume is attached
        volume.refresh()
        self.assertEqual('in-use', volume.status)
        self.assertEqual(fake.INSTANCE_ID, attachment['instance_uuid'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual('attached', attachment['attach_status'])
        admin_metadata = volume.admin_metadata
        self.assertEqual(2, len(admin_metadata))
        self.assertEqual('False', admin_metadata['readonly'])
        self.assertEqual('rw', admin_metadata['attached_mode'])
        conn_info = self.volume_api.initialize_connection(self.ctx,
                                                          volume,
                                                          connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])
        # build request to force detach
        volume_remote_error = \
            messaging.RemoteError(exc_type='VolumeAttachmentNotFound')
        with mock.patch.object(volume_api.API, 'detach',
                               side_effect=volume_remote_error):
            req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
                fake.PROJECT_ID, volume.id))
            req.method = 'POST'
            req.headers['content-type'] = 'application/json'
            body = {'os-force_detach': {'attachment_id': fake.ATTACHMENT_ID}}
            req.body = jsonutils.dump_as_bytes(body)
            # attach admin context to request
            req.environ['cinder.context'] = self.ctx
            # make request
            resp = req.get_response(app())
            self.assertEqual(400, resp.status_int)

        # test for KeyError when missing connector
        volume_remote_error = (
            messaging.RemoteError(exc_type='KeyError'))
        with mock.patch.object(volume_api.API, 'detach',
                               side_effect=volume_remote_error):
            req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
                fake.PROJECT_ID, volume.id))
            req.method = 'POST'
            req.headers['content-type'] = 'application/json'
            body = {'os-force_detach': {'attachment_id': fake.ATTACHMENT_ID}}
            req.body = jsonutils.dump_as_bytes(body)
            # attach admin context to request
            req.environ['cinder.context'] = self.ctx
            # make request
            self.assertRaises(messaging.RemoteError,
                              req.get_response,
                              app())

        # test for VolumeBackendAPIException
        volume_remote_error = (
            messaging.RemoteError(exc_type='VolumeBackendAPIException'))
        with mock.patch.object(volume_api.API, 'detach',
                               side_effect=volume_remote_error):
            req = webob.Request.blank('/v2/%s/volumes/%s/action' % (
                fake.PROJECT_ID, volume.id))
            req.method = 'POST'
            req.headers['content-type'] = 'application/json'
            body = {'os-force_detach': {'attachment_id': fake.ATTACHMENT_ID,
                                        'connector': connector}}
            req.body = jsonutils.dump_as_bytes(body)

            # attach admin context to request
            req.environ['cinder.context'] = self.ctx
            # make request
            self.assertRaises(messaging.RemoteError,
                              req.get_response,
                              app())

    def test_volume_force_detach_raises_db_error(self):
        # In case of DB error 500 error code is returned to user
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}

        self.volume_api.reserve_volume(self.ctx, volume)
        mountpoint = '/dev/vbd'
        attachment = self.volume_api.attach(self.ctx, volume, fake.INSTANCE_ID,
                                            None, mountpoint, 'rw')
        # volume is attached
        volume.refresh()
        self.assertEqual('in-use', volume.status)
        self.assertEqual(fake.INSTANCE_ID, attachment['instance_uuid'])
        self.assertEqual(mountpoint, attachment['mountpoint'])
        self.assertEqual('attached', attachment['attach_status'])
        admin_metadata = volume.admin_metadata
        self.assertEqual(2, len(admin_metadata))
        self.assertEqual('False', admin_metadata['readonly'])
        self.assertEqual('rw', admin_metadata['attached_mode'])
        conn_info = self.volume_api.initialize_connection(self.ctx,
                                                          volume,
                                                          connector)
        self.assertEqual('rw', conn_info['data']['access_mode'])
        # build request to force detach
        volume_remote_error = messaging.RemoteError(exc_type='DBError')
        with mock.patch.object(volume_api.API, 'detach',
                               side_effect=volume_remote_error):
            req = webob.Request.blank('/v2/%s/volumes/%s/action' %
                                      (fake.PROJECT_ID, volume.id))
            req.method = 'POST'
            req.headers['content-type'] = 'application/json'
            body = {'os-force_detach': {'attachment_id': fake.ATTACHMENT_ID,
                                        'connector': connector}}
            req.body = jsonutils.dump_as_bytes(body)
            # attach admin context to request
            req.environ['cinder.context'] = self.ctx
            # make request
            self.assertRaises(messaging.RemoteError,
                              req.get_response,
                              app())

    def test_attach_in_used_volume_by_instance(self):
        """Test that attaching to an in-use volume fails."""
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        self.volume_api.reserve_volume(self.ctx, volume)
        conn_info = self.volume_api.initialize_connection(self.ctx,
                                                          volume, connector)
        self.volume_api.attach(self.ctx, volume, fake.INSTANCE_ID, None,
                               '/dev/vbd0', 'rw')
        self.assertEqual('rw', conn_info['data']['access_mode'])
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          self.ctx,
                          volume,
                          fake.INSTANCE_ID,
                          None,
                          '/dev/vdb1',
                          'ro')

    def test_attach_in_used_volume_by_host(self):
        """Test that attaching to an in-use volume fails."""
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}

        self.volume_api.reserve_volume(self.ctx, volume)
        self.volume_api.initialize_connection(self.ctx, volume, connector)
        self.volume_api.attach(self.ctx, volume, None, 'fake_host1',
                               '/dev/vbd0', 'rw')
        conn_info = self.volume_api.initialize_connection(self.ctx,
                                                          volume, connector)
        conn_info['data']['access_mode'] = 'rw'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          self.ctx,
                          volume,
                          None,
                          'fake_host2',
                          '/dev/vbd1',
                          'ro')

    def test_invalid_iscsi_connector(self):
        """Test connector without the initiator (required by iscsi driver)."""
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})
        connector = {}

        self.assertRaises(exception.InvalidInput,
                          self.volume_api.initialize_connection,
                          self.ctx, volume, connector)

    def test_attach_attaching_volume_with_different_instance(self):
        """Test that attaching volume reserved for another instance fails."""
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})

        self.volume_api.reserve_volume(self.ctx, volume)
        values = {'volume_id': volume['id'],
                  'attach_status': 'attaching',
                  'attach_time': timeutils.utcnow(),
                  'instance_uuid': 'abc123',
                  }
        db.volume_attach(self.ctx, values)
        db.volume_admin_metadata_update(self.ctx, volume['id'],
                                        {"attached_mode": 'rw'}, False)
        mountpoint = '/dev/vbd'
        attachment = self.volume_api.attach(self.ctx, volume,
                                            fake.INSTANCE_ID, None,
                                            mountpoint, 'rw')

        self.assertEqual(fake.INSTANCE_ID, attachment['instance_uuid'])
        self.assertEqual(volume['id'], attachment['volume_id'], volume['id'])
        self.assertEqual('attached', attachment['attach_status'])

    def test_attach_attaching_volume_with_different_mode(self):
        """Test that attaching volume reserved for another mode fails."""
        # current status is available
        volume = self._create_volume(self.ctx, {'provider_location': '',
                                                'size': 1})

        values = {'status': 'attaching',
                  'instance_uuid': fake.INSTANCE_ID}
        db.volume_update(self.ctx, volume['id'], values)
        db.volume_admin_metadata_update(self.ctx, volume['id'],
                                        {"attached_mode": 'rw'}, False)
        mountpoint = '/dev/vbd'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          self.ctx,
                          volume,
                          values['instance_uuid'],
                          None,
                          mountpoint,
                          'ro')
