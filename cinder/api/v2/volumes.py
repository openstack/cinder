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


from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import uuidutils
import webob
from webob import exc

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api.v2.views import volumes as volume_views
from cinder.api import xmlutil
from cinder import consistencygroup as consistencygroupAPI
from cinder import exception
from cinder.i18n import _, _LI
from cinder.image import glance
from cinder import utils
from cinder import volume as cinder_volume
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types


query_volume_filters_opt = cfg.ListOpt('query_volume_filters',
                                       default=['name', 'status', 'metadata',
                                                'availability_zone'],
                                       help="Volume filter options which "
                                            "non-admin user could use to "
                                            "query volumes. Default values "
                                            "are: ['name', 'status', "
                                            "'metadata', 'availability_zone']")

CONF = cfg.CONF
CONF.register_opt(query_volume_filters_opt)

LOG = logging.getLogger(__name__)
SCHEDULER_HINTS_NAMESPACE =\
    "http://docs.openstack.org/block-service/ext/scheduler-hints/api/v2"


def make_attachment(elem):
    elem.set('id')
    elem.set('attachment_id')
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
    elem.set('bootable')
    elem.set('description')
    elem.set('volume_type')
    elem.set('snapshot_id')
    elem.set('source_volid')
    elem.set('consistencygroup_id')
    elem.set('multiattach')

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
                      'image_id', 'snapshot_id', 'source_volid',
                      'consistencygroup_id']
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
        self.volume_api = cinder_volume.API()
        self.consistencygroup_api = consistencygroupAPI.API()
        self.ext_mgr = ext_mgr
        super(VolumeController, self).__init__()

    @wsgi.serializers(xml=VolumeTemplate)
    def show(self, req, id):
        """Return data about the given volume."""
        context = req.environ['cinder.context']

        try:
            vol = self.volume_api.get(context, id, viewable_admin_meta=True)
            req.cache_db_volume(vol)
        except exception.VolumeNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)

        utils.add_visible_admin_metadata(vol)

        return self._view_builder.detail(req, vol)

    def delete(self, req, id):
        """Delete a volume."""
        context = req.environ['cinder.context']

        LOG.info(_LI("Delete volume with id: %s"), id, context=context)

        try:
            volume = self.volume_api.get(context, id)
            self.volume_api.delete(context, volume)
        except exception.VolumeNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)
        except exception.VolumeAttached:
            msg = _("Volume cannot be deleted while in attached state")
            raise exc.HTTPBadRequest(explanation=msg)
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
        marker, limit, offset = common.get_pagination_params(params)
        sort_keys, sort_dirs = common.get_sort_params(params)
        filters = params

        utils.remove_invalid_filter_options(context,
                                            filters,
                                            self._get_volume_filter_options())

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in sort_keys:
            sort_keys[sort_keys.index('name')] = 'display_name'

        if 'name' in filters:
            filters['display_name'] = filters['name']
            del filters['name']

        self.volume_api.check_volume_filters(filters)
        volumes = self.volume_api.get_all(context, marker, limit,
                                          sort_keys=sort_keys,
                                          sort_dirs=sort_dirs,
                                          filters=filters,
                                          viewable_admin_meta=True,
                                          offset=offset)

        volumes = [dict(vol) for vol in volumes]

        for volume in volumes:
            utils.add_visible_admin_metadata(volume)

        req.cache_db_volumes(volumes)

        if is_detail:
            volumes = self._view_builder.detail_list(req, volumes)
        else:
            volumes = self._view_builder.summary_list(req, volumes)
        return volumes

    def _image_uuid_from_ref(self, image_ref, context):
        # If the image ref was generated by nova api, strip image_ref
        # down to an id.
        image_uuid = None
        try:
            image_uuid = image_ref.split('/').pop()
        except AttributeError:
            msg = _("Invalid imageRef provided.")
            raise exc.HTTPBadRequest(explanation=msg)

        image_service = glance.get_default_image_service()

        # First see if this is an actual image ID
        if uuidutils.is_uuid_like(image_uuid):
            try:
                image = image_service.show(context, image_uuid)
                if 'id' in image:
                    return image['id']
            except Exception:
                # Pass and see if there is a matching image name
                pass

        # Could not find by ID, check if it is an image name
        try:
            params = {'filters': {'name': image_ref}}
            images = list(image_service.detail(context, **params))
            if len(images) > 1:
                msg = _("Multiple matches found for '%s', use an ID to be more"
                        " specific.") % image_ref
                raise exc.HTTPConflict(msg)
            for img in images:
                return img['id']
        except Exception:
            # Pass and let default not found error handling take care of it
            pass

        msg = _("Invalid image identifier or unable to "
                "access requested image.")
        raise exc.HTTPBadRequest(explanation=msg)

    @wsgi.response(202)
    @wsgi.serializers(xml=VolumeTemplate)
    @wsgi.deserializers(xml=CreateDeserializer)
    def create(self, req, body):
        """Creates a new volume."""
        self.assert_valid_body(body, 'volume')

        LOG.debug('Create volume request body: %s', body)
        context = req.environ['cinder.context']
        volume = body['volume']

        kwargs = {}
        self.validate_name_and_description(volume)

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in volume:
            volume['display_name'] = volume.pop('name')

        # NOTE(thingee): v2 API allows description instead of
        #                display_description
        if 'description' in volume:
            volume['display_description'] = volume.pop('description')

        if 'image_id' in volume:
            volume['imageRef'] = volume.get('image_id')
            del volume['image_id']

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
            except exception.VolumeTypeNotFound as error:
                raise exc.HTTPNotFound(explanation=error.msg)

        kwargs['metadata'] = volume.get('metadata', None)

        snapshot_id = volume.get('snapshot_id')
        if snapshot_id is not None:
            try:
                kwargs['snapshot'] = self.volume_api.get_snapshot(context,
                                                                  snapshot_id)
            except exception.SnapshotNotFound as error:
                raise exc.HTTPNotFound(explanation=error.msg)
        else:
            kwargs['snapshot'] = None

        source_volid = volume.get('source_volid')
        if source_volid is not None:
            try:
                kwargs['source_volume'] = \
                    self.volume_api.get_volume(context,
                                               source_volid)
            except exception.VolumeNotFound as error:
                raise exc.HTTPNotFound(explanation=error.msg)
        else:
            kwargs['source_volume'] = None

        source_replica = volume.get('source_replica')
        if source_replica is not None:
            try:
                src_vol = self.volume_api.get_volume(context,
                                                     source_replica)
                if src_vol['replication_status'] == 'disabled':
                    explanation = _('source volume id:%s is not'
                                    ' replicated') % source_replica
                    raise exc.HTTPBadRequest(explanation=explanation)
                kwargs['source_replica'] = src_vol
            except exception.VolumeNotFound as error:
                raise exc.HTTPNotFound(explanation=error.msg)
        else:
            kwargs['source_replica'] = None

        consistencygroup_id = volume.get('consistencygroup_id')
        if consistencygroup_id is not None:
            try:
                kwargs['consistencygroup'] = \
                    self.consistencygroup_api.get(context,
                                                  consistencygroup_id)
            except exception.ConsistencyGroupNotFound as error:
                raise exc.HTTPNotFound(explanation=error.msg)
        else:
            kwargs['consistencygroup'] = None

        size = volume.get('size', None)
        if size is None and kwargs['snapshot'] is not None:
            size = kwargs['snapshot']['volume_size']
        elif size is None and kwargs['source_volume'] is not None:
            size = kwargs['source_volume']['size']
        elif size is None and kwargs['source_replica'] is not None:
            size = kwargs['source_replica']['size']

        LOG.info(_LI("Create volume of %s GB"), size, context=context)

        if self.ext_mgr.is_loaded('os-image-create'):
            image_ref = volume.get('imageRef')
            if image_ref is not None:
                image_uuid = self._image_uuid_from_ref(image_ref, context)
                kwargs['image_id'] = image_uuid

        kwargs['availability_zone'] = volume.get('availability_zone', None)
        kwargs['scheduler_hints'] = volume.get('scheduler_hints', None)
        multiattach = volume.get('multiattach', False)
        kwargs['multiattach'] = multiattach

        new_volume = self.volume_api.create(context,
                                            size,
                                            volume.get('display_name'),
                                            volume.get('display_description'),
                                            **kwargs)

        # TODO(vish): Instance should be None at db layer instead of
        #             trying to lazy load, but for now we turn it into
        #             a dict to avoid an error.
        new_volume = dict(new_volume)
        retval = self._view_builder.detail(req, new_volume)

        return retval

    def _get_volume_filter_options(self):
        """Return volume search options allowed by non-admin."""
        return CONF.query_volume_filters

    @wsgi.serializers(xml=VolumeTemplate)
    def update(self, req, id, body):
        """Update a volume."""
        context = req.environ['cinder.context']

        if not body:
            msg = _("Missing request body")
            raise exc.HTTPBadRequest(explanation=msg)

        if 'volume' not in body:
            msg = _("Missing required element '%s' in request body") % 'volume'
            raise exc.HTTPBadRequest(explanation=msg)

        volume = body['volume']
        update_dict = {}

        valid_update_keys = (
            'name',
            'description',
            'display_name',
            'display_description',
            'metadata',
        )

        for key in valid_update_keys:
            if key in volume:
                update_dict[key] = volume[key]

        self.validate_name_and_description(update_dict)

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in update_dict:
            update_dict['display_name'] = update_dict.pop('name')

        # NOTE(thingee): v2 API allows description instead of
        #                display_description
        if 'description' in update_dict:
            update_dict['display_description'] = update_dict.pop('description')

        try:
            volume = self.volume_api.get(context, id, viewable_admin_meta=True)
            volume_utils.notify_about_volume_usage(context, volume,
                                                   'update.start')
            self.volume_api.update(context, volume, update_dict)
        except exception.VolumeNotFound as error:
            raise exc.HTTPNotFound(explanation=error.msg)

        volume.update(update_dict)

        utils.add_visible_admin_metadata(volume)

        volume_utils.notify_about_volume_usage(context, volume,
                                               'update.end')

        return self._view_builder.detail(req, volume)


def create_resource(ext_mgr):
    return wsgi.Resource(VolumeController(ext_mgr))
