#   Copyright 2012 OpenStack Foundation
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

import webob
from webob import exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import db
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import strutils
from cinder import volume


LOG = logging.getLogger(__name__)


class AdminController(wsgi.Controller):
    """Abstract base class for AdminControllers."""

    collection = None  # api collection to extend

    # FIXME(clayg): this will be hard to keep up-to-date
    # Concrete classes can expand or over-ride
    valid_status = set([
        'creating',
        'available',
        'deleting',
        'error',
        'error_deleting',
    ])

    def __init__(self, *args, **kwargs):
        super(AdminController, self).__init__(*args, **kwargs)
        # singular name of the resource
        self.resource_name = self.collection.rstrip('s')
        self.volume_api = volume.API()

    def _update(self, *args, **kwargs):
        raise NotImplementedError()

    def _get(self, *args, **kwargs):
        raise NotImplementedError()

    def _delete(self, *args, **kwargs):
        raise NotImplementedError()

    def validate_update(self, body):
        update = {}
        try:
            update['status'] = body['status']
        except (TypeError, KeyError):
            raise exc.HTTPBadRequest("Must specify 'status'")
        if update['status'] not in self.valid_status:
            raise exc.HTTPBadRequest("Must specify a valid status")
        return update

    def authorize(self, context, action_name):
        # e.g. "snapshot_admin_actions:reset_status"
        action = '%s_admin_actions:%s' % (self.resource_name, action_name)
        extensions.extension_authorizer('volume', action)(context)

    @wsgi.action('os-reset_status')
    def _reset_status(self, req, id, body):
        """Reset status on the resource."""
        context = req.environ['cinder.context']
        self.authorize(context, 'reset_status')
        update = self.validate_update(body['os-reset_status'])
        msg = _("Updating %(resource)s '%(id)s' with '%(update)r'")
        LOG.debug(msg, {'resource': self.resource_name, 'id': id,
                        'update': update})
        try:
            self._update(context, id, update)
        except exception.NotFound as e:
            raise exc.HTTPNotFound(e)
        return webob.Response(status_int=202)

    @wsgi.action('os-force_delete')
    def _force_delete(self, req, id, body):
        """Delete a resource, bypassing the check that it must be available."""
        context = req.environ['cinder.context']
        self.authorize(context, 'force_delete')
        try:
            resource = self._get(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        self._delete(context, resource, force=True)
        return webob.Response(status_int=202)


class VolumeAdminController(AdminController):
    """AdminController for Volumes."""

    collection = 'volumes'
    valid_status = AdminController.valid_status.union(
        set(['attaching', 'in-use', 'detaching']))

    def _update(self, *args, **kwargs):
        db.volume_update(*args, **kwargs)

    def _get(self, *args, **kwargs):
        return self.volume_api.get(*args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self.volume_api.delete(*args, **kwargs)

    def validate_update(self, body):
        update = super(VolumeAdminController, self).validate_update(body)
        if 'attach_status' in body:
            if body['attach_status'] not in ('detached', 'attached'):
                raise exc.HTTPBadRequest("Must specify a valid attach_status")
            update['attach_status'] = body['attach_status']
        return update

    @wsgi.action('os-force_detach')
    def _force_detach(self, req, id, body):
        """
        Roll back a bad detach after the volume been disconnected from
        the hypervisor.
        """
        context = req.environ['cinder.context']
        self.authorize(context, 'force_detach')
        try:
            volume = self._get(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        self.volume_api.terminate_connection(context, volume,
                                             {}, force=True)
        self.volume_api.detach(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-migrate_volume')
    def _migrate_volume(self, req, id, body):
        """Migrate a volume to the specified host."""
        context = req.environ['cinder.context']
        self.authorize(context, 'migrate_volume')
        try:
            volume = self._get(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        params = body['os-migrate_volume']
        host = params['host']
        force_host_copy = params.get('force_host_copy', False)
        if isinstance(force_host_copy, basestring):
            try:
                force_host_copy = strutils.bool_from_string(force_host_copy,
                                                            strict=True)
            except ValueError:
                raise exc.HTTPBadRequest("Bad value for 'force_host_copy'")
        elif not isinstance(force_host_copy, bool):
            raise exc.HTTPBadRequest("'force_host_copy' not string or bool")
        self.volume_api.migrate_volume(context, volume, host, force_host_copy)
        return webob.Response(status_int=202)

    @wsgi.action('os-migrate_volume_completion')
    def _migrate_volume_completion(self, req, id, body):
        """Migrate a volume to the specified host."""
        context = req.environ['cinder.context']
        self.authorize(context, 'migrate_volume_completion')
        try:
            volume = self._get(context, id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        try:
            params = body['os-migrate_volume_completion']
        except KeyError:
            raise exc.HTTPBadRequest("Body does not contain "
                                     "'os-migrate_volume_completion'")
        try:
            new_volume_id = params['new_volume']
        except KeyError:
            raise exc.HTTPBadRequest("Must specify 'new_volume'")
        try:
            new_volume = self._get(context, new_volume_id)
        except exception.NotFound:
            raise exc.HTTPNotFound()
        error = params.get('error', False)
        ret = self.volume_api.migrate_volume_completion(context, volume,
                                                        new_volume, error)
        return {'save_volume_id': ret}


class SnapshotAdminController(AdminController):
    """AdminController for Snapshots."""

    collection = 'snapshots'

    def _update(self, *args, **kwargs):
        db.snapshot_update(*args, **kwargs)

    def _get(self, *args, **kwargs):
        return self.volume_api.get_snapshot(*args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self.volume_api.delete_snapshot(*args, **kwargs)


class Admin_actions(extensions.ExtensionDescriptor):
    """Enable admin actions."""

    name = "AdminActions"
    alias = "os-admin-actions"
    namespace = "http://docs.openstack.org/volume/ext/admin-actions/api/v1.1"
    updated = "2012-08-25T00:00:00+00:00"

    def get_controller_extensions(self):
        exts = []
        for class_ in (VolumeAdminController, SnapshotAdminController):
            controller = class_()
            extension = extensions.ControllerExtension(
                self, class_.collection, controller)
            exts.append(extension)
        return exts
