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


from oslo_config import cfg
from oslo_log import log as logging
import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow.types import failure as ft

from cinder import exception
from cinder import flow_utils
from cinder.i18n import _LE
from cinder.volume.flows import common

LOG = logging.getLogger(__name__)

ACTION = 'volume:manage_existing'
CONF = cfg.CONF


class EntryCreateTask(flow_utils.CinderTask):
    """Creates an entry for the given volume creation in the database.

    Reversion strategy: remove the volume_id created from the database.
    """
    default_provides = set(['volume_properties', 'volume'])

    def __init__(self, db):
        requires = ['availability_zone', 'description', 'metadata',
                    'name', 'host', 'bootable', 'volume_type', 'ref']
        super(EntryCreateTask, self).__init__(addons=[ACTION],
                                              requires=requires)
        self.db = db

    def execute(self, context, **kwargs):
        """Creates a database entry for the given inputs and returns details.

        Accesses the database and creates a new entry for the to be created
        volume using the given volume properties which are extracted from the
        input kwargs.
        """
        volume_type = kwargs.pop('volume_type')
        volume_type_id = volume_type['id'] if volume_type else None

        volume_properties = {
            'size': 0,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': 'creating',
            'attach_status': 'detached',
            # Rename these to the internal name.
            'display_description': kwargs.pop('description'),
            'display_name': kwargs.pop('name'),
            'host': kwargs.pop('host'),
            'availability_zone': kwargs.pop('availability_zone'),
            'volume_type_id': volume_type_id,
            'metadata': kwargs.pop('metadata'),
            'bootable': kwargs.pop('bootable'),
        }

        volume = self.db.volume_create(context, volume_properties)

        return {
            'volume_properties': volume_properties,
            # NOTE(harlowja): it appears like further usage of this volume
            # result actually depend on it being a sqlalchemy object and not
            # just a plain dictionary so that's why we are storing this here.
            #
            # In the future where this task results can be serialized and
            # restored automatically for continued running we will need to
            # resolve the serialization & recreation of this object since raw
            # sqlalchemy objects can't be serialized.
            'volume': volume,
        }

    def revert(self, context, result, optional_args, **kwargs):
        # We never produced a result and therefore can't destroy anything.
        if isinstance(result, ft.Failure):
            return

        vol_id = result['volume_id']
        try:
            self.db.volume_destroy(context.elevated(), vol_id)
        except exception.CinderException:
            LOG.exception(_LE("Failed destroying volume entry: %s."), vol_id)


class ManageCastTask(flow_utils.CinderTask):
    """Performs a volume manage cast to the scheduler and to the volume manager.

    This which will signal a transition of the api workflow to another child
    and/or related workflow.
    """

    def __init__(self, scheduler_rpcapi, db):
        requires = ['volume', 'volume_properties', 'volume_type', 'ref']
        super(ManageCastTask, self).__init__(addons=[ACTION],
                                             requires=requires)
        self.scheduler_rpcapi = scheduler_rpcapi
        self.db = db

    def execute(self, context, **kwargs):
        volume = kwargs.pop('volume')
        request_spec = kwargs.copy()

        # Call the scheduler to ensure that the host exists and that it can
        # accept the volume
        self.scheduler_rpcapi.manage_existing(context, CONF.volume_topic,
                                              volume['id'],
                                              request_spec=request_spec)

    def revert(self, context, result, flow_failures, **kwargs):
        # Restore the source volume status and set the volume to error status.
        volume_id = kwargs['volume_id']
        common.error_out_volume(context, self.db, volume_id)
        LOG.error(_LE("Volume %s: manage failed."), volume_id)
        exc_info = False
        if all(flow_failures[-1].exc_info):
            exc_info = flow_failures[-1].exc_info
        LOG.error(_LE('Unexpected build error:'), exc_info=exc_info)


def get_flow(scheduler_rpcapi, db_api, create_what):
    """Constructs and returns the api entrypoint flow.

    This flow will do the following:

    1. Inject keys & values for dependent tasks.
    2. Extracts and validates the input keys & values.
    3. Creates the database entry.
    4. Casts to volume manager and scheduler for further processing.
    """

    flow_name = ACTION.replace(":", "_") + "_api"
    api_flow = linear_flow.Flow(flow_name)

    # This will cast it out to either the scheduler or volume manager via
    # the rpc apis provided.
    api_flow.add(EntryCreateTask(db_api),
                 ManageCastTask(scheduler_rpcapi, db_api))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(api_flow, store=create_what)
