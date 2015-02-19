#   Copyright 2014 IBM Corp.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from oslo_log import log as logging
import taskflow.engines
from taskflow.patterns import linear_flow

from cinder import exception
from cinder import flow_utils
from cinder.i18n import _, _LE
from cinder.volume.flows.api import create_volume as create_api
from cinder.volume.flows import common as flow_common
from cinder.volume.flows.manager import create_volume as create_mgr

LOG = logging.getLogger(__name__)

ACTION = 'volume:manage_existing'


class PrepareForQuotaReservationTask(flow_utils.CinderTask):
    """Gets the volume size from the driver."""

    default_provides = set(['size', 'volume_type_id', 'volume_properties',
                            'volume_spec'])

    def __init__(self, db, driver):
        super(PrepareForQuotaReservationTask, self).__init__(addons=[ACTION])
        self.db = db
        self.driver = driver

    def execute(self, context, volume_ref, manage_existing_ref):
        volume_id = volume_ref['id']
        if not self.driver.initialized:
            driver_name = self.driver.__class__.__name__
            LOG.error(_LE("Unable to manage existing volume. "
                          "Volume driver %s not initialized.") % driver_name)
            flow_common.error_out_volume(context, self.db, volume_id,
                                         reason=_("Volume driver %s "
                                                  "not initialized.") %
                                         driver_name)
            raise exception.DriverNotInitialized()

        size = self.driver.manage_existing_get_size(volume_ref,
                                                    manage_existing_ref)

        return {'size': size,
                'volume_type_id': volume_ref['volume_type_id'],
                'volume_properties': volume_ref,
                'volume_spec': {'status': volume_ref['status'],
                                'volume_name': volume_ref['name'],
                                'volume_id': volume_ref['id']}}


class ManageExistingTask(flow_utils.CinderTask):
    """Brings an existing volume under Cinder management."""

    default_provides = set(['volume'])

    def __init__(self, db, driver):
        super(ManageExistingTask, self).__init__(addons=[ACTION])
        self.db = db
        self.driver = driver

    def execute(self, context, volume_ref, manage_existing_ref, size):
        model_update = self.driver.manage_existing(volume_ref,
                                                   manage_existing_ref)
        if not model_update:
            model_update = {}
        model_update.update({'size': size})
        try:
            volume_ref = self.db.volume_update(context, volume_ref['id'],
                                               model_update)
        except exception.CinderException:
            LOG.exception(_LE("Failed updating model of volume %(volume_id)s"
                              " with creation provided model %(model)s") %
                          {'volume_id': volume_ref['id'],
                           'model': model_update})
            raise

        return {'volume': volume_ref}


def get_flow(context, db, driver, host, volume_id, ref):
    """Constructs and returns the manager entrypoint flow."""

    flow_name = ACTION.replace(":", "_") + "_manager"
    volume_flow = linear_flow.Flow(flow_name)

    # This injects the initial starting flow values into the workflow so that
    # the dependency order of the tasks provides/requires can be correctly
    # determined.
    create_what = {
        'context': context,
        'volume_id': volume_id,
        'manage_existing_ref': ref,
        'optional_args': {'is_quota_committed': False}
    }

    volume_flow.add(create_mgr.ExtractVolumeRefTask(db, host),
                    create_mgr.NotifyVolumeActionTask(db,
                                                      "manage_existing.start"),
                    PrepareForQuotaReservationTask(db, driver),
                    create_api.QuotaReserveTask(),
                    ManageExistingTask(db, driver),
                    create_api.QuotaCommitTask(),
                    create_mgr.CreateVolumeOnFinishTask(db, "create.end"))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(volume_flow, store=create_what)
