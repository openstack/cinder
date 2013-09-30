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

import ast
import webob
from webob import exc

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import uuidutils
from cinder import utils
from cinder import volume as cinder_volume
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)


def _translate_attachment_detail_view(_context, vol):
    """Maps keys for attachment details view."""

    d = _translate_attachment_summary_view(_context, vol)

    # No additional data / lookups at the moment

    return d


def _translate_attachment_summary_view(_context, vol):
    """Maps keys for attachment summary view."""
    d = {}

    volume_id = vol['id']

    # NOTE(justinsb): We use the volume id as the id of the attachment object
    d['id'] = volume_id

    d['volume_id'] = volume_id
    d['server_id'] = vol['instance_uuid']
    d['host_name'] = vol['attached_host']
    if vol.get('mountpoint'):
        d['device'] = vol['mountpoint']

    return d


def _translate_volume_detail_view(context, vol, image_id=None):
    """Maps keys for volumes details view."""

    d = _translate_volume_summary_view(context, vol, image_id)

    # No additional data / lookups at the moment

    return d


def _translate_volume_summary_view(context, vol, image_id=None):
    """Maps keys for volumes summary view."""
    d = {}

    d['id'] = vol['id']
    d['status'] = vol['status']
    d['size'] = vol['size']
    d['availability_zone'] = vol['availability_zone']
    d['created_at'] = vol['created_at']

    # Need to form the string true/false explicitly here to
    # maintain our API contract
    if vol['bootable']:
        d['bootable'] = 'true'
    else:
        d['bootable'] = 'false'

    d['attachments'] = []
    if vol['attach_status'] == 'attached':
        attachment = _translate_attachment_detail_view(context, vol)
        d['attachments'].append(attachment)

    d['display_name'] = vol['display_name']
    d['display_description'] = vol['display_description']

    if vol['volume_type_id'] and vol.get('volume_type'):
        d['volume_type'] = vol['volume_type']['name']
    else:
        # TODO(bcwaldon): remove str cast once we use uuids
        d['volume_type'] = str(vol['volume_type_id'])

    d['snapshot_id'] = vol['snapshot_id']
    d['source_volid'] = vol['source_volid']

    if image_id:
        d['image_id'] = image_id

    LOG.audit(_("vol=%s"), vol, context=context)

    if vol.get('volume_metadata'):
        metadata = vol.get('volume_metadata')
        d['metadata'] = dict((item['key'], item['value']) for item in metadata)
    # avoid circular ref when vol is a Volume instance
    elif vol.get('metadata') and isinstance(vol.get('metadata'), dict):
        d['metadata'] = vol['metadata']
    else:
        d['metadata'] = {}

    return d


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
    elem.set('display_name')
    elem.set('bootable')
    elem.set('display_description')
    elem.set('volume_type')
    elem.set('snapshot_id')
    elem.set('source_volid')

    attachments = xmlutil.SubTemplateElement(elem, 'attachments')
    attachment = xmlutil.SubTemplateElement(attachments, 'attachment',
                                            selector='attachments')
    make_attachment(attachment)

    # Attach metadata node
    elem.append(common.MetadataTemplate())


volume_nsmap = {None: xmlutil.XMLNS_VOLUME_V1, 'atom': xmlutil.XMLNS_ATOM}


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

    def _extract_volume(self, node):
        """Marshal the volume attribute of a parsed request."""
        volume = {}
        volume_node = self.find_first_child_named(node, 'volume')

        attributes = ['display_name', 'display_description', 'size',
                      'volume_type', 'availability_zone', 'imageRef',
                      'snapshot_id', 'source_volid']
        for attr in attributes:
            if volume_node.getAttribute(attr):
                volume[attr] = volume_node.getAttribute(attr)

        metadata_node = self.find_first_child_named(volume_node, 'metadata')
        if metadata_node is not None:
            volume['metadata'] = self.extract_metadata(metadata_node)

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

    _visible_admin_metadata_keys = ['readonly', 'attached_mode']

    def __init__(self, ext_mgr):
        self.volume_api = cinder_volume.API()
        self.ext_mgr = ext_mgr
        super(VolumeController, self).__init__()

    def _add_visible_admin_metadata(self, context, volume):
        if context is None:
            return

        visible_admin_meta = {}

        if context.is_admin:
            volume_tmp = volume
        else:
            try:
                volume_tmp = self.volume_api.get(context.elevated(),
                                                 volume['id'])
            except Exception:
                return

        if volume_tmp.get('volume_admin_metadata'):
            for item in volume_tmp['volume_admin_metadata']:
                if item['key'] in self._visible_admin_metadata_keys:
                    visible_admin_meta[item['key']] = item['value']
        # avoid circular ref when volume is a Volume instance
        elif (volume_tmp.get('admin_metadata') and
                isinstance(volume_tmp.get('admin_metadata'), dict)):
            for key in self._visible_admin_metadata_keys:
                if key in volume_tmp['admin_metadata'].keys():
                    visible_admin_meta[key] = volume_tmp['admin_metadata'][key]

        if not visible_admin_meta:
            return

        # NOTE(zhiyan): update visible administration metadata to
        # volume metadata, administration metadata will rewrite existing key.
        if volume.get('volume_metadata'):
            orig_meta = list(volume.get('volume_metadata'))
            for item in orig_meta:
                if item['key'] in visible_admin_meta.keys():
                    item['value'] = visible_admin_meta.pop(item['key'])
            for key, value in visible_admin_meta.iteritems():
                orig_meta.append({'key': key, 'value': value})
            volume['volume_metadata'] = orig_meta
        # avoid circular ref when vol is a Volume instance
        elif (volume.get('metadata') and
                isinstance(volume.get('metadata'), dict)):
            volume['metadata'].update(visible_admin_meta)
        else:
            volume['metadata'] = visible_admin_meta

    @wsgi.serializers(xml=VolumeTemplate)
    def show(self, req, id):
        """Return data about the given volume."""
        context = req.environ['cinder.context']

        try:
            vol = self.volume_api.get(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        self._add_visible_admin_metadata(context, vol)

        return {'volume': _translate_volume_detail_view(context, vol)}

    def delete(self, req, id):
        """Delete a volume."""
        context = req.environ['cinder.context']

        LOG.audit(_("Delete volume with id: %s"), id, context=context)

        try:
            volume = self.volume_api.get(context, id)
            self.volume_api.delete(context, volume)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=VolumesTemplate)
    def index(self, req):
        """Returns a summary list of volumes."""
        return self._items(req, entity_maker=_translate_volume_summary_view)

    @wsgi.serializers(xml=VolumesTemplate)
    def detail(self, req):
        """Returns a detailed list of volumes."""
        return self._items(req, entity_maker=_translate_volume_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of volumes, transformed through entity_maker."""

        #pop out limit and offset , they are not search_opts
        search_opts = req.GET.copy()
        search_opts.pop('limit', None)
        search_opts.pop('offset', None)

        if 'metadata' in search_opts:
            search_opts['metadata'] = ast.literal_eval(search_opts['metadata'])

        context = req.environ['cinder.context']
        remove_invalid_options(context,
                               search_opts, self._get_volume_search_options())

        volumes = self.volume_api.get_all(context, marker=None, limit=None,
                                          sort_key='created_at',
                                          sort_dir='desc', filters=search_opts)

        volumes = [dict(vol.iteritems()) for vol in volumes]

        for volume in volumes:
            self._add_visible_admin_metadata(context, volume)

        limited_list = common.limited(volumes, req)
        res = [entity_maker(context, vol) for vol in limited_list]
        return {'volumes': res}

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

    @wsgi.serializers(xml=VolumeTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Creates a new volume."""
        if not self.is_valid_body(body, 'volume'):
            raise exc.HTTPUnprocessableEntity()

        LOG.debug('Create volume request body: %s', body)
        context = req.environ['cinder.context']
        volume = body['volume']

        kwargs = {}

        req_volume_type = volume.get('volume_type', None)
        if req_volume_type:
            try:
                if not uuidutils.is_uuid_like(req_volume_type):
                    kwargs['volume_type'] = \
                        volume_types.get_volume_type_by_name(
                            context, req_volume_type)
                else:
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
            # NOTE(jdg): misleading name "imageRef" as it's an image-id
            image_href = volume.get('imageRef')
            if image_href:
                image_uuid = self._image_uuid_from_href(image_href)
                kwargs['image_id'] = image_uuid

        kwargs['availability_zone'] = volume.get('availability_zone', None)

        new_volume = self.volume_api.create(context,
                                            size,
                                            volume.get('display_name'),
                                            volume.get('display_description'),
                                            **kwargs)

        # TODO(vish): Instance should be None at db layer instead of
        #             trying to lazy load, but for now we turn it into
        #             a dict to avoid an error.
        new_volume = dict(new_volume.iteritems())

        self._add_visible_admin_metadata(context, new_volume)

        retval = _translate_volume_detail_view(context, new_volume, image_uuid)

        return {'volume': retval}

    def _get_volume_search_options(self):
        """Return volume search options allowed by non-admin."""
        return ('display_name', 'status', 'metadata')

    @wsgi.serializers(xml=VolumeTemplate)
    def update(self, req, id, body):
        """Update a volume."""
        context = req.environ['cinder.context']

        if not body:
            raise exc.HTTPUnprocessableEntity()

        if 'volume' not in body:
            raise exc.HTTPUnprocessableEntity()

        volume = body['volume']
        update_dict = {}

        valid_update_keys = (
            'display_name',
            'display_description',
            'metadata',
        )

        for key in valid_update_keys:
            if key in volume:
                update_dict[key] = volume[key]

        try:
            volume = self.volume_api.get(context, id)
            self.volume_api.update(context, volume, update_dict)
        except exception.NotFound:
            raise exc.HTTPNotFound()

        volume.update(update_dict)

        self._add_visible_admin_metadata(context, volume)

        return {'volume': _translate_volume_detail_view(context, volume)}


def create_resource(ext_mgr):
    return wsgi.Resource(VolumeController(ext_mgr))


def remove_invalid_options(context, search_options, allowed_search_options):
    """Remove search options that are not valid for non-admin API/context."""
    if context.is_admin:
        # Allow all options
        return
    # Otherwise, strip out all unknown options
    unknown_options = [opt for opt in search_options
                       if opt not in allowed_search_options]
    bad_options = ", ".join(unknown_options)
    log_msg = _("Removing options '%(bad_options)s'"
                " from query") % {'bad_options': bad_options}
    LOG.debug(log_msg)
    for opt in unknown_options:
        del search_options[opt]
