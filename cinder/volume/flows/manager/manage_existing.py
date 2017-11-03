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
from oslo_utils import excutils
import taskflow.engines
from taskflow.patterns import linear_flow

from cinder import exception
from cinder import flow_utils
from cinder.i18n import _
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

    def execute(self, context, volume, manage_existing_ref):
        driver_name = self.driver.__class__.__name__
        if not self.driver.initialized:
            LOG.error("Unable to manage existing volume. "
                      "Volume driver %s not initialized.", driver_name)
            flow_common.error_out(volume, _("Volume driver %s not "
                                            "initialized.") % driver_name,
                                  status='error_managing')
            raise exception.DriverNotInitialized()

        size = 0
        try:
            size = self.driver.manage_existing_get_size(volume,
                                                        manage_existing_ref)
        except Exception:
            with excutils.save_and_reraise_exception():
                reason = _("Volume driver %s get exception.") % driver_name
                flow_common.error_out(volume, reason,
                                      status='error_managing')

        return {'size': size,
                'volume_type_id': volume.volume_type_id,
                'volume_properties': volume,
                'volume_spec': {'status': volume.status,
                                'volume_name': volume.name,
                                'volume_id': volume.id}}

    def revert(self, context, result, flow_failures, volume, **kwargs):
        reason = _('Volume manage failed.')
        flow_common.error_out(volume, reason=reason,
                              status='error_managing')
        LOG.error("Volume %s: manage failed.", volume.id)


class ManageExistingTask(flow_utils.CinderTask):
    """Brings an existing volume under Cinder management."""

    default_provides = set(['volume'])

    def __init__(self, db, driver):
        super(ManageExistingTask, self).__init__(addons=[ACTION])
        self.db = db
        self.driver = driver

    def execute(self, context, volume, manage_existing_ref, size):
        model_update = self.driver.manage_existing(volume,
                                                   manage_existing_ref)

        if not model_update:
            model_update = {}
        model_update.update({'size': size})
        try:
            volume.update(model_update)
            volume.save()
        except exception.CinderException:
            LOG.exception("Failed updating model of volume %(volume_id)s"
                          " with creation provided model %(model)s",
                          {'volume_id': volume.id,
                           'model': model_update})
            raise

        return {'volume': volume}


def get_flow(context, db, driver, host, volume, ref):
    """Constructs and returns the manager entrypoint flow."""

    flow_name = ACTION.replace(":", "_") + "_manager"
    volume_flow = linear_flow.Flow(flow_name)

    # This injects the initial starting flow values into the workflow so that
    # the dependency order of the tasks provides/requires can be correctly
    # determined.
    create_what = {
        'context': context,
        'volume': volume,
        'manage_existing_ref': ref,
        'group_snapshot': None,
        'optional_args': {'is_quota_committed': False},
    }

    volume_flow.add(create_mgr.NotifyVolumeActionTask(db,
                                                      "manage_existing.start"),
                    PrepareForQuotaReservationTask(db, driver),
                    create_api.QuotaReserveTask(),
                    ManageExistingTask(db, driver),
                    create_api.QuotaCommitTask(),
                    create_mgr.CreateVolumeOnFinishTask(db,
                                                        "manage_existing.end"))

    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(volume_flow, store=create_what)
