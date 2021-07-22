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
from http import HTTPStatus

from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import strutils
import webob

from cinder.api import common
from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import admin_actions
from cinder.api import validation
from cinder import backup
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder import volume
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)


class AdminController(wsgi.Controller):
    """Abstract base class for AdminControllers."""

    collection = None  # api collection to extend

    # FIXME(clayg): this will be hard to keep up-to-date
    # Concrete classes can expand or over-ride

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

    def validate_update(self, req, body):
        raise NotImplementedError()

    def _notify_reset_status(self, context, id, message):
        raise NotImplementedError()

    def authorize(self, context, action_name, target_obj=None):
        context.authorize(
            'volume_extension:%(resource)s_admin_actions:%(action)s' %
            {'resource': self.resource_name,
             'action': action_name}, target_obj=target_obj)

    def _remove_worker(self, context, id):
        # Remove the cleanup worker from the DB when we change a resource
        # status since it renders useless the entry.
        res = db.worker_destroy(context, resource_type=self.collection.title(),
                                resource_id=id)
        if res:
            LOG.debug('Worker entry for %s with id %s has been deleted.',
                      self.collection, id)

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-reset_status')
    def _reset_status(self, req, id, body):
        """Reset status on the resource."""

        def _clean_volume_attachment(context, id):
            attachments = (
                db.volume_attachment_get_all_by_volume_id(context, id))
            for attachment in attachments:
                db.volume_detached(context.elevated(), id, attachment.id)
            db.volume_admin_metadata_delete(context.elevated(), id,
                                            'attached_mode')

        context = req.environ['cinder.context']
        update = self.validate_update(req, body=body)
        msg = "Updating %(resource)s '%(id)s' with '%(update)r'"
        LOG.debug(msg, {'resource': self.resource_name, 'id': id,
                        'update': update})

        self._notify_reset_status(context, id, 'reset_status.start')

        # Not found exception will be handled at the wsgi level
        self._update(context, id, update)
        self._remove_worker(context, id)
        if update.get('attach_status') == 'detached':
            _clean_volume_attachment(context, id)

        self._notify_reset_status(context, id, 'reset_status.end')

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-force_delete')
    def _force_delete(self, req, id, body):
        """Delete a resource, bypassing the check that it must be available."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        resource = self._get(context, id)
        self.authorize(context, 'force_delete', target_obj=resource)
        self._delete(context, resource, force=True)


class VolumeAdminController(AdminController):
    """AdminController for Volumes."""

    collection = 'volumes'

    def _notify_reset_status(self, context, id, message):
        volume = objects.Volume.get_by_id(context, id)
        volume_utils.notify_about_volume_usage(context, volume,
                                               message)

    def _update(self, *args, **kwargs):
        context = args[0]
        volume_id = args[1]
        volume = objects.Volume.get_by_id(context, volume_id)
        self.authorize(context, 'reset_status', target_obj=volume)
        db.volume_update(*args, **kwargs)

    def _get(self, *args, **kwargs):
        return self.volume_api.get(*args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self.volume_api.delete(*args, **kwargs)

    @validation.schema(admin_actions.reset)
    def validate_update(self, req, body):
        update = {}
        body = body['os-reset_status']
        status = body.get('status', None)
        attach_status = body.get('attach_status', None)
        migration_status = body.get('migration_status', None)

        if status:
            update['status'] = status.lower()

        if attach_status:
            update['attach_status'] = attach_status.lower()

        if migration_status:
            update['migration_status'] = migration_status.lower()
            if update['migration_status'] == 'none':
                update['migration_status'] = None

        return update

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-force_detach')
    @validation.schema(admin_actions.force_detach)
    def _force_detach(self, req, id, body):
        """Roll back a bad detach after the volume been disconnected."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self._get(context, id)
        self.authorize(context, 'force_detach', target_obj=volume)
        connector = body['os-force_detach'].get('connector', None)

        try:
            self.volume_api.terminate_connection(context, volume, connector)
        except exception.VolumeBackendAPIException:
            msg = _("Unable to terminate volume connection from backend.")
            raise webob.exc.HTTPInternalServerError(explanation=msg)

        attachment_id = body['os-force_detach'].get('attachment_id', None)

        try:
            self.volume_api.detach(context, volume, attachment_id)
        except messaging.RemoteError as error:
            if error.exc_type in ['VolumeAttachmentNotFound',
                                  'InvalidVolume']:
                msg = _("Error force detaching volume - %(err_type)s: "
                        "%(err_msg)s") % {'err_type': error.exc_type,
                                          'err_msg': error.value}
                raise webob.exc.HTTPBadRequest(explanation=msg)
            else:
                # There are also few cases where force-detach call could fail
                # due to db or volume driver errors. These errors shouldn't
                # be exposed to the user and in such cases it should raise
                # 500 error.
                raise

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-migrate_volume')
    @validation.schema(admin_actions.migrate_volume, mv.BASE_VERSION,
                       mv.get_prior_version(mv.VOLUME_MIGRATE_CLUSTER))
    @validation.schema(admin_actions.migrate_volume_v316,
                       mv.VOLUME_MIGRATE_CLUSTER)
    def _migrate_volume(self, req, id, body):
        """Migrate a volume to the specified host."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self._get(context, id)
        self.authorize(context, 'migrate_volume', target_obj=volume)
        params = body['os-migrate_volume']

        cluster_name, host = common.get_cluster_host(req, params,
                                                     mv.VOLUME_MIGRATE_CLUSTER)
        force_host_copy = strutils.bool_from_string(params.get(
            'force_host_copy', False), strict=True)
        lock_volume = strutils.bool_from_string(params.get(
            'lock_volume', False), strict=True)
        self.volume_api.migrate_volume(context, volume, host, cluster_name,
                                       force_host_copy, lock_volume)

    @wsgi.action('os-migrate_volume_completion')
    @validation.schema(admin_actions.migrate_volume_completion)
    def _migrate_volume_completion(self, req, id, body):
        """Complete an in-progress migration."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self._get(context, id)
        self.authorize(context, 'migrate_volume_completion', target_obj=volume)
        params = body['os-migrate_volume_completion']
        new_volume_id = params['new_volume']
        # Not found exception will be handled at the wsgi level
        new_volume = self._get(context, new_volume_id)
        error = params.get('error', False)
        ret = self.volume_api.migrate_volume_completion(context, volume,
                                                        new_volume, error)
        return {'save_volume_id': ret}


class SnapshotAdminController(AdminController):
    """AdminController for Snapshots."""

    collection = 'snapshots'

    def _notify_reset_status(self, context, id, message):
        snapshot = objects.Snapshot.get_by_id(context, id)
        volume_utils.notify_about_snapshot_usage(context, snapshot,
                                                 message)

    @validation.schema(admin_actions.reset_status_snapshot)
    def validate_update(self, req, body):
        status = body['os-reset_status']['status']
        update = {'status': status.lower()}
        return update

    def _update(self, *args, **kwargs):
        context = args[0]
        snapshot_id = args[1]
        fields = args[2]
        snapshot = objects.Snapshot.get_by_id(context, snapshot_id)
        self.authorize(context, 'reset_status', target_obj=snapshot)
        snapshot.update(fields)
        snapshot.save()

    def _get(self, *args, **kwargs):
        return self.volume_api.get_snapshot(*args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self.volume_api.delete_snapshot(*args, **kwargs)


class BackupAdminController(AdminController):
    """AdminController for Backups."""

    collection = 'backups'

    def _notify_reset_status(self, context, id, message):
        backup = objects.Backup.get_by_id(context, id)
        volume_utils.notify_about_backup_usage(context, backup,
                                               message)

    def _get(self, *args, **kwargs):
        return self.backup_api.get(*args, **kwargs)

    def _delete(self, *args, **kwargs):
        return self.backup_api.delete(*args, **kwargs)

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-reset_status')
    @validation.schema(admin_actions.reset_status_backup)
    def _reset_status(self, req, id, body):
        """Reset status on the resource."""
        context = req.environ['cinder.context']
        status = body['os-reset_status']['status']
        update = {'status': status.lower()}
        msg = "Updating %(resource)s '%(id)s' with '%(update)r'"
        LOG.debug(msg, {'resource': self.resource_name, 'id': id,
                        'update': update})

        self._notify_reset_status(context, id, 'reset_status.start')

        # Not found exception will be handled at the wsgi level
        self.backup_api.reset_status(context=context, backup_id=id,
                                     status=update['status'])


class Admin_actions(extensions.ExtensionDescriptor):
    """Enable admin actions."""

    name = "AdminActions"
    alias = "os-admin-actions"
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
