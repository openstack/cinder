#   Copyright 2015 Huawei Technologies Co., Ltd.
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
from http import HTTPStatus

from oslo_log import log as logging
import webob
from webob import exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import exception
from cinder.policies import manageable_snapshots as policy
from cinder import volume

LOG = logging.getLogger(__name__)


class SnapshotUnmanageController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(SnapshotUnmanageController, self).__init__(*args, **kwargs)
        self.volume_api = volume.API()

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-unmanage')
    def unmanage(self, req, id, body):
        """Stop managing a snapshot.

        This action is very much like a delete, except that a different
        method (unmanage) is called on the Cinder driver.  This has the effect
        of removing the snapshot from Cinder management without actually
        removing the backend storage object associated with it.

        There are no required parameters.

        A Not Found error is returned if the specified snapshot does not exist.
        """
        context = req.environ['cinder.context']

        LOG.info("Unmanage snapshot with id: %s", id)

        try:
            snapshot = self.volume_api.get_snapshot(context, id)
            context.authorize(policy.UNMANAGE_POLICY, target_obj=snapshot)
            self.volume_api.delete_snapshot(context, snapshot,
                                            unmanage_only=True)
        # Not found exception will be handled at the wsgi level
        except exception.InvalidSnapshot as ex:
            raise exc.HTTPBadRequest(explanation=ex.msg)
        return webob.Response(status_int=HTTPStatus.ACCEPTED)


class Snapshot_unmanage(extensions.ExtensionDescriptor):
    """Enable volume unmanage operation."""

    name = "SnapshotUnmanage"
    alias = "os-snapshot-unmanage"
    updated = "2014-12-31T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = SnapshotUnmanageController()
        extension = extensions.ControllerExtension(self, 'snapshots',
                                                   controller)
        return [extension]
