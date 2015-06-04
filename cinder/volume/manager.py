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

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_service import periodic_task
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
from osprofiler import profiler
import six
from taskflow import exceptions as tfe

from cinder import compute
from cinder import context
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _, _LE, _LI, _LW
from cinder.image import glance
from cinder import manager
from cinder import objects
from cinder import quota
from cinder import utils
from cinder.volume import configuration as config
from cinder.volume.flows.manager import create_volume
from cinder.volume.flows.manager import manage_existing
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as vol_utils
from cinder.volume import volume_types

from eventlet import greenpool

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS
CGQUOTAS = quota.CGQUOTAS
VALID_REMOVE_VOL_FROM_CG_STATUS = ('available', 'in-use',)
VALID_CREATE_CG_SRC_SNAP_STATUS = ('available',)

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
                    'specifying key/value pairs. The key/value pairs can '
                    'be used by the CapabilitiesFilter to select between '
                    'backends when requests specify volume types. For '
                    'example, specifying a service level or the geographical '
                    'location of a backend, then creating a volume type to '
                    'allow the user to select by these different '
                    'properties.'),
]

CONF = cfg.CONF
CONF.register_opts(volume_manager_opts)

MAPPING = {
    'cinder.volume.drivers.huawei.huawei_18000.Huawei18000ISCSIDriver':
    'cinder.volume.drivers.huawei.huawei_driver.Huawei18000ISCSIDriver',
    'cinder.volume.drivers.huawei.huawei_18000.Huawei18000FCDriver':
    'cinder.volume.drivers.huawei.huawei_driver.Huawei18000FCDriver',
    'cinder.volume.drivers.fujitsu_eternus_dx_fc.FJDXFCDriver':
    'cinder.volume.drivers.fujitsu.eternus_dx_fc.FJDXFCDriver',
    'cinder.volume.drivers.fujitsu_eternus_dx_iscsi.FJDXISCSIDriver':
    'cinder.volume.drivers.fujitsu.eternus_dx_iscsi.FJDXISCSIDriver',
    'cinder.volume.drivers.hds.nfs.HDSNFSDriver':
    'cinder.volume.drivers.hitachi.hnas_nfs.HDSNFSDriver',
    'cinder.volume.drivers.hds.iscsi.HDSISCSIDriver':
    'cinder.volume.drivers.hitachi.hnas_iscsi.HDSISCSIDriver'}


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


def locked_detach_operation(f):
    """Lock decorator for volume detach operations.

    Takes a named lock prior to executing the detach call.  The lock is named
    with the operation executed and the id of the volume. This lock can then
    be used by other operations to avoid operation conflicts on shared volumes.

    This locking mechanism is only for detach calls.   We can't use the
    locked_volume_operation, because detach requires an additional
    attachment_id in the parameter list.
    """
    def ldo_inner1(inst, context, volume_id, attachment_id=None, **kwargs):
        @utils.synchronized("%s-%s" % (volume_id, f.__name__), external=True)
        def ldo_inner2(*_args, **_kwargs):
            return f(*_args, **_kwargs)
        return ldo_inner2(inst, context, volume_id, attachment_id, **kwargs)
    return ldo_inner1


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
    def lso_inner1(inst, context, snapshot, **kwargs):
        @utils.synchronized("%s-%s" % (snapshot.id, f.__name__), external=True)
        def lso_inner2(*_args, **_kwargs):
            return f(*_args, **_kwargs)
        return lso_inner2(inst, context, snapshot, **kwargs)
    return lso_inner1


class VolumeManager(manager.SchedulerDependentManager):
    """Manages attachable block storage devices."""

    RPC_API_VERSION = '1.23'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, volume_driver=None, service_name=None,
                 *args, **kwargs):
        """Load the driver from the one specified in args, or from flags."""
        # update_service_capabilities needs service_name to be volume
        super(VolumeManager, self).__init__(service_name='volume',
                                            *args, **kwargs)
        self.configuration = config.Configuration(volume_manager_opts,
                                                  config_group=service_name)
        self._tp = greenpool.GreenPool()
        self.stats = {}

        if not volume_driver:
            # Get from configuration, which will get the default
            # if its not using the multi backend
            volume_driver = self.configuration.volume_driver
        if volume_driver in MAPPING:
            LOG.warning(_LW("Driver path %s is deprecated, update your "
                            "configuration to the new path."), volume_driver)
            volume_driver = MAPPING[volume_driver]

        vol_db_empty = self._set_voldb_empty_at_startup_indicator(
            context.get_admin_context())
        LOG.debug("Cinder Volume DB check: vol_db_empty=%s", vol_db_empty)

        self.driver = importutils.import_object(
            volume_driver,
            configuration=self.configuration,
            db=self.db,
            host=self.host,
            is_vol_db_empty=vol_db_empty)

        self.driver = profiler.trace_cls("driver")(self.driver)
        try:
            self.extra_capabilities = jsonutils.loads(
                self.driver.configuration.extra_capabilities)
        except AttributeError:
            self.extra_capabilities = {}
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Invalid JSON: %s"),
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
            except Exception:
                LOG.exception(_LE('Fetch volume pool name failed.'),
                              resource=volume)
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

    def _set_voldb_empty_at_startup_indicator(self, ctxt):
        """Determine if the Cinder volume DB is empty.

        A check of the volume DB is done to determine whether it is empty or
        not at this point.

        :param ctxt: our working context
        """
        vol_entries = self.db.volume_get_all(ctxt, None, 1, filters=None)

        if len(vol_entries) == 0:
            LOG.info(_LI("Determined volume DB was empty at startup."))
            return True
        else:
            LOG.info(_LI("Determined volume DB was not empty at startup."))
            return False

    def init_host(self):
        """Perform any required initialization."""

        ctxt = context.get_admin_context()

        LOG.info(_LI("Starting volume driver %(driver_name)s (%(version)s)"),
                 {'driver_name': self.driver.__class__.__name__,
                  'version': self.driver.get_version()})
        try:
            self.driver.do_setup(ctxt)
            self.driver.check_for_setup_error()
        except Exception:
            LOG.exception(_LE("Failed to initialize driver."),
                          resource={'type': 'driver',
                                    'id': self.__class__.__name__})
            # we don't want to continue since we failed
            # to initialize the driver correctly.
            return

        volumes = self.db.volume_get_all_by_host(ctxt, self.host)
        # FIXME volume count for exporting is wrong

        try:
            self.stats['pools'] = {}
            self.stats.update({'allocated_capacity_gb': 0})
            for volume in volumes:
                # available volume should also be counted into allocated
                if volume['status'] in ['in-use', 'available']:
                    # calculate allocated capacity for driver
                    self._count_allocated_capacity(ctxt, volume)

                    try:
                        if volume['status'] in ['in-use']:
                            self.driver.ensure_export(ctxt, volume)
                    except Exception:
                        LOG.exception(_LE("Failed to re-export volume, "
                                          "setting to ERROR."),
                                      resource=volume)
                        self.db.volume_update(ctxt,
                                              volume['id'],
                                              {'status': 'error'})
                elif volume['status'] in ('downloading', 'creating'):
                    LOG.warning(_LW("Detected volume stuck "
                                    "in %s(curr_status)s "
                                    "status, setting to ERROR."),
                                {'curr_status': volume['status']},
                                resource=volume)

                    if volume['status'] == 'downloading':
                        self.driver.clear_download(ctxt, volume)
                    self.db.volume_update(ctxt,
                                          volume['id'],
                                          {'status': 'error'})
                else:
                    pass
            snapshots = objects.SnapshotList.get_by_host(
                ctxt, self.host, {'status': 'creating'})
            for snapshot in snapshots:
                LOG.warning(_LW("Detected snapshot stuck in creating "
                            "status, setting to ERROR."), resource=snapshot)
                snapshot.status = 'error'
                snapshot.save()
        except Exception:
            LOG.exception(_LE("Error during re-export on driver init."),
                          resource=volume)
            return

        self.driver.set_throttle()

        # at this point the driver is considered initialized.
        self.driver.set_initialized()

        for volume in volumes:
            if volume['status'] == 'deleting':
                if CONF.volume_service_inithost_offload:
                    # Offload all the pending volume delete operations to the
                    # threadpool to prevent the main volume service thread
                    # from being blocked.
                    self._add_to_threadpool(self.delete_volume, ctxt,
                                            volume['id'])
                else:
                    # By default, delete volumes sequentially
                    self.delete_volume(ctxt, volume['id'])
                LOG.info(_LI("Resume volume delete completed successfully."),
                         resource=volume)

        # collect and publish service capabilities
        self.publish_service_capabilities(ctxt)

        # conditionally run replication status task
        stats = self.driver.get_volume_stats(refresh=True)
        if stats and stats.get('replication', False):

            @periodic_task.periodic_task
            def run_replication_task(self, ctxt):
                self._update_replication_relationship_status(ctxt)

            self.add_periodic_task(run_replication_task)
        LOG.info(_LI("Driver initialization completed successfully."),
                 resource={'type': 'driver',
                           'id': self.driver.__class__.__name__})

    def is_working(self):
        """Return if Manager is ready to accept requests.

        This is to inform Service class that in case of volume driver
        initialization failure the manager is actually down and not ready to
        accept any requests.
        """
        return self.driver.initialized

    def create_volume(self, context, volume_id, request_spec=None,
                      filter_properties=None, allow_reschedule=True,
                      snapshot_id=None, image_id=None, source_volid=None,
                      source_replicaid=None, consistencygroup_id=None,
                      cgsnapshot_id=None):

        """Creates the volume."""
        context_elevated = context.elevated()
        if filter_properties is None:
            filter_properties = {}

        try:
            # NOTE(flaper87): Driver initialization is
            # verified by the task itself.
            flow_engine = create_volume.get_flow(
                context_elevated,
                self.db,
                self.driver,
                self.scheduler_rpcapi,
                self.host,
                volume_id,
                allow_reschedule,
                context,
                request_spec,
                filter_properties,
                snapshot_id=snapshot_id,
                image_id=image_id,
                source_volid=source_volid,
                source_replicaid=source_replicaid,
                consistencygroup_id=consistencygroup_id,
                cgsnapshot_id=cgsnapshot_id)
        except Exception:
            msg = _("Create manager volume flow failed.")
            LOG.exception(msg, resource={'type': 'volume', 'id': volume_id})
            raise exception.CinderException(msg)

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

        # NOTE(dulek): Flag to indicate if volume was rescheduled. Used to
        # decide if allocated_capacity should be incremented.
        rescheduled = False

        try:
            if locked_action is None:
                _run_flow()
            else:
                _run_flow_locked()
        except Exception as e:
            if hasattr(e, 'rescheduled'):
                rescheduled = e.rescheduled
            raise
        finally:
            try:
                vol_ref = flow_engine.storage.fetch('volume_ref')
            except tfe.NotFound as e:
                # Flow was reverted, fetching volume_ref from the DB.
                vol_ref = self.db.volume_get(context, volume_id)

            if not rescheduled:
                # NOTE(dulek): Volume wasn't rescheduled so we need to update
                # volume stats as these are decremented on delete.
                self._update_allocated_capacity(vol_ref)

        LOG.info(_LI("Created volume successfully."), resource=vol_ref)
        return vol_ref['id']

    @locked_volume_operation
    def delete_volume(self, context, volume_id, unmanage_only=False):
        """Deletes and unexports volume.

        1. Delete a volume(normal case)
           Delete a volume and update quotas.

        2. Delete a migration source volume
           If deleting the source volume in a migration, we want to skip
           quotas. Also we want to skip other database updates for source
           volume because these update will be handled at
           migrate_volume_completion properly.

        3. Delete a migration destination volume
           If deleting the destination volume in a migration, we want to
           skip quotas but we need database updates for the volume.
      """

        context = context.elevated()

        try:
            volume_ref = self.db.volume_get(context, volume_id)
        except exception.VolumeNotFound:
            # NOTE(thingee): It could be possible for a volume to
            # be deleted when resuming deletes from init_host().
            LOG.debug("Attempted delete of non-existent volume: %s",
                      volume_id)
            return True

        if context.project_id != volume_ref['project_id']:
            project_id = volume_ref['project_id']
        else:
            project_id = context.project_id

        if volume_ref['attach_status'] == "attached":
            # Volume is still attached, need to detach first
            raise exception.VolumeAttached(volume_id=volume_id)
        if vol_utils.extract_host(volume_ref['host']) != self.host:
            raise exception.InvalidVolume(
                reason=_("volume is not local to this node"))

        is_migrating = volume_ref['migration_status'] is not None
        is_migrating_dest = (is_migrating and
                             volume_ref['migration_status'].startswith(
                                 'target:'))
        self._notify_about_volume_usage(context, volume_ref, "delete.start")
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)

            self.driver.remove_export(context, volume_ref)
            if unmanage_only:
                self.driver.unmanage(volume_ref)
            else:
                self.driver.delete_volume(volume_ref)
        except exception.VolumeIsBusy:
            LOG.error(_LE("Unable to delete busy volume."),
                      resource=volume_ref)
            # If this is a destination volume, we have to clear the database
            # record to avoid user confusion.
            self._clear_db(context, is_migrating_dest, volume_ref,
                           'available')
            return True
        except Exception:
            with excutils.save_and_reraise_exception():
                # If this is a destination volume, we have to clear the
                # database record to avoid user confusion.
                self._clear_db(context, is_migrating_dest, volume_ref,
                               'error_deleting')

        # If deleting source/destination volume in a migration, we should
        # skip quotas.
        if not is_migrating:
            # Get reservations
            try:
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
                LOG.exception(_LE("Failed to update usages deleting volume."),
                              resource=volume_ref)

        # If deleting the source volume in a migration, we should skip database
        # update here. In other cases, continue to update database entries.
        if not is_migrating or is_migrating_dest:

            # Delete glance metadata if it exists
            self.db.volume_glance_metadata_delete_by_volume(context, volume_id)

            self.db.volume_destroy(context, volume_id)

        # If deleting source/destination volume in a migration, we should
        # skip quotas.
        if not is_migrating:
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

        LOG.info(_LI("Deleted volume successfully."), resource=volume_ref)
        return True

    def _clear_db(self, context, is_migrating_dest, volume_ref, status):
        # This method is called when driver.unmanage() or
        # driver.delete_volume() fails in delete_volume(), so it is already
        # in the exception handling part.
        if is_migrating_dest:
            self.db.volume_destroy(context, volume_ref['id'])
            LOG.error(_LE("Unable to delete the destination volume "
                          "during volume migration, (NOTE: database "
                          "record needs to be deleted)."), resource=volume_ref)
        else:
            self.db.volume_update(context,
                                  volume_ref['id'],
                                  {'status': status})

    def create_snapshot(self, context, volume_id, snapshot):
        """Creates and exports the snapshot."""
        context = context.elevated()

        self._notify_about_snapshot_usage(
            context, snapshot, "create.start")

        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the snapshot status updated.
            utils.require_driver_initialized(self.driver)

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            snapshot.context = context

            model_update = self.driver.create_snapshot(snapshot)
            if model_update:
                snapshot.update(model_update)
                snapshot.save()

        except Exception:
            with excutils.save_and_reraise_exception():
                snapshot.status = 'error'
                snapshot.save()

        vol_ref = self.db.volume_get(context, volume_id)
        if vol_ref.bootable:
            try:
                self.db.volume_glance_metadata_copy_to_snapshot(
                    context, snapshot.id, volume_id)
            except exception.GlanceMetadataNotFound:
                # If volume is not created from image, No glance metadata
                # would be available for that volume in
                # volume glance metadata table
                pass
            except exception.CinderException as ex:
                LOG.exception(_LE("Failed updating snapshot"
                                  " metadata using the provided volumes"
                                  " %(volume_id)s metadata"),
                              {'volume_id': volume_id}, resource=snapshot)
                snapshot.status = 'error'
                snapshot.save()
                raise exception.MetadataCopyFailure(reason=six.text_type(ex))

        snapshot.status = 'available'
        snapshot.progress = '100%'
        snapshot.save()

        self._notify_about_snapshot_usage(context, snapshot, "create.end")
        LOG.info(_LI("Create snapshot completed successfully"),
                 resource=snapshot)
        return snapshot.id

    @locked_snapshot_operation
    def delete_snapshot(self, context, snapshot):
        """Deletes and unexports snapshot."""
        context = context.elevated()
        snapshot._context = context
        project_id = snapshot.project_id

        self._notify_about_snapshot_usage(
            context, snapshot, "delete.start")

        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the snapshot status updated.
            utils.require_driver_initialized(self.driver)

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            snapshot.context = context
            snapshot.save()

            self.driver.delete_snapshot(snapshot)
        except exception.SnapshotIsBusy:
            LOG.error(_LE("Delete snapshot failed, due to snapshot busy."),
                      resource=snapshot)
            snapshot.status = 'available'
            snapshot.save()
            return True
        except Exception:
            with excutils.save_and_reraise_exception():
                snapshot.status = 'error_deleting'
                snapshot.save()

        # Get reservations
        try:
            if CONF.no_snapshot_gb_quota:
                reserve_opts = {'snapshots': -1}
            else:
                reserve_opts = {
                    'snapshots': -1,
                    'gigabytes': -snapshot.volume_size,
                }
            volume_ref = self.db.volume_get(context, snapshot.volume_id)
            QUOTAS.add_volume_type_opts(context,
                                        reserve_opts,
                                        volume_ref.get('volume_type_id'))
            reservations = QUOTAS.reserve(context,
                                          project_id=project_id,
                                          **reserve_opts)
        except Exception:
            reservations = None
            LOG.exception(_LE("Update snapshot usages failed."),
                          resource=snapshot)
        self.db.volume_glance_metadata_delete_by_snapshot(context, snapshot.id)
        snapshot.destroy()
        self._notify_about_snapshot_usage(context, snapshot, "delete.end")

        # Commit the reservations
        if reservations:
            QUOTAS.commit(context, reservations, project_id=project_id)
        LOG.info(_LI("Delete snapshot completed successfully"),
                 resource=snapshot)
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
                if (volume_metadata.get('attached_mode') and
                   volume_metadata.get('attached_mode') != mode):
                    raise exception.InvalidVolume(
                        reason=_("being attached by different mode"))

            if (volume['status'] == 'in-use' and not volume['multiattach']
               and not volume['migration_status']):
                raise exception.InvalidVolume(
                    reason=_("volume is already attached"))

            attachment = None
            host_name_sanitized = utils.sanitize_hostname(
                host_name) if host_name else None
            if instance_uuid:
                attachment = \
                    self.db.volume_attachment_get_by_instance_uuid(
                        context, volume_id, instance_uuid)
            else:
                attachment = \
                    self.db.volume_attachment_get_by_host(context, volume_id,
                                                          host_name_sanitized)
            if attachment is not None:
                self.db.volume_update(context, volume_id,
                                      {'status': 'in-use'})
                return

            self._notify_about_volume_usage(context, volume,
                                            "attach.start")
            values = {'volume_id': volume_id,
                      'attach_status': 'attaching', }

            attachment = self.db.volume_attach(context.elevated(), values)
            volume_metadata = self.db.volume_admin_metadata_update(
                context.elevated(), volume_id,
                {"attached_mode": mode}, False)

            attachment_id = attachment['id']
            if instance_uuid and not uuidutils.is_uuid_like(instance_uuid):
                self.db.volume_attachment_update(context, attachment_id,
                                                 {'attach_status':
                                                  'error_attaching'})
                raise exception.InvalidUUID(uuid=instance_uuid)

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
                    self.db.volume_attachment_update(
                        context, attachment_id,
                        {'attach_status': 'error_attaching'})

            volume = self.db.volume_attached(context.elevated(),
                                             attachment_id,
                                             instance_uuid,
                                             host_name_sanitized,
                                             mountpoint,
                                             mode)
            if volume['migration_status']:
                self.db.volume_update(context, volume_id,
                                      {'migration_status': None})
            self._notify_about_volume_usage(context, volume, "attach.end")
            LOG.info(_LI("Attach volume completed successfully."),
                     resource=volume)
            return self.db.volume_attachment_get(context, attachment_id)
        return do_attach()

    @locked_detach_operation
    def detach_volume(self, context, volume_id, attachment_id=None):
        """Updates db to show volume is detached."""
        # TODO(vish): refactor this into a more general "unreserve"
        volume = self.db.volume_get(context, volume_id)
        attachment = None
        if attachment_id:
            try:
                attachment = self.db.volume_attachment_get(context,
                                                           attachment_id)
            except exception.VolumeAttachmentNotFound:
                LOG.error(_LE("Find attachment in detach_volume failed."),
                          resource=volume)
                raise
        else:
            # We can try and degrade gracefully here by trying to detach
            # a volume without the attachment_id here if the volume only has
            # one attachment.  This is for backwards compatibility.
            attachments = self.db.volume_attachment_get_used_by_volume_id(
                context, volume_id)
            if len(attachments) > 1:
                # There are more than 1 attachments for this volume
                # we have to have an attachment id.
                msg = _("Detach volume failed: More than one attachment, "
                        "but no attachment_id provided.")
                LOG.error(msg, resource=volume)
                raise exception.InvalidVolume(reason=msg)
            elif len(attachments) == 1:
                attachment = attachments[0]
            else:
                # there aren't any attachments for this volume.
                msg = _("Detach volume failed, because there are currently no "
                        "active attachments.")
                LOG.error(msg, resource=volume)
                raise exception.InvalidVolume(reason=msg)

        self._notify_about_volume_usage(context, volume, "detach.start")
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)

            self.driver.detach_volume(context, volume, attachment)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_attachment_update(
                    context, attachment.get('id'),
                    {'attach_status': 'error_detaching'})

        self.db.volume_detached(context.elevated(), volume_id,
                                attachment.get('id'))
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
            self.driver.remove_export(context.elevated(), volume)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Detach volume failed, due to "
                                  "uninitialized driver."),
                              resource=volume)
        except Exception as ex:
            LOG.exception(_LE("Detach volume failed, due to "
                              "remove-export failure."),
                          resource=volume)
            raise exception.RemoveExportException(volume=volume_id,
                                                  reason=six.text_type(ex))

        self._notify_about_volume_usage(context, volume, "detach.end")
        LOG.info(_LI("Detach volume completed successfully."), resource=volume)

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
            LOG.debug("Uploaded volume to glance image-id: %(image_id)s.",
                      resource=volume)
        except Exception as error:
            LOG.error(_LE("Upload volume to image encountered an error "
                          "(image-id: %(image_id)s)."),
                      {'image_id': image_meta['id']},
                      resource=volume)
            if image_service is not None:
                # Deletes the image if it is in queued or saving state
                self._delete_image(context, image_meta['id'], image_service)

            with excutils.save_and_reraise_exception():
                payload['message'] = six.text_type(error)
        finally:
            self.db.volume_update_status_based_on_attachment(context,
                                                             volume_id)
        LOG.info(_LI("Copy volume to image completed successfully."),
                 resource=volume)

    def _delete_image(self, context, image_id, image_service):
        """Deletes an image stuck in queued or saving state."""
        try:
            image_meta = image_service.show(context, image_id)
            image_status = image_meta.get('status')
            if image_status == 'queued' or image_status == 'saving':
                LOG.warning(_LW("Deleting image in unexpected status: "
                                "%(image_status)s."),
                            {'image_status': image_status},
                            resource={'type': 'image', 'id': image_id})
                image_service.delete(context, image_id)
        except Exception:
            LOG.warning(_LW("Image delete encountered an error."),
                        exc_info=True, resource={'type': 'image',
                                                 'id': image_id})

    def _driver_data_namespace(self):
        return self.driver.configuration.safe_get('driver_data_namespace') \
            or self.driver.configuration.safe_get('volume_backend_name') \
            or self.driver.__class__.__name__

    def _get_driver_initiator_data(self, context, connector):
        data = None
        initiator = connector.get('initiator', False)
        if initiator:
            namespace = self._driver_data_namespace()
            try:
                data = self.db.driver_initiator_data_get(
                    context,
                    initiator,
                    namespace
                )
            except exception.CinderException:
                LOG.exception(_LE("Failed to get driver initiator data for"
                                  " initiator %(initiator)s and namespace"
                                  " %(namespace)s"),
                              {'initiator': initiator,
                               'namespace': namespace})
                raise
        return data

    def _save_driver_initiator_data(self, context, connector, model_update):
        if connector.get('initiator', False) and model_update:
            namespace = self._driver_data_namespace()
            try:
                self.db.driver_initiator_data_update(context,
                                                     connector['initiator'],
                                                     namespace,
                                                     model_update)
            except exception.CinderException:
                LOG.exception(_LE("Failed to update initiator data for"
                                  " initiator %(initiator)s and backend"
                                  " %(backend)s"),
                              {'initiator': connector['initiator'],
                               'backend': namespace})
                raise

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
        volume = self.db.volume_get(context, volume_id)
        model_update = None
        try:
            self.driver.validate_connector(connector)
        except exception.InvalidConnectorException as err:
            raise exception.InvalidInput(reason=six.text_type(err))
        except Exception as err:
            err_msg = (_("Validate volume connection failed "
                         "(error: %(err)).") % {'err': six.text_type(err)})
            LOG.error(err_msg, resource=volume)
            raise exception.VolumeBackendAPIException(data=err_msg)

        try:
            model_update = self.driver.create_export(context.elevated(),
                                                     volume)
        except exception.CinderException:
            err_msg = (_("Create export for volume failed."))
            LOG.exception(err_msg, resource=volume)
            raise exception.VolumeBackendAPIException(data=err_msg)

        try:
            if model_update:
                volume = self.db.volume_update(context,
                                               volume_id,
                                               model_update)
        except exception.CinderException as ex:
            LOG.exception(_LE("Model update failed."), resource=volume)
            raise exception.ExportFailure(reason=six.text_type(ex))

        initiator_data = self._get_driver_initiator_data(context, connector)
        try:
            if initiator_data:
                conn_info = self.driver.initialize_connection(volume,
                                                              connector,
                                                              initiator_data)
            else:
                conn_info = self.driver.initialize_connection(volume,
                                                              connector)
        except Exception as err:
            err_msg = (_("Driver initialize connection failed "
                         "(error: %(err)s).") % {'err': six.text_type(err)})
            LOG.error(err_msg, resource=volume)

            self.driver.remove_export(context.elevated(), volume)

            raise exception.VolumeBackendAPIException(data=err_msg)

        initiator_update = conn_info.get('initiator_update', None)
        if initiator_update:
            self._save_driver_initiator_data(context, connector,
                                             initiator_update)
            del conn_info['initiator_update']

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

        # Add encrypted flag to connection_info if not set in the driver.
        if conn_info['data'].get('encrypted') is None:
            encrypted = bool(volume.get('encryption_key_id'))
            conn_info['data']['encrypted'] = encrypted

        LOG.info(_LI("Initialize volume connection completed successfully."),
                 resource=volume)
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
            err_msg = (_('Terminate volume connection failed: %(err)s')
                       % {'err': six.text_type(err)})
            LOG.error(err_msg, resource=volume_ref)
            raise exception.VolumeBackendAPIException(data=err_msg)
        LOG.info(_LI("Terminate volume connection completed successfully."),
                 resource=volume_ref)

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
                    LOG.exception(_LE("Update volume model for "
                                      "transfer operation failed."),
                                  resource=volume_ref)
                    self.db.volume_update(context.elevated(),
                                          volume_id,
                                          {'status': 'error'})

        LOG.info(_LI("Transfer volume completed successfully."),
                 resource=volume_ref)
        return model_update

    def _migrate_volume_generic(self, ctxt, volume, host, new_type_id):
        rpcapi = volume_rpcapi.VolumeAPI()

        # Create new volume on remote host
        new_vol_values = dict(volume)
        del new_vol_values['id']
        del new_vol_values['_name_id']
        # We don't copy volume_type because the db sets that according to
        # volume_type_id, which we do copy
        del new_vol_values['volume_type']
        if new_type_id:
            new_vol_values['volume_type_id'] = new_type_id
        new_vol_values['host'] = host['host']
        new_vol_values['status'] = 'creating'

        # FIXME(jdg): using a : delimeter is confusing to
        # me below here.  We're adding a string member to a dict
        # using a :, which is kind of a poor choice in this case
        # I think
        new_vol_values['migration_status'] = 'target:%s' % volume['id']
        new_vol_values['attach_status'] = 'detached'
        new_vol_values['volume_attachment'] = []
        new_volume = self.db.volume_create(ctxt, new_vol_values)
        rpcapi.create_volume(ctxt, new_volume, host['host'],
                             None, None, allow_reschedule=False)

        # Wait for new_volume to become ready
        starttime = time.time()
        deadline = starttime + CONF.migration_create_volume_timeout_secs
        new_volume = self.db.volume_get(ctxt, new_volume['id'])
        tries = 0
        while new_volume['status'] != 'available':
            tries += 1
            now = time.time()
            if new_volume['status'] == 'error':
                msg = _("failed to create new_volume on destination host")
                self._clean_temporary_volume(ctxt, volume['id'],
                                             new_volume['id'],
                                             clean_db_only=True)
                raise exception.VolumeMigrationFailed(reason=msg)
            elif now > deadline:
                msg = _("timeout creating new_volume on destination host")
                self._clean_temporary_volume(ctxt, volume['id'],
                                             new_volume['id'],
                                             clean_db_only=True)
                raise exception.VolumeMigrationFailed(reason=msg)
            else:
                time.sleep(tries ** 2)
            new_volume = self.db.volume_get(ctxt, new_volume['id'])

        # Copy the source volume to the destination volume
        try:
            attachments = volume['volume_attachment']
            if not attachments:
                self.driver.copy_volume_data(ctxt, volume, new_volume,
                                             remote='dest')
                # The above call is synchronous so we complete the migration
                self.migrate_volume_completion(ctxt, volume['id'],
                                               new_volume['id'],
                                               error=False)
            else:
                nova_api = compute.API()
                # This is an async call to Nova, which will call the completion
                # when it's done
                for attachment in attachments:
                    instance_uuid = attachment['instance_uuid']
                    nova_api.update_server_volume(ctxt, instance_uuid,
                                                  volume['id'],
                                                  new_volume['id'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to copy volume %(vol1)s to %(vol2)s"),
                          {'vol1': volume['id'], 'vol2': new_volume['id']})
                self._clean_temporary_volume(ctxt, volume['id'],
                                             new_volume['id'])

    def _get_original_status(self, volume):
        attachments = volume['volume_attachment']
        if not attachments:
            return 'available'
        else:
            return 'in-use'

    def _clean_temporary_volume(self, ctxt, volume_id, new_volume_id,
                                clean_db_only=False):
        volume = self.db.volume_get(ctxt, volume_id)
        # If we're in the migrating phase, we need to cleanup
        # destination volume because source volume is remaining
        if volume['migration_status'] == 'migrating':
            try:
                if clean_db_only:
                    # The temporary volume is not created, only DB data
                    # is created
                    self.db.volume_destroy(ctxt, new_volume_id)
                else:
                    # The temporary volume is already created
                    rpcapi = volume_rpcapi.VolumeAPI()
                    volume = self.db.volume_get(ctxt, new_volume_id)
                    rpcapi.delete_volume(ctxt, volume)
            except exception.VolumeNotFound:
                LOG.info(_LI("Couldn't find the temporary volume "
                             "%(vol)s in the database. There is no need "
                             "to clean up this volume."),
                         {'vol': new_volume_id})
        else:
            # If we're in the completing phase don't delete the
            # destination because we may have already deleted the
            # source! But the migration_status in database should
            # be cleared to handle volume after migration failure
            try:
                updates = {'migration_status': None}
                self.db.volume_update(ctxt, new_volume_id, updates)
            except exception.VolumeNotFound:
                LOG.info(_LI("Couldn't find destination volume "
                             "%(vol)s in the database. The entry might be "
                             "successfully deleted during migration "
                             "completion phase."),
                         {'vol': new_volume_id})

                LOG.warning(_LW("Failed to migrate volume. The destination "
                                "volume %(vol)s is not deleted since the "
                                "source volume may have been deleted."),
                            {'vol': new_volume_id})

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

        LOG.debug("migrate_volume_completion: completing migration for "
                  "volume %(vol1)s (temporary volume %(vol2)s",
                  {'vol1': volume_id, 'vol2': new_volume_id})
        volume = self.db.volume_get(ctxt, volume_id)
        new_volume = self.db.volume_get(ctxt, new_volume_id)
        rpcapi = volume_rpcapi.VolumeAPI()

        orig_volume_status = self._get_original_status(volume)

        if error:
            LOG.info(_LI("migrate_volume_completion is cleaning up an error "
                         "for volume %(vol1)s (temporary volume %(vol2)s"),
                     {'vol1': volume['id'], 'vol2': new_volume['id']})
            rpcapi.delete_volume(ctxt, new_volume)
            updates = {'migration_status': None, 'status': orig_volume_status}
            self.db.volume_update(ctxt, volume_id, updates)
            return volume_id

        self.db.volume_update(ctxt, volume_id,
                              {'migration_status': 'completing'})

        # Delete the source volume (if it fails, don't fail the migration)
        try:
            if orig_volume_status == 'in-use':
                attachments = volume['volume_attachment']
                for attachment in attachments:
                    self.detach_volume(ctxt, volume_id, attachment['id'])
            self.delete_volume(ctxt, volume_id)
        except Exception as ex:
            LOG.error(_LE("Delete migration source volume failed:  %(err)s"),
                      {'err': ex}, resource=volume)

        # Give driver (new_volume) a chance to update things as needed
        # after a successful migration.
        # Note this needs to go through rpc to the host of the new volume
        # the current host and driver object is for the "existing" volume.
        rpcapi.update_migrated_volume(ctxt, volume, new_volume,
                                      orig_volume_status)
        self.db.finish_volume_migration(ctxt, volume_id, new_volume_id)
        self.db.volume_destroy(ctxt, new_volume_id)
        if orig_volume_status == 'in-use':
            updates = {'migration_status': 'completing',
                       'status': orig_volume_status}
        else:
            updates = {'migration_status': None}
        self.db.volume_update(ctxt, volume_id, updates)

        if orig_volume_status == 'in-use':
            attachments = volume['volume_attachment']
            for attachment in attachments:
                rpcapi.attach_volume(ctxt, volume,
                                     attachment['instance_uuid'],
                                     attachment['attached_host'],
                                     attachment['mountpoint'],
                                     'rw')
        LOG.info(_LI("Complete-Migrate volume completed successfully."),
                 resource=volume)
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
                LOG.debug("Issue driver.migrate_volume.", resource=volume_ref)
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
                    self.db.volume_update(ctxt, volume_ref['id'], updates)
        LOG.info(_LI("Migrate volume completed successfully."),
                 resource=volume_ref)

    @periodic_task.periodic_task
    def _report_driver_status(self, context):
        if not self.driver.initialized:
            if self.driver.configuration.config_group is None:
                config_group = ''
            else:
                config_group = ('(config name %s)' %
                                self.driver.configuration.config_group)

            LOG.warning(_LW("Update driver status failed: %(config_group)s "
                            "is uninitialized."),
                        {'config_group': config_group},
                        resource={'type': 'driver',
                                  'id': self.driver.__class__.__name__})
        else:
            volume_stats = self.driver.get_volume_stats(refresh=True)
            if self.extra_capabilities:
                volume_stats.update(self.extra_capabilities)
            if volume_stats:
                # Append volume stats with 'allocated_capacity_gb'
                self._append_volume_stats(volume_stats)

                # Append filter and goodness function if needed
                volume_stats = (
                    self._append_filter_goodness_functions(volume_stats))

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

    def _append_filter_goodness_functions(self, volume_stats):
        """Returns volume_stats updated as needed."""

        # Append filter_function if needed
        if 'filter_function' not in volume_stats:
            volume_stats['filter_function'] = (
                self.driver.get_filter_function())

        # Append goodness_function if needed
        if 'goodness_function' not in volume_stats:
            volume_stats['goodness_function'] = (
                self.driver.get_goodness_function())

        return volume_stats

    def publish_service_capabilities(self, context):
        """Collect driver status and then publish."""
        self._report_driver_status(context)
        self._publish_service_capabilities(context)

    def notification(self, context, event):
        LOG.info(_LI("Notification {%s} received"), event)

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
                                             volumes=None,
                                             extra_usage_info=None):
        vol_utils.notify_about_consistencygroup_usage(
            context, group, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

        if not volumes:
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
                                       snapshots=None,
                                       extra_usage_info=None):
        vol_utils.notify_about_cgsnapshot_usage(
            context, cgsnapshot, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

        if not snapshots:
            snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
                context, cgsnapshot['id'])
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
        project_id = volume['project_id']
        size_increase = (int(new_size)) - volume['size']
        self._notify_about_volume_usage(context, volume, "resize.start")
        try:
            self.driver.extend_volume(volume, new_size)
        except Exception:
            LOG.exception(_LE("Extend volume failed."),
                          resource=volume)
            try:
                self.db.volume_update(context, volume['id'],
                                      {'status': 'error_extending'})
                raise exception.CinderException(_("Volume %s: Error trying "
                                                  "to extend volume") %
                                                volume_id)
            finally:
                QUOTAS.rollback(context, reservations, project_id=project_id)
                return

        QUOTAS.commit(context, reservations, project_id=project_id)
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
        LOG.info(_LI("Extend volume completed successfully."),
                 resource=volume)

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
            self.db.volume_update(context, volume_id, status_update)
            LOG.exception(_LE("Failed to update usages "
                              "while retyping volume."))
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

        # NOTE(jdg): Check to see if the destination host is the same
        # as the current.  If it's not don't call the driver.retype
        # method, otherwise drivers that implement retype may report
        # success, but it's invalid in the case of a migrate.

        # We assume that those that support pools do this internally
        # so we strip off the pools designation
        if (not retyped and
                vol_utils.hosts_are_equivalent(self.driver.host,
                                               host['host'])):
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
                    LOG.info(_LI("Volume %s: retyped successfully"), volume_id)
            except Exception:
                retyped = False
                LOG.exception(_LE("Volume %s: driver error when trying to "
                                  "retype, falling back to generic "
                                  "mechanism."), volume_ref['id'])

        # We could not change the type, so we need to migrate the volume, where
        # the destination volume will be of the new type
        if not retyped:
            if migration_policy == 'never':
                _retype_error(context, volume_id, old_reservations,
                              new_reservations, status_update)
                msg = _("Retype requires migration but is not allowed.")
                raise exception.VolumeMigrationFailed(reason=msg)

            snaps = objects.SnapshotList.get_all_for_volume(context,
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
        LOG.info(_LI("Retype volume completed successfully."),
                 resource=volume_ref)

    def manage_existing(self, ctxt, volume_id, ref=None):
        try:
            flow_engine = manage_existing.get_flow(
                ctxt,
                self.db,
                self.driver,
                self.host,
                volume_id,
                ref)
        except Exception:
            msg = _("Failed to create manage_existing flow.")
            LOG.exception(msg, resource={'type': 'volume', 'id': volume_id})
            raise exception.CinderException(msg)

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

        LOG.info(_LI("Manage existing volume completed successfully."),
                 resource=vol_ref)
        return vol_ref['id']

    def promote_replica(self, ctxt, volume_id):
        """Promote volume replica secondary to be the primary volume."""
        volume = self.db.volume_get(ctxt, volume_id)
        model_update = None

        try:
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Promote volume replica failed."),
                              resource=volume)

        try:
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
        LOG.info(_LI("Promote volume replica completed successfully."),
                 resource=volume)

    def reenable_replication(self, ctxt, volume_id):
        """Re-enable replication of secondary volume with primary volumes."""
        volume = self.db.volume_get(ctxt, volume_id)
        model_update = None

        try:
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Sync volume replica failed."),
                              resource=volume)

        try:
            model_update = self.driver.reenable_replication(ctxt, volume)
        except exception.CinderException:
            err_msg = (_("Synchronizing secondary volume to primary failed."))
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

    def _update_replication_relationship_status(self, ctxt):
        # Only want volumes that do not have a 'disabled' replication status
        filters = {'replication_status': ['active', 'copying', 'error',
                                          'active-stopped', 'inactive']}
        volumes = self.db.volume_get_all_by_host(ctxt, self.host,
                                                 filters=filters)
        for vol in volumes:
            model_update = None
            try:
                model_update = self.driver.get_replication_status(
                    ctxt, vol)
                if model_update:
                    self.db.volume_update(ctxt, vol['id'], model_update)
            except Exception:
                LOG.exception(_LE("Get replication status for volume failed."),
                              resource=vol)

    def create_consistencygroup(self, context, group_id):
        """Creates the consistency group."""
        context = context.elevated()
        group_ref = self.db.consistencygroup_get(context, group_id)

        status = 'available'
        model_update = False

        self._notify_about_consistencygroup_usage(
            context, group_ref, "create.start")

        try:
            utils.require_driver_initialized(self.driver)

            LOG.info(_LI("Consistency group %s: creating"), group_ref['name'])
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
                LOG.error(_LE("Consistency group %s: create failed"),
                          group_ref['name'])

        now = timeutils.utcnow()
        self.db.consistencygroup_update(context,
                                        group_ref['id'],
                                        {'status': status,
                                         'created_at': now})
        LOG.info(_LI("Consistency group %s: created successfully"),
                 group_ref['name'])

        self._notify_about_consistencygroup_usage(
            context, group_ref, "create.end")

        LOG.info(_LI("Create consistency group completed successfully."),
                 resource={'type': 'consistency_group',
                           'id': group_ref['id']})
        return group_ref['id']

    def create_consistencygroup_from_src(self, context, group_id,
                                         cgsnapshot_id=None):
        """Creates the consistency group from source.

        Currently the source can only be a cgsnapshot.
        """
        group_ref = self.db.consistencygroup_get(context, group_id)

        try:
            volumes = self.db.volume_get_all_by_group(
                context, group_id)

            cgsnapshot = None
            snapshots = None
            if cgsnapshot_id:
                try:
                    cgsnapshot = self.db.cgsnapshot_get(context, cgsnapshot_id)
                except exception.CgSnapshotNotFound:
                    LOG.error(_LE("Create consistency group "
                                  "from snapshot-%(snap)s failed: "
                                  "SnapshotNotFound."),
                              {'snap': cgsnapshot_id},
                              resource={'type': 'consistency_group',
                                        'id': group_ref['id']})
                    raise
                if cgsnapshot:
                    snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
                        context, cgsnapshot_id)
                    for snap in snapshots:
                        if (snap.status not in
                                VALID_CREATE_CG_SRC_SNAP_STATUS):
                            msg = (_("Cannot create consistency group "
                                     "%(group)s because snapshot %(snap)s is "
                                     "not in a valid state. Valid states are: "
                                     "%(valid)s.") %
                                   {'group': group_id,
                                    'snap': snap['id'],
                                    'valid': VALID_CREATE_CG_SRC_SNAP_STATUS})
                            raise exception.InvalidConsistencyGroup(reason=msg)

            # Sort source snapshots so that they are in the same order as their
            # corresponding target volumes.
            sorted_snapshots = self._sort_snapshots(volumes, snapshots)
            self._notify_about_consistencygroup_usage(
                context, group_ref, "create.start")

            utils.require_driver_initialized(self.driver)

            model_update, volumes_model_update = (
                self.driver.create_consistencygroup_from_src(
                    context, group_ref, volumes, cgsnapshot,
                    sorted_snapshots))

            if volumes_model_update:
                for update in volumes_model_update:
                    self.db.volume_update(context, update['id'], update)

            if model_update:
                group_ref = self.db.consistencygroup_update(
                    context, group_id, model_update)

        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.consistencygroup_update(
                    context,
                    group_id,
                    {'status': 'error'})
                LOG.error(_LE("Create consistency group "
                              "from snapshot-%(snap)s failed."),
                          {'snap': cgsnapshot_id},
                          resource={'type': 'consistency_group',
                                    'id': group_ref['id']})
                # Update volume status to 'error' as well.
                for vol in volumes:
                    self.db.volume_update(
                        context, vol['id'], {'status': 'error'})

        now = timeutils.utcnow()
        status = 'available'
        for vol in volumes:
            update = {'status': status, 'created_at': now}
            self._update_volume_from_src(context, vol, update,
                                         group_id=group_id)
            self._update_allocated_capacity(vol)

        self.db.consistencygroup_update(context,
                                        group_id,
                                        {'status': status,
                                         'created_at': now})

        self._notify_about_consistencygroup_usage(
            context, group_ref, "create.end")

        LOG.info(_LI("Create consistency group "
                     "from snapshot-%(snap)s completed successfully."),
                 {'snap': cgsnapshot_id},
                 resource={'type': 'consistency_group',
                           'id': group_ref['id']})
        return group_ref['id']

    def _sort_snapshots(self, volumes, snapshots):
        # Sort source snapshots so that they are in the same order as their
        # corresponding target volumes. Each source snapshot in the snapshots
        # list should have a corresponding target volume in the volumes list.
        if not volumes or not snapshots or len(volumes) != len(snapshots):
            msg = _("Input volumes or snapshots are invalid.")
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        sorted_snapshots = []
        for vol in volumes:
            found_snaps = filter(
                lambda snap: snap['id'] == vol['snapshot_id'], snapshots)
            if not found_snaps:
                LOG.error(_LE("Source snapshot cannot be found for target "
                              "volume %(volume_id)s."),
                          {'volume_id': vol['id']})
                raise exception.SnapshotNotFound(
                    snapshot_id=vol['snapshot_id'])
            sorted_snapshots.extend(found_snaps)

        return sorted_snapshots

    def _update_volume_from_src(self, context, vol, update, group_id=None):
        try:
            snapshot = objects.Snapshot.get_by_id(context, vol['snapshot_id'])
            orig_vref = self.db.volume_get(context,
                                           snapshot.volume_id)
            if orig_vref.bootable:
                update['bootable'] = True
                self.db.volume_glance_metadata_copy_to_volume(
                    context, vol['id'], vol['snapshot_id'])
        except exception.SnapshotNotFound:
            LOG.error(_LE("Source snapshot %(snapshot_id)s cannot be found."),
                      {'snapshot_id': vol['snapshot_id']})
            self.db.volume_update(context, vol['id'],
                                  {'status': 'error'})
            if group_id:
                self.db.consistencygroup_update(
                    context, group_id, {'status': 'error'})
            raise
        except exception.VolumeNotFound:
            LOG.error(_LE("The source volume %(volume_id)s "
                          "cannot be found."),
                      {'volume_id': snapshot.volume_id})
            self.db.volume_update(context, vol['id'],
                                  {'status': 'error'})
            if group_id:
                self.db.consistencygroup_update(
                    context, group_id, {'status': 'error'})
            raise
        except exception.CinderException as ex:
            LOG.error(_LE("Failed to update %(volume_id)s"
                          " metadata using the provided snapshot"
                          " %(snapshot_id)s metadata."),
                      {'volume_id': vol['id'],
                       'snapshot_id': vol['snapshot_id']})
            self.db.volume_update(context, vol['id'],
                                  {'status': 'error'})
            if group_id:
                self.db.consistencygroup_update(
                    context, group_id, {'status': 'error'})
            raise exception.MetadataCopyFailure(reason=six.text_type(ex))

        self.db.volume_update(context, vol['id'], update)

    def _update_allocated_capacity(self, vol):
        # Update allocated capacity in volume stats
        pool = vol_utils.extract_host(vol['host'], 'pool')
        if pool is None:
            # Legacy volume, put them into default pool
            pool = self.driver.configuration.safe_get(
                'volume_backend_name') or vol_utils.extract_host(
                    vol['host'], 'pool', True)

        try:
            self.stats['pools'][pool]['allocated_capacity_gb'] += (
                vol['size'])
        except KeyError:
            self.stats['pools'][pool] = dict(
                allocated_capacity_gb=vol['size'])

    def delete_consistencygroup(self, context, group_id):
        """Deletes consistency group and the volumes in the group."""
        context = context.elevated()
        group_ref = self.db.consistencygroup_get(context, group_id)
        project_id = group_ref['project_id']

        if context.project_id != group_ref['project_id']:
            project_id = group_ref['project_id']
        else:
            project_id = context.project_id

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
                    msg = (_('Delete consistency group failed.'))
                    LOG.exception(msg,
                                  resource={'type': 'consistency_group',
                                            'id': group_ref['id']})
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
            LOG.exception(_LE("Delete consistency group "
                              "failed to update usages."),
                          resource={'type': 'consistency_group',
                                    'id': group_id})

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
                LOG.exception(_LE("Delete consistency group "
                                  "failed to update usages."),
                              resource={'type': 'consistency_group',
                                        'id': group_id})

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
        self._notify_about_consistencygroup_usage(
            context, group_ref, "delete.end", volumes)
        self.publish_service_capabilities(context)
        LOG.info(_LI("Delete consistency group "
                     "completed successfully."),
                 resource={'type': 'consistency_group',
                           'id': group_id})

        return True

    def update_consistencygroup(self, context, group_id,
                                add_volumes=None, remove_volumes=None):
        """Updates consistency group.

        Update consistency group by adding volumes to the group,
        or removing volumes from the group.
        """
        group = self.db.consistencygroup_get(context, group_id)

        add_volumes_ref = []
        remove_volumes_ref = []
        add_volumes_list = []
        remove_volumes_list = []
        if add_volumes:
            add_volumes_list = add_volumes.split(',')
        if remove_volumes:
            remove_volumes_list = remove_volumes.split(',')
        for add_vol in add_volumes_list:
            try:
                add_vol_ref = self.db.volume_get(context, add_vol)
            except exception.VolumeNotFound:
                LOG.error(_LE("Update consistency group "
                              "failed to add volume-%(volume_id)s: "
                              "VolumeNotFound."),
                          {'volume_id': add_vol_ref['id']},
                          resource={'type': 'consistency_group',
                                    'id': group_id})
                raise
            if add_vol_ref['status'] not in ['in-use', 'available']:
                msg = (_("Cannot add volume %(volume_id)s to consistency "
                         "group %(group_id)s because volume is in an invalid "
                         "state: %(status)s. Valid states are: %(valid)s.") %
                       {'volume_id': add_vol_ref['id'],
                        'group_id': group_id,
                        'status': add_vol_ref['status'],
                        'valid': VALID_REMOVE_VOL_FROM_CG_STATUS})
                raise exception.InvalidVolume(reason=msg)
            # self.host is 'host@backend'
            # volume_ref['host'] is 'host@backend#pool'
            # Extract host before doing comparison
            new_host = vol_utils.extract_host(add_vol_ref['host'])
            if new_host != self.host:
                raise exception.InvalidVolume(
                    reason=_("Volume is not local to this node."))
            add_volumes_ref.append(add_vol_ref)

        for remove_vol in remove_volumes_list:
            try:
                remove_vol_ref = self.db.volume_get(context, remove_vol)
            except exception.VolumeNotFound:
                LOG.error(_LE("Update consistency group "
                              "failed to remove volume-%(volume_id)s: "
                              "VolumeNotFound."),
                          {'volume_id': remove_vol_ref['id']},
                          resource={'type': 'consistency_group',
                                    'id': group_id})
                raise
            remove_volumes_ref.append(remove_vol_ref)

        self._notify_about_consistencygroup_usage(
            context, group, "update.start")

        try:
            utils.require_driver_initialized(self.driver)

            model_update, add_volumes_update, remove_volumes_update = (
                self.driver.update_consistencygroup(
                    context, group,
                    add_volumes=add_volumes_ref,
                    remove_volumes=remove_volumes_ref))

            if add_volumes_update:
                for update in add_volumes_update:
                    self.db.volume_update(context, update['id'], update)

            if remove_volumes_update:
                for update in remove_volumes_update:
                    self.db.volume_update(context, update['id'], update)

            if model_update:
                if model_update['status'] in ['error']:
                    msg = (_('Error occurred when updating consistency group '
                             '%s.') % group_id)
                    LOG.exception(msg)
                    raise exception.VolumeDriverException(message=msg)
                self.db.consistencygroup_update(context, group_id,
                                                model_update)

        except exception.VolumeDriverException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error occurred in the volume driver when "
                              "updating consistency group %(group_id)s."),
                          {'group_id': group_id})
                self.db.consistencygroup_update(context, group_id,
                                                {'status': 'error'})
                for add_vol in add_volumes_ref:
                    self.db.volume_update(context, add_vol['id'],
                                          {'status': 'error'})
                for rem_vol in remove_volumes_ref:
                    self.db.volume_update(context, rem_vol['id'],
                                          {'status': 'error'})
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error occurred when updating consistency "
                              "group %(group_id)s."),
                          {'group_id': group['id']})
                self.db.consistencygroup_update(context, group_id,
                                                {'status': 'error'})
                for add_vol in add_volumes_ref:
                    self.db.volume_update(context, add_vol['id'],
                                          {'status': 'error'})
                for rem_vol in remove_volumes_ref:
                    self.db.volume_update(context, rem_vol['id'],
                                          {'status': 'error'})

        now = timeutils.utcnow()
        self.db.consistencygroup_update(context, group_id,
                                        {'status': 'available',
                                         'updated_at': now})
        for add_vol in add_volumes_ref:
            self.db.volume_update(context, add_vol['id'],
                                  {'consistencygroup_id': group_id,
                                   'updated_at': now})
        for rem_vol in remove_volumes_ref:
            self.db.volume_update(context, rem_vol['id'],
                                  {'consistencygroup_id': None,
                                   'updated_at': now})

        self._notify_about_consistencygroup_usage(
            context, group, "update.end")
        LOG.info(_LI("Delete consistency group "
                     "completed successfully."),
                 resource={'type': 'consistency_group',
                           'id': group_id})

        return True

    def create_cgsnapshot(self, context, group_id, cgsnapshot_id):
        """Creates the cgsnapshot."""
        caller_context = context
        context = context.elevated()
        cgsnapshot_ref = self.db.cgsnapshot_get(context, cgsnapshot_id)
        LOG.info(_LI("Cgsnapshot %s: creating."), cgsnapshot_ref['id'])

        snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
            context, cgsnapshot_id)

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
                snapshot.context = caller_context

            model_update, snapshots = \
                self.driver.create_cgsnapshot(context, cgsnapshot_ref)

            if snapshots:
                for snapshot in snapshots:
                    # Update db if status is error
                    if snapshot['status'] == 'error':
                        update = {'status': snapshot['status']}

                        # TODO(thangp): Switch over to use snapshot.update()
                        # after cgsnapshot has been switched over to objects
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
                        context, snapshot_id, volume_id)
                except exception.CinderException as ex:
                    LOG.error(_LE("Failed updating %(snapshot_id)s"
                                  " metadata using the provided volumes"
                                  " %(volume_id)s metadata"),
                              {'volume_id': volume_id,
                               'snapshot_id': snapshot_id})

                    # TODO(thangp): Switch over to use snapshot.update()
                    # after cgsnapshot has been switched over to objects
                    self.db.snapshot_update(context,
                                            snapshot_id,
                                            {'status': 'error'})
                    raise exception.MetadataCopyFailure(
                        reason=six.text_type(ex))

            self.db.snapshot_update(context,
                                    snapshot['id'], {'status': 'available',
                                                     'progress': '100%'})

        self.db.cgsnapshot_update(context,
                                  cgsnapshot_ref['id'],
                                  {'status': 'available'})

        LOG.info(_LI("cgsnapshot %s: created successfully"),
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

        LOG.info(_LI("cgsnapshot %s: deleting"), cgsnapshot_ref['id'])

        snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
            context, cgsnapshot_id)

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

                    # TODO(thangp): Switch over to use snapshot.update()
                    # after cgsnapshot has been switched over to objects
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
                LOG.exception(_LE("Failed to update usages deleting snapshot"))

            self.db.volume_glance_metadata_delete_by_snapshot(context,
                                                              snapshot['id'])

            # TODO(thangp): Switch over to use snapshot.destroy()
            # after cgsnapshot has been switched over to objects
            self.db.snapshot_destroy(context, snapshot['id'])

            # Commit the reservations
            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

        self.db.cgsnapshot_destroy(context, cgsnapshot_id)
        LOG.info(_LI("cgsnapshot %s: deleted successfully"),
                 cgsnapshot_ref['id'])
        self._notify_about_cgsnapshot_usage(
            context, cgsnapshot_ref, "delete.end", snapshots)

        return True

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               volume_status):
        """Finalize migration process on backend device."""
        model_update = None
        try:
            model_update = self.driver.update_migrated_volume(ctxt,
                                                              volume,
                                                              new_volume,
                                                              volume_status)
        except NotImplementedError:
            # If update_migrated_volume is not implemented for the driver,
            # _name_id and provider_location will be set with the values
            # from new_volume.
            model_update = {'_name_id': new_volume['_name_id'] or
                            new_volume['id'],
                            'provider_location':
                            new_volume['provider_location']}
        if model_update:
            self.db.volume_update(ctxt.elevated(), volume['id'],
                                  model_update)
