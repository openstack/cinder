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
                 :class:`cinder.volume.drivers.lvm.LVMVolumeDriver`.
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
from oslo_utils import units
from oslo_utils import uuidutils
from osprofiler import profiler
import six
from taskflow import exceptions as tfe

from cinder import compute
from cinder import context
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _, _LE, _LI, _LW
from cinder.image import cache as image_cache
from cinder.image import glance
from cinder import manager
from cinder import objects
from cinder import quota
from cinder import utils
from cinder import volume as cinder_volume
from cinder.volume import configuration as config
from cinder.volume.flows.manager import create_volume
from cinder.volume.flows.manager import manage_existing
from cinder.volume.flows.manager import manage_existing_snapshot
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as vol_utils
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS
CGQUOTAS = quota.CGQUOTAS
VALID_REMOVE_VOL_FROM_CG_STATUS = ('available', 'in-use',)
VALID_CREATE_CG_SRC_SNAP_STATUS = ('available',)
VALID_CREATE_CG_SRC_CG_STATUS = ('available',)

volume_manager_opts = [
    cfg.StrOpt('volume_driver',
               default='cinder.volume.drivers.lvm.LVMVolumeDriver',
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

    RPC_API_VERSION = '1.31'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, volume_driver=None, service_name=None,
                 *args, **kwargs):
        """Load the driver from the one specified in args, or from flags."""
        # update_service_capabilities needs service_name to be volume
        super(VolumeManager, self).__init__(service_name='volume',
                                            *args, **kwargs)
        self.configuration = config.Configuration(volume_manager_opts,
                                                  config_group=service_name)
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

        if self.driver.configuration.safe_get(
                'image_volume_cache_enabled'):

            max_cache_size = self.driver.configuration.safe_get(
                'image_volume_cache_max_size_gb')
            max_cache_entries = self.driver.configuration.safe_get(
                'image_volume_cache_max_count')

            self.image_volume_cache = image_cache.ImageVolumeCache(
                self.db,
                cinder_volume.API(),
                max_cache_size,
                max_cache_entries
            )
            LOG.info(_LI('Image-volume cache enabled for host %(host)s.'),
                     {'host': self.host})
        else:
            LOG.info(_LI('Image-volume cache disabled for host %(host)s.'),
                     {'host': self.host})
            self.image_volume_cache = None

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

    def _sync_provider_info(self, ctxt, volumes, snapshots):
        # NOTE(jdg): For now this just updates provider_id, we can add more
        # add more items to the update if theyr'e releveant but we need
        # to be safe in what we allow and add a list of allowed keys
        # things that make sense are provider_*, replication_status etc

        updates, snapshot_updates = self.driver.update_provider_info(
            volumes, snapshots)
        host_vols = utils.list_of_dicts_to_dict(volumes, 'id')

        for u in updates or []:
            update = {}
            # NOTE(JDG): Make sure returned item is in this hosts volumes
            if host_vols.get(u['id'], None):
                update['provider_id'] = u['provider_id']
            if update:
                self.db.volume_update(ctxt,
                                      u['id'],
                                      update)

        # NOTE(jdg): snapshots are slighty harder, because
        # we do not have a host column and of course no get
        # all by host, so we use a get_all and bounce our
        # response off of it
        if snapshot_updates:
            cinder_snaps = self.db.snapshot_get_all(ctxt)
            for snap in cinder_snaps:
                # NOTE(jdg): For now we only update those that have no entry
                if not snap.get('provider_id', None):
                    update = (
                        [updt for updt in snapshot_updates if updt['id'] ==
                            snap['id']][0])
                    if update:
                        self.db.snapshot_update(
                            ctxt,
                            updt['id'],
                            {'provider_id': updt['provider_id']})

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

        # Initialize backend capabilities list
        self.driver.init_capabilities()

        volumes = self.db.volume_get_all_by_host(ctxt, self.host)
        snapshots = self.db.snapshot_get_by_host(ctxt, self.host)
        self._sync_provider_info(ctxt, volumes, snapshots)
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
                                    "in %(curr_status)s "
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

        # FIXME(jdg): This should go away or be handled differently
        #  if/when we're ready for V2 replication

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
                      filter_properties=None, allow_reschedule=True):

        """Creates the volume."""
        context_elevated = context.elevated()
        if filter_properties is None:
            filter_properties = {}

        if request_spec is None:
            request_spec = {}

        try:
            # NOTE(flaper87): Driver initialization is
            # verified by the task itself.
            flow_engine = create_volume.get_flow(
                context_elevated,
                self,
                self.db,
                self.driver,
                self.scheduler_rpcapi,
                self.host,
                volume_id,
                allow_reschedule,
                context,
                request_spec,
                filter_properties,
                image_volume_cache=self.image_volume_cache,
            )
        except Exception:
            msg = _("Create manager volume flow failed.")
            LOG.exception(msg, resource={'type': 'volume', 'id': volume_id})
            raise exception.CinderException(msg)

        snapshot_id = request_spec.get('snapshot_id')
        source_volid = request_spec.get('source_volid')
        source_replicaid = request_spec.get('source_replicaid')

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
        vol_ref = None

        try:
            if locked_action is None:
                _run_flow()
            else:
                _run_flow_locked()
        finally:
            try:
                vol_ref = flow_engine.storage.fetch('volume_ref')
            except tfe.NotFound:
                # If there's no vol_ref, then flow is reverted. Lets check out
                # if rescheduling occurred.
                try:
                    rescheduled = flow_engine.storage.get_revert_result(
                        create_volume.OnFailureRescheduleTask.make_name(
                            [create_volume.ACTION]))
                except tfe.NotFound:
                    pass

            if not rescheduled:
                if not vol_ref:
                    # Flow was reverted and not rescheduled, fetching
                    # volume_ref from the DB, because it will be needed.
                    vol_ref = self.db.volume_get(context, volume_id)
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

        2. Delete a migration volume
           If deleting the volume in a migration, we want to skip
           quotas but we need database updates for the volume.
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

        # The status 'deleting' is not included, because it only applies to
        # the source volume to be deleted after a migration. No quota
        # needs to be handled for it.
        is_migrating = volume_ref['migration_status'] not in (None, 'error',
                                                              'success')
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
    def delete_snapshot(self, context, snapshot, unmanage_only=False):
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

            if unmanage_only:
                self.driver.unmanage_snapshot(snapshot)
            else:
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

                LOG.debug('Attaching volume %(volume_id)s to instance '
                          '%(instance)s at mountpoint %(mount)s on host '
                          '%(host)s.',
                          {'volume_id': volume_id, 'instance': instance_uuid,
                           'mount': mountpoint, 'host': host_name_sanitized},
                          resource=volume)
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
                LOG.info(_LI("Volume detach called, but volume not attached."),
                         resource=volume)
                # We need to make sure the volume status is set to the correct
                # status.  It could be in detaching status now, and we don't
                # want to leave it there.
                self.db.volume_detached(context, volume_id, attachment_id)
                return
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
                # so set the status to available and move on.
                LOG.info(_LI("Volume detach called, but volume not attached."),
                         resource=volume)
                self.db.volume_update(context, volume_id,
                                      {'status': 'available',
                                       'attach_status': 'detached'})
                return

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

    def _create_image_cache_volume_entry(self, ctx, volume_ref,
                                         image_id, image_meta):
        """Create a new image-volume and cache entry for it.

        This assumes that the image has already been downloaded and stored
        in the volume described by the volume_ref.
        """
        image_volume = None
        try:
            if not self.image_volume_cache.ensure_space(
                    ctx,
                    volume_ref['size'],
                    volume_ref['host']):
                LOG.warning(_LW('Unable to ensure space for image-volume in'
                                ' cache. Will skip creating entry for image'
                                ' %(image)s on host %(host)s.'),
                            {'image': image_id, 'host': volume_ref['host']})
                return

            image_volume = self._clone_image_volume(ctx,
                                                    volume_ref,
                                                    image_meta)
            if not image_volume:
                LOG.warning(_LW('Unable to clone image_volume for image '
                                '%(image_id)s will not create cache entry.'),
                            {'image_id': image_id})
                return

            self.image_volume_cache.create_cache_entry(
                ctx,
                image_volume,
                image_id,
                image_meta
            )
        except exception.CinderException as e:
            LOG.warning(_LW('Failed to create new image-volume cache entry.'
                            ' Error: %(exception)s'), {'exception': e})
            if image_volume:
                self.delete_volume(ctx, image_volume.id)

    def _clone_image_volume(self, ctx, volume, image_meta):
        volume_type_id = volume.get('volume_type_id')
        reserve_opts = {'volumes': 1, 'gigabytes': volume.size}
        QUOTAS.add_volume_type_opts(ctx, reserve_opts, volume_type_id)
        reservations = QUOTAS.reserve(ctx, **reserve_opts)

        try:
            new_vol_values = {}
            for k, v in volume.items():
                new_vol_values[k] = v
            del new_vol_values['id']
            del new_vol_values['_name_id']
            del new_vol_values['volume_type']
            new_vol_values['volume_type_id'] = volume_type_id
            new_vol_values['attach_status'] = 'detached'
            new_vol_values['volume_attachment'] = []
            new_vol_values['status'] = 'creating'
            new_vol_values['project_id'] = ctx.project_id
            new_vol_values['display_name'] = 'image-%s' % image_meta['id']
            new_vol_values['source_volid'] = volume.id
            LOG.debug('Creating image volume entry: %s.', new_vol_values)
            image_volume = self.db.volume_create(ctx, new_vol_values)
        except Exception:
            QUOTAS.rollback(ctx, reservations)
            return False

        QUOTAS.commit(ctx, reservations,
                      project_id=new_vol_values['project_id'])

        try:
            self.create_volume(ctx, image_volume.id,
                               allow_reschedule=False)
            image_volume = self.db.volume_get(ctx, image_volume.id)
            if image_volume.status != 'available':
                raise exception.InvalidVolume(_('Volume is not available.'))

            self.db.volume_admin_metadata_update(ctx.elevated(),
                                                 image_volume.id,
                                                 {'readonly': 'True'},
                                                 False)
            return image_volume
        except exception.CinderException:
            LOG.exception(_LE('Failed to clone volume %(volume_id)s for '
                              'image %(image_id)s.'),
                          {'volume_id': volume.id,
                           'image_id': image_meta['id']})
            try:
                self.delete_volume(ctx, image_volume)
            except exception.CinderException:
                LOG.exception(_LE('Could not delete the image volume %(id)s.'),
                              {'id': volume.id})
            return False

    def _clone_image_volume_and_add_location(self, ctx, volume, image_service,
                                             image_meta):
        """Create a cloned volume and register its location to the image."""
        if (image_meta['disk_format'] != 'raw' or
                image_meta['container_format'] != 'bare'):
            return False

        image_volume_context = ctx
        if self.driver.configuration.image_upload_use_internal_tenant:
            internal_ctx = context.get_internal_tenant_context()
            if internal_ctx:
                image_volume_context = internal_ctx

        image_volume = self._clone_image_volume(image_volume_context,
                                                volume,
                                                image_meta)
        if not image_volume:
            return False

        uri = 'cinder://%s' % image_volume.id
        image_registered = None
        try:
            image_registered = image_service.add_location(
                ctx, image_meta['id'], uri, {})
        except (exception.NotAuthorized, exception.Invalid,
                exception.NotFound):
            LOG.exception(_LE('Failed to register image volume location '
                              '%(uri)s.'), {'uri': uri})

        if not image_registered:
            LOG.warning(_LW('Registration of image volume URI %(uri)s '
                            'to image %(image_id)s failed.'),
                        {'uri': uri, 'image_id': image_meta['id']})
            try:
                self.delete_volume(image_volume_context, image_volume)
            except exception.CinderException:
                LOG.exception(_LE('Could not delete failed image volume '
                                  '%(id)s.'), {'id': image_volume.id})
            return False

        image_volume_meta = {'glance_image_id': image_meta['id'],
                             'image_owner': ctx.project_id}
        self.db.volume_metadata_update(image_volume_context,
                                       image_volume.id,
                                       image_volume_meta,
                                       False)
        return True

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
            if (self.driver.configuration.image_upload_use_cinder_backend
                    and self._clone_image_volume_and_add_location(
                        context, volume, image_service, image_meta)):
                LOG.debug("Registered image volume location to glance "
                          "image-id: %(image_id)s.",
                          {'image_id': image_meta['id']},
                          resource=volume)
            else:
                self.driver.copy_volume_to_image(context, volume,
                                                 image_service, image_meta)
                LOG.debug("Uploaded volume to glance image-id: %(image_id)s.",
                          {'image_id': image_meta['id']},
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
                         "(error: %(err)s).") % {'err': six.text_type(err)})
            LOG.error(err_msg, resource=volume)
            raise exception.VolumeBackendAPIException(data=err_msg)

        try:
            model_update = self.driver.create_export(context.elevated(),
                                                     volume, connector)
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

    def remove_export(self, context, volume_id):
        """Removes an export for a volume."""

        utils.require_driver_initialized(self.driver)
        volume_ref = self.db.volume_get(context, volume_id)
        try:
            self.driver.remove_export(context, volume_ref)
        except Exception:
            msg = _("Remove volume export failed.")
            LOG.exception(msg, resource=volume_ref)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info(_LI("Remove volume export completed successfully."),
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

    def _connect_device(self, conn):
        use_multipath = self.configuration.use_multipath_for_image_xfer
        device_scan_attempts = self.configuration.num_volume_device_scan_tries
        protocol = conn['driver_volume_type']
        connector = utils.brick_get_connector(
            protocol,
            use_multipath=use_multipath,
            device_scan_attempts=device_scan_attempts,
            conn=conn)
        vol_handle = connector.connect_volume(conn['data'])

        root_access = True

        if not connector.check_valid_device(vol_handle['path'], root_access):
            if isinstance(vol_handle['path'], six.string_types):
                raise exception.DeviceUnavailable(
                    path=vol_handle['path'],
                    reason=(_("Unable to access the backend storage via the "
                              "path %(path)s.") %
                            {'path': vol_handle['path']}))
            else:
                raise exception.DeviceUnavailable(
                    path=None,
                    reason=(_("Unable to access the backend storage via file "
                              "handle.")))

        return {'conn': conn, 'device': vol_handle, 'connector': connector}

    def _attach_volume(self, ctxt, volume, properties, remote=False):
        status = volume['status']

        if remote:
            rpcapi = volume_rpcapi.VolumeAPI()
            try:
                conn = rpcapi.initialize_connection(ctxt, volume, properties)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE("Failed to attach volume %(vol)s."),
                              {'vol': volume['id']})
                    self.db.volume_update(ctxt, volume['id'],
                                          {'status': status})
        else:
            conn = self.initialize_connection(ctxt, volume['id'], properties)

        return self._connect_device(conn)

    def _detach_volume(self, ctxt, attach_info, volume, properties,
                       force=False, remote=False):
        connector = attach_info['connector']
        connector.disconnect_volume(attach_info['conn']['data'],
                                    attach_info['device'])

        if remote:
            rpcapi = volume_rpcapi.VolumeAPI()
            rpcapi.terminate_connection(ctxt, volume, properties, force=force)
            rpcapi.remove_export(ctxt, volume)
        else:
            try:
                self.terminate_connection(ctxt, volume['id'], properties,
                                          force=force)
                self.remove_export(ctxt, volume['id'])
            except Exception as err:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Unable to terminate volume connection: '
                                  '%(err)s.') % {'err': err})

    def _copy_volume_data(self, ctxt, src_vol, dest_vol, remote=None):
        """Copy data from src_vol to dest_vol."""

        LOG.debug('copy_data_between_volumes %(src)s -> %(dest)s.',
                  {'src': src_vol['name'], 'dest': dest_vol['name']})

        properties = utils.brick_get_connector_properties()

        dest_remote = remote in ['dest', 'both']
        dest_attach_info = self._attach_volume(ctxt, dest_vol, properties,
                                               remote=dest_remote)

        try:
            src_remote = remote in ['src', 'both']
            src_attach_info = self._attach_volume(ctxt, src_vol, properties,
                                                  remote=src_remote)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to attach source volume for copy."))
                self._detach_volume(ctxt, dest_attach_info, dest_vol,
                                    properties, remote=dest_remote)

        # Check the backend capabilities of migration destination host.
        rpcapi = volume_rpcapi.VolumeAPI()
        capabilities = rpcapi.get_capabilities(ctxt, dest_vol['host'],
                                               False)
        sparse_copy_volume = bool(capabilities and
                                  capabilities.get('sparse_copy_volume',
                                                   False))

        copy_error = True
        try:
            size_in_mb = int(src_vol['size']) * units.Ki    # vol size is in GB
            vol_utils.copy_volume(src_attach_info['device']['path'],
                                  dest_attach_info['device']['path'],
                                  size_in_mb,
                                  self.configuration.volume_dd_blocksize,
                                  sparse=sparse_copy_volume)
            copy_error = False
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to copy volume %(src)s to %(dest)s."),
                          {'src': src_vol['id'], 'dest': dest_vol['id']})
        finally:
            try:
                self._detach_volume(ctxt, dest_attach_info, dest_vol,
                                    properties, force=copy_error,
                                    remote=dest_remote)
            finally:
                self._detach_volume(ctxt, src_attach_info, src_vol,
                                    properties, force=copy_error,
                                    remote=src_remote)

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
                self._copy_volume_data(ctxt, volume, new_volume, remote='dest')
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

        orig_volume_status = volume['previous_status']

        if error:
            LOG.info(_LI("migrate_volume_completion is cleaning up an error "
                         "for volume %(vol1)s (temporary volume %(vol2)s"),
                     {'vol1': volume['id'], 'vol2': new_volume['id']})
            rpcapi.delete_volume(ctxt, new_volume)
            updates = {'migration_status': 'error',
                       'status': orig_volume_status}
            self.db.volume_update(ctxt, volume_id, updates)
            return volume_id

        self.db.volume_update(ctxt, volume_id,
                              {'migration_status': 'completing'})

        # Detach the source volume (if it fails, don't fail the migration)
        try:
            if orig_volume_status == 'in-use':
                attachments = volume['volume_attachment']
                for attachment in attachments:
                    self.detach_volume(ctxt, volume_id, attachment['id'])
        except Exception as ex:
            LOG.error(_LE("Detach migration source volume failed:  %(err)s"),
                      {'err': ex}, resource=volume)

        # Give driver (new_volume) a chance to update things as needed
        # after a successful migration.
        # Note this needs to go through rpc to the host of the new volume
        # the current host and driver object is for the "existing" volume.
        rpcapi.update_migrated_volume(ctxt, volume, new_volume,
                                      orig_volume_status)

        # Swap src and dest DB records so we can continue using the src id and
        # asynchronously delete the destination id
        __, updated_new = self.db.finish_volume_migration(
            ctxt, volume_id, new_volume_id)
        updates = {'status': orig_volume_status,
                   'previous_status': volume['status'],
                   'migration_status': 'success'}

        if orig_volume_status == 'in-use':
            attachments = volume['volume_attachment']
            for attachment in attachments:
                rpcapi.attach_volume(ctxt, volume,
                                     attachment['instance_uuid'],
                                     attachment['attached_host'],
                                     attachment['mountpoint'],
                                     'rw')
        self.db.volume_update(ctxt, volume_id, updates)

        # Asynchronous deletion of the source volume in the back-end (now
        # pointed by the target volume id)
        try:
            rpcapi.delete_volume(ctxt, updated_new)
        except Exception as ex:
            LOG.error(_LE('Failed to request async delete of migration source '
                          'vol %(vol)s: %(err)s'),
                      {'vol': volume_id, 'err': ex})

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
        if volume_ref['status'] in ('retyping', 'maintenance'):
            status_update = {'status': volume_ref['previous_status']}

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
                               'migration_status': 'success',
                               'previous_status': volume_ref['status']}
                    if status_update:
                        updates.update(status_update)
                    if model_update:
                        updates.update(model_update)
                    volume_ref = self.db.volume_update(ctxt,
                                                       volume_ref['id'],
                                                       updates)
            except Exception:
                with excutils.save_and_reraise_exception():
                    updates = {'migration_status': 'error'}
                    if status_update:
                        updates.update(status_update)
                    self.db.volume_update(ctxt, volume_ref['id'], updates)
        if not moved:
            try:
                self._migrate_volume_generic(ctxt, volume_ref, host,
                                             new_type_id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    updates = {'migration_status': 'error'}
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

                if volume_stats.get('replication_enabled', False):
                    # replciation_status provides a concise update of
                    # replicating volumes and any error conditions
                    # detected by the driver.  The intent is we don't
                    # expect/worry about updates so long as nothing
                    # changes, but if something goes wrong this is a
                    # handy mechanism to update the manager and the db
                    # possibly let the admin/user be notified

                    # TODO(jdg): Refactor the check/update pieces to a
                    # helper method we can share
                    # We want to leverage some of the same update model
                    # that we have in the targets update call

                    replication_updates = (
                        self.driver.get_replication_updates(context))
                    for update in replication_updates:
                        pass

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
            volumes = self.db.volume_get_all_by_group(context, group.id)
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
                context, cgsnapshot.id)
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
        status_update = {'status': volume_ref['previous_status']}
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

    def create_consistencygroup(self, context, group):
        """Creates the consistency group."""
        context = context.elevated()

        status = 'available'
        model_update = False

        self._notify_about_consistencygroup_usage(
            context, group, "create.start")

        try:
            utils.require_driver_initialized(self.driver)

            LOG.info(_LI("Consistency group %s: creating"), group.name)
            model_update = self.driver.create_consistencygroup(context,
                                                               group)

            if model_update:
                group.update(model_update)
                group.save()
        except Exception:
            with excutils.save_and_reraise_exception():
                group.status = 'error'
                group.save()
                LOG.error(_LE("Consistency group %s: create failed"),
                          group.name)

        group.status = status
        group.created_at = timeutils.utcnow()
        group.save()
        LOG.info(_LI("Consistency group %s: created successfully"),
                 group.name)

        self._notify_about_consistencygroup_usage(
            context, group, "create.end")

        LOG.info(_LI("Create consistency group completed successfully."),
                 resource={'type': 'consistency_group',
                           'id': group.id})
        return group

    def create_consistencygroup_from_src(self, context, group,
                                         cgsnapshot=None, source_cg=None):
        """Creates the consistency group from source.

        The source can be a CG snapshot or a source CG.
        """
        source_name = None
        snapshots = None
        source_vols = None
        try:
            volumes = self.db.volume_get_all_by_group(context, group.id)

            if cgsnapshot:
                try:
                    # Check if cgsnapshot still exists
                    cgsnapshot = objects.CGSnapshot.get_by_id(
                        context, cgsnapshot.id)
                except exception.CgSnapshotNotFound:
                    LOG.error(_LE("Create consistency group "
                                  "from snapshot-%(snap)s failed: "
                                  "SnapshotNotFound."),
                              {'snap': cgsnapshot.id},
                              resource={'type': 'consistency_group',
                                        'id': group.id})
                    raise

                source_name = _("snapshot-%s") % cgsnapshot.id
                snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
                    context, cgsnapshot.id)
                for snap in snapshots:
                    if (snap.status not in
                            VALID_CREATE_CG_SRC_SNAP_STATUS):
                        msg = (_("Cannot create consistency group "
                                 "%(group)s because snapshot %(snap)s is "
                                 "not in a valid state. Valid states are: "
                                 "%(valid)s.") %
                               {'group': group.id,
                                'snap': snap['id'],
                                'valid': VALID_CREATE_CG_SRC_SNAP_STATUS})
                        raise exception.InvalidConsistencyGroup(reason=msg)

            if source_cg:
                try:
                    source_cg = objects.ConsistencyGroup.get_by_id(
                        context, source_cg.id)
                except exception.ConsistencyGroupNotFound:
                    LOG.error(_LE("Create consistency group "
                                  "from source cg-%(cg)s failed: "
                                  "ConsistencyGroupNotFound."),
                              {'cg': source_cg.id},
                              resource={'type': 'consistency_group',
                                        'id': group.id})
                    raise

                source_name = _("cg-%s") % source_cg.id
                source_vols = self.db.volume_get_all_by_group(
                    context, source_cg.id)
                for source_vol in source_vols:
                    if (source_vol['status'] not in
                            VALID_CREATE_CG_SRC_CG_STATUS):
                        msg = (_("Cannot create consistency group "
                                 "%(group)s because source volume "
                                 "%(source_vol)s is not in a valid "
                                 "state. Valid states are: "
                                 "%(valid)s.") %
                               {'group': group.id,
                                'source_vol': source_vol['id'],
                                'valid': VALID_CREATE_CG_SRC_CG_STATUS})
                        raise exception.InvalidConsistencyGroup(reason=msg)

            # Sort source snapshots so that they are in the same order as their
            # corresponding target volumes.
            sorted_snapshots = None
            if cgsnapshot and snapshots:
                sorted_snapshots = self._sort_snapshots(volumes, snapshots)

            # Sort source volumes so that they are in the same order as their
            # corresponding target volumes.
            sorted_source_vols = None
            if source_cg and source_vols:
                sorted_source_vols = self._sort_source_vols(volumes,
                                                            source_vols)

            self._notify_about_consistencygroup_usage(
                context, group, "create.start")

            utils.require_driver_initialized(self.driver)

            model_update, volumes_model_update = (
                self.driver.create_consistencygroup_from_src(
                    context, group, volumes, cgsnapshot,
                    sorted_snapshots, source_cg, sorted_source_vols))

            if volumes_model_update:
                for update in volumes_model_update:
                    self.db.volume_update(context, update['id'], update)

            if model_update:
                group.update(model_update)
                group.save()

        except Exception:
            with excutils.save_and_reraise_exception():
                group.status = 'error'
                group.save()
                LOG.error(_LE("Create consistency group "
                              "from source %(source)s failed."),
                          {'source': source_name},
                          resource={'type': 'consistency_group',
                                    'id': group.id})
                # Update volume status to 'error' as well.
                for vol in volumes:
                    self.db.volume_update(
                        context, vol['id'], {'status': 'error'})

        now = timeutils.utcnow()
        status = 'available'
        for vol in volumes:
            update = {'status': status, 'created_at': now}
            self._update_volume_from_src(context, vol, update, group=group)
            self._update_allocated_capacity(vol)

        group.status = status
        group.created_at = now
        group.save()

        self._notify_about_consistencygroup_usage(
            context, group, "create.end")
        LOG.info(_LI("Create consistency group "
                     "from source-%(source)s completed successfully."),
                 {'source': source_name},
                 resource={'type': 'consistency_group',
                           'id': group.id})
        return group

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
            found_snaps = [snap for snap in snapshots
                           if snap['id'] == vol['snapshot_id']]
            if not found_snaps:
                LOG.error(_LE("Source snapshot cannot be found for target "
                              "volume %(volume_id)s."),
                          {'volume_id': vol['id']})
                raise exception.SnapshotNotFound(
                    snapshot_id=vol['snapshot_id'])
            sorted_snapshots.extend(found_snaps)

        return sorted_snapshots

    def _sort_source_vols(self, volumes, source_vols):
        # Sort source volumes so that they are in the same order as their
        # corresponding target volumes. Each source volume in the source_vols
        # list should have a corresponding target volume in the volumes list.
        if not volumes or not source_vols or len(volumes) != len(source_vols):
            msg = _("Input volumes or source volumes are invalid.")
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        sorted_source_vols = []
        for vol in volumes:
            found_source_vols = [source_vol for source_vol in source_vols
                                 if source_vol['id'] == vol['source_volid']]
            if not found_source_vols:
                LOG.error(_LE("Source volumes cannot be found for target "
                              "volume %(volume_id)s."),
                          {'volume_id': vol['id']})
                raise exception.VolumeNotFound(
                    volume_id=vol['source_volid'])
            sorted_source_vols.extend(found_source_vols)

        return sorted_source_vols

    def _update_volume_from_src(self, context, vol, update, group=None):
        try:
            snapshot_id = vol.get('snapshot_id')
            if snapshot_id:
                snapshot = objects.Snapshot.get_by_id(context, snapshot_id)
                orig_vref = self.db.volume_get(context,
                                               snapshot.volume_id)
                if orig_vref.bootable:
                    update['bootable'] = True
                    self.db.volume_glance_metadata_copy_to_volume(
                        context, vol['id'], snapshot_id)
        except exception.SnapshotNotFound:
            LOG.error(_LE("Source snapshot %(snapshot_id)s cannot be found."),
                      {'snapshot_id': vol['snapshot_id']})
            self.db.volume_update(context, vol['id'],
                                  {'status': 'error'})
            if group:
                group.status = 'error'
                group.save()
            raise
        except exception.VolumeNotFound:
            LOG.error(_LE("The source volume %(volume_id)s "
                          "cannot be found."),
                      {'volume_id': snapshot.volume_id})
            self.db.volume_update(context, vol['id'],
                                  {'status': 'error'})
            if group:
                group.status = 'error'
                group.save()
            raise
        except exception.CinderException as ex:
            LOG.error(_LE("Failed to update %(volume_id)s"
                          " metadata using the provided snapshot"
                          " %(snapshot_id)s metadata."),
                      {'volume_id': vol['id'],
                       'snapshot_id': vol['snapshot_id']})
            self.db.volume_update(context, vol['id'],
                                  {'status': 'error'})
            if group:
                group.status = 'error'
                group.save()
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

    def delete_consistencygroup(self, context, group):
        """Deletes consistency group and the volumes in the group."""
        context = context.elevated()
        project_id = group.project_id

        if context.project_id != group.project_id:
            project_id = group.project_id
        else:
            project_id = context.project_id

        volumes = self.db.volume_get_all_by_group(context, group.id)

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
            context, group, "delete.start")

        try:
            utils.require_driver_initialized(self.driver)

            model_update, volumes = self.driver.delete_consistencygroup(
                context, group)

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
                    LOG.error(msg,
                              resource={'type': 'consistency_group',
                                        'id': group.id})
                    raise exception.VolumeDriverException(message=msg)
                else:
                    group.update(model_update)
                    group.save()

        except Exception:
            with excutils.save_and_reraise_exception():
                group.status = 'error_deleting'
                group.save()

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
                                    'id': group.id})

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
                                        'id': group.id})

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

        group.destroy()
        self._notify_about_consistencygroup_usage(
            context, group, "delete.end", volumes)
        self.publish_service_capabilities(context)
        LOG.info(_LI("Delete consistency group "
                     "completed successfully."),
                 resource={'type': 'consistency_group',
                           'id': group.id})

        return True

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Updates consistency group.

        Update consistency group by adding volumes to the group,
        or removing volumes from the group.
        """

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
                                    'id': group.id})
                raise
            if add_vol_ref['status'] not in ['in-use', 'available']:
                msg = (_("Cannot add volume %(volume_id)s to consistency "
                         "group %(group_id)s because volume is in an invalid "
                         "state: %(status)s. Valid states are: %(valid)s.") %
                       {'volume_id': add_vol_ref['id'],
                        'group_id': group.id,
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
                                    'id': group.id})
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
                             '%s.') % group.id)
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)
                group.update(model_update)
                group.save()

        except exception.VolumeDriverException:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error occurred in the volume driver when "
                              "updating consistency group %(group_id)s."),
                          {'group_id': group.id})
                group.status = 'error'
                group.save()
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
                          {'group_id': group.id})
                group.status = 'error'
                group.save()
                for add_vol in add_volumes_ref:
                    self.db.volume_update(context, add_vol['id'],
                                          {'status': 'error'})
                for rem_vol in remove_volumes_ref:
                    self.db.volume_update(context, rem_vol['id'],
                                          {'status': 'error'})

        now = timeutils.utcnow()
        group.status = 'available'
        group.update_at = now
        group.save()
        for add_vol in add_volumes_ref:
            self.db.volume_update(context, add_vol['id'],
                                  {'consistencygroup_id': group.id,
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
                           'id': group.id})

        return True

    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates the cgsnapshot."""
        caller_context = context
        context = context.elevated()

        LOG.info(_LI("Cgsnapshot %s: creating."), cgsnapshot.id)

        snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
            context, cgsnapshot.id)

        self._notify_about_cgsnapshot_usage(
            context, cgsnapshot, "create.start")

        try:
            utils.require_driver_initialized(self.driver)

            LOG.debug("Cgsnapshot %(cgsnap_id)s: creating.",
                      {'cgsnap_id': cgsnapshot.id})

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            cgsnapshot.context = caller_context
            for snapshot in snapshots:
                snapshot.context = caller_context

            model_update, snapshots = \
                self.driver.create_cgsnapshot(context, cgsnapshot)

            if snapshots:
                for snapshot in snapshots:
                    # Update db if status is error
                    if snapshot['status'] == 'error':
                        update = {'status': snapshot['status']}

                        # TODO(thangp): Switch over to use snapshot.update()
                        # after cgsnapshot-objects bugs are fixed
                        self.db.snapshot_update(context, snapshot['id'],
                                                update)
                        # If status for one snapshot is error, make sure
                        # the status for the cgsnapshot is also error
                        if model_update['status'] != 'error':
                            model_update['status'] = snapshot['status']

            if model_update:
                if model_update['status'] == 'error':
                    msg = (_('Error occurred when creating cgsnapshot '
                             '%s.') % cgsnapshot.id)
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)

        except Exception:
            with excutils.save_and_reraise_exception():
                cgsnapshot.status = 'error'
                cgsnapshot.save()

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
                    # after cgsnapshot-objects bugs are fixed
                    self.db.snapshot_update(context, snapshot_id,
                                            {'status': 'error'})
                    raise exception.MetadataCopyFailure(
                        reason=six.text_type(ex))

            self.db.snapshot_update(context,
                                    snapshot['id'], {'status': 'available',
                                                     'progress': '100%'})

        cgsnapshot.status = 'available'
        cgsnapshot.save()

        LOG.info(_LI("cgsnapshot %s: created successfully"),
                 cgsnapshot.id)
        self._notify_about_cgsnapshot_usage(
            context, cgsnapshot, "create.end")
        return cgsnapshot

    def delete_cgsnapshot(self, context, cgsnapshot):
        """Deletes cgsnapshot."""
        caller_context = context
        context = context.elevated()
        project_id = cgsnapshot.project_id

        LOG.info(_LI("cgsnapshot %s: deleting"), cgsnapshot.id)

        snapshots = objects.SnapshotList.get_all_for_cgsnapshot(
            context, cgsnapshot.id)

        self._notify_about_cgsnapshot_usage(
            context, cgsnapshot, "delete.start")

        try:
            utils.require_driver_initialized(self.driver)

            LOG.debug("cgsnapshot %(cgsnap_id)s: deleting",
                      {'cgsnap_id': cgsnapshot.id})

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            cgsnapshot.context = caller_context
            for snapshot in snapshots:
                snapshot['context'] = caller_context

            model_update, snapshots = \
                self.driver.delete_cgsnapshot(context, cgsnapshot)

            if snapshots:
                for snapshot in snapshots:
                    update = {'status': snapshot['status']}

                    # TODO(thangp): Switch over to use snapshot.update()
                    # after cgsnapshot-objects bugs are fixed
                    self.db.snapshot_update(context, snapshot['id'],
                                            update)
                    if snapshot['status'] in ['error_deleting', 'error'] and \
                            model_update['status'] not in \
                            ['error_deleting', 'error']:
                        model_update['status'] = snapshot['status']

            if model_update:
                if model_update['status'] in ['error_deleting', 'error']:
                    msg = (_('Error occurred when deleting cgsnapshot '
                             '%s.') % cgsnapshot.id)
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)
                else:
                    cgsnapshot.update(model_update)
                    cgsnapshot.save()

        except Exception:
            with excutils.save_and_reraise_exception():
                cgsnapshot.status = 'error_deleting'
                cgsnapshot.save()

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

            # TODO(thangp): Switch over to use snapshot.delete()
            # after cgsnapshot-objects bugs are fixed
            self.db.snapshot_destroy(context, snapshot['id'])

            # Commit the reservations
            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

        cgsnapshot.destroy()
        LOG.info(_LI("cgsnapshot %s: deleted successfully"), cgsnapshot.id)
        self._notify_about_cgsnapshot_usage(context, cgsnapshot, "delete.end",
                                            snapshots)

        return True

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               volume_status):
        """Finalize migration process on backend device."""
        model_update = None
        # This is temporary fix for bug 1491210.
        volume = self.db.volume_get(ctxt, volume['id'])
        new_volume = self.db.volume_get(ctxt, new_volume['id'])
        model_update_default = {'_name_id': new_volume['_name_id'] or
                                new_volume['id'],
                                'provider_location':
                                new_volume['provider_location']}
        try:
            model_update = self.driver.update_migrated_volume(ctxt,
                                                              volume,
                                                              new_volume,
                                                              volume_status)
        except NotImplementedError:
            # If update_migrated_volume is not implemented for the driver,
            # _name_id and provider_location will be set with the values
            # from new_volume.
            model_update = model_update_default
        if model_update:
            model_update_default.update(model_update)
            # Swap keys that were changed in the source so we keep their values
            # in the temporary volume's DB record.
            # Need to convert 'metadata' and 'admin_metadata' since
            # they are not keys of volume, their corresponding keys are
            # 'volume_metadata' and 'volume_admin_metadata'.
            model_update_new = dict()
            for key in model_update:
                if key == 'metadata':
                    if volume.get('volume_metadata'):
                        model_update_new[key] = {
                            metadata['key']: metadata['value']
                            for metadata in volume.get('volume_metadata')}
                elif key == 'admin_metadata':
                    model_update_new[key] = {
                        metadata['key']: metadata['value']
                        for metadata in volume.get('volume_admin_metadata')}
                else:
                    model_update_new[key] = volume[key]
            self.db.volume_update(ctxt.elevated(), new_volume['id'],
                                  model_update_new)
        self.db.volume_update(ctxt.elevated(), volume['id'],
                              model_update_default)

    # Replication V2 methods
    def enable_replication(self, context, volume):
        """Enable replication on a replication capable volume.

        If the volume was created on a replication_enabled host this method
        is used to enable replication for the volume. Primarily used for
        testing and maintenance.

        :param context: security context
        :param volume: volume object returned by DB
        """
        try:
            # If the driver isn't initialized, we can't talk to the backend
            # so the driver can't enable replication
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Can't enable replication because the "
                              "driver isn't initialized"))

        # NOTE(jdg): We're going to do fresh get from the DB and verify that
        # we are in an expected state ('enabling')
        volume = self.db.volume_get(context, volume['id'])
        if volume['replication_status'] != 'enabling':
            msg = (_("Unable to enable replication due to invalid "
                     "replication status: %(status)s.") %
                   {'status': volume['replication_status']})
            LOG.error(msg, resource=volume)
            raise exception.InvalidVolume(reason=msg)

        try:
            rep_driver_data = self.driver.replication_enable(context,
                                                             volume)
        except exception.CinderException:
            err_msg = (_("Enable replication for volume failed."))
            LOG.exception(err_msg, resource=volume)
            raise exception.VolumeBackendAPIException(data=err_msg)

        try:
            if rep_driver_data:
                volume = self.db.volume_update(context,
                                               volume['id'],
                                               rep_driver_data)
        except exception.CinderException as ex:
            LOG.exception(_LE("Driver replication data update failed."),
                          resource=volume)
            raise exception.VolumeBackendAPIException(reason=ex)
        self.db.volume_update(context, volume['id'],
                              {'replication_status': 'enabled'})

    def disable_replication(self, context, volume):
        """Disable replication on the specified volume.

        If the specified volume is currently replication enabled,
        this method can be used to disable the replication process
        on the backend.  This method assumes that we checked
        replication status in the API layer to ensure we should
        send this call to the driver.

        :param context: security context
        :param volume: volume object returned by DB
        """
        try:
            # If the driver isn't initialized, we can't talk to the backend
            # so the driver can't enable replication
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Can't disable replication because the "
                              "driver isn't initialized"))

        volume = self.db.volume_get(context, volume['id'])
        if volume['replication_status'] != 'disabling':
            msg = (_("Unable to disable replication due to invalid "
                     "replication status: %(status)s.") %
                   {'status': volume['replication_status']})
            LOG.error(msg, resource=volume)
            raise exception.InvalidVolume(reason=msg)

        try:
            rep_driver_data = self.driver.replication_disable(context,
                                                              volume)
        except exception.CinderException:
            err_msg = (_("Disable replication for volume failed."))
            LOG.exception(err_msg, resource=volume)
            raise exception.VolumeBackendAPIException(data=err_msg)
        try:
            if rep_driver_data:
                volume = self.db.volume_update(context,
                                               volume['id'],
                                               rep_driver_data)
        except exception.CinderException as ex:
            LOG.exception(_LE("Driver replication data update failed."),
                          resource=volume)
            raise exception.VolumeBackendAPIException(reason=ex)
        self.db.volume_update(context,
                              volume['id'],
                              {'replication_status': 'disabled'})

    def failover_replication(self, context, volume, secondary=None):
        """Force failover to a secondary replication target.

        Forces the failover action of a replicated volume to one of its
        secondary/target devices.  By default the choice of target devices
        is left up to the driver.  In particular we expect one way
        replication here, but are providing a mechanism for 'n' way
        if supported/configrued.

        Currently we leave it up to the driver to figure out how/what
        to do here.  Rather than doing things like ID swaps, we instead
        just let the driver figure out how/where to route things.

        In cases where we might want to drop a volume-service node and
        the replication target is a configured cinder backend, we'll
        just update the host column for the volume.

        :param context: security context
        :param volume: volume object returned by DB
        :param secondary: Specifies rep target to fail over to
        """
        # NOTE(hemna) We intentionally don't enforce the driver being
        # initialized here.  because the primary might actually be down,
        # but we still want to give the driver a chance of doing some work
        # against the target.  It's entirely up to the driver to deal with
        # not being able to talk to the primary array that it's configured
        # to manage.

        try:
            volume = self.db.volume_get(context, volume['id'])
            model_update = self.driver.replication_failover(context,
                                                            volume,
                                                            secondary)

            # model_updates is a dict containing a report of relevant
            # items based on the backend and how it operates or what it needs.
            # For example:
            # {'host': 'secondary-configured-cinder-backend',
            #  'provider_location: 'foo',
            #  'replication_driver_data': 'driver-specific-stuff-for-db'}
            # Where 'host' is a valid cinder host string like
            #  'foo@bar#baz'

        except exception.CinderException:

            # FIXME(jdg): We need to create a few different exceptions here
            # and handle each differently:
            # 1. I couldn't failover, but the original setup is ok so proceed
            #    as if this were never called
            # 2. I ran into a problem and I have no idea what state things
            #    are in, so set volume to error
            # 3. I ran into a problem and a human needs to come fix me up

            err_msg = (_("Replication failover for volume failed."))
            LOG.exception(err_msg, resource=volume)
            self.db.volume_update(context,
                                  volume['id'],
                                  {'replication_status': 'error'})
            raise exception.VolumeBackendAPIException(data=err_msg)

        if model_update:
            try:
                volume = self.db.volume_update(
                    context,
                    volume['id'],
                    model_update)

            except exception.CinderException as ex:
                LOG.exception(_LE("Driver replication data update failed."),
                              resource=volume)
                raise exception.VolumeBackendAPIException(reason=ex)

        # NOTE(jdg): We're setting replication status to failed-over
        # which indicates the volume is ok, things went as epected but
        # we're likely not replicating any longer because... well we
        # did a fail-over.  In the case of admin brining primary
        # back online he/she can use enable_replication to get this
        # state set back to enabled.

        # Also, in the case of multiple targets, the driver can update
        # status in the rep-status checks if it still has valid replication
        # targets that the volume is being replicated to.

        self.db.volume_update(context,
                              volume['id'],
                              {'replication_status': 'failed-over'})

    def list_replication_targets(self, context, volume):
        """Provide a means to obtain replication targets for a volume.

        This method is used to query a backend to get the current
        replication config info for the specified volume.

        In the case of a volume that isn't being replicated,
        the driver should return an empty list.


        Example response for replicating to a managed backend:
            {'volume_id': volume['id'],
             'targets':[{'remote_device_id': 'vendor-id-for-target-device',
                         'managed_host': 'backend_name'}...]

        Example response for replicating to an unmanaged backend:
            {'volume_id': volume['id'], 'targets':[
                {'remote_device_id': 'vendor-id-for-target-device',
                                      'san_ip': '1.1.1.1',
                                      'san_login': 'admin'},
                                      ....]}

        NOTE: It's the responsibility of the driver to mask out any
        passwords or sensitive information.

        `remote_device_id` is required and is used for drivers to identify
        the devices they have in use.

        """
        # NOTE(hemna) We intentionally don't enforce the driver being
        # initialized here.  because the primary might actually be down,
        # but we still want to give the driver a chance of doing some work
        # against the target.  It's entirely up to the driver to deal with
        # not being able to talk to the primary array that it's configured
        # to manage.

        try:
            volume = self.db.volume_get(context, volume['id'])
            replication_targets = self.driver.list_replication_targets(context,
                                                                       volume)

        except exception.CinderException:
            err_msg = (_("Get replication targets failed."))
            LOG.exception(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        return replication_targets

    def manage_existing_snapshot(self, ctxt, snapshot, ref=None):
        LOG.debug('manage_existing_snapshot: managing %s.', ref)
        try:
            flow_engine = manage_existing_snapshot.get_flow(
                ctxt,
                self.db,
                self.driver,
                self.host,
                snapshot.id,
                ref)
        except Exception:
            msg = _LE("Failed to create manage_existing flow: "
                      "%(object_type)s %(object_id)s.")
            LOG.exception(msg, {'object_type': 'snapshot',
                                'object_id': snapshot.id})
            raise exception.CinderException(
                _("Failed to create manage existing flow."))

        with flow_utils.DynamicLogListener(flow_engine, logger=LOG):
            flow_engine.run()
        return snapshot.id

    def get_capabilities(self, context, discover):
        """Get capabilities of backend storage."""
        if discover:
            self.driver.init_capabilities()
        capabilities = self.driver.capabilities
        LOG.debug("Obtained capabilities list: %s.", capabilities)
        return capabilities
