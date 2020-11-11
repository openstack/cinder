# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
from http import HTTPStatus

from oslo_log import log as logging
import webob.dec
import webob.exc

from cinder.api import api_utils
from cinder.api.openstack import wsgi
from cinder import exception
from cinder.i18n import _
from cinder.wsgi import common as base_wsgi


LOG = logging.getLogger(__name__)


class FaultWrapper(base_wsgi.Middleware):
    """Calls down the middleware stack, making exceptions into faults."""

    _status_to_type = {}

    @staticmethod
    def status_to_type(status):
        if not FaultWrapper._status_to_type:
            for clazz in api_utils.walk_class_hierarchy(webob.exc.HTTPError):
                FaultWrapper._status_to_type[clazz.code] = clazz
        return FaultWrapper._status_to_type.get(
            status, webob.exc.HTTPInternalServerError)()

    def _error(self, inner, req):
        if isinstance(inner, UnicodeDecodeError):
            msg = _("Error decoding your request. Either the URL or the "
                    "request body contained characters that could not be "
                    "decoded by Cinder.")
            return wsgi.Fault(webob.exc.HTTPBadRequest(explanation=msg))
        if not isinstance(inner, exception.QuotaError):
            LOG.exception("Caught error: %(type)s %(error)s",
                          {'type': type(inner),
                           'error': inner})
        safe = getattr(inner, 'safe', False)
        headers = getattr(inner, 'headers', None)
        status = getattr(inner, 'code', HTTPStatus.INTERNAL_SERVER_ERROR)
        if status is None:
            status = HTTPStatus.INTERNAL_SERVER_ERROR

        msg_dict = dict(url=req.url, status=status)
        LOG.info("%(url)s returned with HTTP %(status)s", msg_dict)
        outer = self.status_to_type(status)
        if headers:
            outer.headers = headers
        # NOTE(johannes): We leave the explanation empty here on
        # purpose. It could possibly have sensitive information
        # that should not be returned back to the user. See
        # bugs 868360 and 874472
        # NOTE(eglynn): However, it would be over-conservative and
        # inconsistent with the EC2 API to hide every exception,
        # including those that are safe to expose, see bug 1021373
        if safe:
            msg = (inner.msg if isinstance(inner, exception.CinderException)
                   else str(inner))
            params = {'exception': inner.__class__.__name__,
                      'explanation': msg}
            outer.explanation = _('%(exception)s: %(explanation)s') % params
        return wsgi.Fault(outer)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        try:
            return req.get_response(self.application)
        except Exception as ex:
            return self._error(ex, req)
