# Copyright 2012 OpenStack Foundation
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
from cinder.api.schemas import quota_classes as quota_class
from cinder.api import validation
from cinder import db
from cinder import exception
from cinder.policies import quota_class as policy
from cinder import quota


QUOTAS = quota.QUOTAS
GROUP_QUOTAS = quota.GROUP_QUOTAS


class QuotaClassSetsController(wsgi.Controller):

    def _format_quota_set(self, quota_class, quota_set):
        """Convert the quota object to a result dict."""

        quota_set['id'] = str(quota_class)

        return dict(quota_class_set=quota_set)

    def show(self, req, id):
        context = req.environ['cinder.context']
        context.authorize(policy.GET_POLICY)
        try:
            db.sqlalchemy.api.authorize_quota_class_context(context, id)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()
        quota_set = QUOTAS.get_class_quotas(context, id)
        group_quota_set = GROUP_QUOTAS.get_class_quotas(context, id)
        quota_set.update(group_quota_set)

        return self._format_quota_set(id, quota_set)

    @validation.schema(quota_class.update_quota_class)
    def update(self, req, id, body):
        context = req.environ['cinder.context']
        context.authorize(policy.UPDATE_POLICY)
        self.validate_string_length(id, 'quota_class_name',
                                    min_length=1, max_length=255)

        quota_class = id

        for key, value in body['quota_class_set'].items():
            try:
                db.quota_class_update(context, quota_class, key, value)
            except exception.QuotaClassNotFound:
                db.quota_class_create(context, quota_class, key, value)
            except exception.AdminRequired:
                raise webob.exc.HTTPForbidden()

        quota_set = QUOTAS.get_class_quotas(context, quota_class)
        group_quota_set = GROUP_QUOTAS.get_class_quotas(context, quota_class)
        quota_set.update(group_quota_set)

        return {'quota_class_set': quota_set}


class Quota_classes(extensions.ExtensionDescriptor):
    """Quota classes management support."""

    name = "QuotaClasses"
    alias = "os-quota-class-sets"
    updated = "2012-03-12T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-quota-class-sets',
                                           QuotaClassSetsController())
        resources.append(res)

        return resources
