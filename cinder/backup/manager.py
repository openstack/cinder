# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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

"""
Backup manager manages volume backups.

Volume Backups are full copies of persistent volumes stored in a backup
store e.g. an object store or any other backup store if and when support is
added. They are usable without the original object being available. A
volume backup can be restored to the original volume it was created from or
any other available volume with a minimum size of the original volume.
Volume backups can be created, restored, deleted and listed.

**Related Flags**

:backup_manager:  The module name of a class derived from
                          :class:`manager.Manager` (default:
                          :class:`cinder.backup.manager.Manager`).

"""

import os

from castellan import key_manager
from eventlet import tpool
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import loopingcall
from oslo_service import periodic_task
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import timeutils
import six

from cinder.backup import driver
from cinder.backup import rpcapi as backup_rpcapi
from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.keymgr import migration as key_migration
from cinder import manager
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder import rpc
from cinder import utils
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

backup_manager_opts = [
    cfg.StrOpt('backup_driver',
               default='cinder.backup.drivers.swift.SwiftBackupDriver',
               help='Driver to use for backups.',),
    cfg.BoolOpt('backup_service_inithost_offload',
                default=True,
                help='Offload pending backup delete during '
                     'backup service startup. If false, the backup service '
                     'will remain down until all pending backups are '
                     'deleted.',),
    cfg.IntOpt('backup_native_threads_pool_size',
               default=60,
               min=20,
               help='Size of the native threads pool for the backups.  '
                    'Most backup drivers rely heavily on this, it can be '
                    'decreased for specific drivers that don\'t.'),
]

CONF = cfg.CONF
CONF.register_opts(backup_manager_opts)
CONF.import_opt('use_multipath_for_image_xfer', 'cinder.volume.driver')
CONF.import_opt('num_volume_device_scan_tries', 'cinder.volume.driver')
QUOTAS = quota.QUOTAS
MAPPING = {
    # Module name "google" conflicts with google library namespace inside the
    # driver when it imports google.auth
    'cinder.backup.drivers.google.GoogleBackupDriver':
    'cinder.backup.drivers.gcs.GoogleBackupDriver',
}
SERVICE_PGRP = '' if os.name == 'nt' else os.getpgrp()


# TODO(geguileo): Once Eventlet issue #432 gets fixed we can just tpool.execute
# the whole call to the driver's backup and restore methods instead of proxy
# wrapping the device_file and having the drivers also proxy wrap their
# writes/reads and the compression/decompression calls.
# (https://github.com/eventlet/eventlet/issues/432)

class BackupManager(manager.ThreadPoolManager):
    """Manages backup of block storage devices."""

    RPC_API_VERSION = backup_rpcapi.BackupAPI.RPC_API_VERSION

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, *args, **kwargs):
        self.az = CONF.storage_availability_zone
        self.backup_rpcapi = backup_rpcapi.BackupAPI()
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()
        super(BackupManager, self).__init__(*args, **kwargs)
        self.is_initialized = False
        self._set_tpool_size(CONF.backup_native_threads_pool_size)
        self._process_number = kwargs.get('process_number', 1)
        self.driver_name = CONF.backup_driver
        if self.driver_name in MAPPING:
            new_name = MAPPING[self.driver_name]
            LOG.warning('Backup driver path %s is deprecated, update your '
                        'configuration to the new path %s',
                        self.driver_name, new_name)
            self.driver_name = new_name
        self.service = importutils.import_class(self.driver_name)

    def _update_backup_error(self, backup, err,
                             status=fields.BackupStatus.ERROR):
        backup.status = status
        backup.fail_reason = err
        backup.save()

    def init_host(self, **kwargs):
        """Run initialization needed for a standalone service."""
        ctxt = context.get_admin_context()
        self.setup_backup_backend(ctxt)

        try:
            self._cleanup_incomplete_backup_operations(ctxt)
        except Exception:
            # Don't block startup of the backup service.
            LOG.exception("Problem cleaning incomplete backup operations.")

        # Migrate any ConfKeyManager keys based on fixed_key to the currently
        # configured key manager.
        backups = objects.BackupList.get_all_by_host(ctxt, self.host)
        self._add_to_threadpool(key_migration.migrate_fixed_key,
                                backups=backups)

    def _setup_backup_driver(self, ctxt):
        backup_service = self.service(context=ctxt, db=self.db)
        backup_service.check_for_setup_error()
        self.is_initialized = True
        raise loopingcall.LoopingCallDone()

    def setup_backup_backend(self, ctxt):
        try:
            init_loop = loopingcall.FixedIntervalLoopingCall(
                self._setup_backup_driver, ctxt)
            init_loop.start(interval=CONF.periodic_interval)
        except loopingcall.LoopingCallDone:
            LOG.info("Backup driver was successfully initialized.")
        except Exception:
            LOG.exception("Failed to initialize driver.",
                          resource={'type': 'driver',
                                    'id': self.__class__.__name__})

    def reset(self):
        super(BackupManager, self).reset()
        self.backup_rpcapi = backup_rpcapi.BackupAPI()
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()

    @utils.synchronized('cleanup_incomplete_backups_%s' % SERVICE_PGRP,
                        external=True, delay=0.1)
    def _cleanup_incomplete_backup_operations(self, ctxt):
        # Only the first launched process should do the cleanup, the others
        # have waited on the lock for the first one to finish the cleanup and
        # can now continue with the start process.
        if self._process_number != 1:
            LOG.debug("Process #%s %sskips cleanup.",
                      self._process_number,
                      '(pgid=%s) ' % SERVICE_PGRP if SERVICE_PGRP else '')
            return

        LOG.info("Cleaning up incomplete backup operations.")

        # TODO(smulcahy) implement full resume of backup and restore
        # operations on restart (rather than simply resetting)
        backups = objects.BackupList.get_all_by_host(ctxt, self.host)
        for backup in backups:
            try:
                self._cleanup_one_backup(ctxt, backup)
            except Exception:
                LOG.exception("Problem cleaning up backup %(bkup)s.",
                              {'bkup': backup['id']})
            try:
                self._cleanup_temp_volumes_snapshots_for_one_backup(ctxt,
                                                                    backup)
            except Exception:
                LOG.exception("Problem cleaning temp volumes and "
                              "snapshots for backup %(bkup)s.",
                              {'bkup': backup['id']})

    def _cleanup_one_volume(self, ctxt, volume):
        if volume['status'] == 'backing-up':
            self._detach_all_attachments(ctxt, volume)
            LOG.info('Resetting volume %(vol_id)s to previous '
                     'status %(status)s (was backing-up).',
                     {'vol_id': volume['id'],
                      'status': volume['previous_status']})
            self.db.volume_update(ctxt, volume['id'],
                                  {'status': volume['previous_status']})
        elif volume['status'] == 'restoring-backup':
            self._detach_all_attachments(ctxt, volume)
            LOG.info('Setting volume %s to error_restoring '
                     '(was restoring-backup).', volume['id'])
            self.db.volume_update(ctxt, volume['id'],
                                  {'status': 'error_restoring'})

    def _cleanup_one_backup(self, ctxt, backup):
        if backup['status'] == fields.BackupStatus.CREATING:
            LOG.info('Resetting backup %s to error (was creating).',
                     backup['id'])

            volume = objects.Volume.get_by_id(ctxt, backup.volume_id)
            self._cleanup_one_volume(ctxt, volume)

            err = 'incomplete backup reset on manager restart'
            self._update_backup_error(backup, err)
        elif backup['status'] == fields.BackupStatus.RESTORING:
            LOG.info('Resetting backup %s to '
                     'available (was restoring).',
                     backup['id'])
            volume = objects.Volume.get_by_id(ctxt, backup.restore_volume_id)
            self._cleanup_one_volume(ctxt, volume)

            backup.status = fields.BackupStatus.AVAILABLE
            backup.save()
        elif backup['status'] == fields.BackupStatus.DELETING:
            # Don't resume deleting the backup of an encrypted volume. The
            # admin context won't be sufficient to delete the backup's copy
            # of the encryption key ID (a real user context is required).
            if backup.encryption_key_id is None:
                LOG.info('Resuming delete on backup: %s.', backup.id)
                if CONF.backup_service_inithost_offload:
                    # Offload all the pending backup delete operations to the
                    # threadpool to prevent the main backup service thread
                    # from being blocked.
                    self._add_to_threadpool(self.delete_backup, ctxt, backup)
                else:
                    # Delete backups sequentially
                    self.delete_backup(ctxt, backup)
            else:
                LOG.info('Unable to resume deleting backup of an encrypted '
                         'volume, resetting backup %s to error_deleting '
                         '(was deleting).',
                         backup.id)
                backup.status = fields.BackupStatus.ERROR_DELETING
                backup.save()

    def _detach_all_attachments(self, ctxt, volume):
        attachments = volume['volume_attachment'] or []
        for attachment in attachments:
            if (attachment['attached_host'] == self.host and
                    attachment['instance_uuid'] is None):
                try:
                    rpcapi = self.volume_rpcapi
                    rpcapi.detach_volume(ctxt, volume, attachment['id'])
                except Exception:
                    LOG.exception("Detach attachment %(attach_id)s failed.",
                                  {'attach_id': attachment['id']},
                                  resource=volume)

    def _delete_temp_volume(self, ctxt, backup):
        try:
            temp_volume = objects.Volume.get_by_id(
                ctxt, backup.temp_volume_id)
            self.volume_rpcapi.delete_volume(ctxt, temp_volume)
        except exception.VolumeNotFound:
            LOG.debug("Could not find temp volume %(vol)s to clean up "
                      "for backup %(backup)s.",
                      {'vol': backup.temp_volume_id,
                       'backup': backup.id})
        backup.temp_volume_id = None
        backup.save()

    def _delete_temp_snapshot(self, ctxt, backup):
        try:
            temp_snapshot = objects.Snapshot.get_by_id(
                ctxt, backup.temp_snapshot_id)
            # We may want to consider routing those calls through the
            # cinder API.
            temp_snapshot.status = fields.SnapshotStatus.DELETING
            temp_snapshot.save()
            self.volume_rpcapi.delete_snapshot(ctxt, temp_snapshot)
        except exception.SnapshotNotFound:
            LOG.debug("Could not find temp snapshot %(snap)s to clean "
                      "up for backup %(backup)s.",
                      {'snap': backup.temp_snapshot_id,
                       'backup': backup.id})
        backup.temp_snapshot_id = None
        backup.save()

    def _cleanup_temp_volumes_snapshots_for_one_backup(self, ctxt, backup):
        # NOTE(xyang): If the service crashes or gets restarted during the
        # backup operation, there could be temporary volumes or snapshots
        # that are not deleted. Make sure any temporary volumes or snapshots
        # create by the backup job are deleted when service is started.
        if (backup.temp_volume_id
                and backup.status == fields.BackupStatus.ERROR):
            self._delete_temp_volume(ctxt, backup)

        if (backup.temp_snapshot_id
                and backup.status == fields.BackupStatus.ERROR):
            self._delete_temp_snapshot(ctxt, backup)

    def _cleanup_temp_volumes_snapshots_when_backup_created(
            self, ctxt, backup):
        # Delete temp volumes or snapshots when backup creation is completed.
        if backup.temp_volume_id:
            self._delete_temp_volume(ctxt, backup)

        if backup.temp_snapshot_id:
            self._delete_temp_snapshot(ctxt, backup)

    def create_backup(self, context, backup):
        """Create volume backups using configured backup service."""
        volume_id = backup.volume_id
        snapshot_id = backup.snapshot_id
        volume = objects.Volume.get_by_id(context, volume_id)
        snapshot = objects.Snapshot.get_by_id(
            context, snapshot_id) if snapshot_id else None
        previous_status = volume.get('previous_status', None)
        updates = {}
        if snapshot_id:
            log_message = ('Create backup started, backup: %(backup_id)s '
                           'volume: %(volume_id)s snapshot: %(snapshot_id)s.'
                           % {'backup_id': backup.id,
                              'volume_id': volume_id,
                              'snapshot_id': snapshot_id})
        else:
            log_message = ('Create backup started, backup: %(backup_id)s '
                           'volume: %(volume_id)s.'
                           % {'backup_id': backup.id,
                              'volume_id': volume_id})
        LOG.info(log_message)

        self._notify_about_backup_usage(context, backup, "create.start")

        backup.host = self.host
        backup.availability_zone = self.az
        backup.save()

        expected_status = "backing-up"
        if snapshot_id:
            actual_status = snapshot['status']
            if actual_status != expected_status:
                err = _('Create backup aborted, expected snapshot status '
                        '%(expected_status)s but got %(actual_status)s.') % {
                    'expected_status': expected_status,
                    'actual_status': actual_status,
                }
                self._update_backup_error(backup, err)
                raise exception.InvalidSnapshot(reason=err)
        else:
            actual_status = volume['status']
            if actual_status != expected_status:
                err = _('Create backup aborted, expected volume status '
                        '%(expected_status)s but got %(actual_status)s.') % {
                    'expected_status': expected_status,
                    'actual_status': actual_status,
                }
                self._update_backup_error(backup, err)
                raise exception.InvalidVolume(reason=err)

        expected_status = fields.BackupStatus.CREATING
        actual_status = backup.status
        if actual_status != expected_status:
            err = _('Create backup aborted, expected backup status '
                    '%(expected_status)s but got %(actual_status)s.') % {
                'expected_status': expected_status,
                'actual_status': actual_status,
            }
            self._update_backup_error(backup, err)
            raise exception.InvalidBackup(reason=err)

        try:
            if not self.is_working():
                err = _('Create backup aborted due to backup service is down.')
                self._update_backup_error(backup, err)
                raise exception.InvalidBackup(reason=err)

            backup.service = self.driver_name
            backup.save()
            updates = self._run_backup(context, backup, volume)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                if snapshot_id:
                    snapshot.status = fields.SnapshotStatus.AVAILABLE
                    snapshot.save()
                else:
                    self.db.volume_update(
                        context, volume_id,
                        {'status': previous_status,
                         'previous_status': 'error_backing-up'})
                self._update_backup_error(backup, six.text_type(err))

        # Restore the original status.
        if snapshot_id:
            self.db.snapshot_update(
                context, snapshot_id,
                {'status': fields.SnapshotStatus.AVAILABLE})
        else:
            self.db.volume_update(context, volume_id,
                                  {'status': previous_status,
                                   'previous_status': 'backing-up'})

        # _run_backup method above updated the status for the backup, so it
        # will reflect latest status, even if it is deleted
        completion_msg = 'finished'
        if backup.status in (fields.BackupStatus.DELETING,
                             fields.BackupStatus.DELETED):
            completion_msg = 'aborted'
        else:
            backup.status = fields.BackupStatus.AVAILABLE
            backup.size = volume['size']

            if updates:
                backup.update(updates)
            backup.save()

            # Handle the num_dependent_backups of parent backup when child
            # backup has created successfully.
            if backup.parent_id:
                parent_backup = objects.Backup.get_by_id(context,
                                                         backup.parent_id)
                parent_backup.num_dependent_backups += 1
                parent_backup.save()
        LOG.info('Create backup %s. backup: %s.', completion_msg, backup.id)
        self._notify_about_backup_usage(context, backup, "create.end")

    def _run_backup(self, context, backup, volume):
        # Save a copy of the encryption key ID in case the volume is deleted.
        if (volume.encryption_key_id is not None and
                backup.encryption_key_id is None):
            backup.encryption_key_id = volume_utils.clone_encryption_key(
                context,
                key_manager.API(CONF),
                volume.encryption_key_id)
            backup.save()

        backup_service = self.service(context)

        properties = utils.brick_get_connector_properties()

        # NOTE(geguileo): Not all I/O disk operations properly do greenthread
        # context switching and may end up blocking the greenthread, so we go
        # with native threads proxy-wrapping the device file object.
        try:
            backup_device = self.volume_rpcapi.get_backup_device(context,
                                                                 backup,
                                                                 volume)
            attach_info = self._attach_device(context,
                                              backup_device.device_obj,
                                              properties,
                                              backup_device.is_snapshot)
            try:
                device_path = attach_info['device']['path']
                if (isinstance(device_path, six.string_types) and
                        not os.path.isdir(device_path)):
                    if backup_device.secure_enabled:
                        with open(device_path, 'rb') as device_file:
                            updates = backup_service.backup(
                                backup, tpool.Proxy(device_file))
                    else:
                        with utils.temporary_chown(device_path):
                            with open(device_path, 'rb') as device_file:
                                updates = backup_service.backup(
                                    backup, tpool.Proxy(device_file))
                # device_path is already file-like so no need to open it
                else:
                    updates = backup_service.backup(backup,
                                                    tpool.Proxy(device_path))

            finally:
                self._detach_device(context, attach_info,
                                    backup_device.device_obj, properties,
                                    backup_device.is_snapshot, force=True,
                                    ignore_errors=True)
        finally:
            with backup.as_read_deleted():
                backup.refresh()
            self._cleanup_temp_volumes_snapshots_when_backup_created(
                context, backup)
        return updates

    def _is_our_backup(self, backup):
        # Accept strings and Service OVO
        if not isinstance(backup, six.string_types):
            backup = backup.service

        if not backup:
            return True

        # TODO(tommylikehu): We upgraded the 'driver_name' from module
        # to class name, so we use 'in' here to match two namings,
        # this can be replaced with equal sign during next
        # release (Rocky).
        if self.driver_name.startswith(backup):
            return True

        # We support renaming of drivers, so check old names as well
        for key, value in MAPPING.items():
            if key.startswith(backup) and self.driver_name.startswith(value):
                return True

        return False

    def restore_backup(self, context, backup, volume_id):
        """Restore volume backups from configured backup service."""
        LOG.info('Restore backup started, backup: %(backup_id)s '
                 'volume: %(volume_id)s.',
                 {'backup_id': backup.id, 'volume_id': volume_id})

        volume = objects.Volume.get_by_id(context, volume_id)
        self._notify_about_backup_usage(context, backup, "restore.start")

        backup.host = self.host
        backup.save()

        expected_status = [fields.VolumeStatus.RESTORING_BACKUP,
                           fields.VolumeStatus.CREATING]
        volume_previous_status = volume['status']
        if volume_previous_status not in expected_status:
            err = (_('Restore backup aborted, expected volume status '
                     '%(expected_status)s but got %(actual_status)s.') %
                   {'expected_status': ','.join(expected_status),
                    'actual_status': volume_previous_status})
            backup.status = fields.BackupStatus.AVAILABLE
            backup.save()
            self.db.volume_update(
                context, volume_id,
                {'status':
                 (fields.VolumeStatus.ERROR if
                  volume_previous_status == fields.VolumeStatus.CREATING else
                  fields.VolumeStatus.ERROR_RESTORING)})
            raise exception.InvalidVolume(reason=err)

        expected_status = fields.BackupStatus.RESTORING
        actual_status = backup['status']
        if actual_status != expected_status:
            err = (_('Restore backup aborted: expected backup status '
                     '%(expected_status)s but got %(actual_status)s.') %
                   {'expected_status': expected_status,
                    'actual_status': actual_status})
            self._update_backup_error(backup, err)
            self.db.volume_update(context, volume_id,
                                  {'status': fields.VolumeStatus.ERROR})
            raise exception.InvalidBackup(reason=err)

        if volume['size'] > backup['size']:
            LOG.info('Volume: %(vol_id)s, size: %(vol_size)d is '
                     'larger than backup: %(backup_id)s, '
                     'size: %(backup_size)d, continuing with restore.',
                     {'vol_id': volume['id'],
                      'vol_size': volume['size'],
                      'backup_id': backup['id'],
                      'backup_size': backup['size']})

        if not self._is_our_backup(backup):
            err = _('Restore backup aborted, the backup service currently'
                    ' configured [%(configured_service)s] is not the'
                    ' backup service that was used to create this'
                    ' backup [%(backup_service)s].') % {
                'configured_service': self.driver_name,
                'backup_service': backup.service,
            }
            backup.status = fields.BackupStatus.AVAILABLE
            backup.save()
            self.db.volume_update(context, volume_id,
                                  {'status': fields.VolumeStatus.ERROR})
            raise exception.InvalidBackup(reason=err)

        canceled = False
        try:
            self._run_restore(context, backup, volume)
        except exception.BackupRestoreCancel:
            canceled = True
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(
                    context, volume_id,
                    {'status': (fields.VolumeStatus.ERROR if
                                actual_status == fields.VolumeStatus.CREATING
                                else fields.VolumeStatus.ERROR_RESTORING)})
                backup.status = fields.BackupStatus.AVAILABLE
                backup.save()

        if canceled:
            volume.status = fields.VolumeStatus.ERROR
        else:
            volume.status = fields.VolumeStatus.AVAILABLE
            # NOTE(tommylikehu): If previous status is 'creating', this is
            # just a new created volume and we need update the 'launched_at'
            # attribute as well.
            if volume_previous_status == fields.VolumeStatus.CREATING:
                volume['launched_at'] = timeutils.utcnow()
        volume.save()
        backup.status = fields.BackupStatus.AVAILABLE
        backup.save()
        LOG.info('%(result)s restoring backup %(backup_id)s to volume '
                 '%(volume_id)s.',
                 {'result': 'Canceled' if canceled else 'Finished',
                  'backup_id': backup.id,
                  'volume_id': volume_id})
        self._notify_about_backup_usage(context, backup, "restore.end")

    def _run_restore(self, context, backup, volume):
        orig_key_id = volume.encryption_key_id
        backup_service = self.service(context)

        properties = utils.brick_get_connector_properties()
        secure_enabled = (
            self.volume_rpcapi.secure_file_operations_enabled(context,
                                                              volume))
        attach_info = self._attach_device(context, volume, properties)

        # NOTE(geguileo): Not all I/O disk operations properly do greenthread
        # context switching and may end up blocking the greenthread, so we go
        # with native threads proxy-wrapping the device file object.
        try:
            device_path = attach_info['device']['path']
            open_mode = 'rb+' if os.name == 'nt' else 'wb'
            if (isinstance(device_path, six.string_types) and
                    not os.path.isdir(device_path)):
                if secure_enabled:
                    with open(device_path, open_mode) as device_file:
                        backup_service.restore(backup, volume.id,
                                               tpool.Proxy(device_file))
                else:
                    with utils.temporary_chown(device_path):
                        with open(device_path, open_mode) as device_file:
                            backup_service.restore(backup, volume.id,
                                                   tpool.Proxy(device_file))
            # device_path is already file-like so no need to open it
            else:
                backup_service.restore(backup, volume.id,
                                       tpool.Proxy(device_path))
        except exception.BackupRestoreCancel:
            raise
        except Exception:
            LOG.exception('Restoring backup %(backup_id)s to volume '
                          '%(volume_id)s failed.', {'backup_id': backup.id,
                                                    'volume_id': volume.id})
            raise
        finally:
            self._detach_device(context, attach_info, volume, properties,
                                force=True)

        # Regardless of whether the restore was successful, do some
        # housekeeping to ensure the restored volume's encryption key ID is
        # unique, and any previous key ID is deleted. Start by fetching fresh
        # info on the restored volume.
        restored_volume = objects.Volume.get_by_id(context, volume.id)
        restored_key_id = restored_volume.encryption_key_id
        if restored_key_id != orig_key_id:
            LOG.info('Updating encryption key ID for volume %(volume_id)s '
                     'from backup %(backup_id)s.',
                     {'volume_id': volume.id, 'backup_id': backup.id})

            key_mgr = key_manager.API(CONF)
            if orig_key_id is not None:
                LOG.debug('Deleting original volume encryption key ID.')
                volume_utils.delete_encryption_key(context,
                                                   key_mgr,
                                                   orig_key_id)

            if backup.encryption_key_id is None:
                # This backup predates the current code that stores the cloned
                # key ID in the backup database. Fortunately, the key ID
                # restored from the backup data _is_ a clone of the original
                # volume's key ID, so grab it.
                LOG.debug('Gleaning backup encryption key ID from metadata.')
                backup.encryption_key_id = restored_key_id
                backup.save()

            # Clone the key ID again to ensure every restored volume has
            # a unique key ID. The volume's key ID should not be the same
            # as the backup.encryption_key_id (the copy made when the backup
            # was first created).
            new_key_id = volume_utils.clone_encryption_key(
                context,
                key_mgr,
                backup.encryption_key_id)
            restored_volume.encryption_key_id = new_key_id
            restored_volume.save()
        else:
            LOG.debug('Encryption key ID for volume %(volume_id)s already '
                      'matches encryption key ID in backup %(backup_id)s.',
                      {'volume_id': volume.id, 'backup_id': backup.id})

    def delete_backup(self, context, backup):
        """Delete volume backup from configured backup service."""
        LOG.info('Delete backup started, backup: %s.', backup.id)

        self._notify_about_backup_usage(context, backup, "delete.start")
        backup.host = self.host
        backup.save()

        expected_status = fields.BackupStatus.DELETING
        actual_status = backup.status
        if actual_status != expected_status:
            err = _('Delete_backup aborted, expected backup status '
                    '%(expected_status)s but got %(actual_status)s.') \
                % {'expected_status': expected_status,
                   'actual_status': actual_status}
            self._update_backup_error(backup, err)
            raise exception.InvalidBackup(reason=err)

        if backup.service and not self.is_working():
            err = _('Delete backup is aborted due to backup service is down.')
            status = fields.BackupStatus.ERROR_DELETING
            self._update_backup_error(backup, err, status)
            raise exception.InvalidBackup(reason=err)

        if not self._is_our_backup(backup):
            err = _('Delete backup aborted, the backup service currently'
                    ' configured [%(configured_service)s] is not the'
                    ' backup service that was used to create this'
                    ' backup [%(backup_service)s].')\
                % {'configured_service': self.driver_name,
                   'backup_service': backup.service}
            self._update_backup_error(backup, err)
            raise exception.InvalidBackup(reason=err)

        if backup.service:
            try:
                backup_service = self.service(context)
                backup_service.delete_backup(backup)
            except Exception as err:
                with excutils.save_and_reraise_exception():
                    self._update_backup_error(backup, six.text_type(err))

        # Get reservations
        try:
            reserve_opts = {
                'backups': -1,
                'backup_gigabytes': -backup.size,
            }
            reservations = QUOTAS.reserve(context,
                                          project_id=backup.project_id,
                                          **reserve_opts)
        except Exception:
            reservations = None
            LOG.exception("Failed to update usages deleting backup")

        if backup.encryption_key_id is not None:
            volume_utils.delete_encryption_key(context,
                                               key_manager.API(CONF),
                                               backup.encryption_key_id)
            backup.encryption_key_id = None
            backup.save()

        backup.destroy()
        # If this backup is incremental backup, handle the
        # num_dependent_backups of parent backup
        if backup.parent_id:
            parent_backup = objects.Backup.get_by_id(context,
                                                     backup.parent_id)
            if parent_backup.has_dependent_backups:
                parent_backup.num_dependent_backups -= 1
                parent_backup.save()
        # Commit the reservations
        if reservations:
            QUOTAS.commit(context, reservations,
                          project_id=backup.project_id)

        LOG.info('Delete backup finished, backup %s deleted.', backup.id)
        self._notify_about_backup_usage(context, backup, "delete.end")

    def _notify_about_backup_usage(self,
                                   context,
                                   backup,
                                   event_suffix,
                                   extra_usage_info=None):
        volume_utils.notify_about_backup_usage(
            context, backup, event_suffix,
            extra_usage_info=extra_usage_info,
            host=self.host)

    def export_record(self, context, backup):
        """Export all volume backup metadata details to allow clean import.

        Export backup metadata so it could be re-imported into the database
        without any prerequisite in the backup database.

        :param context: running context
        :param backup: backup object to export
        :returns: backup_record - a description of how to import the backup
        :returns: contains 'backup_url' - how to import the backup, and
        :returns: 'backup_service' describing the needed driver.
        :raises InvalidBackup:
        """
        LOG.info('Export record started, backup: %s.', backup.id)

        expected_status = fields.BackupStatus.AVAILABLE
        actual_status = backup.status
        if actual_status != expected_status:
            err = (_('Export backup aborted, expected backup status '
                     '%(expected_status)s but got %(actual_status)s.') %
                   {'expected_status': expected_status,
                    'actual_status': actual_status})
            raise exception.InvalidBackup(reason=err)

        backup_record = {'backup_service': backup.service}
        if not self._is_our_backup(backup):
            err = (_('Export record aborted, the backup service currently '
                     'configured [%(configured_service)s] is not the '
                     'backup service that was used to create this '
                     'backup [%(backup_service)s].') %
                   {'configured_service': self.driver_name,
                    'backup_service': backup.service})
            raise exception.InvalidBackup(reason=err)

        # Call driver to create backup description string
        try:
            backup_service = self.service(context)
            driver_info = backup_service.export_record(backup)
            backup_url = backup.encode_record(driver_info=driver_info)
            backup_record['backup_url'] = backup_url
        except Exception as err:
            msg = six.text_type(err)
            raise exception.InvalidBackup(reason=msg)

        LOG.info('Export record finished, backup %s exported.', backup.id)
        return backup_record

    def import_record(self,
                      context,
                      backup,
                      backup_service,
                      backup_url,
                      backup_hosts):
        """Import all volume backup metadata details to the backup db.

        :param context: running context
        :param backup: The new backup object for the import
        :param backup_service: The needed backup driver for import
        :param backup_url: An identifier string to locate the backup
        :param backup_hosts: Potential hosts to execute the import
        :raises InvalidBackup:
        :raises ServiceNotFound:
        """
        LOG.info('Import record started, backup_url: %s.', backup_url)

        # Can we import this backup?
        if not self._is_our_backup(backup_service):
            # No, are there additional potential backup hosts in the list?
            if len(backup_hosts) > 0:
                # try the next host on the list, maybe he can import
                first_host = backup_hosts.pop()
                self.backup_rpcapi.import_record(context,
                                                 first_host,
                                                 backup,
                                                 backup_service,
                                                 backup_url,
                                                 backup_hosts)
            else:
                # empty list - we are the last host on the list, fail
                err = _('Import record failed, cannot find backup '
                        'service to perform the import. Request service '
                        '%(service)s.') % {'service': backup_service}
                self._update_backup_error(backup, err)
                raise exception.ServiceNotFound(service_id=backup_service)
        else:
            # Yes...
            try:
                # Deserialize backup record information
                backup_options = backup.decode_record(backup_url)

                # Extract driver specific info and pass it to the driver
                driver_options = backup_options.pop('driver_info', {})
                backup_service = self.service(context)
                backup_service.import_record(backup, driver_options)
            except Exception as err:
                msg = six.text_type(err)
                self._update_backup_error(backup, msg)
                raise exception.InvalidBackup(reason=msg)

            required_import_options = {
                'display_name',
                'display_description',
                'container',
                'size',
                'service_metadata',
                'object_count',
                'id'
            }

            # Check for missing fields in imported data
            missing_opts = required_import_options - set(backup_options)
            if missing_opts:
                msg = (_('Driver successfully decoded imported backup data, '
                         'but there are missing fields (%s).') %
                       ', '.join(missing_opts))
                self._update_backup_error(backup, msg)
                raise exception.InvalidBackup(reason=msg)

            # Confirm the ID from the record in the DB is the right one
            backup_id = backup_options['id']
            if backup_id != backup.id:
                msg = (_('Trying to import backup metadata from id %(meta_id)s'
                         ' into backup %(id)s.') %
                       {'meta_id': backup_id, 'id': backup.id})
                self._update_backup_error(backup, msg)
                raise exception.InvalidBackup(reason=msg)

            # Overwrite some fields
            backup_options['service'] = self.driver_name
            backup_options['availability_zone'] = self.az
            backup_options['host'] = self.host

            # Remove some values which are not actual fields and some that
            # were set by the API node
            for key in ('name', 'user_id', 'project_id', 'deleted_at',
                        'deleted', 'fail_reason', 'status'):
                backup_options.pop(key, None)

            # Update the database
            backup.update(backup_options)
            backup.save()

            # Verify backup
            try:
                if isinstance(backup_service, driver.BackupDriverWithVerify):
                    backup_service.verify(backup.id)
                else:
                    LOG.warning('Backup service %(service)s does not '
                                'support verify. Backup id %(id)s is '
                                'not verified. Skipping verify.',
                                {'service': self.driver_name,
                                 'id': backup.id})
            except exception.InvalidBackup as err:
                with excutils.save_and_reraise_exception():
                    self._update_backup_error(backup, six.text_type(err))

            # Update the backup's status
            backup.update({"status": fields.BackupStatus.AVAILABLE})
            backup.save()

            LOG.info('Import record id %s metadata from driver '
                     'finished.', backup.id)

    def reset_status(self, context, backup, status):
        """Reset volume backup status.

        :param context: running context
        :param backup: The backup object for reset status operation
        :param status: The status to be set
        :raises InvalidBackup:
        :raises BackupVerifyUnsupportedDriver:
        :raises AttributeError:
        """
        LOG.info('Reset backup status started, backup_id: '
                 '%(backup_id)s, status: %(status)s.',
                 {'backup_id': backup.id,
                  'status': status})

        LOG.info('Backup service: %s.', backup.service)
        if not self._is_our_backup(backup):
            err = _('Reset backup status aborted, the backup service'
                    ' currently configured [%(configured_service)s] '
                    'is not the backup service that was used to create'
                    ' this backup [%(backup_service)s].') % \
                {'configured_service': self.driver_name,
                 'backup_service': backup.service}
            raise exception.InvalidBackup(reason=err)

        if backup.service is not None:
            # Verify backup
            try:
                # check whether the backup is ok or not
                if (status == fields.BackupStatus.AVAILABLE and
                        backup['status'] != fields.BackupStatus.RESTORING):
                    # check whether we could verify the backup is ok or not
                    backup_service = self.service(context)
                    if isinstance(backup_service,
                                  driver.BackupDriverWithVerify):
                        backup_service.verify(backup.id)
                        backup.status = status
                        backup.save()
                    # driver does not support verify function
                    else:
                        msg = (_('Backup service %(configured_service)s '
                                 'does not support verify. Backup id'
                                 ' %(id)s is not verified. '
                                 'Skipping verify.') %
                               {'configured_service': self.driver_name,
                                'id': backup.id})
                        raise exception.BackupVerifyUnsupportedDriver(
                            reason=msg)
                # reset status to error or from restoring to available
                else:
                    if (status == fields.BackupStatus.ERROR or
                        (status == fields.BackupStatus.AVAILABLE and
                            backup.status == fields.BackupStatus.RESTORING)):
                        backup.status = status
                        backup.save()
            except exception.InvalidBackup:
                with excutils.save_and_reraise_exception():
                    LOG.error("Backup id %s is not invalid. Skipping reset.",
                              backup.id)
            except exception.BackupVerifyUnsupportedDriver:
                with excutils.save_and_reraise_exception():
                    LOG.error('Backup service %(configured_service)s '
                              'does not support verify. Backup id '
                              '%(id)s is not verified. '
                              'Skipping verify.',
                              {'configured_service': self.driver_name,
                               'id': backup.id})
            except AttributeError:
                msg = (_('Backup service %(service)s does not support '
                         'verify. Backup id %(id)s is not verified. '
                         'Skipping reset.') %
                       {'service': self.driver_name,
                        'id': backup.id})
                LOG.error(msg)
                raise exception.BackupVerifyUnsupportedDriver(
                    reason=msg)

            # Needs to clean temporary volumes and snapshots.
            try:
                self._cleanup_temp_volumes_snapshots_for_one_backup(
                    context, backup)
            except Exception:
                LOG.exception("Problem cleaning temp volumes and "
                              "snapshots for backup %(bkup)s.",
                              {'bkup': backup.id})

            # send notification to ceilometer
            notifier_info = {'id': backup.id, 'update': {'status': status}}
            notifier = rpc.get_notifier('backupStatusUpdate')
            notifier.info(context, "backups.reset_status.end",
                          notifier_info)

    def check_support_to_force_delete(self, context):
        """Check if the backup driver supports force delete operation.

        :param context: running context
        """
        backup_service = self.service(context)
        return backup_service.support_force_delete

    def _attach_device(self, ctxt, backup_device,
                       properties, is_snapshot=False):
        """Attach backup device."""
        if not is_snapshot:
            return self._attach_volume(ctxt, backup_device, properties)
        else:
            return self._attach_snapshot(ctxt, backup_device, properties)

    def _attach_volume(self, context, volume, properties):
        """Attach a volume."""

        try:
            conn = self.volume_rpcapi.initialize_connection(context,
                                                            volume,
                                                            properties)
            return self._connect_device(conn)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.volume_rpcapi.terminate_connection(context, volume,
                                                            properties,
                                                            force=True)
                except Exception:
                    LOG.warning("Failed to terminate the connection "
                                "of volume %(volume_id)s, but it is "
                                "acceptable.",
                                {'volume_id', volume.id})

    def _attach_snapshot(self, ctxt, snapshot, properties):
        """Attach a snapshot."""

        try:
            conn = self.volume_rpcapi.initialize_connection_snapshot(
                ctxt, snapshot, properties)
            return self._connect_device(conn)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    self.volume_rpcapi.terminate_connection_snapshot(
                        ctxt, snapshot, properties, force=True)
                except Exception:
                    LOG.warning("Failed to terminate the connection "
                                "of snapshot %(snapshot_id)s, but it is "
                                "acceptable.",
                                {'snapshot_id', snapshot.id})

    def _connect_device(self, conn):
        """Establish connection to device."""
        use_multipath = CONF.use_multipath_for_image_xfer
        device_scan_attempts = CONF.num_volume_device_scan_tries
        protocol = conn['driver_volume_type']
        connector = utils.brick_get_connector(
            protocol,
            use_multipath=use_multipath,
            device_scan_attempts=device_scan_attempts,
            conn=conn,
            expect_raw_disk=True)
        vol_handle = connector.connect_volume(conn['data'])

        return {'conn': conn, 'device': vol_handle, 'connector': connector}

    def _detach_device(self, ctxt, attach_info, device,
                       properties, is_snapshot=False, force=False,
                       ignore_errors=False):
        """Disconnect the volume or snapshot from the host. """
        connector = attach_info['connector']
        connector.disconnect_volume(attach_info['conn']['data'],
                                    attach_info['device'],
                                    force=force, ignore_errors=ignore_errors)
        rpcapi = self.volume_rpcapi
        if not is_snapshot:
            rpcapi.terminate_connection(ctxt, device, properties,
                                        force=force)
            rpcapi.remove_export(ctxt, device)
        else:
            rpcapi.terminate_connection_snapshot(ctxt, device,
                                                 properties, force=force)
            rpcapi.remove_export_snapshot(ctxt, device)

    def is_working(self):
        return self.is_initialized

    @periodic_task.periodic_task(spacing=CONF.periodic_interval)
    def _report_driver_status(self, context):
        if not self.is_working():
            self.setup_backup_backend(context)
