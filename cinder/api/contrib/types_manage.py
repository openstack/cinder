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

"""The volume types manage extension."""

import six
import webob

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.v1 import types
from cinder.api.views import types as views_types
from cinder import exception
from cinder.i18n import _
from cinder import rpc
from cinder.volume import volume_types


authorize = extensions.extension_authorizer('volume', 'types_manage')


class VolumeTypesManageController(wsgi.Controller):
    """The volume types API controller for the OpenStack API."""

    _view_builder_class = views_types.ViewBuilder

    def _notify_volume_type_error(self, context, method, err,
                                  volume_type=None, id=None, name=None):
        payload = dict(
            volume_types=volume_type, name=name, id=id, error_message=err)
        rpc.get_notifier('volumeType').error(context, method, payload)

    def _notify_volume_type_info(self, context, method, volume_type):
        payload = dict(volume_types=volume_type)
        rpc.get_notifier('volumeType').info(context, method, payload)

    @wsgi.action("create")
    @wsgi.serializers(xml=types.VolumeTypeTemplate)
    def _create(self, req, body):
        """Creates a new volume type."""
        context = req.environ['cinder.context']
        authorize(context)

        if not self.is_valid_body(body, 'volume_type'):
            raise webob.exc.HTTPBadRequest()

        vol_type = body['volume_type']
        name = vol_type.get('name', None)
        description = vol_type.get('description')
        specs = vol_type.get('extra_specs', {})
        is_public = vol_type.get('os-volume-type-access:is_public', True)

        if name is None or len(name.strip()) == 0:
            msg = _("Volume type name can not be empty.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            volume_types.create(context,
                                name,
                                specs,
                                is_public,
                                description=description)
            vol_type = volume_types.get_volume_type_by_name(context, name)
            req.cache_resource(vol_type, name='types')
            self._notify_volume_type_info(
                context, 'volume_type.create', vol_type)

        except exception.VolumeTypeExists as err:
            self._notify_volume_type_error(
                context, 'volume_type.create', err, volume_type=vol_type)
            raise webob.exc.HTTPConflict(explanation=six.text_type(err))
        except exception.NotFound as err:
            self._notify_volume_type_error(
                context, 'volume_type.create', err, name=name)
            raise webob.exc.HTTPNotFound()

        return self._view_builder.show(req, vol_type)

    @wsgi.action("update")
    @wsgi.serializers(xml=types.VolumeTypeTemplate)
    def _update(self, req, id, body):
        # Update description for a given volume type.
        context = req.environ['cinder.context']
        authorize(context)

        if not self.is_valid_body(body, 'volume_type'):
            raise webob.exc.HTTPBadRequest()

        vol_type = body['volume_type']
        description = vol_type.get('description')
        name = vol_type.get('name')

        # Name and description can not be both None.
        # If name specified, name can not be empty.
        if name and len(name.strip()) == 0:
            msg = _("Volume type name can not be empty.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if name is None and description is None:
            msg = _("Specify either volume type name and/or description.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            volume_types.update(context, id, name, description)
            # Get the updated
            vol_type = volume_types.get_volume_type(context, id)
            req.cache_resource(vol_type, name='types')
            self._notify_volume_type_info(
                context, 'volume_type.update', vol_type)

        except exception.VolumeTypeNotFound as err:
            self._notify_volume_type_error(
                context, 'volume_type.update', err, id=id)
            raise webob.exc.HTTPNotFound(explanation=six.text_type(err))
        except exception.VolumeTypeExists as err:
            self._notify_volume_type_error(
                context, 'volume_type.update', err, volume_type=vol_type)
            raise webob.exc.HTTPConflict(explanation=six.text_type(err))
        except exception.VolumeTypeUpdateFailed as err:
            self._notify_volume_type_error(
                context, 'volume_type.update', err, volume_type=vol_type)
            raise webob.exc.HTTPInternalServerError(
                explanation=six.text_type(err))

        return self._view_builder.show(req, vol_type)

    @wsgi.action("delete")
    def _delete(self, req, id):
        """Deletes an existing volume type."""
        context = req.environ['cinder.context']
        authorize(context)

        try:
            vol_type = volume_types.get_volume_type(context, id)
            volume_types.destroy(context, vol_type['id'])
            self._notify_volume_type_info(
                context, 'volume_type.delete', vol_type)
        except exception.VolumeTypeInUse as err:
            self._notify_volume_type_error(
                context, 'volume_type.delete', err, volume_type=vol_type)
            msg = _('Target volume type is still in use.')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except exception.NotFound as err:
            self._notify_volume_type_error(
                context, 'volume_type.delete', err, id=id)
            raise webob.exc.HTTPNotFound()

        return webob.Response(status_int=202)


class Types_manage(extensions.ExtensionDescriptor):
    """Types manage support."""

    name = "TypesManage"
    alias = "os-types-manage"
    namespace = "http://docs.openstack.org/volume/ext/types-manage/api/v1"
    updated = "2011-08-24T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeTypesManageController()
        extension = extensions.ControllerExtension(self, 'types', controller)
        return [extension]
