# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import datetime

import routes
import webob
import webob.dec
import webob.request

from cinder.api import auth as api_auth
from cinder.api import openstack as openstack_api
from cinder.api.openstack import auth
from cinder.api.openstack.volume import limits
from cinder.api.openstack import urlmap
from cinder.api.openstack import volume
from cinder.api.openstack.volume import versions
from cinder.api.openstack import wsgi as os_wsgi
from cinder import context
from cinder import exception as exc
from cinder import utils
from cinder import wsgi
from cinder.openstack.common import timeutils


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
FAKE_UUIDS = {}


class Context(object):
    pass


class FakeRouter(wsgi.Router):
    def __init__(self, ext_mgr=None):
        pass

    @webob.dec.wsgify
    def __call__(self, req):
        res = webob.Response()
        res.status = '200'
        res.headers['X-Test-Success'] = 'True'
        return res


@webob.dec.wsgify
def fake_wsgi(self, req):
    return self.application


def wsgi_app(inner_app_v1=None, fake_auth=True, fake_auth_context=None,
        use_no_auth=False, ext_mgr=None):
    if not inner_app_v1:
        inner_app_v1 = volume.APIRouter(ext_mgr)

    if fake_auth:
        if fake_auth_context is not None:
            ctxt = fake_auth_context
        else:
            ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        api_v1 = openstack_api.FaultWrapper(api_auth.InjectContext(ctxt,
              inner_app_v1))
    elif use_no_auth:
        api_v1 = openstack_api.FaultWrapper(auth.NoAuthMiddleware(
              limits.RateLimitingMiddleware(inner_app_v1)))
    else:
        api_v1 = openstack_api.FaultWrapper(auth.AuthMiddleware(
              limits.RateLimitingMiddleware(inner_app_v1)))

    mapper = urlmap.URLMap()
    mapper['/v1'] = api_v1
    mapper['/'] = openstack_api.FaultWrapper(versions.Versions())
    return mapper


def stub_out_rate_limiting(stubs):
    def fake_rate_init(self, app):
        # super(limits.RateLimitingMiddleware, self).__init__(app)
        self.application = app

    # FIXME(ja): unsure about limits in volumes
    # stubs.Set(cinder.api.openstack.compute.limits.RateLimitingMiddleware,
    #     '__init__', fake_rate_init)

    # stubs.Set(cinder.api.openstack.compute.limits.RateLimitingMiddleware,
    #     '__call__', fake_wsgi)


class FakeToken(object):
    id_count = 0

    def __getitem__(self, key):
        return getattr(self, key)

    def __init__(self, **kwargs):
        FakeToken.id_count += 1
        self.id = FakeToken.id_count
        for k, v in kwargs.iteritems():
            setattr(self, k, v)


class FakeRequestContext(context.RequestContext):
    def __init__(self, *args, **kwargs):
        kwargs['auth_token'] = kwargs.get('auth_token', 'fake_auth_token')
        return super(FakeRequestContext, self).__init__(*args, **kwargs)


class HTTPRequest(webob.Request):

    @classmethod
    def blank(cls, *args, **kwargs):
        kwargs['base_url'] = 'http://localhost/v1'
        use_admin_context = kwargs.pop('use_admin_context', False)
        out = webob.Request.blank(*args, **kwargs)
        out.environ['cinder.context'] = FakeRequestContext('fake_user', 'fake',
                is_admin=use_admin_context)
        return out


class TestRouter(wsgi.Router):
    def __init__(self, controller):
        mapper = routes.Mapper()
        mapper.resource("test", "tests",
                        controller=os_wsgi.Resource(controller))
        super(TestRouter, self).__init__(mapper)


class FakeAuthDatabase(object):
    data = {}

    @staticmethod
    def auth_token_get(context, token_hash):
        return FakeAuthDatabase.data.get(token_hash, None)

    @staticmethod
    def auth_token_create(context, token):
        fake_token = FakeToken(created_at=timeutils.utcnow(), **token)
        FakeAuthDatabase.data[fake_token.token_hash] = fake_token
        FakeAuthDatabase.data['id_%i' % fake_token.id] = fake_token
        return fake_token

    @staticmethod
    def auth_token_destroy(context, token_id):
        token = FakeAuthDatabase.data.get('id_%i' % token_id)
        if token and token.token_hash in FakeAuthDatabase.data:
            del FakeAuthDatabase.data[token.token_hash]
            del FakeAuthDatabase.data['id_%i' % token_id]


class FakeRateLimiter(object):
    def __init__(self, application):
        self.application = application

    @webob.dec.wsgify
    def __call__(self, req):
        return self.application


def get_fake_uuid(token=0):
    if not token in FAKE_UUIDS:
        FAKE_UUIDS[token] = str(utils.gen_uuid())
    return FAKE_UUIDS[token]


def stub_volume(id, **kwargs):
    volume = {
        'id': id,
        'user_id': 'fakeuser',
        'project_id': 'fakeproject',
        'host': 'fakehost',
        'size': 1,
        'availability_zone': 'fakeaz',
        'instance_uuid': 'fakeuuid',
        'mountpoint': '/',
        'status': 'fakestatus',
        'attach_status': 'attached',
        'name': 'vol name',
        'display_name': 'displayname',
        'display_description': 'displaydesc',
        'created_at': datetime.datetime(1, 1, 1, 1, 1, 1),
        'snapshot_id': None,
        'volume_type_id': 'fakevoltype',
        'volume_metadata': [],
        'volume_type': {'name': 'vol_type_name'}}

    volume.update(kwargs)
    return volume


def stub_volume_create(self, context, size, name, description, snapshot,
                       **param):
    vol = stub_volume('1')
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    try:
        vol['snapshot_id'] = snapshot['id']
    except (KeyError, TypeError):
        vol['snapshot_id'] = None
    vol['availability_zone'] = param.get('availability_zone', 'fakeaz')
    return vol


def stub_volume_create_from_image(self, context, size, name, description,
                                  snapshot, volume_type, metadata,
                                  availability_zone):
    vol = stub_volume('1')
    vol['status'] = 'creating'
    vol['size'] = size
    vol['display_name'] = name
    vol['display_description'] = description
    vol['availability_zone'] = 'cinder'
    return vol


def stub_volume_update(self, context, *args, **param):
    pass


def stub_volume_delete(self, context, *args, **param):
    pass


def stub_volume_get(self, context, volume_id):
    return stub_volume(volume_id)


def stub_volume_get_notfound(self, context, volume_id):
    raise exc.NotFound


def stub_volume_get_all(context, search_opts=None):
    return [stub_volume(100, project_id='fake'),
            stub_volume(101, project_id='superfake'),
            stub_volume(102, project_id='superduperfake')]


def stub_volume_get_all_by_project(self, context, search_opts=None):
    return [stub_volume_get(self, context, '1')]


def stub_snapshot(id, **kwargs):
    snapshot = {
        'id': id,
        'volume_id': 12,
        'status': 'available',
        'volume_size': 100,
        'created_at': None,
        'display_name': 'Default name',
        'display_description': 'Default description',
        'project_id': 'fake'
        }

    snapshot.update(kwargs)
    return snapshot


def stub_snapshot_get_all(self):
    return [stub_snapshot(100, project_id='fake'),
            stub_snapshot(101, project_id='superfake'),
            stub_snapshot(102, project_id='superduperfake')]


def stub_snapshot_get_all_by_project(self, context):
    return [stub_snapshot(1)]
