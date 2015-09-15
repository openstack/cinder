# Copyright (c) 2011 OpenStack Foundation
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

"""The hosts admin extension."""

from xml.parsers import expat

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
import webob.exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import db
from cinder import exception
from cinder.i18n import _, _LI
from cinder import objects
from cinder import utils
from cinder.volume import api as volume_api


CONF = cfg.CONF

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('volume', 'hosts')


class HostIndexTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('hosts')
        elem = xmlutil.SubTemplateElement(root, 'host', selector='hosts')
        elem.set('service-status')
        elem.set('service')
        elem.set('zone')
        elem.set('service-state')
        elem.set('host_name')
        elem.set('last-update')

        return xmlutil.MasterTemplate(root, 1)


class HostUpdateTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('host')
        root.set('host')
        root.set('status')

        return xmlutil.MasterTemplate(root, 1)


class HostActionTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('host')
        root.set('host')

        return xmlutil.MasterTemplate(root, 1)


class HostShowTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('host')
        elem = xmlutil.make_flat_dict('resource', selector='host',
                                      subselector='resource')
        root.append(elem)

        return xmlutil.MasterTemplate(root, 1)


class HostDeserializer(wsgi.XMLDeserializer):
    def default(self, string):
        try:
            node = utils.safe_minidom_parse_string(string)
        except expat.ExpatError:
            msg = _("cannot understand XML")
            raise exception.MalformedRequestBody(reason=msg)

        updates = {}
        for child in node.childNodes[0].childNodes:
            updates[child.tagName] = self.extract_text(child)

        return dict(body=updates)


def _list_hosts(req, service=None):
    """Returns a summary list of hosts."""
    curr_time = timeutils.utcnow(with_timezone=True)
    context = req.environ['cinder.context']
    services = objects.ServiceList.get_all(context, False)
    zone = ''
    if 'zone' in req.GET:
        zone = req.GET['zone']
    if zone:
        services = [s for s in services if s['availability_zone'] == zone]
    hosts = []
    for host in services:
        delta = curr_time - (host.updated_at or host.created_at)
        alive = abs(delta.total_seconds()) <= CONF.service_down_time
        status = (alive and "available") or "unavailable"
        active = 'enabled'
        if host.disabled:
            active = 'disabled'
        LOG.debug('status, active and update: %s, %s, %s',
                  status, active, host.updated_at)
        updated_at = host.updated_at
        if updated_at:
            updated_at = timeutils.normalize_time(updated_at)
        hosts.append({'host_name': host.host,
                      'service': host.topic,
                      'zone': host.availability_zone,
                      'service-status': status,
                      'service-state': active,
                      'last-update': updated_at,
                      })
    if service:
        hosts = [host for host in hosts
                 if host['service'] == service]
    return hosts


def check_host(fn):
    """Makes sure that the host exists."""
    def wrapped(self, req, id, service=None, *args, **kwargs):
        listed_hosts = _list_hosts(req, service)
        hosts = [h["host_name"] for h in listed_hosts]
        if id in hosts:
            return fn(self, req, id, *args, **kwargs)
        else:
            message = _("Host '%s' could not be found.") % id
            raise webob.exc.HTTPNotFound(explanation=message)
    return wrapped


class HostController(wsgi.Controller):
    """The Hosts API controller for the OpenStack API."""
    def __init__(self):
        self.api = volume_api.HostAPI()
        super(HostController, self).__init__()

    @wsgi.serializers(xml=HostIndexTemplate)
    def index(self, req):
        authorize(req.environ['cinder.context'])
        return {'hosts': _list_hosts(req)}

    @wsgi.serializers(xml=HostUpdateTemplate)
    @wsgi.deserializers(xml=HostDeserializer)
    @check_host
    def update(self, req, id, body):
        authorize(req.environ['cinder.context'])
        update_values = {}
        for raw_key, raw_val in body.items():
            key = raw_key.lower().strip()
            val = raw_val.lower().strip()
            if key == "status":
                if val in ("enable", "disable"):
                    update_values['status'] = val.startswith("enable")
                else:
                    explanation = _("Invalid status: '%s'") % raw_val
                    raise webob.exc.HTTPBadRequest(explanation=explanation)
            else:
                explanation = _("Invalid update setting: '%s'") % raw_key
                raise webob.exc.HTTPBadRequest(explanation=explanation)
        update_setters = {'status': self._set_enabled_status}
        result = {}
        for key, value in update_values.items():
            result.update(update_setters[key](req, id, value))
        return result

    def _set_enabled_status(self, req, host, enabled):
        """Sets the specified host's ability to accept new volumes."""
        context = req.environ['cinder.context']
        state = "enabled" if enabled else "disabled"
        LOG.info(_LI("Setting host %(host)s to %(state)s."),
                 {'host': host, 'state': state})
        result = self.api.set_host_enabled(context,
                                           host=host,
                                           enabled=enabled)
        if result not in ("enabled", "disabled"):
            # An error message was returned
            raise webob.exc.HTTPBadRequest(explanation=result)
        return {"host": host, "status": result}

    @wsgi.serializers(xml=HostShowTemplate)
    def show(self, req, id):
        """Shows the volume usage info given by hosts.

        :param context: security context
        :param host: hostname
        :returns: expected to use HostShowTemplate.
            ex.::

                {'host': {'resource':D},..}
                D: {'host': 'hostname','project': 'admin',
                    'volume_count': 1, 'total_volume_gb': 2048}
        """
        host = id
        context = req.environ['cinder.context']
        if not context.is_admin:
            msg = _("Describe-resource is admin only functionality")
            raise webob.exc.HTTPForbidden(explanation=msg)

        try:
            host_ref = objects.Service.get_by_host_and_topic(
                context, host, CONF.volume_topic)
        except exception.ServiceNotFound:
            raise webob.exc.HTTPNotFound(explanation=_("Host not found"))

        # Getting total available/used resource
        # TODO(jdg): Add summary info for Snapshots
        volume_refs = db.volume_get_all_by_host(context, host_ref.host)
        (count, sum) = db.volume_data_get_for_host(context,
                                                   host_ref.host)

        snap_count_total = 0
        snap_sum_total = 0
        resources = [{'resource': {'host': host, 'project': '(total)',
                                   'volume_count': str(count),
                                   'total_volume_gb': str(sum),
                                   'snapshot_count': str(snap_count_total),
                                   'total_snapshot_gb': str(snap_sum_total)}}]

        project_ids = [v['project_id'] for v in volume_refs]
        project_ids = list(set(project_ids))
        for project_id in project_ids:
            (count, sum) = db.volume_data_get_for_project(context, project_id)
            (snap_count, snap_sum) = (
                objects.Snapshot.snapshot_data_get_for_project(context,
                                                               project_id))
            resources.append(
                {'resource':
                    {'host': host,
                     'project': project_id,
                     'volume_count': str(count),
                     'total_volume_gb': str(sum),
                     'snapshot_count': str(snap_count),
                     'total_snapshot_gb': str(snap_sum)}})
            snap_count_total += int(snap_count)
            snap_sum_total += int(snap_sum)
        resources[0]['resource']['snapshot_count'] = str(snap_count_total)
        resources[0]['resource']['total_snapshot_gb'] = str(snap_sum_total)
        return {"host": resources}


class Hosts(extensions.ExtensionDescriptor):
    """Admin-only host administration."""

    name = "Hosts"
    alias = "os-hosts"
    namespace = "http://docs.openstack.org/volume/ext/hosts/api/v1.1"
    updated = "2011-06-29T00:00:00+00:00"

    def get_resources(self):
        resources = [extensions.ResourceExtension('os-hosts',
                                                  HostController(),
                                                  collection_actions={
                                                      'update': 'PUT'},
                                                  member_actions={
                                                      'startup': 'GET',
                                                      'shutdown': 'GET',
                                                      'reboot': 'GET'})]
        return resources
