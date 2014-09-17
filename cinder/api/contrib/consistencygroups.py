# Copyright (C) 2012 - 2014 EMC Corporation.
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

"""The consistencygroups api."""


import webob
from webob import exc

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.views import consistencygroups as consistencygroup_views
from cinder.api import xmlutil
from cinder import consistencygroup as consistencygroupAPI
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder import utils

LOG = logging.getLogger(__name__)


def make_consistencygroup(elem):
    elem.set('id')
    elem.set('status')
    elem.set('availability_zone')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')


class ConsistencyGroupTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('consistencygroup',
                                       selector='consistencygroup')
        make_consistencygroup(root)
        alias = Consistencygroups.alias
        namespace = Consistencygroups.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class ConsistencyGroupsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('consistencygroups')
        elem = xmlutil.SubTemplateElement(root, 'consistencygroup',
                                          selector='consistencygroups')
        make_consistencygroup(elem)
        alias = Consistencygroups.alias
        namespace = Consistencygroups.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class CreateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = utils.safe_minidom_parse_string(string)
        consistencygroup = self._extract_consistencygroup(dom)
        return {'body': {'consistencygroup': consistencygroup}}

    def _extract_consistencygroup(self, node):
        consistencygroup = {}
        consistencygroup_node = self.find_first_child_named(
            node,
            'consistencygroup')

        attributes = ['name',
                      'description']

        for attr in attributes:
            if consistencygroup_node.getAttribute(attr):
                consistencygroup[attr] = consistencygroup_node.\
                    getAttribute(attr)
        return consistencygroup


class ConsistencyGroupsController(wsgi.Controller):
    """The ConsistencyGroups API controller for the OpenStack API."""

    _view_builder_class = consistencygroup_views.ViewBuilder

    def __init__(self):
        self.consistencygroup_api = consistencygroupAPI.API()
        super(ConsistencyGroupsController, self).__init__()

    @wsgi.serializers(xml=ConsistencyGroupTemplate)
    def show(self, req, id):
        """Return data about the given consistency group."""
        LOG.debug('show called for member %s', id)
        context = req.environ['cinder.context']

        try:
            consistencygroup = self.consistencygroup_api.get(
                context,
                group_id=id)
        except exception.ConsistencyGroupNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)

        return self._view_builder.detail(req, consistencygroup)

    def delete(self, req, id, body):
        """Delete a consistency group."""
        LOG.debug('delete called for member %s', id)
        context = req.environ['cinder.context']
        force = False
        if body:
            cg_body = body['consistencygroup']
            force = cg_body.get('force', False)

        LOG.info(_('Delete consistency group with id: %s'), id,
                 context=context)

        try:
            group = self.consistencygroup_api.get(context, id)
            self.consistencygroup_api.delete(context, group, force)
        except exception.ConsistencyGroupNotFound:
            msg = _("Consistency group %s could not be found.") % id
            raise exc.HTTPNotFound(explanation=msg)
        except exception.InvalidConsistencyGroup as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        return webob.Response(status_int=202)

    @wsgi.serializers(xml=ConsistencyGroupsTemplate)
    def index(self, req):
        """Returns a summary list of consistency groups."""
        return self._get_consistencygroups(req, is_detail=False)

    @wsgi.serializers(xml=ConsistencyGroupsTemplate)
    def detail(self, req):
        """Returns a detailed list of consistency groups."""
        return self._get_consistencygroups(req, is_detail=True)

    def _get_consistencygroups(self, req, is_detail):
        """Returns a list of consistency groups through view builder."""
        context = req.environ['cinder.context']
        consistencygroups = self.consistencygroup_api.get_all(context)
        limited_list = common.limited(consistencygroups, req)

        if is_detail:
            consistencygroups = self._view_builder.detail_list(req,
                                                               limited_list)
        else:
            consistencygroups = self._view_builder.summary_list(req,
                                                                limited_list)
        return consistencygroups

    @wsgi.response(202)
    @wsgi.serializers(xml=ConsistencyGroupTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Create a new consistency group."""
        LOG.debug('Creating new consistency group %s', body)
        if not self.is_valid_body(body, 'consistencygroup'):
            raise exc.HTTPBadRequest()

        context = req.environ['cinder.context']

        try:
            consistencygroup = body['consistencygroup']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)
        name = consistencygroup.get('name', None)
        description = consistencygroup.get('description', None)
        volume_types = consistencygroup.get('volume_types', None)
        if not volume_types:
            msg = _("volume_types must be provided to create "
                    "consistency group %(name)s.") % {'name': name}
            raise exc.HTTPBadRequest(explanation=msg)
        availability_zone = consistencygroup.get('availability_zone', None)

        LOG.info(_("Creating consistency group %(name)s."),
                 {'name': name},
                 context=context)

        try:
            new_consistencygroup = self.consistencygroup_api.create(
                context, name, description, volume_types,
                availability_zone=availability_zone)
        except exception.InvalidConsistencyGroup as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        except exception.InvalidVolumeType as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        except exception.ConsistencyGroupNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)

        retval = self._view_builder.summary(
            req,
            dict(new_consistencygroup.iteritems()))
        return retval


class Consistencygroups(extensions.ExtensionDescriptor):
    """consistency groups support."""

    name = 'Consistencygroups'
    alias = 'consistencygroups'
    namespace = 'http://docs.openstack.org/volume/ext/consistencygroups/api/v1'
    updated = '2014-08-18T00:00:00+00:00'

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Consistencygroups.alias, ConsistencyGroupsController(),
            collection_actions={'detail': 'GET'},
            member_actions={'delete': 'POST'})
        resources.append(res)
        return resources
