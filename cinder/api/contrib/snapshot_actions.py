#   Copyright 2013, Red Hat, Inc.
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

import webob

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import db
from cinder.i18n import _
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def authorize(context, action_name):
    action = 'snapshot_actions:%s' % action_name
    extensions.extension_authorizer('snapshot', action)(context)


class SnapshotActionsController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(SnapshotActionsController, self).__init__(*args, **kwargs)
        LOG.debug("SnapshotActionsController initialized")

    @wsgi.action('os-update_snapshot_status')
    def _update_snapshot_status(self, req, id, body):
        """Update database fields related to status of a snapshot.

           Intended for creation of snapshots, so snapshot state
           must start as 'creating' and be changed to 'available',
           'creating', or 'error'.
        """

        context = req.environ['cinder.context']
        authorize(context, 'update_snapshot_status')

        LOG.debug("body: %s" % body)
        try:
            status = body['os-update_snapshot_status']['status']
        except KeyError:
            msg = _("'status' must be specified.")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        # Allowed state transitions
        status_map = {'creating': ['creating', 'available', 'error'],
                      'deleting': ['deleting', 'error_deleting']}

        current_snapshot = db.snapshot_get(context, id)

        if current_snapshot['status'] not in status_map:
            msg = _("Snapshot status %(cur)s not allowed for "
                    "update_snapshot_status") % {
                        'cur': current_snapshot['status']}
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if status not in status_map[current_snapshot['status']]:
            msg = _("Provided snapshot status %(provided)s not allowed for "
                    "snapshot with status %(current)s.") % \
                {'provided': status,
                 'current': current_snapshot['status']}
            raise webob.exc.HTTPBadRequest(explanation=msg)

        update_dict = {'id': id,
                       'status': status}

        progress = body['os-update_snapshot_status'].get('progress', None)
        if progress:
            # This is expected to be a string like '73%'
            msg = _('progress must be an integer percentage')
            try:
                integer = int(progress[:-1])
            except ValueError:
                raise webob.exc.HTTPBadRequest(explanation=msg)
            if integer < 0 or integer > 100 or progress[-1] != '%':
                raise webob.exc.HTTPBadRequest(explanation=msg)

            update_dict.update({'progress': progress})

        LOG.info("Updating snapshot %(id)s with info %(dict)s" %
                 {'id': id, 'dict': update_dict})

        db.snapshot_update(context, id, update_dict)
        return webob.Response(status_int=202)


class Snapshot_actions(extensions.ExtensionDescriptor):
    """Enable snapshot manager actions."""

    name = "SnapshotActions"
    alias = "os-snapshot-actions"
    namespace = \
        "http://docs.openstack.org/volume/ext/snapshot-actions/api/v1.1"
    updated = "2013-07-16T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = SnapshotActionsController()
        extension = extensions.ControllerExtension(self,
                                                   'snapshots',
                                                   controller)
        return [extension]
