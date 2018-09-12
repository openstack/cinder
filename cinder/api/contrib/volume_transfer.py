# Copyright 2011 OpenStack Foundation
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

from oslo_log import log as logging
from six.moves import http_client
import webob
from webob import exc

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.schemas import volume_transfer
from cinder.api import validation
from cinder.api.views import transfers as transfer_view
from cinder import exception
from cinder import transfer as transferAPI

LOG = logging.getLogger(__name__)


class VolumeTransferController(wsgi.Controller):
    """The Volume Transfer API controller for the OpenStack API."""

    _view_builder_class = transfer_view.ViewBuilder

    def __init__(self):
        self.transfer_api = transferAPI.API()
        super(VolumeTransferController, self).__init__()

    def show(self, req, id):
        """Return data about active transfers."""
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        transfer = self.transfer_api.get(context, transfer_id=id)

        return self._view_builder.detail(req, transfer)

    def index(self, req):
        """Returns a summary list of transfers."""
        return self._get_transfers(req, is_detail=False)

    def detail(self, req):
        """Returns a detailed list of transfers."""
        return self._get_transfers(req, is_detail=True)

    def _get_transfers(self, req, is_detail):
        """Returns a list of transfers, transformed through view builder."""
        context = req.environ['cinder.context']
        filters = req.params.copy()
        LOG.debug('Listing volume transfers')
        transfers = self.transfer_api.get_all(context, filters=filters,
                                              sort_keys=['created_at', 'id'],
                                              sort_dirs=['asc', 'asc'])
        transfer_count = len(transfers)
        limited_list = common.limited(transfers, req)

        if is_detail:
            transfers = self._view_builder.detail_list(req, limited_list,
                                                       transfer_count)
        else:
            transfers = self._view_builder.summary_list(req, limited_list,
                                                        transfer_count)

        return transfers

    @wsgi.response(http_client.ACCEPTED)
    @validation.schema(volume_transfer.create)
    def create(self, req, body):
        """Create a new volume transfer."""
        LOG.debug('Creating new volume transfer %s', body)

        context = req.environ['cinder.context']
        transfer = body['transfer']

        volume_id = transfer['volume_id']

        name = transfer.get('name', None)
        if name is not None:
            name = name.strip()

        LOG.info("Creating transfer of volume %s",
                 volume_id)

        try:
            new_transfer = self.transfer_api.create(context, volume_id, name,
                                                    no_snapshots=False)
        # Not found exception will be handled at the wsgi level
        except exception.InvalidVolume as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        transfer = self._view_builder.create(req,
                                             dict(new_transfer))
        return transfer

    @wsgi.response(http_client.ACCEPTED)
    @validation.schema(volume_transfer.accept)
    def accept(self, req, id, body):
        """Accept a new volume transfer."""
        transfer_id = id
        LOG.debug('Accepting volume transfer %s', transfer_id)

        context = req.environ['cinder.context']
        accept = body['accept']
        auth_key = accept['auth_key']

        LOG.info("Accepting transfer %s", transfer_id)

        try:
            accepted_transfer = self.transfer_api.accept(context, transfer_id,
                                                         auth_key)
        except exception.VolumeSizeExceedsAvailableQuota as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.msg, headers={'Retry-After': '0'})
        except exception.InvalidVolume as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        transfer = \
            self._view_builder.summary(req,
                                       dict(accepted_transfer))
        return transfer

    def delete(self, req, id):
        """Delete a transfer."""
        context = req.environ['cinder.context']

        LOG.info("Delete transfer with id: %s", id)

        # Not found exception will be handled at the wsgi level
        self.transfer_api.delete(context, transfer_id=id)
        return webob.Response(status_int=http_client.ACCEPTED)


class Volume_transfer(extensions.ExtensionDescriptor):
    """Volume transfer management support."""

    name = "VolumeTransfer"
    alias = "os-volume-transfer"
    updated = "2013-05-29T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(Volume_transfer.alias,
                                           VolumeTransferController(),
                                           collection_actions={'detail':
                                                               'GET'},
                                           member_actions={'accept': 'POST'})
        resources.append(res)
        return resources
