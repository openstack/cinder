# Copyright 2010 OpenStack Foundation
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

import uuid

from oslo_utils import timeutils
import routes
import webob
import webob.dec
import webob.request

from cinder.api.middleware import auth
from cinder.api.middleware import fault
from cinder.api.openstack import wsgi as os_wsgi
from cinder.api import urlmap
from cinder.api.v2 import limits
from cinder.api.v2 import router
from cinder.api import versions
from cinder import context
from cinder import wsgi


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


def wsgi_app(inner_app_v2=None, fake_auth=True, fake_auth_context=None,
             use_no_auth=False, ext_mgr=None):
    if not inner_app_v2:
        inner_app_v2 = router.APIRouter(ext_mgr)

    if fake_auth:
        if fake_auth_context is not None:
            ctxt = fake_auth_context
        else:
            ctxt = context.RequestContext('fake', 'fake', auth_token=True)
        api_v2 = fault.FaultWrapper(auth.InjectContext(ctxt,
                                                       inner_app_v2))
    elif use_no_auth:
        api_v2 = fault.FaultWrapper(auth.NoAuthMiddleware(
            limits.RateLimitingMiddleware(inner_app_v2)))
    else:
        api_v2 = fault.FaultWrapper(auth.AuthMiddleware(
            limits.RateLimitingMiddleware(inner_app_v2)))

    mapper = urlmap.URLMap()
    mapper['/v2'] = api_v2
    mapper['/'] = fault.FaultWrapper(versions.Versions())
    return mapper


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
        super(FakeRequestContext, self).__init__(*args, **kwargs)


class HTTPRequest(webob.Request):

    @classmethod
    def blank(cls, *args, **kwargs):
        if args is not None:
            if args[0].find('v1') == 0:
                kwargs['base_url'] = 'http://localhost/v1'
            else:
                kwargs['base_url'] = 'http://localhost/v2'

        use_admin_context = kwargs.pop('use_admin_context', False)
        out = os_wsgi.Request.blank(*args, **kwargs)
        out.environ['cinder.context'] = FakeRequestContext(
            'fake_user',
            'fakeproject',
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
    if token not in FAKE_UUIDS:
        FAKE_UUIDS[token] = str(uuid.uuid4())
    return FAKE_UUIDS[token]
