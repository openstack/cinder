# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack Foundation
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

"""The volume type & volume types extra specs extension."""

from cinder.api.openstack import wsgi
from cinder.api.views import types as views_types
from cinder.volume import volume_types


class VolumeTypesController(wsgi.Controller):
    """The volume types API controller for the OpenStack API."""

    _view_builder_class = views_types.ViewBuilder

    def index(self, req):
        """Returns the list of volume types."""
        context = req.environ['cinder.context']
        vol_types = volume_types.get_all_types(context)
        vol_types = list(vol_types.values())
        req.cache_resource(vol_types, name='types')
        return self._view_builder.index(req, vol_types)

    def show(self, req, id):
        """Return a single volume type item."""
        context = req.environ['cinder.context']

        # Not found exception will be handled at the wsgi level
        vol_type = volume_types.get_volume_type(context, id)
        req.cache_resource(vol_type, name='types')

        return self._view_builder.show(req, vol_type)


def create_resource():
    return wsgi.Resource(VolumeTypesController())
