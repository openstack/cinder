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
import webob
from webob import exc

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.views import transfers as transfer_view
from cinder.api import xmlutil
from cinder import exception
from cinder.i18n import _, _LI
from cinder import transfer as transferAPI
from cinder import utils

LOG = logging.getLogger(__name__)


def make_transfer(elem):
    elem.set('id')
    elem.set('volume_id')
    elem.set('created_at')
    elem.set('name')
    elem.set('auth_key')


class TransferTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('transfer', selector='transfer')
        make_transfer(root)
        alias = Volume_transfer.alias
        namespace = Volume_transfer.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class TransfersTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('transfers')
        elem = xmlutil.SubTemplateElement(root, 'transfer',
                                          selector='transfers')
        make_transfer(elem)
        alias = Volume_transfer.alias
        namespace = Volume_transfer.namespace
        return xmlutil.MasterTemplate(root, 1, nsmap={alias: namespace})


class CreateDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = utils.safe_minidom_parse_string(string)
        transfer = self._extract_transfer(dom)
        return {'body': {'transfer': transfer}}

    def _extract_transfer(self, node):
        transfer = {}
        transfer_node = self.find_first_child_named(node, 'transfer')

        attributes = ['volume_id', 'name']

        for attr in attributes:
            if transfer_node.getAttribute(attr):
                transfer[attr] = transfer_node.getAttribute(attr)
        return transfer


class AcceptDeserializer(wsgi.MetadataXMLDeserializer):
    def default(self, string):
        dom = utils.safe_minidom_parse_string(string)
        transfer = self._extract_transfer(dom)
        return {'body': {'accept': transfer}}

    def _extract_transfer(self, node):
        transfer = {}
        transfer_node = self.find_first_child_named(node, 'accept')

        attributes = ['auth_key']

        for attr in attributes:
            if transfer_node.getAttribute(attr):
                transfer[attr] = transfer_node.getAttribute(attr)
        return transfer


class VolumeTransferController(wsgi.Controller):
    """The Volume Transfer API controller for the OpenStack API."""

    _view_builder_class = transfer_view.ViewBuilder

    def __init__(self):
        self.transfer_api = transferAPI.API()
        super(VolumeTransferController, self).__init__()

    @wsgi.serializers(xml=TransferTemplate)
    def show(self, req, id):
        """Return data about active transfers."""
        context = req.environ['cinder.context']

        try:
            transfer = self.transfer_api.get(context, transfer_id=id)
        except exception.TransferNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)

        return self._view_builder.detail(req, transfer)

    @wsgi.serializers(xml=TransfersTemplate)
    def index(self, req):
        """Returns a summary list of transfers."""
        return self._get_transfers(req, is_detail=False)

    @wsgi.serializers(xml=TransfersTemplate)
    def detail(self, req):
        """Returns a detailed list of transfers."""
        return self._get_transfers(req, is_detail=True)

    def _get_transfers(self, req, is_detail):
        """Returns a list of transfers, transformed through view builder."""
        context = req.environ['cinder.context']
        filters = req.params.copy()
        LOG.debug('Listing volume transfers')
        transfers = self.transfer_api.get_all(context, filters=filters)
        transfer_count = len(transfers)
        limited_list = common.limited(transfers, req)

        if is_detail:
            transfers = self._view_builder.detail_list(req, limited_list,
                                                       transfer_count)
        else:
            transfers = self._view_builder.summary_list(req, limited_list,
                                                        transfer_count)

        return transfers

    @wsgi.response(202)
    @wsgi.serializers(xml=TransferTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Create a new volume transfer."""
        LOG.debug('Creating new volume transfer %s', body)
        if not self.is_valid_body(body, 'transfer'):
            raise exc.HTTPBadRequest()

        context = req.environ['cinder.context']

        try:
            transfer = body['transfer']
            volume_id = transfer['volume_id']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)

        name = transfer.get('name', None)

        LOG.info(_LI("Creating transfer of volume %s"),
                 volume_id,
                 context=context)

        try:
            new_transfer = self.transfer_api.create(context, volume_id, name)
        except exception.InvalidVolume as error:
            raise exc.HTTPBadRequest(explanation=error.msg)
        except exception.VolumeNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)

        transfer = self._view_builder.create(req,
                                             dict(new_transfer.iteritems()))
        return transfer

    @wsgi.response(202)
    @wsgi.serializers(xml=TransferTemplate)
    @wsgi.deserializers(xml=AcceptDeserializer)
    def accept(self, req, id, body):
        """Accept a new volume transfer."""
        transfer_id = id
        LOG.debug('Accepting volume transfer %s', transfer_id)
        if not self.is_valid_body(body, 'accept'):
            raise exc.HTTPBadRequest()

        context = req.environ['cinder.context']

        try:
            accept = body['accept']
            auth_key = accept['auth_key']
        except KeyError:
            msg = _("Incorrect request body format")
            raise exc.HTTPBadRequest(explanation=msg)

        LOG.info(_LI("Accepting transfer %s"), transfer_id,
                 context=context)

        try:
            accepted_transfer = self.transfer_api.accept(context, transfer_id,
                                                         auth_key)
        except exception.VolumeSizeExceedsAvailableQuota as error:
            raise exc.HTTPRequestEntityTooLarge(
                explanation=error.msg, headers={'Retry-After': 0})
        except exception.InvalidVolume as error:
            raise exc.HTTPBadRequest(explanation=error.msg)

        transfer = \
            self._view_builder.summary(req,
                                       dict(accepted_transfer.iteritems()))
        return transfer

    def delete(self, req, id):
        """Delete a transfer."""
        context = req.environ['cinder.context']

        LOG.info(_LI("Delete transfer with id: %s"), id, context=context)

        try:
            self.transfer_api.delete(context, transfer_id=id)
        except exception.TransferNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)
        return webob.Response(status_int=202)


class Volume_transfer(extensions.ExtensionDescriptor):
    """Volume transfer management support."""

    name = "VolumeTransfer"
    alias = "os-volume-transfer"
    namespace = "http://docs.openstack.org/volume/ext/volume-transfer/" + \
                "api/v1.1"
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
