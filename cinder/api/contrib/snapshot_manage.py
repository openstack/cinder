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

from oslo_config import cfg
from oslo_log import log as logging
from webob import exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.v2 import snapshots
from cinder.api.views import snapshots as snapshot_views
from cinder import exception
from cinder.i18n import _
from cinder import volume as cinder_volume

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
authorize = extensions.extension_authorizer('snapshot', 'snapshot_manage')


class SnapshotManageController(wsgi.Controller):
    """The /os-snapshot-manage controller for the OpenStack API."""

    _view_builder_class = snapshot_views.ViewBuilder

    def __init__(self, *args, **kwargs):
        super(SnapshotManageController, self).__init__(*args, **kwargs)
        self.volume_api = cinder_volume.API()

    @wsgi.response(202)
    @wsgi.serializers(xml=snapshots.SnapshotTemplate)
    def create(self, req, body):
        """Instruct Cinder to manage a storage snapshot object.

        Manages an existing backend storage snapshot object (e.g. a Linux
        logical volume or a SAN disk) by creating the Cinder objects required
        to manage it, and possibly renaming the backend storage snapshot object
        (driver dependent).

        From an API perspective, this operation behaves very much like a
        snapshot creation operation.

        Required HTTP Body:

        {
         "snapshot":
          {
           "volume_id": <Cinder volume already exists in volume backend>,
           "ref":  <Driver-specific reference to the existing storage object>,
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

        Optional elements to 'snapshot' are:
            name               A name for the new snapshot.
            description        A description for the new snapshot.
            metadata           Key/value pairs to be associated with the new
                               snapshot.
        """
        context = req.environ['cinder.context']
        authorize(context)

        if not self.is_valid_body(body, 'snapshot'):
            msg = _("Missing required element snapshot in request body.")
            raise exc.HTTPBadRequest(explanation=msg)

        snapshot = body['snapshot']

        # Check that the required keys are present, return an error if they
        # are not.
        required_keys = ('ref', 'volume_id')
        missing_keys = set(required_keys) - set(snapshot.keys())

        if missing_keys:
            msg = _("The following elements are required: "
                    "%s") % ', '.join(missing_keys)
            raise exc.HTTPBadRequest(explanation=msg)

        # Check whether volume exists
        volume_id = snapshot['volume_id']
        try:
            volume = self.volume_api.get(context, volume_id)
        except exception.VolumeNotFound:
            msg = _("Volume: %s could not be found.") % volume_id
            raise exc.HTTPNotFound(explanation=msg)

        LOG.debug('Manage snapshot request body: %s', body)

        snapshot_parameters = {}

        snapshot_parameters['metadata'] = snapshot.get('metadata', None)
        snapshot_parameters['description'] = snapshot.get('description', None)
        # NOTE(wanghao) if name in request body, we are overriding the 'name'
        snapshot_parameters['name'] = snapshot.get('name',
                                                   snapshot.get('display_name')
                                                   )

        try:
            new_snapshot = self.volume_api.manage_existing_snapshot(
                context,
                snapshot['ref'],
                volume,
                **snapshot_parameters)
        except exception.ServiceNotFound:
            msg = _("Service %s not found.") % CONF.volume_topic
            raise exc.HTTPNotFound(explanation=msg)

        return self._view_builder.detail(req, new_snapshot)


class Snapshot_manage(extensions.ExtensionDescriptor):
    """Allows existing backend storage to be 'managed' by Cinder."""

    name = 'SnapshotManage'
    alias = 'os-snapshot-manage'
    namespace = ('http://docs.openstack.org/volume/ext/'
                 'os-snapshot-manage/api/v1')
    updated = '2014-12-31T00:00:00+00:00'

    def get_resources(self):
        controller = SnapshotManageController()
        return [extensions.ResourceExtension(Snapshot_manage.alias,
                                             controller)]
