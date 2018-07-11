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

:volume_manager:  The module name of a class derived from
                  :class:`manager.Manager` (default:
                  :class:`cinder.volume.manager.Manager`).
:volume_driver:  Used by :class:`Manager`.  Defaults to
                 :class:`cinder.volume.drivers.lvm.LVMVolumeDriver`.
:volume_group:  Name of the group that will contain exported volumes (default:
                `cinder-volumes`)
:num_shell_tries:  Number of times to attempt to run commands (default: 3)

"""


import requests
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
profiler = importutils.try_import('osprofiler.profiler')
import six
from taskflow import exceptions as tfe

from cinder.common import constants
from cinder import compute
from cinder import context
from cinder import coordination
from cinder import db
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _
from cinder.image import cache as image_cache
from cinder.image import glance
from cinder.image import image_utils
from cinder import keymgr as key_manager
from cinder import manager
from cinder.message import api as message_api
from cinder.message import message_field
from cinder import objects
from cinder.objects import cgsnapshot
from cinder.objects import consistencygroup
from cinder.objects import fields
from cinder import quota
from cinder import utils
from cinder import volume as cinder_volume
from cinder.volume import configuration as config
from cinder.volume.flows.manager import create_volume
from cinder.volume.flows.manager import manage_existing
from cinder.volume.flows.manager import manage_existing_snapshot
from cinder.volume import group_types
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as vol_utils
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS
CGQUOTAS = quota.CGQUOTAS
GROUP_QUOTAS = quota.GROUP_QUOTAS
VALID_REMOVE_VOL_FROM_CG_STATUS = (
    'available',
    'in-use',
    'error',
    'error_deleting')
VALID_REMOVE_VOL_FROM_GROUP_STATUS = (
    'available',
    'in-use',
    'error',
    'error_deleting')
VALID_ADD_VOL_TO_CG_STATUS = (
    'available',
    'in-use')
VALID_ADD_VOL_TO_GROUP_STATUS = (
    'available',
    'in-use')
VALID_CREATE_CG_SRC_SNAP_STATUS = (fields.SnapshotStatus.AVAILABLE,)
VALID_CREATE_GROUP_SRC_SNAP_STATUS = (fields.SnapshotStatus.AVAILABLE,)
VALID_CREATE_CG_SRC_CG_STATUS = ('available',)
VALID_CREATE_GROUP_SRC_GROUP_STATUS = ('available',)
VA_LIST = objects.VolumeAttachmentList

volume_manager_opts = [
    cfg.IntOpt('migration_create_volume_timeout_secs',
               default=300,
               help='Timeout for creating the volume to migrate to '
                    'when performing volume migration (seconds)'),
    cfg.BoolOpt('volume_service_inithost_offload',
                default=False,
                help='Offload pending volume delete during '
                     'volume service startup'),
    cfg.StrOpt('zoning_mode',
               help="FC Zoning mode configured, only 'fabric' is "
                    "supported now."),
]

volume_backend_opts = [
    cfg.StrOpt('volume_driver',
               default='cinder.volume.drivers.lvm.LVMVolumeDriver',
               help='Driver to use for volume creation'),
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
    cfg.BoolOpt('suppress_requests_ssl_warnings',
                default=False,
                help='Suppress requests library SSL certificate warnings.'),
]

CONF = cfg.CONF
CONF.register_opts(volume_manager_opts)
CONF.register_opts(volume_backend_opts, group=config.SHARED_CONF_GROUP)

MAPPING = {
    'cinder.volume.drivers.hds.nfs.HDSNFSDriver':
    'cinder.volume.drivers.hitachi.hnas_nfs.HNASNFSDriver',
    'cinder.volume.drivers.hitachi.hnas_nfs.HDSNFSDriver':
    'cinder.volume.drivers.hitachi.hnas_nfs.HNASNFSDriver',
    'cinder.volume.drivers.ibm.xiv_ds8k':
    'cinder.volume.drivers.ibm.ibm_storage',
    'cinder.volume.drivers.emc.scaleio':
    'cinder.volume.drivers.dell_emc.scaleio.driver',
    'cinder.volume.drivers.emc.vnx.driver.EMCVNXDriver':
    'cinder.volume.drivers.dell_emc.vnx.driver.VNXDriver',
    'cinder.volume.drivers.emc.xtremio.XtremIOISCSIDriver':
    'cinder.volume.drivers.dell_emc.xtremio.XtremIOISCSIDriver',
    'cinder.volume.drivers.emc.xtremio.XtremIOFibreChannelDriver':
    'cinder.volume.drivers.dell_emc.xtremio.XtremIOFCDriver',
    'cinder.volume.drivers.datera.DateraDriver':
    'cinder.volume.drivers.datera.datera_iscsi.DateraDriver',
    'cinder.volume.drivers.emc.emc_vmax_iscsi.EMCVMAXISCSIDriver':
    'cinder.volume.drivers.dell_emc.vmax.iscsi.VMAXISCSIDriver',
    'cinder.volume.drivers.emc.emc_vmax_fc.EMCVMAXFCDriver':
    'cinder.volume.drivers.dell_emc.vmax.fc.VMAXFCDriver',
    'cinder.volume.drivers.eqlx.DellEQLSanISCSIDriver':
    'cinder.volume.drivers.dell_emc.ps.PSSeriesISCSIDriver',
    'cinder.volume.drivers.dell.dell_storagecenter_iscsi.'
    'DellStorageCenterISCSIDriver':
    'cinder.volume.drivers.dell_emc.sc.storagecenter_iscsi.'
    'SCISCSIDriver',
    'cinder.volume.drivers.dell.dell_storagecenter_fc.'
    'DellStorageCenterFCDriver':
    'cinder.volume.drivers.dell_emc.sc.storagecenter_fc.'
    'SCFCDriver',
}


class VolumeManager(manager.CleanableManager,
                    manager.SchedulerDependentManager):
    """Manages attachable block storage devices."""

    RPC_API_VERSION = volume_rpcapi.VolumeAPI.RPC_API_VERSION

    FAILBACK_SENTINEL = 'default'

    target = messaging.Target(version=RPC_API_VERSION)

    # On cloning a volume, we shouldn't copy volume_type, consistencygroup
    # and volume_attachment, because the db sets that according to [field]_id,
    # which we do copy. We also skip some other values that are set during
    # creation of Volume object.
    _VOLUME_CLONE_SKIP_PROPERTIES = {
        'id', '_name_id', 'name_id', 'name', 'status',
        'attach_status', 'migration_status', 'volume_type',
        'consistencygroup', 'volume_attachment', 'group'}

    def __init__(self, volume_driver=None, service_name=None,
                 *args, **kwargs):
        """Load the driver from the one specified in args, or from flags."""
        # update_service_capabilities needs service_name to be volume
        super(VolumeManager, self).__init__(service_name='volume',
                                            *args, **kwargs)
        # NOTE(dulek): service_name=None means we're running in unit tests.
        service_name = service_name or 'backend_defaults'
        self.configuration = config.Configuration(volume_backend_opts,
                                                  config_group=service_name)
        self.stats = {}

        if not volume_driver:
            # Get from configuration, which will get the default
            # if its not using the multi backend
            volume_driver = self.configuration.volume_driver
        if volume_driver in MAPPING:
            LOG.warning("Driver path %s is deprecated, update your "
                        "configuration to the new path.", volume_driver)
            volume_driver = MAPPING[volume_driver]

        # We pass the current setting for service.active_backend_id to
        # the driver on init, in case there was a restart or something
        curr_active_backend_id = None
        svc_host = vol_utils.extract_host(self.host, 'backend')
        try:
            service = objects.Service.get_by_args(
                context.get_admin_context(),
                svc_host,
                constants.VOLUME_BINARY)
        except exception.ServiceNotFound:
            # NOTE(jdg): This is to solve problems with unit tests
            LOG.info("Service not found for updating "
                     "active_backend_id, assuming default "
                     "for driver init.")
        else:
            curr_active_backend_id = service.active_backend_id

        if self.configuration.suppress_requests_ssl_warnings:
            LOG.warning("Suppressing requests library SSL Warnings")
            requests.packages.urllib3.disable_warnings(
                requests.packages.urllib3.exceptions.InsecureRequestWarning)
            requests.packages.urllib3.disable_warnings(
                requests.packages.urllib3.exceptions.InsecurePlatformWarning)

        self.key_manager = key_manager.API(CONF)
        self.driver = importutils.import_object(
            volume_driver,
            configuration=self.configuration,
            db=self.db,
            host=self.host,
            cluster_name=self.cluster,
            active_backend_id=curr_active_backend_id)

        if self.cluster and not self.driver.SUPPORTS_ACTIVE_ACTIVE:
            msg = _('Active-Active configuration is not currently supported '
                    'by driver %s.') % volume_driver
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        self.message_api = message_api.API()

        if CONF.profiler.enabled and profiler is not None:
            self.driver = profiler.trace_cls("driver")(self.driver)
        try:
            self.extra_capabilities = jsonutils.loads(
                self.driver.configuration.extra_capabilities)
        except AttributeError:
            self.extra_capabilities = {}
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Invalid JSON: %s",
                          self.driver.configuration.extra_capabilities)

        # Check if a per-backend AZ has been specified
        backend_zone = self.driver.configuration.safe_get(
            'backend_availability_zone')
        if backend_zone:
            self.availability_zone = backend_zone

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
            LOG.info('Image-volume cache enabled for host %(host)s.',
                     {'host': self.host})
        else:
            LOG.info('Image-volume cache disabled for host %(host)s.',
                     {'host': self.host})
            self.image_volume_cache = None

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
                LOG.exception('Fetch volume pool name failed.',
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

    def _sync_provider_info(self, ctxt, volumes, snapshots):
        # NOTE(jdg): For now this just updates provider_id, we can add more
        # items to the update if they're relevant but we need to be safe in
        # what we allow and add a list of allowed keys.  Things that make sense
        # are provider_*, replication_status etc

        updates, snapshot_updates = self.driver.update_provider_info(
            volumes, snapshots)

        if updates:
            for volume in volumes:
                # NOTE(JDG): Make sure returned item is in this hosts volumes
                update = (
                    [updt for updt in updates if updt['id'] ==
                        volume['id']])
                if update:
                    update = update[0]
                    self.db.volume_update(
                        ctxt,
                        update['id'],
                        {'provider_id': update['provider_id']})

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
                            update['id'],
                            {'provider_id': update['provider_id']})

    def _include_resources_in_cluster(self, ctxt):

        LOG.info('Including all resources from host %(host)s in cluster '
                 '%(cluster)s.',
                 {'host': self.host, 'cluster': self.cluster})
        num_vols = objects.VolumeList.include_in_cluster(
            ctxt, self.cluster, host=self.host)
        num_cgs = objects.ConsistencyGroupList.include_in_cluster(
            ctxt, self.cluster, host=self.host)
        num_gs = objects.GroupList.include_in_cluster(
            ctxt, self.cluster, host=self.host)
        num_cache = db.image_volume_cache_include_in_cluster(
            ctxt, self.cluster, host=self.host)
        LOG.info('%(num_vols)s volumes, %(num_cgs)s consistency groups, '
                 '%(num_gs)s generic groups and %(num_cache)s image '
                 'volume caches from host %(host)s have been included in '
                 'cluster %(cluster)s.',
                 {'num_vols': num_vols, 'num_cgs': num_cgs, 'num_gs': num_gs,
                  'host': self.host, 'cluster': self.cluster,
                  'num_cache': num_cache})

    def init_host(self, added_to_cluster=None, **kwargs):
        """Perform any required initialization."""
        ctxt = context.get_admin_context()
        if not self.driver.supported:
            utils.log_unsupported_driver_warning(self.driver)

            if not self.configuration.enable_unsupported_driver:
                LOG.error("Unsupported drivers are disabled."
                          " You can re-enable by adding "
                          "enable_unsupported_driver=True to the "
                          "driver section in cinder.conf",
                          resource={'type': 'driver',
                                    'id': self.__class__.__name__})
                return

        # If we have just added this host to a cluster we have to include all
        # our resources in that cluster.
        if added_to_cluster:
            self._include_resources_in_cluster(ctxt)

        LOG.info("Starting volume driver %(driver_name)s (%(version)s)",
                 {'driver_name': self.driver.__class__.__name__,
                  'version': self.driver.get_version()})
        try:
            self.driver.do_setup(ctxt)
            self.driver.check_for_setup_error()
        except Exception:
            LOG.exception("Failed to initialize driver.",
                          resource={'type': 'driver',
                                    'id': self.__class__.__name__})
            # we don't want to continue since we failed
            # to initialize the driver correctly.
            return

        # Initialize backend capabilities list
        self.driver.init_capabilities()

        volumes = self._get_my_volumes(ctxt)
        snapshots = self._get_my_snapshots(ctxt)
        self._sync_provider_info(ctxt, volumes, snapshots)
        # FIXME volume count for exporting is wrong

        self.stats['pools'] = {}
        self.stats.update({'allocated_capacity_gb': 0})

        try:
            for volume in volumes:
                # available volume should also be counted into allocated
                if volume['status'] in ['in-use', 'available']:
                    # calculate allocated capacity for driver
                    self._count_allocated_capacity(ctxt, volume)

                    try:
                        if volume['status'] in ['in-use']:
                            self.driver.ensure_export(ctxt, volume)
                    except Exception:
                        LOG.exception("Failed to re-export volume, "
                                      "setting to ERROR.",
                                      resource=volume)
                        volume.conditional_update({'status': 'error'},
                                                  {'status': 'in-use'})
            # All other cleanups are processed by parent class CleanableManager

        except Exception:
            LOG.exception("Error during re-export on driver init.",
                          resource=volume)
            return

        self.driver.set_throttle()

        # at this point the driver is considered initialized.
        # NOTE(jdg): Careful though because that doesn't mean
        # that an entry exists in the service table
        self.driver.set_initialized()

        # Keep the image tmp file clean when init host.
        backend_name = vol_utils.extract_host(self.service_topic_queue)
        image_utils.cleanup_temporary_file(backend_name)

        # collect and publish service capabilities
        self.publish_service_capabilities(ctxt)
        LOG.info("Driver initialization completed successfully.",
                 resource={'type': 'driver',
                           'id': self.driver.__class__.__name__})

        # Make sure to call CleanableManager to do the cleanup
        super(VolumeManager, self).init_host(added_to_cluster=added_to_cluster,
                                             **kwargs)

    def init_host_with_rpc(self):
        LOG.info("Initializing RPC dependent components of volume "
                 "driver %(driver_name)s (%(version)s)",
                 {'driver_name': self.driver.__class__.__name__,
                  'version': self.driver.get_version()})

        try:
            # Make sure the driver is initialized first
            utils.log_unsupported_driver_warning(self.driver)
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            LOG.error("Cannot complete RPC initialization because "
                      "driver isn't initialized properly.",
                      resource={'type': 'driver',
                                'id': self.driver.__class__.__name__})
            return

        stats = self.driver.get_volume_stats(refresh=True)
        svc_host = vol_utils.extract_host(self.host, 'backend')
        try:
            service = objects.Service.get_by_args(
                context.get_admin_context(),
                svc_host,
                constants.VOLUME_BINARY)
        except exception.ServiceNotFound:
            with excutils.save_and_reraise_exception():
                LOG.error("Service not found for updating replication_status.")

        if service.replication_status != (
                fields.ReplicationStatus.FAILED_OVER):
            if stats and stats.get('replication_enabled', False):
                service.replication_status = fields.ReplicationStatus.ENABLED
            else:
                service.replication_status = fields.ReplicationStatus.DISABLED

        service.save()
        LOG.info("Driver post RPC initialization completed successfully.",
                 resource={'type': 'driver',
                           'id': self.driver.__class__.__name__})

    def _do_cleanup(self, ctxt, vo_resource):
        if isinstance(vo_resource, objects.Volume):
            if vo_resource.status == 'downloading':
                self.driver.clear_download(ctxt, vo_resource)

            elif vo_resource.status == 'uploading':
                # Set volume status to available or in-use.
                self.db.volume_update_status_based_on_attachment(
                    ctxt, vo_resource.id)

            elif vo_resource.status == 'deleting':
                if CONF.volume_service_inithost_offload:
                    # Offload all the pending volume delete operations to the
                    # threadpool to prevent the main volume service thread
                    # from being blocked.
                    self._add_to_threadpool(self.delete_volume, ctxt,
                                            vo_resource, cascade=True)
                else:
                    # By default, delete volumes sequentially
                    self.delete_volume(ctxt, vo_resource, cascade=True)
                # We signal that we take care of cleaning the worker ourselves
                # (with set_workers decorator in delete_volume method) so
                # do_cleanup method doesn't need to remove it.
                return True

        # For Volume creating and downloading and for Snapshot downloading
        # statuses we have to set status to error
        if vo_resource.status in ('creating', 'downloading'):
            vo_resource.status = 'error'
            vo_resource.save()

    def is_working(self):
        """Return if Manager is ready to accept requests.

        This is to inform Service class that in case of volume driver
        initialization failure the manager is actually down and not ready to
        accept any requests.
        """
        return self.driver.initialized

    def _set_resource_host(self, resource):
        """Set the host field on the DB to our own when we are clustered."""
        if (resource.is_clustered and
                not vol_utils.hosts_are_equivalent(resource.host, self.host)):
            pool = vol_utils.extract_host(resource.host, 'pool')
            resource.host = vol_utils.append_host(self.host, pool)
            resource.save()

    @objects.Volume.set_workers
    def create_volume(self, context, volume, request_spec=None,
                      filter_properties=None, allow_reschedule=True):
        """Creates the volume."""
        # Log about unsupported drivers
        utils.log_unsupported_driver_warning(self.driver)

        # Make sure the host in the DB matches our own when clustered
        self._set_resource_host(volume)

        context_elevated = context.elevated()
        if filter_properties is None:
            filter_properties = {}

        if request_spec is None:
            request_spec = objects.RequestSpec()

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
                volume,
                allow_reschedule,
                context,
                request_spec,
                filter_properties,
                image_volume_cache=self.image_volume_cache,
            )
        except Exception:
            msg = _("Create manager volume flow failed.")
            LOG.exception(msg, resource={'type': 'volume', 'id': volume.id})
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

        # NOTE(dulek): Flag to indicate if volume was rescheduled. Used to
        # decide if allocated_capacity should be incremented.
        rescheduled = False

        try:
            if locked_action is None:
                _run_flow()
            else:
                with coordination.COORDINATOR.get_lock(locked_action):
                    _run_flow()
        finally:
            try:
                flow_engine.storage.fetch('refreshed')
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
                # NOTE(dulek): Volume wasn't rescheduled so we need to update
                # volume stats as these are decremented on delete.
                self._update_allocated_capacity(volume)

        LOG.info("Created volume successfully.", resource=volume)
        return volume.id

    def _check_is_our_resource(self, resource):
        if resource.host:
            res_backend = vol_utils.extract_host(resource.service_topic_queue)
            backend = vol_utils.extract_host(self.service_topic_queue)
            if res_backend != backend:
                msg = (_('Invalid %(resource)s: %(resource)s %(id)s is not '
                         'local to %(backend)s.') %
                       {'resource': resource.obj_name, 'id': resource.id,
                        'backend': backend})
                raise exception.Invalid(msg)

    @coordination.synchronized('{volume.id}-{f_name}')
    @objects.Volume.set_workers
    def delete_volume(self, context, volume, unmanage_only=False,
                      cascade=False):
        """Deletes and unexports volume.

        1. Delete a volume(normal case)
           Delete a volume and update quotas.

        2. Delete a migration volume
           If deleting the volume in a migration, we want to skip
           quotas but we need database updates for the volume.

        3. Delete a temp volume for backup
           If deleting the temp volume for backup, we want to skip
           quotas but we need database updates for the volume.
      """

        context = context.elevated()

        try:
            volume.refresh()
        except exception.VolumeNotFound:
            # NOTE(thingee): It could be possible for a volume to
            # be deleted when resuming deletes from init_host().
            LOG.debug("Attempted delete of non-existent volume: %s", volume.id)
            return

        if context.project_id != volume.project_id:
            project_id = volume.project_id
        else:
            project_id = context.project_id

        if volume['attach_status'] == fields.VolumeAttachStatus.ATTACHED:
            # Volume is still attached, need to detach first
            raise exception.VolumeAttached(volume_id=volume.id)
        self._check_is_our_resource(volume)

        if unmanage_only and volume.encryption_key_id is not None:
            raise exception.Invalid(
                reason=_("Unmanaging encrypted volumes is not "
                         "supported."))

        if unmanage_only and cascade:
            # This could be done, but is ruled out for now just
            # for simplicity.
            raise exception.Invalid(
                reason=_("Unmanage and cascade delete options "
                         "are mutually exclusive."))

        # To backup a snapshot or a 'in-use' volume, create a temp volume
        # from the snapshot or in-use volume, and back it up.
        # Get admin_metadata (needs admin context) to detect temporary volume.
        is_temp_vol = False
        with volume.obj_as_admin():
            if volume.admin_metadata.get('temporary', 'False') == 'True':
                is_temp_vol = True
                LOG.info("Trying to delete temp volume: %s", volume.id)

        # The status 'deleting' is not included, because it only applies to
        # the source volume to be deleted after a migration. No quota
        # needs to be handled for it.
        is_migrating = volume.migration_status not in (None, 'error',
                                                       'success')
        is_migrating_dest = (is_migrating and
                             volume.migration_status.startswith(
                                 'target:'))
        notification = "delete.start"
        if unmanage_only:
            notification = "unmanage.start"
        if not is_temp_vol:
            self._notify_about_volume_usage(context, volume, notification)
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)

            self.driver.remove_export(context, volume)
            if unmanage_only:
                self.driver.unmanage(volume)
            elif cascade:
                LOG.debug('Performing cascade delete.')
                snapshots = objects.SnapshotList.get_all_for_volume(context,
                                                                    volume.id)
                for s in snapshots:
                    if s.status != fields.SnapshotStatus.DELETING:
                        self._clear_db(context, is_migrating_dest, volume,
                                       'error_deleting')

                        msg = (_("Snapshot %(id)s was found in state "
                                 "%(state)s rather than 'deleting' during "
                                 "cascade delete.") % {'id': s.id,
                                                       'state': s.status})
                        raise exception.InvalidSnapshot(reason=msg)

                    self.delete_snapshot(context, s)

                LOG.debug('Snapshots deleted, issuing volume delete')
                self.driver.delete_volume(volume)
            else:
                self.driver.delete_volume(volume)
        except exception.VolumeIsBusy:
            LOG.error("Unable to delete busy volume.",
                      resource=volume)
            # If this is a destination volume, we have to clear the database
            # record to avoid user confusion.
            self._clear_db(context, is_migrating_dest, volume,
                           'available')
            return
        except Exception:
            with excutils.save_and_reraise_exception():
                # If this is a destination volume, we have to clear the
                # database record to avoid user confusion.
                new_status = 'error_deleting'
                if unmanage_only is True:
                    new_status = 'error_unmanaging'

                self._clear_db(context, is_migrating_dest, volume,
                               new_status)

        # If deleting source/destination volume in a migration or a temp
        # volume for backup, we should skip quotas.
        skip_quota = is_migrating or is_temp_vol
        if not skip_quota:
            # Get reservations
            try:
                reservations = None
                if volume.status != 'error_managing_deleting':
                    reserve_opts = {'volumes': -1,
                                    'gigabytes': -volume.size}
                    QUOTAS.add_volume_type_opts(context,
                                                reserve_opts,
                                                volume.volume_type_id)
                    reservations = QUOTAS.reserve(context,
                                                  project_id=project_id,
                                                  **reserve_opts)
            except Exception:
                LOG.exception("Failed to update usages deleting volume.",
                              resource=volume)

        # Delete glance metadata if it exists
        self.db.volume_glance_metadata_delete_by_volume(context, volume.id)

        volume.destroy()

        # If deleting source/destination volume in a migration or a temp
        # volume for backup, we should skip quotas.
        if not skip_quota:
            notification = "delete.end"
            if unmanage_only:
                notification = "unmanage.end"
            self._notify_about_volume_usage(context, volume, notification)

            # Commit the reservations
            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

            pool = vol_utils.extract_host(volume.host, 'pool')
            if pool is None:
                # Legacy volume, put them into default pool
                pool = self.driver.configuration.safe_get(
                    'volume_backend_name') or vol_utils.extract_host(
                        volume.host, 'pool', True)
            size = volume.size

            try:
                self.stats['pools'][pool]['allocated_capacity_gb'] -= size
            except KeyError:
                self.stats['pools'][pool] = dict(
                    allocated_capacity_gb=-size)

            self.publish_service_capabilities(context)

        msg = "Deleted volume successfully."
        if unmanage_only:
            msg = "Unmanaged volume successfully."
        LOG.info(msg, resource=volume)

    def _clear_db(self, context, is_migrating_dest, volume_ref, status):
        # This method is called when driver.unmanage() or
        # driver.delete_volume() fails in delete_volume(), so it is already
        # in the exception handling part.
        if is_migrating_dest:
            volume_ref.destroy()
            LOG.error("Unable to delete the destination volume "
                      "during volume migration, (NOTE: database "
                      "record needs to be deleted).", resource=volume_ref)
        else:
            volume_ref.status = status
            volume_ref.save()

    def _revert_to_snapshot_generic(self, ctxt, volume, snapshot):
        """Generic way to revert volume to a snapshot.

        the framework will use the generic way to implement the revert
        to snapshot feature:
        1. create a temporary volume from snapshot
        2. mount two volumes to host
        3. copy data from temporary volume to original volume
        4. detach and destroy temporary volume
        """
        temp_vol = None

        try:
            v_options = {'display_name': '[revert] temporary volume created '
                                         'from snapshot %s' % snapshot.id}
            ctxt = context.get_internal_tenant_context() or ctxt
            temp_vol = self.driver._create_temp_volume_from_snapshot(
                ctxt, volume, snapshot, volume_options=v_options)
            self._copy_volume_data(ctxt, temp_vol, volume)
            self.driver.delete_volume(temp_vol)
            temp_vol.destroy()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(
                    "Failed to use snapshot %(snapshot)s to create "
                    "a temporary volume and copy data to volume "
                    " %(volume)s.",
                    {'snapshot': snapshot.id,
                     'volume': volume.id})
                if temp_vol and temp_vol.status == 'available':
                    self.driver.delete_volume(temp_vol)
                    temp_vol.destroy()

    def _revert_to_snapshot(self, context, volume, snapshot):
        """Use driver or generic method to rollback volume."""

        self._notify_about_volume_usage(context, volume, "revert.start")
        self._notify_about_snapshot_usage(context, snapshot, "revert.start")
        try:
            self.driver.revert_to_snapshot(context, volume, snapshot)
        except (NotImplementedError, AttributeError):
            LOG.info("Driver's 'revert_to_snapshot' is not found. "
                     "Try to use copy-snapshot-to-volume method.")
            self._revert_to_snapshot_generic(context, volume, snapshot)
        self._notify_about_volume_usage(context, volume, "revert.end")
        self._notify_about_snapshot_usage(context, snapshot, "revert.end")

    def _create_backup_snapshot(self, context, volume):
        kwargs = {
            'volume_id': volume.id,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': fields.SnapshotStatus.CREATING,
            'progress': '0%',
            'volume_size': volume.size,
            'display_name': '[revert] volume %s backup snapshot' % volume.id,
            'display_description': 'This is only used for backup when '
                                   'reverting. If the reverting process '
                                   'failed, you can restore you data by '
                                   'creating new volume with this snapshot.',
            'volume_type_id': volume.volume_type_id,
            'encryption_key_id': volume.encryption_key_id,
            'metadata': {}
        }
        snapshot = objects.Snapshot(context=context, **kwargs)
        snapshot.create()
        self.create_snapshot(context, snapshot)
        return snapshot

    def revert_to_snapshot(self, context, volume, snapshot):
        """Revert a volume to a snapshot.

        The process of reverting to snapshot consists of several steps:
        1.   create a snapshot for backup (in case of data loss)
        2.1. use driver's specific logic to revert volume
        2.2. try the generic way to revert volume if driver's method is missing
        3.   delete the backup snapshot
        """
        backup_snapshot = None
        try:
            LOG.info("Start to perform revert to snapshot process.")
            # Create a snapshot which can be used to restore the volume
            # data by hand if revert process failed.
            backup_snapshot = self._create_backup_snapshot(context, volume)
            self._revert_to_snapshot(context, volume, snapshot)
        except Exception as error:
            with excutils.save_and_reraise_exception():
                self._notify_about_volume_usage(context, volume,
                                                "revert.end")
                self._notify_about_snapshot_usage(context, snapshot,
                                                  "revert.end")
                msg = ('Volume %(v_id)s revert to '
                       'snapshot %(s_id)s failed with %(error)s.')
                msg_args = {'v_id': volume.id,
                            's_id': snapshot.id,
                            'error': six.text_type(error)}
                v_res = volume.update_single_status_where(
                    'error',
                    'reverting')
                if not v_res:
                    msg_args = {"id": volume.id,
                                "status": 'error'}
                    msg += ("Failed to reset volume %(id)s "
                            "status to %(status)s.") % msg_args

                s_res = snapshot.update_single_status_where(
                    fields.SnapshotStatus.AVAILABLE,
                    fields.SnapshotStatus.RESTORING)
                if not s_res:
                    msg_args = {"id": snapshot.id,
                                "status":
                                    fields.SnapshotStatus.ERROR}
                    msg += ("Failed to reset snapshot %(id)s "
                            "status to %(status)s." % msg_args)
                LOG.exception(msg, msg_args)

        v_res = volume.update_single_status_where(
            'available', 'reverting')
        if not v_res:
            msg_args = {"id": volume.id,
                        "status": 'available'}
            msg = _("Revert finished, but failed to reset "
                    "volume %(id)s status to %(status)s, "
                    "please manually reset it.") % msg_args
            raise exception.BadResetResourceStatus(message=msg)

        s_res = snapshot.update_single_status_where(
            fields.SnapshotStatus.AVAILABLE,
            fields.SnapshotStatus.RESTORING)
        if not s_res:
            msg_args = {"id": snapshot.id,
                        "status":
                            fields.SnapshotStatus.AVAILABLE}
            msg = _("Revert finished, but failed to reset "
                    "snapshot %(id)s status to %(status)s, "
                    "please manually reset it.") % msg_args
            raise exception.BadResetResourceStatus(message=msg)
        if backup_snapshot:
            self.delete_snapshot(context,
                                 backup_snapshot, handle_quota=False)
        msg = ('Volume %(v_id)s reverted to snapshot %(snap_id)s '
               'successfully.')
        msg_args = {'v_id': volume.id, 'snap_id': snapshot.id}
        LOG.info(msg, msg_args)

    @objects.Snapshot.set_workers
    def create_snapshot(self, context, snapshot):
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
                snapshot.status = fields.SnapshotStatus.ERROR
                snapshot.save()

        vol_ref = self.db.volume_get(context, snapshot.volume_id)
        if vol_ref.bootable:
            try:
                self.db.volume_glance_metadata_copy_to_snapshot(
                    context, snapshot.id, snapshot.volume_id)
            except exception.GlanceMetadataNotFound:
                # If volume is not created from image, No glance metadata
                # would be available for that volume in
                # volume glance metadata table
                pass
            except exception.CinderException as ex:
                LOG.exception("Failed updating snapshot"
                              " metadata using the provided volumes"
                              " %(volume_id)s metadata",
                              {'volume_id': snapshot.volume_id},
                              resource=snapshot)
                snapshot.status = fields.SnapshotStatus.ERROR
                snapshot.save()
                raise exception.MetadataCopyFailure(reason=six.text_type(ex))

        snapshot.status = fields.SnapshotStatus.AVAILABLE
        snapshot.progress = '100%'
        snapshot.save()

        self._notify_about_snapshot_usage(context, snapshot, "create.end")
        LOG.info("Create snapshot completed successfully",
                 resource=snapshot)
        return snapshot.id

    @coordination.synchronized('{snapshot.id}-{f_name}')
    def delete_snapshot(self, context, snapshot,
                        unmanage_only=False, handle_quota=True):
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
            LOG.error("Delete snapshot failed, due to snapshot busy.",
                      resource=snapshot)
            snapshot.status = fields.SnapshotStatus.AVAILABLE
            snapshot.save()
            return
        except Exception:
            with excutils.save_and_reraise_exception():
                snapshot.status = fields.SnapshotStatus.ERROR_DELETING
                snapshot.save()

        # Get reservations
        reservations = None
        try:
            if handle_quota:
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
            LOG.exception("Update snapshot usages failed.",
                          resource=snapshot)
        self.db.volume_glance_metadata_delete_by_snapshot(context, snapshot.id)
        snapshot.destroy()
        self._notify_about_snapshot_usage(context, snapshot, "delete.end")

        # Commit the reservations
        if reservations:
            QUOTAS.commit(context, reservations, project_id=project_id)

        msg = "Delete snapshot completed successfully."
        if unmanage_only:
            msg = "Unmanage snapshot completed successfully."
        LOG.info(msg, resource=snapshot)

    @coordination.synchronized('{volume_id}')
    def attach_volume(self, context, volume_id, instance_uuid, host_name,
                      mountpoint, mode, volume=None):
        """Updates db to show volume is attached."""
        # FIXME(lixiaoy1): Remove this in v4.0 of RPC API.
        if volume is None:
            # For older clients, mimic the old behavior and look
            # up the volume by its volume_id.
            volume = objects.Volume.get_by_id(context, volume_id)
        # Get admin_metadata. This needs admin context.
        with volume.obj_as_admin():
            volume_metadata = volume.admin_metadata
        # check the volume status before attaching
        if volume.status == 'attaching':
            if (volume_metadata.get('attached_mode') and
               volume_metadata.get('attached_mode') != mode):
                raise exception.InvalidVolume(
                    reason=_("being attached by different mode"))

        host_name_sanitized = utils.sanitize_hostname(
            host_name) if host_name else None
        if instance_uuid:
            attachments = (
                VA_LIST.get_all_by_instance_uuid(
                    context, instance_uuid))
        else:
            attachments = (
                VA_LIST.get_all_by_host(
                    context, host_name_sanitized))
        if attachments:
            # check if volume<->instance mapping is already tracked in DB
            for attachment in attachments:
                if attachment['volume_id'] == volume_id:
                    volume.status = 'in-use'
                    volume.save()
                    return attachment

        if (volume.status == 'in-use' and not volume.multiattach
           and not volume.migration_status):
            raise exception.InvalidVolume(
                reason=_("volume is already attached"))

        self._notify_about_volume_usage(context, volume,
                                        "attach.start")

        attachment = volume.begin_attach(mode)

        if instance_uuid and not uuidutils.is_uuid_like(instance_uuid):
            attachment.attach_status = (
                fields.VolumeAttachStatus.ERROR_ATTACHING)
            attachment.save()
            raise exception.InvalidUUID(uuid=instance_uuid)

        try:
            if volume_metadata.get('readonly') == 'True' and mode != 'ro':
                raise exception.InvalidVolumeAttachMode(mode=mode,
                                                        volume_id=volume.id)
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)

            LOG.info('Attaching volume %(volume_id)s to instance '
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
        except Exception as excep:
            with excutils.save_and_reraise_exception():
                self.message_api.create(
                    context,
                    message_field.Action.ATTACH_VOLUME,
                    resource_uuid=volume_id,
                    exception=excep)
                attachment.attach_status = (
                    fields.VolumeAttachStatus.ERROR_ATTACHING)
                attachment.save()

        volume = attachment.finish_attach(
            instance_uuid,
            host_name_sanitized,
            mountpoint,
            mode)

        self._notify_about_volume_usage(context, volume, "attach.end")
        LOG.info("Attach volume completed successfully.",
                 resource=volume)
        return attachment

    @coordination.synchronized('{volume_id}-{f_name}')
    def detach_volume(self, context, volume_id, attachment_id=None,
                      volume=None):
        """Updates db to show volume is detached."""
        # TODO(vish): refactor this into a more general "unreserve"
        # FIXME(lixiaoy1): Remove this in v4.0 of RPC API.
        if volume is None:
            # For older clients, mimic the old behavior and look up the volume
            # by its volume_id.
            volume = objects.Volume.get_by_id(context, volume_id)

        if attachment_id:
            try:
                attachment = objects.VolumeAttachment.get_by_id(context,
                                                                attachment_id)
            except exception.VolumeAttachmentNotFound:
                LOG.info("Volume detach called, but volume not attached.",
                         resource=volume)
                # We need to make sure the volume status is set to the correct
                # status.  It could be in detaching status now, and we don't
                # want to leave it there.
                volume.finish_detach(attachment_id)
                return
        else:
            # We can try and degrade gracefully here by trying to detach
            # a volume without the attachment_id here if the volume only has
            # one attachment.  This is for backwards compatibility.
            attachments = volume.volume_attachment
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
                LOG.info("Volume detach called, but volume not attached.",
                         resource=volume)
                volume.status = 'available'
                volume.attach_status = fields.VolumeAttachStatus.DETACHED
                volume.save()
                return

        self._notify_about_volume_usage(context, volume, "detach.start")
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)

            LOG.info('Detaching volume %(volume_id)s from instance '
                     '%(instance)s.',
                     {'volume_id': volume_id,
                      'instance': attachment.get('instance_uuid')},
                     resource=volume)
            self.driver.detach_volume(context, volume, attachment)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.db.volume_attachment_update(
                    context, attachment.get('id'), {
                        'attach_status':
                            fields.VolumeAttachStatus.ERROR_DETACHING})

        # NOTE(jdg): We used to do an ensure export here to
        # catch upgrades while volumes were attached (E->F)
        # this was necessary to convert in-use volumes from
        # int ID's to UUID's.  Don't need this any longer

        # We're going to remove the export here
        # (delete the iscsi target)
        try:
            utils.require_driver_initialized(self.driver)
            self.driver.remove_export(context.elevated(), volume)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception("Detach volume failed, due to "
                              "uninitialized driver.",
                              resource=volume)
        except Exception as ex:
            LOG.exception("Detach volume failed, due to "
                          "remove-export failure.",
                          resource=volume)
            raise exception.RemoveExportException(volume=volume_id,
                                                  reason=six.text_type(ex))

        volume.finish_detach(attachment.id)
        self._notify_about_volume_usage(context, volume, "detach.end")
        LOG.info("Detach volume completed successfully.", resource=volume)

    def _create_image_cache_volume_entry(self, ctx, volume_ref,
                                         image_id, image_meta):
        """Create a new image-volume and cache entry for it.

        This assumes that the image has already been downloaded and stored
        in the volume described by the volume_ref.
        """
        image_volume = None
        try:
            if not self.image_volume_cache.ensure_space(ctx, volume_ref):
                LOG.warning('Unable to ensure space for image-volume in'
                            ' cache. Will skip creating entry for image'
                            ' %(image)s on %(service)s.',
                            {'image': image_id,
                             'service': volume_ref.service_topic_queue})
                return

            image_volume = self._clone_image_volume(ctx,
                                                    volume_ref,
                                                    image_meta)
            if not image_volume:
                LOG.warning('Unable to clone image_volume for image '
                            '%(image_id)s will not create cache entry.',
                            {'image_id': image_id})
                return

            self.image_volume_cache.create_cache_entry(
                ctx,
                image_volume,
                image_id,
                image_meta
            )
        except exception.CinderException as e:
            LOG.warning('Failed to create new image-volume cache entry.'
                        ' Error: %(exception)s', {'exception': e})
            if image_volume:
                self.delete_volume(ctx, image_volume)

    def _clone_image_volume(self, ctx, volume, image_meta):
        volume_type_id = volume.get('volume_type_id')
        reserve_opts = {'volumes': 1, 'gigabytes': volume.size}
        QUOTAS.add_volume_type_opts(ctx, reserve_opts, volume_type_id)
        reservations = QUOTAS.reserve(ctx, **reserve_opts)
        try:
            new_vol_values = {k: volume[k] for k in set(volume.keys()) -
                              self._VOLUME_CLONE_SKIP_PROPERTIES}
            new_vol_values['volume_type_id'] = volume_type_id
            new_vol_values['attach_status'] = (
                fields.VolumeAttachStatus.DETACHED)
            new_vol_values['status'] = 'creating'
            new_vol_values['project_id'] = ctx.project_id
            new_vol_values['display_name'] = 'image-%s' % image_meta['id']
            new_vol_values['source_volid'] = volume.id

            LOG.debug('Creating image volume entry: %s.', new_vol_values)
            image_volume = objects.Volume(context=ctx, **new_vol_values)
            image_volume.create()
        except Exception as ex:
            LOG.exception('Create clone_image_volume: %(volume_id)s'
                          'for image %(image_id)s, '
                          'failed (Exception: %(except)s)',
                          {'volume_id': volume.id,
                           'image_id': image_meta['id'],
                           'except': ex})
            QUOTAS.rollback(ctx, reservations)
            return

        QUOTAS.commit(ctx, reservations,
                      project_id=new_vol_values['project_id'])

        try:
            self.create_volume(ctx, image_volume, allow_reschedule=False)
            image_volume = objects.Volume.get_by_id(ctx, image_volume.id)
            if image_volume.status != 'available':
                raise exception.InvalidVolume(_('Volume is not available.'))

            self.db.volume_admin_metadata_update(ctx.elevated(),
                                                 image_volume.id,
                                                 {'readonly': 'True'},
                                                 False)
            return image_volume
        except exception.CinderException:
            LOG.exception('Failed to clone volume %(volume_id)s for '
                          'image %(image_id)s.',
                          {'volume_id': volume.id,
                           'image_id': image_meta['id']})
            try:
                self.delete_volume(ctx, image_volume)
            except exception.CinderException:
                LOG.exception('Could not delete the image volume %(id)s.',
                              {'id': volume.id})
            return

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

        # The image_owner metadata should be set before uri is added to
        # the image so glance cinder store can check its owner.
        image_volume_meta = {'image_owner': ctx.project_id}
        self.db.volume_metadata_update(image_volume_context,
                                       image_volume.id,
                                       image_volume_meta,
                                       False)

        uri = 'cinder://%s' % image_volume.id
        image_registered = None
        try:
            image_registered = image_service.add_location(
                ctx, image_meta['id'], uri, {})
        except (exception.NotAuthorized, exception.Invalid,
                exception.NotFound):
            LOG.exception('Failed to register image volume location '
                          '%(uri)s.', {'uri': uri})

        if not image_registered:
            LOG.warning('Registration of image volume URI %(uri)s '
                        'to image %(image_id)s failed.',
                        {'uri': uri, 'image_id': image_meta['id']})
            try:
                self.delete_volume(image_volume_context, image_volume)
            except exception.CinderException:
                LOG.exception('Could not delete failed image volume '
                              '%(id)s.', {'id': image_volume.id})
            return False

        image_volume_meta['glance_image_id'] = image_meta['id']
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
            volume = objects.Volume.get_by_id(context, volume_id)

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
            LOG.error("Upload volume to image encountered an error "
                      "(image-id: %(image_id)s).",
                      {'image_id': image_meta['id']},
                      resource=volume)
            self.message_api.create(
                context,
                message_field.Action.COPY_VOLUME_TO_IMAGE,
                resource_uuid=volume_id,
                exception=error,
                detail=message_field.Detail.FAILED_TO_UPLOAD_VOLUME)
            if image_service is not None:
                # Deletes the image if it is in queued or saving state
                self._delete_image(context, image_meta['id'], image_service)
            with excutils.save_and_reraise_exception():
                payload['message'] = six.text_type(error)
        finally:
            self.db.volume_update_status_based_on_attachment(context,
                                                             volume_id)
        LOG.info("Copy volume to image completed successfully.",
                 resource=volume)

    def _delete_image(self, context, image_id, image_service):
        """Deletes an image stuck in queued or saving state."""
        try:
            image_meta = image_service.show(context, image_id)
            image_status = image_meta.get('status')
            if image_status == 'queued' or image_status == 'saving':
                LOG.warning("Deleting image in unexpected status: "
                            "%(image_status)s.",
                            {'image_status': image_status},
                            resource={'type': 'image', 'id': image_id})
                image_service.delete(context, image_id)
        except Exception:
            LOG.warning("Image delete encountered an error.",
                        exc_info=True, resource={'type': 'image',
                                                 'id': image_id})

    def _parse_connection_options(self, context, volume, conn_info):
        # Add qos_specs to connection info
        typeid = volume.volume_type_id
        specs = None
        if typeid:
            res = volume_types.get_volume_type_qos_specs(typeid)
            qos = res['qos_specs']
            # only pass qos_specs that is designated to be consumed by
            # front-end, or both front-end and back-end.
            if qos and qos.get('consumer') in ['front-end', 'both']:
                specs = qos.get('specs')

            if specs is not None:
                # Compute fixed IOPS values for per-GB keys
                if 'write_iops_sec_per_gb' in specs:
                    specs['write_iops_sec'] = (
                        int(specs['write_iops_sec_per_gb']) * int(volume.size))
                    specs.pop('write_iops_sec_per_gb')

                if 'read_iops_sec_per_gb' in specs:
                    specs['read_iops_sec'] = (
                        int(specs['read_iops_sec_per_gb']) * int(volume.size))
                    specs.pop('read_iops_sec_per_gb')

                if 'total_iops_sec_per_gb' in specs:
                    specs['total_iops_sec'] = (
                        int(specs['total_iops_sec_per_gb']) * int(volume.size))
                    specs.pop('total_iops_sec_per_gb')

        qos_spec = dict(qos_specs=specs)
        conn_info['data'].update(qos_spec)

        # Add access_mode to connection info
        volume_metadata = volume.admin_metadata
        access_mode = volume_metadata.get('attached_mode')
        if access_mode is None:
            # NOTE(zhiyan): client didn't call 'os-attach' before
            access_mode = ('ro'
                           if volume_metadata.get('readonly') == 'True'
                           else 'rw')
        conn_info['data']['access_mode'] = access_mode

        # Add encrypted flag to connection_info if not set in the driver.
        if conn_info['data'].get('encrypted') is None:
            encrypted = bool(volume.encryption_key_id)
            conn_info['data']['encrypted'] = encrypted

        # Add discard flag to connection_info if not set in the driver and
        # configured to be reported.
        if conn_info['data'].get('discard') is None:
            discard_supported = (self.driver.configuration
                                 .safe_get('report_discard_supported'))
            if discard_supported:
                conn_info['data']['discard'] = True

        return conn_info

    def initialize_connection(self, context, volume, connector):
        """Prepare volume for connection from host represented by connector.

        This method calls the driver initialize_connection and returns
        it to the caller.  The connector parameter is a dictionary with
        information about the host that will connect to the volume in the
        following format::

          .. code:: json

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

          .. code:: json

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

        # TODO(jdg): Add deprecation warning
        utils.require_driver_initialized(self.driver)
        try:
            self.driver.validate_connector(connector)
        except exception.InvalidConnectorException as err:
            raise exception.InvalidInput(reason=six.text_type(err))
        except Exception as err:
            err_msg = (_("Validate volume connection failed "
                         "(error: %(err)s).") % {'err': six.text_type(err)})
            LOG.exception(err_msg, resource=volume)
            raise exception.VolumeBackendAPIException(data=err_msg)

        try:
            model_update = self.driver.create_export(context.elevated(),
                                                     volume, connector)
        except exception.CinderException as ex:
            msg = _("Create export of volume failed (%s)") % ex.msg
            LOG.exception(msg, resource=volume)
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            if model_update:
                volume.update(model_update)
                volume.save()
        except Exception as ex:
            LOG.exception("Model update failed.", resource=volume)
            try:
                self.driver.remove_export(context.elevated(), volume)
            except Exception:
                LOG.exception('Could not remove export after DB model failed.')
            raise exception.ExportFailure(reason=six.text_type(ex))

        try:
            conn_info = self.driver.initialize_connection(volume, connector)
        except Exception as err:
            err_msg = (_("Driver initialize connection failed "
                         "(error: %(err)s).") % {'err': six.text_type(err)})
            LOG.exception(err_msg, resource=volume)

            self.driver.remove_export(context.elevated(), volume)

            raise exception.VolumeBackendAPIException(data=err_msg)

        conn_info = self._parse_connection_options(context, volume, conn_info)
        LOG.info("Initialize volume connection completed successfully.",
                 resource=volume)
        return conn_info

    def initialize_connection_snapshot(self, ctxt, snapshot_id, connector):
        utils.require_driver_initialized(self.driver)
        snapshot = objects.Snapshot.get_by_id(ctxt, snapshot_id)
        try:
            self.driver.validate_connector(connector)
        except exception.InvalidConnectorException as err:
            raise exception.InvalidInput(reason=six.text_type(err))
        except Exception as err:
            err_msg = (_("Validate snapshot connection failed "
                         "(error: %(err)s).") % {'err': six.text_type(err)})
            LOG.exception(err_msg, resource=snapshot)
            raise exception.VolumeBackendAPIException(data=err_msg)

        model_update = None
        try:
            LOG.debug("Snapshot %s: creating export.", snapshot.id)
            model_update = self.driver.create_export_snapshot(
                ctxt.elevated(), snapshot, connector)
            if model_update:
                snapshot.provider_location = model_update.get(
                    'provider_location', None)
                snapshot.provider_auth = model_update.get(
                    'provider_auth', None)
                snapshot.save()
        except exception.CinderException as ex:
            msg = _("Create export of snapshot failed (%s)") % ex.msg
            LOG.exception(msg, resource=snapshot)
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            if model_update:
                snapshot.update(model_update)
                snapshot.save()
        except exception.CinderException as ex:
            LOG.exception("Model update failed.", resource=snapshot)
            raise exception.ExportFailure(reason=six.text_type(ex))

        try:
            conn = self.driver.initialize_connection_snapshot(snapshot,
                                                              connector)
        except Exception as err:
            try:
                err_msg = (_('Unable to fetch connection information from '
                             'backend: %(err)s') %
                           {'err': six.text_type(err)})
                LOG.error(err_msg)
                LOG.debug("Cleaning up failed connect initialization.")
                self.driver.remove_export_snapshot(ctxt.elevated(), snapshot)
            except Exception as ex:
                ex_msg = (_('Error encountered during cleanup '
                            'of a failed attach: %(ex)s') %
                          {'ex': six.text_type(ex)})
                LOG.error(ex_msg)
                raise exception.VolumeBackendAPIException(data=ex_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        LOG.info("Initialize snapshot connection completed successfully.",
                 resource=snapshot)
        return conn

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
            LOG.exception(err_msg, resource=volume_ref)
            raise exception.VolumeBackendAPIException(data=err_msg)
        LOG.info("Terminate volume connection completed successfully.",
                 resource=volume_ref)

    def terminate_connection_snapshot(self, ctxt, snapshot_id,
                                      connector, force=False):
        utils.require_driver_initialized(self.driver)

        snapshot = objects.Snapshot.get_by_id(ctxt, snapshot_id)
        try:
            self.driver.terminate_connection_snapshot(snapshot, connector,
                                                      force=force)
        except Exception as err:
            err_msg = (_('Terminate snapshot connection failed: %(err)s')
                       % {'err': six.text_type(err)})
            LOG.exception(err_msg, resource=snapshot)
            raise exception.VolumeBackendAPIException(data=err_msg)
        LOG.info("Terminate snapshot connection completed successfully.",
                 resource=snapshot)

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

        LOG.info("Remove volume export completed successfully.",
                 resource=volume_ref)

    def remove_export_snapshot(self, ctxt, snapshot_id):
        """Removes an export for a snapshot."""
        utils.require_driver_initialized(self.driver)
        snapshot = objects.Snapshot.get_by_id(ctxt, snapshot_id)
        try:
            self.driver.remove_export_snapshot(ctxt, snapshot)
        except Exception:
            msg = _("Remove snapshot export failed.")
            LOG.exception(msg, resource=snapshot)
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.info("Remove snapshot export completed successfully.",
                 resource=snapshot)

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
                    LOG.exception("Update volume model for "
                                  "transfer operation failed.",
                                  resource=volume_ref)
                    self.db.volume_update(context.elevated(),
                                          volume_id,
                                          {'status': 'error'})

        LOG.info("Transfer volume completed successfully.",
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

    def _attach_volume(self, ctxt, volume, properties, remote=False,
                       attach_encryptor=False):
        status = volume['status']

        if remote:
            rpcapi = volume_rpcapi.VolumeAPI()
            try:
                conn = rpcapi.initialize_connection(ctxt, volume, properties)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error("Failed to attach volume %(vol)s.",
                              {'vol': volume['id']})
                    self.db.volume_update(ctxt, volume['id'],
                                          {'status': status})
        else:
            conn = self.initialize_connection(ctxt, volume, properties)

        attach_info = self._connect_device(conn)
        try:
            if attach_encryptor and (
                    volume_types.is_encrypted(ctxt,
                                              volume.volume_type_id)):
                encryption = self.db.volume_encryption_metadata_get(
                    ctxt.elevated(), volume.id)
                if encryption:
                    utils.brick_attach_volume_encryptor(ctxt,
                                                        attach_info,
                                                        encryption)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to attach volume encryptor"
                          " %(vol)s.", {'vol': volume['id']})
                self._detach_volume(ctxt, attach_info, volume, properties,
                                    force=True)
        return attach_info

    def _detach_volume(self, ctxt, attach_info, volume, properties,
                       force=False, remote=False,
                       attach_encryptor=False):
        connector = attach_info['connector']
        if attach_encryptor and (
                volume_types.is_encrypted(ctxt,
                                          volume.volume_type_id)):
            encryption = self.db.volume_encryption_metadata_get(
                ctxt.elevated(), volume.id)
            if encryption:
                utils.brick_detach_volume_encryptor(attach_info, encryption)
        connector.disconnect_volume(attach_info['conn']['data'],
                                    attach_info['device'], force=force)

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
                    LOG.error('Unable to terminate volume connection: '
                              '%(err)s.', {'err': err})

    def _copy_volume_data(self, ctxt, src_vol, dest_vol, remote=None):
        """Copy data from src_vol to dest_vol."""

        LOG.debug('copy_data_between_volumes %(src)s -> %(dest)s.',
                  {'src': src_vol['name'], 'dest': dest_vol['name']})
        attach_encryptor = False
        # If the encryption method or key is changed, we have to
        # copy data through dm-crypt.
        if volume_types.volume_types_encryption_changed(
                ctxt,
                src_vol.volume_type_id,
                dest_vol.volume_type_id):
            attach_encryptor = True
        properties = utils.brick_get_connector_properties()

        dest_remote = remote in ['dest', 'both']
        dest_attach_info = self._attach_volume(
            ctxt, dest_vol, properties,
            remote=dest_remote,
            attach_encryptor=attach_encryptor)

        try:
            src_remote = remote in ['src', 'both']
            src_attach_info = self._attach_volume(
                ctxt, src_vol, properties,
                remote=src_remote,
                attach_encryptor=attach_encryptor)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to attach source volume for copy.")
                self._detach_volume(ctxt, dest_attach_info, dest_vol,
                                    properties, remote=dest_remote,
                                    attach_encryptor=attach_encryptor,
                                    force=True)

        # Check the backend capabilities of migration destination host.
        rpcapi = volume_rpcapi.VolumeAPI()
        capabilities = rpcapi.get_capabilities(ctxt,
                                               dest_vol.service_topic_queue,
                                               False)
        sparse_copy_volume = bool(capabilities and
                                  capabilities.get('sparse_copy_volume',
                                                   False))

        try:
            size_in_mb = int(src_vol['size']) * units.Ki    # vol size is in GB
            vol_utils.copy_volume(src_attach_info['device']['path'],
                                  dest_attach_info['device']['path'],
                                  size_in_mb,
                                  self.configuration.volume_dd_blocksize,
                                  sparse=sparse_copy_volume)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to copy volume %(src)s to %(dest)s.",
                          {'src': src_vol['id'], 'dest': dest_vol['id']})
        finally:
            try:
                self._detach_volume(ctxt, dest_attach_info, dest_vol,
                                    properties, force=True,
                                    remote=dest_remote,
                                    attach_encryptor=attach_encryptor)
            finally:
                self._detach_volume(ctxt, src_attach_info, src_vol,
                                    properties, force=True,
                                    remote=src_remote,
                                    attach_encryptor=attach_encryptor)

    def _migrate_volume_generic(self, ctxt, volume, backend, new_type_id):
        rpcapi = volume_rpcapi.VolumeAPI()

        # Create new volume on remote host
        tmp_skip = {'snapshot_id', 'source_volid'}
        skip = self._VOLUME_CLONE_SKIP_PROPERTIES | tmp_skip | {'host',
                                                                'cluster_name'}
        new_vol_values = {k: volume[k] for k in set(volume.keys()) - skip}
        if new_type_id:
            new_vol_values['volume_type_id'] = new_type_id
            if volume_types.volume_types_encryption_changed(
                    ctxt, volume.volume_type_id, new_type_id):
                encryption_key_id = vol_utils.create_encryption_key(
                    ctxt, self.key_manager, new_type_id)
                new_vol_values['encryption_key_id'] = encryption_key_id

        new_volume = objects.Volume(
            context=ctxt,
            host=backend['host'],
            cluster_name=backend.get('cluster_name'),
            status='creating',
            attach_status=fields.VolumeAttachStatus.DETACHED,
            migration_status='target:%s' % volume['id'],
            **new_vol_values
        )
        new_volume.create()
        rpcapi.create_volume(ctxt, new_volume, None, None,
                             allow_reschedule=False)

        # Wait for new_volume to become ready
        starttime = time.time()
        deadline = starttime + CONF.migration_create_volume_timeout_secs
        # TODO(thangp): Replace get_by_id with refresh when it is available
        new_volume = objects.Volume.get_by_id(ctxt, new_volume.id)
        tries = 0
        while new_volume.status != 'available':
            tries += 1
            now = time.time()
            if new_volume.status == 'error':
                msg = _("failed to create new_volume on destination")
                self._clean_temporary_volume(ctxt, volume,
                                             new_volume,
                                             clean_db_only=True)
                raise exception.VolumeMigrationFailed(reason=msg)
            elif now > deadline:
                msg = _("timeout creating new_volume on destination")
                self._clean_temporary_volume(ctxt, volume,
                                             new_volume,
                                             clean_db_only=True)
                raise exception.VolumeMigrationFailed(reason=msg)
            else:
                time.sleep(tries ** 2)
            # TODO(thangp): Replace get_by_id with refresh when it is
            # available
            new_volume = objects.Volume.get_by_id(ctxt, new_volume.id)

        # Set skipped value to avoid calling
        # function except for _create_raw_volume
        tmp_skipped_values = {k: volume[k] for k in tmp_skip if volume.get(k)}
        if tmp_skipped_values:
            new_volume.update(tmp_skipped_values)
            new_volume.save()

        # Copy the source volume to the destination volume
        try:
            attachments = volume.volume_attachment
            if not attachments:
                # Pre- and post-copy driver-specific actions
                self.driver.before_volume_copy(ctxt, volume, new_volume,
                                               remote='dest')
                self._copy_volume_data(ctxt, volume, new_volume, remote='dest')
                self.driver.after_volume_copy(ctxt, volume, new_volume,
                                              remote='dest')

                # The above call is synchronous so we complete the migration
                self.migrate_volume_completion(ctxt, volume, new_volume,
                                               error=False)
            else:
                nova_api = compute.API()
                # This is an async call to Nova, which will call the completion
                # when it's done
                for attachment in attachments:
                    instance_uuid = attachment['instance_uuid']
                    nova_api.update_server_volume(ctxt, instance_uuid,
                                                  volume.id,
                                                  new_volume.id)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(
                    "Failed to copy volume %(vol1)s to %(vol2)s", {
                        'vol1': volume.id, 'vol2': new_volume.id})
                self._clean_temporary_volume(ctxt, volume,
                                             new_volume)

    def _clean_temporary_volume(self, ctxt, volume, new_volume,
                                clean_db_only=False):
        # If we're in the migrating phase, we need to cleanup
        # destination volume because source volume is remaining
        if volume.migration_status == 'migrating':
            try:
                if clean_db_only:
                    # The temporary volume is not created, only DB data
                    # is created
                    new_volume.destroy()
                else:
                    # The temporary volume is already created
                    rpcapi = volume_rpcapi.VolumeAPI()
                    rpcapi.delete_volume(ctxt, new_volume)
            except exception.VolumeNotFound:
                LOG.info("Couldn't find the temporary volume "
                         "%(vol)s in the database. There is no need "
                         "to clean up this volume.",
                         {'vol': new_volume.id})
        else:
            # If we're in the completing phase don't delete the
            # destination because we may have already deleted the
            # source! But the migration_status in database should
            # be cleared to handle volume after migration failure
            try:
                new_volume.migration_status = None
                new_volume.save()
            except exception.VolumeNotFound:
                LOG.info("Couldn't find destination volume "
                         "%(vol)s in the database. The entry might be "
                         "successfully deleted during migration "
                         "completion phase.",
                         {'vol': new_volume.id})

                LOG.warning("Failed to migrate volume. The destination "
                            "volume %(vol)s is not deleted since the "
                            "source volume may have been deleted.",
                            {'vol': new_volume.id})

    def migrate_volume_completion(self, ctxt, volume, new_volume, error=False):
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the migration status updated.
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                volume.migration_status = 'error'
                volume.save()

        # NOTE(jdg):  Things get a little hairy in here and we do a lot of
        # things based on volume previous-status and current-status.  At some
        # point this should all be reworked but for now we need to maintain
        # backward compatability and NOT change the API so we're going to try
        # and make this work best we can

        LOG.debug("migrate_volume_completion: completing migration for "
                  "volume %(vol1)s (temporary volume %(vol2)s",
                  {'vol1': volume.id, 'vol2': new_volume.id})
        rpcapi = volume_rpcapi.VolumeAPI()

        orig_volume_status = volume.previous_status

        if error:
            LOG.info("migrate_volume_completion is cleaning up an error "
                     "for volume %(vol1)s (temporary volume %(vol2)s",
                     {'vol1': volume['id'], 'vol2': new_volume.id})
            rpcapi.delete_volume(ctxt, new_volume)
            updates = {'migration_status': 'error',
                       'status': orig_volume_status}
            volume.update(updates)
            volume.save()
            return volume.id

        volume.migration_status = 'completing'
        volume.save()

        volume_attachments = []

        # NOTE(jdg): With new attach flow, we deleted the attachment, so the
        # original volume should now be listed as available, we still need to
        # do the magic swappy thing of name.id etc but we're done with the
        # original attachment record

        # In the "old flow" at this point the orig_volume_status will be in-use
        # and the current status will be retyping.  This is sort of a
        # misleading deal, because Nova has already called terminate
        # connection

        # New Attach Flow, Nova has gone ahead and deleted the attachemnt, this
        # is the source/original volume, we've already migrated the data, we're
        # basically done with it at this point.  We don't need to issue the
        # detach to toggle the status
        if orig_volume_status == 'in-use' and volume.status != 'available':
            for attachment in volume.volume_attachment:
                # Save the attachments the volume currently have
                volume_attachments.append(attachment)
                try:
                    self.detach_volume(ctxt, volume.id, attachment.id)
                except Exception as ex:
                    LOG.error("Detach migration source volume "
                              "%(volume.id)s from attachment "
                              "%(attachment.id)s failed: %(err)s",
                              {'err': ex,
                               'volume.id': volume.id,
                               'attachment.id': attachment.id},
                              resource=volume)

        # Give driver (new_volume) a chance to update things as needed
        # after a successful migration.
        # Note this needs to go through rpc to the host of the new volume
        # the current host and driver object is for the "existing" volume.
        rpcapi.update_migrated_volume(ctxt, volume, new_volume,
                                      orig_volume_status)
        volume.refresh()
        new_volume.refresh()

        # Swap src and dest DB records so we can continue using the src id and
        # asynchronously delete the destination id
        updated_new = volume.finish_volume_migration(new_volume)
        updates = {'status': orig_volume_status,
                   'previous_status': volume.status,
                   'migration_status': 'success'}

        # NOTE(jdg):  With new attachment API's nova will delete the
        # attachment for the source volume for us before calling the
        # migration-completion, now we just need to do the swapping on the
        # volume record, but don't jack with the attachments other than
        # updating volume_id

        # In the old flow at this point the volumes are in attaching and
        # deleting status (dest/new is deleting, but we've done our magic
        # swappy thing so it's a bit confusing, but it does unwind properly
        # when you step through it)

        # In the new flow we simlified this and we don't need it, instead of
        # doing a bunch of swapping we just do attachment-create/delete on the
        # nova side, and then here we just do the ID swaps that are necessary
        # to maintain the old beahvior

        # Restore the attachments for old flow use-case
        if orig_volume_status == 'in-use' and volume.status in ['available',
                                                                'reserved',
                                                                'attaching']:
            for attachment in volume_attachments:
                LOG.debug('Re-attaching: %s', attachment)
                # This is just a db state toggle, the volume is actually
                # already attach and in-use, new attachment flow won't allow
                # this
                rpcapi.attach_volume(ctxt, volume,
                                     attachment.instance_uuid,
                                     attachment.attached_host,
                                     attachment.mountpoint,
                                     'rw')
                # At this point we now have done almost all of our swapping and
                # state-changes.  The target volume is now marked back to
                # "in-use" the destination/worker volume is now in deleting
                # state and the next steps will finish the deletion steps
        volume.update(updates)
        volume.save()

        # Asynchronous deletion of the source volume in the back-end (now
        # pointed by the target volume id)
        try:
            rpcapi.delete_volume(ctxt, updated_new)
        except Exception as ex:
            LOG.error('Failed to request async delete of migration source '
                      'vol %(vol)s: %(err)s',
                      {'vol': volume.id, 'err': ex})

        # For the new flow this is realy the key part.  We just use the
        # attachments to the worker/destination volumes that we created and
        # used for the libvirt migration and we'll just swap their volume_id
        # entries to coorespond with the volume.id swap we did
        for attachment in VA_LIST.get_all_by_volume_id(ctxt, updated_new.id):
            attachment.volume_id = volume.id
            attachment.save()

        # Phewww.. that was easy!  Once we get to a point where the old attach
        # flow can go away we really should rewrite all of this.
        LOG.info("Complete-Migrate volume completed successfully.",
                 resource=volume)
        return volume.id

    def migrate_volume(self, ctxt, volume, host, force_host_copy=False,
                       new_type_id=None):
        """Migrate the volume to the specified host (called on source host)."""
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the migration status updated.
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                volume.migration_status = 'error'
                volume.save()

        model_update = None
        moved = False

        status_update = None
        if volume.status in ('retyping', 'maintenance'):
            status_update = {'status': volume.previous_status}

        volume.migration_status = 'migrating'
        volume.save()
        if not force_host_copy and new_type_id is None:
            try:
                LOG.debug("Issue driver.migrate_volume.", resource=volume)
                moved, model_update = self.driver.migrate_volume(ctxt,
                                                                 volume,
                                                                 host)
                if moved:
                    updates = {'host': host['host'],
                               'cluster_name': host.get('cluster_name'),
                               'migration_status': 'success',
                               'previous_status': volume.status}
                    if status_update:
                        updates.update(status_update)
                    if model_update:
                        updates.update(model_update)
                    volume.update(updates)
                    volume.save()
            except Exception:
                with excutils.save_and_reraise_exception():
                    updates = {'migration_status': 'error'}
                    if status_update:
                        updates.update(status_update)
                    volume.update(updates)
                    volume.save()
        if not moved:
            try:
                self._migrate_volume_generic(ctxt, volume, host, new_type_id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    updates = {'migration_status': 'error'}
                    if status_update:
                        updates.update(status_update)
                    volume.update(updates)
                    volume.save()
        LOG.info("Migrate volume completed successfully.",
                 resource=volume)

    @periodic_task.periodic_task
    def _report_driver_status(self, context):
        if not self.driver.initialized:
            if self.driver.configuration.config_group is None:
                config_group = ''
            else:
                config_group = ('(config name %s)' %
                                self.driver.configuration.config_group)

            LOG.warning("Update driver status failed: %(config_group)s "
                        "is uninitialized.",
                        {'config_group': config_group},
                        resource={'type': 'driver',
                                  'id': self.driver.__class__.__name__})
        else:
            volume_stats = self.driver.get_volume_stats(refresh=True)
            if self.extra_capabilities:
                volume_stats.update(self.extra_capabilities)
            if volume_stats:

                # NOTE(xyang): If driver reports replication_status to be
                # 'error' in volume_stats, get model updates from driver
                # and update db
                if volume_stats.get('replication_status') == (
                        fields.ReplicationStatus.ERROR):
                    filters = self._get_cluster_or_host_filters()
                    groups = objects.GroupList.get_all_replicated(
                        context, filters=filters)
                    group_model_updates, volume_model_updates = (
                        self.driver.get_replication_error_status(context,
                                                                 groups))
                    for grp_update in group_model_updates:
                        try:
                            grp_obj = objects.Group.get_by_id(
                                context, grp_update['group_id'])
                            grp_obj.update(grp_update)
                            grp_obj.save()
                        except exception.GroupNotFound:
                            # Group may be deleted already. Log a warning
                            # and continue.
                            LOG.warning("Group %(grp)s not found while "
                                        "updating driver status.",
                                        {'grp': grp_update['group_id']},
                                        resource={
                                            'type': 'group',
                                            'id': grp_update['group_id']})
                    for vol_update in volume_model_updates:
                        try:
                            vol_obj = objects.Volume.get_by_id(
                                context, vol_update['volume_id'])
                            vol_obj.update(vol_update)
                            vol_obj.save()
                        except exception.VolumeNotFound:
                            # Volume may be deleted already. Log a warning
                            # and continue.
                            LOG.warning("Volume %(vol)s not found while "
                                        "updating driver status.",
                                        {'vol': vol_update['volume_id']},
                                        resource={
                                            'type': 'volume',
                                            'id': vol_update['volume_id']})

                # Append volume stats with 'allocated_capacity_gb'
                self._append_volume_stats(volume_stats)

                # Append filter and goodness function if needed
                volume_stats = (
                    self._append_filter_goodness_functions(volume_stats))

                # queue it to be sent to the Schedulers.
                self.update_service_capabilities(volume_stats)

    def _append_volume_stats(self, vol_stats):
        pools = vol_stats.get('pools', None)
        if pools:
            if isinstance(pools, list):
                for pool in pools:
                    pool_name = pool['pool_name']
                    try:
                        pool_stats = self.stats['pools'][pool_name]
                    except KeyError:
                        # Pool not found in volume manager
                        pool_stats = dict(allocated_capacity_gb=0)

                    pool.update(pool_stats)
            else:
                raise exception.ProgrammingError(
                    reason='Pools stats reported by the driver are not '
                           'reported in a list')
        # For drivers that are not reporting their stats by pool we will use
        # the data from the special fixed pool created by
        # _count_allocated_capacity.
        elif self.stats.get('pools'):
            vol_stats.update(next(iter(self.stats['pools'].values())))
        # This is a special subcase of the above no pool case that happens when
        # we don't have any volumes yet.
        else:
            vol_stats.update(self.stats)
            vol_stats.pop('pools', None)

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

    def _notify_about_group_usage(self,
                                  context,
                                  group,
                                  event_suffix,
                                  volumes=None,
                                  extra_usage_info=None):
        vol_utils.notify_about_group_usage(
            context, group, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

        if not volumes:
            volumes = self.db.volume_get_all_by_generic_group(
                context, group.id)
        if volumes:
            for volume in volumes:
                vol_utils.notify_about_volume_usage(
                    context, volume, event_suffix,
                    extra_usage_info=extra_usage_info, host=self.host)

    def _notify_about_group_snapshot_usage(self,
                                           context,
                                           group_snapshot,
                                           event_suffix,
                                           snapshots=None,
                                           extra_usage_info=None):
        vol_utils.notify_about_group_snapshot_usage(
            context, group_snapshot, event_suffix,
            extra_usage_info=extra_usage_info, host=self.host)

        if not snapshots:
            snapshots = objects.SnapshotList.get_all_for_group_snapshot(
                context, group_snapshot.id)
        if snapshots:
            for snapshot in snapshots:
                vol_utils.notify_about_snapshot_usage(
                    context, snapshot, event_suffix,
                    extra_usage_info=extra_usage_info, host=self.host)

    def extend_volume(self, context, volume, new_size, reservations):
        try:
            # NOTE(flaper87): Verify the driver is enabled
            # before going forward. The exception will be caught
            # and the volume status updated.
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                volume.status = 'error_extending'
                volume.save()

        project_id = volume.project_id
        size_increase = (int(new_size)) - volume.size
        self._notify_about_volume_usage(context, volume, "resize.start")
        try:
            self.driver.extend_volume(volume, new_size)
        except Exception:
            LOG.exception("Extend volume failed.",
                          resource=volume)
            try:
                self.db.volume_update(context, volume.id,
                                      {'status': 'error_extending'})
                raise exception.CinderException(_("Volume %s: Error trying "
                                                  "to extend volume") %
                                                volume.id)
            finally:
                QUOTAS.rollback(context, reservations, project_id=project_id)
                return

        QUOTAS.commit(context, reservations, project_id=project_id)

        attachments = volume.volume_attachment
        if not attachments:
            orig_volume_status = 'available'
        else:
            orig_volume_status = 'in-use'

        volume.update({'size': int(new_size), 'status': orig_volume_status})
        volume.save()

        if orig_volume_status == 'in-use':
            nova_api = compute.API()
            instance_uuids = [attachment.instance_uuid
                              for attachment in attachments]
            nova_api.extend_volume(context, instance_uuids, volume.id)

        pool = vol_utils.extract_host(volume.host, 'pool')
        if pool is None:
            # Legacy volume, put them into default pool
            pool = self.driver.configuration.safe_get(
                'volume_backend_name') or vol_utils.extract_host(
                    volume.host, 'pool', True)

        try:
            self.stats['pools'][pool]['allocated_capacity_gb'] += size_increase
        except KeyError:
            self.stats['pools'][pool] = dict(
                allocated_capacity_gb=size_increase)

        self._notify_about_volume_usage(
            context, volume, "resize.end",
            extra_usage_info={'size': int(new_size)})
        LOG.info("Extend volume completed successfully.",
                 resource=volume)

    def _is_our_backend(self, host, cluster_name):
        return ((not cluster_name and
                 vol_utils.hosts_are_equivalent(self.driver.host, host)) or
                (cluster_name and
                 vol_utils.hosts_are_equivalent(self.driver.cluster_name,
                                                cluster_name)))

    def retype(self, context, volume, new_type_id, host,
               migration_policy='never', reservations=None,
               old_reservations=None):

        def _retype_error(context, volume, old_reservations,
                          new_reservations, status_update):
            try:
                volume.update(status_update)
                volume.save()
            finally:
                QUOTAS.rollback(context, old_reservations)
                QUOTAS.rollback(context, new_reservations)

        status_update = {'status': volume.previous_status}
        if context.project_id != volume.project_id:
            project_id = volume.project_id
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
                volume.update(status_update)
                volume.save()

        # If old_reservations has been passed in from the API, we should
        # skip quotas.
        # TODO(ntpttr): These reservation checks are left in to be backwards
        #               compatible with Liberty and can be removed in N.
        if not old_reservations:
            # Get old reservations
            try:
                reserve_opts = {'volumes': -1, 'gigabytes': -volume.size}
                QUOTAS.add_volume_type_opts(context,
                                            reserve_opts,
                                            volume.volume_type_id)
                # NOTE(wanghao): We don't need to reserve volumes and gigabytes
                # quota for retyping operation since they didn't changed, just
                # reserve volume_type and type gigabytes is fine.
                reserve_opts.pop('volumes')
                reserve_opts.pop('gigabytes')
                old_reservations = QUOTAS.reserve(context,
                                                  project_id=project_id,
                                                  **reserve_opts)
            except Exception:
                volume.update(status_update)
                volume.save()
                msg = _("Failed to update quota usage while retyping volume.")
                LOG.exception(msg, resource=volume)
                raise exception.CinderException(msg)

        # We already got the new reservations
        new_reservations = reservations

        # If volume types have the same contents, no need to do anything.
        # Use the admin contex to be able to access volume extra_specs
        retyped = False
        diff, all_equal = volume_types.volume_types_diff(
            context.elevated(), volume.volume_type_id, new_type_id)
        if all_equal:
            retyped = True

        # Call driver to try and change the type
        retype_model_update = None

        # NOTE(jdg): Check to see if the destination host or cluster (depending
        # if it's the volume is in a clustered backend or not) is the same as
        # the current.  If it's not don't call the driver.retype method,
        # otherwise drivers that implement retype may report success, but it's
        # invalid in the case of a migrate.

        # We assume that those that support pools do this internally
        # so we strip off the pools designation

        if (not retyped and
                not diff.get('encryption') and
                self._is_our_backend(host['host'], host.get('cluster_name'))):
            try:
                new_type = volume_types.get_volume_type(context.elevated(),
                                                        new_type_id)
                with volume.obj_as_admin():
                    ret = self.driver.retype(context,
                                             volume,
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
                    LOG.info("Volume %s: retyped successfully.", volume.id)
            except Exception:
                retyped = False
                LOG.exception("Volume %s: driver error when trying to "
                              "retype, falling back to generic "
                              "mechanism.", volume.id)

        # We could not change the type, so we need to migrate the volume, where
        # the destination volume will be of the new type
        if not retyped:
            if migration_policy == 'never':
                _retype_error(context, volume, old_reservations,
                              new_reservations, status_update)
                msg = _("Retype requires migration but is not allowed.")
                raise exception.VolumeMigrationFailed(reason=msg)

            snaps = objects.SnapshotList.get_all_for_volume(context,
                                                            volume.id)
            if snaps:
                _retype_error(context, volume, old_reservations,
                              new_reservations, status_update)
                msg = _("Volume must not have snapshots.")
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

            # Don't allow volume with replicas to be migrated
            rep_status = volume.replication_status
            if rep_status is not None and rep_status != 'disabled':
                _retype_error(context, volume, old_reservations,
                              new_reservations, status_update)
                msg = _("Volume must not be replicated.")
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

            volume.migration_status = 'starting'
            volume.save()

            try:
                self.migrate_volume(context, volume, host,
                                    new_type_id=new_type_id)
            except Exception:
                with excutils.save_and_reraise_exception():
                    _retype_error(context, volume, old_reservations,
                                  new_reservations, status_update)
        else:
            model_update = {'volume_type_id': new_type_id,
                            'host': host['host'],
                            'cluster_name': host.get('cluster_name'),
                            'status': status_update['status']}
            if retype_model_update:
                model_update.update(retype_model_update)
            self._set_replication_status(diff, model_update)
            volume.update(model_update)
            volume.save()

        if old_reservations:
            QUOTAS.commit(context, old_reservations, project_id=project_id)
        if new_reservations:
            QUOTAS.commit(context, new_reservations, project_id=project_id)
        self._notify_about_volume_usage(
            context, volume, "retype",
            extra_usage_info={'volume_type': new_type_id})
        self.publish_service_capabilities(context)
        LOG.info("Retype volume completed successfully.",
                 resource=volume)

    @staticmethod
    def _set_replication_status(diff, model_update):
        """Update replication_status in model_update if it has changed."""
        if not diff or model_update.get('replication_status'):
            return

        diff_specs = diff.get('extra_specs', {})
        replication_diff = diff_specs.get('replication_enabled')

        if replication_diff:
            is_replicated = vol_utils.is_replicated_str(replication_diff[1])
            if is_replicated:
                replication_status = fields.ReplicationStatus.ENABLED
            else:
                replication_status = fields.ReplicationStatus.DISABLED
            model_update['replication_status'] = replication_status

    def manage_existing(self, ctxt, volume, ref=None):
        vol_ref = self._run_manage_existing_flow_engine(
            ctxt, volume, ref)

        self._update_stats_for_managed(vol_ref)

        LOG.info("Manage existing volume completed successfully.",
                 resource=vol_ref)
        return vol_ref.id

    def _update_stats_for_managed(self, volume_reference):
        # Update volume stats
        pool = vol_utils.extract_host(volume_reference.host, 'pool')
        if pool is None:
            # Legacy volume, put them into default pool
            pool = self.driver.configuration.safe_get(
                'volume_backend_name') or vol_utils.extract_host(
                    volume_reference.host, 'pool', True)

        try:
            self.stats['pools'][pool]['allocated_capacity_gb'] \
                += volume_reference.size
        except KeyError:
            self.stats['pools'][pool] = dict(
                allocated_capacity_gb=volume_reference.size)

    def _run_manage_existing_flow_engine(self, ctxt, volume, ref):
        try:
            flow_engine = manage_existing.get_flow(
                ctxt,
                self.db,
                self.driver,
                self.host,
                volume,
                ref,
            )
        except Exception:
            msg = _("Failed to create manage_existing flow.")
            LOG.exception(msg, resource={'type': 'volume', 'id': volume.id})
            raise exception.CinderException(msg)

        with flow_utils.DynamicLogListener(flow_engine, logger=LOG):
            flow_engine.run()

        # Fetch created volume from storage
        vol_ref = flow_engine.storage.fetch('volume')

        return vol_ref

    def _get_cluster_or_host_filters(self):
        if self.cluster:
            filters = {'cluster_name': self.cluster}
        else:
            filters = {'host': self.host}
        return filters

    def _get_my_resources(self, ctxt, ovo_class_list):
        filters = self._get_cluster_or_host_filters()
        return getattr(ovo_class_list, 'get_all')(ctxt, filters=filters)

    def _get_my_volumes(self, ctxt):
        return self._get_my_resources(ctxt, objects.VolumeList)

    def _get_my_snapshots(self, ctxt):
        return self._get_my_resources(ctxt, objects.SnapshotList)

    def get_manageable_volumes(self, ctxt, marker, limit, offset, sort_keys,
                               sort_dirs, want_objects=False):
        try:
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception("Listing manageable volumes failed, due "
                              "to uninitialized driver.")

        cinder_volumes = self._get_my_volumes(ctxt)
        try:
            driver_entries = self.driver.get_manageable_volumes(
                cinder_volumes, marker, limit, offset, sort_keys, sort_dirs)
            if want_objects:
                driver_entries = (objects.ManageableVolumeList.
                                  from_primitives(ctxt, driver_entries))
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Listing manageable volumes failed, due "
                              "to driver error.")
        return driver_entries

    def create_group(self, context, group):
        """Creates the group."""
        context = context.elevated()

        # Make sure the host in the DB matches our own when clustered
        self._set_resource_host(group)

        status = fields.GroupStatus.AVAILABLE
        model_update = None

        self._notify_about_group_usage(context, group, "create.start")

        try:
            utils.require_driver_initialized(self.driver)

            LOG.info("Group %s: creating", group.name)

            try:
                model_update = self.driver.create_group(context, group)
            except NotImplementedError:
                if not group_types.is_default_cgsnapshot_type(
                        group.group_type_id):
                    model_update = self._create_group_generic(context, group)
                else:
                    cg, __ = self._convert_group_to_cg(group, [])
                    model_update = self.driver.create_consistencygroup(
                        context, cg)

            if model_update:
                if (model_update['status'] ==
                        fields.GroupStatus.ERROR):
                    msg = (_('Create group failed.'))
                    LOG.error(msg,
                              resource={'type': 'group',
                                        'id': group.id})
                    raise exception.VolumeDriverException(message=msg)
                else:
                    group.update(model_update)
                    group.save()
        except Exception:
            with excutils.save_and_reraise_exception():
                group.status = fields.GroupStatus.ERROR
                group.save()
                LOG.error("Group %s: create failed",
                          group.name)

        group.status = status
        group.created_at = timeutils.utcnow()
        group.save()
        LOG.info("Group %s: created successfully", group.name)

        self._notify_about_group_usage(context, group, "create.end")

        LOG.info("Create group completed successfully.",
                 resource={'type': 'group',
                           'id': group.id})
        return group

    def create_group_from_src(self, context, group,
                              group_snapshot=None, source_group=None):
        """Creates the group from source.

        The source can be a group snapshot or a source group.
        """
        source_name = None
        snapshots = None
        source_vols = None
        try:
            volumes = objects.VolumeList.get_all_by_generic_group(context,
                                                                  group.id)
            if group_snapshot:
                try:
                    # Check if group_snapshot still exists
                    group_snapshot = objects.GroupSnapshot.get_by_id(
                        context, group_snapshot.id)
                except exception.GroupSnapshotNotFound:
                    LOG.error("Create group from snapshot-%(snap)s failed: "
                              "SnapshotNotFound.",
                              {'snap': group_snapshot.id},
                              resource={'type': 'group',
                                        'id': group.id})
                    raise

                source_name = _("snapshot-%s") % group_snapshot.id
                snapshots = objects.SnapshotList.get_all_for_group_snapshot(
                    context, group_snapshot.id)
                for snap in snapshots:
                    if (snap.status not in
                            VALID_CREATE_GROUP_SRC_SNAP_STATUS):
                        msg = (_("Cannot create group "
                                 "%(group)s because snapshot %(snap)s is "
                                 "not in a valid state. Valid states are: "
                                 "%(valid)s.") %
                               {'group': group.id,
                                'snap': snap['id'],
                                'valid': VALID_CREATE_GROUP_SRC_SNAP_STATUS})
                        raise exception.InvalidGroup(reason=msg)

            if source_group:
                try:
                    source_group = objects.Group.get_by_id(
                        context, source_group.id)
                except exception.GroupNotFound:
                    LOG.error("Create group "
                              "from source group-%(group)s failed: "
                              "GroupNotFound.",
                              {'group': source_group.id},
                              resource={'type': 'group',
                                        'id': group.id})
                    raise

                source_name = _("group-%s") % source_group.id
                source_vols = objects.VolumeList.get_all_by_generic_group(
                    context, source_group.id)
                for source_vol in source_vols:
                    if (source_vol.status not in
                            VALID_CREATE_GROUP_SRC_GROUP_STATUS):
                        msg = (_("Cannot create group "
                                 "%(group)s because source volume "
                                 "%(source_vol)s is not in a valid "
                                 "state. Valid states are: "
                                 "%(valid)s.") %
                               {'group': group.id,
                                'source_vol': source_vol.id,
                                'valid': VALID_CREATE_GROUP_SRC_GROUP_STATUS})
                        raise exception.InvalidGroup(reason=msg)

            # Sort source snapshots so that they are in the same order as their
            # corresponding target volumes.
            sorted_snapshots = None
            if group_snapshot and snapshots:
                sorted_snapshots = self._sort_snapshots(volumes, snapshots)

            # Sort source volumes so that they are in the same order as their
            # corresponding target volumes.
            sorted_source_vols = None
            if source_group and source_vols:
                sorted_source_vols = self._sort_source_vols(volumes,
                                                            source_vols)

            self._notify_about_group_usage(
                context, group, "create.start")

            utils.require_driver_initialized(self.driver)

            try:
                model_update, volumes_model_update = (
                    self.driver.create_group_from_src(
                        context, group, volumes, group_snapshot,
                        sorted_snapshots, source_group, sorted_source_vols))
            except NotImplementedError:
                if not group_types.is_default_cgsnapshot_type(
                        group.group_type_id):
                    model_update, volumes_model_update = (
                        self._create_group_from_src_generic(
                            context, group, volumes, group_snapshot,
                            sorted_snapshots, source_group,
                            sorted_source_vols))
                else:
                    cg, volumes = self._convert_group_to_cg(
                        group, volumes)
                    cgsnapshot, sorted_snapshots = (
                        self._convert_group_snapshot_to_cgsnapshot(
                            group_snapshot, sorted_snapshots, context))
                    source_cg, sorted_source_vols = (
                        self._convert_group_to_cg(source_group,
                                                  sorted_source_vols))
                    model_update, volumes_model_update = (
                        self.driver.create_consistencygroup_from_src(
                            context, cg, volumes, cgsnapshot,
                            sorted_snapshots, source_cg, sorted_source_vols))
                    self._remove_cgsnapshot_id_from_snapshots(sorted_snapshots)
                    self._remove_consistencygroup_id_from_volumes(volumes)
                    self._remove_consistencygroup_id_from_volumes(
                        sorted_source_vols)

            if volumes_model_update:
                for update in volumes_model_update:
                    self.db.volume_update(context, update['id'], update)

            if model_update:
                group.update(model_update)
                group.save()

        except Exception:
            with excutils.save_and_reraise_exception():
                group.status = fields.GroupStatus.ERROR
                group.save()
                LOG.error("Create group "
                          "from source %(source)s failed.",
                          {'source': source_name},
                          resource={'type': 'group',
                                    'id': group.id})
                # Update volume status to 'error' as well.
                self._remove_consistencygroup_id_from_volumes(volumes)
                for vol in volumes:
                    vol.status = 'error'
                    vol.save()

        now = timeutils.utcnow()
        status = 'available'
        for vol in volumes:
            update = {'status': status, 'created_at': now}
            self._update_volume_from_src(context, vol, update, group=group)
            self._update_allocated_capacity(vol)

        group.status = status
        group.created_at = now
        group.save()

        self._notify_about_group_usage(
            context, group, "create.end")
        LOG.info("Create group "
                 "from source-%(source)s completed successfully.",
                 {'source': source_name},
                 resource={'type': 'group',
                           'id': group.id})
        return group

    def _create_group_from_src_generic(self, context, group, volumes,
                                       group_snapshot=None, snapshots=None,
                                       source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of volume objects in the source_group.
        :returns: model_update, volumes_model_update
        """
        model_update = {'status': 'available'}
        volumes_model_update = []
        for vol in volumes:
            if snapshots:
                for snapshot in snapshots:
                    if vol.snapshot_id == snapshot.id:
                        vol_model_update = {'id': vol.id}
                        try:
                            driver_update = (
                                self.driver.create_volume_from_snapshot(
                                    vol, snapshot))
                            if driver_update:
                                driver_update.pop('id', None)
                                vol_model_update.update(driver_update)
                            if 'status' not in vol_model_update:
                                vol_model_update['status'] = 'available'
                        except Exception:
                            vol_model_update['status'] = 'error'
                            model_update['status'] = 'error'
                        volumes_model_update.append(vol_model_update)
                        break
            elif source_vols:
                for source_vol in source_vols:
                    if vol.source_volid == source_vol.id:
                        vol_model_update = {'id': vol.id}
                        try:
                            driver_update = self.driver.create_cloned_volume(
                                vol, source_vol)
                            if driver_update:
                                driver_update.pop('id', None)
                                vol_model_update.update(driver_update)
                            if 'status' not in vol_model_update:
                                vol_model_update['status'] = 'available'
                        except Exception:
                            vol_model_update['status'] = 'error'
                            model_update['status'] = 'error'
                        volumes_model_update.append(vol_model_update)
                        break

        return model_update, volumes_model_update

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
                LOG.error("Source snapshot cannot be found for target "
                          "volume %(volume_id)s.",
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
                LOG.error("Source volumes cannot be found for target "
                          "volume %(volume_id)s.",
                          {'volume_id': vol['id']})
                raise exception.VolumeNotFound(
                    volume_id=vol['source_volid'])
            sorted_source_vols.extend(found_source_vols)

        return sorted_source_vols

    def _update_volume_from_src(self, context, vol, update, group=None):
        try:
            snapshot_id = vol.get('snapshot_id')
            source_volid = vol.get('source_volid')
            if snapshot_id:
                snapshot = objects.Snapshot.get_by_id(context, snapshot_id)
                orig_vref = self.db.volume_get(context,
                                               snapshot.volume_id)
                if orig_vref.bootable:
                    update['bootable'] = True
                    self.db.volume_glance_metadata_copy_to_volume(
                        context, vol['id'], snapshot_id)
            if source_volid:
                source_vol = objects.Volume.get_by_id(context, source_volid)
                if source_vol.bootable:
                    update['bootable'] = True
                    self.db.volume_glance_metadata_copy_from_volume_to_volume(
                        context, source_volid, vol['id'])
                if source_vol.multiattach:
                    update['multiattach'] = True

        except exception.SnapshotNotFound:
            LOG.error("Source snapshot %(snapshot_id)s cannot be found.",
                      {'snapshot_id': vol['snapshot_id']})
            self.db.volume_update(context, vol['id'],
                                  {'status': 'error'})
            if group:
                group.status = fields.GroupStatus.ERROR
                group.save()
            raise
        except exception.VolumeNotFound:
            LOG.error("The source volume %(volume_id)s "
                      "cannot be found.",
                      {'volume_id': snapshot.volume_id})
            self.db.volume_update(context, vol['id'],
                                  {'status': 'error'})
            if group:
                group.status = fields.GroupStatus.ERROR
                group.save()
            raise
        except exception.CinderException as ex:
            LOG.error("Failed to update %(volume_id)s"
                      " metadata using the provided snapshot"
                      " %(snapshot_id)s metadata.",
                      {'volume_id': vol['id'],
                       'snapshot_id': vol['snapshot_id']})
            self.db.volume_update(context, vol['id'],
                                  {'status': 'error'})
            if group:
                group.status = fields.GroupStatus.ERROR
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

    def delete_group(self, context, group):
        """Deletes group and the volumes in the group."""
        context = context.elevated()
        project_id = group.project_id

        if context.project_id != group.project_id:
            project_id = group.project_id
        else:
            project_id = context.project_id

        volumes = objects.VolumeList.get_all_by_generic_group(
            context, group.id)

        for vol_obj in volumes:
            if vol_obj.attach_status == "attached":
                # Volume is still attached, need to detach first
                raise exception.VolumeAttached(volume_id=vol_obj.id)
            self._check_is_our_resource(vol_obj)

        self._notify_about_group_usage(
            context, group, "delete.start")

        volumes_model_update = None
        model_update = None
        try:
            utils.require_driver_initialized(self.driver)

            try:
                model_update, volumes_model_update = (
                    self.driver.delete_group(context, group, volumes))
            except NotImplementedError:
                if not group_types.is_default_cgsnapshot_type(
                        group.group_type_id):
                    model_update, volumes_model_update = (
                        self._delete_group_generic(context, group, volumes))
                else:
                    cg, volumes = self._convert_group_to_cg(
                        group, volumes)
                    model_update, volumes_model_update = (
                        self.driver.delete_consistencygroup(context, cg,
                                                            volumes))
                    self._remove_consistencygroup_id_from_volumes(volumes)

            if volumes_model_update:
                for update in volumes_model_update:
                    # If we failed to delete a volume, make sure the
                    # status for the group is set to error as well
                    if (update['status'] in ['error_deleting', 'error']
                            and model_update['status'] not in
                            ['error_deleting', 'error']):
                        model_update['status'] = update['status']
                self.db.volumes_update(context, volumes_model_update)

            if model_update:
                if model_update['status'] in ['error_deleting', 'error']:
                    msg = (_('Delete group failed.'))
                    LOG.error(msg,
                              resource={'type': 'group',
                                        'id': group.id})
                    raise exception.VolumeDriverException(message=msg)
                else:
                    group.update(model_update)
                    group.save()

        except Exception:
            with excutils.save_and_reraise_exception():
                group.status = fields.GroupStatus.ERROR
                group.save()
                # Update volume status to 'error' if driver returns
                # None for volumes_model_update.
                if not volumes_model_update:
                    self._remove_consistencygroup_id_from_volumes(volumes)
                    for vol_obj in volumes:
                        vol_obj.status = 'error'
                        vol_obj.save()

        # Get reservations for group
        try:
            reserve_opts = {'groups': -1}
            grpreservations = GROUP_QUOTAS.reserve(context,
                                                   project_id=project_id,
                                                   **reserve_opts)
        except Exception:
            grpreservations = None
            LOG.exception("Delete group "
                          "failed to update usages.",
                          resource={'type': 'group',
                                    'id': group.id})

        for vol in volumes:
            # Get reservations for volume
            try:
                reserve_opts = {'volumes': -1,
                                'gigabytes': -vol.size}
                QUOTAS.add_volume_type_opts(context,
                                            reserve_opts,
                                            vol.volume_type_id)
                reservations = QUOTAS.reserve(context,
                                              project_id=project_id,
                                              **reserve_opts)
            except Exception:
                reservations = None
                LOG.exception("Delete group "
                              "failed to update usages.",
                              resource={'type': 'group',
                                        'id': group.id})

            # Delete glance metadata if it exists
            self.db.volume_glance_metadata_delete_by_volume(context, vol.id)

            vol.destroy()

            # Commit the reservations
            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

            self.stats['allocated_capacity_gb'] -= vol.size

        if grpreservations:
            GROUP_QUOTAS.commit(context, grpreservations,
                                project_id=project_id)

        group.destroy()
        self._notify_about_group_usage(
            context, group, "delete.end")
        self.publish_service_capabilities(context)
        LOG.info("Delete group "
                 "completed successfully.",
                 resource={'type': 'group',
                           'id': group.id})

    def _convert_group_to_cg(self, group, volumes):
        if not group:
            return None, None
        cg = consistencygroup.ConsistencyGroup()
        cg.from_group(group)
        for vol in volumes:
            vol.consistencygroup_id = vol.group_id
            vol.consistencygroup = cg

        return cg, volumes

    def _remove_consistencygroup_id_from_volumes(self, volumes):
        if not volumes:
            return
        for vol in volumes:
            vol.consistencygroup_id = None
            vol.consistencygroup = None

    def _convert_group_snapshot_to_cgsnapshot(self, group_snapshot, snapshots,
                                              ctxt):
        if not group_snapshot:
            return None, None
        cgsnap = cgsnapshot.CGSnapshot()
        cgsnap.from_group_snapshot(group_snapshot)

        # Populate consistencygroup object
        grp = objects.Group.get_by_id(ctxt, group_snapshot.group_id)
        cg, __ = self._convert_group_to_cg(grp, [])
        cgsnap.consistencygroup = cg

        for snap in snapshots:
            snap.cgsnapshot_id = snap.group_snapshot_id
            snap.cgsnapshot = cgsnap

        return cgsnap, snapshots

    def _remove_cgsnapshot_id_from_snapshots(self, snapshots):
        if not snapshots:
            return
        for snap in snapshots:
            snap.cgsnapshot_id = None
            snap.cgsnapshot = None

    def _create_group_generic(self, context, group):
        """Creates a group."""
        # A group entry is already created in db. Just returns a status here.
        model_update = {'status': fields.GroupStatus.AVAILABLE,
                        'created_at': timeutils.utcnow()}
        return model_update

    def _delete_group_generic(self, context, group, volumes):
        """Deletes a group and volumes in the group."""
        model_update = {'status': group.status}
        volume_model_updates = []
        for volume_ref in volumes:
            volume_model_update = {'id': volume_ref.id}
            try:
                self.driver.remove_export(context, volume_ref)
                self.driver.delete_volume(volume_ref)
                volume_model_update['status'] = 'deleted'
            except exception.VolumeIsBusy:
                volume_model_update['status'] = 'available'
            except Exception:
                volume_model_update['status'] = 'error'
                model_update['status'] = fields.GroupStatus.ERROR
            volume_model_updates.append(volume_model_update)

        return model_update, volume_model_updates

    def _update_group_generic(self, context, group,
                              add_volumes=None, remove_volumes=None):
        """Updates a group."""
        # NOTE(xyang): The volume manager adds/removes the volume to/from the
        # group in the database. This default implementation does not do
        # anything in the backend storage.
        return None, None, None

    def _collect_volumes_for_group(self, context, group, volumes, add=True):
        if add:
            valid_status = VALID_ADD_VOL_TO_GROUP_STATUS
        else:
            valid_status = VALID_REMOVE_VOL_FROM_GROUP_STATUS
        volumes_ref = []
        if not volumes:
            return volumes_ref
        for add_vol in volumes.split(','):
            try:
                add_vol_ref = objects.Volume.get_by_id(context, add_vol)
            except exception.VolumeNotFound:
                LOG.error("Update group "
                          "failed to %(op)s volume-%(volume_id)s: "
                          "VolumeNotFound.",
                          {'volume_id': add_vol_ref.id,
                           'op': 'add' if add else 'remove'},
                          resource={'type': 'group',
                                    'id': group.id})
                raise
            if add_vol_ref.status not in valid_status:
                msg = (_("Can not %(op)s volume %(volume_id)s to "
                         "group %(group_id)s because volume is in an invalid "
                         "state: %(status)s. Valid states are: %(valid)s.") %
                       {'volume_id': add_vol_ref.id,
                        'group_id': group.id,
                        'status': add_vol_ref.status,
                        'valid': valid_status,
                        'op': 'add' if add else 'remove'})
                raise exception.InvalidVolume(reason=msg)
            if add:
                self._check_is_our_resource(add_vol_ref)
            volumes_ref.append(add_vol_ref)
        return volumes_ref

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Updates group.

        Update group by adding volumes to the group,
        or removing volumes from the group.
        """

        add_volumes_ref = self._collect_volumes_for_group(context,
                                                          group,
                                                          add_volumes,
                                                          add=True)
        remove_volumes_ref = self._collect_volumes_for_group(context,
                                                             group,
                                                             remove_volumes,
                                                             add=False)
        self._notify_about_group_usage(
            context, group, "update.start")

        try:
            utils.require_driver_initialized(self.driver)

            try:
                model_update, add_volumes_update, remove_volumes_update = (
                    self.driver.update_group(
                        context, group,
                        add_volumes=add_volumes_ref,
                        remove_volumes=remove_volumes_ref))
            except NotImplementedError:
                if not group_types.is_default_cgsnapshot_type(
                        group.group_type_id):
                    model_update, add_volumes_update, remove_volumes_update = (
                        self._update_group_generic(
                            context, group,
                            add_volumes=add_volumes_ref,
                            remove_volumes=remove_volumes_ref))
                else:
                    cg, remove_volumes_ref = self._convert_group_to_cg(
                        group, remove_volumes_ref)
                    model_update, add_volumes_update, remove_volumes_update = (
                        self.driver.update_consistencygroup(
                            context, cg,
                            add_volumes=add_volumes_ref,
                            remove_volumes=remove_volumes_ref))
                    self._remove_consistencygroup_id_from_volumes(
                        remove_volumes_ref)

            volumes_to_update = []
            if add_volumes_update:
                volumes_to_update.extend(add_volumes_update)
            if remove_volumes_update:
                volumes_to_update.extend(remove_volumes_update)
            self.db.volumes_update(context, volumes_to_update)

            if model_update:
                if model_update['status'] in (
                        [fields.GroupStatus.ERROR]):
                    msg = (_('Error occurred when updating group '
                             '%s.') % group.id)
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)
                group.update(model_update)
                group.save()

        except Exception as e:
            with excutils.save_and_reraise_exception():
                if isinstance(e, exception.VolumeDriverException):
                    LOG.error("Error occurred in the volume driver when "
                              "updating group %(group_id)s.",
                              {'group_id': group.id})
                else:
                    LOG.error("Failed to update group %(group_id)s.",
                              {'group_id': group.id})
                group.status = fields.GroupStatus.ERROR
                group.save()
                for add_vol in add_volumes_ref:
                    add_vol.status = 'error'
                    add_vol.save()
                for rem_vol in remove_volumes_ref:
                    if isinstance(e, exception.VolumeDriverException):
                        rem_vol.consistencygroup_id = None
                        rem_vol.consistencygroup = None
                    rem_vol.status = 'error'
                    rem_vol.save()

        for add_vol in add_volumes_ref:
            add_vol.group_id = group.id
            add_vol.save()
        for rem_vol in remove_volumes_ref:
            rem_vol.group_id = None
            rem_vol.save()
        group.status = fields.GroupStatus.AVAILABLE
        group.save()

        self._notify_about_group_usage(
            context, group, "update.end")
        LOG.info("Update group completed successfully.",
                 resource={'type': 'group',
                           'id': group.id})

    def create_group_snapshot(self, context, group_snapshot):
        """Creates the group_snapshot."""
        caller_context = context
        context = context.elevated()

        LOG.info("GroupSnapshot %s: creating.", group_snapshot.id)

        snapshots = objects.SnapshotList.get_all_for_group_snapshot(
            context, group_snapshot.id)

        self._notify_about_group_snapshot_usage(
            context, group_snapshot, "create.start")

        snapshots_model_update = None
        model_update = None
        try:
            utils.require_driver_initialized(self.driver)

            LOG.debug("Group snapshot %(grp_snap_id)s: creating.",
                      {'grp_snap_id': group_snapshot.id})

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            group_snapshot.context = caller_context
            for snapshot in snapshots:
                snapshot.context = caller_context

            try:
                model_update, snapshots_model_update = (
                    self.driver.create_group_snapshot(context, group_snapshot,
                                                      snapshots))
            except NotImplementedError:
                if not group_types.is_default_cgsnapshot_type(
                        group_snapshot.group_type_id):
                    model_update, snapshots_model_update = (
                        self._create_group_snapshot_generic(
                            context, group_snapshot, snapshots))
                else:
                    cgsnapshot, snapshots = (
                        self._convert_group_snapshot_to_cgsnapshot(
                            group_snapshot, snapshots, context))
                    model_update, snapshots_model_update = (
                        self.driver.create_cgsnapshot(context, cgsnapshot,
                                                      snapshots))
                    self._remove_cgsnapshot_id_from_snapshots(snapshots)
            if snapshots_model_update:
                for snap_model in snapshots_model_update:
                    # Update db for snapshot.
                    # NOTE(xyang): snapshots is a list of snapshot objects.
                    # snapshots_model_update should be a list of dicts.
                    snap_id = snap_model.pop('id')
                    snap_obj = objects.Snapshot.get_by_id(context, snap_id)
                    snap_obj.update(snap_model)
                    snap_obj.save()
                    if (snap_model['status'] in [
                        fields.SnapshotStatus.ERROR_DELETING,
                        fields.SnapshotStatus.ERROR] and
                            model_update['status'] not in
                            [fields.GroupSnapshotStatus.ERROR_DELETING,
                             fields.GroupSnapshotStatus.ERROR]):
                        model_update['status'] = snap_model['status']

            if model_update:
                if model_update['status'] == fields.GroupSnapshotStatus.ERROR:
                    msg = (_('Error occurred when creating group_snapshot '
                             '%s.') % group_snapshot.id)
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)

                group_snapshot.update(model_update)
                group_snapshot.save()

        except exception.CinderException:
            with excutils.save_and_reraise_exception():
                group_snapshot.status = fields.GroupSnapshotStatus.ERROR
                group_snapshot.save()
                # Update snapshot status to 'error' if driver returns
                # None for snapshots_model_update.
                self._remove_cgsnapshot_id_from_snapshots(snapshots)
                if not snapshots_model_update:
                    for snapshot in snapshots:
                        snapshot.status = fields.SnapshotStatus.ERROR
                        snapshot.save()

        for snapshot in snapshots:
            volume_id = snapshot.volume_id
            snapshot_id = snapshot.id
            vol_obj = objects.Volume.get_by_id(context, volume_id)
            if vol_obj.bootable:
                try:
                    self.db.volume_glance_metadata_copy_to_snapshot(
                        context, snapshot_id, volume_id)
                except exception.GlanceMetadataNotFound:
                    # If volume is not created from image, No glance metadata
                    # would be available for that volume in
                    # volume glance metadata table
                    pass
                except exception.CinderException as ex:
                    LOG.error("Failed updating %(snapshot_id)s"
                              " metadata using the provided volumes"
                              " %(volume_id)s metadata.",
                              {'volume_id': volume_id,
                               'snapshot_id': snapshot_id})
                    snapshot.status = fields.SnapshotStatus.ERROR
                    snapshot.save()
                    raise exception.MetadataCopyFailure(
                        reason=six.text_type(ex))

            snapshot.status = fields.SnapshotStatus.AVAILABLE
            snapshot.progress = '100%'
            snapshot.save()

        group_snapshot.status = fields.GroupSnapshotStatus.AVAILABLE
        group_snapshot.save()

        LOG.info("group_snapshot %s: created successfully",
                 group_snapshot.id)
        self._notify_about_group_snapshot_usage(
            context, group_snapshot, "create.end")
        return group_snapshot

    def _create_group_snapshot_generic(self, context, group_snapshot,
                                       snapshots):
        """Creates a group_snapshot."""
        model_update = {'status': 'available'}
        snapshot_model_updates = []
        for snapshot in snapshots:
            snapshot_model_update = {'id': snapshot.id}
            try:
                driver_update = self.driver.create_snapshot(snapshot)
                if driver_update:
                    driver_update.pop('id', None)
                    snapshot_model_update.update(driver_update)
                if 'status' not in snapshot_model_update:
                    snapshot_model_update['status'] = (
                        fields.SnapshotStatus.AVAILABLE)
            except Exception:
                snapshot_model_update['status'] = (
                    fields.SnapshotStatus.ERROR)
                model_update['status'] = 'error'
            snapshot_model_updates.append(snapshot_model_update)

        return model_update, snapshot_model_updates

    def _delete_group_snapshot_generic(self, context, group_snapshot,
                                       snapshots):
        """Deletes a group_snapshot."""
        model_update = {'status': group_snapshot.status}
        snapshot_model_updates = []
        for snapshot in snapshots:
            snapshot_model_update = {'id': snapshot.id}
            try:
                self.driver.delete_snapshot(snapshot)
                snapshot_model_update['status'] = (
                    fields.SnapshotStatus.DELETED)
            except exception.SnapshotIsBusy:
                snapshot_model_update['status'] = (
                    fields.SnapshotStatus.AVAILABLE)
            except Exception:
                snapshot_model_update['status'] = (
                    fields.SnapshotStatus.ERROR)
                model_update['status'] = 'error'
            snapshot_model_updates.append(snapshot_model_update)

        return model_update, snapshot_model_updates

    def delete_group_snapshot(self, context, group_snapshot):
        """Deletes group_snapshot."""
        caller_context = context
        context = context.elevated()
        project_id = group_snapshot.project_id

        LOG.info("group_snapshot %s: deleting", group_snapshot.id)

        snapshots = objects.SnapshotList.get_all_for_group_snapshot(
            context, group_snapshot.id)

        self._notify_about_group_snapshot_usage(
            context, group_snapshot, "delete.start")

        snapshots_model_update = None
        model_update = None
        try:
            utils.require_driver_initialized(self.driver)

            LOG.debug("group_snapshot %(grp_snap_id)s: deleting",
                      {'grp_snap_id': group_snapshot.id})

            # Pass context so that drivers that want to use it, can,
            # but it is not a requirement for all drivers.
            group_snapshot.context = caller_context
            for snapshot in snapshots:
                snapshot.context = caller_context

            try:
                model_update, snapshots_model_update = (
                    self.driver.delete_group_snapshot(context, group_snapshot,
                                                      snapshots))
            except NotImplementedError:
                if not group_types.is_default_cgsnapshot_type(
                        group_snapshot.group_type_id):
                    model_update, snapshots_model_update = (
                        self._delete_group_snapshot_generic(
                            context, group_snapshot, snapshots))
                else:
                    cgsnapshot, snapshots = (
                        self._convert_group_snapshot_to_cgsnapshot(
                            group_snapshot, snapshots, context))
                    model_update, snapshots_model_update = (
                        self.driver.delete_cgsnapshot(context, cgsnapshot,
                                                      snapshots))
                    self._remove_cgsnapshot_id_from_snapshots(snapshots)

            if snapshots_model_update:
                for snap_model in snapshots_model_update:
                    # NOTE(xyang): snapshots is a list of snapshot objects.
                    # snapshots_model_update should be a list of dicts.
                    snap = next((item for item in snapshots if
                                 item.id == snap_model['id']), None)
                    if snap:
                        snap_model.pop('id')
                        snap.update(snap_model)
                        snap.save()

                    if (snap_model['status'] in
                            [fields.SnapshotStatus.ERROR_DELETING,
                             fields.SnapshotStatus.ERROR] and
                            model_update['status'] not in
                            ['error_deleting', 'error']):
                        model_update['status'] = snap_model['status']

            if model_update:
                if model_update['status'] in ['error_deleting', 'error']:
                    msg = (_('Error occurred when deleting group_snapshot '
                             '%s.') % group_snapshot.id)
                    LOG.error(msg)
                    raise exception.VolumeDriverException(message=msg)
                else:
                    group_snapshot.update(model_update)
                    group_snapshot.save()

        except exception.CinderException:
            with excutils.save_and_reraise_exception():
                group_snapshot.status = fields.GroupSnapshotStatus.ERROR
                group_snapshot.save()
                # Update snapshot status to 'error' if driver returns
                # None for snapshots_model_update.
                if not snapshots_model_update:
                    self._remove_cgsnapshot_id_from_snapshots(snapshots)
                    for snapshot in snapshots:
                        snapshot.status = fields.SnapshotStatus.ERROR
                        snapshot.save()

        for snapshot in snapshots:
            # Get reservations
            try:
                reserve_opts = {'snapshots': -1}
                volume_ref = objects.Volume.get_by_id(context,
                                                      snapshot.volume_id)
                QUOTAS.add_volume_type_opts(context,
                                            reserve_opts,
                                            volume_ref.volume_type_id)
                reservations = QUOTAS.reserve(context,
                                              project_id=project_id,
                                              **reserve_opts)

            except Exception:
                reservations = None
                LOG.exception("Failed to update usages deleting snapshot")

            self.db.volume_glance_metadata_delete_by_snapshot(context,
                                                              snapshot.id)
            snapshot.destroy()

            # Commit the reservations
            if reservations:
                QUOTAS.commit(context, reservations, project_id=project_id)

        group_snapshot.destroy()
        LOG.info("group_snapshot %s: deleted successfully",
                 group_snapshot.id)
        self._notify_about_group_snapshot_usage(context, group_snapshot,
                                                "delete.end",
                                                snapshots)

    def update_migrated_volume(self, ctxt, volume, new_volume, volume_status):
        """Finalize migration process on backend device."""
        model_update = None
        model_update_default = {'_name_id': new_volume.name_id,
                                'provider_location':
                                new_volume.provider_location}
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
                            for metadata in volume.volume_metadata}
                elif key == 'admin_metadata':
                    model_update_new[key] = {
                        metadata['key']: metadata['value']
                        for metadata in volume.volume_admin_metadata}
                else:
                    model_update_new[key] = volume[key]
            with new_volume.obj_as_admin():
                new_volume.update(model_update_new)
                new_volume.save()
        with volume.obj_as_admin():
                volume.update(model_update_default)
                volume.save()

    # Replication V2.1 and a/a method
    def failover(self, context, secondary_backend_id=None):
        """Failover a backend to a secondary replication target.

        Instructs a replication capable/configured backend to failover
        to one of it's secondary replication targets. host=None is
        an acceetable input, and leaves it to the driver to failover
        to the only configured target, or to choose a target on it's
        own. All of the hosts volumes will be passed on to the driver
        in order for it to determine the replicated volumes on the host,
        if needed.

        :param context: security context
        :param secondary_backend_id: Specifies backend_id to fail over to
        """
        updates = {}
        repl_status = fields.ReplicationStatus

        svc_host = vol_utils.extract_host(self.host, 'backend')
        service = objects.Service.get_by_args(context, svc_host,
                                              constants.VOLUME_BINARY)

        # TODO(geguileo): We should optimize these updates by doing them
        # directly on the DB with just 3 queries, one to change the volumes
        # another to change all the snapshots, and another to get replicated
        # volumes.

        # Change non replicated volumes and their snapshots to error if we are
        # failing over, leave them as they are for failback
        volumes = self._get_my_volumes(context)

        replicated_vols = []
        for volume in volumes:
            if volume.replication_status not in (repl_status.DISABLED,
                                                 repl_status.NOT_CAPABLE):
                replicated_vols.append(volume)
            elif secondary_backend_id != self.FAILBACK_SENTINEL:
                volume.previous_status = volume.status
                volume.status = 'error'
                volume.replication_status = repl_status.NOT_CAPABLE
                volume.save()

                for snapshot in volume.snapshots:
                    snapshot.status = fields.SnapshotStatus.ERROR
                    snapshot.save()

        volume_update_list = None
        group_update_list = None
        try:
            # For non clustered we can call v2.1 failover_host, but for
            # clustered we call a/a failover method.  We know a/a method
            # exists because BaseVD class wouldn't have started if it didn't.
            failover = getattr(self.driver,
                               'failover' if service.is_clustered
                               else 'failover_host')
            # expected form of volume_update_list:
            # [{volume_id: <cinder-volid>, updates: {'provider_id': xxxx....}},
            #  {volume_id: <cinder-volid>, updates: {'provider_id': xxxx....}}]
            # It includes volumes in replication groups and those not in them
            # expected form of group_update_list:
            # [{group_id: <cinder-grpid>, updates: {'xxxx': xxxx....}},
            #  {group_id: <cinder-grpid>, updates: {'xxxx': xxxx....}}]
            filters = self._get_cluster_or_host_filters()
            groups = objects.GroupList.get_all_replicated(context,
                                                          filters=filters)
            active_backend_id, volume_update_list, group_update_list = (
                failover(context,
                         replicated_vols,
                         secondary_id=secondary_backend_id,
                         groups=groups))
            try:
                update_data = {u['volume_id']: u['updates']
                               for u in volume_update_list}
            except KeyError:
                msg = "Update list, doesn't include volume_id"
                raise exception.ProgrammingError(reason=msg)
            try:
                update_group_data = {g['group_id']: g['updates']
                                     for g in group_update_list}
            except KeyError:
                msg = "Update list, doesn't include group_id"
                raise exception.ProgrammingError(reason=msg)
        except Exception as exc:
            # NOTE(jdg): Drivers need to be aware if they fail during
            # a failover sequence, we're expecting them to cleanup
            # and make sure the driver state is such that the original
            # backend is still set as primary as per driver memory

            # We don't want to log the exception trace invalid replication
            # target
            if isinstance(exc, exception.InvalidReplicationTarget):
                log_method = LOG.error
                # Preserve the replication_status: Status should be failed over
                # if we were failing back or if we were failing over from one
                # secondary to another secondary. In both cases
                # active_backend_id will be set.
                if service.active_backend_id:
                    updates['replication_status'] = repl_status.FAILED_OVER
                else:
                    updates['replication_status'] = repl_status.ENABLED
            else:
                log_method = LOG.exception
                updates.update(disabled=True,
                               replication_status=repl_status.FAILOVER_ERROR)

            log_method("Error encountered during failover on host: %(host)s "
                       "to %(backend_id)s: %(error)s",
                       {'host': self.host, 'backend_id': secondary_backend_id,
                        'error': exc})
            # We dump the update list for manual recovery
            LOG.error('Failed update_list is: %s', volume_update_list)
            self.finish_failover(context, service, updates)
            return

        if secondary_backend_id == "default":
            updates['replication_status'] = repl_status.ENABLED
            updates['active_backend_id'] = ''
            updates['disabled'] = service.frozen
            updates['disabled_reason'] = 'frozen' if service.frozen else ''
        else:
            updates['replication_status'] = repl_status.FAILED_OVER
            updates['active_backend_id'] = active_backend_id
            updates['disabled'] = True
            updates['disabled_reason'] = 'failed-over'

        self.finish_failover(context, service, updates)

        for volume in replicated_vols:
            update = update_data.get(volume.id, {})
            if update.get('status', '') == 'error':
                update['replication_status'] = repl_status.FAILOVER_ERROR
            elif update.get('replication_status') in (None,
                                                      repl_status.FAILED_OVER):
                update['replication_status'] = updates['replication_status']

            if update['replication_status'] == repl_status.FAILOVER_ERROR:
                update.setdefault('status', 'error')
                # Set all volume snapshots to error
                for snapshot in volume.snapshots:
                    snapshot.status = fields.SnapshotStatus.ERROR
                    snapshot.save()
            if 'status' in update:
                update['previous_status'] = volume.status
            volume.update(update)
            volume.save()

        for grp in groups:
            update = update_group_data.get(grp.id, {})
            if update.get('status', '') == 'error':
                update['replication_status'] = repl_status.FAILOVER_ERROR
            elif update.get('replication_status') in (None,
                                                      repl_status.FAILED_OVER):
                update['replication_status'] = updates['replication_status']

            if update['replication_status'] == repl_status.FAILOVER_ERROR:
                update.setdefault('status', 'error')
            grp.update(update)
            grp.save()

        LOG.info("Failed over to replication target successfully.")

    # TODO(geguileo): In P - remove this
    failover_host = failover

    def finish_failover(self, context, service, updates):
        """Completion of the failover locally or via RPC."""
        # If the service is clustered, broadcast the service changes to all
        # volume services, including this one.
        if service.is_clustered:
            # We have to update the cluster with the same data, and we do it
            # before broadcasting the failover_completed RPC call to prevent
            # races with services that may be starting..
            for key, value in updates.items():
                setattr(service.cluster, key, value)
            service.cluster.save()
            rpcapi = volume_rpcapi.VolumeAPI()
            rpcapi.failover_completed(context, service, updates)
        else:
            service.update(updates)
            service.save()

    def failover_completed(self, context, updates):
        """Finalize failover of this backend.

        When a service is clustered and replicated the failover has 2 stages,
        one that does the failover of the volumes and another that finalizes
        the failover of the services themselves.

        This method takes care of the last part and is called from the service
        doing the failover of the volumes after finished processing the
        volumes.
        """
        svc_host = vol_utils.extract_host(self.host, 'backend')
        service = objects.Service.get_by_args(context, svc_host,
                                              constants.VOLUME_BINARY)
        service.update(updates)
        try:
            self.driver.failover_completed(context, service.active_backend_id)
        except Exception:
            msg = _('Driver reported error during replication failover '
                    'completion.')
            LOG.exception(msg)
            service.disabled = True
            service.disabled_reason = msg
            service.replication_status = (
                fields.ReplicationStatus.ERROR)
        service.save()

    def freeze_host(self, context):
        """Freeze management plane on this backend.

        Basically puts the control/management plane into a
        Read Only state.  We should handle this in the scheduler,
        however this is provided to let the driver know in case it
        needs/wants to do something specific on the backend.

        :param context: security context
        """
        # TODO(jdg): Return from driver? or catch?
        # Update status column in service entry
        try:
            self.driver.freeze_backend(context)
        except exception.VolumeDriverException:
            # NOTE(jdg): In the case of freeze, we don't really
            # need the backend's consent or anything, we'll just
            # disable the service, so we can just log this and
            # go about our business
            LOG.warning('Error encountered on Cinder backend during '
                        'freeze operation, service is frozen, however '
                        'notification to driver has failed.')
        svc_host = vol_utils.extract_host(self.host, 'backend')

        service = objects.Service.get_by_args(
            context,
            svc_host,
            constants.VOLUME_BINARY)
        service.disabled = True
        service.disabled_reason = "frozen"
        service.save()
        LOG.info("Set backend status to frozen successfully.")
        return True

    def thaw_host(self, context):
        """UnFreeze management plane on this backend.

        Basically puts the control/management plane back into
        a normal state.  We should handle this in the scheduler,
        however this is provided to let the driver know in case it
        needs/wants to do something specific on the backend.

        :param context: security context
        """

        # TODO(jdg): Return from driver? or catch?
        # Update status column in service entry
        try:
            self.driver.thaw_backend(context)
        except exception.VolumeDriverException:
            # NOTE(jdg): Thaw actually matters, if this call
            # to the backend fails, we're stuck and can't re-enable
            LOG.error('Error encountered on Cinder backend during '
                      'thaw operation, service will remain frozen.')
            return False
        svc_host = vol_utils.extract_host(self.host, 'backend')

        service = objects.Service.get_by_args(
            context,
            svc_host,
            constants.VOLUME_BINARY)
        service.disabled = False
        service.disabled_reason = ""
        service.save()
        LOG.info("Thawed backend successfully.")
        return True

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
            LOG.exception("Failed to create manage_existing flow: "
                          "%(object_type)s %(object_id)s.",
                          {'object_type': 'snapshot',
                           'object_id': snapshot.id})
            raise exception.CinderException(
                _("Failed to create manage existing flow."))

        with flow_utils.DynamicLogListener(flow_engine, logger=LOG):
            flow_engine.run()
        return snapshot.id

    def get_manageable_snapshots(self, ctxt, marker, limit, offset,
                                 sort_keys, sort_dirs, want_objects=False):
        try:
            utils.require_driver_initialized(self.driver)
        except exception.DriverNotInitialized:
            with excutils.save_and_reraise_exception():
                LOG.exception("Listing manageable snapshots failed, due "
                              "to uninitialized driver.")

        cinder_snapshots = self._get_my_snapshots(ctxt)
        try:
            driver_entries = self.driver.get_manageable_snapshots(
                cinder_snapshots, marker, limit, offset, sort_keys, sort_dirs)
            if want_objects:
                driver_entries = (objects.ManageableSnapshotList.
                                  from_primitives(ctxt, driver_entries))
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Listing manageable snapshots failed, due "
                              "to driver error.")
        return driver_entries

    def get_capabilities(self, context, discover):
        """Get capabilities of backend storage."""
        if discover:
            self.driver.init_capabilities()
        capabilities = self.driver.capabilities
        LOG.debug("Obtained capabilities list: %s.", capabilities)
        return capabilities

    def get_backup_device(self, ctxt, backup, want_objects=False):
        (backup_device, is_snapshot) = (
            self.driver.get_backup_device(ctxt, backup))
        secure_enabled = self.driver.secure_file_operations_enabled()
        backup_device_dict = {'backup_device': backup_device,
                              'secure_enabled': secure_enabled,
                              'is_snapshot': is_snapshot, }
        # TODO(sborkows): from_primitive method will be removed in O, so there
        # is a need to clean here then.
        return (objects.BackupDeviceInfo.from_primitive(backup_device_dict,
                                                        ctxt)
                if want_objects else backup_device_dict)

    def secure_file_operations_enabled(self, ctxt, volume):
        secure_enabled = self.driver.secure_file_operations_enabled()
        return secure_enabled

    def _connection_create(self, ctxt, volume, attachment, connector):
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
            model_update = self.driver.create_export(ctxt.elevated(),
                                                     volume, connector)
        except exception.CinderException as ex:
            err_msg = (_("Create export for volume failed (%s).") % ex.msg)
            LOG.exception(err_msg, resource=volume)
            raise exception.VolumeBackendAPIException(data=err_msg)

        try:
            if model_update:
                volume.update(model_update)
                volume.save()
        except exception.CinderException as ex:
            LOG.exception("Model update failed.", resource=volume)
            raise exception.ExportFailure(reason=six.text_type(ex))

        try:
            conn_info = self.driver.initialize_connection(volume, connector)
        except Exception as err:
            err_msg = (_("Driver initialize connection failed "
                         "(error: %(err)s).") % {'err': six.text_type(err)})
            LOG.exception(err_msg, resource=volume)
            self.driver.remove_export(ctxt.elevated(), volume)
            raise exception.VolumeBackendAPIException(data=err_msg)
        conn_info = self._parse_connection_options(ctxt, volume, conn_info)

        # NOTE(jdg): Get rid of the nested dict (data key)
        conn_data = conn_info.pop('data', {})
        connection_info = conn_data.copy()
        connection_info.update(conn_info)
        values = {'volume_id': volume.id,
                  'attach_status': 'attaching', }

        self.db.volume_attachment_update(ctxt, attachment.id, values)
        self.db.attachment_specs_update_or_create(
            ctxt,
            attachment.id,
            connector)

        connection_info['attachment_id'] = attachment.id
        return connection_info

    def attachment_update(self,
                          context,
                          vref,
                          connector,
                          attachment_id):
        """Update/Finalize an attachment.

        This call updates a valid attachment record to associate with a volume
        and provide the caller with the proper connection info.  Note that
        this call requires an `attachment_ref`.  It's expected that prior to
        this call that the volume and an attachment UUID has been reserved.

        param: vref: Volume object to create attachment for
        param: connector: Connector object to use for attachment creation
        param: attachment_ref: ID of the attachment record to update
        """

        mode = connector.get('mode', 'rw')
        self._notify_about_volume_usage(context, vref, 'attach.start')
        attachment_ref = objects.VolumeAttachment.get_by_id(context,
                                                            attachment_id)
        connection_info = self._connection_create(context,
                                                  vref,
                                                  attachment_ref,
                                                  connector)
        # FIXME(jdg): get rid of this admin_meta option here, the only thing
        # it does is enforce that a volume is R/O, that should be done via a
        # type and not *more* metadata
        volume_metadata = self.db.volume_admin_metadata_update(
            context.elevated(),
            attachment_ref.volume_id,
            {'attached_mode': mode}, False)

        try:
            if volume_metadata.get('readonly') == 'True' and mode != 'ro':
                raise exception.InvalidVolumeAttachMode(mode=mode,
                                                        volume_id=vref.id)
            utils.require_driver_initialized(self.driver)
            self.driver.attach_volume(context,
                                      vref,
                                      attachment_ref.instance_uuid,
                                      connector.get('host', ''),
                                      connector.get('mountpoint', 'na'))
        except Exception as err:
            self.message_api.create(
                context, message_field.Action.UPDATE_ATTACHMENT,
                resource_uuid=vref.id,
                exception=err)
            with excutils.save_and_reraise_exception():
                self.db.volume_attachment_update(
                    context, attachment_ref.id,
                    {'attach_status':
                     fields.VolumeAttachStatus.ERROR_ATTACHING})

        self.db.volume_attached(context.elevated(),
                                attachment_ref.id,
                                attachment_ref.instance_uuid,
                                connector.get('host', ''),
                                connector.get('mountpoint', 'na'),
                                mode)
        vref.refresh()
        self._notify_about_volume_usage(context, vref, "attach.end")
        LOG.info("Attach volume completed successfully.",
                 resource=vref)
        attachment_ref = objects.VolumeAttachment.get_by_id(context,
                                                            attachment_id)
        return connection_info

    def _connection_terminate(self, context, volume,
                              attachment, force=False):
        """Remove a volume connection, but leave attachment."""
        utils.require_driver_initialized(self.driver)

        # TODO(jdg): Add an object method to cover this
        connector = self.db.attachment_specs_get(
            context,
            attachment.id)

        try:
            shared_connections = self.driver.terminate_connection(volume,
                                                                  connector,
                                                                  force=force)
            if not isinstance(shared_connections, bool):
                shared_connections = False

        except Exception as err:
            err_msg = (_('Terminate volume connection failed: %(err)s')
                       % {'err': six.text_type(err)})
            LOG.exception(err_msg, resource=volume)
            raise exception.VolumeBackendAPIException(data=err_msg)
        LOG.info("Terminate volume connection completed successfully.",
                 resource=volume)
        # NOTE(jdg): Return True/False if there are other outstanding
        # attachments that share this connection.  If True should signify
        # caller to preserve the actual host connection (work should be
        # done in the brick connector as it has the knowledge of what's
        # going on here.
        return shared_connections

    def attachment_delete(self, context, attachment_id, vref):
        """Delete/Detach the specified attachment.

        Notifies the backend device that we're detaching the specified
        attachment instance.

        param: vref: Volume object associated with the attachment
        param: attachment: Attachment reference object to remove

        NOTE if the attachment reference is None, we remove all existing
        attachments for the specified volume object.
        """
        attachment_ref = objects.VolumeAttachment.get_by_id(context,
                                                            attachment_id)
        if not attachment_ref:
            for attachment in VA_LIST.get_all_by_volume_id(context, vref.id):
                self._do_attachment_delete(context, vref, attachment)
        else:
            self._do_attachment_delete(context, vref, attachment_ref)

    def _do_attachment_delete(self, context, vref, attachment):
        utils.require_driver_initialized(self.driver)
        self._notify_about_volume_usage(context, vref, "detach.start")
        has_shared_connection = self._connection_terminate(context,
                                                           vref,
                                                           attachment)
        try:
            LOG.debug('Deleting attachment %(attachment_id)s.',
                      {'attachment_id': attachment.id},
                      resource=vref)
            self.driver.detach_volume(context, vref, attachment)
            if not has_shared_connection:
                self.driver.remove_export(context.elevated(), vref)
        except Exception:
            # FIXME(jdg): Obviously our volume object is going to need some
            # changes to deal with multi-attach and figuring out how to
            # represent a single failed attach out of multiple attachments

            # TODO(jdg): object method here
            self.db.volume_attachment_update(
                context, attachment.get('id'),
                {'attach_status': 'error_detaching'})
        else:
            self.db.volume_detached(context.elevated(), vref.id,
                                    attachment.get('id'))
            self.db.volume_admin_metadata_delete(context.elevated(),
                                                 vref.id,
                                                 'attached_mode')
        self._notify_about_volume_usage(context, vref, "detach.end")

    # Replication group API (Tiramisu)
    def enable_replication(self, ctxt, group):
        """Enable replication."""
        group.refresh()
        if group.replication_status != fields.ReplicationStatus.ENABLING:
            msg = _("Replication status in group %s is not "
                    "enabling. Cannot enable replication.") % group.id
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        volumes = group.volumes
        for vol in volumes:
            vol.refresh()
            if vol.replication_status != fields.ReplicationStatus.ENABLING:
                msg = _("Replication status in volume %s is not "
                        "enabling. Cannot enable replication.") % vol.id
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

        self._notify_about_group_usage(
            ctxt, group, "enable_replication.start")

        volumes_model_update = None
        model_update = None
        try:
            utils.require_driver_initialized(self.driver)

            model_update, volumes_model_update = (
                self.driver.enable_replication(ctxt, group, volumes))

            if volumes_model_update:
                for update in volumes_model_update:
                    vol_obj = objects.Volume.get_by_id(ctxt, update['id'])
                    vol_obj.update(update)
                    vol_obj.save()
                    # If we failed to enable a volume, make sure the status
                    # for the group is set to error as well
                    if (update.get('replication_status') ==
                            fields.ReplicationStatus.ERROR and
                            model_update.get('replication_status') !=
                            fields.ReplicationStatus.ERROR):
                        model_update['replication_status'] = update.get(
                            'replication_status')

            if model_update:
                if (model_update.get('replication_status') ==
                        fields.ReplicationStatus.ERROR):
                    msg = _('Enable replication failed.')
                    LOG.error(msg,
                              resource={'type': 'group',
                                        'id': group.id})
                    raise exception.VolumeDriverException(message=msg)
                else:
                    group.update(model_update)
                    group.save()

        except exception.CinderException as ex:
            group.status = fields.GroupStatus.ERROR
            group.replication_status = fields.ReplicationStatus.ERROR
            group.save()
            # Update volume status to 'error' if driver returns
            # None for volumes_model_update.
            if not volumes_model_update:
                for vol in volumes:
                    vol.status = 'error'
                    vol.replication_status = fields.ReplicationStatus.ERROR
                    vol.save()
            err_msg = _("Enable replication group failed: "
                        "%s.") % six.text_type(ex)
            raise exception.ReplicationGroupError(reason=err_msg,
                                                  group_id=group.id)

        for vol in volumes:
            vol.replication_status = fields.ReplicationStatus.ENABLED
            vol.save()
        group.replication_status = fields.ReplicationStatus.ENABLED
        group.save()

        self._notify_about_group_usage(
            ctxt, group, "enable_replication.end", volumes)
        LOG.info("Enable replication completed successfully.",
                 resource={'type': 'group',
                           'id': group.id})

    # Replication group API (Tiramisu)
    def disable_replication(self, ctxt, group):
        """Disable replication."""
        group.refresh()
        if group.replication_status != fields.ReplicationStatus.DISABLING:
            msg = _("Replication status in group %s is not "
                    "disabling. Cannot disable replication.") % group.id
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        volumes = group.volumes
        for vol in volumes:
            vol.refresh()
            if (vol.replication_status !=
                    fields.ReplicationStatus.DISABLING):
                msg = _("Replication status in volume %s is not "
                        "disabling. Cannot disable replication.") % vol.id
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

        self._notify_about_group_usage(
            ctxt, group, "disable_replication.start")

        volumes_model_update = None
        model_update = None
        try:
            utils.require_driver_initialized(self.driver)

            model_update, volumes_model_update = (
                self.driver.disable_replication(ctxt, group, volumes))

            if volumes_model_update:
                for update in volumes_model_update:
                    vol_obj = objects.Volume.get_by_id(ctxt, update['id'])
                    vol_obj.update(update)
                    vol_obj.save()
                    # If we failed to enable a volume, make sure the status
                    # for the group is set to error as well
                    if (update.get('replication_status') ==
                            fields.ReplicationStatus.ERROR and
                            model_update.get('replication_status') !=
                            fields.ReplicationStatus.ERROR):
                        model_update['replication_status'] = update.get(
                            'replication_status')

            if model_update:
                if (model_update.get('replication_status') ==
                        fields.ReplicationStatus.ERROR):
                    msg = _('Disable replication failed.')
                    LOG.error(msg,
                              resource={'type': 'group',
                                        'id': group.id})
                    raise exception.VolumeDriverException(message=msg)
                else:
                    group.update(model_update)
                    group.save()

        except exception.CinderException as ex:
            group.status = fields.GroupStatus.ERROR
            group.replication_status = fields.ReplicationStatus.ERROR
            group.save()
            # Update volume status to 'error' if driver returns
            # None for volumes_model_update.
            if not volumes_model_update:
                for vol in volumes:
                    vol.status = 'error'
                    vol.replication_status = fields.ReplicationStatus.ERROR
                    vol.save()
            err_msg = _("Disable replication group failed: "
                        "%s.") % six.text_type(ex)
            raise exception.ReplicationGroupError(reason=err_msg,
                                                  group_id=group.id)

        for vol in volumes:
            vol.replication_status = fields.ReplicationStatus.DISABLED
            vol.save()
        group.replication_status = fields.ReplicationStatus.DISABLED
        group.save()

        self._notify_about_group_usage(
            ctxt, group, "disable_replication.end", volumes)
        LOG.info("Disable replication completed successfully.",
                 resource={'type': 'group',
                           'id': group.id})

    # Replication group API (Tiramisu)
    def failover_replication(self, ctxt, group, allow_attached_volume=False,
                             secondary_backend_id=None):
        """Failover replication."""
        group.refresh()
        if group.replication_status != fields.ReplicationStatus.FAILING_OVER:
            msg = _("Replication status in group %s is not "
                    "failing-over. Cannot failover replication.") % group.id
            LOG.error(msg)
            raise exception.InvalidGroup(reason=msg)

        volumes = group.volumes
        for vol in volumes:
            vol.refresh()
            if vol.status == 'in-use' and not allow_attached_volume:
                msg = _("Volume %s is attached but allow_attached_volume flag "
                        "is False. Cannot failover replication.") % vol.id
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)
            if (vol.replication_status !=
                    fields.ReplicationStatus.FAILING_OVER):
                msg = _("Replication status in volume %s is not "
                        "failing-over. Cannot failover replication.") % vol.id
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)

        self._notify_about_group_usage(
            ctxt, group, "failover_replication.start")

        volumes_model_update = None
        model_update = None
        try:
            utils.require_driver_initialized(self.driver)

            model_update, volumes_model_update = (
                self.driver.failover_replication(
                    ctxt, group, volumes, secondary_backend_id))

            if volumes_model_update:
                for update in volumes_model_update:
                    vol_obj = objects.Volume.get_by_id(ctxt, update['id'])
                    vol_obj.update(update)
                    vol_obj.save()
                    # If we failed to enable a volume, make sure the status
                    # for the group is set to error as well
                    if (update.get('replication_status') ==
                            fields.ReplicationStatus.ERROR and
                            model_update.get('replication_status') !=
                            fields.ReplicationStatus.ERROR):
                        model_update['replication_status'] = update.get(
                            'replication_status')

            if model_update:
                if (model_update.get('replication_status') ==
                        fields.ReplicationStatus.ERROR):
                    msg = _('Failover replication failed.')
                    LOG.error(msg,
                              resource={'type': 'group',
                                        'id': group.id})
                    raise exception.VolumeDriverException(message=msg)
                else:
                    group.update(model_update)
                    group.save()

        except exception.CinderException as ex:
            group.status = fields.GroupStatus.ERROR
            group.replication_status = fields.ReplicationStatus.ERROR
            group.save()
            # Update volume status to 'error' if driver returns
            # None for volumes_model_update.
            if not volumes_model_update:
                for vol in volumes:
                    vol.status = 'error'
                    vol.replication_status = fields.ReplicationStatus.ERROR
                    vol.save()
            err_msg = _("Failover replication group failed: "
                        "%s.") % six.text_type(ex)
            raise exception.ReplicationGroupError(reason=err_msg,
                                                  group_id=group.id)

        for vol in volumes:
            if secondary_backend_id == "default":
                vol.replication_status = fields.ReplicationStatus.ENABLED
            else:
                vol.replication_status = (
                    fields.ReplicationStatus.FAILED_OVER)
            vol.save()
        if secondary_backend_id == "default":
            group.replication_status = fields.ReplicationStatus.ENABLED
        else:
            group.replication_status = fields.ReplicationStatus.FAILED_OVER
        group.save()

        self._notify_about_group_usage(
            ctxt, group, "failover_replication.end", volumes)
        LOG.info("Failover replication completed successfully.",
                 resource={'type': 'group',
                           'id': group.id})

    def list_replication_targets(self, ctxt, group):
        """Provide a means to obtain replication targets for a group.

        This method is used to find the replication_device config
        info. 'backend_id' is a required key in 'replication_device'.

        Response Example for admin:

        .. code:: json

          {
              'replication_targets': [
                  {
                      'backend_id': 'vendor-id-1',
                      'unique_key': 'val1',
                      ......
                  },
                  {
                      'backend_id': 'vendor-id-2',
                      'unique_key': 'val2',
                      ......
                  }
               ]
          }

        Response example for non-admin:

        .. code json

          {
              'replication_targets': [
                  {
                      'backend_id': 'vendor-id-1'
                  },
                  {
                      'backend_id': 'vendor-id-2'
                  }
               ]
          }

        """

        replication_targets = []
        try:
            group = objects.Group.get_by_id(ctxt, group.id)
            if self.configuration.replication_device:
                if ctxt.is_admin:
                    for rep_dev in self.configuration.replication_device:
                        keys = rep_dev.keys()
                        dev = {}
                        for k in keys:
                            dev[k] = rep_dev[k]
                        replication_targets.append(dev)
                else:
                    for rep_dev in self.configuration.replication_device:
                        dev = rep_dev.get('backend_id')
                        if dev:
                            replication_targets.append({'backend_id': dev})

        except exception.GroupNotFound:
            err_msg = (_("Get replication targets failed. Group %s not "
                         "found.") % group.id)
            LOG.exception(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        return {'replication_targets': replication_targets}
