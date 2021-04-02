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

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.schemas import quotas
from cinder.api import validation
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.policies import quotas as policy
from cinder import quota
from cinder import utils

QUOTAS = quota.QUOTAS
GROUP_QUOTAS = quota.GROUP_QUOTAS
NON_QUOTA_KEYS = quota.NON_QUOTA_KEYS


class QuotaSetsController(wsgi.Controller):

    def _format_quota_set(self, project_id, quota_set):
        """Convert the quota object to a result dict."""

        quota_set['id'] = str(project_id)

        return dict(quota_set=quota_set)

    def _validate_existing_resource(self, key, value, quota_values):
        # -1 limit will always be greater than the existing value
        if key == 'per_volume_gigabytes' or value == -1:
            return
        v = quota_values.get(key, {})
        used = (v.get('in_use', 0) + v.get('reserved', 0))
        if value < used:
            msg = (_("Quota %(key)s limit must be equal or greater than "
                     "existing resources. Current usage is %(usage)s "
                     "and the requested limit is %(limit)s.")
                   % {'key': key,
                      'usage': used,
                      'limit': value})
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_quotas(self, context, id, usages=False):
        values = QUOTAS.get_project_quotas(context, id, usages=usages)
        group_values = GROUP_QUOTAS.get_project_quotas(context, id,
                                                       usages=usages)
        values.update(group_values)

        if usages:
            return values
        else:
            return {k: v['limit'] for k, v in values.items()}

    def show(self, req, id):
        """Show quota for a particular tenant

        :param req: request
        :param id: target project id that needs to be shown
        """
        context = req.environ['cinder.context']
        params = req.params
        target_project_id = id
        context.authorize(policy.SHOW_POLICY,
                          target={'project_id': target_project_id})

        if not hasattr(params, '__call__') and 'usage' in params:
            usage = utils.get_bool_param('usage', params)
        else:
            usage = False

        quotas = self._get_quotas(context, target_project_id, usage)
        return self._format_quota_set(target_project_id, quotas)

    @validation.schema(quotas.update_quota)
    def update(self, req, id, body):
        """Update Quota for a particular tenant

        :param req: request
        :param id: target project id that needs to be updated
        :param body: key, value pair that will be applied to
                     the resources if the update succeeds
        """
        context = req.environ['cinder.context']
        target_project_id = id
        context.authorize(policy.UPDATE_POLICY,
                          target={'project_id': target_project_id})
        self.validate_string_length(id, 'quota_set_name',
                                    min_length=1, max_length=255)

        # NOTE(ankit): Pass #1 - In this loop for body['quota_set'].keys(),
        # we validate the quota limits to ensure that we can bail out if
        # any of the items in the set is bad. Meanwhile we validate value
        # to ensure that the value can't be lower than number of existing
        # resources.
        quota_values = QUOTAS.get_project_quotas(context, target_project_id,
                                                 defaults=False)
        group_quota_values = GROUP_QUOTAS.get_project_quotas(context,
                                                             target_project_id,
                                                             defaults=False)
        quota_values.update(group_quota_values)
        valid_quotas = {}
        reservations = []
        for key in body['quota_set'].keys():
            if key in NON_QUOTA_KEYS:
                continue
            self._validate_existing_resource(key, body['quota_set'][key],
                                             quota_values)

            valid_quotas[key] = body['quota_set'][key]

        # NOTE(ankit): Pass #2 - At this point we know that all the keys and
        # values are valid and we can iterate and update them all in one shot
        # without having to worry about rolling back etc as we have done
        # the validation up front in the 2 loops above.
        for key, value in valid_quotas.items():
            try:
                db.quota_update(context, target_project_id, key, value)
            except exception.ProjectQuotaNotFound:
                db.quota_create(context, target_project_id, key, value)
            except exception.AdminRequired:
                raise webob.exc.HTTPForbidden()

        if reservations:
            db.reservation_commit(context, reservations)
        return {'quota_set': self._get_quotas(context, target_project_id)}

    def _get_quota_usage(self, quota_obj):
        return (quota_obj.get('in_use', 0) + quota_obj.get('reserved', 0))

    def defaults(self, req, id):
        context = req.environ['cinder.context']
        context.authorize(policy.SHOW_POLICY, target={'project_id': id})
        defaults = QUOTAS.get_defaults(context, project_id=id)
        group_defaults = GROUP_QUOTAS.get_defaults(context, project_id=id)
        defaults.update(group_defaults)
        return self._format_quota_set(id, defaults)

    def delete(self, req, id):
        """Delete Quota for a particular tenant.

        :param req: request
        :param id: target project id that needs to be deleted
        """
        context = req.environ['cinder.context']
        context.authorize(policy.DELETE_POLICY, target={'project_id': id})

        db.quota_destroy_by_project(context, id)


class Quotas(extensions.ExtensionDescriptor):
    """Quota management support."""

    name = "Quotas"
    alias = "os-quota-sets"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
            'os-quota-sets', QuotaSetsController(),
            member_actions={'defaults': 'GET'})
        resources.append(res)

        return resources
