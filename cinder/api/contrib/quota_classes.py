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
from cinder.api import xmlutil
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import quota


QUOTAS = quota.QUOTAS


authorize = extensions.extension_authorizer('volume', 'quota_classes')


class QuotaClassTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('quota_class_set',
                                       selector='quota_class_set')
        root.set('id')

        for resource in QUOTAS.resources:
            elem = xmlutil.SubTemplateElement(root, resource)
            elem.text = resource

        return xmlutil.MasterTemplate(root, 1)


class QuotaClassSetsController(wsgi.Controller):

    def _format_quota_set(self, quota_class, quota_set):
        """Convert the quota object to a result dict."""

        quota_set['id'] = str(quota_class)

        return dict(quota_class_set=quota_set)

    @wsgi.serializers(xml=QuotaClassTemplate)
    def show(self, req, id):
        context = req.environ['cinder.context']
        authorize(context)
        try:
            db.sqlalchemy.api.authorize_quota_class_context(context, id)
        except exception.NotAuthorized:
            raise webob.exc.HTTPForbidden()

        return self._format_quota_set(id,
                                      QUOTAS.get_class_quotas(context, id))

    @wsgi.serializers(xml=QuotaClassTemplate)
    def update(self, req, id, body):
        context = req.environ['cinder.context']
        authorize(context)
        quota_class = id
        if not self.is_valid_body(body, 'quota_class_set'):
            msg = (_("Missing required element quota_class_set"
                     " in request body."))
            raise webob.exc.HTTPBadRequest(explanation=msg)

        for key in body['quota_class_set'].keys():
            if key in QUOTAS:
                try:
                    value = int(body['quota_class_set'][key])
                except ValueError:
                    msg = _("Quota class limit must be specified as an"
                            " integer value.")
                    raise webob.exc.HTTPBadRequest(explanation=msg)
                if value < -1:
                    msg = _("Quota class limit must be -1 or greater.")
                    raise webob.exc.HTTPBadRequest(explanation=msg)
                try:
                    db.quota_class_update(context, quota_class, key, value)
                except exception.QuotaClassNotFound:
                    db.quota_class_create(context, quota_class, key, value)
                except exception.AdminRequired:
                    raise webob.exc.HTTPForbidden()
        return {'quota_class_set': QUOTAS.get_class_quotas(context,
                                                           quota_class)}


class Quota_classes(extensions.ExtensionDescriptor):
    """Quota classes management support."""

    name = "QuotaClasses"
    alias = "os-quota-class-sets"
    namespace = ("http://docs.openstack.org/volume/ext/"
                 "quota-classes-sets/api/v1.1")
    updated = "2012-03-12T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-quota-class-sets',
                                           QuotaClassSetsController())
        resources.append(res)

        return resources
