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
from oslo import messaging

from cinder import context
from cinder import db
from cinder import exception
from cinder import manager
from cinder.openstack.common import excutils
from cinder.openstack.common import importutils
from cinder.openstack.common import log as logging
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

    RPC_API_VERSION = '1.5'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, scheduler_driver=None, service_name=None,
                 *args, **kwargs):
        if not scheduler_driver:
            scheduler_driver = CONF.scheduler_driver
        if scheduler_driver in ['cinder.scheduler.chance.ChanceScheduler',
                                'cinder.scheduler.simple.SimpleScheduler']:
            scheduler_driver = ('cinder.scheduler.filter_scheduler.'
                                'FilterScheduler')
            LOG.deprecated(_('ChanceScheduler and SimpleScheduler have been '
                             'deprecated due to lack of support for advanced '
                             'features like: volume types, volume encryption,'
                             ' QoS etc. These two schedulers can be fully '
                             'replaced by FilterScheduler with certain '
                             'combination of filters and weighers.'))
        self.driver = importutils.import_object(scheduler_driver)
        super(SchedulerManager, self).__init__(*args, **kwargs)

    def init_host(self):
        ctxt = context.get_admin_context()
        self.request_service_capabilities(ctxt)

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
            flow_engine = create_volume.get_flow(context,
                                                 db, self.driver,
                                                 request_spec,
                                                 filter_properties,
                                                 volume_id,
                                                 snapshot_id,
                                                 image_id)
        except Exception:
            LOG.exception(_("Failed to create scheduler manager volume flow"))
            raise exception.CinderException(
                _("Failed to create scheduler manager volume flow"))
        flow_engine.run()

    def request_service_capabilities(self, context):
        volume_rpcapi.VolumeAPI().publish_service_capabilities(context)

    def migrate_volume_to_host(self, context, topic, volume_id, host,
                               force_host_copy, request_spec,
                               filter_properties=None):
        """Ensure that the host exists and can accept the volume."""

        def _migrate_volume_set_error(self, context, ex, request_spec):
            volume_state = {'volume_state': {'migration_status': None}}
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
        def _retype_volume_set_error(self, context, ex, request_spec,
                                     volume_ref, msg, reservations):
            if reservations:
                QUOTAS.rollback(context, reservations)
            if (volume_ref['instance_uuid'] is None and
                    volume_ref['attached_host'] is None):
                orig_status = 'available'
            else:
                orig_status = 'in-use'
            volume_state = {'volume_state': {'status': orig_status}}
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

        def _manage_existing_set_error(self, context, ex, request_spec):
            volume_state = {'volume_state': {'status': 'error'}}
            self._set_volume_state_and_notify('manage_existing', volume_state,
                                              context, ex, request_spec)

        volume_ref = db.volume_get(context, volume_id)
        try:
            tgt_host = self.driver.host_passes_filters(context,
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

    def _set_volume_state_and_notify(self, method, updates, context, ex,
                                     request_spec, msg=None):
        # TODO(harlowja): move into a task that just does this later.
        if not msg:
            msg = (_("Failed to schedule_%(method)s: %(ex)s") %
                   {'method': method, 'ex': ex})
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
