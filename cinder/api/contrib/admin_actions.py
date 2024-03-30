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


class VolumeAdminController(wsgi.Controller):
    """AdminController for Volumes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.volume_api = volume.API()

    def authorize(self, context, action_name, target_obj=None):
        context.authorize(
            'volume_extension:volume_admin_actions:%(action)s' %
            {'action': action_name}, target_obj=target_obj
        )

    def _notify_reset_status(self, context, id, message):
        volume = objects.Volume.get_by_id(context, id)
        volume_utils.notify_about_volume_usage(context, volume,
                                               message)

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-reset_status')
    @validation.schema(admin_actions.reset)
    def _reset_status(self, req, id, body):
        """Reset status on the volume."""

        def _clean_volume_attachment(context, id):
            attachments = (
                db.volume_attachment_get_all_by_volume_id(context, id))
            for attachment in attachments:
                db.volume_detached(context.elevated(), id, attachment.id)
            db.volume_admin_metadata_delete(context.elevated(), id,
                                            'attached_mode')

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

        context = req.environ['cinder.context']
        # any exceptions raised will be handled at the wsgi level
        volume = objects.Volume.get_by_id(context, id)
        self.authorize(context, 'reset_status', target_obj=volume)

        # at this point, we still don't know if we're going to
        # reset the volume's state.  Need to check what the caller
        # is requesting first.
        if update.get('status') in ('deleting', 'error_deleting'
                                    'detaching'):
            msg = _("Cannot reset-state to %s"
                    % update.get('status'))
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if update.get('status') == 'in-use':
            attachments = (
                db.volume_attachment_get_all_by_volume_id(context, id))
            if not attachments:
                msg = _("Cannot reset-state to in-use "
                        "because volume does not have any attachments.")
                raise webob.exc.HTTPBadRequest(explanation=msg)

        msg = "Updating volume '%(id)s' with '%(update)r'"
        LOG.debug(msg, {'id': id, 'update': update})
        self._notify_reset_status(context, id, 'reset_status.start')

        db.volume_update(context, id, update)

        # Remove the cleanup worker from the DB when we change a resource
        # status since it renders useless the entry.
        res = db.worker_destroy(context, resource_type='VOLUME',
                                resource_id=id)
        if res:
            LOG.debug('Worker entry for volume with id %s has been deleted.',
                      id)

        if update.get('attach_status') == 'detached':
            _clean_volume_attachment(context, id)

        self._notify_reset_status(context, id, 'reset_status.end')

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-force_detach')
    @validation.schema(admin_actions.force_detach)
    def _force_detach(self, req, id, body):
        """Roll-back a bad detach after the volume been disconnected."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)
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
        volume = self.volume_api.get(context, id)
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
        volume = self.volume_api.get(context, id)
        self.authorize(context, 'migrate_volume_completion', target_obj=volume)
        params = body['os-migrate_volume_completion']
        new_volume_id = params['new_volume']
        # Not found exception will be handled at the wsgi level
        new_volume = self.volume_api.get(context, new_volume_id)
        error = params.get('error', False)
        ret = self.volume_api.migrate_volume_completion(context, volume,
                                                        new_volume, error)
        return {'save_volume_id': ret}

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-extend_volume_completion')
    @validation.schema(admin_actions.extend_volume_completion)
    def _extend_volume_completion(self, req, id, body):
        """Complete an in-progress extend operation."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        volume = self.volume_api.get(context, id)
        self.authorize(context, 'extend_volume_completion', target_obj=volume)
        params = body['os-extend_volume_completion']
        error = params.get('error', False)
        self.volume_api.extend_volume_completion(context, volume, error)

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-force_delete')
    def _force_delete(self, req, id, body):
        """Delete a volume, bypassing the check that it must be available."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        resource = self.volume_api.get(context, id)
        self.authorize(context, 'force_delete', target_obj=resource)
        self.volume_api.delete(context, resource, force=True)


class SnapshotAdminController(wsgi.Controller):
    """AdminController for Snapshots."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.volume_api = volume.API()

    def authorize(self, context, action_name, target_obj=None):
        context.authorize(
            'volume_extension:snapshot_admin_actions:%(action)s' %
            {'action': action_name}, target_obj=target_obj
        )

    def _notify_reset_status(self, context, id, message):
        snapshot = objects.Snapshot.get_by_id(context, id)
        volume_utils.notify_about_snapshot_usage(context, snapshot,
                                                 message)

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-reset_status')
    @validation.schema(admin_actions.reset_status_snapshot)
    def _reset_status(self, req, id, body):
        """Reset status on the snapshot."""

        def _clean_volume_attachment(context, id):
            attachments = (
                db.volume_attachment_get_all_by_volume_id(context, id))
            for attachment in attachments:
                db.volume_detached(context.elevated(), id, attachment.id)
            db.volume_admin_metadata_delete(context.elevated(), id,
                                            'attached_mode')

        context = req.environ['cinder.context']
        status = body['os-reset_status']['status']
        update = {'status': status.lower()}
        msg = "Updating snapshot '%(id)s' with '%(update)r'"
        LOG.debug(msg, {'id': id, 'update': update})

        self._notify_reset_status(context, id, 'reset_status.start')

        # Not found exception will be handled at the wsgi level
        snapshot = objects.Snapshot.get_by_id(context, id)
        self.authorize(context, 'reset_status', target_obj=snapshot)
        snapshot.update(update)
        snapshot.save()

        # Remove the cleanup worker from the DB when we change a resource
        # status since it renders useless the entry.
        res = db.worker_destroy(context, resource_type='SNAPSHOT',
                                resource_id=id)
        if res:
            LOG.debug('Worker entry for snapshot with id %s has been deleted.',
                      id)

        if update.get('attach_status') == 'detached':
            _clean_volume_attachment(context, id)

        self._notify_reset_status(context, id, 'reset_status.end')

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-force_delete')
    def _force_delete(self, req, id, body):
        """Delete a snapshot, bypassing the check that it must be available."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        resource = self.volume_api.get_snapshot(context, id)
        self.authorize(context, 'force_delete', target_obj=resource)
        self.volume_api.delete_snapshot(context, resource, force=True)


class BackupAdminController(wsgi.Controller):
    """AdminController for Backups."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.backup_api = backup.API()

    def authorize(self, context, action_name, target_obj=None):
        context.authorize(
            'volume_extension:backup_admin_actions:%(action)s' %
            {'action': action_name}, target_obj=target_obj
        )

    def _notify_reset_status(self, context, id, message):
        backup = objects.Backup.get_by_id(context, id)
        volume_utils.notify_about_backup_usage(context, backup,
                                               message)

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-reset_status')
    @validation.schema(admin_actions.reset_status_backup)
    def _reset_status(self, req, id, body):
        """Reset status on the backup."""
        context = req.environ['cinder.context']
        status = body['os-reset_status']['status']
        update = {'status': status.lower()}
        msg = "Updating backup '%(id)s' with '%(update)r'"
        LOG.debug(msg, {'id': id, 'update': update})

        self._notify_reset_status(context, id, 'reset_status.start')

        # Not found exception will be handled at the wsgi level
        self.backup_api.reset_status(context=context, backup_id=id,
                                     status=update['status'])

        # the backup API takes care of the reset_status.end notification

    @wsgi.response(HTTPStatus.ACCEPTED)
    @wsgi.action('os-force_delete')
    def _force_delete(self, req, id, body):
        """Delete a backup, bypassing the check that it must be available."""
        context = req.environ['cinder.context']
        # Not found exception will be handled at the wsgi level
        resource = self.backup_api.get(context, id)
        self.authorize(context, 'force_delete', target_obj=resource)
        self.backup_api.delete(context, resource, force=True)


class Admin_actions(extensions.ExtensionDescriptor):
    """Enable admin actions."""

    name = "AdminActions"
    alias = "os-admin-actions"
    updated = "2012-08-25T00:00:00+00:00"

    def get_controller_extensions(self):
        return [
            extensions.ControllerExtension(
                self, 'volumes', VolumeAdminController()),
            extensions.ControllerExtension(
                self, 'snapshots', SnapshotAdminController()),
            extensions.ControllerExtension(
                self, 'backups', BackupAdminController()),
        ]
