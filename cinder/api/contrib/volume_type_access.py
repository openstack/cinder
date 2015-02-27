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

"""The volume type access extension."""

from oslo_utils import uuidutils
import six
import webob

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import exception
from cinder.i18n import _
from cinder.volume import volume_types


soft_authorize = extensions.soft_extension_authorizer('volume',
                                                      'volume_type_access')
authorize = extensions.extension_authorizer('volume', 'volume_type_access')


def make_volume_type(elem):
    elem.set('{%s}is_public' % Volume_type_access.namespace,
             '%s:is_public' % Volume_type_access.alias)


def make_volume_type_access(elem):
    elem.set('volume_type_id')
    elem.set('project_id')


class VolumeTypeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_type', selector='volume_type')
        make_volume_type(root)
        alias = Volume_type_access.alias
        namespace = Volume_type_access.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class VolumeTypesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_types')
        elem = xmlutil.SubTemplateElement(
            root, 'volume_type', selector='volume_types')
        make_volume_type(elem)
        alias = Volume_type_access.alias
        namespace = Volume_type_access.namespace
        return xmlutil.SlaveTemplate(root, 1, nsmap={alias: namespace})


class VolumeTypeAccessTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_type_access')
        elem = xmlutil.SubTemplateElement(root, 'access',
                                          selector='volume_type_access')
        make_volume_type_access(elem)
        return xmlutil.MasterTemplate(root, 1)


def _marshall_volume_type_access(vol_type):
    rval = []
    for project_id in vol_type['projects']:
        rval.append({'volume_type_id': vol_type['id'],
                     'project_id': project_id})

    return {'volume_type_access': rval}


class VolumeTypeAccessController(object):
    """The volume type access API controller for the OpenStack API."""

    def __init__(self):
        super(VolumeTypeAccessController, self).__init__()

    @wsgi.serializers(xml=VolumeTypeAccessTemplate)
    def index(self, req, type_id):
        context = req.environ['cinder.context']
        authorize(context)

        try:
            vol_type = volume_types.get_volume_type(
                context, type_id, expected_fields=['projects'])
        except exception.VolumeTypeNotFound:
            explanation = _("Volume type not found.")
            raise webob.exc.HTTPNotFound(explanation=explanation)

        if vol_type['is_public']:
            expl = _("Access list not available for public volume types.")
            raise webob.exc.HTTPNotFound(explanation=expl)

        return _marshall_volume_type_access(vol_type)


class VolumeTypeActionController(wsgi.Controller):
    """The volume type access API controller for the OpenStack API."""

    def _check_body(self, body, action_name):
        if not self.is_valid_body(body, action_name):
            raise webob.exc.HTTPBadRequest()
        access = body[action_name]
        project = access.get('project')
        if not uuidutils.is_uuid_like(project):
            msg = _("Bad project format: "
                    "project is not in proper format (%s)") % project
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _extend_vol_type(self, vol_type_rval, vol_type_ref):
        if vol_type_ref:
            key = "%s:is_public" % (Volume_type_access.alias)
            vol_type_rval[key] = vol_type_ref.get('is_public', True)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if soft_authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=VolumeTypeTemplate())
            vol_type = req.cached_resource_by_id(id, name='types')
            self._extend_vol_type(resp_obj.obj['volume_type'], vol_type)

    @wsgi.extends
    def index(self, req, resp_obj):
        context = req.environ['cinder.context']
        if soft_authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=VolumeTypesTemplate())
            for vol_type_rval in list(resp_obj.obj['volume_types']):
                type_id = vol_type_rval['id']
                vol_type = req.cached_resource_by_id(type_id, name='types')
                self._extend_vol_type(vol_type_rval, vol_type)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if soft_authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=VolumeTypesTemplate())
            for vol_type_rval in list(resp_obj.obj['volume_types']):
                type_id = vol_type_rval['id']
                vol_type = req.cached_resource_by_id(type_id, name='types')
                self._extend_vol_type(vol_type_rval, vol_type)

    @wsgi.extends(action='create')
    def create(self, req, body, resp_obj):
        context = req.environ['cinder.context']
        if soft_authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=VolumeTypeTemplate())
            type_id = resp_obj.obj['volume_type']['id']
            vol_type = req.cached_resource_by_id(type_id, name='types')
            self._extend_vol_type(resp_obj.obj['volume_type'], vol_type)

    @wsgi.action('addProjectAccess')
    def _addProjectAccess(self, req, id, body):
        context = req.environ['cinder.context']
        authorize(context, action="addProjectAccess")
        self._check_body(body, 'addProjectAccess')
        project = body['addProjectAccess']['project']

        try:
            volume_types.add_volume_type_access(context, id, project)
        except exception.VolumeTypeAccessExists as err:
            raise webob.exc.HTTPConflict(explanation=six.text_type(err))
        except exception.VolumeTypeNotFound as err:
            raise webob.exc.HTTPNotFound(explanation=six.text_type(err))
        return webob.Response(status_int=202)

    @wsgi.action('removeProjectAccess')
    def _removeProjectAccess(self, req, id, body):
        context = req.environ['cinder.context']
        authorize(context, action="removeProjectAccess")
        self._check_body(body, 'removeProjectAccess')
        project = body['removeProjectAccess']['project']

        try:
            volume_types.remove_volume_type_access(context, id, project)
        except (exception.VolumeTypeNotFound,
                exception.VolumeTypeAccessNotFound) as err:
            raise webob.exc.HTTPNotFound(explanation=six.text_type(err))
        return webob.Response(status_int=202)


class Volume_type_access(extensions.ExtensionDescriptor):
    """Volume type access support."""

    name = "VolumeTypeAccess"
    alias = "os-volume-type-access"
    namespace = ("http://docs.openstack.org/volume/"
                 "ext/os-volume-type-access/api/v1")
    updated = "2014-06-26T00:00:00Z"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Volume_type_access.alias,
            VolumeTypeAccessController(),
            parent=dict(member_name='type', collection_name='types'))
        resources.append(res)
        return resources

    def get_controller_extensions(self):
        controller = VolumeTypeActionController()
        extension = extensions.ControllerExtension(self, 'types', controller)
        return [extension]
