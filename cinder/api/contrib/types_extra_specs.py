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

"""The volume types extra specs extension"""

from six.moves import http_client
import webob

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import rpc
from cinder import utils
from cinder.volume import volume_types

authorize = extensions.extension_authorizer('volume', 'types_extra_specs')


class VolumeTypeExtraSpecsController(wsgi.Controller):
    """The volume type extra specs API controller for the OpenStack API."""

    def _get_extra_specs(self, context, type_id):
        extra_specs = db.volume_type_extra_specs_get(context, type_id)
        specs_dict = {}
        for key, value in extra_specs.items():
            specs_dict[key] = value
        return dict(extra_specs=specs_dict)

    def _check_type(self, context, type_id):
        # Not found exception will be handled at the wsgi level
        volume_types.get_volume_type(context, type_id)

    def index(self, req, type_id):
        """Returns the list of extra specs for a given volume type."""
        context = req.environ['cinder.context']
        authorize(context)
        self._check_type(context, type_id)
        return self._get_extra_specs(context, type_id)

    def create(self, req, type_id, body=None):
        context = req.environ['cinder.context']
        authorize(context)

        self.assert_valid_body(body, 'extra_specs')

        self._check_type(context, type_id)
        specs = body['extra_specs']
        self._check_key_names(specs.keys())
        utils.validate_dictionary_string_length(specs)

        db.volume_type_extra_specs_update_or_create(context,
                                                    type_id,
                                                    specs)
        notifier_info = dict(type_id=type_id, specs=specs)
        notifier = rpc.get_notifier('volumeTypeExtraSpecs')
        notifier.info(context, 'volume_type_extra_specs.create',
                      notifier_info)
        return body

    def update(self, req, type_id, id, body=None):
        context = req.environ['cinder.context']
        authorize(context)
        if not body:
            expl = _('Request body empty')
            raise webob.exc.HTTPBadRequest(explanation=expl)
        self._check_type(context, type_id)
        if id not in body:
            expl = _('Request body and URI mismatch')
            raise webob.exc.HTTPBadRequest(explanation=expl)
        if len(body) > 1:
            expl = _('Request body contains too many items')
            raise webob.exc.HTTPBadRequest(explanation=expl)
        self._check_key_names(body.keys())
        utils.validate_dictionary_string_length(body)

        db.volume_type_extra_specs_update_or_create(context,
                                                    type_id,
                                                    body)
        notifier_info = dict(type_id=type_id, id=id)
        notifier = rpc.get_notifier('volumeTypeExtraSpecs')
        notifier.info(context,
                      'volume_type_extra_specs.update',
                      notifier_info)
        return body

    def show(self, req, type_id, id):
        """Return a single extra spec item."""
        context = req.environ['cinder.context']
        authorize(context)
        self._check_type(context, type_id)
        specs = self._get_extra_specs(context, type_id)
        if id in specs['extra_specs']:
            return {id: specs['extra_specs'][id]}
        else:
            raise exception.VolumeTypeExtraSpecsNotFound(
                volume_type_id=type_id, extra_specs_key=id)

    def delete(self, req, type_id, id):
        """Deletes an existing extra spec."""
        context = req.environ['cinder.context']
        self._check_type(context, type_id)
        authorize(context)

        # Not found exception will be handled at the wsgi level
        db.volume_type_extra_specs_delete(context, type_id, id)

        notifier_info = dict(type_id=type_id, id=id)
        notifier = rpc.get_notifier('volumeTypeExtraSpecs')
        notifier.info(context,
                      'volume_type_extra_specs.delete',
                      notifier_info)
        return webob.Response(status_int=http_client.ACCEPTED)

    def _check_key_names(self, keys):
        if not common.validate_key_names(keys):
            expl = _('Key names can only contain alphanumeric characters, '
                     'underscores, periods, colons and hyphens.')

            raise webob.exc.HTTPBadRequest(explanation=expl)


class Types_extra_specs(extensions.ExtensionDescriptor):
    """Type extra specs support."""

    name = "TypesExtraSpecs"
    alias = "os-types-extra-specs"
    updated = "2011-08-24T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension('extra_specs',
                                           VolumeTypeExtraSpecsController(),
                                           parent=dict(member_name='type',
                                                       collection_name='types')
                                           )
        resources.append(res)

        return resources
