# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from oslo.config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder import manager
from cinder.openstack.common import excutils
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.openstack.common.notifier import api as notifier
from cinder.volume.flows import create_volume
from cinder.volume import rpcapi as volume_rpcapi

from cinder.taskflow import states

scheduler_driver_opt = cfg.StrOpt('scheduler_driver',
                                  default='cinder.scheduler.filter_scheduler.'
                                          'FilterScheduler',
                                  help='Default scheduler driver to use')

CONF = cfg.CONF
CONF.register_opt(scheduler_driver_opt)

LOG = logging.getLogger(__name__)


class SchedulerManager(manager.Manager):
    """Chooses a host to create volumes."""

    RPC_API_VERSION = '1.3'

    def __init__(self, scheduler_driver=None, service_name=None,
                 *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = CONF.scheduler_driver
        self.driver = importutils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(*args, **kwargs)

    def init_host(self):
        ctxt = context.get_admin_context()
        self.request_service_capabilities(ctxt)

    def get_host_list(self, context):
        """Get a list of hosts from the HostManager."""
        return self.driver.get_host_list()

    def get_service_capabilities(self, context):
        """Get the normalized set of capabilities for this zone."""
        return self.driver.get_service_capabilities()

    def update_service_capabilities(self, context, service_name=None,
                                    host=None, capabilities=None, **kwargs):
        """Process a capability update from a service node."""
        if capabilities is None:
            capabilities = {}
        self.driver.update_service_capabilities(service_name,
                                                host,
                                                capabilities)

    def create_volume(self, context, topic, volume_id, snapshot_id=None,
                      image_id=None, request_spec=None,
                      filter_properties=None):

        flow = create_volume.get_scheduler_flow(db, self.driver,
                                                request_spec,
                                                filter_properties,
                                                volume_id, snapshot_id,
                                                image_id)
        assert flow, _('Schedule volume flow not retrieved')

        flow.run(context)
        if flow.state != states.SUCCESS:
            LOG.warn(_("Failed to successfully complete"
                       " schedule volume using flow: %s"), flow)

    def request_service_capabilities(self, context):
        volume_rpcapi.VolumeAPI().publish_service_capabilities(context)

    def _migrate_volume_set_error(self, context, ex, request_spec):
        volume_state = {'volume_state': {'migration_status': None}}
        self._set_volume_state_and_notify('migrate_volume_to_host',
                                          volume_state,
                                          context, ex, request_spec)

    def migrate_volume_to_host(self, context, topic, volume_id, host,
                               force_host_copy, request_spec,
                               filter_properties=None):
        """Ensure that the host exists and can accept the volume."""
        try:
            tgt_host = self.driver.host_passes_filters(context, host,
                                                       request_spec,
                                                       filter_properties)
        except exception.NoValidHost as ex:
                self._migrate_volume_set_error(context, ex, request_spec)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                self._migrate_volume_set_error(context, ex, request_spec)
        else:
            volume_ref = db.volume_get(context, volume_id)
            volume_rpcapi.VolumeAPI().migrate_volume(context, volume_ref,
                                                     tgt_host,
                                                     force_host_copy)

    def _set_volume_state_and_notify(self, method, updates, context, ex,
                                     request_spec):
        # TODO(harlowja): move into a task that just does this later.

        LOG.error(_("Failed to schedule_%(method)s: %(ex)s") %
                  {'method': method, 'ex': ex})

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

        notifier.notify(context, notifier.publisher_id("scheduler"),
                        'scheduler.' + method, notifier.ERROR, payload)
