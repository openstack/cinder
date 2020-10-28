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
from http import HTTPStatus

from oslo_utils import strutils
import webob

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.schemas import volume_types as volume_types_schema
from cinder.api import validation
from cinder.api.views import types as views_types
from cinder import exception
from cinder.i18n import _
from cinder.policies import volume_type as policy
from cinder import rpc
from cinder import utils
from cinder.volume import volume_types


class VolumeTypesManageController(wsgi.Controller):
    """The volume types API controller for the OpenStack API."""

    _view_builder_class = views_types.ViewBuilder

    @utils.if_notifications_enabled
    def _notify_volume_type_error(self, context, method, err,
                                  volume_type=None, id=None, name=None):
        payload = dict(
            volume_types=volume_type, name=name, id=id, error_message=err)
        rpc.get_notifier('volumeType').error(context, method, payload)

    @utils.if_notifications_enabled
    def _notify_volume_type_info(self, context, method, volume_type):
        payload = dict(volume_types=volume_type)
        rpc.get_notifier('volumeType').info(context, method, payload)

    @wsgi.action("create")
    @validation.schema(volume_types_schema.create)
    def _create(self, req, body):
        """Creates a new volume type."""
        context = req.environ['cinder.context']
        context.authorize(policy.CREATE_POLICY)
        vol_type = body['volume_type']
        name = vol_type['name']
        description = vol_type.get('description')
        specs = vol_type.get('extra_specs', {})
        is_public = vol_type.get('os-volume-type-access:is_public', True)
        is_public = strutils.bool_from_string(is_public, strict=True)
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
            raise webob.exc.HTTPConflict(explanation=str(err))
        except exception.VolumeTypeNotFoundByName as err:
            self._notify_volume_type_error(
                context, 'volume_type.create', err, name=name)
            # Not found exception will be handled at the wsgi level
            raise

        return self._view_builder.show(req, vol_type)

    @wsgi.action("update")
    @validation.schema(volume_types_schema.update)
    def _update(self, req, id, body):
        # Update description for a given volume type.
        context = req.environ['cinder.context']
        context.authorize(policy.UPDATE_POLICY)
        vol_type = body['volume_type']
        description = vol_type.get('description')
        name = vol_type.get('name')
        is_public = vol_type.get('is_public')

        if is_public is not None:
            is_public = strutils.bool_from_string(is_public, strict=True)

        # If name specified, name can not be empty.
        if name and len(name.strip()) == 0:
            msg = _("Volume type name can not be empty.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # Name, description and is_public can not be None.
        # Specify one of them, or a combination thereof.
        if name is None and description is None and is_public is None:
            msg = _("Specify volume type name, description, is_public or "
                    "a combination thereof.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        try:
            volume_types.update(context, id, name, description,
                                is_public=is_public)
            # Get the updated
            vol_type = volume_types.get_volume_type(context, id)
            req.cache_resource(vol_type, name='types')
            self._notify_volume_type_info(
                context, 'volume_type.update', vol_type)

        except exception.VolumeTypeNotFound as err:
            self._notify_volume_type_error(
                context, 'volume_type.update', err, id=id)
            # Not found exception will be handled at the wsgi level
            raise
        except exception.VolumeTypeExists as err:
            self._notify_volume_type_error(
                context, 'volume_type.update', err, volume_type=vol_type)
            raise webob.exc.HTTPConflict(explanation=str(err))
        except exception.VolumeTypeUpdateFailed as err:
            self._notify_volume_type_error(
                context, 'volume_type.update', err, volume_type=vol_type)
            raise webob.exc.HTTPInternalServerError(
                explanation=str(err))

        return self._view_builder.show(req, vol_type)

    @wsgi.action("delete")
    def _delete(self, req, id):
        """Deletes an existing volume type."""
        context = req.environ['cinder.context']
        context.authorize(policy.DELETE_POLICY)

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
        except exception.VolumeTypeNotFound as err:
            self._notify_volume_type_error(
                context, 'volume_type.delete', err, id=id)
            # Not found exception will be handled at the wsgi level
            raise
        except (exception.VolumeTypeDeletionError,
                exception.VolumeTypeDefaultDeletionError) as err:
            self._notify_volume_type_error(
                context, 'volume_type.delete', err, volume_type=vol_type)
            raise webob.exc.HTTPBadRequest(explanation=err.msg)
        except exception.VolumeTypeDefaultMisconfiguredError as err:
            self._notify_volume_type_error(
                context, 'volume_type.delete', err, volume_type=vol_type)
            raise webob.exc.HTTPInternalServerError(explanation=err.msg)

        return webob.Response(status_int=HTTPStatus.ACCEPTED)


class Types_manage(extensions.ExtensionDescriptor):
    """Types manage support."""

    name = "TypesManage"
    alias = "os-types-manage"
    updated = "2011-08-24T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = VolumeTypesManageController()
        extension = extensions.ControllerExtension(self, 'types', controller)
        return [extension]
