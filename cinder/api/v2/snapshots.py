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

"""The volumes snapshots api."""

from oslo_log import log as logging
from oslo_utils import strutils
import webob
from webob import exc

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder.api import xmlutil
from cinder import exception
from cinder.i18n import _, _LI
from cinder import utils
from cinder import volume


LOG = logging.getLogger(__name__)


def _translate_snapshot_detail_view(context, snapshot):
    """Maps keys for snapshots details view."""

    d = _translate_snapshot_summary_view(context, snapshot)

    # NOTE(gagupta): No additional data / lookups at the moment
    return d


def _translate_snapshot_summary_view(context, snapshot):
    """Maps keys for snapshots summary view."""
    d = {}

    d['id'] = snapshot['id']
    d['created_at'] = snapshot['created_at']
    d['name'] = snapshot['display_name']
    d['description'] = snapshot['display_description']
    d['volume_id'] = snapshot['volume_id']
    d['status'] = snapshot['status']
    d['size'] = snapshot['volume_size']

    if snapshot.get('metadata') and isinstance(snapshot.get('metadata'),
                                               dict):
        d['metadata'] = snapshot['metadata']
    else:
        d['metadata'] = {}
    return d


def make_snapshot(elem):
    elem.set('id')
    elem.set('status')
    elem.set('size')
    elem.set('created_at')
    elem.set('name')
    elem.set('description')
    elem.set('volume_id')
    elem.append(common.MetadataTemplate())


class SnapshotTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshot', selector='snapshot')
        make_snapshot(root)
        return xmlutil.MasterTemplate(root, 1)


class SnapshotsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('snapshots')
        elem = xmlutil.SubTemplateElement(root, 'snapshot',
                                          selector='snapshots')
        make_snapshot(elem)
        return xmlutil.MasterTemplate(root, 1)


class SnapshotsController(wsgi.Controller):
    """The Snapshots API controller for the OpenStack API."""

    def __init__(self, ext_mgr=None):
        self.volume_api = volume.API()
        self.ext_mgr = ext_mgr
        super(SnapshotsController, self).__init__()

    @wsgi.serializers(xml=SnapshotTemplate)
    def show(self, req, id):
        """Return data about the given snapshot."""
        context = req.environ['cinder.context']

        try:
            snapshot = self.volume_api.get_snapshot(context, id)
            req.cache_db_snapshot(snapshot)
        except exception.NotFound:
            msg = _("Snapshot could not be found")
            raise exc.HTTPNotFound(explanation=msg)

        return {'snapshot': _translate_snapshot_detail_view(context, snapshot)}

    def delete(self, req, id):
        """Delete a snapshot."""
        context = req.environ['cinder.context']

        LOG.info(_LI("Delete snapshot with id: %s"), id, context=context)

        try:
            snapshot = self.volume_api.get_snapshot(context, id)
            self.volume_api.delete_snapshot(context, snapshot)
        except exception.NotFound:
            msg = _("Snapshot could not be found")
            raise exc.HTTPNotFound(explanation=msg)

        return webob.Response(status_int=202)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def index(self, req):
        """Returns a summary list of snapshots."""
        return self._items(req, entity_maker=_translate_snapshot_summary_view)

    @wsgi.serializers(xml=SnapshotsTemplate)
    def detail(self, req):
        """Returns a detailed list of snapshots."""
        return self._items(req, entity_maker=_translate_snapshot_detail_view)

    def _items(self, req, entity_maker):
        """Returns a list of snapshots, transformed through entity_maker."""
        context = req.environ['cinder.context']

        # pop out limit and offset , they are not search_opts
        search_opts = req.GET.copy()
        search_opts.pop('limit', None)
        search_opts.pop('offset', None)

        # filter out invalid option
        allowed_search_options = ('status', 'volume_id', 'name')
        utils.remove_invalid_filter_options(context, search_opts,
                                            allowed_search_options)

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in search_opts:
            search_opts['display_name'] = search_opts['name']
            del search_opts['name']

        snapshots = self.volume_api.get_all_snapshots(context,
                                                      search_opts=search_opts)
        limited_list = common.limited(snapshots, req)
        req.cache_db_snapshots(limited_list)
        res = [entity_maker(context, snapshot) for snapshot in limited_list]
        return {'snapshots': res}

    @wsgi.response(202)
    @wsgi.serializers(xml=SnapshotTemplate)
    def create(self, req, body):
        """Creates a new snapshot."""
        kwargs = {}
        context = req.environ['cinder.context']

        if not self.is_valid_body(body, 'snapshot'):
            msg = (_("Missing required element '%s' in request body") %
                   'snapshot')
            raise exc.HTTPBadRequest(explanation=msg)

        snapshot = body['snapshot']
        kwargs['metadata'] = snapshot.get('metadata', None)

        try:
            volume_id = snapshot['volume_id']
        except KeyError:
            msg = _("'volume_id' must be specified")
            raise exc.HTTPBadRequest(explanation=msg)

        try:
            volume = self.volume_api.get(context, volume_id)
        except exception.NotFound:
            msg = _("Volume could not be found")
            raise exc.HTTPNotFound(explanation=msg)
        force = snapshot.get('force', False)
        msg = _LI("Create snapshot from volume %s")
        LOG.info(msg, volume_id, context=context)

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in snapshot:
            snapshot['display_name'] = snapshot.get('name')
            del snapshot['name']

        if not utils.is_valid_boolstr(force):
            msg = _("Invalid value '%s' for force. ") % force
            raise exception.InvalidParameterValue(err=msg)

        if strutils.bool_from_string(force):
            new_snapshot = self.volume_api.create_snapshot_force(
                context,
                volume,
                snapshot.get('display_name'),
                snapshot.get('description'),
                **kwargs)
        else:
            new_snapshot = self.volume_api.create_snapshot(
                context,
                volume,
                snapshot.get('display_name'),
                snapshot.get('description'),
                **kwargs)
        req.cache_db_snapshot(new_snapshot)

        retval = _translate_snapshot_detail_view(context, new_snapshot)

        return {'snapshot': retval}

    @wsgi.serializers(xml=SnapshotTemplate)
    def update(self, req, id, body):
        """Update a snapshot."""
        context = req.environ['cinder.context']

        if not body:
            msg = _("Missing request body")
            raise exc.HTTPBadRequest(explanation=msg)

        if 'snapshot' not in body:
            msg = (_("Missing required element '%s' in request body") %
                   'snapshot')
            raise exc.HTTPBadRequest(explanation=msg)

        snapshot = body['snapshot']
        update_dict = {}

        valid_update_keys = (
            'name',
            'description',
            'display_name',
            'display_description',
        )

        # NOTE(thingee): v2 API allows name instead of display_name
        if 'name' in snapshot:
            snapshot['display_name'] = snapshot['name']
            del snapshot['name']

        # NOTE(thingee): v2 API allows description instead of
        # display_description
        if 'description' in snapshot:
            snapshot['display_description'] = snapshot['description']
            del snapshot['description']

        for key in valid_update_keys:
            if key in snapshot:
                update_dict[key] = snapshot[key]

        try:
            snapshot = self.volume_api.get_snapshot(context, id)
            self.volume_api.update_snapshot(context, snapshot, update_dict)
        except exception.NotFound:
            msg = _("Snapshot could not be found")
            raise exc.HTTPNotFound(explanation=msg)

        snapshot.update(update_dict)
        req.cache_db_snapshot(snapshot)

        return {'snapshot': _translate_snapshot_detail_view(context, snapshot)}


def create_resource(ext_mgr):
    return wsgi.Resource(SnapshotsController(ext_mgr))
