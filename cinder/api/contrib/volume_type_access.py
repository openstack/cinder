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

import six
from six.moves import http_client
import webob

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.schemas import volume_type_access
from cinder.api import validation
from cinder import exception
from cinder.i18n import _
from cinder.policies import volume_access as policy
from cinder.volume import volume_types


def _marshall_volume_type_access(vol_type):
    rval = []
    for project_id in vol_type['projects']:
        rval.append({'volume_type_id': vol_type['id'],
                     'project_id': project_id})

    return {'volume_type_access': rval}


class VolumeTypeAccessController(object):
    """The volume type access API controller for the OpenStack API."""

    def index(self, req, type_id):
        context = req.environ['cinder.context']
        context.authorize(policy.TYPE_ACCESS_POLICY)

        # Not found exception will be handled at the wsgi level
        vol_type = volume_types.get_volume_type(
            context, type_id, expected_fields=['projects'])

        if vol_type['is_public']:
            expl = _("Access list not available for public volume types.")
            raise exception.VolumeTypeAccessNotFound(message=expl)

        return _marshall_volume_type_access(vol_type)


class VolumeTypeActionController(wsgi.Controller):
    """The volume type access API controller for the OpenStack API."""

    def _extend_vol_type(self, vol_type_rval, vol_type_ref):
        if vol_type_ref:
            key = "%s:is_public" % (Volume_type_access.alias)
            vol_type_rval[key] = vol_type_ref.get('is_public', True)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if context.authorize(policy.TYPE_ACCESS_POLICY, fatal=False):
            vol_type = req.cached_resource_by_id(id, name='types')
            self._extend_vol_type(resp_obj.obj['volume_type'], vol_type)

    @wsgi.extends
    def index(self, req, resp_obj):
        context = req.environ['cinder.context']
        if context.authorize(policy.TYPE_ACCESS_POLICY, fatal=False):
            for vol_type_rval in list(resp_obj.obj['volume_types']):
                type_id = vol_type_rval['id']
                vol_type = req.cached_resource_by_id(type_id, name='types')
                self._extend_vol_type(vol_type_rval, vol_type)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if context.authorize(policy.TYPE_ACCESS_POLICY, fatal=False):
            for vol_type_rval in list(resp_obj.obj['volume_types']):
                type_id = vol_type_rval['id']
                vol_type = req.cached_resource_by_id(type_id, name='types')
                self._extend_vol_type(vol_type_rval, vol_type)

    @wsgi.extends(action='create')
    def create(self, req, body, resp_obj):
        context = req.environ['cinder.context']
        if context.authorize(policy.TYPE_ACCESS_POLICY, fatal=False):
            type_id = resp_obj.obj['volume_type']['id']
            vol_type = req.cached_resource_by_id(type_id, name='types')
            self._extend_vol_type(resp_obj.obj['volume_type'], vol_type)

    @wsgi.action('addProjectAccess')
    @validation.schema(volume_type_access.add_project_access)
    def _addProjectAccess(self, req, id, body):
        context = req.environ['cinder.context']
        context.authorize(policy.ADD_PROJECT_POLICY)
        project = body['addProjectAccess']['project']

        try:
            volume_types.add_volume_type_access(context, id, project)
        # Not found exception will be handled at the wsgi level
        except exception.VolumeTypeAccessExists as err:
            raise webob.exc.HTTPConflict(explanation=six.text_type(err))
        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.action('removeProjectAccess')
    @validation.schema(volume_type_access.remove_project_access)
    def _removeProjectAccess(self, req, id, body):
        context = req.environ['cinder.context']
        context.authorize(policy.REMOVE_PROJECT_POLICY)
        project = body['removeProjectAccess']['project']

        # Not found exception will be handled at the wsgi level
        volume_types.remove_volume_type_access(context, id, project)
        return webob.Response(status_int=http_client.ACCEPTED)


class Volume_type_access(extensions.ExtensionDescriptor):
    """Volume type access support."""

    name = "VolumeTypeAccess"
    alias = "os-volume-type-access"
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
