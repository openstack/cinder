# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Volume manager manages creating, attaching, detaching, and persistent storage.

Persistent storage volumes keep their state independent of instances.  You can
attach to an instance, terminate the instance, spawn a new instance (even
one from a different image) and re-attach the volume with the same data
intact.

**Related Flags**

:volume_topic:  What :mod:`rpc` topic to listen to (default: `cinder-volume`).
:volume_manager:  The module name of a class derived from
                  :class:`manager.Manager` (default:
                  :class:`cinder.volume.manager.Manager`).
:volume_driver:  Used by :class:`Manager`.  Defaults to
                 :class:`cinder.volume.drivers.lvm.LVMISCSIDriver`.
:volume_group:  Name of the group that will contain exported volumes (default:
                `cinder-volumes`)
:num_shell_tries:  Number of times to attempt to run commands (default: 3)

"""


import time

from oslo.config import cfg

from cinder.brick.initiator import connector as initiator
from cinder import compute
from cinder import context
from cinder import exception
from cinder.image import glance
from cinder import manager
from cinder.openstack.common import excutils
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import periodic_task
from cinder.openstack.common import timeutils
from cinder.openstack.common import uuidutils
from cinder import quota
from cinder import utils
from cinder.volume.configuration import Configuration
from cinder.volume.flows import create_volume
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types

from cinder.taskflow import states

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS

volume_manager_opts = [
    cfg.StrOpt('volume_driver',
               default='cinder.volume.drivers.lvm.LVMISCSIDriver',
               help='Driver to use for volume creation'),
    cfg.IntOpt('migration_create_volume_timeout_secs',
               default=300,
               help='Timeout for creating the volume to migrate to '
                    'when performing volume migration (seconds)'),
]

CONF = cfg.CONF
CONF.register_opts(volume_manager_opts)

MAPPING = {
    'cinder.volume.driver.RBDDriver': 'cinder.volume.drivers.rbd.RBDDriver',
    'cinder.volume.driver.SheepdogDriver':
    'cinder.volume.drivers.sheepdog.SheepdogDriver',
    'cinder.volume.nexenta.volume.NexentaDriver':
    'cinder.volume.drivers.nexenta.volume.NexentaDriver',
    'cinder.volume.san.SanISCSIDriver':
    'cinder.volume.drivers.san.san.SanISCSIDriver',
    'cinder.volume.san.SolarisISCSIDriver':
    'cinder.volume.drivers.san.solaris.SolarisISCSIDriver',
    'cinder.volume.san.HpSanISCSIDriver':
    'cinder.volume.drivers.san.hp_lefthand.HpSanISCSIDriver',
    'cinder.volume.nfs.NfsDriver':
    'cinder.volume.drivers.nfs.NfsDriver',
    'cinder.volume.solidfire.SolidFire':
    'cinder.volume.drivers.solidfire.SolidFireDriver',
    'cinder.volume.drivers.solidfire.SolidFire':
    'cinder.volume.drivers.solidfire.SolidFireDriver',
    'cinder.volume.storwize_svc.StorwizeSVCDriver':
    'cinder.volume.drivers.storwize_svc.StorwizeSVCDriver',
    'cinder.volume.windows.WindowsDriver':
    'cinder.volume.drivers.windows.windows.WindowsDriver',
    'cinder.volume.drivers.windows.WindowsDriver':
    'cinder.volume.drivers.windows.windows.WindowsDriver',
    'cinder.volume.xiv.XIVDriver':
    'cinder.volume.drivers.xiv_ds8k.XIVDS8KDriver',
    'cinder.volume.drivers.xiv.XIVDriver':
    'cinder.volume.drivers.xiv_ds8k.XIVDS8KDriver',
    'cinder.volume.zadara.ZadaraVPSAISCSIDriver':
    'cinder.volume.drivers.zadara.ZadaraVPSAISCSIDriver',
    'cinder.volume.driver.ISCSIDriver':
    'cinder.volume.drivers.lvm.LVMISCSIDriver',
    'cinder.volume.netapp.NetAppISCSIDriver':
    'cinder.volume.drivers.netapp.common.Deprecated',
    'cinder.volume.drivers.netapp.iscsi.NetAppISCSIDriver':
    'cinder.volume.drivers.netapp.common.Deprecated',
    'cinder.volume.netapp.NetAppCmodeISCSIDriver':
    'cinder.volume.drivers.netapp.common.Deprecated',
    'cinder.volume.drivers.netapp.iscsi.NetAppCmodeISCSIDriver':
    'cinder.volume.drivers.netapp.common.Deprecated',
    'cinder.volume.netapp_nfs.NetAppNFSDriver':
    'cinder.volume.drivers.netapp.common.Deprecated',
    'cinder.volume.drivers.netapp.nfs.NetAppNFSDriver':
    'cinder.volume.drivers.netapp.common.Deprecated',
    'cinder.volume.drivers.netapp.nfs.NetAppCmodeNfsDriver':
    'cinder.volume.drivers.netapp.common.Deprecated',
    'cinder.volume.drivers.huawei.HuaweiISCSIDriver':
    'cinder.volume.drivers.huawei.HuaweiVolumeDriver'}


class VolumeManager(manager.SchedulerDependentManager):
    """Manages attachable block storage devices."""

    RPC_API_VERSION = '1.11'

    def __init__(self, volume_driver=None, service_name=None,
                 *args, **kwargs):
        """Load the driver from the one specified in args, or from flags."""
        # update_service_capabilities needs service_name to be volume
        super(VolumeManager, self).__init__(service_name='volume',
                                            *args, **kwargs)
        self.configuration = Configuration(volume_manager_opts,
                                           config_group=service_name)
        if not volume_driver:
            # Get from configuration, which will get the default
            # if its not using the multi backend
            volume_driver = self.configuration.volume_driver
        if volume_driver in MAPPING:
            LOG.warn(_("Driver path %s is deprecated, update your "
                       "configuration to the new path."), volume_driver)
            volume_driver = MAPPING[volume_driver]
        self.driver = importutils.import_object(
            volume_driver,
            configuration=self.configuration,
            db=self.db)

    def init_host(self):
        """Do any initialization that needs to be run if this is a
           standalone service.
        """

        ctxt = context.get_admin_context()
        LOG.info(_("Starting volume driver %(driver_name)s (%(version)s)") %
                 {'driver_name': self.driver.__class__.__name__,
                  'version': self.driver.get_version()})
        self.driver.do_setup(ctxt)
        self.driver.check_for_setup_error()

        volumes = self.db.volume_get_all_by_host(ctxt, self.host)
        LOG.debug(_("Re-exporting %s volumes"), len(volumes))
        for volume in volumes:
            if volume['status'] in ['available', 'in-use']:
                self.driver.ensure_export(ctxt, volume)
            elif volume['status'] == 'downloading':
                LOG.info(_("volume %s stuck in a downloading state"),
                         volume['id'])
                self.driver.clear_download(ctxt, volume)
                self.db.volume_update(ctxt, volume['id'], {'status': 'error'})
            else:
                LOG.info(_("volume %s: skipping export"), volume['id'])

        LOG.debug(_('Resuming any in progress delete operations'))
        for volume in volumes:
            if volume['status'] == 'deleting':
                LOG.info(_('Resuming delete on volume: %s') % volume['id'])
                self.delete_volume(ctxt, volume['id'])

        # collect and publish service capabilities
        self.publish_service_capabilities(ctxt)

    def create_volume(self, context, volume_id, request_spec=None,
                      filter_properties=None, allow_reschedule=True,
                      snapshot_id=None, image_id=None, source_volid=None):
        """Creates and exports the volume."""

        flow = create_volume.get_manager_flow(
            self.db,
            self.driver,
            self.scheduler_rpcapi,
            self.host,
            volume_id,
            request_spec=request_spec,
            filter_properties=filter_properties,
            allow_reschedule=allow_reschedule,
            snapshot_id=snapshot_id,
            image_id=image_id,
            source_volid=source_volid,
            reschedule_context=context.deepcopy())

        assert flow, _('Manager volume flow not retrieved')

        flow.run(context.elevated())
        if flow.state != states.SUCCESS:
            raise exception.CinderException(_("Failed to successfully complete"
                                              " manager volume workflow"))

        self._reset_stats()
        return volume_id

    def delete_volume(self, context, volume_id):
        """Deletes and unexports volume."""
        context = context.elevated()
        volume_ref = self.db.volume_get(context, volume_id)

        if context.project_id != volume_ref['project_id']:
            project_id = volume_ref['project_id']
        else:
            project_id = context.project_id

        LOG.info(_("volume %s: deleting"), volume_ref['id'])
        if volume_ref['attach_status'] == "attached":
            # Volume is still attached, need to detach first
            raise exception.VolumeAttached(volume_id=volume_id)
        if volume_ref['host'] != self.host:
            raise exception.InvalidVolume(
                reason=_("volume is not local to this node"))

        self._notify_about_volume_usage(context, volume_ref, "delete.start")
        self._reset_stats()
        try:
            LOG.debug(_("volume %s: removing export"), volume_ref['id'])
            self.driver.remove_export(context, volume_ref)
            LOG.debug(_("volume %s: deleting"), volume_ref['id'])
            self.driver.delete_volume(volume_ref)
        except exception.VolumeIsBusy:
            LOG.error(_("Cannot delete volume %s: volume is busy"),
                      volume_ref['id'])
            self.driver.ensure_export(context, volume_ref)
            self.db.volume_update(context, volume_ref['id'],
                                  {'status': 'available'})
            return True
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_ref['id'],
                                      {'status': 'error_deleting'})

        # If deleting the source volume in a migration, we want to skip quotas
        # and other database updates.
        if volume_ref['migration_status']:
            return True

        # Get reservations
        try:
            reserve_opts = {'volumes': -1, 'gigabytes': -volume_ref['size']}
            QUOTAS.add_volume_type_opts(context,
                                        reserve_opts,
                                        volume_ref.get('volume_type_id'))
            reservations = QUOTAS.reserve(context,
                                          project_id=project_id,
                                          **reserve_opts)
        except Exception:
            reservations = None
            LOG.exception(_("Failed to update usages deleting volume"))

        # Delete glance metadata if it exists
        try:
            self.db.volume_glance_metadata_delete_by_volume(context, volume_id)
            LOG.debug(_("volume %s: glance metadata deleted"),
                      volume_ref['id'])
        except exception.GlanceMetadataNotFound:
            LOG.debug(_("no glance metadata found for volume %s"),
                      volume_ref['id'])

        self.db.volume_destroy(context, volume_id)
        LOG.info(_("volume %s: deleted successfully"), volume_ref['id'])
        self._notify_about_volume_usage(context, volume_ref, "delete.end")

        # Commit the reservations
        if reservations:
            QUOTAS.commit(context, reservations, project_id=project_id)

        self.publish_service_capabilities(context)

        return True

    def create_snapshot(self, context, volume_id, snapshot_id):
        """Creates and exports the snapshot."""
        caller_context = context
        context = context.elevated()
        snapshot_ref = self.db.snapshot_get(context, snapshot_id)
        LOG.info(_("snapshot %s: creating"), snapshot_ref['id'])
        self._notify_about_snapshot_usage(
            context, snapshot_ref, "create.start")

        try:
            LOG.debug(_("snapshot %(snap_id)s: creating"),
                      {'snap_id': snapshot_ref['id']})

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            snapshot_ref['context'] = caller_context

            model_update = self.driver.create_snapshot(snapshot_ref)
            if model_update:
                self.db.snapshot_update(context, snapshot_ref['id'],
                                        model_update)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.snapshot_update(context,
                                        snapshot_ref['id'],
                                        {'status': 'error'})

        self.db.snapshot_update(context,
                                snapshot_ref['id'], {'status': 'available',
                                                     'progress': '100%'})

        vol_ref = self.db.volume_get(context, volume_id)
        if vol_ref.bootable:
            try:
                self.db.volume_glance_metadata_copy_to_snapshot(
                    context, snapshot_ref['id'], volume_id)
            except exception.CinderException as ex:
                LOG.exception(_("Failed updating %(snapshot_id)s"
                                " metadata using the provided volumes"
                                " %(volume_id)s metadata") %
                              {'volume_id': volume_id,
                               'snapshot_id': snapshot_id})
                raise exception.MetadataCopyFailure(reason=ex)
        LOG.info(_("snapshot %s: created successfully"), snapshot_ref['id'])
        self._notify_about_snapshot_usage(context, snapshot_ref, "create.end")
        return snapshot_id

    def delete_snapshot(self, context, snapshot_id):
        """Deletes and unexports snapshot."""
        caller_context = context
        context = context.elevated()
        snapshot_ref = self.db.snapshot_get(context, snapshot_id)
        project_id = snapshot_ref['project_id']
        LOG.info(_("snapshot %s: deleting"), snapshot_ref['id'])
        self._notify_about_snapshot_usage(
            context, snapshot_ref, "delete.start")

        try:
            LOG.debug(_("snapshot %s: deleting"), snapshot_ref['id'])

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            snapshot_ref['context'] = caller_context

            self.driver.delete_snapshot(snapshot_ref)
        except exception.SnapshotIsBusy:
            LOG.error(_("Cannot delete snapshot %s: snapshot is busy"),
                      snapshot_ref['id'])
            self.db.snapshot_update(context,
                                    snapshot_ref['id'],
                                    {'status': 'available'})
            return True
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.snapshot_update(context,
                                        snapshot_ref['id'],
                                        {'status': 'error_deleting'})

        # Get reservations
        try:
            if CONF.no_snapshot_gb_quota:
                reserve_opts = {'snapshots': -1}
            else:
                reserve_opts = {
                    'snapshots': -1,
                    'gigabytes': -snapshot_ref['volume_size'],
                }
            volume_ref = self.db.volume_get(context, snapshot_ref['volume_id'])
            QUOTAS.add_volume_type_opts(context,
                                        reserve_opts,
                                        volume_ref.get('volume_type_id'))
            reservations = QUOTAS.reserve(context,
                                          project_id=project_id,
                                          **reserve_opts)
        except Exception:
            reservations = None
            LOG.exception(_("Failed to update usages deleting snapshot"))
        self.db.volume_glance_metadata_delete_by_snapshot(context, snapshot_id)
        self.db.snapshot_destroy(context, snapshot_id)
        LOG.info(_("snapshot %s: deleted successfully"), snapshot_ref['id'])
        self._notify_about_snapshot_usage(context, snapshot_ref, "delete.end")

        # Commit the reservations
        if reservations:
            QUOTAS.commit(context, reservations, project_id=project_id)
        return True

    def attach_volume(self, context, volume_id, instance_uuid, host_name,
                      mountpoint, mode):
        """Updates db to show volume is attached"""
        @utils.synchronized(volume_id, external=True)
        def do_attach():
            # check the volume status before attaching
            volume = self.db.volume_get(context, volume_id)
            volume_metadata = self.db.volume_admin_metadata_get(
                context.elevated(), volume_id)
            if volume['status'] == 'attaching':
                if (volume['instance_uuid'] and volume['instance_uuid'] !=
                        instance_uuid):
                    msg = _("being attached by another instance")
                    raise exception.InvalidVolume(reason=msg)
                if (volume['attached_host'] and volume['attached_host'] !=
                        host_name):
                    msg = _("being attached by another host")
                    raise exception.InvalidVolume(reason=msg)
                if (volume_metadata.get('attached_mode') and
                        volume_metadata.get('attached_mode') != mode):
                    msg = _("being attached by different mode")
                    raise exception.InvalidVolume(reason=msg)
            elif volume['status'] != "available":
                msg = _("status must be available")
                raise exception.InvalidVolume(reason=msg)

            # TODO(jdg): attach_time column is currently varchar
            # we should update this to a date-time object
            # also consider adding detach_time?
            self.db.volume_update(context, volume_id,
                                  {"instance_uuid": instance_uuid,
                                   "attached_host": host_name,
                                   "status": "attaching",
                                   "attach_time": timeutils.strtime()})
            self.db.volume_admin_metadata_update(context.elevated(),
                                                 volume_id,
                                                 {"attached_mode": mode},
                                                 False)

            if instance_uuid and not uuidutils.is_uuid_like(instance_uuid):
                self.db.volume_update(context, volume_id,
                                      {'status': 'error_attaching'})
                raise exception.InvalidUUID(uuid=instance_uuid)

            host_name_sanitized = utils.sanitize_hostname(
                host_name) if host_name else None

            volume = self.db.volume_get(context, volume_id)

            if volume_metadata.get('readonly') == 'True' and mode != 'ro':
                self.db.volume_update(context, volume_id,
                                      {'status': 'error_attaching'})
                raise exception.InvalidVolumeAttachMode(mode=mode,
                                                        volume_id=volume_id)
            try:
                self.driver.attach_volume(context,
                                          volume,
                                          instance_uuid,
                                          host_name_sanitized,
                                          mountpoint)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.db.volume_update(context, volume_id,
                                          {'status': 'error_attaching'})

            self.db.volume_attached(context.elevated(),
                                    volume_id,
                                    instance_uuid,
                                    host_name_sanitized,
                                    mountpoint)
        return do_attach()

    def detach_volume(self, context, volume_id):
        """Updates db to show volume is detached"""
        # TODO(vish): refactor this into a more general "unreserve"
        # TODO(sleepsonthefloor): Is this 'elevated' appropriate?

        volume = self.db.volume_get(context, volume_id)
        try:
            self.driver.detach_volume(context, volume)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_id,
                                      {'status': 'error_detaching'})

        self.db.volume_detached(context.elevated(), volume_id)
        self.db.volume_admin_metadata_delete(context.elevated(), volume_id,
                                             'attached_mode')

        # Check for https://bugs.launchpad.net/cinder/+bug/1065702
        volume = self.db.volume_get(context, volume_id)
        if (volume['provider_location'] and
                volume['name'] not in volume['provider_location']):
            self.driver.ensure_export(context, volume)

    def copy_volume_to_image(self, context, volume_id, image_meta):
        """Uploads the specified volume to Glance.

        image_meta is a dictionary containing the following keys:
        'id', 'container_format', 'disk_format'

        """
        payload = {'volume_id': volume_id, 'image_id': image_meta['id']}
        try:
            volume = self.db.volume_get(context, volume_id)
            self.driver.ensure_export(context.elevated(), volume)
            image_service, image_id = \
                glance.get_remote_image_service(context, image_meta['id'])
            self.driver.copy_volume_to_image(context, volume, image_service,
                                             image_meta)
            LOG.debug(_("Uploaded volume %(volume_id)s to "
                        "image (%(image_id)s) successfully"),
                      {'volume_id': volume_id, 'image_id': image_id})
        except Exception as error:
            with excutils.save_and_reraise_exception():
                payload['message'] = unicode(error)
        finally:
            if (volume['instance_uuid'] is None and
                    volume['attached_host'] is None):
                self.db.volume_update(context, volume_id,
                                      {'status': 'available'})
            else:
                self.db.volume_update(context, volume_id,
                                      {'status': 'in-use'})

    def initialize_connection(self, context, volume_id, connector):
        """Prepare volume for connection from host represented by connector.

        This method calls the driver initialize_connection and returns
        it to the caller.  The connector parameter is a dictionary with
        information about the host that will connect to the volume in the
        following format::

            {
                'ip': ip,
                'initiator': initiator,
            }

        ip: the ip address of the connecting machine

        initiator: the iscsi initiator name of the connecting machine.
        This can be None if the connecting machine does not support iscsi
        connections.

        driver is responsible for doing any necessary security setup and
        returning a connection_info dictionary in the following format::

            {
                'driver_volume_type': driver_volume_type,
                'data': data,
            }

        driver_volume_type: a string to identify the type of volume.  This
                           can be used by the calling code to determine the
                           strategy for connecting to the volume. This could
                           be 'iscsi', 'rbd', 'sheepdog', etc.

        data: this is the data that the calling code will use to connect
              to the volume. Keep in mind that this will be serialized to
              json in various places, so it should not contain any non-json
              data types.
        """
        volume = self.db.volume_get(context, volume_id)
        self.driver.validate_connector(connector)
        conn_info = self.driver.initialize_connection(volume, connector)

        # Add qos_specs to connection info
        typeid = volume['volume_type_id']
        specs = {}
        if typeid:
            res = volume_types.get_volume_type_qos_specs(typeid)
            specs = res['qos_specs']

        # Don't pass qos_spec as empty dict
        qos_spec = dict(qos_spec=specs if specs else None)

        conn_info['data'].update(qos_spec)

        # Add access_mode to connection info
        volume_metadata = self.db.volume_admin_metadata_get(context.elevated(),
                                                            volume_id)
        if conn_info['data'].get('access_mode') is None:
            access_mode = volume_metadata.get('attached_mode')
            if access_mode is None:
                # NOTE(zhiyan): client didn't call 'os-attach' before
                access_mode = ('ro'
                               if volume_metadata.get('readonly') == 'True'
                               else 'rw')
            conn_info['data']['access_mode'] = access_mode
        return conn_info

    def terminate_connection(self, context, volume_id, connector, force=False):
        """Cleanup connection from host represented by connector.

        The format of connector is the same as for initialize_connection.
        """
        volume_ref = self.db.volume_get(context, volume_id)
        self.driver.terminate_connection(volume_ref, connector, force=force)

    def accept_transfer(self, context, volume_id, new_user, new_project):
        # NOTE(jdg): need elevated context as we haven't "given" the vol
        # yet
        volume_ref = self.db.volume_get(context.elevated(), volume_id)
        self.driver.accept_transfer(context, volume_ref, new_user, new_project)

    def _migrate_volume_generic(self, ctxt, volume, host):
        rpcapi = volume_rpcapi.VolumeAPI()

        # Create new volume on remote host
        new_vol_values = {}
        for k, v in volume.iteritems():
            new_vol_values[k] = v
        del new_vol_values['id']
        del new_vol_values['_name_id']
        # We don't copy volume_type because the db sets that according to
        # volume_type_id, which we do copy
        del new_vol_values['volume_type']
        new_vol_values['host'] = host['host']
        new_vol_values['status'] = 'creating'
        new_vol_values['migration_status'] = 'target:%s' % volume['id']
        new_vol_values['attach_status'] = 'detached'
        new_volume = self.db.volume_create(ctxt, new_vol_values)
        rpcapi.create_volume(ctxt, new_volume, host['host'],
                             None, None)

        # Wait for new_volume to become ready
        starttime = time.time()
        deadline = starttime + CONF.migration_create_volume_timeout_secs
        new_volume = self.db.volume_get(ctxt, new_volume['id'])
        tries = 0
        while new_volume['status'] != 'available':
            tries = tries + 1
            now = time.time()
            if new_volume['status'] == 'error':
                msg = _("failed to create new_volume on destination host")
                raise exception.VolumeMigrationFailed(reason=msg)
            elif now > deadline:
                msg = _("timeout creating new_volume on destination host")
                raise exception.VolumeMigrationFailed(reason=msg)
            else:
                time.sleep(tries ** 2)
            new_volume = self.db.volume_get(ctxt, new_volume['id'])

        # Copy the source volume to the destination volume
        try:
            if volume['status'] == 'available':
                self.driver.copy_volume_data(ctxt, volume, new_volume,
                                             remote='dest')
                # The above call is synchronous so we complete the migration
                self.migrate_volume_completion(ctxt, volume['id'],
                                               new_volume['id'], error=False)
            else:
                nova_api = compute.API()
                # This is an async call to Nova, which will call the completion
                # when it's done
                nova_api.update_server_volume(ctxt, volume['instance_uuid'],
                                              volume['id'], new_volume['id'])
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = _("Failed to copy volume %(vol1)s to %(vol2)s")
                LOG.error(msg % {'vol1': volume['id'],
                                 'vol2': new_volume['id']})
                volume = self.db.volume_get(ctxt, volume['id'])
                # If we're in the completing phase don't delete the target
                # because we may have already deleted the source!
                if volume['migration_status'] == 'migrating':
                    rpcapi.delete_volume(ctxt, new_volume)
                new_volume['migration_status'] = None

    def migrate_volume_completion(self, ctxt, volume_id, new_volume_id,
                                  error=False):
        volume = self.db.volume_get(ctxt, volume_id)
        new_volume = self.db.volume_get(ctxt, new_volume_id)
        rpcapi = volume_rpcapi.VolumeAPI()

        if error:
            new_volume['migration_status'] = None
            rpcapi.delete_volume(ctxt, new_volume)
            self.db.volume_update(ctxt, volume_id, {'migration_status': None})
            return volume_id

        self.db.volume_update(ctxt, volume_id,
                              {'migration_status': 'completing'})

        # Delete the source volume (if it fails, don't fail the migration)
        try:
            self.delete_volume(ctxt, volume_id)
        except Exception as ex:
            msg = _("Failed to delete migration source vol %(vol)s: %(err)s")
            LOG.error(msg % {'vol': volume_id, 'err': ex})

        self.db.finish_volume_migration(ctxt, volume_id, new_volume_id)
        self.db.volume_update(ctxt, volume_id, {'migration_status': None})
        return volume['id']

    def migrate_volume(self, ctxt, volume_id, host, force_host_copy=False):
        """Migrate the volume to the specified host (called on source host)."""
        volume_ref = self.db.volume_get(ctxt, volume_id)
        model_update = None
        moved = False

        self.db.volume_update(ctxt, volume_ref['id'],
                              {'migration_status': 'migrating'})
        if not force_host_copy:
            try:
                LOG.debug(_("volume %s: calling driver migrate_volume"),
                          volume_ref['id'])
                moved, model_update = self.driver.migrate_volume(ctxt,
                                                                 volume_ref,
                                                                 host)
                if moved:
                    updates = {'host': host['host'],
                               'migration_status': None}
                    if model_update:
                        updates.update(model_update)
                    volume_ref = self.db.volume_update(ctxt,
                                                       volume_ref['id'],
                                                       updates)
            except Exception:
                with excutils.save_and_reraise_exception():
                    updates = {'migration_status': None}
                    model_update = self.driver.create_export(ctxt, volume_ref)
                    if model_update:
                        updates.update(model_update)
                    self.db.volume_update(ctxt, volume_ref['id'], updates)
        if not moved:
            try:
                self._migrate_volume_generic(ctxt, volume_ref, host)
            except Exception:
                with excutils.save_and_reraise_exception():
                    updates = {'migration_status': None}
                    model_update = self.driver.create_export(ctxt, volume_ref)
                    if model_update:
                        updates.update(model_update)
                    self.db.volume_update(ctxt, volume_ref['id'], updates)

    @periodic_task.periodic_task
    def _report_driver_status(self, context):
        LOG.info(_("Updating volume status"))
        volume_stats = self.driver.get_volume_stats(refresh=True)
        if volume_stats:
            # This will grab info about the host and queue it
            # to be sent to the Schedulers.
            self.update_service_capabilities(volume_stats)

    def publish_service_capabilities(self, context):
        """Collect driver status and then publish."""
        self._report_driver_status(context)
        self._publish_service_capabilities(context)

    def _reset_stats(self):
        LOG.info(_("Clear capabilities"))
        self._last_volume_stats = []

    def notification(self, context, event):
        LOG.info(_("Notification {%s} received"), event)
        self._reset_stats()

    def _notify_about_volume_usage(self,
                                   context,
                                   volume,
                                   event_suffix,
                                   extra_usage_info=None):
        volume_utils.notify_about_volume_usage(
            context, volume, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

    def _notify_about_snapshot_usage(self,
                                     context,
                                     snapshot,
                                     event_suffix,
                                     extra_usage_info=None):
        volume_utils.notify_about_snapshot_usage(
            context, snapshot, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

    def extend_volume(self, context, volume_id, new_size):
        volume = self.db.volume_get(context, volume_id)
        size_increase = (int(new_size)) - volume['size']

        try:
            reservations = QUOTAS.reserve(context, gigabytes=+size_increase)
        except exception.OverQuota as exc:
            self.db.volume_update(context, volume['id'],
                                  {'status': 'error_extending'})
            overs = exc.kwargs['overs']
            usages = exc.kwargs['usages']
            quotas = exc.kwargs['quotas']

            def _consumed(name):
                return (usages[name]['reserved'] + usages[name]['in_use'])

            if 'gigabytes' in overs:
                msg = _("Quota exceeded for %(s_pid)s, "
                        "tried to extend volume by "
                        "%(s_size)sG, (%(d_consumed)dG of %(d_quota)dG "
                        "already consumed)")
                LOG.error(msg % {'s_pid': context.project_id,
                                 's_size': size_increase,
                                 'd_consumed': _consumed('gigabytes'),
                                 'd_quota': quotas['gigabytes']})
            return

        try:
            LOG.info(_("volume %s: extending"), volume['id'])
            self.driver.extend_volume(volume, new_size)
            LOG.info(_("volume %s: extended successfully"), volume['id'])
        except Exception:
            LOG.exception(_("volume %s: Error trying to extend volume"),
                          volume_id)
            try:
                self.db.volume_update(context, volume['id'],
                                      {'status': 'error_extending'})
            finally:
                QUOTAS.rollback(context, reservations)
                return

        QUOTAS.commit(context, reservations)
        self.db.volume_update(context, volume['id'], {'size': int(new_size),
                                                      'status': 'available'})
