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

import eventlet
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import excutils
from oslo_utils import importutils
import six

from cinder import context
from cinder import db
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _, _LE
from cinder import manager
from cinder import quota
from cinder import rpc
from cinder.scheduler.flows import create_volume
from cinder.volume import rpcapi as volume_rpcapi


scheduler_driver_opt = cfg.StrOpt('scheduler_driver',
                                  default='cinder.scheduler.filter_scheduler.'
                                          'FilterScheduler',
                                  help='Default scheduler driver to use')

CONF = cfg.CONF
CONF.register_opt(scheduler_driver_opt)

QUOTAS = quota.QUOTAS

LOG = logging.getLogger(__name__)


class SchedulerManager(manager.Manager):
    """Chooses a host to create volumes."""

    RPC_API_VERSION = '1.8'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, scheduler_driver=None, service_name=None,
                 *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = CONF.scheduler_driver
        self.driver = importutils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(*args, **kwargs)
        self._startup_delay = True

    def init_host_with_rpc(self):
        ctxt = context.get_admin_context()
        self.request_service_capabilities(ctxt)

        eventlet.sleep(CONF.periodic_interval)
        self._startup_delay = False

    def update_service_capabilities(self, context, service_name=None,
                                    host=None, capabilities=None, **kwargs):
        """Process a capability update from a service node."""
        if capabilities is None:
            capabilities = {}
        self.driver.update_service_capabilities(service_name,
                                                host,
                                                capabilities)

    def _wait_for_scheduler(self):
        # NOTE(dulek): We're waiting for scheduler to announce that it's ready
        # or CONF.periodic_interval seconds from service startup has passed.
        while self._startup_delay and not self.driver.is_ready():
            eventlet.sleep(1)

    def create_consistencygroup(self, context, topic,
                                group,
                                request_spec_list=None,
                                filter_properties_list=None):

        self._wait_for_scheduler()
        try:
            self.driver.schedule_create_consistencygroup(
                context, group,
                request_spec_list,
                filter_properties_list)
        except exception.NoValidHost:
            LOG.error(_LE("Could not find a host for consistency group "
                          "%(group_id)s."),
                      {'group_id': group.id})
            group.status = 'error'
            group.save()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Failed to create consistency group "
                                  "%(group_id)s."),
                              {'group_id': group.id})
                group.status = 'error'
                group.save()

    def create_volume(self, context, topic, volume_id, snapshot_id=None,
                      image_id=None, request_spec=None,
                      filter_properties=None):

        self._wait_for_scheduler()
        try:
            flow_engine = create_volume.get_flow(context,
                                                 db, self.driver,
                                                 request_spec,
                                                 filter_properties,
                                                 volume_id,
                                                 snapshot_id,
                                                 image_id)
        except Exception:
            msg = _("Failed to create scheduler manager volume flow")
            LOG.exception(msg)
            raise exception.CinderException(msg)

        with flow_utils.DynamicLogListener(flow_engine, logger=LOG):
            flow_engine.run()

    def request_service_capabilities(self, context):
        volume_rpcapi.VolumeAPI().publish_service_capabilities(context)

    def migrate_volume_to_host(self, context, topic, volume_id, host,
                               force_host_copy, request_spec,
                               filter_properties=None):
        """Ensure that the host exists and can accept the volume."""

        self._wait_for_scheduler()

        def _migrate_volume_set_error(self, context, ex, request_spec):
            volume = db.volume_get(context, request_spec['volume_id'])
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
            tgt_host = self.driver.host_passes_filters(context, host,
                                                       request_spec,
                                                       filter_properties)
        except exception.NoValidHost as ex:
            _migrate_volume_set_error(self, context, ex, request_spec)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                _migrate_volume_set_error(self, context, ex, request_spec)
        else:
            volume_ref = db.volume_get(context, volume_id)
            volume_rpcapi.VolumeAPI().migrate_volume(context, volume_ref,
                                                     tgt_host,
                                                     force_host_copy)

    def retype(self, context, topic, volume_id,
               request_spec, filter_properties=None):
        """Schedule the modification of a volume's type.

        :param context: the request context
        :param topic: the topic listened on
        :param volume_id: the ID of the volume to retype
        :param request_spec: parameters for this retype request
        :param filter_properties: parameters to filter by
        """

        self._wait_for_scheduler()

        def _retype_volume_set_error(self, context, ex, request_spec,
                                     volume_ref, msg, reservations):
            if reservations:
                QUOTAS.rollback(context, reservations)
            previous_status = (
                volume_ref.previous_status or volume_ref.status)
            volume_state = {'volume_state': {'status': previous_status}}
            self._set_volume_state_and_notify('retype', volume_state,
                                              context, ex, request_spec, msg)

        volume_ref = db.volume_get(context, volume_id)
        reservations = request_spec.get('quota_reservations')
        new_type = request_spec.get('volume_type')
        if new_type is None:
            msg = _('New volume type not specified in request_spec.')
            ex = exception.ParameterNotFound(param='volume_type')
            _retype_volume_set_error(self, context, ex, request_spec,
                                     volume_ref, msg, reservations)

        # Default migration policy is 'never'
        migration_policy = request_spec.get('migration_policy')
        if not migration_policy:
            migration_policy = 'never'

        try:
            tgt_host = self.driver.find_retype_host(context, request_spec,
                                                    filter_properties,
                                                    migration_policy)
        except exception.NoValidHost as ex:
            msg = (_("Could not find a host for volume %(volume_id)s with "
                     "type %(type_id)s.") %
                   {'type_id': new_type['id'], 'volume_id': volume_id})
            _retype_volume_set_error(self, context, ex, request_spec,
                                     volume_ref, msg, reservations)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                _retype_volume_set_error(self, context, ex, request_spec,
                                         volume_ref, None, reservations)
        else:
            volume_rpcapi.VolumeAPI().retype(context, volume_ref,
                                             new_type['id'], tgt_host,
                                             migration_policy, reservations)

    def manage_existing(self, context, topic, volume_id,
                        request_spec, filter_properties=None):
        """Ensure that the host exists and can accept the volume."""

        self._wait_for_scheduler()

        def _manage_existing_set_error(self, context, ex, request_spec):
            volume_state = {'volume_state': {'status': 'error'}}
            self._set_volume_state_and_notify('manage_existing', volume_state,
                                              context, ex, request_spec)

        volume_ref = db.volume_get(context, volume_id)
        try:
            self.driver.host_passes_filters(context,
                                            volume_ref['host'],
                                            request_spec,
                                            filter_properties)
        except exception.NoValidHost as ex:
            _manage_existing_set_error(self, context, ex, request_spec)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                _manage_existing_set_error(self, context, ex, request_spec)
        else:
            volume_rpcapi.VolumeAPI().manage_existing(context, volume_ref,
                                                      request_spec.get('ref'))

    def get_pools(self, context, filters=None):
        """Get active pools from scheduler's cache.

        NOTE(dulek): There's no self._wait_for_scheduler() because get_pools is
        an RPC call (is blocking for the c-api). Also this is admin-only API
        extension so it won't hurt the user much to retry the request manually.
        """
        return self.driver.get_pools(context, filters)

    def _set_volume_state_and_notify(self, method, updates, context, ex,
                                     request_spec, msg=None):
        # TODO(harlowja): move into a task that just does this later.
        if not msg:
            msg = (_LE("Failed to schedule_%(method)s: %(ex)s") %
                   {'method': method, 'ex': six.text_type(ex)})
        LOG.error(msg)

        volume_state = updates['volume_state']
        properties = request_spec.get('volume_properties', {})

        volume_id = request_spec.get('volume_id', None)

        if volume_id:
            db.volume_update(context, volume_id, volume_state)

        payload = dict(request_spec=request_spec,
                       volume_properties=properties,
                       volume_id=volume_id,
                       state=volume_state,
                       method=method,
                       reason=ex)

        rpc.get_notifier("scheduler").error(context,
                                            'scheduler.' + method,
                                            payload)
