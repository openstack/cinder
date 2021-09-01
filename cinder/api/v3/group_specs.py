# Copyright (c) 2016 EMC Corporation
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

"""The group types specs controller"""
from http import HTTPStatus

import webob

from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import group_specs
from cinder.api import validation
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.policies import group_types as policy
from cinder import rpc
from cinder.volume import group_types


class GroupTypeSpecsController(wsgi.Controller):
    """The group type specs API controller for the OpenStack API."""

    def _get_group_specs(self, context, group_type_id):
        group_specs = db.group_type_specs_get(context, group_type_id)
        specs_dict = {}
        for key, value in group_specs.items():
            specs_dict[key] = value
        return dict(group_specs=specs_dict)

    def _check_type(self, context, group_type_id):
        try:
            group_types.get_group_type(context, group_type_id)
        except exception.GroupTypeNotFound as ex:
            raise webob.exc.HTTPNotFound(explanation=ex.msg)

    @wsgi.Controller.api_version(mv.GROUP_TYPE)
    def index(self, req, group_type_id):
        """Returns the list of group specs for a given group type."""
        context = req.environ['cinder.context']
        context.authorize(policy.SPEC_GET_ALL_POLICY)
        self._check_type(context, group_type_id)
        return self._get_group_specs(context, group_type_id)

    @wsgi.Controller.api_version(mv.GROUP_TYPE)
    @wsgi.response(HTTPStatus.ACCEPTED)
    @validation.schema(group_specs.create)
    def create(self, req, group_type_id, body):
        context = req.environ['cinder.context']
        context.authorize(policy.SPEC_CREATE_POLICY)

        self._check_type(context, group_type_id)
        specs = body['group_specs']
        db.group_type_specs_update_or_create(context,
                                             group_type_id,
                                             specs)
        notifier_info = dict(type_id=group_type_id, specs=specs)
        notifier = rpc.get_notifier('groupTypeSpecs')
        notifier.info(context, 'group_type_specs.create',
                      notifier_info)
        return body

    @wsgi.Controller.api_version(mv.GROUP_TYPE)
    @validation.schema(group_specs.update)
    def update(self, req, group_type_id, id, body):
        context = req.environ['cinder.context']
        context.authorize(policy.SPEC_UPDATE_POLICY)

        self._check_type(context, group_type_id)
        if id not in body:
            expl = _('Request body and URI mismatch')
            raise webob.exc.HTTPBadRequest(explanation=expl)

        db.group_type_specs_update_or_create(context,
                                             group_type_id,
                                             body)
        notifier_info = dict(type_id=group_type_id, id=id)
        notifier = rpc.get_notifier('groupTypeSpecs')
        notifier.info(context,
                      'group_type_specs.update',
                      notifier_info)
        return body

    @wsgi.Controller.api_version(mv.GROUP_TYPE)
    def show(self, req, group_type_id, id):
        """Return a single extra spec item."""
        context = req.environ['cinder.context']
        context.authorize(policy.SPEC_GET_POLICY)

        self._check_type(context, group_type_id)
        specs = self._get_group_specs(context, group_type_id)
        if id in specs['group_specs']:
            return {id: specs['group_specs'][id]}
        else:
            msg = _("Group Type %(type_id)s has no extra spec with key "
                    "%(id)s.") % ({'type_id': group_type_id, 'id': id})
            raise webob.exc.HTTPNotFound(explanation=msg)

    @wsgi.Controller.api_version(mv.GROUP_TYPE)
    def delete(self, req, group_type_id, id):
        """Deletes an existing group spec."""
        context = req.environ['cinder.context']
        context.authorize(policy.SPEC_DELETE_POLICY)

        self._check_type(context, group_type_id)

        try:
            db.group_type_specs_delete(context, group_type_id, id)
        except exception.GroupTypeSpecsNotFound as error:
            raise webob.exc.HTTPNotFound(explanation=error.msg)

        notifier_info = dict(type_id=group_type_id, id=id)
        notifier = rpc.get_notifier('groupTypeSpecs')
        notifier.info(context,
                      'group_type_specs.delete',
                      notifier_info)
        return webob.Response(status_int=HTTPStatus.ACCEPTED)


def create_resource():
    return wsgi.Resource(GroupTypeSpecsController())
