#   Copyright (c) 2015 Huawei Technologies Co., Ltd.
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

from oslo_config import cfg
from oslo_log import log as logging
import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow.types import failure as ft

from cinder import exception
from cinder import flow_utils
from cinder.i18n import _
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder import quota_utils
from cinder.volume.flows import common as flow_common
from cinder.volume import volume_utils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)
QUOTAS = quota.QUOTAS

ACTION = 'snapshot:manage_existing'


class ExtractSnapshotRefTask(flow_utils.CinderTask):
    """Extracts snapshot reference for given snapshot id."""

    default_provides = 'snapshot_ref'

    def __init__(self, db):
        super(ExtractSnapshotRefTask, self).__init__(addons=[ACTION])
        self.db = db

    def execute(self, context, snapshot_id):
        # NOTE(wanghao): this will fetch the snapshot from the database, if
        # the snapshot has been deleted before we got here then this should
        # fail.
        #
        # In the future we might want to have a lock on the snapshot_id so that
        # the snapshot can not be deleted while its still being created?
        snapshot_ref = objects.Snapshot.get_by_id(context, snapshot_id)
        LOG.debug("ExtractSnapshotRefTask return"
                  " snapshot_ref: %s", snapshot_ref)
        return snapshot_ref

    def revert(self, context, snapshot_id, result, **kwargs):
        if isinstance(result, ft.Failure):
            return

        flow_common.error_out(result)
        LOG.error("Snapshot %s: create failed", result.id)


class NotifySnapshotActionTask(flow_utils.CinderTask):
    """Performs a notification about the given snapshot when called.

    Reversion strategy: N/A
    """

    def __init__(self, db, event_suffix, host):
        super(NotifySnapshotActionTask, self).__init__(addons=[ACTION,
                                                               event_suffix])
        self.db = db
        self.event_suffix = event_suffix
        self.host = host

    def execute(self, context, snapshot_ref):
        snapshot_id = snapshot_ref['id']
        try:
            volume_utils.notify_about_snapshot_usage(context, snapshot_ref,
                                                     self.event_suffix,
                                                     host=self.host)
        except exception.CinderException:
            # If notification sending of snapshot database entry reading fails
            # then we shouldn't error out the whole workflow since this is
            # not always information that must be sent for snapshots to operate
            LOG.exception("Failed notifying about the snapshot "
                          "action %(event)s for snapshot %(snp_id)s.",
                          {'event': self.event_suffix,
                           'snp_id': snapshot_id})


class PrepareForQuotaReservationTask(flow_utils.CinderTask):
    """Gets the snapshot size from the driver."""

    default_provides = set(['size', 'snapshot_properties'])

    def __init__(self, db, driver):
        super(PrepareForQuotaReservationTask, self).__init__(addons=[ACTION])
        self.db = db
        self.driver = driver

    def execute(self, context, snapshot_ref, manage_existing_ref):
        if not self.driver.initialized:
            driver_name = (self.driver.configuration.
                           safe_get('volume_backend_name'))
            LOG.error("Unable to manage existing snapshot. "
                      "Volume driver %s not initialized.", driver_name)
            flow_common.error_out(snapshot_ref, reason=_("Volume driver %s "
                                                         "not initialized.") %
                                  driver_name)
            raise exception.DriverNotInitialized()

        size = self.driver.manage_existing_snapshot_get_size(
            snapshot=snapshot_ref,
            existing_ref=manage_existing_ref)

        return {'size': size,
                'snapshot_properties': snapshot_ref}


class QuotaReserveTask(flow_utils.CinderTask):
    """Reserves a single snapshot with the given size.

    Reversion strategy: rollback the quota reservation.

    Warning Warning: if the process that is running this reserve and commit
    process fails (or is killed before the quota is rolled back or committed
    it does appear like the quota will never be rolled back). This makes
    software upgrades hard (inflight operations will need to be stopped or
    allowed to complete before the upgrade can occur). *In the future* when
    taskflow has persistence built-in this should be easier to correct via
    an automated or manual process.
    """

    default_provides = set(['reservations'])

    def __init__(self):
        super(QuotaReserveTask, self).__init__(addons=[ACTION])

    def execute(self, context, size, snapshot_ref, optional_args):
        try:
            if CONF.no_snapshot_gb_quota:
                reserve_opts = {'snapshots': 1}
            else:
                # NOTE(tommylikehu): We only use the difference of size here
                # as we already committed the original size at the API
                # service before and this reservation task is only used for
                # managing snapshots now.
                reserve_opts = {'snapshots': 1,
                                'gigabytes':
                                    int(size) - snapshot_ref.volume_size}
            if 'update_size' in optional_args and optional_args['update_size']:
                reserve_opts.pop('snapshots', None)
            volume = objects.Volume.get_by_id(context, snapshot_ref.volume_id)
            QUOTAS.add_volume_type_opts(context,
                                        reserve_opts,
                                        volume.volume_type_id)
            reservations = QUOTAS.reserve(context, **reserve_opts)
            return {
                'reservations': reservations,
            }
        except exception.OverQuota as e:
            quota_utils.process_reserve_over_quota(
                context, e,
                resource='snapshots',
                size=size)

    def revert(self, context, result, optional_args, **kwargs):
        # We never produced a result and therefore can't destroy anything.
        if isinstance(result, ft.Failure):
            return

        if optional_args['is_quota_committed']:
            # The reservations have already been committed and can not be
            # rolled back at this point.
            return
        # We actually produced an output that we can revert so lets attempt
        # to use said output to rollback the reservation.
        reservations = result['reservations']
        try:
            QUOTAS.rollback(context, reservations)
        except exception.CinderException:
            # We are already reverting, therefore we should silence this
            # exception since a second exception being active will be bad.
            LOG.exception("Failed rolling back quota for"
                          " %s reservations.", reservations)


class QuotaCommitTask(flow_utils.CinderTask):
    """Commits the reservation.

    Reversion strategy: N/A (the rollback will be handled by the task that did
    the initial reservation (see: QuotaReserveTask).

    Warning Warning: if the process that is running this reserve and commit
    process fails (or is killed before the quota is rolled back or committed
    it does appear like the quota will never be rolled back). This makes
    software upgrades hard (inflight operations will need to be stopped or
    allowed to complete before the upgrade can occur). *In the future* when
    taskflow has persistence built-in this should be easier to correct via
    an automated or manual process.
    """

    def __init__(self):
        super(QuotaCommitTask, self).__init__(addons=[ACTION])

    def execute(self, context, reservations, snapshot_properties,
                optional_args):
        QUOTAS.commit(context, reservations)
        # updating is_quota_committed attribute of optional_args dictionary
        optional_args['is_quota_committed'] = True
        return {'snapshot_properties': snapshot_properties}

    def revert(self, context, result, **kwargs):
        # We never produced a result and therefore can't destroy anything.
        if isinstance(result, ft.Failure):
            return
        snapshot = result['snapshot_properties']
        try:
            reserve_opts = {'snapshots': -1,
                            'gigabytes': -snapshot['volume_size']}
            reservations = QUOTAS.reserve(context,
                                          project_id=context.project_id,
                                          **reserve_opts)
            if reservations:
                QUOTAS.commit(context, reservations,
                              project_id=context.project_id)
        except Exception:
            LOG.exception("Failed to update quota while deleting "
                          "snapshots: %s", snapshot['id'])


class ManageExistingTask(flow_utils.CinderTask):
    """Brings an existing snapshot under Cinder management."""

    default_provides = set(['snapshot', 'new_status'])

    def __init__(self, db, driver):
        super(ManageExistingTask, self).__init__(addons=[ACTION])
        self.db = db
        self.driver = driver

    def execute(self, context, snapshot_ref, manage_existing_ref, size):
        model_update = self.driver.manage_existing_snapshot(
            snapshot=snapshot_ref,
            existing_ref=manage_existing_ref)
        if not model_update:
            model_update = {}
        model_update['volume_size'] = size
        try:
            snapshot_object = objects.Snapshot.get_by_id(context,
                                                         snapshot_ref['id'])
            snapshot_object.update(model_update)
            snapshot_object.save()
        except exception.CinderException:
            LOG.exception("Failed updating model of snapshot "
                          "%(snapshot_id)s with creation provided model "
                          "%(model)s.",
                          {'snapshot_id': snapshot_ref['id'],
                           'model': model_update})
            raise

        return {'snapshot': snapshot_ref,
                'new_status': fields.SnapshotStatus.AVAILABLE}


class CreateSnapshotOnFinishTask(NotifySnapshotActionTask):
    """Perform final snapshot actions.

    When a snapshot is created successfully it is expected that MQ
    notifications and database updates will occur to 'signal' to others that
    the snapshot is now ready for usage. This task does those notifications and
    updates in a reliable manner (not re-raising exceptions if said actions can
    not be triggered).

    Reversion strategy: N/A
    """

    def execute(self, context, snapshot, new_status):
        LOG.debug("Begin to call CreateSnapshotOnFinishTask execute.")
        snapshot_id = snapshot['id']
        LOG.debug("New status: %s", new_status)
        update = {
            'status': new_status
        }
        try:
            # TODO(harlowja): is it acceptable to only log if this fails??
            # or are there other side-effects that this will cause if the
            # status isn't updated correctly (aka it will likely be stuck in
            # 'building' if this fails)??
            snapshot_object = objects.Snapshot.get_by_id(context,
                                                         snapshot_id)
            snapshot_object.update(update)
            snapshot_object.save()
            # Now use the parent to notify.
            super(CreateSnapshotOnFinishTask, self).execute(context, snapshot)
        except exception.CinderException:
            LOG.exception("Failed updating snapshot %(snapshot_id)s with "
                          "%(update)s.", {'snapshot_id': snapshot_id,
                                          'update': update})
        # Even if the update fails, the snapshot is ready.
        LOG.info("Snapshot %s created successfully.", snapshot_id)


def get_flow(context, db, driver, host, snapshot_id, ref):
    """Constructs and returns the manager entry point flow."""

    LOG.debug("Input parameters: context=%(context)s, db=%(db)s,"
              "driver=%(driver)s, host=%(host)s, "
              "snapshot_id=(snapshot_id)s, ref=%(ref)s.",
              {'context': context,
               'db': db,
               'driver': driver,
               'host': host,
               'snapshot_id': snapshot_id,
               'ref': ref}
              )
    flow_name = ACTION.replace(":", "_") + "_manager"
    snapshot_flow = linear_flow.Flow(flow_name)

    # This injects the initial starting flow values into the workflow so that
    # the dependency order of the tasks provides/requires can be correctly
    # determined.
    create_what = {
        'context': context,
        'snapshot_id': snapshot_id,
        'manage_existing_ref': ref,
        'optional_args': {'is_quota_committed': False, 'update_size': True}
    }

    notify_start_msg = "manage_existing_snapshot.start"
    notify_end_msg = "manage_existing_snapshot.end"
    snapshot_flow.add(ExtractSnapshotRefTask(db),
                      NotifySnapshotActionTask(db, notify_start_msg,
                                               host=host),
                      PrepareForQuotaReservationTask(db, driver),
                      QuotaReserveTask(),
                      ManageExistingTask(db, driver),
                      QuotaCommitTask(),
                      CreateSnapshotOnFinishTask(db, notify_end_msg,
                                                 host=host))
    LOG.debug("Begin to return taskflow.engines."
              "load(snapshot_flow,store=create_what).")
    # Now load (but do not run) the flow using the provided initial data.
    return taskflow.engines.load(snapshot_flow, store=create_what)
