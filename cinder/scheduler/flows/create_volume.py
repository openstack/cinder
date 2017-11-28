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

from oslo_log import log as logging
from oslo_utils import excutils
import taskflow.engines
from taskflow.patterns import linear_flow

from cinder import exception
from cinder import flow_utils
from cinder.message import api as message_api
from cinder.message import message_field
from cinder import rpc
from cinder import utils
from cinder.volume.flows import common

LOG = logging.getLogger(__name__)

ACTION = 'volume:create'


class ExtractSchedulerSpecTask(flow_utils.CinderTask):
    """Extracts a spec object from a partial and/or incomplete request spec.

    Reversion strategy: N/A
    """

    default_provides = set(['request_spec'])

    def __init__(self, **kwargs):
        super(ExtractSchedulerSpecTask, self).__init__(addons=[ACTION],
                                                       **kwargs)

    def _populate_request_spec(self, volume, snapshot_id, image_id, backup_id):
        # Create the full request spec using the volume object.
        #
        # NOTE(dulek): At this point, a volume can be deleted before it gets
        # scheduled.  If a delete API call is made, the volume gets instantly
        # delete and scheduling will fail when it tries to update the DB entry
        # (with the host) in ScheduleCreateVolumeTask below.
        volume_type_id = volume.volume_type_id
        vol_type = volume.volume_type
        return {
            'volume_id': volume.id,
            'snapshot_id': snapshot_id,
            'image_id': image_id,
            'backup_id': backup_id,
            'volume_properties': {
                'size': utils.as_int(volume.size, quiet=False),
                'availability_zone': volume.availability_zone,
                'volume_type_id': volume_type_id,
            },
            'volume_type': list(dict(vol_type).items()),
        }

    def execute(self, context, request_spec, volume, snapshot_id,
                image_id, backup_id):
        # For RPC version < 1.2 backward compatibility
        if request_spec is None:
            request_spec = self._populate_request_spec(volume,
                                                       snapshot_id, image_id,
                                                       backup_id)
        return {
            'request_spec': request_spec,
        }


class ScheduleCreateVolumeTask(flow_utils.CinderTask):
    """Activates a scheduler driver and handles any subsequent failures.

    Notification strategy: on failure the scheduler rpc notifier will be
    activated and a notification will be emitted indicating what errored,
    the reason, and the request (and misc. other data) that caused the error
    to be triggered.

    Reversion strategy: N/A
    """
    FAILURE_TOPIC = "scheduler.create_volume"

    def __init__(self, driver_api, **kwargs):
        super(ScheduleCreateVolumeTask, self).__init__(addons=[ACTION],
                                                       **kwargs)
        self.driver_api = driver_api
        self.message_api = message_api.API()

    def _handle_failure(self, context, request_spec, cause):
        try:
            self._notify_failure(context, request_spec, cause)
        finally:
            LOG.error("Failed to run task %(name)s: %(cause)s",
                      {'cause': cause, 'name': self.name})

    @utils.if_notifications_enabled
    def _notify_failure(self, context, request_spec, cause):
        """When scheduling fails send out an event that it failed."""
        payload = {
            'request_spec': request_spec,
            'volume_properties': request_spec.get('volume_properties', {}),
            'volume_id': request_spec['volume_id'],
            'state': 'error',
            'method': 'create_volume',
            'reason': cause,
        }
        try:
            rpc.get_notifier('scheduler').error(context, self.FAILURE_TOPIC,
                                                payload)
        except exception.CinderException:
            LOG.exception("Failed notifying on %(topic)s "
                          "payload %(payload)s",
                          {'topic': self.FAILURE_TOPIC, 'payload': payload})

    def execute(self, context, request_spec, filter_properties, volume):
        try:
            self.driver_api.schedule_create_volume(context, request_spec,
                                                   filter_properties)
        except Exception as e:
            self.message_api.create(
                context,
                message_field.Action.SCHEDULE_ALLOCATE_VOLUME,
                resource_uuid=request_spec['volume_id'],
                exception=e)
            # An error happened, notify on the scheduler queue and log that
            # this happened and set the volume to errored out and reraise the
            # error *if* exception caught isn't NoValidBackend. Otherwise *do
            # not* reraise (since what's the point?)
            with excutils.save_and_reraise_exception(
                    reraise=not isinstance(e, exception.NoValidBackend)):
                try:
                    self._handle_failure(context, request_spec, e)
                finally:
                    common.error_out(volume, reason=e)


def get_flow(context, driver_api, request_spec=None,
             filter_properties=None,
             volume=None, snapshot_id=None, image_id=None, backup_id=None):

    """Constructs and returns the scheduler entrypoint flow.

    This flow will do the following:

    1. Inject keys & values for dependent tasks.
    2. Extract a scheduler specification from the provided inputs.
    3. Use provided scheduler driver to select host and pass volume creation
       request further.
    """
    create_what = {
        'context': context,
        'raw_request_spec': request_spec,
        'filter_properties': filter_properties,
        'volume': volume,
        'snapshot_id': snapshot_id,
        'image_id': image_id,
        'backup_id': backup_id,
    }

    flow_name = ACTION.replace(":", "_") + "_scheduler"
    scheduler_flow = linear_flow.Flow(flow_name)

    # This will extract and clean the spec from the starting values.
    scheduler_flow.add(ExtractSchedulerSpecTask(
        rebind={'request_spec': 'raw_request_spec'}))

    # This will activate the desired scheduler driver (and handle any
    # driver related failures appropriately).
    scheduler_flow.add(ScheduleCreateVolumeTask(driver_api))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(scheduler_flow, store=create_what)
