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

import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow import task

from cinder import exception
from cinder import flow_utils
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common.notifier import api as notifier
from cinder import utils
from cinder.volume.flows import common

LOG = logging.getLogger(__name__)

ACTION = 'volume:create'


class ExtractSchedulerSpecTask(flow_utils.CinderTask):
    """Extracts a spec object from a partial and/or incomplete request spec.

    Reversion strategy: N/A
    """

    default_provides = set(['request_spec'])

    def __init__(self, db, **kwargs):
        super(ExtractSchedulerSpecTask, self).__init__(addons=[ACTION],
                                                       **kwargs)
        self.db = db

    def _populate_request_spec(self, context, volume_id, snapshot_id,
                               image_id):
        # Create the full request spec using the volume_id.
        #
        # NOTE(harlowja): this will fetch the volume from the database, if
        # the volume has been deleted before we got here then this should fail.
        #
        # In the future we might want to have a lock on the volume_id so that
        # the volume can not be deleted while its still being created?
        if not volume_id:
            msg = _("No volume_id provided to populate a request_spec from")
            raise exception.InvalidInput(reason=msg)
        volume_ref = self.db.volume_get(context, volume_id)
        volume_type_id = volume_ref.get('volume_type_id')
        vol_type = self.db.volume_type_get(context, volume_type_id)
        return {
            'volume_id': volume_id,
            'snapshot_id': snapshot_id,
            'image_id': image_id,
            'volume_properties': {
                'size': utils.as_int(volume_ref.get('size'), quiet=False),
                'availability_zone': volume_ref.get('availability_zone'),
                'volume_type_id': volume_type_id,
            },
            'volume_type': list(dict(vol_type).iteritems()),
        }

    def execute(self, context, request_spec, volume_id, snapshot_id,
                image_id):
        # For RPC version < 1.2 backward compatibility
        if request_spec is None:
            request_spec = self._populate_request_spec(context, volume_id,
                                                       snapshot_id, image_id)
        return {
            'request_spec': request_spec,
        }


def get_flow(context, db, driver, request_spec=None,
             filter_properties=None,
             volume_id=None, snapshot_id=None, image_id=None):

    """Constructs and returns the scheduler entrypoint flow.

    This flow will do the following:

    1. Inject keys & values for dependent tasks.
    2. Extracts a scheduler specification from the provided inputs.
    3. Attaches 2 activated only on *failure* tasks (one to update the db
       status and one to notify on the MQ of the failure that occurred).
    4. Uses provided driver to to then select and continue processing of
       volume request.
    """
    create_what = {
        'context': context,
        'raw_request_spec': request_spec,
        'filter_properties': filter_properties,
        'volume_id': volume_id,
        'snapshot_id': snapshot_id,
        'image_id': image_id,
    }

    flow_name = ACTION.replace(":", "_") + "_scheduler"
    scheduler_flow = linear_flow.Flow(flow_name)

    # This will extract and clean the spec from the starting values.
    scheduler_flow.add(ExtractSchedulerSpecTask(
        db,
        rebind={'request_spec': 'raw_request_spec'}))

    def schedule_create_volume(context, request_spec, filter_properties):

        def _log_failure(cause):
            LOG.error(_("Failed to schedule_create_volume: %(cause)s") %
                      {'cause': cause})

        def _notify_failure(cause):
            """When scheduling fails send out a event that it failed."""
            topic = "scheduler.create_volume"
            payload = {
                'request_spec': request_spec,
                'volume_properties': request_spec.get('volume_properties', {}),
                'volume_id': volume_id,
                'state': 'error',
                'method': 'create_volume',
                'reason': cause,
            }
            try:
                publisher_id = notifier.publisher_id("scheduler")
                notifier.notify(context, publisher_id, topic, notifier.ERROR,
                                payload)
            except exception.CinderException:
                LOG.exception(_("Failed notifying on %(topic)s "
                                "payload %(payload)s") % {'topic': topic,
                                                          'payload': payload})

        try:
            driver.schedule_create_volume(context, request_spec,
                                          filter_properties)
        except exception.NoValidHost as e:
            # Not host found happened, notify on the scheduler queue and log
            # that this happened and set the volume to errored out and
            # *do not* reraise the error (since whats the point).
            _notify_failure(e)
            _log_failure(e)
            common.error_out_volume(context, db, volume_id, reason=e)
        except Exception as e:
            # Some other error happened, notify on the scheduler queue and log
            # that this happened and set the volume to errored out and
            # *do* reraise the error.
            with excutils.save_and_reraise_exception():
                _notify_failure(e)
                _log_failure(e)
                common.error_out_volume(context, db, volume_id, reason=e)

    scheduler_flow.add(task.FunctorTask(schedule_create_volume))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(scheduler_flow, store=create_what)
