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
"""
Common Auth Middleware.

"""

from http import HTTPStatus
import os

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
import webob.dec
import webob.exc

from cinder.api.openstack import wsgi
from cinder import context
from cinder.i18n import _
from cinder.wsgi import common as base_wsgi


use_forwarded_for_opt = cfg.BoolOpt(
    'use_forwarded_for',
    default=False,
    help='Treat X-Forwarded-For as the canonical remote address. '
         'Only enable this if you have a sanitizing proxy.')

CONF = cfg.CONF
CONF.register_opt(use_forwarded_for_opt)

LOG = logging.getLogger(__name__)


def pipeline_factory(loader, global_conf, **local_conf):
    """A paste pipeline replica that keys off of auth_strategy."""
    pipeline = local_conf[CONF.auth_strategy]
    if not CONF.api_rate_limit:
        limit_name = CONF.auth_strategy + '_nolimit'
        pipeline = local_conf.get(limit_name, pipeline)
    pipeline = pipeline.split()
    filters = [loader.get_filter(n) for n in pipeline[:-1]]
    app = loader.get_app(pipeline[-1])
    filters.reverse()
    for filter in filters:
        app = filter(app)
    return app


def _set_request_context(req, **kwargs):
    """Sets request context based on parameters and request."""
    remote_address = getattr(req, 'remote_address', '127.0.0.1')

    service_catalog = None
    if req.headers.get('X_SERVICE_CATALOG') is not None:
        try:
            catalog_header = req.headers.get('X_SERVICE_CATALOG')
            service_catalog = jsonutils.loads(catalog_header)
        except ValueError:
            raise webob.exc.HTTPInternalServerError(
                explanation=_('Invalid service catalog json.'))

    if CONF.use_forwarded_for:
        remote_address = req.headers.get('X-Forwarded-For', remote_address)

    kwargs.setdefault('remote_address', remote_address)
    kwargs.setdefault('service_catalog', service_catalog)

    # Preserve the timestamp set by the RequestId middleware
    kwargs['timestamp'] = getattr(req.environ.get('cinder.context'),
                                  'timestamp',
                                  None)

    # request ID and global ID are present in the environment req.environ
    ctx = context.RequestContext.from_environ(req.environ, **kwargs)
    req.environ['cinder.context'] = ctx
    return ctx


class InjectContext(base_wsgi.Middleware):
    """Add a 'cinder.context' to WSGI environ."""

    def __init__(self, context, *args, **kwargs):
        self.context = context
        super(InjectContext, self).__init__(*args, **kwargs)

    @webob.dec.wsgify(RequestClass=base_wsgi.Request)
    def __call__(self, req):
        req.environ['cinder.context'] = self.context
        return self.application


class CinderKeystoneContext(base_wsgi.Middleware):
    """Make a request context from keystone headers."""
    ENV_OVERWRITES = {
        'X_PROJECT_DOMAIN_ID': 'project_domain_id',
        'X_PROJECT_DOMAIN_NAME': 'project_domain_name',
        'X_USER_DOMAIN_ID': 'user_domain_id',
        'X_USER_DOMAIN_NAME': 'user_domain_name',
    }

    @webob.dec.wsgify(RequestClass=base_wsgi.Request)
    def __call__(self, req):
        params = {'project_name': req.headers.get('X_TENANT_NAME')}
        for env_name, param_name in self.ENV_OVERWRITES.items():
            if req.environ.get(env_name):
                params[param_name] = req.environ[env_name]
        ctx = _set_request_context(req, **params)

        if ctx.user_id is None:
            LOG.debug("Neither X_USER_ID nor X_USER found in request")
            return webob.exc.HTTPUnauthorized()

        return self.application


class NoAuthMiddlewareBase(base_wsgi.Middleware):
    """Return a fake token if one isn't specified."""

    def base_call(self, req, project_id_in_path=False):
        if 'X-Auth-Token' not in req.headers:
            user_id = req.headers.get('X-Auth-User', 'admin')
            project_id = req.headers.get('X-Auth-Project-Id', 'admin')
            if project_id_in_path:
                os_url = os.path.join(req.url.rstrip('/'), project_id)
            else:
                os_url = req.url.rstrip('/')
            res = webob.Response()
            # NOTE(vish): This is expecting and returning Auth(1.1), whereas
            #             keystone uses 2.0 auth.  We should probably allow
            #             2.0 auth here as well.
            res.headers['X-Auth-Token'] = '%s:%s' % (user_id, project_id)
            res.headers['X-Server-Management-Url'] = os_url
            res.content_type = 'text/plain'
            res.status_int = HTTPStatus.NO_CONTENT
            return res

        token = req.headers['X-Auth-Token']
        user_id, _sep, project_id = token.partition(':')
        project_id = project_id or user_id
        _set_request_context(req, user_id=user_id, project_id=project_id,
                             is_admin=True)
        return self.application


class NoAuthMiddleware(NoAuthMiddlewareBase):
    """Return a fake token if one isn't specified.

    Sets project_id in URLs.
    """

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        return self.base_call(req)


class NoAuthMiddlewareIncludeProjectID(NoAuthMiddlewareBase):
    """Return a fake token if one isn't specified.

    Does not set project_id in URLs.
    """
    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        return self.base_call(req, project_id_in_path=True)
