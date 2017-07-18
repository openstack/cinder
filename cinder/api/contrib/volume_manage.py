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

from oslo_log import log as logging
from six.moves import http_client

from cinder.api import common
from cinder.api.contrib import resource_common_manage
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.api.v2.views import volumes as volume_views
from cinder.api.views import manageable_volumes as list_manageable_view
from cinder import exception
from cinder.i18n import _
from cinder import utils
from cinder import volume as cinder_volume
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)
authorize_manage = extensions.extension_authorizer('volume', 'volume_manage')
authorize_list_manageable = extensions.extension_authorizer('volume',
                                                            'list_manageable')


class VolumeManageController(wsgi.Controller):
    """The /os-volume-manage controller for the OpenStack API."""

    _view_builder_class = volume_views.ViewBuilder

    def __init__(self, *args, **kwargs):
        super(VolumeManageController, self).__init__(*args, **kwargs)
        self.volume_api = cinder_volume.API()
        self._list_manageable_view = list_manageable_view.ViewBuilder()

    @wsgi.response(http_client.ACCEPTED)
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

        .. code-block:: json

         {
           "volume": {
             "host": "<Cinder host on which the existing storage resides>",
             "cluster": "<Cinder cluster on which the storage resides>",
             "ref": "<Driver-specific reference to existing storage object>"
           }
         }

        See the appropriate Cinder drivers' implementations of the
        manage_volume method to find out the accepted format of 'ref'.

        This API call will return with an error if any of the above elements
        are missing from the request, or if the 'host' element refers to a
        cinder host that is not registered.

        The volume will later enter the error state if it is discovered that
        'ref' is bad.

        Optional elements to 'volume' are::

         name               A name for the new volume.
         description        A description for the new volume.
         volume_type        ID or name of a volume type to associate with
                            the new Cinder volume. Does not necessarily
                            guarantee that the managed volume will have the
                            properties described in the volume_type. The
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
        authorize_manage(context)

        self.assert_valid_body(body, 'volume')

        volume = body['volume']
        self.validate_name_and_description(volume)

        # Check that the required keys are present, return an error if they
        # are not.
        if 'ref' not in volume:
            raise exception.MissingRequired(element='ref')

        cluster_name, host = common.get_cluster_host(req, volume, '3.16')

        LOG.debug('Manage volume request body: %s', body)

        kwargs = {}
        req_volume_type = volume.get('volume_type', None)
        if req_volume_type:
            try:
                kwargs['volume_type'] = volume_types.get_by_name_or_id(
                    context, req_volume_type)
            except exception.VolumeTypeNotFound:
                msg = _("Cannot find requested '%s' "
                        "volume type") % req_volume_type
                raise exception.InvalidVolumeType(reason=msg)
        else:
            kwargs['volume_type'] = {}

        kwargs['name'] = volume.get('name', None)
        kwargs['description'] = volume.get('description', None)
        kwargs['metadata'] = volume.get('metadata', None)
        kwargs['availability_zone'] = volume.get('availability_zone', None)
        kwargs['bootable'] = utils.get_bool_param('bootable', volume)

        utils.check_metadata_properties(kwargs['metadata'])

        try:
            new_volume = self.volume_api.manage_existing(context,
                                                         host,
                                                         cluster_name,
                                                         volume['ref'],
                                                         **kwargs)
        except exception.ServiceNotFound:
            msg = _("Host '%s' not found") % volume['host']
            raise exception.ServiceUnavailable(message=msg)

        utils.add_visible_admin_metadata(new_volume)

        return self._view_builder.detail(req, new_volume)

    @wsgi.extends
    def index(self, req):
        """Returns a summary list of volumes available to manage."""
        context = req.environ['cinder.context']
        authorize_list_manageable(context)
        return resource_common_manage.get_manageable_resources(
            req, False, self.volume_api.get_manageable_volumes,
            self._list_manageable_view)

    @wsgi.extends
    def detail(self, req):
        """Returns a detailed list of volumes available to manage."""
        context = req.environ['cinder.context']
        authorize_list_manageable(context)
        return resource_common_manage.get_manageable_resources(
            req, True, self.volume_api.get_manageable_volumes,
            self._list_manageable_view)


class Volume_manage(extensions.ExtensionDescriptor):
    """Allows existing backend storage to be 'managed' by Cinder."""

    name = 'VolumeManage'
    alias = 'os-volume-manage'
    updated = '2014-02-10T00:00:00+00:00'

    def get_resources(self):
        controller = VolumeManageController()
        res = extensions.ResourceExtension(Volume_manage.alias,
                                           controller,
                                           collection_actions=
                                           {'detail': 'GET'})
        return [res]
