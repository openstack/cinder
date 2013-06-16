# Copyright 2011 Justin Santa Barbara
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

"""The volumes api."""


import webob
from webob import exc

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api.v2.views import volumes as volume_views
from cinder.api import xmlutil
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import uuidutils
from cinder import utils
from cinder import volume
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)
SCHEDULER_HINTS_NAMESPACE =\
    "http://docs.openstack.org/block-service/ext/scheduler-hints/api/v2"


def make_attachment(elem):
    elem.set('id')
    elem.set('server_id')
    elem.set('host_name')
    elem.set('volume_id')
    elem.set('device')


def make_volume(elem):
    elem.set('id')
    elem.set('status')
    elem.set('size')
    elem.set('availability_zone')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')
    elem.set('volume_type')
    elem.set('snapshot_id')
    elem.set('source_volid')

    attachments = xmlutil.SubTemplateElement(elem, 'attachments')
    attachment = xmlutil.SubTemplateElement(attachments, 'attachment',
                                            selector='attachments')
    make_attachment(attachment)

    # Attach metadata node
    elem.append(common.MetadataTemplate())


volume_nsmap = {None: xmlutil.XMLNS_VOLUME_V2, 'atom': xmlutil.XMLNS_ATOM}


class VolumeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volume', selector='volume')
        make_volume(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=volume_nsmap)


class VolumesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('volumes')
        elem = xmlutil.SubTemplateElement(root, 'volume', selector='volumes')
        make_volume(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=volume_nsmap)


class CommonDeserializer(wsgi.MetadataXMLDeserializer):
    """Common deserializer to handle xml-formatted volume requests.

       Handles standard volume attributes as well as the optional metadata
       attribute
    """

    metadata_deserializer = common.MetadataXMLDeserializer()

    def _extract_scheduler_hints(self, volume_node):
        """Marshal the scheduler hints attribute of a parsed request."""
        node =\
            self.find_first_child_named_in_namespace(volume_node,
                                                     SCHEDULER_HINTS_NAMESPACE,
                                                     "scheduler_hints")
        if node:
            scheduler_hints = {}
            for child in self.extract_elements(node):
                scheduler_hints.setdefault(child.nodeName, [])
                value = self.extract_text(child).strip()
                scheduler_hints[child.nodeName].append(value)
            return scheduler_hints
        else:
            return None

    def _extract_volume(self, node):
        """Marshal the volume attribute of a parsed request."""
        volume = {}
        volume_node = self.find_first_child_named(node, 'volume')

        attributes = ['name', 'description', 'size',
                      'volume_type', 'availability_zone', 'imageRef',
                      'snapshot_id', 'source_volid']
        for attr in attributes:
            if volume_node.getAttribute(attr):
                volume[attr] = volume_node.getAttribute(attr)

        metadata_node = self.find_first_child_named(volume_node, 'metadata')
        if metadata_node is not None:
            volume['metadata'] = self.extract_metadata(metadata_node)

        scheduler_hints = self._extract_scheduler_hints(volume_node)
        if scheduler_hints:
            volume['scheduler_hints'] = scheduler_hints

        return volume


class CreateDeserializer(CommonDeserializer):
    """Deserializer to handle xml-formatted create volume requests.

       Handles standard volume attributes as well as the optional metadata
       attribute
    """

    def default(self, string):
        """Deserialize an xml-formatted volume create request."""
        dom = utils.safe_minidom_parse_string(string)
        volume = self._extract_volume(dom)
        return {'body': {'volume': volume}}


class VolumeController(wsgi.Controller):
    """The Volumes API controller for the OpenStack API."""

    _view_builder_class = volume_views.ViewBuilder

    def __init__(self, ext_mgr):
        self.volume_api = volume.API()
        self.ext_mgr = ext_mgr
        super(VolumeController, self).__init__()

    @wsgi.serializers(xml=VolumeTemplate)
    def show(self, req, id):
        """Return data about the given volume."""
        context = req.environ['cinder.context']

        try:
            vol = self.volume_api.get(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        return self._view_builder.detail(req, vol)

    def delete(self, req, id):
        """Delete a volume."""
        context = req.environ['cinder.context']

        LOG.audit(_("Delete volume with id: %s"), id, context=context)

        try:
            volume = self.volume_api.get(context, id)
            self.volume_api.delete(context, volume)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        except exception.VolumeAttached:
            explanation = 'Volume cannot be deleted while in attached state'
            raise exc.HTTPBadRequest(explanation=explanation)
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=VolumesTemplate)
    def index(self, req):
        """Returns a summary list of volumes."""
        return self._get_volumes(req, is_detail=False)

    @wsgi.serializers(xml=VolumesTemplate)
    def detail(self, req):
        """Returns a detailed list of volumes."""
        return self._get_volumes(req, is_detail=True)

    def _get_volumes(self, req, is_detail):
        """Returns a list of volumes, transformed through view builder."""

        context = req.environ['cinder.context']

        params = req.params.copy()
        marker = params.pop('marker', None)
        limit = params.pop('limit', None)
        sort_key = params.pop('sort_key', 'created_at')
        sort_dir = params.pop('sort_dir', 'desc')
        params.pop('offset', None)
        filters = params

        remove_invalid_options(context,
                               filters, self._get_volume_filter_options())

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in filters:
            filters['display_name'] = filters['name']
            del filters['name']

        volumes = self.volume_api.get_all(context, marker, limit, sort_key,
                                          sort_dir, filters)
        limited_list = common.limited(volumes, req)

        if is_detail:
            volumes = self._view_builder.detail_list(req, limited_list)
        else:
            volumes = self._view_builder.summary_list(req, limited_list)
        return volumes

    def _image_uuid_from_href(self, image_href):
        # If the image href was generated by nova api, strip image_href
        # down to an id.
        try:
            image_uuid = image_href.split('/').pop()
        except (TypeError, AttributeError):
            msg = _("Invalid imageRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        if not uuidutils.is_uuid_like(image_uuid):
            msg = _("Invalid imageRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        return image_uuid

    @wsgi.response(202)
    @wsgi.serializers(xml=VolumeTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Creates a new volume."""
        if not self.is_valid_body(body, 'volume'):
            raise exc.HTTPBadRequest()

        LOG.debug('Create volume request body: %s', body)
        context = req.environ['cinder.context']
        volume = body['volume']

        kwargs = {}

        # NOTE(thingee): v2 API allows name instead of display_name
        if volume.get('name'):
            volume['display_name'] = volume.get('name')
            del volume['name']

        # NOTE(thingee): v2 API allows description instead of description
        if volume.get('description'):
            volume['display_description'] = volume.get('description')
            del volume['description']

        req_volume_type = volume.get('volume_type', None)
        if req_volume_type:
            try:
                kwargs['volume_type'] = volume_types.get_volume_type(
                    context, req_volume_type)
            except exception.VolumeTypeNotFound:
                explanation = 'Volume type not found.'
                raise exc.HTTPNotFound(explanation=explanation)

        kwargs['metadata'] = volume.get('metadata', None)

        snapshot_id = volume.get('snapshot_id')
        if snapshot_id is not None:
            kwargs['snapshot'] = self.volume_api.get_snapshot(context,
                                                              snapshot_id)
        else:
            kwargs['snapshot'] = None

        source_volid = volume.get('source_volid')
        if source_volid is not None:
            kwargs['source_volume'] = self.volume_api.get_volume(context,
                                                                 source_volid)
        else:
            kwargs['source_volume'] = None

        size = volume.get('size', None)
        if size is None and kwargs['snapshot'] is not None:
            size = kwargs['snapshot']['volume_size']
        elif size is None and kwargs['source_volume'] is not None:
            size = kwargs['source_volume']['size']

        LOG.audit(_("Create volume of %s GB"), size, context=context)

        image_href = None
        image_uuid = None
        if self.ext_mgr.is_loaded('os-image-create'):
            image_href = volume.get('imageRef')
            if image_href:
                image_uuid = self._image_uuid_from_href(image_href)
                kwargs['image_id'] = image_uuid

        kwargs['availability_zone'] = volume.get('availability_zone', None)
        kwargs['scheduler_hints'] = volume.get('scheduler_hints', None)

        new_volume = self.volume_api.create(context,
                                            size,
                                            volume.get('display_name'),
                                            volume.get('display_description'),
                                            **kwargs)

        # TODO(vish): Instance should be None at db layer instead of
        #             trying to lazy load, but for now we turn it into
        #             a dict to avoid an error.
        retval = self._view_builder.summary(req, dict(new_volume.iteritems()))

        return retval

    def _get_volume_filter_options(self):
        """Return volume search options allowed by non-admin."""
        return ('name', 'status')

    @wsgi.serializers(xml=VolumeTemplate)
    def update(self, req, id, body):
        """Update a volume."""
        context = req.environ['cinder.context']

        if not body:
            raise exc.HTTPBadRequest()

        if 'volume' not in body:
            raise exc.HTTPBadRequest()

        volume = body['volume']
        update_dict = {}

        valid_update_keys = (
            'name',
            'description',
            'metadata',
        )

        for key in valid_update_keys:
            if key in volume:
                update_dict[key] = volume[key]

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in update_dict:
            update_dict['display_name'] = update_dict['name']
            del update_dict['name']

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'description' in update_dict:
            update_dict['display_description'] = update_dict['description']
            del update_dict['description']

        try:
            volume = self.volume_api.get(context, id)
            self.volume_api.update(context, volume, update_dict)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        volume.update(update_dict)

        return self._view_builder.detail(req, volume)


def create_resource(ext_mgr):
    return wsgi.Resource(VolumeController(ext_mgr))


def remove_invalid_options(context, filters, allowed_search_options):
    """Remove search options that are not valid for non-admin API/context."""
    if context.is_admin:
        # Allow all options
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in filters
                       if opt not in allowed_search_options]
    bad_options = ", ".join(unknown_options)
    log_msg = _("Removing options '%s' from query") % bad_options
    LOG.debug(log_msg)
    for opt in unknown_options:
        del filters[opt]
