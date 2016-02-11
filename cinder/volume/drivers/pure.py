# Copyright (c) 2014 Pure Storage, Inc.
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
Volume driver for Pure Storage FlashArray storage system.

This driver requires Purity version 4.0.0 or later.
"""

import math
import re
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.objects import fields
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types
from cinder.zonemanager import utils as fczm_utils

try:
    from purestorage import purestorage
except ImportError:
    purestorage = None

LOG = logging.getLogger(__name__)

PURE_OPTS = [
    cfg.StrOpt("pure_api_token",
               help="REST API authorization token."),
    cfg.BoolOpt("pure_automatic_max_oversubscription_ratio",
                default=True,
                help="Automatically determine an oversubscription ratio based "
                     "on the current total data reduction values. If used "
                     "this calculated value will override the "
                     "max_over_subscription_ratio config option."),
    # These are used as default settings.  In future these can be overridden
    # by settings in volume-type.
    cfg.IntOpt("pure_replica_interval_default", default=900,
               help="Snapshot replication interval in seconds."),
    cfg.IntOpt("pure_replica_retention_short_term_default", default=14400,
               help="Retain all snapshots on target for this "
                    "time (in seconds.)"),
    cfg.IntOpt("pure_replica_retention_long_term_per_day_default", default=3,
               help="Retain how many snapshots for each day."),
    cfg.IntOpt("pure_replica_retention_long_term_default", default=7,
               help="Retain snapshots per day on target for this time "
                    "(in days.)"),
    cfg.BoolOpt("pure_eradicate_on_delete",
                default=False,
                help="When enabled, all Pure volumes, snapshots, and "
                     "protection groups will be eradicated at the time of "
                     "deletion in Cinder. Data will NOT be recoverable after "
                     "a delete with this set to True! When disabled, volumes "
                     "and snapshots will go into pending eradication state "
                     "and can be recovered."
                )
]

CONF = cfg.CONF
CONF.register_opts(PURE_OPTS)

INVALID_CHARACTERS = re.compile(r"[^-a-zA-Z0-9]")
GENERATED_NAME = re.compile(r".*-[a-f0-9]{32}-cinder$")

REPLICATION_CG_NAME = "cinder-group"

CHAP_SECRET_KEY = "PURE_TARGET_CHAP_SECRET"

ERR_MSG_NOT_EXIST = "does not exist"
ERR_MSG_PENDING_ERADICATION = "has been destroyed"
ERR_MSG_ALREADY_EXISTS = "already exists"
ERR_MSG_COULD_NOT_BE_FOUND = "could not be found"
ERR_MSG_ALREADY_INCLUDES = "already includes"
ERR_MSG_ALREADY_ALLOWED = "already allowed on"
ERR_MSG_NOT_CONNECTED = "is not connected"
ERR_MSG_ALREADY_BELONGS = "already belongs to"

EXTRA_SPECS_REPL_ENABLED = "replication_enabled"

CONNECT_LOCK_NAME = 'PureVolumeDriver_connect'


UNMANAGED_SUFFIX = '-unmanaged'
MANAGE_SNAP_REQUIRED_API_VERSIONS = ['1.4', '1.5']
REPLICATION_REQUIRED_API_VERSIONS = ['1.3', '1.4', '1.5']

REPL_SETTINGS_PROPAGATE_RETRY_INTERVAL = 5  # 5 seconds
REPL_SETTINGS_PROPAGATE_MAX_RETRIES = 36  # 36 * 5 = 180 seconds


def log_debug_trace(f):
    def wrapper(*args, **kwargs):
        cls_name = args[0].__class__.__name__
        method_name = "%(cls_name)s.%(method)s" % {"cls_name": cls_name,
                                                   "method": f.__name__}
        LOG.debug("Enter " + method_name)
        result = f(*args, **kwargs)
        LOG.debug("Leave " + method_name)
        return result

    return wrapper


class PureBaseVolumeDriver(san.SanDriver):
    """Performs volume management on Pure Storage FlashArray."""

    SUPPORTED_REST_API_VERSIONS = ['1.2', '1.3', '1.4', '1.5']

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureBaseVolumeDriver, self).__init__(execute=execute, *args,
                                                   **kwargs)
        self.configuration.append_config_values(PURE_OPTS)
        self._array = None
        self._storage_protocol = None
        self._backend_name = (self.configuration.volume_backend_name or
                              self.__class__.__name__)
        self._replication_target_arrays = []
        self._replication_pg_name = REPLICATION_CG_NAME
        self._replication_interval = None
        self._replication_retention_short_term = None
        self._replication_retention_long_term = None
        self._replication_retention_long_term_per_day = None
        self._is_replication_enabled = False

    def parse_replication_configs(self):
        self._replication_interval = (
            self.configuration.pure_replica_interval_default)
        self._replication_retention_short_term = (
            self.configuration.pure_replica_retention_short_term_default)
        self._replication_retention_long_term = (
            self.configuration.pure_replica_retention_long_term_default)
        self._replication_retention_long_term_per_day = (
            self.configuration.
            pure_replica_retention_long_term_per_day_default)

        retention_policy = self._generate_replication_retention()
        replication_devices = self.configuration.safe_get(
            'replication_device')
        if replication_devices:
            for replication_device in replication_devices:
                target_device_id = replication_device["target_device_id"]
                san_ip = replication_device["san_ip"]
                api_token = replication_device["api_token"]
                target_array = self._get_flasharray(san_ip, api_token)
                target_array._target_device_id = target_device_id
                LOG.debug("Adding san_ip %(san_ip)s to replication_targets.",
                          {"san_ip": san_ip})
                api_version = target_array.get_rest_version()
                if api_version not in REPLICATION_REQUIRED_API_VERSIONS:
                    msg = _('Unable to do replication with Purity REST '
                            'API version %(api_version)s, requires one of '
                            '%(required_versions)s.') % {
                        'api_version': api_version,
                        'required_versions': REPLICATION_REQUIRED_API_VERSIONS
                    }
                    raise exception.PureDriverException(reason=msg)
                target_array_info = target_array.get()
                target_array.array_name = target_array_info["array_name"]
                target_array.array_id = target_array_info["id"]
                LOG.debug("secondary array name: %s", self._array.array_name)
                LOG.debug("secondary array id: %s", self._array.array_id)
                self._setup_replicated_pgroups(target_array, [self._array],
                                               self._replication_pg_name,
                                               self._replication_interval,
                                               retention_policy)
                self._replication_target_arrays.append(target_array)
        self._setup_replicated_pgroups(self._array,
                                       self._replication_target_arrays,
                                       self._replication_pg_name,
                                       self._replication_interval,
                                       retention_policy)

    def do_setup(self, context):
        """Performs driver initialization steps that could raise exceptions."""
        if purestorage is None:
            msg = _("Missing 'purestorage' python module, ensure the library"
                    " is installed and available.")
            raise exception.PureDriverException(msg)

        # Raises PureDriverException if unable to connect and PureHTTPError
        # if unable to authenticate.
        purestorage.FlashArray.supported_rest_versions = \
            self.SUPPORTED_REST_API_VERSIONS
        self._array = self._get_flasharray(
            self.configuration.san_ip,
            api_token=self.configuration.pure_api_token)
        self._array._target_device_id = self.configuration.config_group
        LOG.debug("Primary array target_device_id: %s",
                  self.configuration.config_group)
        LOG.debug("Primary array name: %s", self._array.array_name)
        LOG.debug("Primary array id: %s", self._array.array_id)
        self.do_setup_replication()

    def do_setup_replication(self):
        replication_devices = self.configuration.safe_get(
            'replication_device')
        if replication_devices:
            self.parse_replication_configs()
            self._is_replication_enabled = True

    def check_for_setup_error(self):
        # Avoid inheriting check_for_setup_error from SanDriver, which checks
        # for san_password or san_private_key, not relevant to our driver.
        pass

    @log_debug_trace
    def create_volume(self, volume):
        """Creates a volume."""
        vol_name = self._get_vol_name(volume)
        vol_size = volume["size"] * units.Gi
        self._array.create_volume(vol_name, vol_size)

        if volume['consistencygroup_id']:
            self._add_volume_to_consistency_group(
                volume['consistencygroup_id'],
                vol_name
            )

        model_update = {'provider_location': self._array.array_id}
        if self._add_and_replicate_if_needed(self._array, volume):
            model_update['replication_status'] = 'enabled'

        return model_update

    @log_debug_trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        vol_name = self._get_vol_name(volume)
        if snapshot['cgsnapshot_id']:
            snap_name = self._get_pgroup_snap_name_from_snapshot(snapshot)
        else:
            snap_name = self._get_snap_name(snapshot)

        if not snap_name:
            msg = _('Unable to determine snapshot name in Purity for snapshot '
                    '%(id)s.') % {'id': snapshot['id']}
            raise exception.PureDriverException(reason=msg)

        # Check which backend the snapshot is on. In case of failover and
        # snapshot on failed over volume the snapshot may be on the
        # secondary array.
        current_array = self._get_current_array(snapshot)

        current_array.copy_volume(snap_name, vol_name)
        self._extend_if_needed(current_array,
                               vol_name,
                               snapshot["volume_size"],
                               volume["size"])

        # TODO(dwilson): figure out if we need to mirror consisgroup on
        # target array if failover has occurred.
        if volume['consistencygroup_id']:
            if current_array.array_id == self._array.array_id:
                self._add_volume_to_consistency_group(
                    volume['consistencygroup_id'],
                    vol_name)
            else:
                LOG.warning(_LW("Volume %s is failed over - skipping addition"
                                " to Consistency Group."), volume["id"])

        model_update = {"provider_location": current_array.array_id}
        if self._add_and_replicate_if_needed(current_array, volume):
            model_update['replication_status'] = 'enabled'

        return model_update

    def _add_and_replicate_if_needed(self, array, volume):
        """Add volume to protection group and create a snapshot."""
        if self._is_volume_replicated_type(volume):
            try:
                array.set_pgroup(self._replication_pg_name,
                                 addvollist=[self._get_vol_name(volume)])
            except purestorage.PureHTTPError as err:
                with excutils.save_and_reraise_exception() as ctxt:
                    if (err.code == 400 and
                            ERR_MSG_ALREADY_BELONGS in err.text):
                        # Happens if the volume already added to PG.
                        ctxt.reraise = False
                        LOG.warning(_LW("Adding Volume to Protection Group "
                                        "failed with message: %s"), err.text)
            array.create_pgroup_snapshot(self._replication_pg_name,
                                         replicate_now=True,
                                         apply_retention=True)
            return True
        else:
            return False

    @log_debug_trace
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_name = self._get_vol_name(volume)
        src_name = self._get_vol_name(src_vref)

        # Check which backend the source volume is on. In case of failover
        # the source volume may be on the secondary array.
        current_array = self._get_current_array(src_vref)
        current_array.copy_volume(src_name, vol_name)
        self._extend_if_needed(current_array,
                               vol_name,
                               src_vref["size"],
                               volume["size"])

        # TODO(dwilson): figure out if we need to mirror consisgroup on
        # target array if failover has occurred.
        if volume['consistencygroup_id']:
            if current_array.array_id == self._array.array_id:
                self._add_volume_to_consistency_group(
                    volume['consistencygroup_id'],
                    vol_name)
            else:
                LOG.warning(_LW("Volume %s is failed over - skipping addition"
                                " to Consistency Group."), volume["id"])

        model_update = {"provider_location": current_array.array_id}
        if self._add_and_replicate_if_needed(current_array, volume):
            model_update['replication_status'] = 'enabled'

        return model_update

    def _extend_if_needed(self, array, vol_name, src_size, vol_size):
        """Extend the volume from size src_size to size vol_size."""
        if vol_size > src_size:
            vol_size = vol_size * units.Gi
            array.extend_volume(vol_name, vol_size)

    @log_debug_trace
    def delete_volume(self, volume):
        """Disconnect all hosts and delete the volume"""
        vol_name = self._get_vol_name(volume)
        current_array = self._get_current_array(volume)
        try:
            connected_hosts = current_array.list_volume_private_connections(
                vol_name)
            for host_info in connected_hosts:
                host_name = host_info["host"]
                self._disconnect_host(current_array, host_name, vol_name)
            current_array.destroy_volume(vol_name)
            if self.configuration.pure_eradicate_on_delete:
                current_array.eradicate_volume(vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_NOT_EXIST in err.text):
                    # Happens if the volume does not exist.
                    ctxt.reraise = False
                    LOG.warning(_LW("Volume deletion failed with message: %s"),
                                err.text)

    @log_debug_trace
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array(snapshot)
        vol_name, snap_suff = self._get_snap_name(snapshot).split(".")
        current_array.create_snapshot(vol_name, suffix=snap_suff)
        return {'provider_location': current_array.array_id}

    @log_debug_trace
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array(snapshot)

        snap_name = self._get_snap_name(snapshot)
        try:
            current_array.destroy_volume(snap_name)
            if self.configuration.pure_eradicate_on_delete:
                current_array.eradicate_volume(snap_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and (
                        ERR_MSG_NOT_EXIST in err.text):
                    # Happens if the snapshot does not exist.
                    ctxt.reraise = False
                    LOG.warning(_LW("Snapshot deletion failed with "
                                    "message: %s"), err.text)

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        pass

    def initialize_connection(self, volume, connector, initiator_data=None):
        """Connect the volume to the specified initiator in Purity.

        This implementation is specific to the host type (iSCSI, FC, etc).
        """
        raise NotImplementedError

    def _get_host(self, array, connector):
        """Get a Purity Host that corresponds to the host in the connector.

        This implementation is specific to the host type (iSCSI, FC, etc).
        """
        raise NotImplementedError

    @utils.synchronized(CONNECT_LOCK_NAME, external=True)
    def _disconnect(self, array, volume, connector, **kwargs):
        vol_name = self._get_vol_name(volume)
        host = self._get_host(array, connector)
        if host:
            host_name = host["name"]
            result = self._disconnect_host(array, host_name, vol_name)
        else:
            LOG.error(_LE("Unable to disconnect host from volume, could not "
                          "determine Purity host"))
            result = False

        return result

    @log_debug_trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection."""
        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array(volume)
        self._disconnect(current_array, volume, connector, **kwargs)

    @log_debug_trace
    def _disconnect_host(self, array, host_name, vol_name):
        """Return value indicates if host was deleted on array or not"""
        try:
            array.disconnect_host(host_name, vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and ERR_MSG_NOT_CONNECTED in err.text:
                    # Happens if the host and volume are not connected.
                    ctxt.reraise = False
                    LOG.error(_LE("Disconnection failed with message: "
                                  "%(msg)s."), {"msg": err.text})
        if (GENERATED_NAME.match(host_name) and
                not array.list_host_connections(host_name, private=True)):
            LOG.info(_LI("Deleting unneeded host %(host_name)r."),
                     {"host_name": host_name})
            try:
                array.delete_host(host_name)
            except purestorage.PureHTTPError as err:
                with excutils.save_and_reraise_exception() as ctxt:
                    if err.code == 400 and ERR_MSG_NOT_EXIST in err.text:
                        # Happens if the host is already deleted.
                        # This is fine though, just treat it as a warning.
                        ctxt.reraise = False
                        LOG.warning(_LW("Purity host deletion failed: "
                                        "%(msg)s."), {"msg": err.text})
            return True

        return False

    @log_debug_trace
    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service.

        If 'refresh' is True, run the update first.
        """

        if refresh:
            LOG.debug("Updating volume stats.")
            self._update_stats()
        return self._stats

    def _update_stats(self):
        """Set self._stats with relevant information."""

        # Collect info from the array
        space_info = self._array.get(space=True)
        perf_info = self._array.get(action='monitor')[0]  # Always first index
        hosts = self._array.list_hosts()
        snaps = self._array.list_volumes(snap=True, pending=True)
        pgroups = self._array.list_pgroups(pending=True)

        # Perform some translations and calculations
        total_capacity = float(space_info["capacity"]) / units.Gi
        used_space = float(space_info["total"]) / units.Gi
        free_space = float(total_capacity - used_space)
        prov_space, total_vols = self._get_provisioned_space()
        total_hosts = len(hosts)
        total_snaps = len(snaps)
        total_pgroups = len(pgroups)
        provisioned_space = float(prov_space) / units.Gi
        thin_provisioning = self._get_thin_provisioning(provisioned_space,
                                                        used_space)

        # Start with some required info
        data = dict(
            volume_backend_name=self._backend_name,
            vendor_name='Pure Storage',
            driver_version=self.VERSION,
            storage_protocol=self._storage_protocol,
        )

        # Add flags for supported features
        data['consistencygroup_support'] = True
        data['thin_provisioning_support'] = True
        data['multiattach'] = True

        # Add capacity info for scheduler
        data['total_capacity_gb'] = total_capacity
        data['free_capacity_gb'] = free_space
        data['reserved_percentage'] = self.configuration.reserved_percentage
        data['provisioned_capacity'] = provisioned_space
        data['max_over_subscription_ratio'] = thin_provisioning

        # Add the filtering/goodness functions
        data['filter_function'] = self.get_filter_function()
        data['goodness_function'] = self.get_goodness_function()

        # Add array metadata counts for filtering and weighing functions
        data['total_volumes'] = total_vols
        data['total_snapshots'] = total_snaps
        data['total_hosts'] = total_hosts
        data['total_pgroups'] = total_pgroups

        # Add performance stats for filtering and weighing functions
        #  IOPS
        data['writes_per_sec'] = perf_info['writes_per_sec']
        data['reads_per_sec'] = perf_info['reads_per_sec']

        #  Bandwidth
        data['input_per_sec'] = perf_info['input_per_sec']
        data['output_per_sec'] = perf_info['output_per_sec']

        #  Latency
        data['usec_per_read_op'] = perf_info['usec_per_read_op']
        data['usec_per_write_op'] = perf_info['usec_per_write_op']
        data['queue_depth'] = perf_info['queue_depth']

        data["replication_enabled"] = self._is_replication_enabled
        data["replication_type"] = ["async"]
        data["replication_count"] = len(self._replication_target_arrays)
        self._stats = data

    def _get_provisioned_space(self):
        """Sum up provisioned size of all volumes on array"""
        volumes = self._array.list_volumes(pending=True)
        return sum(item["size"] for item in volumes), len(volumes)

    def _get_thin_provisioning(self, provisioned_space, used_space):
        """Get the current value for the thin provisioning ratio.

        If pure_automatic_max_oversubscription_ratio is True we will calculate
        a value, if not we will respect the configuration option for the
        max_over_subscription_ratio.
        """
        if (self.configuration.pure_automatic_max_oversubscription_ratio and
                used_space != 0 and provisioned_space != 0):
            # If array is empty we can not calculate a max oversubscription
            # ratio. In this case we look to the config option as a starting
            # point. Once some volumes are actually created and some data is
            # stored on the array a much more accurate number will be
            # presented based on current usage.
            thin_provisioning = provisioned_space / used_space
        else:
            thin_provisioning = self.configuration.max_over_subscription_ratio

        return thin_provisioning

    @log_debug_trace
    def extend_volume(self, volume, new_size):
        """Extend volume to new_size."""

        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array(volume)

        vol_name = self._get_vol_name(volume)
        new_size = new_size * units.Gi
        current_array.extend_volume(vol_name, new_size)

    def _add_volume_to_consistency_group(self, consistencygroup_id, vol_name):
        pgroup_name = self._get_pgroup_name_from_id(consistencygroup_id)
        self._array.set_pgroup(pgroup_name, addvollist=[vol_name])

    @log_debug_trace
    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""

        self._array.create_pgroup(self._get_pgroup_name_from_id(group.id))

        model_update = {'status': fields.ConsistencyGroupStatus.AVAILABLE}
        return model_update

    def _create_cg_from_cgsnap(self, volumes, snapshots):
        """Creates a new consistency group from a cgsnapshot.

        The new volumes will be consistent with the snapshot.
        """
        for volume, snapshot in zip(volumes, snapshots):
            self.create_volume_from_snapshot(volume, snapshot)

    def _create_cg_from_cg(self, group, source_group, volumes, source_vols):
        """Creates a new consistency group from an existing cg.

        The new volumes will be in a consistent state, but this requires
        taking a new temporary group snapshot and cloning from that.
        """
        pgroup_name = self._get_pgroup_name_from_id(source_group.id)
        tmp_suffix = '%s-tmp' % uuid.uuid4()
        tmp_pgsnap_name = '%(pgroup_name)s.%(pgsnap_suffix)s' % {
            'pgroup_name': pgroup_name,
            'pgsnap_suffix': tmp_suffix,
        }
        LOG.debug('Creating temporary Protection Group snapshot %(snap_name)s '
                  'while cloning Consistency Group %(source_group)s.',
                  {'snap_name': tmp_pgsnap_name,
                   'source_group': source_group.id})
        self._array.create_pgroup_snapshot(pgroup_name, suffix=tmp_suffix)
        try:
            for source_vol, cloned_vol in zip(source_vols, volumes):
                source_snap_name = self._get_pgroup_vol_snap_name(
                    pgroup_name,
                    tmp_suffix,
                    self._get_vol_name(source_vol)
                )
                cloned_vol_name = self._get_vol_name(cloned_vol)
                self._array.copy_volume(source_snap_name, cloned_vol_name)
                self._add_volume_to_consistency_group(
                    group.id,
                    cloned_vol_name
                )
        finally:
            self._delete_pgsnapshot(tmp_pgsnap_name)

    @log_debug_trace
    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        self.create_consistencygroup(context, group)
        if cgsnapshot and snapshots:
            self._create_cg_from_cgsnap(volumes,
                                        snapshots)
        elif source_cg:
            self._create_cg_from_cg(group, source_cg, volumes, source_vols)

        return_volumes = []
        for volume in volumes:
            return_volume = {'id': volume.id, 'status': 'available',
                             'provider_location': self._array.array_id}
            return_volumes.append(return_volume)
        model_update = {'status': 'available'}
        return model_update, return_volumes

    @log_debug_trace
    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group."""

        try:
            pgroup_name = self._get_pgroup_name_from_id(group.id)
            self._array.destroy_pgroup(pgroup_name)
            if self.configuration.pure_eradicate_on_delete:
                self._array.eradicate_pgroup(pgroup_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        (ERR_MSG_PENDING_ERADICATION in err.text or
                         ERR_MSG_NOT_EXIST in err.text)):
                    # Treat these as a "success" case since we are trying
                    # to delete them anyway.
                    ctxt.reraise = False
                    LOG.warning(_LW("Unable to delete Protection Group: %s"),
                                err.text)

        volume_updates = []
        for volume in volumes:
            self.delete_volume(volume)
            volume_updates.append({
                'id': volume.id,
                'status': 'deleted'
            })

        model_update = {'status': group['status']}

        return model_update, volume_updates

    @log_debug_trace
    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):

        pgroup_name = self._get_pgroup_name_from_id(group.id)
        if add_volumes:
            addvollist = [self._get_vol_name(vol) for vol in add_volumes]
        else:
            addvollist = []

        if remove_volumes:
            remvollist = [self._get_vol_name(vol) for vol in remove_volumes]
        else:
            remvollist = []

        self._array.set_pgroup(pgroup_name, addvollist=addvollist,
                               remvollist=remvollist)

        return None, None, None

    @log_debug_trace
    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot."""

        cg_id = cgsnapshot.consistencygroup_id
        pgroup_name = self._get_pgroup_name_from_id(cg_id)
        pgsnap_suffix = self._get_pgroup_snap_suffix(cgsnapshot)
        self._array.create_pgroup_snapshot(pgroup_name, suffix=pgsnap_suffix)

        snapshot_updates = []
        for snapshot in snapshots:
            snapshot_updates.append({
                'id': snapshot.id,
                'status': 'available',
                'provider_location': self._array.array_id
            })

        model_update = {'status': 'available'}

        return model_update, snapshot_updates

    def _delete_pgsnapshot(self, pgsnap_name):
        try:
            # FlashArray.destroy_pgroup is also used for deleting
            # pgroup snapshots. The underlying REST API is identical.
            self._array.destroy_pgroup(pgsnap_name)
            if self.configuration.pure_eradicate_on_delete:
                self._array.eradicate_pgroup(pgsnap_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        (ERR_MSG_PENDING_ERADICATION in err.text or
                         ERR_MSG_NOT_EXIST in err.text)):
                    # Treat these as a "success" case since we are trying
                    # to delete them anyway.
                    ctxt.reraise = False
                    LOG.warning(_LW("Unable to delete Protection Group "
                                    "Snapshot: %s"), err.text)

    @log_debug_trace
    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot."""

        pgsnap_name = self._get_pgroup_snap_name(cgsnapshot)
        self._delete_pgsnapshot(pgsnap_name)

        snapshot_updates = []
        for snapshot in snapshots:
            snapshot_updates.append({
                'id': snapshot.id,
                'status': 'deleted',
            })

        model_update = {'status': cgsnapshot.status}

        return model_update, snapshot_updates

    def _validate_manage_existing_ref(self, existing_ref, is_snap=False):
        """Ensure that an existing_ref is valid and return volume info

        If the ref is not valid throw a ManageExistingInvalidReference
        exception with an appropriate error.

        Will return volume or snapshot information from the array for
        the object specified by existing_ref.
        """
        if "name" not in existing_ref or not existing_ref["name"]:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("manage_existing requires a 'name'"
                         " key to identify an existing volume."))

        if is_snap:
            # Purity snapshot names are prefixed with the source volume name.
            ref_vol_name, ref_snap_suffix = existing_ref['name'].split('.')
        else:
            ref_vol_name = existing_ref['name']

        try:
            volume_info = self._array.get_volume(ref_vol_name, snap=is_snap)
            if volume_info:
                if is_snap:
                    for snap in volume_info:
                        if snap['name'] == existing_ref['name']:
                            return snap
                else:
                    return volume_info
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_NOT_EXIST in err.text):
                    ctxt.reraise = False

        # If volume information was unable to be retrieved we need
        # to throw a Invalid Reference exception.
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref,
            reason=_("Unable to find Purity ref with name=%s") % ref_vol_name)

    @log_debug_trace
    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        We expect a volume name in the existing_ref that matches one in Purity.
        """

        self._validate_manage_existing_ref(existing_ref)

        ref_vol_name = existing_ref['name']

        connected_hosts = \
            self._array.list_volume_private_connections(ref_vol_name)
        if len(connected_hosts) > 0:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("%(driver)s manage_existing cannot manage a volume "
                         "connected to hosts. Please disconnect this volume "
                         "from existing hosts before importing"
                         ) % {'driver': self.__class__.__name__})
        new_vol_name = self._get_vol_name(volume)
        LOG.info(_LI("Renaming existing volume %(ref_name)s to %(new_name)s"),
                 {"ref_name": ref_vol_name, "new_name": new_vol_name})
        self._rename_volume_object(ref_vol_name,
                                   new_vol_name,
                                   raise_not_exist=True)
        return None

    @log_debug_trace
    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        We expect a volume name in the existing_ref that matches one in Purity.
        """

        volume_info = self._validate_manage_existing_ref(existing_ref)
        size = int(math.ceil(float(volume_info["size"]) / units.Gi))

        return size

    def _rename_volume_object(self, old_name, new_name, raise_not_exist=False):
        """Rename a volume object (could be snapshot) in Purity.

        This will not raise an exception if the object does not exist
        """
        try:
            self._array.rename_volume(old_name, new_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_NOT_EXIST in err.text):
                    ctxt.reraise = raise_not_exist
                    LOG.warning(_LW("Unable to rename %(old_name)s, error "
                                    "message: %(error)s"),
                                {"old_name": old_name, "error": err.text})
        return new_name

    @log_debug_trace
    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        The volume will be renamed with "-unmanaged" as a suffix
        """

        vol_name = self._get_vol_name(volume)
        unmanaged_vol_name = vol_name + UNMANAGED_SUFFIX
        LOG.info(_LI("Renaming existing volume %(ref_name)s to %(new_name)s"),
                 {"ref_name": vol_name, "new_name": unmanaged_vol_name})
        self._rename_volume_object(vol_name, unmanaged_vol_name)

    def _verify_manage_snap_api_requirements(self):
        api_version = self._array.get_rest_version()
        if api_version not in MANAGE_SNAP_REQUIRED_API_VERSIONS:
            msg = _('Unable to do manage snapshot operations with Purity REST '
                    'API version %(api_version)s, requires '
                    '%(required_versions)s.') % {
                'api_version': api_version,
                'required_versions': MANAGE_SNAP_REQUIRED_API_VERSIONS
            }
            raise exception.PureDriverException(reason=msg)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        We expect a snapshot name in the existing_ref that matches one in
        Purity.
        """
        self._verify_manage_snap_api_requirements()
        self._validate_manage_existing_ref(existing_ref, is_snap=True)
        ref_snap_name = existing_ref['name']
        new_snap_name = self._get_snap_name(snapshot)
        LOG.info(_LI("Renaming existing snapshot %(ref_name)s to "
                     "%(new_name)s"), {"ref_name": ref_snap_name,
                                       "new_name": new_snap_name})
        self._rename_volume_object(ref_snap_name,
                                   new_snap_name,
                                   raise_not_exist=True)
        return None

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing.

        We expect a snapshot name in the existing_ref that matches one in
        Purity.
        """
        self._verify_manage_snap_api_requirements()
        snap_info = self._validate_manage_existing_ref(existing_ref,
                                                       is_snap=True)
        size = int(math.ceil(float(snap_info["size"]) / units.Gi))
        return size

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        We expect a snapshot name in the existing_ref that matches one in
        Purity.
        """
        self._verify_manage_snap_api_requirements()
        snap_name = self._get_snap_name(snapshot)
        unmanaged_snap_name = snap_name + UNMANAGED_SUFFIX
        LOG.info(_LI("Renaming existing snapshot %(ref_name)s to "
                     "%(new_name)s"), {"ref_name": snap_name,
                                       "new_name": unmanaged_snap_name})
        self._rename_volume_object(snap_name, unmanaged_snap_name)

    @staticmethod
    def _get_flasharray(san_ip, api_token, rest_version=None):
        array = purestorage.FlashArray(san_ip,
                                       api_token=api_token,
                                       rest_version=rest_version)
        array_info = array.get()
        array.array_name = array_info["array_name"]
        array.array_id = array_info["id"]
        LOG.debug("connected to %(array_name)s with REST API %(api_version)s",
                  {"array_name": array.array_name,
                   "api_version": array._rest_version})
        return array

    @staticmethod
    def _get_vol_name(volume):
        """Return the name of the volume Purity will use."""
        return volume["name"] + "-cinder"

    @staticmethod
    def _get_snap_name(snapshot):
        """Return the name of the snapshot that Purity will use."""
        return "%s-cinder.%s" % (snapshot["volume_name"], snapshot["name"])

    @staticmethod
    def _get_pgroup_name_from_id(id):
        return "consisgroup-%s-cinder" % id

    @staticmethod
    def _get_pgroup_snap_suffix(cgsnapshot):
        return "cgsnapshot-%s-cinder" % cgsnapshot.id

    @classmethod
    def _get_pgroup_snap_name(cls, cgsnapshot):
        """Return the name of the pgroup snapshot that Purity will use"""
        cg_id = cgsnapshot.consistencygroup_id
        return "%s.%s" % (cls._get_pgroup_name_from_id(cg_id),
                          cls._get_pgroup_snap_suffix(cgsnapshot))

    @staticmethod
    def _get_pgroup_vol_snap_name(pg_name, pgsnap_suffix, volume_name):
        return "%(pgroup_name)s.%(pgsnap_suffix)s.%(volume_name)s" % {
            'pgroup_name': pg_name,
            'pgsnap_suffix': pgsnap_suffix,
            'volume_name': volume_name,
        }

    def _get_pgroup_snap_name_from_snapshot(self, snapshot):
        """Return the name of the snapshot that Purity will use."""

        # TODO(patrickeast): Remove DB calls once the cgsnapshot objects are
        # available to use and can be associated with the snapshot objects.
        ctxt = context.get_admin_context()
        cgsnapshot = self.db.cgsnapshot_get(ctxt, snapshot.cgsnapshot_id)

        pg_vol_snap_name = "%(group_snap)s.%(volume_name)s-cinder" % {
            'group_snap': self._get_pgroup_snap_name(cgsnapshot),
            'volume_name': snapshot.volume_name
        }
        return pg_vol_snap_name

    @staticmethod
    def _generate_purity_host_name(name):
        """Return a valid Purity host name based on the name passed in."""
        if len(name) > 23:
            name = name[0:23]
        name = INVALID_CHARACTERS.sub("-", name)
        name = name.lstrip("-")
        return "{name}-{uuid}-cinder".format(name=name, uuid=uuid.uuid4().hex)

    @staticmethod
    def _connect_host_to_vol(array, host_name, vol_name):
        connection = None
        try:
            connection = array.connect_host(host_name, vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_ALREADY_EXISTS in err.text):
                    # Happens if the volume is already connected to the host.
                    # Treat this as a success.
                    ctxt.reraise = False
                    LOG.debug("Volume connection already exists for Purity "
                              "host with message: %s", err.text)

                    # Get the info for the existing connection.
                    connected_hosts = (
                        array.list_volume_private_connections(vol_name))
                    for host_info in connected_hosts:
                        if host_info["host"] == host_name:
                            connection = host_info
                            break
        if not connection:
            raise exception.PureDriverException(
                reason=_("Unable to connect or find connection to host"))

        return connection

    def retype(self, context, volume, new_type, diff, host):
        """Retype from one volume type to another on the same backend.

        For a Pure Array there is currently no differentiation between types
        of volumes other than some being part of a protection group to be
        replicated.
        """
        previous_vol_replicated = self._is_volume_replicated_type(volume)

        new_vol_replicated = False
        if new_type:
            specs = new_type.get("extra_specs")
            if specs and EXTRA_SPECS_REPL_ENABLED in specs:
                replication_capability = specs[EXTRA_SPECS_REPL_ENABLED]
                # Do not validate settings, ignore invalid.
                new_vol_replicated = (replication_capability == "<is> True")

        if previous_vol_replicated and not new_vol_replicated:
            # Remove from protection group.
            self.replication_disable(context, volume)
        elif not previous_vol_replicated and new_vol_replicated:
            # Add to protection group.
            self.replication_enable(context, volume)

        return True, None

    # Replication v2
    @log_debug_trace
    def replication_enable(self, context, volume):
        """Enable replication on the given volume."""

        # Get current array in case we have failed over.
        current_array = self._get_current_array(volume)
        LOG.debug("Enabling replication for volume %(id)s residing on "
                  "array %(target_device_id)s." %
                  {"id": volume["id"],
                   "target_device_id": current_array._target_device_id})

        model_update = {"provider_location": current_array.array_id}
        if self._add_and_replicate_if_needed(current_array, volume):
            model_update['replication_status'] = 'enabled'

        return model_update

    @log_debug_trace
    def replication_disable(self, context, volume):
        """Disable replication on the given volume."""

        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array(volume)
        LOG.debug("Disabling replication for volume %(id)s residing on "
                  "array %(target_device_id)s." %
                  {"id": volume["id"],
                   "target_device_id": current_array._target_device_id})

        try:
            current_array.set_pgroup(self._replication_pg_name,
                                     remvollist=(
                                         [self._get_vol_name(volume)]))
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_COULD_NOT_BE_FOUND in err.text):
                    ctxt.reraise = False
                    LOG.warning(_LW("Disable replication on volume failed: "
                                    "already disabled: %s"), err.text)
                else:
                    LOG.error(_LE("Disable replication on volume failed with "
                                  "message: %s"), err.text)
        return {'replication_status': 'disabled'}

    @log_debug_trace
    def replication_failover(self, context, volume, secondary):
        """Failover volume to the secondary array

        This action will not affect the original volume in any
        way and it will stay as is. If a subsequent replication_enable
        and failover is performed we will simply overwrite the original
        volume.
        """
        vol_name = self._get_vol_name(volume)
        # Get the latest replicated snapshot for src_name volume.
        # Find "source": "<source_array>:<vol_name>" in snapshot attributes.
        secondary_array = None
        current_array, failover_candidate_arrays = self._get_arrays(volume)
        LOG.debug("Failover replication for volume %(id)s residing on "
                  "array %(primary)s to %(secondary)s." %
                  {"id": volume["id"],
                   "primary": current_array._target_device_id,
                   "secondary": secondary})

        if not failover_candidate_arrays:
                raise exception.PureDriverException(
                    reason=_("Unable to failover volume %(volume)s, no "
                             "secondary targets configured.") %
                    {'volume': vol_name})

        if secondary:
            for array in failover_candidate_arrays:
                if array._target_device_id == secondary:
                    secondary_array = array
        if not secondary_array:
            raise exception.PureDriverException(
                reason=_("Unable to determine secondary_array from supplied "
                         "secondary: %(secondary)s.") %
                {"secondary": secondary}
            )
        LOG.debug("Starting failover from %(primary)s to %(secondary)s",
                  {"primary": current_array.array_name,
                   "secondary": secondary_array.array_name})

        vol_source_name_to_find = "%s:%s" % (current_array.array_name,
                                             vol_name)
        volume_snap = self._get_latest_replicated_vol_snap(
            secondary_array,
            current_array.array_name,
            self._replication_pg_name,
            vol_name)
        if not volume_snap:
            raise exception.PureDriverException(
                reason=_("Unable to find volume snapshot for %s.")
                % vol_source_name_to_find)
        # Create volume from snapshot.
        secondary_array.copy_volume(volume_snap["name"],
                                    vol_name,
                                    overwrite=True)
        # New volume inherits replicated type, but is not actively replicating.
        model_update = {"provider_location": secondary_array.array_id,
                        "replication_status": "failed-over"}
        return model_update

    @log_debug_trace
    def list_replication_targets(self, context, vref):
        """Return all connected arrays that are active."""
        data = {'volume_id': vref['id']}
        status = {}
        current_array, failover_candidate_arrays = self._get_arrays(vref)
        LOG.debug("List replication targets for volume %(id)s residing on "
                  "array %(primary)s." %
                  {"id": vref["id"],
                   "primary": current_array._target_device_id})
        pgroup = current_array.get_pgroup(self._replication_pg_name)
        volume_name = self._get_vol_name(vref)
        volumes_in_pgroup = pgroup["volumes"]
        is_vol_in_pgroup = (volumes_in_pgroup and
                            volume_name in pgroup["volumes"])
        # Purity returns None instead of empty list if no targets
        target_arrays = pgroup.get("targets") or []
        for target_array in target_arrays:
            if is_vol_in_pgroup:
                status[target_array["name"]] = target_array["allowed"]
            else:
                status[target_array["name"]] = False

        remote_targets = []

        for flash_array in (failover_candidate_arrays or []):
            if flash_array.array_name in status:
                remote_targets.append(
                    {'target_device_id': flash_array._target_device_id})

        data["targets"] = remote_targets
        return data

    def get_replication_updates(self, context):
        # currently, the manager does not use these updates.
        # TODO(mudassir): update this when implemented in manager
        return []

    def _get_current_array(self, volume):
        current_array, _ = self._get_arrays(volume)
        return current_array

    def _get_arrays(self, volume):
        """Returns the current and secondary arrays for a volume or snapshot

        :param volume: volume or snapshot object
        :return: the current_array, list of secondary_arrays for the volume
        """
        current_array_id = volume.get("provider_location", None)
        # Default to configured current array, including case when
        # provider_location is misconfigured.
        primary_array = self._array
        secondary_arrays = []

        if self._replication_target_arrays:
            secondary_arrays = self._replication_target_arrays

        if current_array_id and not current_array_id == self._array.array_id:
            for flash_array in self._replication_target_arrays:
                if flash_array.array_id == current_array_id:
                    primary_array = flash_array
                    secondary_arrays = [self._array]
                    break

        return primary_array, secondary_arrays

    def _does_pgroup_exist(self, array, pgroup_name):
        """Return True/False"""
        try:
            array.get_pgroup(pgroup_name)
            return True
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and ERR_MSG_NOT_EXIST in err.text:
                    ctxt.reraise = False
                    return False
            # Any unexpected exception to be handled by caller.

    @log_debug_trace
    @utils.retry(exception.PureDriverException,
                 REPL_SETTINGS_PROPAGATE_RETRY_INTERVAL,
                 REPL_SETTINGS_PROPAGATE_MAX_RETRIES)
    def _wait_until_target_group_setting_propagates(
            self, target_array, pgroup_name_on_target):
        # Wait for pgroup to show up on target array.
        if self._does_pgroup_exist(target_array, pgroup_name_on_target):
            return
        else:
            raise exception.PureDriverException(message=
                                                _('Protection Group not '
                                                  'ready.'))

    @log_debug_trace
    @utils.retry(exception.PureDriverException,
                 REPL_SETTINGS_PROPAGATE_RETRY_INTERVAL,
                 REPL_SETTINGS_PROPAGATE_MAX_RETRIES)
    def _wait_until_source_array_allowed(self, source_array, pgroup_name):
        result = source_array.get_pgroup(pgroup_name)
        if result["targets"][0]["allowed"]:
            return
        else:
            raise exception.PureDriverException(message=_('Replication not '
                                                          'allowed yet.'))

    def _get_pgroup_name_on_target(self, source_array_name, pgroup_name):
        return "%s:%s" % (source_array_name, pgroup_name)

    @log_debug_trace
    def _setup_replicated_pgroups(self, primary, secondaries, pg_name,
                                  replication_interval, retention_policy):
            self._create_protection_group_if_not_exist(
                primary, pg_name)

            # Apply retention policies to a protection group.
            # These retention policies will be applied on the replicated
            # snapshots on the target array.
            primary.set_pgroup(pg_name, **retention_policy)

            # Configure replication propagation frequency on a
            # protection group.
            primary.set_pgroup(pg_name,
                               replicate_frequency=replication_interval)
            for target_array in secondaries:
                try:
                    # Configure PG to replicate to target_array.
                    primary.set_pgroup(pg_name,
                                       addtargetlist=[target_array.array_name])
                except purestorage.PureHTTPError as err:
                    with excutils.save_and_reraise_exception() as ctxt:
                        if err.code == 400 and (
                                ERR_MSG_ALREADY_INCLUDES
                                in err.text):
                            ctxt.reraise = False
                            LOG.info(_LI("Skipping add target %(target_array)s"
                                         " to protection group %(pgname)s"
                                         " since it's already added."),
                                     {"target_array": target_array.array_name,
                                      "pgname": pg_name})

            # Wait until "Target Group" setting propagates to target_array.
            pgroup_name_on_target = self._get_pgroup_name_on_target(
                primary.array_name, pg_name)

            for target_array in secondaries:
                self._wait_until_target_group_setting_propagates(
                    target_array,
                    pgroup_name_on_target)
                try:
                    # Configure the target_array to allow replication from the
                    # PG on source_array.
                    target_array.set_pgroup(pgroup_name_on_target,
                                            allowed=True)
                except purestorage.PureHTTPError as err:
                    with excutils.save_and_reraise_exception() as ctxt:
                        if (err.code == 400 and
                                ERR_MSG_ALREADY_ALLOWED in err.text):
                            ctxt.reraise = False
                            LOG.info(_LI("Skipping allow pgroup %(pgname)s on "
                                         "target array %(target_array)s since "
                                         "it is already allowed."),
                                     {"pgname": pg_name,
                                      "target_array": target_array.array_name})

            # Wait until source array acknowledges previous operation.
            self._wait_until_source_array_allowed(primary, pg_name)
            # Start replication on the PG.
            primary.set_pgroup(pg_name, replicate_enabled=True)

    @log_debug_trace
    def _generate_replication_retention(self):
        """Generates replication retention settings in Purity compatible format

        An example of the settings:
        target_all_for = 14400 (i.e. 4 hours)
        target_per_day = 6
        target_days = 4
        The settings above configure the target array to retain 4 hours of
        the most recent snapshots.
        After the most recent 4 hours, the target will choose 4 snapshots
        per day from the previous 6 days for retention

        :return: a dictionary representing replication retention settings
        """
        replication_retention = dict(
            target_all_for=self._replication_retention_short_term,
            target_per_day=self._replication_retention_long_term_per_day,
            target_days=self._replication_retention_long_term
        )
        return replication_retention

    @log_debug_trace
    def _get_latest_replicated_vol_snap(self,
                                        array,
                                        source_array_name,
                                        pgroup_name,
                                        vol_name):
        # NOTE(patrickeast): This currently requires a call with REST API 1.3
        # if we need to create a temporary FlashArray for this operation.
        api_version = array.get_rest_version()
        LOG.debug("Current REST API for array id %(id)s is %(api_version)s",
                  {"id": array.array_id, "api_version": api_version})
        if api_version != '1.3':
            target_array = self._get_flasharray(array._target,
                                                api_token=array._api_token,
                                                rest_version='1.3')
        else:
            target_array = array

        # Get all protection group snapshots.
        snap_name = "%s:%s" % (source_array_name, pgroup_name)
        LOG.debug("Looking for snap %(snap)s on array id %(array_id)s",
                  {"snap": snap_name, "array_id": target_array.array_id})
        pg_snaps = target_array.get_pgroup(snap_name, snap=True, transfer=True)
        LOG.debug("Retrieved snapshots on target %(pg_snaps)s",
                  {"pg_snaps": pg_snaps})

        # Only use snapshots that are replicated completely.
        pg_snaps_filtered = [s for s in pg_snaps if s["progress"] == 1]
        LOG.debug("Filtered list of snapshots %(pg_snaps_filtered)s",
                  {"pg_snaps_filtered": pg_snaps_filtered})

        # Go through the protection group snapshots, latest first ....
        #   stop when we find required volume snapshot.
        pg_snaps_filtered.sort(key=lambda x: x["created"], reverse=True)
        LOG.debug("Sorted list of snapshots %(pg_snaps_filtered)s",
                  {"pg_snaps_filtered": pg_snaps_filtered})
        volume_snap = None
        vol_snap_source_to_find = "%s:%s" % (source_array_name, vol_name)

        LOG.debug("Searching for snapshot of volume %(vol)s on array "
                  "%(array)s.",
                  {"vol": vol_snap_source_to_find, "array": array.array_name})
        for pg_snap in pg_snaps_filtered:
            # Get volume snapshots inside the replicated PG snapshot.
            volume_snaps = target_array.get_volume(pg_snap["name"],
                                                   snap=True,
                                                   pgroup=True)
            for snap in volume_snaps:
                LOG.debug("Examining snapshot %(snap)s.", {"snap": snap})
                if snap["source"] == vol_snap_source_to_find:
                    volume_snap = snap
                    break
            if volume_snap:  # Found the volume snapshot we needed.
                    LOG.debug("Found snapshot for volume %(vol)s in "
                              "snap %(snap)s.",
                              {"snap": pg_snap["name"],
                               "vol": vol_snap_source_to_find})
                    break
        return volume_snap

    @log_debug_trace
    def _create_protection_group_if_not_exist(self, source_array, pgname):
        try:
            source_array.create_pgroup(pgname)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and ERR_MSG_ALREADY_EXISTS in err.text:
                    # Happens if the PG already exists
                    ctxt.reraise = False
                    LOG.warning(_LW("Skipping creation of PG %s since it "
                                    "already exists."), pgname)
                    # We assume PG has already been setup with correct
                    # replication settings.
                    return
                if err.code == 400 and (
                        ERR_MSG_PENDING_ERADICATION in err.text):
                    ctxt.reraise = False
                    LOG.warning(_LW("Protection group %s is deleted but not"
                                    " eradicated - will recreate."), pgname)
                    source_array.eradicate_pgroup(pgname)
                    source_array.create_pgroup(pgname)

    def _is_volume_replicated_type(self, volume):
        ctxt = context.get_admin_context()
        volume_type = volume_types.get_volume_type(ctxt,
                                                   volume["volume_type_id"])
        replication_flag = False
        specs = volume_type.get("extra_specs")
        if specs and EXTRA_SPECS_REPL_ENABLED in specs:
            replication_capability = specs[EXTRA_SPECS_REPL_ENABLED]
            # Do not validate settings, ignore invalid.
            replication_flag = (replication_capability == "<is> True")
        return replication_flag


class PureISCSIDriver(PureBaseVolumeDriver, san.SanISCSIDriver):

    VERSION = "4.0.0"

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureISCSIDriver, self).__init__(execute=execute, *args, **kwargs)
        self._storage_protocol = "iSCSI"

    def _get_host(self, array, connector):
        """Return dict describing existing Purity host object or None."""
        hosts = array.list_hosts()
        for host in hosts:
            if connector["initiator"] in host["iqn"]:
                return host
        return None

    @log_debug_trace
    def initialize_connection(self, volume, connector, initiator_data=None):
        """Allow connection to connector and return connection info."""
        connection = self._connect(volume, connector, initiator_data)
        target_ports = self._get_target_iscsi_ports()
        multipath = connector.get("multipath", False)

        properties = self._build_connection_properties(connection,
                                                       target_ports,
                                                       multipath)

        if self.configuration.use_chap_auth:
            properties["data"]["auth_method"] = "CHAP"
            properties["data"]["auth_username"] = connection["auth_username"]
            properties["data"]["auth_password"] = connection["auth_password"]

        initiator_update = connection.get("initiator_update", False)
        if initiator_update:
            properties["initiator_update"] = initiator_update

        return properties

    def _build_connection_properties(self, connection, target_ports,
                                     multipath):
        props = {
            "driver_volume_type": "iscsi",
            "data": {
                "target_discovered": False,
                "discard": True,
            },
        }

        port_iter = iter(target_ports)

        target_luns = []
        target_iqns = []
        target_portals = []

        for port in port_iter:
            target_luns.append(connection["lun"])
            target_iqns.append(port["iqn"])
            target_portals.append(port["portal"])

        # If we have multiple ports always report them.
        if target_luns and target_iqns and target_portals:
            props["data"]["target_luns"] = target_luns
            props["data"]["target_iqns"] = target_iqns
            props["data"]["target_portals"] = target_portals

        return props

    def _get_target_iscsi_ports(self):
        """Return list of iSCSI-enabled port descriptions."""
        ports = self._array.list_ports()
        iscsi_ports = [port for port in ports if port["iqn"]]
        if not iscsi_ports:
            raise exception.PureDriverException(
                reason=_("No iSCSI-enabled ports on target array."))
        return iscsi_ports

    @staticmethod
    def _generate_chap_secret():
        return volume_utils.generate_password()

    @classmethod
    def _get_chap_credentials(cls, host, data):
        initiator_updates = None
        username = host
        password = None
        if data:
            for d in data:
                if d["key"] == CHAP_SECRET_KEY:
                    password = d["value"]
                    break
        if not password:
            password = cls._generate_chap_secret()
            initiator_updates = {
                "set_values": {
                    CHAP_SECRET_KEY: password
                }
            }
        return username, password, initiator_updates

    @utils.synchronized(CONNECT_LOCK_NAME, external=True)
    def _connect(self, volume, connector, initiator_data):
        """Connect the host and volume; return dict describing connection."""
        iqn = connector["initiator"]

        if self.configuration.use_chap_auth:
            (chap_username, chap_password, initiator_update) = \
                self._get_chap_credentials(connector['host'], initiator_data)

        current_array = self._get_current_array(volume)
        vol_name = self._get_vol_name(volume)
        host = self._get_host(current_array, connector)

        if host:
            host_name = host["name"]
            LOG.info(_LI("Re-using existing purity host %(host_name)r"),
                     {"host_name": host_name})
            if self.configuration.use_chap_auth:
                if not GENERATED_NAME.match(host_name):
                    LOG.error(_LE("Purity host %(host_name)s is not managed "
                                  "by Cinder and can't have CHAP credentials "
                                  "modified. Remove IQN %(iqn)s from the host "
                                  "to resolve this issue."),
                              {"host_name": host_name,
                               "iqn": connector["initiator"]})
                    raise exception.PureDriverException(
                        reason=_("Unable to re-use a host that is not "
                                 "managed by Cinder with use_chap_auth=True,"))
                elif chap_username is None or chap_password is None:
                    LOG.error(_LE("Purity host %(host_name)s is managed by "
                                  "Cinder but CHAP credentials could not be "
                                  "retrieved from the Cinder database."),
                              {"host_name": host_name})
                    raise exception.PureDriverException(
                        reason=_("Unable to re-use host with unknown CHAP "
                                 "credentials configured."))
        else:
            host_name = self._generate_purity_host_name(connector["host"])
            LOG.info(_LI("Creating host object %(host_name)r with IQN:"
                         " %(iqn)s."), {"host_name": host_name, "iqn": iqn})
            current_array.create_host(host_name, iqnlist=[iqn])

            if self.configuration.use_chap_auth:
                current_array.set_host(host_name,
                                       host_user=chap_username,
                                       host_password=chap_password)

        connection = self._connect_host_to_vol(current_array,
                                               host_name,
                                               vol_name)

        if self.configuration.use_chap_auth:
            connection["auth_username"] = chap_username
            connection["auth_password"] = chap_password

            if initiator_update:
                connection["initiator_update"] = initiator_update

        return connection


class PureFCDriver(PureBaseVolumeDriver, driver.FibreChannelDriver):

    VERSION = "2.0.0"

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureFCDriver, self).__init__(execute=execute, *args, **kwargs)
        self._storage_protocol = "FC"
        self._lookup_service = fczm_utils.create_lookup_service()

    def _get_host(self, array, connector):
        """Return dict describing existing Purity host object or None."""
        hosts = array.list_hosts()
        for host in hosts:
            for wwn in connector["wwpns"]:
                if wwn in str(host["wwn"]).lower():
                    return host

    @staticmethod
    def _get_array_wwns(array):
        """Return list of wwns from the array"""
        ports = array.list_ports()
        return [port["wwn"] for port in ports if port["wwn"]]

    @fczm_utils.AddFCZone
    @log_debug_trace
    def initialize_connection(self, volume, connector, initiator_data=None):
        """Allow connection to connector and return connection info."""
        current_array = self._get_current_array(volume)
        connection = self._connect(volume, connector)
        target_wwns = self._get_array_wwns(current_array)
        init_targ_map = self._build_initiator_target_map(target_wwns,
                                                         connector)
        properties = {
            "driver_volume_type": "fibre_channel",
            "data": {
                'target_discovered': True,
                "target_lun": connection["lun"],
                "target_wwn": target_wwns,
                'initiator_target_map': init_targ_map,
                "discard": True,
            }
        }

        return properties

    @utils.synchronized(CONNECT_LOCK_NAME, external=True)
    def _connect(self, volume, connector):
        """Connect the host and volume; return dict describing connection."""
        wwns = connector["wwpns"]

        current_array = self._get_current_array(volume)
        vol_name = self._get_vol_name(volume)
        host = self._get_host(current_array, connector)

        if host:
            host_name = host["name"]
            LOG.info(_LI("Re-using existing purity host %(host_name)r"),
                     {"host_name": host_name})
        else:
            host_name = self._generate_purity_host_name(connector["host"])
            LOG.info(_LI("Creating host object %(host_name)r with WWN:"
                         " %(wwn)s."), {"host_name": host_name, "wwn": wwns})
            current_array.create_host(host_name, wwnlist=wwns)

        return self._connect_host_to_vol(current_array, host_name, vol_name)

    def _build_initiator_target_map(self, target_wwns, connector):
        """Build the target_wwns and the initiator target map."""
        init_targ_map = {}

        if self._lookup_service:
            # use FC san lookup to determine which NSPs to use
            # for the new VLUN.
            dev_map = self._lookup_service.get_device_mapping_from_network(
                connector['wwpns'],
                target_wwns)

            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(set(
                        init_targ_map[initiator]))
        else:
            init_targ_map = dict.fromkeys(connector["wwpns"], target_wwns)

        return init_targ_map

    @fczm_utils.RemoveFCZone
    @log_debug_trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection."""
        current_array = self._get_current_array(volume)

        no_more_connections = self._disconnect(current_array, volume,
                                               connector, **kwargs)

        properties = {"driver_volume_type": "fibre_channel", "data": {}}

        if no_more_connections:
            target_wwns = self._get_array_wwns(current_array)
            init_targ_map = self._build_initiator_target_map(target_wwns,
                                                             connector)
            properties["data"] = {"target_wwn": target_wwns,
                                  "initiator_target_map": init_targ_map}

        return properties
