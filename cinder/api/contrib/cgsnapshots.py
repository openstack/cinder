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

"""The cgsnapshots api."""


import webob
from webob import exc

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.views import cgsnapshots as cgsnapshot_views
from cinder.api import xmlutil
from cinder import consistencygroup as consistencygroupAPI
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder import utils

LOG = logging.getLogger(__name__)


def make_cgsnapshot(elem):
    elem.set('id')
    elem.set('consistencygroup_id')
    elem.set('status')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')


class CgsnapshotTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('cgsnapshot', selector='cgsnapshot')
        make_cgsnapshot(root)
        alias = Cgsnapshots.alias
        namespace = Cgsnapshots.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class CgsnapshotsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('cgsnapshots')
        elem = xmlutil.SubTemplateElement(root, 'cgsnapshot',
                                          selector='cgsnapshots')
        make_cgsnapshot(elem)
        alias = Cgsnapshots.alias
        namespace = Cgsnapshots.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class CreateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = utils.safe_minidom_parse_string(string)
        cgsnapshot = self._extract_cgsnapshot(dom)
        return {'body': {'cgsnapshot': cgsnapshot}}

    def _extract_cgsnapshot(self, node):
        cgsnapshot = {}
        cgsnapshot_node = self.find_first_child_named(node, 'cgsnapshot')

        attributes = ['name',
                      'description']

        for attr in attributes:
            if cgsnapshot_node.getAttribute(attr):
                cgsnapshot[attr] = cgsnapshot_node.getAttribute(attr)
        return cgsnapshot


class CgsnapshotsController(wsgi.Controller):
    """The cgsnapshots API controller for the OpenStack API."""

    _view_builder_class = cgsnapshot_views.ViewBuilder

    def __init__(self):
        self.cgsnapshot_api = consistencygroupAPI.API()
        super(CgsnapshotsController, self).__init__()

    @wsgi.serializers(xml=CgsnapshotTemplate)
    def show(self, req, id):
        """Return data about the given cgsnapshot."""
        LOG.debug('show called for member %s', id)
        context = req.environ['cinder.context']

        try:
            cgsnapshot = self.cgsnapshot_api.get_cgsnapshot(
                context,
                cgsnapshot_id=id)
        except exception.CgSnapshotNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)

        return self._view_builder.detail(req, cgsnapshot)

    def delete(self, req, id):
        """Delete a cgsnapshot."""
        LOG.debug('delete called for member %s', id)
        context = req.environ['cinder.context']

        LOG.info(_('Delete cgsnapshot with id: %s'), id, context=context)

        try:
            cgsnapshot = self.cgsnapshot_api.get_cgsnapshot(
                context,
                cgsnapshot_id=id)
            self.cgsnapshot_api.delete_cgsnapshot(context, cgsnapshot)
        except exception.CgSnapshotNotFound:
            msg = _("Cgsnapshot could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        except exception.InvalidCgSnapshot:
            msg = _("Invalid cgsnapshot")
            raise exc.HTTPBadRequest(explanation=msg)
        except Exception:
            msg = _("Failed cgsnapshot")
            raise exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=202)

    @wsgi.serializers(xml=CgsnapshotsTemplate)
    def index(self, req):
        """Returns a summary list of cgsnapshots."""
        return self._get_cgsnapshots(req, is_detail=False)

    @wsgi.serializers(xml=CgsnapshotsTemplate)
    def detail(self, req):
        """Returns a detailed list of cgsnapshots."""
        return self._get_cgsnapshots(req, is_detail=True)

    def _get_cgsnapshots(self, req, is_detail):
        """Returns a list of cgsnapshots, transformed through view builder."""
        context = req.environ['cinder.context']
        cgsnapshots = self.cgsnapshot_api.get_all_cgsnapshots(context)
        limited_list = common.limited(cgsnapshots, req)

        if is_detail:
            cgsnapshots = self._view_builder.detail_list(req, limited_list)
        else:
            cgsnapshots = self._view_builder.summary_list(req, limited_list)
        return cgsnapshots

    @wsgi.response(202)
    @wsgi.serializers(xml=CgsnapshotTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Create a new cgsnapshot."""
        LOG.debug('Creating new cgsnapshot %s', body)
        if not self.is_valid_body(body, 'cgsnapshot'):
            raise exc.HTTPBadRequest()

        context = req.environ['cinder.context']

        try:
            cgsnapshot = body['cgsnapshot']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            group_id = cgsnapshot['consistencygroup_id']
        except KeyError:
            msg = _("'consistencygroup_id' must be specified")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            group = self.cgsnapshot_api.get(context, group_id)
        except exception.NotFound:
            msg = _("Consistency group could not be found")
            raise exc.HTTPNotFound(explanation=msg)

        name = cgsnapshot.get('name', None)
        description = cgsnapshot.get('description', None)

        LOG.info(_("Creating cgsnapshot %(name)s."),
                 {'name': name},
                 context=context)

        try:
            new_cgsnapshot = self.cgsnapshot_api.create_cgsnapshot(
                context, group, name, description)
        except exception.InvalidCgSnapshot as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        except exception.CgSnapshotNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)

        retval = self._view_builder.summary(
            req,
            dict(new_cgsnapshot.iteritems()))

        return retval


class Cgsnapshots(extensions.ExtensionDescriptor):
    """cgsnapshots support."""

    name = 'Cgsnapshots'
    alias = 'cgsnapshots'
    namespace = 'http://docs.openstack.org/volume/ext/cgsnapshots/api/v1'
    updated = '2014-08-18T00:00:00+00:00'

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Cgsnapshots.alias, CgsnapshotsController(),
            collection_actions={'detail': 'GET'})
        resources.append(res)
        return resources
