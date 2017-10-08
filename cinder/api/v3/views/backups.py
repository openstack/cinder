# Copyright 2017 FiberHome Telecommunication Technologies CO.,LTD
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

from cinder.api import microversions as mv
from cinder.api.views import backups as views_v2


class ViewBuilder(views_v2.ViewBuilder):
    """Model a backups API V3 response as a python dictionary."""

    def detail(self, request, backup):
        """Detailed view of a single backup."""
        backup_ref = super(ViewBuilder, self).detail(request, backup)

        # Add metadata if min version is greater than or equal to
        # BACKUP_METADATA.
        req_version = request.api_version_request
        if req_version.matches(mv.BACKUP_METADATA):
            backup_ref['backup']['metadata'] = backup.metadata
        return backup_ref
