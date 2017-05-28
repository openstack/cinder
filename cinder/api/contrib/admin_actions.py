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
from six.moves import http_client
import webob
from webob import exc

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder import backup
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields
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
                        'error_deleting',
                        'error_managing',
                        'managing', ])

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

    def _remove_worker(self, context, id):
        # Remove the cleanup worker from the DB when we change a resource
        # status since it renders useless the entry.
        res = db.worker_destroy(context, resource_type=self.collection.title(),
                                resource_id=id)
        if res:
            LOG.debug('Worker entry for %s with id %s has been deleted.',
                      self.collection, id)

    @wsgi.action('os-reset_status')
    def _reset_status(self, req, id, body):
        """Reset status on the resource."""

        def _clean_volume_attachment(context, id):
            attachments = (
                db.volume_attachment_get_all_by_volume_id(context, id))
            for attachment in attachments:
                db.volume_detached(context, id, attachment.id)
            db.volume_admin_metadata_delete(context, id,
                                            'attached_mode')

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

        # Not found exception will be handled at the wsgi level
        self._update(context, id, update)
        self._remove_worker(context, id)
        if update.get('attach_status') == 'detached':
            _clean_volume_attachment(context, id)

        notifier.info(context, self.collection + '.reset_status.end',
                      notifier_info)

        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.action('os-force_delete')
    def _force_delete(self, req, id, body):
        """Delete a resource, bypassing the check that it must be available."""
        context = req.environ['cinder.context']
        self.authorize(context, 'force_delete')
        # Not found exception will be handled at the wsgi level
        resource = self._get(context, id)
        self._delete(context, resource, force=True)
        return webob.Response(status_int=http_client.ACCEPTED)


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
    valid_attach_status = (fields.VolumeAttachStatus.ATTACHED,
                           fields.VolumeAttachStatus.DETACHED,)
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
        # Not found exception will be handled at the wsgi level
        volume = self._get(context, id)
        try:
            connector = body['os-force_detach'].get('connector', None)
        except AttributeError:
            msg = _("Invalid value '%s' for "
                    "os-force_detach.") % body['os-force_detach']
            raise webob.exc.HTTPBadRequest(explanation=msg)
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
        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.action('os-migrate_volume')
    def _migrate_volume(self, req, id, body):
        """Migrate a volume to the specified host."""
        context = req.environ['cinder.context']
        self.authorize(context, 'migrate_volume')
        # Not found exception will be handled at the wsgi level
        volume = self._get(context, id)
        params = body['os-migrate_volume']

        cluster_name, host = common.get_cluster_host(req, params, '3.16')
        force_host_copy = utils.get_bool_param('force_host_copy', params)
        lock_volume = utils.get_bool_param('lock_volume', params)
        self.volume_api.migrate_volume(context, volume, host, cluster_name,
                                       force_host_copy, lock_volume)
        return webob.Response(status_int=http_client.ACCEPTED)

    @wsgi.action('os-migrate_volume_completion')
    def _migrate_volume_completion(self, req, id, body):
        """Complete an in-progress migration."""
        context = req.environ['cinder.context']
        self.authorize(context, 'migrate_volume_completion')
        # Not found exception will be handled at the wsgi level
        volume = self._get(context, id)
        params = body['os-migrate_volume_completion']
        try:
            new_volume_id = params['new_volume']
        except KeyError:
            raise exc.HTTPBadRequest(
                explanation=_("Must specify 'new_volume'"))
        # Not found exception will be handled at the wsgi level
        new_volume = self._get(context, new_volume_id)
        error = params.get('error', False)
        ret = self.volume_api.migrate_volume_completion(context, volume,
                                                        new_volume, error)
        return {'save_volume_id': ret}


class SnapshotAdminController(AdminController):
    """AdminController for Snapshots."""

    collection = 'snapshots'
    valid_status = fields.SnapshotStatus.ALL

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

        # Not found exception will be handled at the wsgi level
        self.backup_api.reset_status(context=context, backup_id=id,
                                     status=update['status'])
        return webob.Response(status_int=http_client.ACCEPTED)


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
