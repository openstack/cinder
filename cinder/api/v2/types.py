# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack Foundation
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

"""The volume type & volume types extra specs extension."""

from oslo_utils import strutils
from webob import exc

from cinder.api.openstack import wsgi
from cinder.api.v2.views import types as views_types
from cinder.api import xmlutil
from cinder import context as ctx
from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder.volume import volume_types

import cinder.policy


def make_voltype(elem):
    elem.set('id')
    elem.set('name')
    elem.set('description')
    elem.set('qos_specs_id')
    extra_specs = xmlutil.make_flat_dict('extra_specs', selector='extra_specs')
    elem.append(extra_specs)


class VolumeTypeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_type', selector='volume_type')
        make_voltype(root)
        return xmlutil.MasterTemplate(root, 1)


class VolumeTypesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume_types')
        elem = xmlutil.SubTemplateElement(root, 'volume_type',
                                          selector='volume_types')
        make_voltype(elem)
        return xmlutil.MasterTemplate(root, 1)


class VolumeTypesController(wsgi.Controller):
    """The volume types API controller for the OpenStack API."""

    _view_builder_class = views_types.ViewBuilder

    def _validate_policy(self, context):
        target = {
            'project_id': context.project_id,
            'user_id': context.user_id,
        }
        try:
            action = 'volume_extension:access_types_extra_specs'
            cinder.policy.enforce(context, action, target)
            return True
        except Exception:
            return False

    @wsgi.serializers(xml=VolumeTypesTemplate)
    def index(self, req):
        """Returns the list of volume types."""
        limited_types = self._get_volume_types(req)
        req.cache_resource(limited_types, name='types')
        return self._view_builder.index(req, limited_types)

    @wsgi.serializers(xml=VolumeTypeTemplate)
    def show(self, req, id):
        """Return a single volume type item."""
        context = req.environ['cinder.context']

        if not context.is_admin and self._validate_policy(context):
            context = ctx.get_admin_context()

        # get default volume type
        if id is not None and id == 'default':
            vol_type = volume_types.get_default_volume_type()
            if not vol_type:
                msg = _("Default volume type can not be found.")
                raise exc.HTTPNotFound(explanation=msg)
            req.cache_resource(vol_type, name='types')
        else:
            try:
                vol_type = volume_types.get_volume_type(context, id)
                req.cache_resource(vol_type, name='types')
            except exception.VolumeTypeNotFound as error:
                raise exc.HTTPNotFound(explanation=error.msg)

        return self._view_builder.show(req, vol_type)

    def _parse_is_public(self, is_public):
        """Parse is_public into something usable.

        * True: List public volume types only
        * False: List private volume types only
        * None: List both public and private volume types
        """

        if is_public is None:
            # preserve default value of showing only public types
            return True
        elif utils.is_none_string(is_public):
            return None
        else:
            try:
                return strutils.bool_from_string(is_public, strict=True)
            except ValueError:
                msg = _('Invalid is_public filter [%s]') % is_public
                raise exc.HTTPBadRequest(explanation=msg)

    def _get_volume_types(self, req):
        """Helper function that returns a list of type dicts."""
        filters = {}
        context = req.environ['cinder.context']
        if not context.is_admin and self._validate_policy(context):
            context = ctx.get_admin_context()
        if context.is_admin:
            # Only admin has query access to all volume types
            filters['is_public'] = self._parse_is_public(
                req.params.get('is_public', None))
        else:
            filters['is_public'] = True
        limited_types = volume_types.get_all_types(
            context, search_opts=filters).values()
        return limited_types


def create_resource():
    return wsgi.Resource(VolumeTypesController())
