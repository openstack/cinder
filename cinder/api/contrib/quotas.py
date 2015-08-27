# Copyright 2011 OpenStack Foundation
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

import webob

from keystoneclient import exceptions
from keystoneclient.v3 import client

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import db
from cinder.db.sqlalchemy import api as sqlalchemy_api
from cinder import exception
from cinder.i18n import _
from cinder import quota
from cinder import utils

from oslo_config import cfg
from oslo_utils import strutils


CONF = cfg.CONF
QUOTAS = quota.QUOTAS
NON_QUOTA_KEYS = ['tenant_id', 'id']


authorize_update = extensions.extension_authorizer('volume', 'quotas:update')
authorize_show = extensions.extension_authorizer('volume', 'quotas:show')
authorize_delete = extensions.extension_authorizer('volume', 'quotas:delete')


class QuotaTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_set', selector='quota_set')
        root.set('id')

        for resource in QUOTAS.resources:
            elem = xmlutil.SubTemplateElement(root, resource)
            elem.text = resource

        return xmlutil.MasterTemplate(root, 1)


class QuotaSetsController(wsgi.Controller):

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict."""

        quota_set['id'] = str(project_id)

        return dict(quota_set=quota_set)

    def _validate_existing_resource(self, key, value, quota_values):
        if key == 'per_volume_gigabytes':
            return
        v = quota_values.get(key, {})
        if value < (v.get('in_use', 0) + v.get('reserved', 0)):
            msg = _("Quota %s limit must be equal or greater than existing "
                    "resources.") % key
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_quotas(self, context, id, usages=False, parent_project_id=None):
        values = QUOTAS.get_project_quotas(context, id, usages=usages,
                                           parent_project_id=parent_project_id)

        if usages:
            return values
        else:
            return {k: v['limit'] for k, v in values.items()}

    def _get_project(self, context, id, subtree_as_ids=False):
        """A Helper method to get the project hierarchy.

        Along with Hierachical Multitenancy, projects can be hierarchically
        organized. Therefore, we need to know the project hierarchy, if any, in
        order to do quota operations properly.
        """
        try:
            keystone = client.Client(auth_url=CONF.keymgr.encryption_auth_url,
                                     token=context.auth_token,
                                     project_id=context.project_id)
            project = keystone.projects.get(id, subtree_as_ids=subtree_as_ids)
        except exceptions.NotFound:
            msg = (_("Tenant ID: %s does not exist.") % id)
            raise webob.exc.HTTPNotFound(explanation=msg)
        return project

    @wsgi.serializers(xml=QuotaTemplate)
    def show(self, req, id):
        context = req.environ['cinder.context']
        authorize_show(context)

        params = req.params
        if not hasattr(params, '__call__') and 'usage' in params:
            usage = strutils.bool_from_string(params['usage'])
        else:
            usage = False

        try:
            sqlalchemy_api.authorize_project_context(context, id)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        return self._format_quota_set(id, self._get_quotas(context, id, usage))

    @wsgi.serializers(xml=QuotaTemplate)
    def update(self, req, id, body):
        context = req.environ['cinder.context']
        authorize_update(context)
        self.validate_string_length(id, 'quota_set_name',
                                    min_length=1, max_length=255)

        project_id = id
        self.assert_valid_body(body, 'quota_set')

        # Get the optional argument 'skip_validation' from body,
        # if skip_validation is False, then validate existing resource.
        skip_flag = body.get('skip_validation', True)
        if not utils.is_valid_boolstr(skip_flag):
            msg = _("Invalid value '%s' for skip_validation.") % skip_flag
            raise exception.InvalidParameterValue(err=msg)
        skip_flag = strutils.bool_from_string(skip_flag)

        bad_keys = []

        # NOTE(ankit): Pass #1 - In this loop for body['quota_set'].items(),
        # we figure out if we have any bad keys.
        for key, value in body['quota_set'].items():
            if (key not in QUOTAS and key not in NON_QUOTA_KEYS):
                bad_keys.append(key)
                continue

        if len(bad_keys) > 0:
            msg = _("Bad key(s) in quota set: %s") % ",".join(bad_keys)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # NOTE(ankit): Pass #2 - In this loop for body['quota_set'].keys(),
        # we validate the quota limits to ensure that we can bail out if
        # any of the items in the set is bad. Meanwhile we validate value
        # to ensure that the value can't be lower than number of existing
        # resources.
        quota_values = QUOTAS.get_project_quotas(context, project_id)
        valid_quotas = {}
        for key in body['quota_set'].keys():
            if key in NON_QUOTA_KEYS:
                continue

            valid_quotas[key] = self.validate_integer(
                body['quota_set'][key], key, min_value=-1,
                max_value=db.MAX_INT)

            if not skip_flag:
                self._validate_existing_resource(key, value, quota_values)

        # NOTE(ankit): Pass #3 - At this point we know that all the keys and
        # values are valid and we can iterate and update them all in one shot
        # without having to worry about rolling back etc as we have done
        # the validation up front in the 2 loops above.
        for key, value in valid_quotas.items():
            try:
                db.quota_update(context, project_id, key, value)
            except exception.ProjectQuotaNotFound:
                db.quota_create(context, project_id, key, value)
            except exception.AdminRequired:
                raise webob.exc.HTTPForbidden()
        return {'quota_set': self._get_quotas(context, id)}

    @wsgi.serializers(xml=QuotaTemplate)
    def defaults(self, req, id):
        context = req.environ['cinder.context']
        authorize_show(context)
        project = self._get_project(context, context.project_id)
        return self._format_quota_set(id, QUOTAS.get_defaults(
            context, parent_project_id=project.parent_id))

    @wsgi.serializers(xml=QuotaTemplate)
    def delete(self, req, id):

        context = req.environ['cinder.context']
        authorize_delete(context)

        try:
            db.quota_destroy_by_project(context, id)
        except exception.AdminRequired:
            raise webob.exc.HTTPForbidden()


class Quotas(extensions.ExtensionDescriptor):
    """Quota management support."""

    name = "Quotas"
    alias = "os-quota-sets"
    namespace = "http://docs.openstack.org/volume/ext/quotas-sets/api/v1.1"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-quota-sets',
                                           QuotaSetsController(),
                                           member_actions={'defaults': 'GET'})
        resources.append(res)

        return resources
