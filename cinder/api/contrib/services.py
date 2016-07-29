# Copyright 2012 IBM Corp.
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


from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import timeutils
import webob.exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import utils
from cinder import volume


CONF = cfg.CONF

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('volume', 'services')


class ServiceController(wsgi.Controller):
    def __init__(self, ext_mgr=None):
        self.ext_mgr = ext_mgr
        super(ServiceController, self).__init__()
        self.volume_api = volume.API()

    def index(self, req):
        """Return a list of all running services.

        Filter by host & service name.
        """
        context = req.environ['cinder.context']
        authorize(context, action='index')
        detailed = self.ext_mgr.is_loaded('os-extended-services')
        now = timeutils.utcnow(with_timezone=True)

        filters = {}

        if 'host' in req.GET:
            filters['host'] = req.GET['host']
        if 'binary' in req.GET:
            filters['binary'] = req.GET['binary']
        elif 'service' in req.GET:
            filters['binary'] = req.GET['service']
            versionutils.report_deprecated_feature(LOG, _(
                "Query by service parameter is deprecated. "
                "Please use binary parameter instead."))

        services = objects.ServiceList.get_all(context, filters)

        svcs = []
        for svc in services:
            updated_at = svc.updated_at
            delta = now - (svc.updated_at or svc.created_at)
            delta_sec = delta.total_seconds()
            if svc.modified_at:
                delta_mod = now - svc.modified_at
                if abs(delta_sec) >= abs(delta_mod.total_seconds()):
                    updated_at = svc.modified_at
            alive = abs(delta_sec) <= CONF.service_down_time
            art = (alive and "up") or "down"
            active = 'enabled'
            if svc.disabled:
                active = 'disabled'
            if updated_at:
                updated_at = timeutils.normalize_time(updated_at)
            ret_fields = {'binary': svc.binary, 'host': svc.host,
                          'zone': svc.availability_zone,
                          'status': active, 'state': art,
                          'updated_at': updated_at}

            # On V3.7 we added cluster support
            if req.api_version_request.matches('3.7'):
                ret_fields['cluster'] = svc.cluster_name

            if detailed:
                ret_fields['disabled_reason'] = svc.disabled_reason
                if svc.binary == "cinder-volume":
                    ret_fields['replication_status'] = svc.replication_status
                    ret_fields['active_backend_id'] = svc.active_backend_id
                    ret_fields['frozen'] = svc.frozen
            svcs.append(ret_fields)
        return {'services': svcs}

    def _is_valid_as_reason(self, reason):
        if not reason:
            return False
        try:
            utils.check_string_length(reason, 'Disabled reason', min_length=1,
                                      max_length=255, allow_all_spaces=False)
        except exception.InvalidInput:
            return False

        return True

    def _freeze(self, context, host):
        return self.volume_api.freeze_host(context, host)

    def _thaw(self, context, host):
        return self.volume_api.thaw_host(context, host)

    def _failover(self, context, host, backend_id=None):
        return self.volume_api.failover_host(context, host, backend_id)

    def update(self, req, id, body):
        """Enable/Disable scheduling for a service.

        Includes Freeze/Thaw which sends call down to drivers
        and allows volume.manager for the specified host to
        disable the service rather than accessing the service
        directly in this API layer.
        """
        context = req.environ['cinder.context']
        authorize(context, action='update')

        ext_loaded = self.ext_mgr.is_loaded('os-extended-services')
        ret_val = {}
        if id == "enable":
            disabled = False
            status = "enabled"
            if ext_loaded:
                ret_val['disabled_reason'] = None
        elif (id == "disable" or
                (id == "disable-log-reason" and ext_loaded)):
            disabled = True
            status = "disabled"
        elif id == "freeze":
            return self._freeze(context, body['host'])
        elif id == "thaw":
            return self._thaw(context, body['host'])
        elif id == "failover_host":
            self._failover(
                context,
                body['host'],
                body.get('backend_id', None)
            )
            return webob.Response(status_int=202)
        else:
            raise exception.InvalidInput(reason=_("Unknown action"))

        try:
            host = body['host']
        except (TypeError, KeyError):
            raise exception.MissingRequired(element='host')

        ret_val['disabled'] = disabled
        if id == "disable-log-reason" and ext_loaded:
            reason = body.get('disabled_reason')
            if not self._is_valid_as_reason(reason):
                msg = _('Disabled reason contains invalid characters '
                        'or is too long')
                raise webob.exc.HTTPBadRequest(explanation=msg)
            ret_val['disabled_reason'] = reason

        # NOTE(uni): deprecating service request key, binary takes precedence
        # Still keeping service key here for API compatibility sake.
        service = body.get('service', '')
        binary = body.get('binary', '')
        binary_key = binary or service
        if not binary_key:
            raise webob.exc.HTTPBadRequest()

        # Not found exception will be handled at the wsgi level
        svc = objects.Service.get_by_args(context, host, binary_key)

        svc.disabled = ret_val['disabled']
        if 'disabled_reason' in ret_val:
            svc.disabled_reason = ret_val['disabled_reason']
        svc.save()

        ret_val.update({'host': host, 'service': service,
                        'binary': binary, 'status': status})
        return ret_val


class Services(extensions.ExtensionDescriptor):
    """Services support."""

    name = "Services"
    alias = "os-services"
    updated = "2012-10-28T00:00:00-00:00"

    def get_resources(self):
        resources = []
        controller = ServiceController(self.ext_mgr)
        resource = extensions.ResourceExtension('os-services', controller)
        resources.append(resource)
        return resources
