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

from cinder.api.contrib import resource_common_manage
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.schemas import snapshot_manage
from cinder.api import validation
from cinder.api.views import manageable_snapshots as list_manageable_view
from cinder.api.views import snapshots as snapshot_views
from cinder.policies import manageable_snapshots as policy
from cinder import volume as cinder_volume

LOG = logging.getLogger(__name__)


class SnapshotManageController(wsgi.Controller):
    """The /os-snapshot-manage controller for the OpenStack API."""

    _view_builder_class = snapshot_views.ViewBuilder

    def __init__(self, *args, **kwargs):
        super(SnapshotManageController, self).__init__(*args, **kwargs)
        self.volume_api = cinder_volume.API()
        self._list_manageable_view = list_manageable_view.ViewBuilder()

    @wsgi.response(HTTPStatus.ACCEPTED)
    @validation.schema(snapshot_manage.create)
    def create(self, req, body):
        """Instruct Cinder to manage a storage snapshot object.

        Manages an existing backend storage snapshot object (e.g. a Linux
        logical volume or a SAN disk) by creating the Cinder objects required
        to manage it, and possibly renaming the backend storage snapshot object
        (driver dependent).

        From an API perspective, this operation behaves very much like a
        snapshot creation operation.

        Required HTTP Body:

        .. code-block:: json

         {
           "snapshot":
           {
             "volume_id": "<Cinder volume already exists in volume backend>",
             "ref":
                "<Driver-specific reference to the existing storage object>"
           }
         }

        See the appropriate Cinder drivers' implementations of the
        manage_snapshot method to find out the accepted format of 'ref'.
        For example,in LVM driver, it will be the logic volume name of snapshot
        which you want to manage.

        This API call will return with an error if any of the above elements
        are missing from the request, or if the 'volume_id' element refers to
        a cinder volume that could not be found.

        The snapshot will later enter the error state if it is discovered that
        'ref' is bad.

        Optional elements to 'snapshot' are::

         name           A name for the new snapshot.
         description    A description for the new snapshot.
         metadata       Key/value pairs to be associated with the new snapshot.

        """
        context = req.environ['cinder.context']

        snapshot = body['snapshot']
        # Check whether volume exists
        volume_id = snapshot['volume_id']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, volume_id)
        context.authorize(policy.MANAGE_POLICY, target_obj=volume)

        LOG.debug('Manage snapshot request body: %s', body)

        snapshot_parameters = {}

        snapshot_parameters['metadata'] = snapshot.get('metadata', None)
        snapshot_parameters['description'] = snapshot.get('description', None)
        snapshot_parameters['name'] = snapshot.get('name')

        # Not found exception will be handled at the wsgi level
        new_snapshot = self.volume_api.manage_existing_snapshot(
            context,
            snapshot['ref'],
            volume,
            **snapshot_parameters)

        return self._view_builder.detail(req, new_snapshot)

    @wsgi.extends
    def index(self, req):
        """Returns a summary list of snapshots available to manage."""
        context = req.environ['cinder.context']
        context.authorize(policy.LIST_MANAGEABLE_POLICY)
        return resource_common_manage.get_manageable_resources(
            req, False, self.volume_api.get_manageable_snapshots,
            self._list_manageable_view)

    @wsgi.extends
    def detail(self, req):
        """Returns a detailed list of snapshots available to manage."""
        context = req.environ['cinder.context']
        context.authorize(policy.LIST_MANAGEABLE_POLICY)
        return resource_common_manage.get_manageable_resources(
            req, True, self.volume_api.get_manageable_snapshots,
            self._list_manageable_view)


class Snapshot_manage(extensions.ExtensionDescriptor):
    """Allows existing backend storage to be 'managed' by Cinder."""

    name = 'SnapshotManage'
    alias = 'os-snapshot-manage'
    updated = '2014-12-31T00:00:00+00:00'

    def get_resources(self):
        controller = SnapshotManageController()
        return [extensions.ResourceExtension(Snapshot_manage.alias,
                                             controller,
                                             collection_actions=
                                             {'detail': 'GET'})]
