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


from oslo.config import cfg
import webob.exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import db
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
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

        return xmlutil.MasterTemplate(root, 1)


class ServiceController(wsgi.Controller):
    @wsgi.serializers(xml=ServicesIndexTemplate)
    def index(self, req):
        """Return a list of all running services.

        Filter by host & service name.
        """
        context = req.environ['cinder.context']
        authorize(context)
        now = timeutils.utcnow()
        services = db.service_get_all(context)

        host = ''
        if 'host' in req.GET:
            host = req.GET['host']
        service = ''
        if 'service' in req.GET:
            service = req.GET['service']
            LOG.deprecated(_("Query by service parameter is deprecated. "
                             "Please use binary parameter instead."))
        binary = ''
        if 'binary' in req.GET:
            binary = req.GET['binary']

        if host:
            services = [s for s in services if s['host'] == host]
        # NOTE(uni): deprecating service request key, binary takes precedence
        binary_key = binary or service
        if binary_key:
            services = [s for s in services if s['binary'] == binary_key]

        svcs = []
        for svc in services:
            delta = now - (svc['updated_at'] or svc['created_at'])
            alive = abs(utils.total_seconds(delta)) <= CONF.service_down_time
            art = (alive and "up") or "down"
            active = 'enabled'
            if svc['disabled']:
                active = 'disabled'
            svcs.append({"binary": svc['binary'], 'host': svc['host'],
                         'zone': svc['availability_zone'],
                         'status': active, 'state': art,
                         'updated_at': svc['updated_at']})
        return {'services': svcs}

    @wsgi.serializers(xml=ServicesUpdateTemplate)
    def update(self, req, id, body):
        """Enable/Disable scheduling for a service."""
        context = req.environ['cinder.context']
        authorize(context)

        if id == "enable":
            disabled = False
        elif id == "disable":
            disabled = True
        else:
            raise webob.exc.HTTPNotFound("Unknown action")

        try:
            host = body['host']
        except (TypeError, KeyError):
            raise webob.exc.HTTPBadRequest()

        # NOTE(uni): deprecating service request key, binary takes precedence
        # Still keeping service key here for API compatibility sake.
        service = body.get('service', '')
        binary = body.get('binary', '')
        binary_key = binary or service
        if not binary_key:
            raise webob.exc.HTTPBadRequest()

        try:
            svc = db.service_get_by_args(context, host, binary_key)
            if not svc:
                raise webob.exc.HTTPNotFound('Unknown service')

            db.service_update(context, svc['id'], {'disabled': disabled})
        except exception.ServiceNotFound:
            raise webob.exc.HTTPNotFound("service not found")

        status = id + 'd'
        return {'host': host,
                'service': service,
                'disabled': disabled,
                'binary': binary,
                'status': status}


class Services(extensions.ExtensionDescriptor):
    """Services support."""

    name = "Services"
    alias = "os-services"
    namespace = "http://docs.openstack.org/volume/ext/services/api/v2"
    updated = "2012-10-28T00:00:00-00:00"

    def get_resources(self):
        resources = []
        resource = extensions.ResourceExtension('os-services',
                                                ServiceController())
        resources.append(resource)
        return resources
