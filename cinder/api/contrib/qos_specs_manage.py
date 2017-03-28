# Copyright (c) 2013 eBay Inc.
# Copyright (c) 2013 OpenStack Foundation
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

"""The QoS specs extension"""

from oslo_log import log as logging
import six
from six.moves import http_client
import webob

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.views import qos_specs as view_qos_specs
from cinder import exception
from cinder.i18n import _
from cinder import rpc
from cinder import utils
from cinder.volume import qos_specs


LOG = logging.getLogger(__name__)

authorize_create = extensions.extension_authorizer('volume',
                                                   'qos_specs_manage:create')
authorize_get = extensions.extension_authorizer('volume',
                                                'qos_specs_manage:get')
authorize_get_all = extensions.extension_authorizer('volume',
                                                    'qos_specs_manage:get_all')
authorize_update = extensions.extension_authorizer('volume',
                                                   'qos_specs_manage:update')
authorize_delete = extensions.extension_authorizer('volume',
                                                   'qos_specs_manage:delete')


def _check_specs(context, specs_id):
    # Not found exception will be handled at the wsgi level
    qos_specs.get_qos_specs(context, specs_id)


class QoSSpecsController(wsgi.Controller):
    """The volume type extra specs API controller for the OpenStack API."""

    _view_builder_class = view_qos_specs.ViewBuilder

    @staticmethod
    @utils.if_notifications_enabled
    def _notify_qos_specs_error(context, method, payload):
        rpc.get_notifier('QoSSpecs').error(context,
                                           method,
                                           payload)

    def index(self, req):
        """Returns the list of qos_specs."""
        context = req.environ['cinder.context']
        authorize_get_all(context)

        params = req.params.copy()

        marker, limit, offset = common.get_pagination_params(params)
        sort_keys, sort_dirs = common.get_sort_params(params)
        filters = params
        allowed_search_options = ('id', 'name', 'consumer')
        utils.remove_invalid_filter_options(context, filters,
                                            allowed_search_options)

        specs = qos_specs.get_all_specs(context, filters=filters,
                                        marker=marker, limit=limit,
                                        offset=offset, sort_keys=sort_keys,
                                        sort_dirs=sort_dirs)
        return self._view_builder.summary_list(req, specs)

    def create(self, req, body=None):
        context = req.environ['cinder.context']
        authorize_create(context)

        self.assert_valid_body(body, 'qos_specs')

        specs = body['qos_specs']
        name = specs.pop('name', None)
        if name is None:
            msg = _("Please specify a name for QoS specs.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        self.validate_string_length(name, 'name', min_length=1,
                                    max_length=255, remove_whitespaces=True)
        name = name.strip()

        # Validate the key-value pairs in the qos spec.
        utils.validate_dictionary_string_length(specs)

        try:
            spec = qos_specs.create(context, name, specs)
            notifier_info = dict(name=name, specs=specs)
            rpc.get_notifier('QoSSpecs').info(context,
                                              'qos_specs.create',
                                              notifier_info)
        except exception.InvalidQoSSpecs as err:
            notifier_err = dict(name=name, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.create',
                                         notifier_err)
            raise webob.exc.HTTPBadRequest(explanation=six.text_type(err))
        except exception.QoSSpecsExists as err:
            notifier_err = dict(name=name, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.create',
                                         notifier_err)
            raise webob.exc.HTTPConflict(explanation=six.text_type(err))
        except exception.QoSSpecsCreateFailed as err:
            notifier_err = dict(name=name, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.create',
                                         notifier_err)
            raise webob.exc.HTTPInternalServerError(
                explanation=six.text_type(err))

        return self._view_builder.detail(req, spec)

    def update(self, req, id, body=None):
        context = req.environ['cinder.context']
        authorize_update(context)

        self.assert_valid_body(body, 'qos_specs')
        specs = body['qos_specs']
        try:
            qos_specs.update(context, id, specs)
            notifier_info = dict(id=id, specs=specs)
            rpc.get_notifier('QoSSpecs').info(context,
                                              'qos_specs.update',
                                              notifier_info)
        except (exception.QoSSpecsNotFound, exception.InvalidQoSSpecs) as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.update',
                                         notifier_err)
            # Not found exception will be handled at the wsgi level
            raise
        except exception.QoSSpecsUpdateFailed as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.update',
                                         notifier_err)
            raise webob.exc.HTTPInternalServerError(
                explanation=six.text_type(err))

        return body

    def show(self, req, id):
        """Return a single qos spec item."""
        context = req.environ['cinder.context']
        authorize_get(context)

        # Not found exception will be handled at the wsgi level
        spec = qos_specs.get_qos_specs(context, id)

        return self._view_builder.detail(req, spec)

    def delete(self, req, id):
        """Deletes an existing qos specs."""
        context = req.environ['cinder.context']
        authorize_delete(context)

        # Convert string to bool type in strict manner
        force = utils.get_bool_param('force', req.params)
        LOG.debug("Delete qos_spec: %(id)s, force: %(force)s",
                  {'id': id, 'force': force})

        try:
            qos_specs.delete(context, id, force)
            notifier_info = dict(id=id)
            rpc.get_notifier('QoSSpecs').info(context,
                                              'qos_specs.delete',
                                              notifier_info)
        except exception.QoSSpecsNotFound as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.delete',
                                         notifier_err)
            # Not found exception will be handled at the wsgi level
            raise
        except exception.QoSSpecsInUse as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.delete',
                                         notifier_err)
            if force:
                msg = _('Failed to disassociate qos specs.')
                raise webob.exc.HTTPInternalServerError(explanation=msg)
            msg = _('Qos specs still in use.')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=http_client.ACCEPTED)

    def delete_keys(self, req, id, body):
        """Deletes specified keys in qos specs."""
        context = req.environ['cinder.context']
        authorize_delete(context)

        if not (body and 'keys' in body
                and isinstance(body.get('keys'), list)):
            raise webob.exc.HTTPBadRequest()

        keys = body['keys']
        LOG.debug("Delete_key spec: %(id)s, keys: %(keys)s",
                  {'id': id, 'keys': keys})

        try:
            qos_specs.delete_keys(context, id, keys)
            notifier_info = dict(id=id)
            rpc.get_notifier('QoSSpecs').info(context, 'qos_specs.delete_keys',
                                              notifier_info)
        except exception.NotFound as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.delete_keys',
                                         notifier_err)
            # Not found exception will be handled at the wsgi level
            raise

        return webob.Response(status_int=http_client.ACCEPTED)

    def associations(self, req, id):
        """List all associations of given qos specs."""
        context = req.environ['cinder.context']
        authorize_get_all(context)

        LOG.debug("Get associations for qos_spec id: %s", id)

        try:
            associates = qos_specs.get_associations(context, id)
            notifier_info = dict(id=id)
            rpc.get_notifier('QoSSpecs').info(context,
                                              'qos_specs.associations',
                                              notifier_info)
        except exception.QoSSpecsNotFound as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.associations',
                                         notifier_err)
            # Not found exception will be handled at the wsgi level
            raise
        except exception.CinderException as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.associations',
                                         notifier_err)
            raise webob.exc.HTTPInternalServerError(
                explanation=six.text_type(err))

        return self._view_builder.associations(req, associates)

    def associate(self, req, id):
        """Associate a qos specs with a volume type."""
        context = req.environ['cinder.context']
        authorize_update(context)

        type_id = req.params.get('vol_type_id', None)

        if not type_id:
            msg = _('Volume Type id must not be None.')
            notifier_err = dict(id=id, error_message=msg)
            self._notify_qos_specs_error(context,
                                         'qos_specs.delete',
                                         notifier_err)
            raise webob.exc.HTTPBadRequest(explanation=msg)
        LOG.debug("Associate qos_spec: %(id)s with type: %(type_id)s",
                  {'id': id, 'type_id': type_id})

        try:
            qos_specs.associate_qos_with_type(context, id, type_id)
            notifier_info = dict(id=id, type_id=type_id)
            rpc.get_notifier('QoSSpecs').info(context,
                                              'qos_specs.associate',
                                              notifier_info)
        except exception.NotFound as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.associate',
                                         notifier_err)
            # Not found exception will be handled at the wsgi level
            raise
        except exception.InvalidVolumeType as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.associate',
                                         notifier_err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.associate',
                                         notifier_err)
            raise webob.exc.HTTPBadRequest(explanation=six.text_type(err))
        except exception.QoSSpecsAssociateFailed as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.associate',
                                         notifier_err)
            raise webob.exc.HTTPInternalServerError(
                explanation=six.text_type(err))

        return webob.Response(status_int=http_client.ACCEPTED)

    def disassociate(self, req, id):
        """Disassociate a qos specs from a volume type."""
        context = req.environ['cinder.context']
        authorize_update(context)

        type_id = req.params.get('vol_type_id', None)

        if not type_id:
            msg = _('Volume Type id must not be None.')
            notifier_err = dict(id=id, error_message=msg)
            self._notify_qos_specs_error(context,
                                         'qos_specs.delete',
                                         notifier_err)
            raise webob.exc.HTTPBadRequest(explanation=msg)
        LOG.debug("Disassociate qos_spec: %(id)s from type: %(type_id)s",
                  {'id': id, 'type_id': type_id})

        try:
            qos_specs.disassociate_qos_specs(context, id, type_id)
            notifier_info = dict(id=id, type_id=type_id)
            rpc.get_notifier('QoSSpecs').info(context,
                                              'qos_specs.disassociate',
                                              notifier_info)
        except exception.NotFound as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.disassociate',
                                         notifier_err)
            # Not found exception will be handled at the wsgi level
            raise
        except exception.QoSSpecsDisassociateFailed as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.disassociate',
                                         notifier_err)
            raise webob.exc.HTTPInternalServerError(
                explanation=six.text_type(err))

        return webob.Response(status_int=http_client.ACCEPTED)

    def disassociate_all(self, req, id):
        """Disassociate a qos specs from all volume types."""
        context = req.environ['cinder.context']
        authorize_update(context)

        LOG.debug("Disassociate qos_spec: %s from all.", id)

        try:
            qos_specs.disassociate_all(context, id)
            notifier_info = dict(id=id)
            rpc.get_notifier('QoSSpecs').info(context,
                                              'qos_specs.disassociate_all',
                                              notifier_info)
        except exception.QoSSpecsNotFound as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.disassociate_all',
                                         notifier_err)
            # Not found exception will be handled at the wsgi level
            raise
        except exception.QoSSpecsDisassociateFailed as err:
            notifier_err = dict(id=id, error_message=err)
            self._notify_qos_specs_error(context,
                                         'qos_specs.disassociate_all',
                                         notifier_err)
            raise webob.exc.HTTPInternalServerError(
                explanation=six.text_type(err))

        return webob.Response(status_int=http_client.ACCEPTED)


class Qos_specs_manage(extensions.ExtensionDescriptor):
    """QoS specs support."""

    name = "Qos_specs_manage"
    alias = "qos-specs"
    updated = "2013-08-02T00:00:00+00:00"

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            Qos_specs_manage.alias,
            QoSSpecsController(),
            member_actions={"associations": "GET",
                            "associate": "GET",
                            "disassociate": "GET",
                            "disassociate_all": "GET",
                            "delete_keys": "PUT"})

        resources.append(res)

        return resources
