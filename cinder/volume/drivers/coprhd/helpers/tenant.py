# Copyright (c) 2016 EMC Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from cinder.i18n import _
from cinder.volume.drivers.coprhd.helpers import commoncoprhdapi as common


class Tenant(common.CoprHDResource):

    URI_SERVICES_BASE = ''
    URI_TENANT = URI_SERVICES_BASE + '/tenant'
    URI_TENANTS = URI_SERVICES_BASE + '/tenants/{0}'
    URI_TENANTS_SUBTENANT = URI_TENANTS + '/subtenants'

    def tenant_query(self, label):
        """Returns the UID of the tenant specified by the hierarchical name.

        (ex tenant1/tenant2/tenant3)
        """

        if common.is_uri(label):
            return label

        tenant_id = self.tenant_getid()

        if not label:
            return tenant_id

        subtenants = self.tenant_list(tenant_id)
        subtenants.append(self.tenant_show(None))

        for tenant in subtenants:
            if tenant['name'] == label:
                rslt = self.tenant_show_by_uri(tenant['id'])
                if rslt:
                    return tenant['id']

        raise common.CoprHdError(common.CoprHdError.NOT_FOUND_ERR,
                                 (_("Tenant %s: not found") % label))

    def tenant_show(self, label):
        """Returns the details of the tenant based on its name."""
        if label:
            tenant_id = self.tenant_query(label)
        else:
            tenant_id = self.tenant_getid()

        return self.tenant_show_by_uri(tenant_id)

    def tenant_getid(self):
        (s, h) = common.service_json_request(self.ipaddr, self.port,
                                             "GET", Tenant.URI_TENANT, None)

        o = common.json_decode(s)
        return o['id']

    def tenant_list(self, uri=None):
        """Returns all the tenants under a parent tenant.

        :param uri: The parent tenant name
        :returns: JSON payload of tenant list
        """

        if not uri:
            uri = self.tenant_getid()

        tenantdtls = self.tenant_show_by_uri(uri)

        if(tenantdtls and not ('parent_tenant' in tenantdtls and
                               ("id" in tenantdtls['parent_tenant']))):
            (s, h) = common.service_json_request(
                self.ipaddr, self.port,
                "GET", self.URI_TENANTS_SUBTENANT.format(uri), None)

            o = common.json_decode(s)
            return o['subtenant']

        else:
            return []

    def tenant_show_by_uri(self, uri):
        """Makes REST API call to retrieve tenant details based on UUID."""
        (s, h) = common.service_json_request(self.ipaddr, self.port, "GET",
                                             Tenant.URI_TENANTS.format(uri),
                                             None)

        o = common.json_decode(s)
        if 'inactive' in o and o['inactive']:
            return None

        return o

    def get_tenant_by_name(self, tenant):
        uri = None
        if not tenant:
            uri = self.tenant_getid()
        else:
            if not common.is_uri(tenant):
                uri = self.tenant_query(tenant)
            else:
                uri = tenant
            if not uri:
                raise common.CoprHdError(common.CoprHdError.NOT_FOUND_ERR,
                                         (_("Tenant %s: not found") % tenant))
        return uri
