# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 OpenStack, LLC.
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

from cinder import context
from cinder import db
from cinder import exception
from cinder import flags
from cinder import manager
from cinder.openstack.common import cfg
from cinder.openstack.common import excutils
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
from cinder.openstack.common.notifier import api as notifier
from cinder.volume import rpcapi as volume_rpcapi


LOG = logging.getLogger(__name__)

scheduler_driver_opt = cfg.StrOpt('scheduler_driver',
                                  default='cinder.scheduler.filter_scheduler.'
                                          'FilterScheduler',
                                  help='Default scheduler driver to use')

FLAGS = flags.FLAGS
FLAGS.register_opt(scheduler_driver_opt)


class SchedulerManager(manager.Manager):
    """Chooses a host to create volumes."""

    RPC_API_VERSION = '1.2'

    def __init__(self, scheduler_driver=None, *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = FLAGS.scheduler_driver
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
        try:
            if request_spec is None:
                # For RPC version < 1.2 backward compatibility
                request_spec = {}
                volume_ref = db.volume_get(context, volume_id)
                size = volume_ref.get('size')
                availability_zone = volume_ref.get('availability_zone')
                volume_type_id = volume_ref.get('volume_type_id')
                vol_type = db.volume_type_get(context, volume_type_id)
                volume_properties = {'size': size,
                                     'availability_zone': availability_zone,
                                     'volume_type_id': volume_type_id}
                request_spec.update(
                    {'volume_id': volume_id,
                     'snapshot_id': snapshot_id,
                     'image_id': image_id,
                     'volume_properties': volume_properties,
                     'volume_type': dict(vol_type).iteritems()})

            self.driver.schedule_create_volume(context, request_spec,
                                               filter_properties)
        except exception.NoValidHost as ex:
            volume_state = {'volume_state': {'status': 'error'}}
            self._set_volume_state_and_notify('create_volume',
                                              volume_state,
                                              context, ex, request_spec)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                volume_state = {'volume_state': {'status': 'error'}}
                self._set_volume_state_and_notify('create_volume',
                                                  volume_state,
                                                  context, ex, request_spec)

    def _set_volume_state_and_notify(self, method, updates, context, ex,
                                     request_spec):
        LOG.warning(_("Failed to schedule_%(method)s: %(ex)s") % locals())

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

    def request_service_capabilities(self, context):
        volume_rpcapi.VolumeAPI().publish_service_capabilities(context)
