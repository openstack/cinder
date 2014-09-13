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
from oslo import messaging
from osprofiler import profiler

from cinder import compute
from cinder import context
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _
from cinder.image import glance
from cinder import manager
from cinder.openstack.common import excutils
from cinder.openstack.common import importutils
from cinder.openstack.common import jsonutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import periodic_task
from cinder.openstack.common import timeutils
from cinder.openstack.common import uuidutils
from cinder import quota
from cinder import utils
from cinder.volume.configuration import Configuration
from cinder.volume.flows.manager import create_volume
from cinder.volume.flows.manager import manage_existing
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as vol_utils
from cinder.volume import volume_types

from eventlet.greenpool import GreenPool

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS
CGQUOTAS = quota.CGQUOTAS

volume_manager_opts = [
    cfg.StrOpt('volume_driver',
               default='cinder.volume.drivers.lvm.LVMISCSIDriver',
               help='Driver to use for volume creation'),
    cfg.IntOpt('migration_create_volume_timeout_secs',
               default=300,
               help='Timeout for creating the volume to migrate to '
                    'when performing volume migration (seconds)'),
    cfg.BoolOpt('volume_service_inithost_offload',
                default=False,
                help='Offload pending volume delete during '
                     'volume service startup'),
    cfg.StrOpt('zoning_mode',
               default='none',
               help='FC Zoning mode configured'),
    cfg.StrOpt('extra_capabilities',
               default='{}',
               help='User defined capabilities, a JSON formatted string '
                    'specifying key/value pairs.'),
]

CONF = cfg.CONF
CONF.register_opts(volume_manager_opts)

MAPPING = {
    'cinder.volume.drivers.storwize_svc.StorwizeSVCDriver':
    'cinder.volume.drivers.ibm.storwize_svc.StorwizeSVCDriver',
    'cinder.volume.drivers.xiv_ds8k.XIVDS8KDriver':
    'cinder.volume.drivers.ibm.xiv_ds8k.XIVDS8KDriver',
    'cinder.volume.drivers.san.hp_lefthand.HpSanISCSIDriver':
    'cinder.volume.drivers.san.hp.hp_lefthand_iscsi.HPLeftHandISCSIDriver',
    'cinder.volume.drivers.gpfs.GPFSDriver':
    'cinder.volume.drivers.ibm.gpfs.GPFSDriver', }


def locked_volume_operation(f):
    """Lock decorator for volume operations.

    Takes a named lock prior to executing the operation. The lock is named with
    the operation executed and the id of the volume. This lock can then be used
    by other operations to avoid operation conflicts on shared volumes.

    Example use:

    If a volume operation uses this decorator, it will block until the named
    lock is free. This is used to protect concurrent operations on the same
    volume e.g. delete VolA while create volume VolB from VolA is in progress.
    """
    def lvo_inner1(inst, context, volume_id, **kwargs):
        @utils.synchronized("%s-%s" % (volume_id, f.__name__), external=True)
        def lvo_inner2(*_args, **_kwargs):
            return f(*_args, **_kwargs)
        return lvo_inner2(inst, context, volume_id, **kwargs)
    return lvo_inner1


def locked_snapshot_operation(f):
    """Lock decorator for snapshot operations.

    Takes a named lock prior to executing the operation. The lock is named with
    the operation executed and the id of the snapshot. This lock can then be
    used by other operations to avoid operation conflicts on shared snapshots.

    Example use:

    If a snapshot operation uses this decorator, it will block until the named
    lock is free. This is used to protect concurrent operations on the same
    snapshot e.g. delete SnapA while create volume VolA from SnapA is in
    progress.
    """
    def lso_inner1(inst, context, snapshot_id, **kwargs):
        @utils.synchronized("%s-%s" % (snapshot_id, f.__name__), external=True)
        def lso_inner2(*_args, **_kwargs):
            return f(*_args, **_kwargs)
        return lso_inner2(inst, context, snapshot_id, **kwargs)
    return lso_inner1


class VolumeManager(manager.SchedulerDependentManager):
    """Manages attachable block storage devices."""

    RPC_API_VERSION = '1.18'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, volume_driver=None, service_name=None,
                 *args, **kwargs):
        """Load the driver from the one specified in args, or from flags."""
        # update_service_capabilities needs service_name to be volume
        super(VolumeManager, self).__init__(service_name='volume',
                                            *args, **kwargs)
        self.configuration = Configuration(volume_manager_opts,
                                           config_group=service_name)
        self._tp = GreenPool()
        self.stats = {}

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
            db=self.db,
            host=self.host)

        self.driver = profiler.trace_cls("driver")(self.driver)
        try:
            self.extra_capabilities = jsonutils.loads(
                self.driver.configuration.extra_capabilities)
        except AttributeError:
            self.extra_capabilities = {}
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Invalid JSON: %s" %
                          self.driver.configuration.extra_capabilities)

    def _add_to_threadpool(self, func, *args, **kwargs):
        self._tp.spawn_n(func, *args, **kwargs)

    def _count_allocated_capacity(self, ctxt, volume):
        pool = vol_utils.extract_host(volume['host'], 'pool')
        if pool is None:
            # No pool name encoded in host, so this is a legacy
            # volume created before pool is introduced, ask
            # driver to provide pool info if it has such
            # knowledge and update the DB.
            try:
                pool = self.driver.get_pool(volume)
            except Exception as err:
                LOG.error(_('Failed to fetch pool name for volume: %s'),
                          volume['id'])
                LOG.exception(err)
                return

            if pool:
                new_host = vol_utils.append_host(volume['host'],
                                                 pool)
                self.db.volume_update(ctxt, volume['id'],
                                      {'host': new_host})
            else:
                # Otherwise, put them into a special fixed pool with
                # volume_backend_name being the pool name, if
                # volume_backend_name is None, use default pool name.
                # This is only for counting purpose, doesn't update DB.
                pool = (self.driver.configuration.safe_get(
                    'volume_backend_name') or vol_utils.extract_host(
                    volume['host'], 'pool', True))
        try:
            pool_stat = self.stats['pools'][pool]
        except KeyError:
            # First volume in the pool
            self.stats['pools'][pool] = dict(
                allocated_capacity_gb=0)
            pool_stat = self.stats['pools'][pool]
        pool_sum = pool_stat['allocated_capacity_gb']
        pool_sum += volume['size']

        self.stats['pools'][pool]['allocated_capacity_gb'] = pool_sum
        self.stats['allocated_capacity_gb'] += volume['size']

    def init_host(self):
        """Do any initialization that needs to be run if this is a
           standalone service.
        """

        ctxt = context.get_admin_context()
        LOG.info(_("Starting volume driver %(driver_name)s (%(version)s)") %
                 {'driver_name': self.driver.__class__.__name__,
                  'version': self.driver.get_version()})
        try:
            self.driver.do_setup(ctxt)
            self.driver.check_for_setup_error()
        except Exception as ex:
            LOG.error(_("Error encountered during "
                        "initialization of driver: %(name)s") %
                      {'name': self.driver.__class__.__name__})
            LOG.exception(ex)
            # we don't want to continue since we failed
            # to initialize the driver correctly.
            return

        volumes = self.db.volume_get_all_by_host(ctxt, self.host)
        # FIXME volume count for exporting is wrong
        LOG.debug("Re-exporting %s volumes" % len(volumes))

        try:
            self.stats['pools'] = {}
            self.stats.update({'allocated_capacity_gb': 0})
            for volume in volumes:
                # available volume should also be counted into allocated
                if volume['status'] in ['in-use', 'available']:
                    # calculate allocated capacity for driver
                    self._count_allocated_capacity(ctxt, volume)

                    try:
                        self.driver.ensure_export(ctxt, volume)
                    except Exception as export_ex:
                        LOG.error(_("Failed to re-export volume %s: "
                                    "setting to error state"), volume['id'])
                        LOG.exception(export_ex)
                        self.db.volume_update(ctxt,
                                              volume['id'],
                                              {'status': 'error'})
                elif volume['status'] == 'downloading':
                    LOG.info(_("volume %s stuck in a downloading state"),
                             volume['id'])
                    self.driver.clear_download(ctxt, volume)
                    self.db.volume_update(ctxt,
                                          volume['id'],
                                          {'status': 'error'})
                else:
                    LOG.info(_("volume %s: skipping export"), volume['id'])
        except Exception as ex:
            LOG.error(_("Error encountered during "
                        "re-exporting phase of driver initialization: "
                        " %(name)s") %
                      {'name': self.driver.__class__.__name__})
            LOG.exception(ex)
            return

        # at this point the driver is considered initialized.
        self.driver.set_initialized()

        LOG.debug('Resuming any in progress delete operations')
        for volume in volumes:
            if volume['status'] == 'deleting':
                LOG.info(_('Resuming delete on volume: %s') % volume['id'])
                if CONF.volume_service_inithost_offload:
                    # Offload all the pending volume delete operations to the
                    # threadpool to prevent the main volume service thread
                    # from being blocked.
                    self._add_to_threadpool(self.delete_volume(ctxt,
                                                               volume['id']))
                else:
                    # By default, delete volumes sequentially
                    self.delete_volume(ctxt, volume['id'])

        # collect and publish service capabilities
        self.publish_service_capabilities(ctxt)

    def create_volume(self, context, volume_id, request_spec=None,
                      filter_properties=None, allow_reschedule=True,
                      snapshot_id=None, image_id=None, source_volid=None,
                      source_replicaid=None, consistencygroup_id=None):

        """Creates the volume."""
        context_saved = context.deepcopy()
        context = context.elevated()
        if filter_properties is None:
            filter_properties = {}

        try:
            # NOTE(flaper87): Driver initialization is
            # verified by the task itself.
            flow_engine = create_volume.get_flow(
                context,
                self.db,
                self.driver,
                self.scheduler_rpcapi,
                self.host,
                volume_id,
                snapshot_id=snapshot_id,
                image_id=image_id,
                source_volid=source_volid,
                source_replicaid=source_replicaid,
                consistencygroup_id=consistencygroup_id,
                allow_reschedule=allow_reschedule,
                reschedule_context=context_saved,
                request_spec=request_spec,
                filter_properties=filter_properties)
        except Exception:
            LOG.exception(_("Failed to create manager volume flow"))
            raise exception.CinderException(
                _("Failed to create manager volume flow."))

        if snapshot_id is not None:
            # Make sure the snapshot is not deleted until we are done with it.
            locked_action = "%s-%s" % (snapshot_id, 'delete_snapshot')
        elif source_volid is not None:
            # Make sure the volume is not deleted until we are done with it.
            locked_action = "%s-%s" % (source_volid, 'delete_volume')
        elif source_replicaid is not None:
            # Make sure the volume is not deleted until we are done with it.
            locked_action = "%s-%s" % (source_replicaid, 'delete_volume')
        else:
            locked_action = None

        def _run_flow():
            # This code executes create volume flow. If something goes wrong,
            # flow reverts all job that was done and reraises an exception.
            # Otherwise, all data that was generated by flow becomes available
            # in flow engine's storage.
            with flow_utils.DynamicLogListener(flow_engine, logger=LOG):
                flow_engine.run()

        @utils.synchronized(locked_action, external=True)
        def _run_flow_locked():
            _run_flow()

        if locked_action is None:
            _run_flow()
        else:
            _run_flow_locked()

        # Fetch created volume from storage
        vol_ref = flow_engine.storage.fetch('volume')
        # Update volume stats
        pool = vol_utils.extract_host(vol_ref['host'], 'pool')
        if pool is None:
            # Legacy volume, put them into default pool
            pool = self.driver.configuration.safe_get(
                'volume_backend_name') or vol_utils.extract_host(
                    vol_ref['host'], 'pool', True)

        try:
            self.stats['pools'][pool]['allocated_capacity_gb'] \
                += vol_ref['size']
        except KeyError:
            self.stats['pools'][pool] = dict(
                allocated_capacity_gb=vol_ref['size'])

        return vol_ref['id']

    @locked_volume_operation
    def delete_volume(self, context, volume_id, unmanage_only=False):
        """Deletes and unexports volume."""
        context = context.elevated()

        try:
            volume_ref = self.db.volume_get(context, volume_id)
        except exception.VolumeNotFound:
            # NOTE(thingee): It could be possible for a volume to
            # be deleted when resuming deletes from init_host().
            LOG.info(_("Tried to delete volume %s, but it no longer exists, "
                       "moving on") % (volume_id))
            return True

        if context.project_id != volume_ref['project_id']:
            project_id = volume_ref['project_id']
        else:
            project_id = context.project_id

        LOG.info(_("volume %s: deleting"), volume_ref['id'])
        if volume_ref['attach_status'] == "attached":
            # Volume is still attached, need to detach first
            raise exception.VolumeAttached(volume_id=volume_id)
        if (vol_utils.extract_host(volume_ref['host']) != self.host):
            raise exception.InvalidVolume(
                reason=_("volume is not local to this node"))

        self._notify_about_volume_usage(context, volume_ref, "delete.start")
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)

            LOG.debug("volume %s: removing export", volume_ref['id'])
            self.driver.remove_export(context, volume_ref)
            LOG.debug("volume %s: deleting", volume_ref['id'])
            if unmanage_only:
                self.driver.unmanage(volume_ref)
            else:
                self.driver.delete_volume(volume_ref)
        except exception.VolumeIsBusy:
            LOG.error(_("Cannot delete volume %s: volume is busy"),
                      volume_ref['id'])
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
        self.db.volume_glance_metadata_delete_by_volume(context, volume_id)

        self.db.volume_destroy(context, volume_id)
        LOG.info(_("volume %s: deleted successfully"), volume_ref['id'])
        self._notify_about_volume_usage(context, volume_ref, "delete.end")

        # Commit the reservations
        if reservations:
            QUOTAS.commit(context, reservations, project_id=project_id)

        pool = vol_utils.extract_host(volume_ref['host'], 'pool')
        if pool is None:
            # Legacy volume, put them into default pool
            pool = self.driver.configuration.safe_get(
                'volume_backend_name') or vol_utils.extract_host(
                    volume_ref['host'], 'pool', True)
        size = volume_ref['size']

        try:
            self.stats['pools'][pool]['allocated_capacity_gb'] -= size
        except KeyError:
            self.stats['pools'][pool] = dict(
                allocated_capacity_gb=-size)

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
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the snapshot status updated.
            utils.require_driver_initialized(self.driver)

            LOG.debug("snapshot %(snap_id)s: creating",
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
                self.db.snapshot_update(context,
                                        snapshot_ref['id'],
                                        {'status': 'error'})
                raise exception.MetadataCopyFailure(reason=ex)

        snapshot_ref = self.db.snapshot_update(context,
                                               snapshot_ref['id'],
                                               {'status': 'available',
                                                'progress': '100%'})

        LOG.info(_("snapshot %s: created successfully"), snapshot_ref['id'])
        self._notify_about_snapshot_usage(context, snapshot_ref, "create.end")
        return snapshot_id

    @locked_snapshot_operation
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
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the snapshot status updated.
            utils.require_driver_initialized(self.driver)

            LOG.debug("snapshot %s: deleting", snapshot_ref['id'])

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
        """Updates db to show volume is attached."""
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
            elif (not volume['migration_status'] and
                  volume['status'] != "available"):
                msg = _("status must be available or attaching")
                raise exception.InvalidVolume(reason=msg)

            # TODO(jdg): attach_time column is currently varchar
            # we should update this to a date-time object
            # also consider adding detach_time?
            self._notify_about_volume_usage(context, volume,
                                            "attach.start")
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
                # NOTE(flaper87): Verify the driver is enabled
                # before going forward. The exception will be caught
                # and the volume status updated.
                utils.require_driver_initialized(self.driver)

                self.driver.attach_volume(context,
                                          volume,
                                          instance_uuid,
                                          host_name_sanitized,
                                          mountpoint)
            except Exception:
                with excutils.save_and_reraise_exception():
                    self.db.volume_update(context, volume_id,
                                          {'status': 'error_attaching'})

            volume = self.db.volume_attached(context.elevated(),
                                             volume_id,
                                             instance_uuid,
                                             host_name_sanitized,
                                             mountpoint)
            if volume['migration_status']:
                self.db.volume_update(context, volume_id,
                                      {'migration_status': None})
            self._notify_about_volume_usage(context, volume, "attach.end")
        return do_attach()

    @locked_volume_operation
    def detach_volume(self, context, volume_id):
        """Updates db to show volume is detached."""
        # TODO(vish): refactor this into a more general "unreserve"

        volume = self.db.volume_get(context, volume_id)
        self._notify_about_volume_usage(context, volume, "detach.start")
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)

            self.driver.detach_volume(context, volume)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_id,
                                      {'status': 'error_detaching'})

        self.db.volume_detached(context.elevated(), volume_id)
        self.db.volume_admin_metadata_delete(context.elevated(), volume_id,
                                             'attached_mode')

        # NOTE(jdg): We used to do an ensure export here to
        # catch upgrades while volumes were attached (E->F)
        # this was necessary to convert in-use volumes from
        # int ID's to UUID's.  Don't need this any longer

        # We're going to remove the export here
        # (delete the iscsi target)
        volume = self.db.volume_get(context, volume_id)
        try:
            utils.require_driver_initialized(self.driver)
            LOG.debug("volume %s: removing export", volume_id)
            self.driver.remove_export(context.elevated(), volume)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Error detaching volume %(volume)s, "
                                "due to uninitialized driver."),
                              {"volume": volume_id})
        except Exception as ex:
            LOG.exception(_("Error detaching volume %(volume)s, "
                            "due to remove export failure."),
                          {"volume": volume_id})
            raise exception.RemoveExportException(volume=volume_id, reason=ex)

        self._notify_about_volume_usage(context, volume, "detach.end")

    def copy_volume_to_image(self, context, volume_id, image_meta):
        """Uploads the specified volume to Glance.

        image_meta is a dictionary containing the following keys:
        'id', 'container_format', 'disk_format'

        """
        payload = {'volume_id': volume_id, 'image_id': image_meta['id']}
        image_service = None
        try:
            volume = self.db.volume_get(context, volume_id)

            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)

            image_service, image_id = \
                glance.get_remote_image_service(context, image_meta['id'])
            self.driver.copy_volume_to_image(context, volume, image_service,
                                             image_meta)
            LOG.debug("Uploaded volume %(volume_id)s to "
                      "image (%(image_id)s) successfully",
                      {'volume_id': volume_id, 'image_id': image_id})
        except Exception as error:
            LOG.error(_("Error occurred while uploading volume %(volume_id)s "
                        "to image %(image_id)s."),
                      {'volume_id': volume_id, 'image_id': image_meta['id']})
            if image_service is not None:
                # Deletes the image if it is in queued or saving state
                self._delete_image(context, image_meta['id'], image_service)

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

    def _delete_image(self, context, image_id, image_service):
        """Deletes an image stuck in queued or saving state."""
        try:
            image_meta = image_service.show(context, image_id)
            image_status = image_meta.get('status')
            if image_status == 'queued' or image_status == 'saving':
                LOG.warn("Deleting image %(image_id)s in %(image_status)s "
                         "state.",
                         {'image_id': image_id,
                          'image_status': image_status})
                image_service.delete(context, image_id)
        except Exception:
            LOG.warn(_("Error occurred while deleting image %s."),
                     image_id, exc_info=True)

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
        # NOTE(flaper87): Verify the driver is enabled
        # before going forward. The exception will be caught
        # and the volume status updated.
        utils.require_driver_initialized(self.driver)
        try:
            self.driver.validate_connector(connector)
        except Exception as err:
            err_msg = (_('Unable to fetch connection information from '
                         'backend: %(err)s') % {'err': err})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        volume = self.db.volume_get(context, volume_id)
        model_update = None
        try:
            LOG.debug("Volume %s: creating export", volume_id)
            model_update = self.driver.create_export(context.elevated(),
                                                     volume)
        except exception.CinderException:
            err_msg = (_('Unable to create export for volume %(volume_id)s') %
                       {'volume_id': volume_id})
            LOG.exception(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        try:
            if model_update:
                volume = self.db.volume_update(context,
                                               volume_id,
                                               model_update)
        except exception.CinderException as ex:
            LOG.exception(_("Failed updating model of volume %(volume_id)s"
                          " with driver provided model %(model)s") %
                          {'volume_id': volume_id, 'model': model_update})
            raise exception.ExportFailure(reason=ex)

        try:
            conn_info = self.driver.initialize_connection(volume, connector)
        except Exception as err:
            err_msg = (_('Unable to fetch connection information from '
                         'backend: %(err)s') % {'err': err})
            LOG.error(err_msg)

            self.driver.remove_export(context.elevated(), volume)

            raise exception.VolumeBackendAPIException(data=err_msg)

        # Add qos_specs to connection info
        typeid = volume['volume_type_id']
        specs = None
        if typeid:
            res = volume_types.get_volume_type_qos_specs(typeid)
            qos = res['qos_specs']
            # only pass qos_specs that is designated to be consumed by
            # front-end, or both front-end and back-end.
            if qos and qos.get('consumer') in ['front-end', 'both']:
                specs = qos.get('specs')

        qos_spec = dict(qos_specs=specs)
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
        # NOTE(flaper87): Verify the driver is enabled
        # before going forward. The exception will be caught
        # and the volume status updated.
        utils.require_driver_initialized(self.driver)

        volume_ref = self.db.volume_get(context, volume_id)
        try:
            self.driver.terminate_connection(volume_ref, connector,
                                             force=force)
        except Exception as err:
            err_msg = (_('Unable to terminate volume connection: %(err)s')
                       % {'err': err})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def accept_transfer(self, context, volume_id, new_user, new_project):
        # NOTE(flaper87): Verify the driver is enabled
        # before going forward. The exception will be caught
        # and the volume status updated.
        utils.require_driver_initialized(self.driver)

        # NOTE(jdg): need elevated context as we haven't "given" the vol
        # yet
        volume_ref = self.db.volume_get(context.elevated(), volume_id)

        # NOTE(jdg): Some drivers tie provider info (CHAP) to tenant
        # for those that do allow them to return updated model info
        model_update = self.driver.accept_transfer(context,
                                                   volume_ref,
                                                   new_user,
                                                   new_project)

        if model_update:
            try:
                self.db.volume_update(context.elevated(),
                                      volume_id,
                                      model_update)
            except exception.CinderException:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_("Failed updating model of "
                                    "volume %(volume_id)s "
                                    "with drivers update %(model)s "
                                    "during xfr.") %
                                  {'volume_id': volume_id,
                                   'model': model_update})
                    self.db.volume_update(context.elevated(),
                                          volume_id,
                                          {'status': 'error'})

        return model_update

    def _migrate_volume_generic(self, ctxt, volume, host, new_type_id):
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
        if new_type_id:
            new_vol_values['volume_type_id'] = new_type_id
        new_vol_values['host'] = host['host']
        new_vol_values['status'] = 'creating'
        new_vol_values['migration_status'] = 'target:%s' % volume['id']
        new_vol_values['attach_status'] = 'detached'
        new_volume = self.db.volume_create(ctxt, new_vol_values)
        rpcapi.create_volume(ctxt, new_volume, host['host'],
                             None, None, allow_reschedule=False)

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
            if (volume['instance_uuid'] is None and
                    volume['attached_host'] is None):
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

    def _get_original_status(self, volume):
        if (volume['instance_uuid'] is None and
                volume['attached_host'] is None):
            return 'available'
        else:
            return 'in-use'

    def migrate_volume_completion(self, ctxt, volume_id, new_volume_id,
                                  error=False):
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the migration status updated.
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(ctxt, volume_id,
                                      {'migration_status': 'error'})

        msg = _("migrate_volume_completion: completing migration for "
                "volume %(vol1)s (temporary volume %(vol2)s")
        LOG.debug(msg % {'vol1': volume_id, 'vol2': new_volume_id})
        volume = self.db.volume_get(ctxt, volume_id)
        new_volume = self.db.volume_get(ctxt, new_volume_id)
        rpcapi = volume_rpcapi.VolumeAPI()

        status_update = {}
        if volume['status'] == 'retyping':
            status_update = {'status': self._get_original_status(volume)}

        if error:
            msg = _("migrate_volume_completion is cleaning up an error "
                    "for volume %(vol1)s (temporary volume %(vol2)s")
            LOG.info(msg % {'vol1': volume['id'],
                            'vol2': new_volume['id']})
            new_volume['migration_status'] = None
            rpcapi.delete_volume(ctxt, new_volume)
            updates = {'migration_status': None}
            if status_update:
                updates.update(status_update)
            self.db.volume_update(ctxt, volume_id, updates)
            return volume_id

        self.db.volume_update(ctxt, volume_id,
                              {'migration_status': 'completing'})

        # Delete the source volume (if it fails, don't fail the migration)
        try:
            if status_update.get('status') == 'in-use':
                self.detach_volume(ctxt, volume_id)
            self.delete_volume(ctxt, volume_id)
        except Exception as ex:
            msg = _("Failed to delete migration source vol %(vol)s: %(err)s")
            LOG.error(msg % {'vol': volume_id, 'err': ex})

        self.db.finish_volume_migration(ctxt, volume_id, new_volume_id)
        self.db.volume_destroy(ctxt, new_volume_id)
        if status_update.get('status') == 'in-use':
            updates = {'migration_status': 'completing'}
            updates.update(status_update)
        else:
            updates = {'migration_status': None}
        self.db.volume_update(ctxt, volume_id, updates)

        if 'in-use' in (status_update.get('status'), volume['status']):
            rpcapi.attach_volume(ctxt,
                                 volume,
                                 volume['instance_uuid'],
                                 volume['attached_host'],
                                 volume['mountpoint'],
                                 'rw')
        return volume['id']

    def migrate_volume(self, ctxt, volume_id, host, force_host_copy=False,
                       new_type_id=None):
        """Migrate the volume to the specified host (called on source host)."""
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the migration status updated.
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(ctxt, volume_id,
                                      {'migration_status': 'error'})

        volume_ref = self.db.volume_get(ctxt, volume_id)
        model_update = None
        moved = False

        status_update = None
        if volume_ref['status'] == 'retyping':
            status_update = {'status': self._get_original_status(volume_ref)}

        self.db.volume_update(ctxt, volume_ref['id'],
                              {'migration_status': 'migrating'})
        if not force_host_copy and new_type_id is None:
            try:
                LOG.debug("volume %s: calling driver migrate_volume",
                          volume_ref['id'])
                moved, model_update = self.driver.migrate_volume(ctxt,
                                                                 volume_ref,
                                                                 host)
                if moved:
                    updates = {'host': host['host'],
                               'migration_status': None}
                    if status_update:
                        updates.update(status_update)
                    if model_update:
                        updates.update(model_update)
                    volume_ref = self.db.volume_update(ctxt,
                                                       volume_ref['id'],
                                                       updates)
            except Exception:
                with excutils.save_and_reraise_exception():
                    updates = {'migration_status': None}
                    if status_update:
                        updates.update(status_update)
                    model_update = self.driver.create_export(ctxt, volume_ref)
                    if model_update:
                        updates.update(model_update)
                    self.db.volume_update(ctxt, volume_ref['id'], updates)
        if not moved:
            try:
                self._migrate_volume_generic(ctxt, volume_ref, host,
                                             new_type_id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    updates = {'migration_status': None}
                    if status_update:
                        updates.update(status_update)
                    model_update = self.driver.create_export(ctxt, volume_ref)
                    if model_update:
                        updates.update(model_update)
                    self.db.volume_update(ctxt, volume_ref['id'], updates)

    @periodic_task.periodic_task
    def _report_driver_status(self, context):
        LOG.info(_("Updating volume status"))
        if not self.driver.initialized:
            if self.driver.configuration.config_group is None:
                config_group = ''
            else:
                config_group = ('(config name %s)' %
                                self.driver.configuration.config_group)

            LOG.warning(_('Unable to update stats, %(driver_name)s '
                          '-%(driver_version)s '
                          '%(config_group)s driver is uninitialized.') %
                        {'driver_name': self.driver.__class__.__name__,
                         'driver_version': self.driver.get_version(),
                         'config_group': config_group})
        else:
            volume_stats = self.driver.get_volume_stats(refresh=True)
            if self.extra_capabilities:
                volume_stats.update(self.extra_capabilities)
            if volume_stats:
                # Append volume stats with 'allocated_capacity_gb'
                self._append_volume_stats(volume_stats)

                # queue it to be sent to the Schedulers.
                self.update_service_capabilities(volume_stats)

    def _append_volume_stats(self, vol_stats):
        pools = vol_stats.get('pools', None)
        if pools and isinstance(pools, list):
            for pool in pools:
                pool_name = pool['pool_name']
                try:
                    pool_stats = self.stats['pools'][pool_name]
                except KeyError:
                    # Pool not found in volume manager
                    pool_stats = dict(allocated_capacity_gb=0)

                pool.update(pool_stats)

    def publish_service_capabilities(self, context):
        """Collect driver status and then publish."""
        self._report_driver_status(context)
        self._publish_service_capabilities(context)

    def notification(self, context, event):
        LOG.info(_("Notification {%s} received"), event)

    def _notify_about_volume_usage(self,
                                   context,
                                   volume,
                                   event_suffix,
                                   extra_usage_info=None):
        vol_utils.notify_about_volume_usage(
            context, volume, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

    def _notify_about_snapshot_usage(self,
                                     context,
                                     snapshot,
                                     event_suffix,
                                     extra_usage_info=None):
        vol_utils.notify_about_snapshot_usage(
            context, snapshot, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

    def _notify_about_consistencygroup_usage(self,
                                             context,
                                             group,
                                             event_suffix,
                                             extra_usage_info=None):
        vol_utils.notify_about_consistencygroup_usage(
            context, group, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

        volumes = self.db.volume_get_all_by_group(context, group['id'])
        if volumes:
            for volume in volumes:
                vol_utils.notify_about_volume_usage(
                    context, volume, event_suffix,
                    extra_usage_info=extra_usage_info, host=self.host)

    def _notify_about_cgsnapshot_usage(self,
                                       context,
                                       cgsnapshot,
                                       event_suffix,
                                       extra_usage_info=None):
        vol_utils.notify_about_cgsnapshot_usage(
            context, cgsnapshot, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

        snapshots = self.db.snapshot_get_all_for_cgsnapshot(context,
                                                            cgsnapshot['id'])
        if snapshots:
            for snapshot in snapshots:
                vol_utils.notify_about_snapshot_usage(
                    context, snapshot, event_suffix,
                    extra_usage_info=extra_usage_info, host=self.host)

    def extend_volume(self, context, volume_id, new_size, reservations):
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                self.db.volume_update(context, volume_id,
                                      {'status': 'error_extending'})

        volume = self.db.volume_get(context, volume_id)
        size_increase = (int(new_size)) - volume['size']
        self._notify_about_volume_usage(context, volume, "resize.start")
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
                raise exception.CinderException(_("Volume %s: Error trying "
                                                  "to extend volume") %
                                                volume_id)
            finally:
                QUOTAS.rollback(context, reservations)
                return

        QUOTAS.commit(context, reservations)
        volume = self.db.volume_update(context,
                                       volume['id'],
                                       {'size': int(new_size),
                                        'status': 'available'})
        pool = vol_utils.extract_host(volume['host'], 'pool')
        if pool is None:
            # Legacy volume, put them into default pool
            pool = self.driver.configuration.safe_get(
                'volume_backend_name') or vol_utils.extract_host(
                    volume['host'], 'pool', True)

        try:
            self.stats['pools'][pool]['allocated_capacity_gb'] += size_increase
        except KeyError:
            self.stats['pools'][pool] = dict(
                allocated_capacity_gb=size_increase)

        self._notify_about_volume_usage(
            context, volume, "resize.end",
            extra_usage_info={'size': int(new_size)})

    def retype(self, ctxt, volume_id, new_type_id, host,
               migration_policy='never', reservations=None):

        def _retype_error(context, volume_id, old_reservations,
                          new_reservations, status_update):
            try:
                self.db.volume_update(context, volume_id, status_update)
            finally:
                QUOTAS.rollback(context, old_reservations)
                QUOTAS.rollback(context, new_reservations)

        context = ctxt.elevated()

        volume_ref = self.db.volume_get(ctxt, volume_id)
        status_update = {'status': self._get_original_status(volume_ref)}
        if context.project_id != volume_ref['project_id']:
            project_id = volume_ref['project_id']
        else:
            project_id = context.project_id

        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                # NOTE(flaper87): Other exceptions in this method don't
                # set the volume status to error. Should that be done
                # here? Setting the volume back to it's original status
                # for now.
                self.db.volume_update(context, volume_id, status_update)

        # Get old reservations
        try:
            reserve_opts = {'volumes': -1, 'gigabytes': -volume_ref['size']}
            QUOTAS.add_volume_type_opts(context,
                                        reserve_opts,
                                        volume_ref.get('volume_type_id'))
            old_reservations = QUOTAS.reserve(context,
                                              project_id=project_id,
                                              **reserve_opts)
        except Exception:
            old_reservations = None
            self.db.volume_update(context, volume_id, status_update)
            LOG.exception(_("Failed to update usages while retyping volume."))
            raise exception.CinderException(_("Failed to get old volume type"
                                              " quota reservations"))

        # We already got the new reservations
        new_reservations = reservations

        # If volume types have the same contents, no need to do anything
        retyped = False
        diff, all_equal = volume_types.volume_types_diff(
            context, volume_ref.get('volume_type_id'), new_type_id)
        if all_equal:
            retyped = True

        # Call driver to try and change the type
        retype_model_update = None
        if not retyped:
            try:
                new_type = volume_types.get_volume_type(context, new_type_id)
                ret = self.driver.retype(context,
                                         volume_ref,
                                         new_type,
                                         diff,
                                         host)
                # Check if the driver retype provided a model update or
                # just a retype indication
                if type(ret) == tuple:
                    retyped, retype_model_update = ret
                else:
                    retyped = ret

                if retyped:
                    LOG.info(_("Volume %s: retyped successfully"), volume_id)
            except Exception as ex:
                retyped = False
                LOG.error(_("Volume %s: driver error when trying to retype, "
                            "falling back to generic mechanism."),
                          volume_ref['id'])
                LOG.exception(ex)

        # We could not change the type, so we need to migrate the volume, where
        # the destination volume will be of the new type
        if not retyped:
            if migration_policy == 'never':
                _retype_error(context, volume_id, old_reservations,
                              new_reservations, status_update)
                msg = _("Retype requires migration but is not allowed.")
                raise exception.VolumeMigrationFailed(reason=msg)

            snaps = self.db.snapshot_get_all_for_volume(context,
                                                        volume_ref['id'])
            if snaps:
                _retype_error(context, volume_id, old_reservations,
                              new_reservations, status_update)
                msg = _("Volume must not have snapshots.")
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

            # Don't allow volume with replicas to be migrated
            rep_status = volume_ref['replication_status']
            if rep_status is not None and rep_status != 'disabled':
                _retype_error(context, volume_id, old_reservations,
                              new_reservations, status_update)
                msg = _("Volume must not be replicated.")
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

            self.db.volume_update(context, volume_ref['id'],
                                  {'migration_status': 'starting'})

            try:
                self.migrate_volume(context, volume_id, host,
                                    new_type_id=new_type_id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    _retype_error(context, volume_id, old_reservations,
                                  new_reservations, status_update)
        else:
            model_update = {'volume_type_id': new_type_id,
                            'host': host['host'],
                            'status': status_update['status']}
            if retype_model_update:
                model_update.update(retype_model_update)
            self.db.volume_update(context, volume_id, model_update)

        if old_reservations:
            QUOTAS.commit(context, old_reservations, project_id=project_id)
        if new_reservations:
            QUOTAS.commit(context, new_reservations, project_id=project_id)
        self.publish_service_capabilities(context)

    def manage_existing(self, ctxt, volume_id, ref=None):
        LOG.debug('manage_existing: managing %s.' % ref)
        try:
            flow_engine = manage_existing.get_flow(
                ctxt,
                self.db,
                self.driver,
                self.host,
                volume_id,
                ref)
        except Exception:
            LOG.exception(_("Failed to create manage_existing flow."))
            raise exception.CinderException(
                _("Failed to create manage existing flow."))

        with flow_utils.DynamicLogListener(flow_engine, logger=LOG):
            flow_engine.run()

        # Fetch created volume from storage
        vol_ref = flow_engine.storage.fetch('volume')
        # Update volume stats
        pool = vol_utils.extract_host(vol_ref['host'], 'pool')
        if pool is None:
            # Legacy volume, put them into default pool
            pool = self.driver.configuration.safe_get(
                'volume_backend_name') or vol_utils.extract_host(
                    vol_ref['host'], 'pool', True)

        try:
            self.stats['pools'][pool]['allocated_capacity_gb'] \
                += vol_ref['size']
        except KeyError:
            self.stats['pools'][pool] = dict(
                allocated_capacity_gb=vol_ref['size'])

        return vol_ref['id']

    def promote_replica(self, ctxt, volume_id):
        """Promote volume replica secondary to be the primary volume."""
        try:
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Failed to promote replica for volume %(id)s.")
                              % {'id': volume_id})

        volume = self.db.volume_get(ctxt, volume_id)
        model_update = None
        try:
            LOG.debug("Volume %s: promote replica.", volume_id)
            model_update = self.driver.promote_replica(ctxt, volume)
        except exception.CinderException:
            err_msg = (_('Error promoting secondary volume to primary'))
            raise exception.ReplicationError(reason=err_msg,
                                             volume_id=volume_id)

        try:
            if model_update:
                volume = self.db.volume_update(ctxt,
                                               volume_id,
                                               model_update)
        except exception.CinderException:
            err_msg = (_("Failed updating model"
                         " with driver provided model %(model)s") %
                       {'model': model_update})
            raise exception.ReplicationError(reason=err_msg,
                                             volume_id=volume_id)

    def reenable_replication(self, ctxt, volume_id):
        """Re-enable replication of secondary volume with primary volumes."""
        try:
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Failed to sync replica for volume %(id)s.")
                              % {'id': volume_id})

        volume = self.db.volume_get(ctxt, volume_id)
        model_update = None
        try:
            LOG.debug("Volume %s: sync replica.", volume_id)
            model_update = self.driver.reenable_replication(ctxt, volume)
        except exception.CinderException:
            err_msg = (_('Error synchronizing secondary volume to primary'))
            raise exception.ReplicationError(reason=err_msg,
                                             volume_id=volume_id)

        try:
            if model_update:
                volume = self.db.volume_update(ctxt,
                                               volume_id,
                                               model_update)
        except exception.CinderException:
            err_msg = (_("Failed updating model"
                         " with driver provided model %(model)s") %
                       {'model': model_update})
            raise exception.ReplicationError(reason=err_msg,
                                             volume_id=volume_id)

    @periodic_task.periodic_task
    def _update_replication_relationship_status(self, ctxt):
        LOG.info(_('Updating volume replication status.'))
        if not self.driver.initialized:
            if self.driver.configuration.config_group is None:
                config_group = ''
            else:
                config_group = ('(config name %s)' %
                                self.driver.configuration.config_group)

            LOG.warning(_('Unable to update volume replication status, '
                          '%(driver_name)s -%(driver_version)s '
                          '%(config_group)s driver is uninitialized.') %
                        {'driver_name': self.driver.__class__.__name__,
                         'driver_version': self.driver.get_version(),
                         'config_group': config_group})
        else:
            volumes = self.db.volume_get_all_by_host(ctxt, self.host)
            for vol in volumes:
                model_update = None
                try:
                    model_update = self.driver.get_replication_status(
                        ctxt, vol)
                    if model_update:
                        self.db.volume_update(ctxt,
                                              vol['id'],
                                              model_update)
                except Exception:
                    LOG.exception(_("Error checking replication status for "
                                    "volume %s") % vol['id'])

    def create_consistencygroup(self, context, group_id):
        """Creates the consistency group."""
        context = context.elevated()
        group_ref = self.db.consistencygroup_get(context, group_id)
        group_ref['host'] = self.host

        status = 'available'
        model_update = False

        self._notify_about_consistencygroup_usage(
            context, group_ref, "create.start")

        try:
            utils.require_driver_initialized(self.driver)

            LOG.info(_("Consistency group %s: creating"), group_ref['name'])
            model_update = self.driver.create_consistencygroup(context,
                                                               group_ref)

            if model_update:
                group_ref = self.db.consistencygroup_update(
                    context, group_ref['id'], model_update)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.consistencygroup_update(
                    context,
                    group_ref['id'],
                    {'status': 'error'})
                LOG.error(_("Consistency group %s: create failed"),
                          group_ref['name'])

        now = timeutils.utcnow()
        self.db.consistencygroup_update(context,
                                        group_ref['id'],
                                        {'status': status,
                                         'created_at': now})
        LOG.info(_("Consistency group %s: created successfully"),
                 group_ref['name'])

        self._notify_about_consistencygroup_usage(
            context, group_ref, "create.end")

        return group_ref['id']

    def delete_consistencygroup(self, context, group_id):
        """Deletes consistency group and the volumes in the group."""
        context = context.elevated()
        group_ref = self.db.consistencygroup_get(context, group_id)
        project_id = group_ref['project_id']

        if context.project_id != group_ref['project_id']:
            project_id = group_ref['project_id']
        else:
            project_id = context.project_id

        LOG.info(_("Consistency group %s: deleting"), group_ref['id'])

        volumes = self.db.volume_get_all_by_group(context, group_id)

        for volume_ref in volumes:
            if volume_ref['attach_status'] == "attached":
                # Volume is still attached, need to detach first
                raise exception.VolumeAttached(volume_id=volume_ref['id'])
            # self.host is 'host@backend'
            # volume_ref['host'] is 'host@backend#pool'
            # Extract host before doing comparison
            new_host = vol_utils.extract_host(volume_ref['host'])
            if new_host != self.host:
                raise exception.InvalidVolume(
                    reason=_("Volume is not local to this node"))

        self._notify_about_consistencygroup_usage(
            context, group_ref, "delete.start")

        try:
            utils.require_driver_initialized(self.driver)

            LOG.debug("Consistency group %(group_id)s: deleting",
                      {'group_id': group_id})

            model_update, volumes = self.driver.delete_consistencygroup(
                context, group_ref)

            if volumes:
                for volume in volumes:
                    update = {'status': volume['status']}
                    self.db.volume_update(context, volume['id'],
                                          update)
                    # If we failed to delete a volume, make sure the status
                    # for the cg is set to error as well
                    if (volume['status'] in ['error_deleting', 'error'] and
                            model_update['status'] not in
                            ['error_deleting', 'error']):
                        model_update['status'] = volume['status']

            if model_update:
                if model_update['status'] in ['error_deleting', 'error']:
                    msg = (_('Error occurred when deleting consistency group '
                             '%s.') % group_ref['id'])
                    LOG.exception(msg)
                    raise exception.VolumeDriverException(message=msg)
                else:
                    self.db.consistencygroup_update(context, group_ref['id'],
                                                    model_update)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.consistencygroup_update(
                    context,
                    group_ref['id'],
                    {'status': 'error_deleting'})

        # Get reservations for group
        try:
            reserve_opts = {'consistencygroups': -1}
            cgreservations = CGQUOTAS.reserve(context,
                                              project_id=project_id,
                                              **reserve_opts)
        except Exception:
            cgreservations = None
            LOG.exception(_("Failed to update usages deleting "
                          "consistency groups."))

        for volume_ref in volumes:
            # Get reservations for volume
            try:
                volume_id = volume_ref['id']
                reserve_opts = {'volumes': -1,
                                'gigabytes': -volume_ref['size']}
                QUOTAS.add_volume_type_opts(context,
                                            reserve_opts,
                                            volume_ref.get('volume_type_id'))
                reservations = QUOTAS.reserve(context,
                                              project_id=project_id,
                                              **reserve_opts)
            except Exception:
                reservations = None
                LOG.exception(_("Failed to update usages deleting volume."))

            # Delete glance metadata if it exists
            self.db.volume_glance_metadata_delete_by_volume(context, volume_id)

            self.db.volume_destroy(context, volume_id)

            # Commit the reservations
            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

            self.stats['allocated_capacity_gb'] -= volume_ref['size']

        if cgreservations:
            CGQUOTAS.commit(context, cgreservations,
                            project_id=project_id)

        self.db.consistencygroup_destroy(context, group_id)
        LOG.info(_("Consistency group %s: deleted successfully."),
                 group_id)
        self._notify_about_consistencygroup_usage(
            context, group_ref, "delete.end")
        self.publish_service_capabilities(context)

        return True

    def create_cgsnapshot(self, context, group_id, cgsnapshot_id):
        """Creates the cgsnapshot."""
        caller_context = context
        context = context.elevated()
        cgsnapshot_ref = self.db.cgsnapshot_get(context, cgsnapshot_id)
        LOG.info(_("Cgsnapshot %s: creating."), cgsnapshot_ref['id'])

        snapshots = self.db.snapshot_get_all_for_cgsnapshot(context,
                                                            cgsnapshot_id)

        self._notify_about_cgsnapshot_usage(
            context, cgsnapshot_ref, "create.start")

        try:
            utils.require_driver_initialized(self.driver)

            LOG.debug("Cgsnapshot %(cgsnap_id)s: creating.",
                      {'cgsnap_id': cgsnapshot_id})

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            cgsnapshot_ref['context'] = caller_context
            for snapshot in snapshots:
                snapshot['context'] = caller_context

            model_update, snapshots = \
                self.driver.create_cgsnapshot(context, cgsnapshot_ref)

            if snapshots:
                for snapshot in snapshots:
                    # Update db if status is error
                    if snapshot['status'] == 'error':
                        update = {'status': snapshot['status']}
                        self.db.snapshot_update(context, snapshot['id'],
                                                update)
                        # If status for one snapshot is error, make sure
                        # the status for the cgsnapshot is also error
                        if model_update['status'] != 'error':
                            model_update['status'] = snapshot['status']

            if model_update:
                if model_update['status'] == 'error':
                    msg = (_('Error occurred when creating cgsnapshot '
                             '%s.') % cgsnapshot_ref['id'])
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.cgsnapshot_update(context,
                                          cgsnapshot_ref['id'],
                                          {'status': 'error'})

        for snapshot in snapshots:
            volume_id = snapshot['volume_id']
            snapshot_id = snapshot['id']
            vol_ref = self.db.volume_get(context, volume_id)
            if vol_ref.bootable:
                try:
                    self.db.volume_glance_metadata_copy_to_snapshot(
                        context, snapshot['id'], volume_id)
                except exception.CinderException as ex:
                    LOG.error(_("Failed updating %(snapshot_id)s"
                                " metadata using the provided volumes"
                                " %(volume_id)s metadata") %
                              {'volume_id': volume_id,
                               'snapshot_id': snapshot_id})
                    self.db.snapshot_update(context,
                                            snapshot['id'],
                                            {'status': 'error'})
                    raise exception.MetadataCopyFailure(reason=ex)

            self.db.snapshot_update(context,
                                    snapshot['id'], {'status': 'available',
                                                     'progress': '100%'})

        self.db.cgsnapshot_update(context,
                                  cgsnapshot_ref['id'],
                                  {'status': 'available'})

        LOG.info(_("cgsnapshot %s: created successfully"),
                 cgsnapshot_ref['id'])
        self._notify_about_cgsnapshot_usage(
            context, cgsnapshot_ref, "create.end")
        return cgsnapshot_id

    def delete_cgsnapshot(self, context, cgsnapshot_id):
        """Deletes cgsnapshot."""
        caller_context = context
        context = context.elevated()
        cgsnapshot_ref = self.db.cgsnapshot_get(context, cgsnapshot_id)
        project_id = cgsnapshot_ref['project_id']

        LOG.info(_("cgsnapshot %s: deleting"), cgsnapshot_ref['id'])

        snapshots = self.db.snapshot_get_all_for_cgsnapshot(context,
                                                            cgsnapshot_id)

        self._notify_about_cgsnapshot_usage(
            context, cgsnapshot_ref, "delete.start")

        try:
            utils.require_driver_initialized(self.driver)

            LOG.debug("cgsnapshot %(cgsnap_id)s: deleting",
                      {'cgsnap_id': cgsnapshot_id})

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            cgsnapshot_ref['context'] = caller_context
            for snapshot in snapshots:
                snapshot['context'] = caller_context

            model_update, snapshots = \
                self.driver.delete_cgsnapshot(context, cgsnapshot_ref)

            if snapshots:
                for snapshot in snapshots:
                    update = {'status': snapshot['status']}
                    self.db.snapshot_update(context, snapshot['id'],
                                            update)
                    if snapshot['status'] in ['error_deleting', 'error'] and \
                            model_update['status'] not in \
                            ['error_deleting', 'error']:
                        model_update['status'] = snapshot['status']

            if model_update:
                if model_update['status'] in ['error_deleting', 'error']:
                    msg = (_('Error occurred when deleting cgsnapshot '
                             '%s.') % cgsnapshot_ref['id'])
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)
                else:
                    self.db.cgsnapshot_update(context, cgsnapshot_ref['id'],
                                              model_update)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.cgsnapshot_update(context,
                                          cgsnapshot_ref['id'],
                                          {'status': 'error_deleting'})

        for snapshot in snapshots:
            # Get reservations
            try:
                if CONF.no_snapshot_gb_quota:
                    reserve_opts = {'snapshots': -1}
                else:
                    reserve_opts = {
                        'snapshots': -1,
                        'gigabytes': -snapshot['volume_size'],
                    }
                volume_ref = self.db.volume_get(context, snapshot['volume_id'])
                QUOTAS.add_volume_type_opts(context,
                                            reserve_opts,
                                            volume_ref.get('volume_type_id'))
                reservations = QUOTAS.reserve(context,
                                              project_id=project_id,
                                              **reserve_opts)

            except Exception:
                reservations = None
                LOG.exception(_("Failed to update usages deleting snapshot"))

            self.db.volume_glance_metadata_delete_by_snapshot(context,
                                                              snapshot['id'])
            self.db.snapshot_destroy(context, snapshot['id'])

            # Commit the reservations
            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

        self.db.cgsnapshot_destroy(context, cgsnapshot_id)
        LOG.info(_("cgsnapshot %s: deleted successfully"),
                 cgsnapshot_ref['id'])
        self._notify_about_cgsnapshot_usage(
            context, cgsnapshot_ref, "delete.end")

        return True
