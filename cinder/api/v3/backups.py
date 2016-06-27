# Copyright (c) 2016 Intel, Inc.
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

"""The backups V3 api."""

from webob import exc

from cinder.api.contrib import backups as backups_v2
from cinder.api.openstack import wsgi
from cinder.i18n import _

BACKUP_UPDATE_MICRO_VERSION = '3.9'


class BackupsController(backups_v2.BackupsController):
    """The backups API controller for the Openstack API V3."""

    @wsgi.Controller.api_version(BACKUP_UPDATE_MICRO_VERSION)
    def update(self, req, id, body):
        """Update a backup."""
        context = req.environ['cinder.context']
        self.assert_valid_body(body, 'backup')

        backup_update = body['backup']

        self.validate_name_and_description(backup_update)
        update_dict = {}
        if 'name' in backup_update:
            update_dict['display_name'] = backup_update.pop('name')
        if 'description' in backup_update:
            update_dict['display_description'] = (
                backup_update.pop('description'))
        # Check no unsupported fields.
        if backup_update:
            msg = _("Unsupported fields %s.") % (", ".join(backup_update))
            raise exc.HTTPBadRequest(explanation=msg)

        new_backup = self.backup_api.update(context, id, update_dict)

        return self._view_builder.summary(req, new_backup)


def create_resource():
    return wsgi.Resource(BackupsController())
