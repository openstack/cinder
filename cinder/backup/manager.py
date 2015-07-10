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

:backup_topic:  What :mod:`rpc` topic to listen to (default:
                        `cinder-backup`).
:backup_manager:  The module name of a class derived from
                          :class:`manager.Manager` (default:
                          :class:`cinder.backup.manager.Manager`).

"""

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import excutils
from oslo_utils import importutils
import six

from cinder.backup import driver
from cinder.backup import rpcapi as backup_rpcapi
from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import manager
from cinder import objects
from cinder import quota
from cinder import rpc
from cinder import utils
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

backup_manager_opts = [
    cfg.StrOpt('backup_driver',
               default='cinder.backup.drivers.swift',
               help='Driver to use for backups.',
               deprecated_name='backup_service'),
]

# This map doesn't need to be extended in the future since it's only
# for old backup services
mapper = {'cinder.backup.services.swift': 'cinder.backup.drivers.swift',
          'cinder.backup.services.ceph': 'cinder.backup.drivers.ceph'}

CONF = cfg.CONF
CONF.register_opts(backup_manager_opts)
QUOTAS = quota.QUOTAS


class BackupManager(manager.SchedulerDependentManager):
    """Manages backup of block storage devices."""

    RPC_API_VERSION = '1.0'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, service_name=None, *args, **kwargs):
        self.service = importutils.import_module(self.driver_name)
        self.az = CONF.storage_availability_zone
        self.volume_managers = {}
        self._setup_volume_drivers()
        self.backup_rpcapi = backup_rpcapi.BackupAPI()
        super(BackupManager, self).__init__(service_name='backup',
                                            *args, **kwargs)

    @property
    def driver_name(self):
        """This function maps old backup services to backup drivers."""

        return self._map_service_to_driver(CONF.backup_driver)

    def _map_service_to_driver(self, service):
        """Maps services to drivers."""

        if service in mapper:
            return mapper[service]
        return service

    @property
    def driver(self):
        return self._get_driver()

    def _get_volume_backend(self, host=None, allow_null_host=False):
        if host is None:
            if not allow_null_host:
                msg = _("NULL host not allowed for volume backend lookup.")
                raise exception.BackupFailedToGetVolumeBackend(msg)
        else:
            LOG.debug("Checking hostname '%s' for backend info.", host)
            part = host.partition('@')
            if (part[1] == '@') and (part[2] != ''):
                backend = part[2]
                LOG.debug("Got backend '%s'.", backend)
                return backend

        LOG.info(_LI("Backend not found in hostname (%s) so using default."),
                 host)

        if 'default' not in self.volume_managers:
            # For multi-backend we just pick the top of the list.
            return self.volume_managers.keys()[0]

        return 'default'

    def _get_manager(self, backend):
        LOG.debug("Manager requested for volume_backend '%s'.",
                  backend)
        if backend is None:
            LOG.debug("Fetching default backend.")
            backend = self._get_volume_backend(allow_null_host=True)
        if backend not in self.volume_managers:
            msg = (_("Volume manager for backend '%s' does not exist.") %
                   (backend))
            raise exception.BackupFailedToGetVolumeBackend(msg)
        return self.volume_managers[backend]

    def _get_driver(self, backend=None):
        LOG.debug("Driver requested for volume_backend '%s'.",
                  backend)
        if backend is None:
            LOG.debug("Fetching default backend.")
            backend = self._get_volume_backend(allow_null_host=True)
        mgr = self._get_manager(backend)
        mgr.driver.db = self.db
        return mgr.driver

    def _setup_volume_drivers(self):
        if CONF.enabled_backends:
            for backend in CONF.enabled_backends:
                host = "%s@%s" % (CONF.host, backend)
                mgr = importutils.import_object(CONF.volume_manager,
                                                host=host,
                                                service_name=backend)
                config = mgr.configuration
                backend_name = config.safe_get('volume_backend_name')
                LOG.debug("Registering backend %(backend)s (host=%(host)s "
                          "backend_name=%(backend_name)s).",
                          {'backend': backend, 'host': host,
                           'backend_name': backend_name})
                self.volume_managers[backend] = mgr
        else:
            default = importutils.import_object(CONF.volume_manager)
            LOG.debug("Registering default backend %s.", default)
            self.volume_managers['default'] = default

    def _init_volume_driver(self, ctxt, driver):
        LOG.info(_LI("Starting volume driver %(driver_name)s (%(version)s)."),
                 {'driver_name': driver.__class__.__name__,
                  'version': driver.get_version()})
        try:
            driver.do_setup(ctxt)
            driver.check_for_setup_error()
        except Exception:
            LOG.exception(_LE("Error encountered during initialization of "
                              "driver: %(name)s."),
                          {'name': driver.__class__.__name__})
            # we don't want to continue since we failed
            # to initialize the driver correctly.
            return

        driver.set_initialized()

    def _update_backup_error(self, backup, context, err):
        backup.status = 'error'
        backup.fail_reason = err
        backup.save()

    def init_host(self):
        """Do any initialization that needs to be run if this is a
           standalone service.
        """
        ctxt = context.get_admin_context()

        for mgr in self.volume_managers.values():
            self._init_volume_driver(ctxt, mgr.driver)

        LOG.info(_LI("Cleaning up incomplete backup operations."))
        volumes = self.db.volume_get_all_by_host(ctxt, self.host)
        for volume in volumes:
            volume_host = volume_utils.extract_host(volume['host'], 'backend')
            backend = self._get_volume_backend(host=volume_host)
            attachments = volume['volume_attachment']
            if attachments:
                if volume['status'] == 'backing-up':
                    LOG.info(_LI('Resetting volume %s to available '
                                 '(was backing-up).'), volume['id'])
                    mgr = self._get_manager(backend)
                    for attachment in attachments:
                        if (attachment['attached_host'] == self.host and
                           attachment['instance_uuid'] is None):
                            mgr.detach_volume(ctxt, volume['id'],
                                              attachment['id'])
                if volume['status'] == 'restoring-backup':
                    LOG.info(_LI('setting volume %s to error_restoring '
                                 '(was restoring-backup).'), volume['id'])
                    mgr = self._get_manager(backend)
                    for attachment in attachments:
                        if (attachment['attached_host'] == self.host and
                           attachment['instance_uuid'] is None):
                            mgr.detach_volume(ctxt, volume['id'],
                                              attachment['id'])
                    self.db.volume_update(ctxt, volume['id'],
                                          {'status': 'error_restoring'})

        # TODO(smulcahy) implement full resume of backup and restore
        # operations on restart (rather than simply resetting)
        backups = objects.BackupList.get_all_by_host(ctxt, self.host)
        for backup in backups:
            if backup['status'] == 'creating':
                LOG.info(_LI('Resetting backup %s to error (was creating).'),
                         backup['id'])
                err = 'incomplete backup reset on manager restart'
                self._update_backup_error(backup, ctxt, err)
            if backup['status'] == 'restoring':
                LOG.info(_LI('Resetting backup %s to '
                             'available (was restoring).'),
                         backup['id'])
                backup.status = 'available'
                backup.save()
            if backup['status'] == 'deleting':
                LOG.info(_LI('Resuming delete on backup: %s.'), backup['id'])
                self.delete_backup(ctxt, backup)

    def create_backup(self, context, backup):
        """Create volume backups using configured backup service."""
        volume_id = backup.volume_id
        volume = self.db.volume_get(context, volume_id)
        LOG.info(_LI('Create backup started, backup: %(backup_id)s '
                     'volume: %(volume_id)s.'),
                 {'backup_id': backup.id, 'volume_id': volume_id})

        self._notify_about_backup_usage(context, backup, "create.start")
        volume_host = volume_utils.extract_host(volume['host'], 'backend')
        backend = self._get_volume_backend(host=volume_host)

        backup.host = self.host
        backup.service = self.driver_name
        backup.save()

        expected_status = 'backing-up'
        actual_status = volume['status']
        if actual_status != expected_status:
            err = _('Create backup aborted, expected volume status '
                    '%(expected_status)s but got %(actual_status)s.') % {
                'expected_status': expected_status,
                'actual_status': actual_status,
            }
            self._update_backup_error(backup, context, err)
            raise exception.InvalidVolume(reason=err)

        expected_status = 'creating'
        actual_status = backup.status
        if actual_status != expected_status:
            err = _('Create backup aborted, expected backup status '
                    '%(expected_status)s but got %(actual_status)s.') % {
                'expected_status': expected_status,
                'actual_status': actual_status,
            }
            self._update_backup_error(backup, context, err)
            backup.save()
            raise exception.InvalidBackup(reason=err)

        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught,
            # the volume status will be set back to available and
            # the backup status to 'error'
            utils.require_driver_initialized(self.driver)

            backup_service = self.service.get_backup_driver(context)
            self._get_driver(backend).backup_volume(context, backup,
                                                    backup_service)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context, volume_id,
                                      {'status': 'available'})
                self._update_backup_error(backup, context, six.text_type(err))

        self.db.volume_update(context, volume_id, {'status': 'available'})
        backup.status = 'available'
        backup.size = volume['size']
        backup.availability_zone = self.az
        backup.save()
        LOG.info(_LI('Create backup finished. backup: %s.'), backup.id)
        self._notify_about_backup_usage(context, backup, "create.end")

    def restore_backup(self, context, backup, volume_id):
        """Restore volume backups from configured backup service."""
        LOG.info(_LI('Restore backup started, backup: %(backup_id)s '
                     'volume: %(volume_id)s.'),
                 {'backup_id': backup.id, 'volume_id': volume_id})

        volume = self.db.volume_get(context, volume_id)
        volume_host = volume_utils.extract_host(volume['host'], 'backend')
        backend = self._get_volume_backend(host=volume_host)
        self._notify_about_backup_usage(context, backup, "restore.start")

        backup.host = self.host
        backup.save()

        expected_status = 'restoring-backup'
        actual_status = volume['status']
        if actual_status != expected_status:
            err = (_('Restore backup aborted, expected volume status '
                     '%(expected_status)s but got %(actual_status)s.') %
                   {'expected_status': expected_status,
                    'actual_status': actual_status})
            backup.status = 'available'
            backup.save()
            raise exception.InvalidVolume(reason=err)

        expected_status = 'restoring'
        actual_status = backup['status']
        if actual_status != expected_status:
            err = (_('Restore backup aborted: expected backup status '
                     '%(expected_status)s but got %(actual_status)s.') %
                   {'expected_status': expected_status,
                    'actual_status': actual_status})
            self._update_backup_error(backup, context, err)
            self.db.volume_update(context, volume_id, {'status': 'error'})
            raise exception.InvalidBackup(reason=err)

        if volume['size'] > backup['size']:
            LOG.info(_LI('Volume: %(vol_id)s, size: %(vol_size)d is '
                         'larger than backup: %(backup_id)s, '
                         'size: %(backup_size)d, continuing with restore.'),
                     {'vol_id': volume['id'],
                      'vol_size': volume['size'],
                      'backup_id': backup['id'],
                      'backup_size': backup['size']})

        backup_service = self._map_service_to_driver(backup['service'])
        configured_service = self.driver_name
        if backup_service != configured_service:
            err = _('Restore backup aborted, the backup service currently'
                    ' configured [%(configured_service)s] is not the'
                    ' backup service that was used to create this'
                    ' backup [%(backup_service)s].') % {
                'configured_service': configured_service,
                'backup_service': backup_service,
            }
            backup.status = 'available'
            backup.save()
            self.db.volume_update(context, volume_id, {'status': 'error'})
            raise exception.InvalidBackup(reason=err)

        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught,
            # the volume status will be set back to available and
            # the backup status to 'error'
            utils.require_driver_initialized(self.driver)

            backup_service = self.service.get_backup_driver(context)
            self._get_driver(backend).restore_backup(context, backup,
                                                     volume,
                                                     backup_service)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context, volume_id,
                                      {'status': 'error_restoring'})
                backup.status = 'available'
                backup.save()

        self.db.volume_update(context, volume_id, {'status': 'available'})
        backup.status = 'available'
        backup.save()
        LOG.info(_LI('Restore backup finished, backup %(backup_id)s restored'
                     ' to volume %(volume_id)s.'),
                 {'backup_id': backup.id, 'volume_id': volume_id})
        self._notify_about_backup_usage(context, backup, "restore.end")

    def delete_backup(self, context, backup):
        """Delete volume backup from configured backup service."""
        LOG.info(_LI('Delete backup started, backup: %s.'), backup.id)

        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the backup status updated. Fail early since there
            # are no other status to change but backup's
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized as err:
            with excutils.save_and_reraise_exception():
                self._update_backup_error(backup, context, six.text_type(err))

        self._notify_about_backup_usage(context, backup, "delete.start")
        backup.host = self.host
        backup.save()

        expected_status = 'deleting'
        actual_status = backup.status
        if actual_status != expected_status:
            err = _('Delete_backup aborted, expected backup status '
                    '%(expected_status)s but got %(actual_status)s.') \
                % {'expected_status': expected_status,
                   'actual_status': actual_status}
            self._update_backup_error(backup, context, err)
            raise exception.InvalidBackup(reason=err)

        backup_service = self._map_service_to_driver(backup['service'])
        if backup_service is not None:
            configured_service = self.driver_name
            if backup_service != configured_service:
                err = _('Delete backup aborted, the backup service currently'
                        ' configured [%(configured_service)s] is not the'
                        ' backup service that was used to create this'
                        ' backup [%(backup_service)s].')\
                    % {'configured_service': configured_service,
                       'backup_service': backup_service}
                self._update_backup_error(backup, context, err)
                raise exception.InvalidBackup(reason=err)

            try:
                backup_service = self.service.get_backup_driver(context)
                backup_service.delete(backup)
            except Exception as err:
                with excutils.save_and_reraise_exception():
                    self._update_backup_error(backup, context,
                                              six.text_type(err))

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
            LOG.exception(_LE("Failed to update usages deleting backup"))

        backup.destroy()

        # Commit the reservations
        if reservations:
            QUOTAS.commit(context, reservations,
                          project_id=backup.project_id)

        LOG.info(_LI('Delete backup finished, backup %s deleted.'), backup.id)
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
        :raises: InvalidBackup
        """
        LOG.info(_LI('Export record started, backup: %s.'), backup.id)

        expected_status = 'available'
        actual_status = backup.status
        if actual_status != expected_status:
            err = (_('Export backup aborted, expected backup status '
                     '%(expected_status)s but got %(actual_status)s.') %
                   {'expected_status': expected_status,
                    'actual_status': actual_status})
            raise exception.InvalidBackup(reason=err)

        backup_record = {}
        backup_record['backup_service'] = backup.service
        backup_service = self._map_service_to_driver(backup.service)
        configured_service = self.driver_name
        if backup_service != configured_service:
            err = (_('Export record aborted, the backup service currently'
                     ' configured [%(configured_service)s] is not the'
                     ' backup service that was used to create this'
                     ' backup [%(backup_service)s].') %
                   {'configured_service': configured_service,
                    'backup_service': backup_service})
            raise exception.InvalidBackup(reason=err)

        # Call driver to create backup description string
        try:
            utils.require_driver_initialized(self.driver)
            backup_service = self.service.get_backup_driver(context)
            backup_url = backup_service.export_record(backup)
            backup_record['backup_url'] = backup_url
        except Exception as err:
            msg = six.text_type(err)
            raise exception.InvalidBackup(reason=msg)

        LOG.info(_LI('Export record finished, backup %s exported.'), backup.id)
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
        :raises: InvalidBackup
        :raises: ServiceNotFound
        """
        LOG.info(_LI('Import record started, backup_url: %s.'), backup_url)

        # Can we import this backup?
        if (backup_service != self.driver_name):
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
                        '%(service)s') % {'service': backup_service}
                self._update_backup_error(backup, context, err)
                raise exception.ServiceNotFound(service_id=backup_service)
        else:
            # Yes...
            try:
                utils.require_driver_initialized(self.driver)
                backup_service = self.service.get_backup_driver(context)
                backup_options = backup_service.import_record(backup_url)
            except Exception as err:
                msg = six.text_type(err)
                self._update_backup_error(backup, context, msg)
                raise exception.InvalidBackup(reason=msg)

            required_import_options = ['display_name',
                                       'display_description',
                                       'container',
                                       'size',
                                       'service_metadata',
                                       'service',
                                       'object_count']

            backup_update = {}
            backup_update['status'] = 'available'
            backup_update['service'] = self.driver_name
            backup_update['availability_zone'] = self.az
            backup_update['host'] = self.host
            for entry in required_import_options:
                if entry not in backup_options:
                    msg = (_('Backup metadata received from driver for '
                             'import is missing %s.'), entry)
                    self._update_backup_error(backup, context, msg)
                    raise exception.InvalidBackup(reason=msg)
                backup_update[entry] = backup_options[entry]
            # Update the database
            backup.update(backup_update)
            backup.save()

            # Verify backup
            try:
                if isinstance(backup_service, driver.BackupDriverWithVerify):
                    backup_service.verify(backup.id)
                else:
                    LOG.warning(_LW('Backup service %(service)s does not '
                                    'support verify. Backup id %(id)s is '
                                    'not verified. Skipping verify.'),
                                {'service': self.driver_name,
                                 'id': backup.id})
            except exception.InvalidBackup as err:
                with excutils.save_and_reraise_exception():
                    self._update_backup_error(backup, context,
                                              six.text_type(err))

            LOG.info(_LI('Import record id %s metadata from driver '
                         'finished.'), backup.id)

    def reset_status(self, context, backup, status):
        """Reset volume backup status.

        :param context: running context
        :param backup: The backup object for reset status operation
        :param status: The status to be set
        :raises: InvalidBackup
        :raises: BackupVerifyUnsupportedDriver
        :raises: AttributeError
        """
        LOG.info(_LI('Reset backup status started, backup_id: '
                     '%(backup_id)s, status: %(status)s.'),
                 {'backup_id': backup.id,
                  'status': status})
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the backup status updated. Fail early since there
            # are no other status to change but backup's
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Backup driver has not been initialized"))

        backup_service = self._map_service_to_driver(backup.service)
        LOG.info(_LI('Backup service: %s.'), backup_service)
        if backup_service is not None:
            configured_service = self.driver_name
            if backup_service != configured_service:
                err = _('Reset backup status aborted, the backup service'
                        ' currently configured [%(configured_service)s] '
                        'is not the backup service that was used to create'
                        ' this backup [%(backup_service)s].') % \
                    {'configured_service': configured_service,
                     'backup_service': backup_service}
                raise exception.InvalidBackup(reason=err)
            # Verify backup
            try:
                # check whether the backup is ok or not
                if status == 'available' and backup['status'] != 'restoring':
                    # check whether we could verify the backup is ok or not
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
                    if (status == 'error' or
                        (status == 'available' and
                            backup.status == 'restoring')):
                        backup.status = status
                        backup.save()
            except exception.InvalidBackup:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE("Backup id %s is not invalid. "
                                  "Skipping reset."), backup.id)
            except exception.BackupVerifyUnsupportedDriver:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Backup service %(configured_service)s '
                                  'does not support verify. Backup id '
                                  '%(id)s is not verified. '
                                  'Skipping verify.'),
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

            # send notification to ceilometer
            notifier_info = {'id': backup.id, 'update': {'status': status}}
            notifier = rpc.get_notifier('backupStatusUpdate')
            notifier.info(context, "backups.reset_status.end",
                          notifier_info)
