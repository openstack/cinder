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
from cinder.api import xmlutil
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import utils


CONF = cfg.CONF

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('volume', 'services')


class ServicesIndexTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('services')
        elem = xmlutil.SubTemplateElement(root, 'service', selector='services')
        elem.set('binary')
        elem.set('host')
        elem.set('zone')
        elem.set('status')
        elem.set('state')
        elem.set('update_at')
        elem.set('disabled_reason')

        return xmlutil.MasterTemplate(root, 1)


class ServicesUpdateTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        # TODO(uni): template elements of 'host', 'service' and 'disabled'
        # should be deprecated to make ServicesUpdateTemplate consistent
        # with ServicesIndexTemplate. Still keeping it here for API
        # compatibility sake.
        root = xmlutil.TemplateElement('host')
        root.set('host')
        root.set('service')
        root.set('disabled')
        root.set('binary')
        root.set('status')
        root.set('disabled_reason')

        return xmlutil.MasterTemplate(root, 1)


class ServiceController(wsgi.Controller):
    def __init__(self, ext_mgr=None):
        self.ext_mgr = ext_mgr
        super(ServiceController, self).__init__()

    @wsgi.serializers(xml=ServicesIndexTemplate)
    def index(self, req):
        """Return a list of all running services.

        Filter by host & service name.
        """
        context = req.environ['cinder.context']
        authorize(context, action='index')
        detailed = self.ext_mgr.is_loaded('os-extended-services')
        now = timeutils.utcnow(with_timezone=True)
        services = objects.ServiceList.get_all(context)

        host = ''
        if 'host' in req.GET:
            host = req.GET['host']
        service = ''
        if 'service' in req.GET:
            service = req.GET['service']
            versionutils.report_deprecated_feature(LOG, _(
                "Query by service parameter is deprecated. "
                "Please use binary parameter instead."))
        binary = ''
        if 'binary' in req.GET:
            binary = req.GET['binary']

        if host:
            services = [s for s in services if s.host == host]
        # NOTE(uni): deprecating service request key, binary takes precedence
        binary_key = binary or service
        if binary_key:
            services = [s for s in services if s.binary == binary_key]

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
            if detailed:
                ret_fields['disabled_reason'] = svc.disabled_reason
            svcs.append(ret_fields)
        return {'services': svcs}

    def _is_valid_as_reason(self, reason):
        if not reason:
            return False
        try:
            utils.check_string_length(reason.strip(), 'Disabled reason',
                                      min_length=1, max_length=255)
        except exception.InvalidInput:
            return False

        return True

    @wsgi.serializers(xml=ServicesUpdateTemplate)
    def update(self, req, id, body):
        """Enable/Disable scheduling for a service."""
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
        else:
            raise webob.exc.HTTPNotFound(explanation=_("Unknown action"))

        try:
            host = body['host']
        except (TypeError, KeyError):
            msg = _("Missing required element 'host' in request body.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

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

        try:
            svc = objects.Service.get_by_args(context, host, binary_key)
            if not svc:
                raise webob.exc.HTTPNotFound(explanation=_('Unknown service'))

            svc.disabled = ret_val['disabled']
            if 'disabled_reason' in ret_val:
                svc.disabled_reason = ret_val['disabled_reason']
            svc.save()
        except exception.ServiceNotFound:
            raise webob.exc.HTTPNotFound(explanation=_("service not found"))

        ret_val.update({'host': host, 'service': service,
                        'binary': binary, 'status': status})
        return ret_val


class Services(extensions.ExtensionDescriptor):
    """Services support."""

    name = "Services"
    alias = "os-services"
    namespace = "http://docs.openstack.org/volume/ext/services/api/v2"
    updated = "2012-10-28T00:00:00-00:00"

    def get_resources(self):
        resources = []
        controller = ServiceController(self.ext_mgr)
        resource = extensions.ResourceExtension('os-services', controller)
        resources.append(resource)
        return resources
