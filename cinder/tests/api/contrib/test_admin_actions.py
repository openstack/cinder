import shutil
import tempfile
import webob

from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import jsonutils
from cinder import test
from cinder.tests.api import fakes
from cinder.tests.api.v2 import stubs
from cinder.volume import api as volume_api


def app():
    # no auth, just let environ['cinder.context'] pass through
    api = fakes.router.APIRouter()
    mapper = fakes.urlmap.URLMap()
    mapper['/v2'] = api
    return mapper


class AdminActionsTest(test.TestCase):

    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        super(AdminActionsTest, self).setUp()
        self.flags(rpc_backend='cinder.openstack.common.rpc.impl_fake')
        self.flags(lock_path=self.tempdir)
        self.volume_api = volume_api.API()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

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
        self.assertEquals(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        # status changed to 'error'
        self.assertEquals(volume['status'], 'error')

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
        self.assertEquals(resp.status_int, 403)
        volume = db.volume_get(context.get_admin_context(), volume['id'])
        # status is still 'error'
        self.assertEquals(volume['status'], 'error')

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
        self.assertEquals(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        # status is still 'available'
        self.assertEquals(volume['status'], 'available')

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
        self.assertEquals(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        # status is still 'available'
        self.assertEquals(volume['status'], 'available')

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
        self.assertEquals(resp.status_int, 404)
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
        self.assertEquals(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        # attach_status changed to 'detached'
        self.assertEquals(volume['attach_status'], 'detached')
        # status un-modified
        self.assertEquals(volume['status'], 'available')

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
        self.assertEquals(resp.status_int, 400)
        volume = db.volume_get(ctx, volume['id'])
        # status and attach_status un-modified
        self.assertEquals(volume['status'], 'available')
        self.assertEquals(volume['attach_status'], 'detached')

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
        self.assertEquals(resp.status_int, 202)
        snapshot = db.snapshot_get(ctx, snapshot['id'])
        # status changed to 'error'
        self.assertEquals(snapshot['status'], 'error')

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
        self.assertEquals(resp.status_int, 400)
        snapshot = db.snapshot_get(ctx, snapshot['id'])
        # status is still 'available'
        self.assertEquals(snapshot['status'], 'available')

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
        self.assertEquals(resp.status_int, 202)
        # volume is deleted
        self.assertRaises(exception.NotFound, db.volume_get, ctx, volume['id'])

    def test_force_delete_snapshot(self):
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
        self.start_service('volume', host='test')
        # make request
        resp = req.get_response(app())
        # request is accepted
        self.assertEquals(resp.status_int, 202)
        # snapshot is deleted
        self.assertRaises(exception.NotFound, db.snapshot_get, ctx,
                          snapshot['id'])

    def test_force_detach_volume(self):
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        # start service to handle rpc messages for attach requests
        self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        self.volume_api.initialize_connection(ctx, volume, {})
        mountpoint = '/dev/vbd'
        self.volume_api.attach(ctx, volume, stubs.FAKE_UUID, mountpoint)
        # volume is attached
        volume = db.volume_get(ctx, volume['id'])
        self.assertEquals(volume['status'], 'in-use')
        self.assertEquals(volume['instance_uuid'], stubs.FAKE_UUID)
        self.assertEquals(volume['mountpoint'], mountpoint)
        self.assertEquals(volume['attach_status'], 'attached')
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
        self.assertEquals(resp.status_int, 202)
        volume = db.volume_get(ctx, volume['id'])
        # status changed to 'available'
        self.assertEquals(volume['status'], 'available')
        self.assertEquals(volume['instance_uuid'], None)
        self.assertEquals(volume['mountpoint'], None)
        self.assertEquals(volume['attach_status'], 'detached')

    def test_attach_in_use_volume(self):
        """Test that attaching to an in-use volume fails."""
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        # start service to handle rpc messages for attach requests
        self.start_service('volume', host='test')
        self.volume_api.reserve_volume(ctx, volume)
        self.volume_api.initialize_connection(ctx, volume, {})
        mountpoint = '/dev/vbd'
        self.volume_api.attach(ctx, volume, stubs.FAKE_UUID, mountpoint)
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          fakes.get_fake_uuid(),
                          mountpoint)

    def test_attach_attaching_volume_with_different_instance(self):
        """Test that attaching volume reserved for another instance fails."""
        # admin context
        ctx = context.RequestContext('admin', 'fake', True)
        # current status is available
        volume = db.volume_create(ctx, {'status': 'available', 'host': 'test',
                                        'provider_location': ''})
        # start service to handle rpc messages for attach requests
        self.start_service('volume', host='test')
        self.volume_api.initialize_connection(ctx, volume, {})
        values = {'status': 'attaching',
                  'instance_uuid': fakes.get_fake_uuid()}
        db.volume_update(ctx, volume['id'], values)
        mountpoint = '/dev/vbd'
        self.assertRaises(exception.InvalidVolume,
                          self.volume_api.attach,
                          ctx,
                          volume,
                          stubs.FAKE_UUID,
                          mountpoint)
