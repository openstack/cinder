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

from oslo_log import log as logging
import oslo_messaging as messaging
import webob
from webob import exc

from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import backup
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import rpc
from cinder import utils
from cinder import volume


LOG = logging.getLogger(__name__)


class AdminController(wsgi.Controller):
    """Abstract base class for AdminControllers."""

    collection = None  # api collection to extend

    # FIXME(clayg): this will be hard to keep up-to-date
    # Concrete classes can expand or over-ride
    valid_status = set(['creating',
                        'available',
                        'deleting',
                        'error',
                        'error_deleting', ])

    def __init__(self, *args, **kwargs):
        super(AdminController, self).__init__(*args, **kwargs)
        # singular name of the resource
        self.resource_name = self.collection.rstrip('s')
        self.volume_api = volume.API()
        self.backup_api = backup.API()

    def _update(self, *args, **kwargs):
        raise NotImplementedError()

    def _get(self, *args, **kwargs):
        raise NotImplementedError()

    def _delete(self, *args, **kwargs):
        raise NotImplementedError()

    def validate_update(self, body):
        update = {}
        try:
            update['status'] = body['status'].lower()
        except (TypeError, KeyError):
            raise exc.HTTPBadRequest(explanation=_("Must specify 'status'"))
        if update['status'] not in self.valid_status:
            raise exc.HTTPBadRequest(
                explanation=_("Must specify a valid status"))
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
        msg = "Updating %(resource)s '%(id)s' with '%(update)r'"
        LOG.debug(msg, {'resource': self.resource_name, 'id': id,
                        'update': update})

        notifier_info = dict(id=id, update=update)
        notifier = rpc.get_notifier('volumeStatusUpdate')
        notifier.info(context, self.collection + '.reset_status.start',
                      notifier_info)

        try:
            self._update(context, id, update)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)

        notifier.info(context, self.collection + '.reset_status.end',
                      notifier_info)

        return webob.Response(status_int=202)

    @wsgi.action('os-force_delete')
    def _force_delete(self, req, id, body):
        """Delete a resource, bypassing the check that it must be available."""
        context = req.environ['cinder.context']
        self.authorize(context, 'force_delete')
        try:
            resource = self._get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)
        self._delete(context, resource, force=True)
        return webob.Response(status_int=202)


class VolumeAdminController(AdminController):
    """AdminController for Volumes."""

    collection = 'volumes'

    # FIXME(jdg): We're appending additional valid status
    # entries to the set we declare in the parent class
    # this doesn't make a ton of sense, we should probably
    # look at the structure of this whole process again
    # Perhaps we don't even want any definitions in the abstract
    # parent class?
    valid_status = AdminController.valid_status.union(
        ('attaching', 'in-use', 'detaching', 'maintenance'))

    valid_attach_status = ('detached', 'attached',)
    valid_migration_status = ('migrating', 'error',
                              'success', 'completing',
                              'none', 'starting',)

    def _update(self, *args, **kwargs):
        db.volume_update(*args, **kwargs)

    def _get(self, *args, **kwargs):
        return self.volume_api.get(*args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self.volume_api.delete(*args, **kwargs)

    def validate_update(self, body):
        update = {}
        status = body.get('status', None)
        attach_status = body.get('attach_status', None)
        migration_status = body.get('migration_status', None)

        valid = False
        if status:
            valid = True
            update = super(VolumeAdminController, self).validate_update(body)

        if attach_status:
            valid = True
            update['attach_status'] = attach_status.lower()
            if update['attach_status'] not in self.valid_attach_status:
                raise exc.HTTPBadRequest(
                    explanation=_("Must specify a valid attach status"))

        if migration_status:
            valid = True
            update['migration_status'] = migration_status.lower()
            if update['migration_status'] not in self.valid_migration_status:
                raise exc.HTTPBadRequest(
                    explanation=_("Must specify a valid migration status"))
            if update['migration_status'] == 'none':
                update['migration_status'] = None

        if not valid:
            raise exc.HTTPBadRequest(
                explanation=_("Must specify 'status', 'attach_status' "
                              "or 'migration_status' for update."))
        return update

    @wsgi.action('os-force_detach')
    def _force_detach(self, req, id, body):
        """Roll back a bad detach after the volume been disconnected."""
        context = req.environ['cinder.context']
        self.authorize(context, 'force_detach')
        try:
            volume = self._get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)
        try:
            connector = body['os-force_detach'].get('connector', None)
        except KeyError:
            raise webob.exc.HTTPBadRequest(
                explanation=_("Must specify 'connector'."))
        try:
            self.volume_api.terminate_connection(context, volume, connector)
        except exception.VolumeBackendAPIException as error:
            msg = _("Unable to terminate volume connection from backend.")
            raise webob.exc.HTTPInternalServerError(explanation=msg)

        attachment_id = body['os-force_detach'].get('attachment_id', None)

        try:
            self.volume_api.detach(context, volume, attachment_id)
        except messaging.RemoteError as error:
            if error.exc_type in ['VolumeAttachmentNotFound',
                                  'InvalidVolume']:
                msg = "Error force detaching volume - %(err_type)s: " \
                      "%(err_msg)s" % {'err_type': error.exc_type,
                                       'err_msg': error.value}
                raise webob.exc.HTTPBadRequest(explanation=msg)
            else:
                # There are also few cases where force-detach call could fail
                # due to db or volume driver errors. These errors shouldn't
                # be exposed to the user and in such cases it should raise
                # 500 error.
                raise
        return webob.Response(status_int=202)

    @wsgi.action('os-migrate_volume')
    def _migrate_volume(self, req, id, body):
        """Migrate a volume to the specified host."""
        context = req.environ['cinder.context']
        self.authorize(context, 'migrate_volume')
        try:
            volume = self._get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)
        params = body['os-migrate_volume']
        try:
            host = params['host']
        except KeyError:
            raise exc.HTTPBadRequest(explanation=_("Must specify 'host'."))
        force_host_copy = utils.get_bool_param('force_host_copy', params)
        lock_volume = utils.get_bool_param('lock_volume', params)
        self.volume_api.migrate_volume(context, volume, host, force_host_copy,
                                       lock_volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-migrate_volume_completion')
    def _migrate_volume_completion(self, req, id, body):
        """Complete an in-progress migration."""
        context = req.environ['cinder.context']
        self.authorize(context, 'migrate_volume_completion')
        try:
            volume = self._get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)
        params = body['os-migrate_volume_completion']
        try:
            new_volume_id = params['new_volume']
        except KeyError:
            raise exc.HTTPBadRequest(
                explanation=_("Must specify 'new_volume'"))
        try:
            new_volume = self._get(context, new_volume_id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)
        error = params.get('error', False)
        ret = self.volume_api.migrate_volume_completion(context, volume,
                                                        new_volume, error)
        return {'save_volume_id': ret}

    @wsgi.action('os-enable_replication')
    def _enable_replication(self, req, id, body):
        """Enable/Re-enable replication on replciation capable volume.

        Admin only method, used primarily for cases like disable/re-enable
        replication process on a replicated volume for maintenance or testing
        """

        context = req.environ['cinder.context']
        self.authorize(context, 'enable_replication')
        try:
            volume = self._get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)
        self.volume_api.enable_replication(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-disable_replication')
    def _disable_replication(self, req, id, body):
        """Disable replication on replciation capable volume.

        Admin only method, used to instruct a backend to
        disable replication process to a replicated volume.
        """

        context = req.environ['cinder.context']
        self.authorize(context, 'disable_replication')
        try:
            volume = self._get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)
        self.volume_api.disable_replication(context, volume)
        return webob.Response(status_int=202)

    @wsgi.action('os-failover_replication')
    def _failover_replication(self, req, id, body):
        """Failover a replicating volume to it's secondary

        Admin only method, used to force a fail-over to
        a replication target. Optional secondary param to
        indicate what device to promote in case of multiple
        replication targets.
        """

        context = req.environ['cinder.context']
        self.authorize(context, 'failover_replication')
        try:
            volume = self._get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)
        secondary = body['os-failover_replication'].get('secondary', None)
        self.volume_api.failover_replication(context, volume, secondary)
        return webob.Response(status_int=202)

    @wsgi.action('os-list_replication_targets')
    def _list_replication_targets(self, req, id, body):
        """Show replication targets for the specified host.

        Admin only method, used to display configured
        replication target devices for the specified volume.

        """

        # TODO(jdg): We'll want an equivalent type of command
        # to querie a backend host (show configuration for a
        # specified backend), but priority here is for
        # a volume as it's likely to be more useful.
        context = req.environ['cinder.context']
        self.authorize(context, 'list_replication_targets')
        try:
            volume = self._get(context, id)
        except exception.VolumeNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)

        # Expected response is a dict is a dict with unkonwn
        # keys.  Should be of the form:
        #    {'volume_id': xx, 'replication_targets':[{k: v, k1: v1...}]}
        return self.volume_api.list_replication_targets(context, volume)


class SnapshotAdminController(AdminController):
    """AdminController for Snapshots."""

    collection = 'snapshots'

    def _update(self, *args, **kwargs):
        context = args[0]
        snapshot_id = args[1]
        fields = args[2]
        snapshot = objects.Snapshot.get_by_id(context, snapshot_id)
        snapshot.update(fields)
        snapshot.save()

    def _get(self, *args, **kwargs):
        return self.volume_api.get_snapshot(*args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self.volume_api.delete_snapshot(*args, **kwargs)


class BackupAdminController(AdminController):
    """AdminController for Backups."""

    collection = 'backups'

    valid_status = set(['available',
                        'error'
                        ])

    def _get(self, *args, **kwargs):
        return self.backup_api.get(*args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self.backup_api.delete(*args, **kwargs)

    @wsgi.action('os-reset_status')
    def _reset_status(self, req, id, body):
        """Reset status on the resource."""
        context = req.environ['cinder.context']
        self.authorize(context, 'reset_status')
        update = self.validate_update(body['os-reset_status'])
        msg = "Updating %(resource)s '%(id)s' with '%(update)r'"
        LOG.debug(msg, {'resource': self.resource_name, 'id': id,
                        'update': update})

        notifier_info = {'id': id, 'update': update}
        notifier = rpc.get_notifier('backupStatusUpdate')
        notifier.info(context, self.collection + '.reset_status.start',
                      notifier_info)

        try:
            self.backup_api.reset_status(context=context, backup_id=id,
                                         status=update['status'])
        except exception.BackupNotFound as e:
            raise exc.HTTPNotFound(explanation=e.msg)
        return webob.Response(status_int=202)


class Admin_actions(extensions.ExtensionDescriptor):
    """Enable admin actions."""

    name = "AdminActions"
    alias = "os-admin-actions"
    namespace = "http://docs.openstack.org/volume/ext/admin-actions/api/v1.1"
    updated = "2012-08-25T00:00:00+00:00"

    def get_controller_extensions(self):
        exts = []
        for class_ in (VolumeAdminController, SnapshotAdminController,
                       BackupAdminController):
            controller = class_()
            extension = extensions.ControllerExtension(
                self, class_.collection, controller)
            exts.append(extension)
        return exts
