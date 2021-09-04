# Copyright (c) 2010 OpenStack Foundation
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
Scheduler Service
"""

import collections
from datetime import datetime
import functools

import eventlet
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import periodic_task
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import timeutils
from oslo_utils import versionutils

from cinder.backup import rpcapi as backup_rpcapi
from cinder import context
from cinder import db
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _
from cinder import manager
from cinder.message import api as mess_api
from cinder.message import message_field
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder import rpc
from cinder.scheduler.flows import create_volume
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import volume_utils as vol_utils


scheduler_manager_opts = [
    cfg.StrOpt('scheduler_driver',
               default='cinder.scheduler.filter_scheduler.'
                       'FilterScheduler',
               help='Default scheduler driver to use'),
    cfg.IntOpt('scheduler_driver_init_wait_time',
               default=60,
               min=1,
               help='Maximum time in seconds to wait for the driver to '
                    'report as ready'),
]

CONF = cfg.CONF
CONF.register_opts(scheduler_manager_opts)

QUOTAS = quota.QUOTAS

LOG = logging.getLogger(__name__)


def append_operation_type(name=None):
    def _decorator(schedule_function):
        @functools.wraps(schedule_function)
        def inject_operation_decorator(*args, **kwargs):

            request_spec = kwargs.get('request_spec', None)
            request_spec_list = kwargs.get('request_spec_list', None)
            if request_spec:
                request_spec['operation'] = name or schedule_function.__name__
            if request_spec_list:
                for rs in request_spec_list:
                    rs['operation'] = name or schedule_function.__name__
            return schedule_function(*args, **kwargs)
        return inject_operation_decorator
    return _decorator


class SchedulerManager(manager.CleanableManager, manager.Manager):
    """Chooses a host to create volumes."""

    RPC_API_VERSION = scheduler_rpcapi.SchedulerAPI.RPC_API_VERSION

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, scheduler_driver=None, service_name=None,
                 *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = CONF.scheduler_driver
        self.driver = importutils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(*args, **kwargs)
        self._startup_delay = True
        self.backup_api = backup_rpcapi.BackupAPI()
        self.volume_api = volume_rpcapi.VolumeAPI()
        self.sch_api = scheduler_rpcapi.SchedulerAPI()
        self.message_api = mess_api.API()
        self.rpc_api_version = versionutils.convert_version_to_int(
            self.RPC_API_VERSION)

    def init_host_with_rpc(self):
        ctxt = context.get_admin_context()
        self.request_service_capabilities(ctxt)

        for __ in range(CONF.scheduler_driver_init_wait_time):
            if self.driver.is_first_receive():
                break
            eventlet.sleep(1)
        self._startup_delay = False

    def reset(self):
        super(SchedulerManager, self).reset()
        self.volume_api = volume_rpcapi.VolumeAPI()
        self.sch_api = scheduler_rpcapi.SchedulerAPI()
        self.driver.reset()

    @periodic_task.periodic_task(spacing=CONF.message_reap_interval,
                                 run_immediately=True)
    def _clean_expired_messages(self, context):
        self.message_api.cleanup_expired_messages(context)

    @periodic_task.periodic_task(spacing=CONF.reservation_clean_interval,
                                 run_immediately=True)
    def _clean_expired_reservation(self, context):
        QUOTAS.expire(context)

    def update_service_capabilities(self, context, service_name=None,
                                    host=None, capabilities=None,
                                    cluster_name=None, timestamp=None,
                                    **kwargs):
        """Process a capability update from a service node."""
        if capabilities is None:
            capabilities = {}
        # If we received the timestamp we have to deserialize it
        elif timestamp:
            timestamp = datetime.strptime(timestamp,
                                          timeutils.PERFECT_TIME_FORMAT)

        self.driver.update_service_capabilities(service_name,
                                                host,
                                                capabilities,
                                                cluster_name,
                                                timestamp)

    def notify_service_capabilities(self, context, service_name,
                                    capabilities, host=None, backend=None,
                                    timestamp=None):
        """Process a capability update from a service node."""
        # TODO(geguileo): On v4 remove host field.
        if capabilities is None:
            capabilities = {}
        # If we received the timestamp we have to deserialize it
        elif timestamp:
            timestamp = datetime.strptime(timestamp,
                                          timeutils.PERFECT_TIME_FORMAT)
        backend = backend or host
        self.driver.notify_service_capabilities(service_name,
                                                backend,
                                                capabilities,
                                                timestamp)

    def _wait_for_scheduler(self):
        # NOTE(dulek): We're waiting for scheduler to announce that it's ready
        # or CONF.scheduler_driver_init_wait_time seconds from service startup
        # has passed.
        while self._startup_delay and not self.driver.is_ready():
            eventlet.sleep(1)

    @append_operation_type()
    def create_group(self, context, group, group_spec=None,
                     group_filter_properties=None, request_spec_list=None,
                     filter_properties_list=None):
        self._wait_for_scheduler()
        try:
            self.driver.schedule_create_group(
                context, group,
                group_spec,
                request_spec_list,
                group_filter_properties,
                filter_properties_list)
        except exception.NoValidBackend:
            LOG.error("Could not find a backend for group "
                      "%(group_id)s.",
                      {'group_id': group.id})
            group.status = fields.GroupStatus.ERROR
            group.save()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Failed to create generic group "
                              "%(group_id)s.",
                              {'group_id': group.id})
                group.status = fields.GroupStatus.ERROR
                group.save()

    @objects.Volume.set_workers
    @append_operation_type()
    def create_volume(self, context, volume, snapshot_id=None, image_id=None,
                      request_spec=None, filter_properties=None,
                      backup_id=None):
        self._wait_for_scheduler()

        try:
            flow_engine = create_volume.get_flow(context,
                                                 self.driver,
                                                 request_spec,
                                                 filter_properties,
                                                 volume,
                                                 snapshot_id,
                                                 image_id,
                                                 backup_id)
        except Exception:
            msg = _("Failed to create scheduler manager volume flow")
            LOG.exception(msg)
            raise exception.CinderException(msg)

        with flow_utils.DynamicLogListener(flow_engine, logger=LOG):
            flow_engine.run()

    @append_operation_type()
    def create_snapshot(self, ctxt, volume, snapshot, backend,
                        request_spec=None, filter_properties=None):
        """Create snapshot for a volume.

        The main purpose of this method is to check if target
        backend (of volume and snapshot) has sufficient capacity
        to host to-be-created snapshot.
        """
        self._wait_for_scheduler()

        try:
            tgt_backend = self.driver.backend_passes_filters(
                ctxt, backend, request_spec, filter_properties)
            tgt_backend.consume_from_volume(
                {'size': request_spec['volume_properties']['size']})
        except exception.NoValidBackend as ex:
            self._set_snapshot_state_and_notify('create_snapshot',
                                                snapshot,
                                                fields.SnapshotStatus.ERROR,
                                                ctxt, ex, request_spec)
        else:
            volume_rpcapi.VolumeAPI().create_snapshot(ctxt, volume,
                                                      snapshot)

    def _do_cleanup(self,
                    ctxt: context.RequestContext,
                    vo_resource: 'objects.base.CinderObject'):
        # We can only receive cleanup requests for volumes, but we check anyway
        # We need to cleanup the volume status for cases where the scheduler
        # died while scheduling the volume creation.
        if (isinstance(vo_resource, objects.Volume) and
                vo_resource.status == 'creating'):
            vo_resource.status = 'error'
            vo_resource.save()

    def request_service_capabilities(self,
                                     context: context.RequestContext) -> None:
        volume_rpcapi.VolumeAPI().publish_service_capabilities(context)
        try:
            self.backup_api.publish_service_capabilities(context)
        except exception.ServiceTooOld as e:
            # cinder-backup has publish_service_capabilities starting Stein
            # release only.
            msg = ("Failed to notify about cinder-backup service "
                   "capabilities for host %(host)s. This is normal "
                   "during a live upgrade. Error: %(e)s")
            LOG.warning(msg, {'host': self.host, 'e': e})

    @append_operation_type()
    def migrate_volume(self,
                       context: context.RequestContext,
                       volume: objects.Volume,
                       backend: str, force_copy: bool,
                       request_spec, filter_properties) -> None:
        """Ensure that the backend exists and can accept the volume."""
        self._wait_for_scheduler()

        def _migrate_volume_set_error(self, context, ex, request_spec):
            if volume.status == 'maintenance':
                previous_status = (
                    volume.previous_status or 'maintenance')
                volume_state = {'volume_state': {'migration_status': 'error',
                                                 'status': previous_status}}
            else:
                volume_state = {'volume_state': {'migration_status': 'error'}}
            self._set_volume_state_and_notify('migrate_volume_to_host',
                                              volume_state,
                                              context, ex, request_spec)

        try:
            tgt_backend = self.driver.backend_passes_filters(context, backend,
                                                             request_spec,
                                                             filter_properties)
        except exception.NoValidBackend as ex:
            _migrate_volume_set_error(self, context, ex, request_spec)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                _migrate_volume_set_error(self, context, ex, request_spec)
        else:
            volume_rpcapi.VolumeAPI().migrate_volume(context, volume,
                                                     tgt_backend,
                                                     force_copy)

    # FIXME(geguileo): Remove this in v4.0 of RPC API.
    def migrate_volume_to_host(self, context, volume, host, force_host_copy,
                               request_spec, filter_properties=None):
        return self.migrate_volume(context, volume, host, force_host_copy,
                                   request_spec, filter_properties)

    @append_operation_type(name='retype_volume')
    def retype(self, context, volume, request_spec, filter_properties=None):
        """Schedule the modification of a volume's type.

        :param context: the request context
        :param volume: the volume object to retype
        :param request_spec: parameters for this retype request
        :param filter_properties: parameters to filter by
        """

        self._wait_for_scheduler()

        def _retype_volume_set_error(self, context, ex, request_spec,
                                     volume_ref, reservations, msg=None):
            if reservations:
                QUOTAS.rollback(context, reservations)
            previous_status = (
                volume_ref.previous_status or volume_ref.status)
            volume_state = {'volume_state': {'status': previous_status}}
            self._set_volume_state_and_notify('retype', volume_state,
                                              context, ex, request_spec, msg)

        reservations = request_spec.get('quota_reservations')
        old_reservations = request_spec.get('old_reservations', None)
        new_type = request_spec.get('volume_type')
        if new_type is None:
            msg = _('New volume type not specified in request_spec.')
            ex = exception.ParameterNotFound(param='volume_type')
            _retype_volume_set_error(self, context, ex, request_spec,
                                     volume, reservations, msg)

        # Default migration policy is 'never'
        migration_policy = request_spec.get('migration_policy')
        if not migration_policy:
            migration_policy = 'never'

        try:
            tgt_backend = self.driver.find_retype_backend(context,
                                                          request_spec,
                                                          filter_properties,
                                                          migration_policy)
        except Exception as ex:
            # Not having a valid host is an expected exception, so we don't
            # reraise on it.
            reraise = not isinstance(ex, exception.NoValidBackend)
            with excutils.save_and_reraise_exception(reraise=reraise):
                _retype_volume_set_error(self, context, ex, request_spec,
                                         volume, reservations)
        else:
            volume_rpcapi.VolumeAPI().retype(context, volume,
                                             new_type['id'], tgt_backend,
                                             migration_policy,
                                             reservations,
                                             old_reservations)

    @append_operation_type()
    def manage_existing(self, context, volume, request_spec,
                        filter_properties=None):
        """Ensure that the host exists and can accept the volume."""

        self._wait_for_scheduler()

        def _manage_existing_set_error(self, context, ex, request_spec):
            volume_state = {'volume_state': {'status': 'error_managing'}}
            self._set_volume_state_and_notify('manage_existing', volume_state,
                                              context, ex, request_spec)

        try:
            backend = self.driver.backend_passes_filters(
                context, volume.service_topic_queue, request_spec,
                filter_properties)

            # At the API we didn't have the pool info, so the volume DB entry
            # was created without it, now we add it.
            volume.host = backend.host
            volume.cluster_name = backend.cluster_name
            volume.save()

        except exception.NoValidBackend as ex:
            _manage_existing_set_error(self, context, ex, request_spec)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                _manage_existing_set_error(self, context, ex, request_spec)
        else:
            volume_rpcapi.VolumeAPI().manage_existing(context, volume,
                                                      request_spec.get('ref'))

    @append_operation_type()
    def manage_existing_snapshot(self, context, volume, snapshot, ref,
                                 request_spec, filter_properties=None):
        """Ensure that the host exists and can accept the snapshot."""

        self._wait_for_scheduler()

        try:
            backend = self.driver.backend_passes_filters(
                context, volume.service_topic_queue, request_spec,
                filter_properties)
            backend.consume_from_volume({'size': volume.size})

        except exception.NoValidBackend as ex:
            self._set_snapshot_state_and_notify('manage_existing_snapshot',
                                                snapshot,
                                                fields.SnapshotStatus.ERROR,
                                                context, ex, request_spec)
        else:
            volume_rpcapi.VolumeAPI().manage_existing_snapshot(
                context, snapshot, ref,
                volume.service_topic_queue)

    def get_pools(self, context, filters=None):
        """Get active pools from scheduler's cache.

        NOTE(dulek): There's no self._wait_for_scheduler() because get_pools is
        an RPC call (is blocking for the c-api). Also this is admin-only API
        extension so it won't hurt the user much to retry the request manually.
        """
        return self.driver.get_pools(context, filters)

    @append_operation_type(name='create_group')
    def validate_host_capacity(self, context, backend, request_spec,
                               filter_properties):
        try:
            backend_state = self.driver.backend_passes_filters(
                context,
                backend,
                request_spec, filter_properties)
            backend_state.consume_from_volume(
                {'size': request_spec['volume_properties']['size']})
        except exception.NoValidBackend:
            LOG.error("Desired host %(host)s does not have enough "
                      "capacity.", {'host': backend})
            return False
        return True

    @append_operation_type()
    def extend_volume(self, context, volume, new_size, reservations,
                      request_spec=None, filter_properties=None):

        def _extend_volume_set_error(self, context, ex, request_spec):
            volume_state = {'volume_state': {'status': volume.previous_status,
                                             'previous_status': None}}
            self._set_volume_state_and_notify('extend_volume', volume_state,
                                              context, ex, request_spec)

        if not filter_properties:
            filter_properties = {}

        filter_properties['new_size'] = new_size
        try:
            backend_state = self.driver.backend_passes_filters(
                context,
                volume.service_topic_queue,
                request_spec, filter_properties)
            backend_state.consume_from_volume(
                {'size': new_size - volume.size})
            volume_rpcapi.VolumeAPI().extend_volume(context, volume, new_size,
                                                    reservations)
        except exception.NoValidBackend as ex:
            QUOTAS.rollback(context, reservations,
                            project_id=volume.project_id)
            _extend_volume_set_error(self, context, ex, request_spec)
            self.message_api.create(
                context,
                message_field.Action.EXTEND_VOLUME,
                resource_uuid=volume.id,
                exception=ex)

    def _set_volume_state_and_notify(self, method, updates, context, ex,
                                     request_spec, msg=None):
        # TODO(harlowja): move into a task that just does this later.
        if not msg:
            msg = ("Failed to schedule_%(method)s: %(ex)s" %
                   {'method': method, 'ex': ex})
        LOG.error(msg)

        volume_state = updates['volume_state']
        properties = request_spec.get('volume_properties', {})

        volume_id = request_spec.get('volume_id', None)

        if volume_id:
            db.volume_update(context, volume_id, volume_state)

        if volume_state.get('status') == 'error_managing':
            volume_state['status'] = 'error'

        payload = dict(request_spec=request_spec,
                       volume_properties=properties,
                       volume_id=volume_id,
                       state=volume_state,
                       method=method,
                       reason=ex)

        rpc.get_notifier("scheduler").error(context,
                                            'scheduler.' + method,
                                            payload)

    def _set_snapshot_state_and_notify(self, method, snapshot, state,
                                       context, ex, request_spec,
                                       msg=None):
        if not msg:
            msg = ("Failed to schedule_%(method)s: %(ex)s" %
                   {'method': method, 'ex': ex})
        LOG.error(msg)

        model_update = dict(status=state)
        snapshot.update(model_update)
        snapshot.save()

        payload = dict(request_spec=request_spec,
                       snapshot_id=snapshot.id,
                       state=state,
                       method=method,
                       reason=ex)

        rpc.get_notifier("scheduler").error(context,
                                            'scheduler.' + method,
                                            payload)

    @property
    def upgrading_cloud(self):
        min_version_str = self.sch_api.determine_rpc_version_cap()
        min_version = versionutils.convert_version_to_int(min_version_str)
        return min_version < self.rpc_api_version

    def _cleanup_destination(self, clusters, service):
        """Determines the RPC method, destination service and name.

        The name is only used for logging, and it is the topic queue.
        """
        # For the scheduler we don't have a specific destination, as any
        # scheduler will do and we know we are up, since we are running this
        # code.
        if service.binary == 'cinder-scheduler':
            cleanup_rpc = self.sch_api.do_cleanup
            dest = None
            dest_name = service.host
        else:
            cleanup_rpc = self.volume_api.do_cleanup

            # For clustered volume services we try to get info from the cache.
            if service.is_clustered:
                # Get cluster info from cache
                dest = clusters[service.binary].get(service.cluster_name)
                # Cache miss forces us to get the cluster from the DB via OVO
                if not dest:
                    dest = service.cluster
                    clusters[service.binary][service.cluster_name] = dest
                dest_name = dest.name
            # Non clustered volume services
            else:
                dest = service
                dest_name = service.host
        return cleanup_rpc, dest, dest_name

    def work_cleanup(self, context, cleanup_request):
        """Process request from API to do cleanup on services.

        Here we retrieve from the DB which services we want to clean up based
        on the request from the user.

        Then send individual cleanup requests to each of the services that are
        up, and we finally return a tuple with services that we have sent a
        cleanup request and those that were not up and we couldn't send it.
        """
        if self.upgrading_cloud:
            raise exception.UnavailableDuringUpgrade(action='workers cleanup')

        LOG.info('Workers cleanup request started.')

        filters = dict(service_id=cleanup_request.service_id,
                       cluster_name=cleanup_request.cluster_name,
                       host=cleanup_request.host,
                       binary=cleanup_request.binary,
                       is_up=cleanup_request.is_up,
                       disabled=cleanup_request.disabled)
        # Get the list of all the services that match the request
        services = objects.ServiceList.get_all(context, filters)

        until = cleanup_request.until or timeutils.utcnow()
        requested = []
        not_requested = []

        # To reduce DB queries we'll cache the clusters data
        clusters: collections.defaultdict = collections.defaultdict(dict)

        for service in services:
            cleanup_request.cluster_name = service.cluster_name
            cleanup_request.service_id = service.id
            cleanup_request.host = service.host
            cleanup_request.binary = service.binary
            cleanup_request.until = until

            cleanup_rpc, dest, dest_name = self._cleanup_destination(clusters,
                                                                     service)

            # If it's a scheduler or the service is up, send the request.
            if not dest or dest.is_up:
                LOG.info('Sending cleanup for %(binary)s %(dest_name)s.',
                         {'binary': service.binary,
                          'dest_name': dest_name})
                cleanup_rpc(context, cleanup_request)
                requested.append(service)
            # We don't send cleanup requests when there are no services alive
            # to do the cleanup.
            else:
                LOG.info('No service available to cleanup %(binary)s '
                         '%(dest_name)s.',
                         {'binary': service.binary,
                          'dest_name': dest_name})
                not_requested.append(service)

        LOG.info('Cleanup requests completed.')
        return requested, not_requested

    def create_backup(self, context, backup):
        volume_id = backup.volume_id
        volume = self.db.volume_get(context, volume_id)
        try:
            host = self.driver.get_backup_host(volume)
            backup.host = host
            backup.save()
            self.backup_api.create_backup(context, backup)
        except exception.ServiceNotFound:
            self.db.volume_update(context, volume_id,
                                  {'status': volume['previous_status'],
                                   'previous_status': volume['status']})
            msg = "Service not found for creating backup."
            LOG.error(msg)
            vol_utils.update_backup_error(backup, msg)
            self.message_api.create(
                context,
                action=message_field.Action.BACKUP_CREATE,
                resource_type=message_field.Resource.VOLUME_BACKUP,
                resource_uuid=backup.id,
                detail=message_field.Detail.BACKUP_SCHEDULE_ERROR)
