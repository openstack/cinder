# Copyright 2012 OpenStack Foundation
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

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import quota

QUOTAS = quota.QUOTAS

authorize = extensions.soft_extension_authorizer('limits', 'used_limits')


class UsedLimitsController(wsgi.Controller):

    @wsgi.extends
    def index(self, req, resp_obj):
        context = req.environ['cinder.context']
        if authorize(context):
            params = req.params.copy()
            req_version = req.api_version_request

            # TODO(wangxiyuan): Support "tenant_id" here to keep the backwards
            # compatibility. Remove it once we drop all support for "tenant".
            if req_version.matches(None, "3.38") or not context.is_admin:
                params.pop('project_id', None)
                params.pop('tenant_id', None)
            project_id = params.get(
                'project_id', params.get('tenant_id', context.project_id))
            quotas = QUOTAS.get_project_quotas(context, project_id,
                                               usages=True)

            quota_map = {
                'totalVolumesUsed': 'volumes',
                'totalGigabytesUsed': 'gigabytes',
                'totalSnapshotsUsed': 'snapshots',
                'totalBackupsUsed': 'backups',
                'totalBackupGigabytesUsed': 'backup_gigabytes'
            }

            used_limits = {}
            for display_name, single_quota in quota_map.items():
                if single_quota in quotas:
                    used_limits[display_name] = quotas[single_quota]['in_use']

            resp_obj.obj['limits']['absolute'].update(used_limits)


class Used_limits(extensions.ExtensionDescriptor):
    """Provide data on limited resources that are being used."""

    name = "UsedLimits"
    alias = 'os-used-limits'
    updated = "2013-10-03T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = UsedLimitsController()
        extension = extensions.ControllerExtension(self, 'limits', controller)
        return [extension]
