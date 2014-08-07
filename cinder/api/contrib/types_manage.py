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

    def _notify_volume_type_error(self, context, method, payload):
        rpc.get_notifier('volumeType').error(context, method, payload)

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
        specs = vol_type.get('extra_specs', {})

        if name is None or name == "":
            raise webob.exc.HTTPBadRequest()

        try:
            volume_types.create(context, name, specs)
            vol_type = volume_types.get_volume_type_by_name(context, name)
            notifier_info = dict(volume_types=vol_type)
            rpc.get_notifier('volumeType').info(context, 'volume_type.create',
                                                notifier_info)

        except exception.VolumeTypeExists as err:
            notifier_err = dict(volume_types=vol_type, error_message=err)
            self._notify_volume_type_error(context,
                                           'volume_type.create',
                                           notifier_err)

            raise webob.exc.HTTPConflict(explanation=six.text_type(err))
        except exception.NotFound as err:
            notifier_err = dict(volume_types=vol_type, error_message=err)
            self._notify_volume_type_error(context,
                                           'volume_type.create',
                                           notifier_err)
            raise webob.exc.HTTPNotFound()

        return self._view_builder.show(req, vol_type)

    @wsgi.action("delete")
    def _delete(self, req, id):
        """Deletes an existing volume type."""
        context = req.environ['cinder.context']
        authorize(context)

        try:
            vol_type = volume_types.get_volume_type(context, id)
            volume_types.destroy(context, vol_type['id'])
            notifier_info = dict(volume_types=vol_type)
            rpc.get_notifier('volumeType').info(context,
                                                'volume_type.delete',
                                                notifier_info)
        except exception.VolumeTypeInUse as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_volume_type_error(context,
                                           'volume_type.delete',
                                           notifier_err)
            msg = _('Target volume type is still in use.')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except exception.NotFound as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_volume_type_error(context,
                                           'volume_type.delete',
                                           notifier_err)

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
