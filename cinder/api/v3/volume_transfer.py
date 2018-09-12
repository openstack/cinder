# Copyright 2018 FiberHome Telecommunication Technologies CO.,LTD
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

from oslo_log import log as logging
from oslo_utils import strutils
from six.moves import http_client
from webob import exc

from cinder.api import common
from cinder.api.contrib import volume_transfer as volume_transfer_v2
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import volume_transfer
from cinder.api import validation
from cinder import exception

LOG = logging.getLogger(__name__)


class VolumeTransferController(volume_transfer_v2.VolumeTransferController):
    """The transfer API controller for the OpenStack API V3."""

    def _get_transfers(self, req, is_detail):
        """Returns a list of transfers, transformed through view builder."""
        context = req.environ['cinder.context']
        req_version = req.api_version_request
        params = req.params.copy()
        marker = limit = offset = None
        if req_version.matches(mv.SUPPORT_TRANSFER_PAGINATION):
            marker, limit, offset = common.get_pagination_params(params)
            sort_keys, sort_dirs = common.get_sort_params(params)
        else:
            # NOTE(yikun): After microversion SUPPORT_TRANSFER_PAGINATION,
            # transfers list api use the ['created_at'], ['asc']
            # as default order, but we should keep the compatible in here.
            sort_keys, sort_dirs = ['created_at', 'id'], ['asc', 'asc']
        filters = params
        LOG.debug('Listing volume transfers')

        transfers = self.transfer_api.get_all(context, marker=marker,
                                              limit=limit,
                                              sort_keys=sort_keys,
                                              sort_dirs=sort_dirs,
                                              filters=filters,
                                              offset=offset)
        transfer_count = len(transfers)
        limited_list = common.limited(transfers, req)

        if is_detail:
            transfers = self._view_builder.detail_list(req, limited_list,
                                                       transfer_count)
        else:
            transfers = self._view_builder.summary_list(req, limited_list,
                                                        transfer_count)

        return transfers

    def index(self, req):
        """Returns a summary list of transfers."""
        return self._get_transfers(req, is_detail=False)

    def detail(self, req):
        """Returns a detailed list of transfers."""
        return self._get_transfers(req, is_detail=True)

    @wsgi.response(http_client.ACCEPTED)
    @validation.schema(volume_transfer.create, mv.BASE_VERSION,
                       mv.get_prior_version(mv.TRANSFER_WITH_SNAPSHOTS))
    @validation.schema(volume_transfer.create_v355, mv.TRANSFER_WITH_SNAPSHOTS)
    def create(self, req, body):
        """Create a new volume transfer."""
        LOG.debug('Creating new volume transfer %s', body)

        context = req.environ['cinder.context']
        transfer = body['transfer']

        volume_id = transfer['volume_id']

        name = transfer.get('name', None)
        if name is not None:
            name = name.strip()

        no_snapshots = strutils.bool_from_string(transfer.get('no_snapshots',
                                                              False))

        LOG.info("Creating transfer of volume %s", volume_id)

        try:
            new_transfer = self.transfer_api.create(context, volume_id, name,
                                                    no_snapshots=no_snapshots)
        # Not found exception will be handled at the wsgi level
        except exception.Invalid as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        transfer = self._view_builder.create(req,
                                             dict(new_transfer))
        return transfer


def create_resource():
    return wsgi.Resource(VolumeTransferController())
