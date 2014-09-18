#   Copyright 2014 IBM Corp.
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

from oslo.config import cfg
from webob import exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.v2.views import volumes as volume_views
from cinder.api.v2 import volumes
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import uuidutils
from cinder import utils
from cinder import volume as cinder_volume
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
authorize = extensions.extension_authorizer('volume', 'volume_manage')


class VolumeManageController(wsgi.Controller):
    """The /os-volume-manage controller for the OpenStack API."""

    _view_builder_class = volume_views.ViewBuilder

    def __init__(self, *args, **kwargs):
        super(VolumeManageController, self).__init__(*args, **kwargs)
        self.volume_api = cinder_volume.API()

    @wsgi.response(202)
    @wsgi.serializers(xml=volumes.VolumeTemplate)
    @wsgi.deserializers(xml=volumes.CreateDeserializer)
    def create(self, req, body):
        """Instruct Cinder to manage a storage object.

        Manages an existing backend storage object (e.g. a Linux logical
        volume or a SAN disk) by creating the Cinder objects required to manage
        it, and possibly renaming the backend storage object
        (driver dependent)

        From an API perspective, this operation behaves very much like a
        volume creation operation, except that properties such as image,
        snapshot and volume references don't make sense, because we are taking
        an existing storage object into Cinder management.

        Required HTTP Body:

        {
         'volume':
          {
           'host': <Cinder host on which the existing storage resides>,
           'ref':  <Driver-specific reference to the existing storage object>,
          }
        }

        See the appropriate Cinder drivers' implementations of the
        manage_volume method to find out the accepted format of 'ref'.

        This API call will return with an error if any of the above elements
        are missing from the request, or if the 'host' element refers to a
        cinder host that is not registered.

        The volume will later enter the error state if it is discovered that
        'ref' is bad.

        Optional elements to 'volume' are:
            name               A name for the new volume.
            description        A description for the new volume.
            volume_type        ID or name of a volume type to associate with
                               the new Cinder volume.  Does not necessarily
                               guarantee that the managed volume will have the
                               properties described in the volume_type.  The
                               driver may choose to fail if it identifies that
                               the specified volume_type is not compatible with
                               the backend storage object.
            metadata           Key/value pairs to be associated with the new
                               volume.
            availability_zone  The availability zone to associate with the new
                               volume.
            bootable           If set to True, marks the volume as bootable.
        """
        context = req.environ['cinder.context']
        authorize(context)

        if not self.is_valid_body(body, 'volume'):
            msg = _("Missing required element '%s' in request body") % 'volume'
            raise exc.HTTPBadRequest(explanation=msg)

        volume = body['volume']

        # Check that the required keys are present, return an error if they
        # are not.
        required_keys = set(['ref', 'host'])
        missing_keys = list(required_keys - set(volume.keys()))

        if missing_keys:
            msg = _("The following elements are required: %s") % \
                ', '.join(missing_keys)
            raise exc.HTTPBadRequest(explanation=msg)

        LOG.debug('Manage volume request body: %s', body)

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
                msg = _("Volume type not found.")
                raise exc.HTTPNotFound(explanation=msg)
        else:
            kwargs['volume_type'] = {}

        kwargs['name'] = volume.get('name', None)
        kwargs['description'] = volume.get('description', None)
        kwargs['metadata'] = volume.get('metadata', None)
        kwargs['availability_zone'] = volume.get('availability_zone', None)
        kwargs['bootable'] = volume.get('bootable', False)
        try:
            new_volume = self.volume_api.manage_existing(context,
                                                         volume['host'],
                                                         volume['ref'],
                                                         **kwargs)
        except exception.ServiceNotFound:
            msg = _("Service not found.")
            raise exc.HTTPNotFound(explanation=msg)

        new_volume = dict(new_volume.iteritems())
        utils.add_visible_admin_metadata(new_volume)

        return self._view_builder.detail(req, new_volume)


class Volume_manage(extensions.ExtensionDescriptor):
    """Allows existing backend storage to be 'managed' by Cinder."""

    name = 'VolumeManage'
    alias = 'os-volume-manage'
    namespace = ('http://docs.openstack.org/volume/ext/'
                 'os-volume-manage/api/v1')
    updated = '2014-02-10T00:00:00+00:00'

    def get_resources(self):
        controller = VolumeManageController()
        res = extensions.ResourceExtension(Volume_manage.alias,
                                           controller)
        return [res]
