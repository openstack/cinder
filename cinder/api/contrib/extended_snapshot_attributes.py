#   Copyright 2012 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

"""The Extended Snapshot Attributes API extension."""

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.policies import snapshots as policy


class ExtendedSnapshotAttributesController(wsgi.Controller):
    def _extend_snapshot(self, req, resp_snap):
        db_snap = req.get_db_snapshot(resp_snap['id'])
        for attr in ['project_id', 'progress']:
            key = "%s:%s" % (Extended_snapshot_attributes.alias, attr)
            resp_snap[key] = db_snap[attr]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['cinder.context']
        if context.authorize(policy.EXTEND_ATTRIBUTE, fatal=False):
            # Attach our slave template to the response object
            snapshot = resp_obj.obj['snapshot']
            self._extend_snapshot(req, snapshot)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['cinder.context']
        if context.authorize(policy.EXTEND_ATTRIBUTE, fatal=False):
            # Attach our slave template to the response object
            for snapshot in list(resp_obj.obj['snapshots']):
                self._extend_snapshot(req, snapshot)


class Extended_snapshot_attributes(extensions.ExtensionDescriptor):
    """Extended SnapshotAttributes support."""

    name = "ExtendedSnapshotAttributes"
    alias = "os-extended-snapshot-attributes"
    updated = "2012-06-19T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ExtendedSnapshotAttributesController()
        extension = extensions.ControllerExtension(self, 'snapshots',
                                                   controller)
        return [extension]
