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

Volume Backups are full copies of persistent volumes stored in Swift object
storage. They are usable without the original object being available. A
volume backup can be restored to the original volume it was created from or
any other available volume with a minimum size of the original volume.
Volume backups can be created, restored, deleted and listed.

**Related Flags**

:backup_topic:  What :mod:`rpc` topic to listen to (default:
                        `cinder-backup`).
:backup_manager:  The module name of a class derived from
                          :class:`manager.Manager` (default:
                          :class:`cinder.backup.manager.Manager`).

"""

from oslo.config import cfg

from cinder import context
from cinder import exception
from cinder import flags
from cinder import manager
from cinder.openstack.common import excutils
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging

LOG = logging.getLogger(__name__)

backup_manager_opts = [
    cfg.StrOpt('backup_service',
               default='cinder.backup.services.swift',
               help='Service to use for backups.'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(backup_manager_opts)


class BackupManager(manager.SchedulerDependentManager):
    """Manages backup of block storage devices."""

    RPC_API_VERSION = '1.0'

    def __init__(self, service_name=None, *args, **kwargs):
        self.service = importutils.import_module(FLAGS.backup_service)
        self.az = FLAGS.storage_availability_zone
        self.volume_manager = importutils.import_object(FLAGS.volume_manager)
        self.driver = self.volume_manager.driver
        super(BackupManager, self).__init__(service_name='backup',
                                            *args, **kwargs)
        self.driver.db = self.db

    def init_host(self):
        """Do any initialization that needs to be run if this is a
           standalone service."""

        ctxt = context.get_admin_context()
        self.driver.do_setup(ctxt)
        self.driver.check_for_setup_error()

        LOG.info(_("Cleaning up incomplete backup operations"))
        volumes = self.db.volume_get_all_by_host(ctxt, self.host)
        for volume in volumes:
            if volume['status'] == 'backing-up':
                LOG.info(_('Resetting volume %s to available '
                           '(was backing-up)') % volume['id'])
                self.volume_manager.detach_volume(ctxt, volume['id'])
            if volume['status'] == 'restoring-backup':
                LOG.info(_('Resetting volume %s to error_restoring '
                           '(was restoring-backup)') % volume['id'])
                self.volume_manager.detach_volume(ctxt, volume['id'])
                self.db.volume_update(ctxt, volume['id'],
                                      {'status': 'error_restoring'})

        # TODO(smulcahy) implement full resume of backup and restore
        # operations on restart (rather than simply resetting)
        backups = self.db.backup_get_all_by_host(ctxt, self.host)
        for backup in backups:
            if backup['status'] == 'creating':
                LOG.info(_('Resetting backup %s to error '
                           '(was creating)') % backup['id'])
                err = 'incomplete backup reset on manager restart'
                self.db.backup_update(ctxt, backup['id'], {'status': 'error',
                                                           'fail_reason': err})
            if backup['status'] == 'restoring':
                LOG.info(_('Resetting backup %s to available '
                           '(was restoring)') % backup['id'])
                self.db.backup_update(ctxt, backup['id'],
                                      {'status': 'available'})
            if backup['status'] == 'deleting':
                LOG.info(_('Resuming delete on backup: %s') % backup['id'])
                self.delete_backup(ctxt, backup['id'])

    def create_backup(self, context, backup_id):
        """
        Create volume backups using configured backup service.
        """
        backup = self.db.backup_get(context, backup_id)
        volume_id = backup['volume_id']
        volume = self.db.volume_get(context, volume_id)
        LOG.info(_('create_backup started, backup: %(backup_id)s for '
                   'volume: %(volume_id)s') % locals())
        self.db.backup_update(context, backup_id, {'host': self.host,
                                                   'service':
                                                   FLAGS.backup_service})

        expected_status = 'backing-up'
        actual_status = volume['status']
        if actual_status != expected_status:
            err = _('create_backup aborted, expected volume status '
                    '%(expected_status)s but got %(actual_status)s') % locals()
            self.db.backup_update(context, backup_id, {'status': 'error',
                                                       'fail_reason': err})
            raise exception.InvalidVolume(reason=err)

        expected_status = 'creating'
        actual_status = backup['status']
        if actual_status != expected_status:
            err = _('create_backup aborted, expected backup status '
                    '%(expected_status)s but got %(actual_status)s') % locals()
            self.db.volume_update(context, volume_id, {'status': 'available'})
            self.db.backup_update(context, backup_id, {'status': 'error',
                                                       'fail_reason': err})
            raise exception.InvalidBackup(reason=err)

        try:
            backup_service = self.service.get_backup_service(context)
            self.driver.backup_volume(context, backup, backup_service)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context, volume_id,
                                      {'status': 'available'})
                self.db.backup_update(context, backup_id,
                                      {'status': 'error',
                                       'fail_reason': unicode(err)})

        self.db.volume_update(context, volume_id, {'status': 'available'})
        self.db.backup_update(context, backup_id, {'status': 'available',
                                                   'size': volume['size'],
                                                   'availability_zone':
                                                   self.az})
        LOG.info(_('create_backup finished. backup: %s'), backup_id)

    def restore_backup(self, context, backup_id, volume_id):
        """
        Restore volume backups from configured backup service.
        """
        LOG.info(_('restore_backup started, restoring backup: %(backup_id)s'
                   ' to volume: %(volume_id)s') % locals())
        backup = self.db.backup_get(context, backup_id)
        volume = self.db.volume_get(context, volume_id)
        self.db.backup_update(context, backup_id, {'host': self.host})

        expected_status = 'restoring-backup'
        actual_status = volume['status']
        if actual_status != expected_status:
            err = _('restore_backup aborted, expected volume status '
                    '%(expected_status)s but got %(actual_status)s') % locals()
            self.db.backup_update(context, backup_id, {'status': 'available'})
            raise exception.InvalidVolume(reason=err)

        expected_status = 'restoring'
        actual_status = backup['status']
        if actual_status != expected_status:
            err = _('restore_backup aborted, expected backup status '
                    '%(expected_status)s but got %(actual_status)s') % locals()
            self.db.backup_update(context, backup_id, {'status': 'error',
                                                       'fail_reason': err})
            self.db.volume_update(context, volume_id, {'status': 'error'})
            raise exception.InvalidBackup(reason=err)

        if volume['size'] > backup['size']:
            LOG.warn('volume: %s, size: %d is larger than backup: %s, '
                     'size: %d, continuing with restore',
                     volume['id'], volume['size'],
                     backup['id'], backup['size'])

        backup_service = backup['service']
        configured_service = FLAGS.backup_service
        if backup_service != configured_service:
            err = _('restore_backup aborted, the backup service currently'
                    ' configured [%(configured_service)s] is not the'
                    ' backup service that was used to create this'
                    ' backup [%(backup_service)s]') % locals()
            self.db.backup_update(context, backup_id, {'status': 'available'})
            self.db.volume_update(context, volume_id, {'status': 'error'})
            raise exception.InvalidBackup(reason=err)

        try:
            backup_service = self.service.get_backup_service(context)
            self.driver.restore_backup(context, backup, volume,
                                       backup_service)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context, volume_id,
                                      {'status': 'error_restoring'})
                self.db.backup_update(context, backup_id,
                                      {'status': 'available'})

        self.db.volume_update(context, volume_id, {'status': 'available'})
        self.db.backup_update(context, backup_id, {'status': 'available'})
        LOG.info(_('restore_backup finished, backup: %(backup_id)s restored'
                   ' to volume: %(volume_id)s') % locals())

    def delete_backup(self, context, backup_id):
        """
        Delete volume backup from configured backup service.
        """
        backup = self.db.backup_get(context, backup_id)
        LOG.info(_('delete_backup started, backup: %s'), backup_id)
        self.db.backup_update(context, backup_id, {'host': self.host})

        expected_status = 'deleting'
        actual_status = backup['status']
        if actual_status != expected_status:
            err = _('delete_backup aborted, expected backup status '
                    '%(expected_status)s but got %(actual_status)s') % locals()
            self.db.backup_update(context, backup_id, {'status': 'error',
                                                       'fail_reason': err})
            raise exception.InvalidBackup(reason=err)

        backup_service = backup['service']
        configured_service = FLAGS.backup_service
        if backup_service != configured_service:
            err = _('delete_backup aborted, the backup service currently'
                    ' configured [%(configured_service)s] is not the'
                    ' backup service that was used to create this'
                    ' backup [%(backup_service)s]') % locals()
            self.db.backup_update(context, backup_id, {'status': 'available'})
            raise exception.InvalidBackup(reason=err)

        try:
            backup_service = self.service.get_backup_service(context)
            backup_service.delete(backup)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.backup_update(context, backup_id, {'status': 'error',
                                                           'fail_reason':
                                                           unicode(err)})

        context = context.elevated()
        self.db.backup_destroy(context, backup_id)
        LOG.info(_('delete_backup finished, backup %s deleted'), backup_id)
