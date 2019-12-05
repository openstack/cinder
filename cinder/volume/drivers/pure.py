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

import functools
import math
import platform
import re
import uuid

from distutils import version
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.objects import fields
from cinder.objects import volume_type
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import utils as volume_utils
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
    cfg.IntOpt("pure_replica_interval_default", default=3600,
               help="Snapshot replication interval in seconds."),
    cfg.IntOpt("pure_replica_retention_short_term_default", default=14400,
               help="Retain all snapshots on target for this "
                    "time (in seconds.)"),
    cfg.IntOpt("pure_replica_retention_long_term_per_day_default", default=3,
               help="Retain how many snapshots for each day."),
    cfg.IntOpt("pure_replica_retention_long_term_default", default=7,
               help="Retain snapshots per day on target for this time "
                    "(in days.)"),
    cfg.StrOpt("pure_replication_pg_name", default="cinder-group",
               help="Pure Protection Group name to use for async replication "
                    "(will be created if it does not exist)."),
    cfg.StrOpt("pure_replication_pod_name", default="cinder-pod",
               help="Pure Pod name to use for sync replication "
                    "(will be created if it does not exist)."),
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
CONF.register_opts(PURE_OPTS, group=configuration.SHARED_CONF_GROUP)

INVALID_CHARACTERS = re.compile(r"[^-a-zA-Z0-9]")
GENERATED_NAME = re.compile(r".*-[a-f0-9]{32}-cinder$")

REPLICATION_TYPE_SYNC = "sync"
REPLICATION_TYPE_ASYNC = "async"
REPLICATION_TYPES = [REPLICATION_TYPE_SYNC, REPLICATION_TYPE_ASYNC]

CHAP_SECRET_KEY = "PURE_TARGET_CHAP_SECRET"

ERR_MSG_NOT_EXIST = "does not exist"
ERR_MSG_HOST_NOT_EXIST = "Host " + ERR_MSG_NOT_EXIST
ERR_MSG_NO_SUCH_SNAPSHOT = "No such volume or snapshot"
ERR_MSG_PENDING_ERADICATION = "has been destroyed"
ERR_MSG_ALREADY_EXISTS = "already exists"
ERR_MSG_COULD_NOT_BE_FOUND = "could not be found"
ERR_MSG_ALREADY_INCLUDES = "already includes"
ERR_MSG_ALREADY_ALLOWED = "already allowed on"
ERR_MSG_NOT_CONNECTED = "is not connected"
ERR_MSG_ALREADY_BELONGS = "already belongs to"
ERR_MSG_EXISTING_CONNECTIONS = "cannot be deleted due to existing connections"
ERR_MSG_ALREADY_IN_USE = "already in use"

EXTRA_SPECS_REPL_ENABLED = "replication_enabled"
EXTRA_SPECS_REPL_TYPE = "replication_type"

UNMANAGED_SUFFIX = '-unmanaged'
SYNC_REPLICATION_REQUIRED_API_VERSIONS = ['1.13', '1.14']
ASYNC_REPLICATION_REQUIRED_API_VERSIONS = [
    '1.3', '1.4', '1.5'] + SYNC_REPLICATION_REQUIRED_API_VERSIONS
MANAGE_SNAP_REQUIRED_API_VERSIONS = [
    '1.4', '1.5'] + SYNC_REPLICATION_REQUIRED_API_VERSIONS

REPL_SETTINGS_PROPAGATE_RETRY_INTERVAL = 5  # 5 seconds
REPL_SETTINGS_PROPAGATE_MAX_RETRIES = 36  # 36 * 5 = 180 seconds

HOST_CREATE_MAX_RETRIES = 5

USER_AGENT_BASE = 'OpenStack Cinder'


def pure_driver_debug_trace(f):
    """Log the method entrance and exit including active backend name.

    This should only be used on VolumeDriver class methods. It depends on
    having a 'self' argument that is a PureBaseVolumeDriver.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        driver = args[0]  # self
        cls_name = driver.__class__.__name__
        method_name = "%(cls_name)s.%(method)s" % {"cls_name": cls_name,
                                                   "method": f.__name__}
        backend_name = driver._get_current_array().backend_id
        LOG.debug("[%(backend_name)s] Enter %(method_name)s, args=%(args)s,"
                  " kwargs=%(kwargs)s",
                  {
                      "method_name": method_name,
                      "backend_name": backend_name,
                      "args": args,
                      "kwargs": kwargs,
                  })
        result = f(*args, **kwargs)
        LOG.debug("[%(backend_name)s] Leave %(method_name)s, ret=%(result)s",
                  {
                      "method_name": method_name,
                      "backend_name": backend_name,
                      "result": result,
                  })
        return result

    return wrapper


class PureBaseVolumeDriver(san.SanDriver):
    """Performs volume management on Pure Storage FlashArray."""

    SUPPORTED_REST_API_VERSIONS = ['1.2', '1.3', '1.4', '1.5', '1.13', '1.14']

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Pure_Storage_CI"

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
        self._active_cluster_target_arrays = []
        self._uniform_active_cluster_target_arrays = []
        self._replication_pg_name = None
        self._replication_pod_name = None
        self._replication_interval = None
        self._replication_retention_short_term = None
        self._replication_retention_long_term = None
        self._replication_retention_long_term_per_day = None
        self._async_replication_retention_policy = None
        self._is_replication_enabled = False
        self._is_active_cluster_enabled = False
        self._active_backend_id = kwargs.get('active_backend_id', None)
        self._failed_over_primary_array = None
        self._user_agent = '%(base)s %(class)s/%(version)s (%(platform)s)' % {
            'base': USER_AGENT_BASE,
            'class': self.__class__.__name__,
            'version': self.VERSION,
            'platform': platform.platform()
        }

    @staticmethod
    def get_driver_options():
        return PURE_OPTS

    def parse_replication_configs(self):
        self._replication_pg_name = (
            self.configuration.pure_replication_pg_name)
        self._replication_pod_name = (
            self.configuration.pure_replication_pod_name)
        self._replication_interval = (
            self.configuration.pure_replica_interval_default)
        self._replication_retention_short_term = (
            self.configuration.pure_replica_retention_short_term_default)
        self._replication_retention_long_term = (
            self.configuration.pure_replica_retention_long_term_default)
        self._replication_retention_long_term_per_day = (
            self.configuration.
            pure_replica_retention_long_term_per_day_default)

        self._async_replication_retention_policy = (
            self._generate_replication_retention())

        replication_devices = self.configuration.safe_get(
            'replication_device')

        if replication_devices:
            for replication_device in replication_devices:
                backend_id = replication_device["backend_id"]
                san_ip = replication_device["san_ip"]
                api_token = replication_device["api_token"]
                verify_https = strutils.bool_from_string(
                    replication_device.get("ssl_cert_verify", False))
                ssl_cert_path = replication_device.get("ssl_cert_path", None)
                repl_type = replication_device.get("type",
                                                   REPLICATION_TYPE_ASYNC)
                uniform = strutils.bool_from_string(
                    replication_device.get("uniform", False))

                target_array = self._get_flasharray(
                    san_ip,
                    api_token,
                    verify_https=verify_https,
                    ssl_cert_path=ssl_cert_path
                )

                api_version = target_array.get_rest_version()

                if repl_type == REPLICATION_TYPE_ASYNC:
                    req_api_versions = ASYNC_REPLICATION_REQUIRED_API_VERSIONS
                elif repl_type == REPLICATION_TYPE_SYNC:
                    req_api_versions = SYNC_REPLICATION_REQUIRED_API_VERSIONS
                else:
                    msg = _('Invalid replication type specified:') % repl_type
                    raise exception.PureDriverException(reason=msg)

                if api_version not in req_api_versions:
                    msg = _('Unable to do replication with Purity REST '
                            'API version %(api_version)s, requires one of '
                            '%(required_versions)s.') % {
                        'api_version': api_version,
                        'required_versions':
                            ASYNC_REPLICATION_REQUIRED_API_VERSIONS
                    }
                    raise exception.PureDriverException(reason=msg)

                target_array_info = target_array.get()
                target_array.array_name = target_array_info["array_name"]
                target_array.array_id = target_array_info["id"]
                target_array.replication_type = repl_type
                target_array.backend_id = backend_id
                target_array.uniform = uniform

                LOG.info("Added secondary array: backend_id='%s', name='%s',"
                         " id='%s', type='%s', uniform='%s'",
                         target_array.backend_id,
                         target_array.array_name,
                         target_array.array_id,
                         target_array.replication_type,
                         target_array.uniform)

                self._replication_target_arrays.append(target_array)
                if repl_type == REPLICATION_TYPE_SYNC:
                    self._active_cluster_target_arrays.append(target_array)
                    if target_array.uniform:
                        self._uniform_active_cluster_target_arrays.append(
                            target_array)

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
            api_token=self.configuration.pure_api_token,
            verify_https=self.configuration.driver_ssl_cert_verify,
            ssl_cert_path=self.configuration.driver_ssl_cert_path
        )

        array_info = self._array.get()
        self._array.array_name = array_info["array_name"]
        self._array.array_id = array_info["id"]
        self._array.replication_type = None
        self._array.backend_id = self._backend_name
        self._array.preferred = True
        self._array.uniform = True

        LOG.info("Primary array: backend_id='%s', name='%s', id='%s'",
                 self.configuration.config_group,
                 self._array.array_name,
                 self._array.array_id)

        self.do_setup_replication()

        # If we have failed over at some point we need to adjust our current
        # array based on the one that we have failed over to
        if (self._active_backend_id is not None and
                self._active_backend_id != self._array.backend_id):
            for secondary_array in self._replication_target_arrays:
                if secondary_array.backend_id == self._active_backend_id:
                    self._swap_replication_state(self._array, secondary_array)
                    break

    def do_setup_replication(self):
        replication_devices = self.configuration.safe_get(
            'replication_device')
        if replication_devices:
            self.parse_replication_configs()
            self._is_replication_enabled = True

            if len(self._active_cluster_target_arrays) > 0:
                self._is_active_cluster_enabled = True

                # Only set this up on sync rep arrays
                self._setup_replicated_pods(
                    self._get_current_array(),
                    self._active_cluster_target_arrays,
                    self._replication_pod_name
                )

            # Even if the array is configured for sync rep set it
            # up to handle async too
            self._setup_replicated_pgroups(
                self._get_current_array(),
                self._replication_target_arrays,
                self._replication_pg_name,
                self._replication_interval,
                self._async_replication_retention_policy
            )

    def check_for_setup_error(self):
        # Avoid inheriting check_for_setup_error from SanDriver, which checks
        # for san_password or san_private_key, not relevant to our driver.
        pass

    def update_provider_info(self, volumes, snapshots):
        """Ensure we have a provider_id set on volumes.

        If there is a provider_id already set then skip, if it is missing then
        we will update it based on the volume object. We can always compute
        the id if we have the full volume object, but not all driver API's
        give us that info.

        We don't care about snapshots, they just use the volume's provider_id.
        """
        vol_updates = []
        for vol in volumes:
            if not vol.provider_id:
                vol_updates.append({
                    'id': vol.id,
                    'provider_id': self._generate_purity_vol_name(vol),
                })
        return vol_updates, None

    @pure_driver_debug_trace
    def create_volume(self, volume):
        """Creates a volume."""
        vol_name = self._generate_purity_vol_name(volume)
        vol_size = volume["size"] * units.Gi
        current_array = self._get_current_array()
        current_array.create_volume(vol_name, vol_size)

        return self._setup_volume(current_array, volume, vol_name)

    @pure_driver_debug_trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        vol_name = self._generate_purity_vol_name(volume)
        if snapshot['group_snapshot'] or snapshot['cgsnapshot']:
            snap_name = self._get_pgroup_snap_name_from_snapshot(snapshot)
        else:
            snap_name = self._get_snap_name(snapshot)

        if not snap_name:
            msg = _('Unable to determine snapshot name in Purity for snapshot '
                    '%(id)s.') % {'id': snapshot['id']}
            raise exception.PureDriverException(reason=msg)

        current_array = self._get_current_array()

        current_array.copy_volume(snap_name, vol_name)
        self._extend_if_needed(current_array,
                               vol_name,
                               snapshot["volume_size"],
                               volume["size"])
        return self._setup_volume(current_array, volume, vol_name)

    def _setup_volume(self, array, volume, purity_vol_name):
        # set provider_id early so other methods can use it even though
        # it wont be set in the cinder DB until we return from create_volume
        volume.provider_id = purity_vol_name
        async_enabled = False
        try:
            self._add_to_group_if_needed(volume, purity_vol_name)
            async_enabled = self._enable_async_replication_if_needed(
                array, volume)
        except purestorage.PureError as err:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to add volume %s to pgroup, removing volume",
                          err)
                array.destroy_volume(purity_vol_name)
                array.eradicate_volume(purity_vol_name)

        repl_status = fields.ReplicationStatus.DISABLED
        if self._is_vol_in_pod(purity_vol_name) or async_enabled:
            repl_status = fields.ReplicationStatus.ENABLED

        model_update = {
            'provider_id': purity_vol_name,
            'replication_status': repl_status,
        }
        return model_update

    def _enable_async_replication_if_needed(self, array, volume):
        repl_type = self._get_replication_type_from_vol_type(
            volume.volume_type)
        if repl_type == REPLICATION_TYPE_ASYNC:
            self._enable_async_replication(array, volume)
            return True
        return False

    def _enable_async_replication(self, array, volume):
        """Add volume to replicated protection group."""
        try:
            array.set_pgroup(self._replication_pg_name,
                             addvollist=[self._get_vol_name(volume)])
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_ALREADY_BELONGS in err.text):
                    # Happens if the volume already added to PG.
                    ctxt.reraise = False
                    LOG.warning("Adding Volume to Protection Group "
                                "failed with message: %s", err.text)

    @pure_driver_debug_trace
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_name = self._generate_purity_vol_name(volume)
        src_name = self._get_vol_name(src_vref)

        # Check which backend the source volume is on. In case of failover
        # the source volume may be on the secondary array.
        current_array = self._get_current_array()
        current_array.copy_volume(src_name, vol_name)
        self._extend_if_needed(current_array,
                               vol_name,
                               src_vref["size"],
                               volume["size"])

        return self._setup_volume(current_array, volume, vol_name)

    def _extend_if_needed(self, array, vol_name, src_size, vol_size):
        """Extend the volume from size src_size to size vol_size."""
        if vol_size > src_size:
            vol_size = vol_size * units.Gi
            array.extend_volume(vol_name, vol_size)

    @pure_driver_debug_trace
    def delete_volume(self, volume):
        """Disconnect all hosts and delete the volume"""
        vol_name = self._get_vol_name(volume)
        current_array = self._get_current_array()
        try:
            # Do a pass over remaining connections on the current array, if
            # we can try and remove any remote connections too.
            if (current_array.get_rest_version() in
                    SYNC_REPLICATION_REQUIRED_API_VERSIONS):
                hosts = current_array.list_volume_private_connections(
                    vol_name, remote=True)
            else:
                hosts = current_array.list_volume_private_connections(
                    vol_name)
            for host_info in hosts:
                host_name = host_info["host"]
                self._disconnect_host(current_array, host_name, vol_name)

            # Finally, it should be safe to delete the volume
            current_array.destroy_volume(vol_name)
            if self.configuration.pure_eradicate_on_delete:
                current_array.eradicate_volume(vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_NOT_EXIST in err.text):
                    # Happens if the volume does not exist.
                    ctxt.reraise = False
                    LOG.warning("Volume deletion failed with message: %s",
                                err.text)

    @pure_driver_debug_trace
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array()
        vol_name, snap_suff = self._get_snap_name(snapshot).split(".")
        current_array.create_snapshot(vol_name, suffix=snap_suff)

    @pure_driver_debug_trace
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array()

        snap_name = self._get_snap_name(snapshot)
        try:
            current_array.destroy_volume(snap_name)
            if self.configuration.pure_eradicate_on_delete:
                current_array.eradicate_volume(snap_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and (
                        ERR_MSG_NOT_EXIST in err.text or
                        ERR_MSG_NO_SUCH_SNAPSHOT in err.text or
                        ERR_MSG_PENDING_ERADICATION in err.text):
                    # Happens if the snapshot does not exist.
                    ctxt.reraise = False
                    LOG.warning("Unable to delete snapshot, assuming "
                                "already deleted. Error: %s", err.text)

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        pass

    def initialize_connection(self, volume, connector):
        """Connect the volume to the specified initiator in Purity.

        This implementation is specific to the host type (iSCSI, FC, etc).
        """
        raise NotImplementedError

    def _get_host(self, array, connector, remote=False):
        """Get a Purity Host that corresponds to the host in the connector.

        This implementation is specific to the host type (iSCSI, FC, etc).
        """
        raise NotImplementedError

    @pure_driver_debug_trace
    def _disconnect(self, array, volume, connector, remove_remote_hosts=False):
        """Disconnect the volume from the host described by the connector.

        If no connector is specified it will remove *all* attachments for
        the volume.

        Returns True if it was the hosts last connection.
        """
        vol_name = self._get_vol_name(volume)
        if connector is None:
            # If no connector was provided it is a force-detach, remove all
            # host connections for the volume
            LOG.warning("Removing ALL host connections for volume %s",
                        vol_name)
            if (array.get_rest_version() in
                    SYNC_REPLICATION_REQUIRED_API_VERSIONS):
                # Remote connections are only allowed in newer API versions
                connections = array.list_volume_private_connections(
                    vol_name, remote=True)
            else:
                connections = array.list_volume_private_connections(vol_name)

            for connection in connections:
                self._disconnect_host(array, connection['host'], vol_name)
            return False
        else:
            # Normal case with a specific initiator to detach it from
            hosts = self._get_host(array, connector,
                                   remote=remove_remote_hosts)
            if hosts:
                any_in_use = False
                for host in hosts:
                    host_name = host["name"]
                    host_in_use = self._disconnect_host(array,
                                                        host_name,
                                                        vol_name)
                    any_in_use = any_in_use or host_in_use
                return any_in_use
            else:
                LOG.error("Unable to disconnect host from volume, could not "
                          "determine Purity host on array %s",
                          array.backend_id)
                return False

    @pure_driver_debug_trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection."""
        vol_name = self._get_vol_name(volume)
        if self._is_vol_in_pod(vol_name):
            # Try to disconnect from each host, they may not be online though
            # so if they fail don't cause a problem.
            for array in self._uniform_active_cluster_target_arrays:
                try:
                    self._disconnect(array, volume, connector,
                                     remove_remote_hosts=False)
                except purestorage.PureError as err:
                    # Swallow any exception, just warn and continue
                    LOG.warning("Disconnect on secondary array failed with"
                                " message: %(msg)s", {"msg": err.text})
        # Now disconnect from the current array
        self._disconnect(self._get_current_array(), volume,
                         connector, remove_remote_hosts=False)

    @pure_driver_debug_trace
    def _disconnect_host(self, array, host_name, vol_name):
        """Return value indicates if host should be cleaned up."""
        try:
            array.disconnect_host(host_name, vol_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and (ERR_MSG_NOT_CONNECTED in err.text or
                                        ERR_MSG_HOST_NOT_EXIST in err.text):
                    # Happens if the host and volume are not connected or
                    # the host has already been deleted
                    ctxt.reraise = False
                    LOG.warning("Disconnection failed with message: "
                                "%(msg)s.", {"msg": err.text})

        # If it is a remote host, call it quits here. We cannot delete a remote
        # host even if it should be cleaned up now.
        if ':' in host_name:
            return

        connections = None
        try:
            connections = array.list_host_connections(host_name, private=True)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and ERR_MSG_NOT_EXIST in err.text:
                    ctxt.reraise = False

        # Assume still used if volumes are attached
        host_still_used = bool(connections)

        if GENERATED_NAME.match(host_name) and not host_still_used:
            LOG.info("Attempting to delete unneeded host %(host_name)r.",
                     {"host_name": host_name})
            try:
                array.delete_host(host_name)
                host_still_used = False
            except purestorage.PureHTTPError as err:
                with excutils.save_and_reraise_exception() as ctxt:
                    if err.code == 400:
                        if ERR_MSG_NOT_EXIST in err.text:
                            # Happens if the host is already deleted.
                            # This is fine though, just log so we know what
                            # happened.
                            ctxt.reraise = False
                            host_still_used = False
                            LOG.debug("Purity host deletion failed: "
                                      "%(msg)s.", {"msg": err.text})
                        if ERR_MSG_EXISTING_CONNECTIONS in err.text:
                            # If someone added a connection underneath us
                            # that's ok, just keep going.
                            ctxt.reraise = False
                            host_still_used = True
                            LOG.debug("Purity host deletion ignored: %(msg)s",
                                      {"msg": err.text})
        return not host_still_used

    @pure_driver_debug_trace
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
        current_array = self._get_current_array()

        # Collect info from the array
        space_info = current_array.get(space=True)
        if not isinstance(space_info, dict):
            # Some versions of the API give back a list of dicts, always use 0
            space_info = space_info[0]
        perf_info = current_array.get(action='monitor')[0]  # Always index 0
        hosts = current_array.list_hosts()
        snaps = current_array.list_volumes(snap=True, pending=True)
        pgroups = current_array.list_pgroups(pending=True)

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
        data['QoS_support'] = False

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

        #  Replication
        data["replication_enabled"] = self._is_replication_enabled
        repl_types = []
        if self._is_replication_enabled:
            repl_types = [REPLICATION_TYPE_ASYNC]
        if self._is_active_cluster_enabled:
            repl_types.append(REPLICATION_TYPE_SYNC)
        data["replication_type"] = repl_types
        data["replication_count"] = len(self._replication_target_arrays)
        data["replication_targets"] = [array.backend_id for array
                                       in self._replication_target_arrays]
        self._stats = data

    def _get_provisioned_space(self):
        """Sum up provisioned size of all volumes on array"""
        volumes = self._get_current_array().list_volumes(pending=True)
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
            thin_provisioning = volume_utils.get_max_over_subscription_ratio(
                self.configuration.max_over_subscription_ratio,
                supports_auto=True)

        return thin_provisioning

    @pure_driver_debug_trace
    def extend_volume(self, volume, new_size):
        """Extend volume to new_size."""

        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array()

        vol_name = self._get_vol_name(volume)
        new_size = new_size * units.Gi
        current_array.extend_volume(vol_name, new_size)

    def _add_volume_to_consistency_group(self, group, vol_name):
        pgroup_name = self._get_pgroup_name(group)
        current_array = self._get_current_array()
        current_array.set_pgroup(pgroup_name, addvollist=[vol_name])

    @pure_driver_debug_trace
    def create_consistencygroup(self, context, group):
        """Creates a consistencygroup."""

        current_array = self._get_current_array()
        current_array.create_pgroup(self._get_pgroup_name(group))

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
        pgroup_name = self._get_pgroup_name(source_group)
        tmp_suffix = '%s-tmp' % uuid.uuid4()
        tmp_pgsnap_name = '%(pgroup_name)s.%(pgsnap_suffix)s' % {
            'pgroup_name': pgroup_name,
            'pgsnap_suffix': tmp_suffix,
        }
        LOG.debug('Creating temporary Protection Group snapshot %(snap_name)s '
                  'while cloning Consistency Group %(source_group)s.',
                  {'snap_name': tmp_pgsnap_name,
                   'source_group': source_group.id})
        current_array = self._get_current_array()
        current_array.create_pgroup_snapshot(pgroup_name, suffix=tmp_suffix)
        try:
            for source_vol, cloned_vol in zip(source_vols, volumes):
                source_snap_name = self._get_pgroup_vol_snap_name(
                    pgroup_name,
                    tmp_suffix,
                    self._get_vol_name(source_vol)
                )
                cloned_vol_name = self._get_vol_name(cloned_vol)
                current_array.copy_volume(source_snap_name, cloned_vol_name)
                self._add_volume_to_consistency_group(
                    group,
                    cloned_vol_name
                )
        finally:
            self._delete_pgsnapshot(tmp_pgsnap_name)

    @pure_driver_debug_trace
    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        self.create_consistencygroup(context, group)
        if cgsnapshot and snapshots:
            self._create_cg_from_cgsnap(volumes,
                                        snapshots)
        elif source_cg:
            self._create_cg_from_cg(group, source_cg, volumes, source_vols)

        return None, None

    @pure_driver_debug_trace
    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group."""

        try:
            pgroup_name = self._get_pgroup_name(group)
            current_array = self._get_current_array()
            current_array.destroy_pgroup(pgroup_name)
            if self.configuration.pure_eradicate_on_delete:
                current_array.eradicate_pgroup(pgroup_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        (ERR_MSG_PENDING_ERADICATION in err.text or
                         ERR_MSG_NOT_EXIST in err.text)):
                    # Treat these as a "success" case since we are trying
                    # to delete them anyway.
                    ctxt.reraise = False
                    LOG.warning("Unable to delete Protection Group: %s",
                                err.text)

        for volume in volumes:
            self.delete_volume(volume)

        return None, None

    @pure_driver_debug_trace
    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):

        pgroup_name = self._get_pgroup_name(group)
        if add_volumes:
            addvollist = [self._get_vol_name(vol) for vol in add_volumes]
        else:
            addvollist = []

        if remove_volumes:
            remvollist = [self._get_vol_name(vol) for vol in remove_volumes]
        else:
            remvollist = []

        current_array = self._get_current_array()
        current_array.set_pgroup(pgroup_name, addvollist=addvollist,
                                 remvollist=remvollist)

        return None, None, None

    @pure_driver_debug_trace
    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot."""

        pgroup_name = self._get_pgroup_name(cgsnapshot.group)
        pgsnap_suffix = self._get_pgroup_snap_suffix(cgsnapshot)
        current_array = self._get_current_array()
        current_array.create_pgroup_snapshot(pgroup_name, suffix=pgsnap_suffix)

        return None, None

    def _delete_pgsnapshot(self, pgsnap_name):
        current_array = self._get_current_array()
        try:
            # FlashArray.destroy_pgroup is also used for deleting
            # pgroup snapshots. The underlying REST API is identical.
            current_array.destroy_pgroup(pgsnap_name)
            if self.configuration.pure_eradicate_on_delete:
                current_array.eradicate_pgroup(pgsnap_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        (ERR_MSG_PENDING_ERADICATION in err.text or
                         ERR_MSG_NOT_EXIST in err.text)):
                    # Treat these as a "success" case since we are trying
                    # to delete them anyway.
                    ctxt.reraise = False
                    LOG.warning("Unable to delete Protection Group "
                                "Snapshot: %s", err.text)

    @pure_driver_debug_trace
    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot."""

        pgsnap_name = self._get_pgroup_snap_name(cgsnapshot)
        self._delete_pgsnapshot(pgsnap_name)

        return None, None

    def _validate_manage_existing_vol_type(self, volume):
        """Ensure the volume type makes sense for being managed.

        We will not allow volumes that need to be sync-rep'd to be managed.
        There isn't a safe way to automate adding them to the Pod from here,
        an admin doing the import to Cinder would need to handle that part
        first.
        """
        replication_type = self._get_replication_type_from_vol_type(
            volume.volume_type)
        if replication_type == REPLICATION_TYPE_SYNC:
            raise exception.ManageExistingVolumeTypeMismatch(
                _("Unable to managed volume with type requiring sync"
                  " replication enabled."))

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

        if not is_snap and '::' in ref_vol_name:
            # Don't allow for managing volumes in a pod
            raise exception.ManageExistingInvalidReference(
                _("Unable to manage volume in a Pod"))

        current_array = self._get_current_array()
        try:
            volume_info = current_array.get_volume(ref_vol_name, snap=is_snap)
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
        # to throw an Invalid Reference exception.
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref,
            reason=_("Unable to find Purity ref with name=%s") % ref_vol_name)

    def _add_to_group_if_needed(self, volume, vol_name):
        if volume['group_id']:
            if volume_utils.is_group_a_cg_snapshot_type(volume.group):
                self._add_volume_to_consistency_group(
                    volume.group,
                    vol_name
                )
        elif volume['consistencygroup_id']:
            self._add_volume_to_consistency_group(
                volume.consistencygroup,
                vol_name
            )

    def create_group(self, ctxt, group):
        """Creates a group.

        :param ctxt: the context of the caller.
        :param group: the Group object of the group to be created.
        :returns: model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self.create_consistencygroup(ctxt, group)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def delete_group(self, ctxt, group, volumes):
        """Deletes a group.

        :param ctxt: the context of the caller.
        :param group: the Group object of the group to be deleted.
        :param volumes: a list of Volume objects in the group.
        :returns: model_update, volumes_model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self.delete_consistencygroup(ctxt, group, volumes)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def update_group(self, ctxt, group,
                     add_volumes=None, remove_volumes=None):
        """Updates a group.

        :param ctxt: the context of the caller.
        :param group: the Group object of the group to be updated.
        :param add_volumes: a list of Volume objects to be added.
        :param remove_volumes: a list of Volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update
        """

        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self.update_consistencygroup(ctxt,
                                                group,
                                                add_volumes,
                                                remove_volumes)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def create_group_from_src(self, ctxt, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param ctxt: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of volume objects in the source_group.
        :returns: model_update, volumes_model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group):
            return self.create_consistencygroup_from_src(ctxt,
                                                         group,
                                                         volumes,
                                                         group_snapshot,
                                                         snapshots,
                                                         source_group,
                                                         source_vols)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def create_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Creates a group_snapshot.

        :param ctxt: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            return self.create_cgsnapshot(ctxt, group_snapshot, snapshots)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    def delete_group_snapshot(self, ctxt, group_snapshot, snapshots):
        """Deletes a group_snapshot.

        :param ctxt: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """
        if volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            return self.delete_cgsnapshot(ctxt, group_snapshot, snapshots)

        # If it wasn't a consistency group request ignore it and we'll rely on
        # the generic group implementation.
        raise NotImplementedError()

    @pure_driver_debug_trace
    def manage_existing(self, volume, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        We expect a volume name in the existing_ref that matches one in Purity.
        """
        self._validate_manage_existing_vol_type(volume)
        self._validate_manage_existing_ref(existing_ref)

        ref_vol_name = existing_ref['name']
        current_array = self._get_current_array()
        connected_hosts = \
            current_array.list_volume_private_connections(ref_vol_name)
        if len(connected_hosts) > 0:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("%(driver)s manage_existing cannot manage a volume "
                         "connected to hosts. Please disconnect this volume "
                         "from existing hosts before importing"
                         ) % {'driver': self.__class__.__name__})
        new_vol_name = self._generate_purity_vol_name(volume)
        LOG.info("Renaming existing volume %(ref_name)s to %(new_name)s",
                 {"ref_name": ref_vol_name, "new_name": new_vol_name})
        self._rename_volume_object(ref_vol_name,
                                   new_vol_name,
                                   raise_not_exist=True)
        volume.provider_id = new_vol_name
        async_enabled = self._enable_async_replication_if_needed(current_array,
                                                                 volume)
        repl_status = fields.ReplicationStatus.DISABLED
        if async_enabled:
            repl_status = fields.ReplicationStatus.ENABLED
        return {
            'provider_id': new_vol_name,
            'replication_status': repl_status,
        }

    @pure_driver_debug_trace
    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        We expect a volume name in the existing_ref that matches one in Purity.
        """
        volume_info = self._validate_manage_existing_ref(existing_ref)
        size = self._round_bytes_to_gib(volume_info['size'])

        return size

    def _rename_volume_object(self, old_name, new_name, raise_not_exist=False):
        """Rename a volume object (could be snapshot) in Purity.

        This will not raise an exception if the object does not exist
        """
        current_array = self._get_current_array()
        try:
            current_array.rename_volume(old_name, new_name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_NOT_EXIST in err.text):
                    ctxt.reraise = raise_not_exist
                    LOG.warning("Unable to rename %(old_name)s, error "
                                "message: %(error)s",
                                {"old_name": old_name, "error": err.text})
        return new_name

    @pure_driver_debug_trace
    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        The volume will be renamed with "-unmanaged" as a suffix
        """

        vol_name = self._get_vol_name(volume)
        unmanaged_vol_name = vol_name + UNMANAGED_SUFFIX
        LOG.info("Renaming existing volume %(ref_name)s to %(new_name)s",
                 {"ref_name": vol_name, "new_name": unmanaged_vol_name})
        self._rename_volume_object(vol_name, unmanaged_vol_name)

    def _verify_manage_snap_api_requirements(self):
        current_array = self._get_current_array()
        api_version = current_array.get_rest_version()
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
        LOG.info("Renaming existing snapshot %(ref_name)s to "
                 "%(new_name)s", {"ref_name": ref_snap_name,
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
        size = self._round_bytes_to_gib(snap_info['size'])
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
        LOG.info("Renaming existing snapshot %(ref_name)s to "
                 "%(new_name)s", {"ref_name": snap_name,
                                  "new_name": unmanaged_snap_name})
        self._rename_volume_object(snap_name, unmanaged_snap_name)

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder.

        Rule out volumes that are attached to a Purity host or that
        are already in the list of cinder_volumes.

        Also exclude any volumes that are in a pod, it is difficult to safely
        move in/out of pods from here without more context so we'll rely on
        the admin to move them before managing the volume.

        We return references of the volume names for any others.
        """
        array = self._get_current_array()
        pure_vols = array.list_volumes()
        hosts_with_connections = array.list_hosts(all=True)

        # Put together a map of volumes that are connected to hosts
        connected_vols = {}
        for host in hosts_with_connections:
            vol = host.get('vol')
            if vol:
                connected_vols[vol] = host['name']

        # Put together a map of existing cinder volumes on the array
        # so we can lookup cinder id's by purity volume names
        existing_vols = {}
        for cinder_vol in cinder_volumes:
            existing_vols[self._get_vol_name(cinder_vol)] = cinder_vol.name_id

        manageable_vols = []
        for pure_vol in pure_vols:
            vol_name = pure_vol['name']
            cinder_id = existing_vols.get(vol_name)
            not_safe_msgs = []
            host = connected_vols.get(vol_name)
            in_pod = ("::" in vol_name)

            if host:
                not_safe_msgs.append(_('Volume connected to host %s') % host)

            if cinder_id:
                not_safe_msgs.append(_('Volume already managed'))

            if in_pod:
                not_safe_msgs.append(_('Volume is in a Pod'))

            is_safe = (len(not_safe_msgs) == 0)
            reason_not_safe = ''
            if not is_safe:
                for i, msg in enumerate(not_safe_msgs):
                    if i > 0:
                        reason_not_safe += ' && '
                    reason_not_safe += "%s" % msg

            manageable_vols.append({
                'reference': {'name': vol_name},
                'size': self._round_bytes_to_gib(pure_vol['size']),
                'safe_to_manage': is_safe,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': None,
            })

        return volume_utils.paginate_entries_list(
            manageable_vols, marker, limit, offset, sort_keys, sort_dirs)

    def get_manageable_snapshots(self, cinder_snapshots, marker, limit, offset,
                                 sort_keys, sort_dirs):
        """List snapshots on the backend available for management by Cinder."""
        array = self._get_current_array()
        pure_snapshots = array.list_volumes(snap=True)

        # Put together a map of existing cinder snapshots on the array
        # so we can lookup cinder id's by purity snapshot names
        existing_snapshots = {}
        for cinder_snap in cinder_snapshots:
            name = self._get_snap_name(cinder_snap)
            existing_snapshots[name] = cinder_snap.id

        manageable_snaps = []
        for pure_snap in pure_snapshots:
            snap_name = pure_snap['name']
            cinder_id = existing_snapshots.get(snap_name)
            is_safe = True
            reason_not_safe = None

            if cinder_id:
                is_safe = False
                reason_not_safe = _("Snapshot already managed.")

            manageable_snaps.append({
                'reference': {'name': snap_name},
                'size': self._round_bytes_to_gib(pure_snap['size']),
                'safe_to_manage': is_safe,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': None,
                'source_reference': {'name': pure_snap['source']},
            })

        return volume_utils.paginate_entries_list(
            manageable_snaps, marker, limit, offset, sort_keys, sort_dirs)

    @staticmethod
    def _round_bytes_to_gib(size):
        return int(math.ceil(float(size) / units.Gi))

    def _get_flasharray(self, san_ip, api_token, rest_version=None,
                        verify_https=None, ssl_cert_path=None,
                        request_kwargs=None):

        if (version.LooseVersion(purestorage.VERSION) <
                version.LooseVersion('1.14.0')):
            if request_kwargs is not None:
                LOG.warning("Unable to specify request_kwargs='%s' on "
                            "purestorage.FlashArray using 'purestorage' "
                            "python module <1.14.0. Current version: %s",
                            request_kwargs,
                            purestorage.VERSION)
            array = purestorage.FlashArray(san_ip,
                                           api_token=api_token,
                                           rest_version=rest_version,
                                           verify_https=verify_https,
                                           ssl_cert=ssl_cert_path,
                                           user_agent=self._user_agent)
        else:
            array = purestorage.FlashArray(san_ip,
                                           api_token=api_token,
                                           rest_version=rest_version,
                                           verify_https=verify_https,
                                           ssl_cert=ssl_cert_path,
                                           user_agent=self._user_agent,
                                           request_kwargs=request_kwargs)
        array_info = array.get()
        array.array_name = array_info["array_name"]
        array.array_id = array_info["id"]

        # Configure some extra tracing on requests made to the array
        if hasattr(array, '_request'):
            def trace_request(fn):
                def wrapper(*args, **kwargs):
                    request_id = uuid.uuid4().hex
                    LOG.debug("Making HTTP Request [%(id)s]:"
                              " 'args=%(args)s kwargs=%(kwargs)s'",
                              {
                                  "id": request_id,
                                  "args": args,
                                  "kwargs": kwargs,
                              })
                    ret = fn(*args, **kwargs)
                    LOG.debug(
                        "Response for HTTP request [%(id)s]: '%(response)s'",
                        {
                            "id": request_id,
                            "response": ret,
                        }
                    )
                    return ret
                return wrapper
            array._request = trace_request(array._request)

        LOG.debug("connected to %(array_name)s with REST API %(api_version)s",
                  {"array_name": array.array_name,
                   "api_version": array._rest_version})
        return array

    @staticmethod
    def _client_version_greater_than(version):
        module_version = [int(v) for v in purestorage.VERSION.split('.')]
        for limit_version, actual_version in zip(version, module_version):
            if actual_version > limit_version:
                return True
        return False

    @staticmethod
    def _get_pod_for_volume(volume_name):
        """Return the Purity pod name for the given volume.

        This works on the assumption that volume names are always prefixed
        with the pod name followed by '::'
        """
        if '::' not in volume_name:
            # Not in a pod
            return None
        parts = volume_name.split('::')
        if len(parts) != 2 or not parts[0]:
            # Can't parse this.. Should never happen though, would mean a
            # break to the API contract with Purity.
            raise exception.PureDriverException(
                _("Unable to determine pod for volume %s") % volume_name)
        return parts[0]

    @classmethod
    def _is_vol_in_pod(cls, pure_vol_name):
        return bool(cls._get_pod_for_volume(pure_vol_name) is not None)

    @staticmethod
    def _get_replication_type_from_vol_type(volume_type):
        if volume_type and volume_type.is_replicated():
            specs = volume_type.get("extra_specs")
            if specs and EXTRA_SPECS_REPL_TYPE in specs:
                    replication_type_spec = specs[EXTRA_SPECS_REPL_TYPE]
                    # Do not validate settings, ignore invalid.
                    if replication_type_spec == "<in> async":
                        return REPLICATION_TYPE_ASYNC
                    elif replication_type_spec == "<in> sync":
                        return REPLICATION_TYPE_SYNC
            else:
                # if no type was specified but replication is enabled assume
                # that async replication is enabled
                return REPLICATION_TYPE_ASYNC
        return None

    def _generate_purity_vol_name(self, volume):
        """Return the name of the volume Purity will use.

        This expects to be given a Volume OVO and not a volume
        dictionary.
        """
        base_name = volume.name

        # Some OpenStack deployments, eg PowerVC, create a volume.name that
        # when appended with out '-cinder' string will exceed the maximum
        # volume name length for Pure, so here we left truncate the true volume
        # name before the opennstack volume_name_template affected it and
        # then put back the template format
        if len(base_name) > 56:
            actual_name = base_name[7:]
            base_name = "volume-" + actual_name[-52:]

        repl_type = self._get_replication_type_from_vol_type(
            volume.volume_type)
        if repl_type == REPLICATION_TYPE_SYNC:
            base_name = self._replication_pod_name + "::" + base_name

        return base_name + "-cinder"

    def _get_vol_name(self, volume):
        """Return the name of the volume Purity will use."""
        # Use the dictionary access style for compatibility, this works for
        # db or OVO volume objects too.
        return volume['provider_id']

    def _get_snap_name(self, snapshot):
        """Return the name of the snapshot that Purity will use."""
        return "%s.%s" % (self._get_vol_name(snapshot.volume),
                          snapshot["name"])

    def _group_potential_repl_types(self, pgroup):
        repl_types = set()
        for type in pgroup.volume_types:
            repl_type = self._get_replication_type_from_vol_type(type)
            repl_types.add(repl_type)
        return repl_types

    def _get_pgroup_name(self, pgroup):
        # check if the pgroup has any volume types that are sync rep enabled,
        # if so, we need to use a group name accounting for the ActiveCluster
        # pod.
        base_name = ""
        if REPLICATION_TYPE_SYNC in self._group_potential_repl_types(pgroup):
            base_name = self._replication_pod_name + "::"

        return "%(base)sconsisgroup-%(id)s-cinder" % {
            'base': base_name, 'id': pgroup.id}

    @staticmethod
    def _get_pgroup_snap_suffix(group_snapshot):
        return "cgsnapshot-%s-cinder" % group_snapshot['id']

    @staticmethod
    def _get_group_id_from_snap(group_snap):
        # We don't really care what kind of group it is, if we are calling
        # this look for a group_id and fall back to using a consistencygroup_id
        id = None
        try:
            id = group_snap['group_id']
        except AttributeError:
            pass
        if id is None:
            try:
                id = group_snap['consistencygroup_id']
            except AttributeError:
                pass
        return id

    def _get_pgroup_snap_name(self, group_snapshot):
        """Return the name of the pgroup snapshot that Purity will use"""
        return "%s.%s" % (self._get_pgroup_name(group_snapshot.group),
                          self._get_pgroup_snap_suffix(group_snapshot))

    @staticmethod
    def _get_pgroup_vol_snap_name(pg_name, pgsnap_suffix, volume_name):
        return "%(pgroup_name)s.%(pgsnap_suffix)s.%(volume_name)s" % {
            'pgroup_name': pg_name,
            'pgsnap_suffix': pgsnap_suffix,
            'volume_name': volume_name,
        }

    def _get_pgroup_snap_name_from_snapshot(self, snapshot):
        """Return the name of the snapshot that Purity will use."""

        group_snap = None
        if snapshot.group_snapshot:
            group_snap = snapshot.group_snapshot
        elif snapshot.cgsnapshot:
            group_snap = snapshot.cgsnapshot

        pg_vol_snap_name = "%(group_snap)s.%(volume_name)s-cinder" % {
            'group_snap': self._get_pgroup_snap_name(group_snap),
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
            if err.code == 400 and ERR_MSG_HOST_NOT_EXIST in err.text:
                LOG.debug('Unable to attach volume to host: %s', err.text)
                raise exception.PureRetryableException()
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

    @pure_driver_debug_trace
    def retype(self, context, volume, new_type, diff, host):
        """Retype from one volume type to another on the same backend.

        For a Pure Array there is currently no differentiation between types
        of volumes other than some being part of a protection group to be
        replicated for async, or part of a pod for sync replication.
        """

        # TODO(patrickeast): Can remove this once new_type is a VolumeType OVO
        new_type = volume_type.VolumeType.get_by_name_or_id(context,
                                                            new_type['id'])
        previous_vol_replicated = volume.is_replicated()
        new_vol_replicated = (new_type and new_type.is_replicated())

        prev_repl_type = None
        new_repl_type = None

        # See if the type specifies the replication type. If we know it is
        # replicated but doesn't specify a type assume that it is async rep
        # for backwards compatibility. This applies to both old and new types

        if previous_vol_replicated:
            prev_repl_type = self._get_replication_type_from_vol_type(
                volume.volume_type)

        if new_vol_replicated:
            new_repl_type = self._get_replication_type_from_vol_type(new_type)
            if new_repl_type is None:
                new_repl_type = REPLICATION_TYPE_ASYNC

        # There are a few cases we care about, going from non-replicated to
        # replicated, from replicated to non-replicated, and switching
        # replication types.
        model_update = None
        if previous_vol_replicated and not new_vol_replicated:
            if prev_repl_type == REPLICATION_TYPE_ASYNC:
                # Remove from protection group.
                self._disable_async_replication(volume)
                model_update = {
                    "replication_status": fields.ReplicationStatus.DISABLED
                }
            elif prev_repl_type == REPLICATION_TYPE_SYNC:
                # We can't pull a volume out of a stretched pod, indicate
                # to the volume manager that we need to use a migration instead
                return False, None
        elif not previous_vol_replicated and new_vol_replicated:
            if new_repl_type == REPLICATION_TYPE_ASYNC:
                # Add to protection group.
                self._enable_async_replication(self._get_current_array(),
                                               volume)
                model_update = {
                    "replication_status": fields.ReplicationStatus.ENABLED
                }
            elif new_repl_type == REPLICATION_TYPE_SYNC:
                # We can't add a volume to a stretched pod, they must be
                # created in one, indicate to the volume manager that it
                # should do a migration.
                return False, None
        elif (previous_vol_replicated and new_vol_replicated
                and (prev_repl_type != new_repl_type)):
            # We can't move a volume in or out of a pod, indicate to the
            #  manager that it should do a migration for this retype
            return False, None
        return True, model_update

    @pure_driver_debug_trace
    def _disable_async_replication(self, volume):
        """Disable replication on the given volume."""

        current_array = self._get_current_array()
        LOG.debug("Disabling replication for volume %(id)s residing on "
                  "array %(backend_id)s.",
                  {"id": volume["id"],
                   "backend_id": current_array.backend_id})
        try:
            current_array.set_pgroup(self._replication_pg_name,
                                     remvollist=([self._get_vol_name(volume)]))
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 400 and
                        ERR_MSG_COULD_NOT_BE_FOUND in err.text):
                    ctxt.reraise = False
                    LOG.warning("Disable replication on volume failed: "
                                "already disabled: %s", err.text)
                else:
                    LOG.error("Disable replication on volume failed with "
                              "message: %s", err.text)

    @pure_driver_debug_trace
    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failover backend to a secondary array

        This action will not affect the original volumes in any
        way and it will stay as is. If a subsequent failover is performed we
        will simply overwrite the original (now unmanaged) volumes.
        """
        if secondary_id == 'default':
            # We are going back to the 'original' driver config, just put
            # our current array back to the primary.
            if self._failed_over_primary_array:

                # If the "default" and current host are in an ActiveCluster
                # with volumes stretched between the two then we can put
                # the sync rep enabled volumes into available states, anything
                # else will go into an error state pending an admin to check
                # them and adjust states as appropriate.

                current_array = self._get_current_array()
                repl_type = current_array.replication_type
                is_in_ac = bool(repl_type == REPLICATION_TYPE_SYNC)
                model_updates = []

                # We are only given replicated volumes, but any non sync rep
                # volumes should go into error upon doing a failback as the
                # async replication is not bi-directional.
                for vol in volumes:
                    repl_type = self._get_replication_type_from_vol_type(
                        vol.volume_type)
                    if not (is_in_ac and repl_type == REPLICATION_TYPE_SYNC):
                        model_updates.append({
                            'volume_id': vol['id'],
                            'updates': {
                                'status': 'error',
                            }
                        })
                self._swap_replication_state(current_array,
                                             self._failed_over_primary_array,
                                             failback=True)
                return secondary_id, model_updates, []
            else:
                msg = _('Unable to failback to "default", this can only be '
                        'done after a failover has completed.')
                raise exception.InvalidReplicationTarget(message=msg)

        current_array = self._get_current_array()
        LOG.debug("Failover replication for array %(primary)s to "
                  "%(secondary)s.",
                  {"primary": current_array.backend_id,
                   "secondary": secondary_id})

        if secondary_id == current_array.backend_id:
            raise exception.InvalidReplicationTarget(
                reason=_("Secondary id can not be the same as primary array, "
                         "backend_id = %(secondary)s.") %
                {"secondary": secondary_id}
            )

        secondary_array = None
        pg_snap = None  # used for async only
        if secondary_id:
            for array in self._replication_target_arrays:
                if array.backend_id == secondary_id:
                    secondary_array = array
                    break

            if not secondary_array:
                raise exception.InvalidReplicationTarget(
                    reason=_("Unable to determine secondary_array from"
                             " supplied secondary: %(secondary)s.") %
                    {"secondary": secondary_id}
                )

            if secondary_array.replication_type == REPLICATION_TYPE_ASYNC:
                pg_snap = self._get_latest_replicated_pg_snap(
                    secondary_array,
                    self._get_current_array().array_name,
                    self._replication_pg_name
                )
        else:
            LOG.debug('No secondary array id specified, checking all targets.')
            # Favor sync-rep targets options
            secondary_array = self._find_sync_failover_target()

            if not secondary_array:
                # Now look for an async one
                secondary_array, pg_snap = self._find_async_failover_target()

        # If we *still* don't have a secondary array it means we couldn't
        # determine one to use. Stop now.
        if not secondary_array:
            raise exception.PureDriverException(
                reason=_("Unable to find viable secondary array from "
                         "configured targets: %(targets)s.") %
                {"targets": six.text_type(self._replication_target_arrays)}
            )

        LOG.debug("Starting failover from %(primary)s to %(secondary)s",
                  {"primary": current_array.array_name,
                   "secondary": secondary_array.array_name})

        model_updates = []
        if secondary_array.replication_type == REPLICATION_TYPE_ASYNC:
            model_updates = self._async_failover_host(
                volumes, secondary_array, pg_snap)
        elif secondary_array.replication_type == REPLICATION_TYPE_SYNC:
            model_updates = self._sync_failover_host(volumes, secondary_array)

        current_array = self._get_current_array()
        self._swap_replication_state(current_array, secondary_array)

        return secondary_array.backend_id, model_updates, []

    def _swap_replication_state(self, current_array, secondary_array,
                                failback=False):
        # After failover we want our current array to be swapped for the
        # secondary array we just failed over to.
        self._failed_over_primary_array = current_array

        # Remove the new primary from our secondary targets
        if secondary_array in self._replication_target_arrays:
            self._replication_target_arrays.remove(secondary_array)

        # For async, if we're doing a failback then add the old primary back
        # into the replication list
        if failback:
            self._replication_target_arrays.append(current_array)
            self._is_replication_enabled = True

        # If its sync rep then swap the two in their lists since it is a
        # bi-directional setup, if the primary is still OK or comes back
        # it can continue being used as a secondary target until a 'failback'
        # occurs. This is primarily important for "uniform" environments with
        # attachments to both arrays. We may need to adjust flags on the
        # primary array object to lock it into one type of replication.
        if secondary_array.replication_type == REPLICATION_TYPE_SYNC:
            self._is_active_cluster_enabled = True
            self._is_replication_enabled = True
            if secondary_array in self._active_cluster_target_arrays:
                self._active_cluster_target_arrays.remove(secondary_array)

            current_array.replication_type = REPLICATION_TYPE_SYNC
            self._replication_target_arrays.append(current_array)
            self._active_cluster_target_arrays.append(current_array)
        else:
            # If the target is not configured for sync rep it means it isn't
            # part of the ActiveCluster and we need to reflect this in our
            # capabilities.
            self._is_active_cluster_enabled = False
            self._is_replication_enabled = False

        if secondary_array.uniform:
            if secondary_array in self._uniform_active_cluster_target_arrays:
                self._uniform_active_cluster_target_arrays.remove(
                    secondary_array)
            current_array.unform = True
            self._uniform_active_cluster_target_arrays.append(current_array)

        self._set_current_array(secondary_array)

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

    @pure_driver_debug_trace
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

    @pure_driver_debug_trace
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

    @pure_driver_debug_trace
    def _setup_replicated_pods(self, primary, ac_secondaries, pod_name):
        # Make sure the pod exists
        self._create_pod_if_not_exist(primary, pod_name)

        # Stretch it across arrays we have configured, assume all secondary
        # arrays given to this method are configured for sync rep with active
        # cluster enabled.
        for target_array in ac_secondaries:
            try:
                primary.add_pod(pod_name, target_array.array_name)
            except purestorage.PureHTTPError as err:
                with excutils.save_and_reraise_exception() as ctxt:
                    if err.code == 400 and (
                            ERR_MSG_ALREADY_EXISTS
                            in err.text):
                        ctxt.reraise = False
                        LOG.info("Skipping add array %(target_array)s to pod"
                                 " %(pod_name)s since it's already added.",
                                 {"target_array": target_array.array_name,
                                  "pod_name": pod_name})

    @pure_driver_debug_trace
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
                        LOG.info("Skipping add target %(target_array)s"
                                 " to protection group %(pgname)s"
                                 " since it's already added.",
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
                        LOG.info("Skipping allow pgroup %(pgname)s on "
                                 "target array %(target_array)s since "
                                 "it is already allowed.",
                                 {"pgname": pg_name,
                                  "target_array": target_array.array_name})

        # Wait until source array acknowledges previous operation.
        self._wait_until_source_array_allowed(primary, pg_name)
        # Start replication on the PG.
        primary.set_pgroup(pg_name, replicate_enabled=True)

    @pure_driver_debug_trace
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

    @pure_driver_debug_trace
    def _get_latest_replicated_pg_snap(self,
                                       target_array,
                                       source_array_name,
                                       pgroup_name):
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

        pg_snap = pg_snaps_filtered[0] if pg_snaps_filtered else None
        LOG.debug("Selecting snapshot %(pg_snap)s for failover.",
                  {"pg_snap": pg_snap})

        return pg_snap

    @pure_driver_debug_trace
    def _create_pod_if_not_exist(self, source_array, name):
        if not name:
            raise exception.PureDriverException(
                reason=_("Empty string passed for Pod name."))
        try:
            source_array.create_pod(name)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and ERR_MSG_ALREADY_EXISTS in err.text:
                    # Happens if the pod already exists
                    ctxt.reraise = False
                    LOG.warning("Skipping creation of pod %s since it "
                                "already exists.", name)
                    return
                if err.code == 400 and (
                        ERR_MSG_PENDING_ERADICATION in err.text):
                    ctxt.reraise = False
                    LOG.warning("Pod %s is deleted but not"
                                " eradicated - will recreate.", name)
                    source_array.eradicate_pod(name)
                    self._create_pod_if_not_exist(source_array, name)

    @pure_driver_debug_trace
    def _create_protection_group_if_not_exist(self, source_array, pgname):
        if not pgname:
            raise exception.PureDriverException(
                reason=_("Empty string passed for PG name."))
        try:
            source_array.create_pgroup(pgname)
        except purestorage.PureHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if err.code == 400 and ERR_MSG_ALREADY_EXISTS in err.text:
                    # Happens if the PG already exists
                    ctxt.reraise = False
                    LOG.warning("Skipping creation of PG %s since it "
                                "already exists.", pgname)
                    # We assume PG has already been setup with correct
                    # replication settings.
                    return
                if err.code == 400 and (
                        ERR_MSG_PENDING_ERADICATION in err.text):
                    ctxt.reraise = False
                    LOG.warning("Protection group %s is deleted but not"
                                " eradicated - will recreate.", pgname)
                    source_array.eradicate_pgroup(pgname)
                    self._create_protection_group_if_not_exist(source_array,
                                                               pgname)

    def _find_async_failover_target(self):
        if not self._replication_target_arrays:
                raise exception.PureDriverException(
                    reason=_("Unable to find failover target, no "
                             "secondary targets configured."))
        secondary_array = None
        pg_snap = None
        for array in self._replication_target_arrays:
            if array.replication_type != REPLICATION_TYPE_ASYNC:
                continue
            try:
                secondary_array = array
                pg_snap = self._get_latest_replicated_pg_snap(
                    secondary_array,
                    self._get_current_array().array_name,
                    self._replication_pg_name
                )
                if pg_snap:
                    break
            except Exception:
                LOG.exception('Error finding replicated pg snapshot '
                              'on %(secondary)s.',
                              {'secondary': array.backend_id})
                secondary_array = None

        if not pg_snap:
            raise exception.PureDriverException(
                reason=_("Unable to find viable pg snapshot to use for "
                         "failover on selected secondary array: %(id)s.") %
                {"id": secondary_array.backend_id if secondary_array else None}
            )

        return secondary_array, pg_snap

    def _find_sync_failover_target(self):
        secondary_array = None
        if not self._active_cluster_target_arrays:
            LOG.warning("Unable to find failover target, no "
                        "sync rep secondary targets configured.")
            return secondary_array

        for array in self._active_cluster_target_arrays:
            try:
                secondary_array = array
                # Ensure the pod is in a good state on the array
                pod_info = secondary_array.get_pod(self._replication_pod_name)
                for pod_array in pod_info["arrays"]:
                    # Compare against Purity ID's
                    if pod_array["array_id"] == secondary_array.array_id:
                        if pod_array["status"] == "online":
                            # Success! Use this array.
                            break
                        else:
                            secondary_array = None

            except purestorage.PureHTTPError as err:
                LOG.warning("Failed to get pod status for secondary array "
                            "%(id)s: %(err)s",
                            {
                                "id": secondary_array.backend_id,
                                "err": err,
                            })
                secondary_array = None
        return secondary_array

    def _async_failover_host(self, volumes, secondary_array, pg_snap):
        # NOTE(patrickeast): This currently requires a call with REST API 1.3.
        # If we need to, create a temporary FlashArray for this operation.
        api_version = secondary_array.get_rest_version()
        LOG.debug("Current REST API for array id %(id)s is %(api_version)s",
                  {"id": secondary_array.array_id, "api_version": api_version})
        if api_version != '1.3':
            # Try to copy the flasharray as close as we can..
            if hasattr(secondary_array, '_request_kwargs'):
                target_array = self._get_flasharray(
                    secondary_array._target,
                    api_token=secondary_array._api_token,
                    rest_version='1.3',
                    request_kwargs=secondary_array._request_kwargs,
                )
            else:
                target_array = self._get_flasharray(
                    secondary_array._target,
                    api_token=secondary_array._api_token,
                    rest_version='1.3',
                )
        else:
            target_array = secondary_array

        volume_snaps = target_array.get_volume(pg_snap['name'],
                                               snap=True,
                                               pgroup=True)

        # We only care about volumes that are in the list we are given.
        vol_names = set()
        for vol in volumes:
            vol_names.add(self._get_vol_name(vol))

        for snap in volume_snaps:
            vol_name = snap['name'].split('.')[-1]
            if vol_name in vol_names:
                vol_names.remove(vol_name)
                LOG.debug('Creating volume %(vol)s from replicated snapshot '
                          '%(snap)s', {'vol': vol_name, 'snap': snap['name']})
                secondary_array.copy_volume(snap['name'],
                                            vol_name,
                                            overwrite=True)
            else:
                LOG.debug('Ignoring unmanaged volume %(vol)s from replicated '
                          'snapshot %(snap)s.', {'vol': vol_name,
                                                 'snap': snap['name']})
        # The only volumes remaining in the vol_names set have been left behind
        # on the array and should be considered as being in an error state.
        model_updates = []
        for vol in volumes:
            if self._get_vol_name(vol) in vol_names:
                model_updates.append({
                    'volume_id': vol['id'],
                    'updates': {
                        'status': 'error',
                    }
                })
            else:
                repl_status = fields.ReplicationStatus.FAILED_OVER
                model_updates.append({
                    'volume_id': vol['id'],
                    'updates': {
                        'replication_status': repl_status,
                    }
                })
        return model_updates

    def _sync_failover_host(self, volumes, secondary_array):
        """Perform a failover for hosts in an ActiveCluster setup

        There isn't actually anything that needs to be changed, only
        update the volume status to distinguish the survivors..
        """
        array_volumes = secondary_array.list_volumes()
        replicated_vol_names = set()
        for vol in array_volumes:
            name = vol['name']
            if name.startswith(self._replication_pod_name):
                replicated_vol_names.add(name)

        model_updates = []
        for vol in volumes:
            if self._get_vol_name(vol) not in replicated_vol_names:
                model_updates.append({
                    'volume_id': vol['id'],
                    'updates': {
                        'status': fields.VolumeStatus.ERROR,
                    }
                })
            else:
                repl_status = fields.ReplicationStatus.FAILED_OVER
                model_updates.append({
                    'volume_id': vol['id'],
                    'updates': {
                        'replication_status': repl_status,
                    }
                })
        return model_updates

    def _get_wwn(self, pure_vol_name):
        """Return the WWN based on the volume's serial number

        The WWN is composed of the constant '36', the OUI for Pure, followed
        by '0', and finally the serial number.
        """
        array = self._get_current_array()
        volume_info = array.get_volume(pure_vol_name)
        wwn = '3624a9370' + volume_info['serial']
        return wwn.lower()

    def _get_current_array(self):
        return self._array

    def _set_current_array(self, array):
        self._array = array


@interface.volumedriver
class PureISCSIDriver(PureBaseVolumeDriver, san.SanISCSIDriver):
    """OpenStack Volume Driver to support Pure Storage FlashArray.

    This version of the driver enables the use of iSCSI for
    the underlying storage connectivity with the FlashArray.
    """

    VERSION = "8.0.0"

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureISCSIDriver, self).__init__(execute=execute, *args, **kwargs)
        self._storage_protocol = "iSCSI"

    def _get_host(self, array, connector, remote=False):
        """Return dict describing existing Purity host object or None."""
        if (remote and array.get_rest_version() in
                SYNC_REPLICATION_REQUIRED_API_VERSIONS):
            hosts = array.list_hosts(remote=True)
        else:
            hosts = array.list_hosts()
        matching_hosts = []
        for host in hosts:
            if connector["initiator"] in host["iqn"]:
                matching_hosts.append(host)
        return matching_hosts

    @pure_driver_debug_trace
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        pure_vol_name = self._get_vol_name(volume)
        target_arrays = [self._get_current_array()]
        if (self._is_vol_in_pod(pure_vol_name) and
                self._is_active_cluster_enabled):
            target_arrays += self._uniform_active_cluster_target_arrays

        chap_username = None
        chap_password = None
        if self.configuration.use_chap_auth:
            (chap_username, chap_password) = self._get_chap_credentials(
                connector['host'], connector["initiator"])

        targets = []
        for array in target_arrays:
            connection = self._connect(array, pure_vol_name, connector,
                                       chap_username, chap_password)

            target_ports = self._get_target_iscsi_ports(array)
            targets.append({
                "connection": connection,
                "ports": target_ports,
            })

        properties = self._build_connection_properties(targets)
        properties["data"]["wwn"] = self._get_wwn(pure_vol_name)

        if self.configuration.use_chap_auth:
            properties["data"]["auth_method"] = "CHAP"
            properties["data"]["auth_username"] = chap_username
            properties["data"]["auth_password"] = chap_password

        return properties

    def _build_connection_properties(self, targets):
        props = {
            "driver_volume_type": "iscsi",
            "data": {
                "target_discovered": False,
                "discard": True,
            },
        }

        target_luns = []
        target_iqns = []
        target_portals = []

        # Aggregate all targets together, we may end up with different LUNs
        # for different target iqn/portal sets (ie. it could be a unique LUN
        # for each FlashArray)
        for target in targets:
            port_iter = iter(target["ports"])
            for port in port_iter:
                target_luns.append(target["connection"]["lun"])
                target_iqns.append(port["iqn"])
                target_portals.append(port["portal"])

        # If we have multiple ports always report them.
        if target_luns and target_iqns and target_portals:
            props["data"]["target_luns"] = target_luns
            props["data"]["target_iqns"] = target_iqns
            props["data"]["target_portals"] = target_portals

        return props

    def _get_target_iscsi_ports(self, array):
        """Return list of iSCSI-enabled port descriptions."""
        ports = array.list_ports()
        iscsi_ports = [port for port in ports if port["iqn"]]
        if not iscsi_ports:
            raise exception.PureDriverException(
                reason=_("No iSCSI-enabled ports on target array."))
        return iscsi_ports

    @staticmethod
    def _generate_chap_secret():
        return volume_utils.generate_password()

    def _get_chap_secret_from_init_data(self, initiator):
        data = self.driver_utils.get_driver_initiator_data(initiator)
        if data:
            for d in data:
                if d["key"] == CHAP_SECRET_KEY:
                    return d["value"]
        return None

    def _get_chap_credentials(self, host, initiator):
        username = host
        password = self._get_chap_secret_from_init_data(initiator)
        if not password:
            password = self._generate_chap_secret()
            success = self.driver_utils.insert_driver_initiator_data(
                initiator, CHAP_SECRET_KEY, password)
            if not success:
                # The only reason the save would have failed is if someone
                # else (read: another thread/instance of the driver) set
                # one before we did. In that case just do another query.
                password = self._get_chap_secret_from_init_data(initiator)

        return username, password

    @utils.retry(exception.PureRetryableException,
                 retries=HOST_CREATE_MAX_RETRIES)
    def _connect(self, array, vol_name, connector,
                 chap_username, chap_password):
        """Connect the host and volume; return dict describing connection."""
        iqn = connector["initiator"]
        hosts = self._get_host(array, connector, remote=False)
        host = hosts[0] if len(hosts) > 0 else None
        if host:
            host_name = host["name"]
            LOG.info("Re-using existing purity host %(host_name)r",
                     {"host_name": host_name})
            if self.configuration.use_chap_auth:
                if not GENERATED_NAME.match(host_name):
                    LOG.error("Purity host %(host_name)s is not managed "
                              "by Cinder and can't have CHAP credentials "
                              "modified. Remove IQN %(iqn)s from the host "
                              "to resolve this issue.",
                              {"host_name": host_name,
                               "iqn": connector["initiator"]})
                    raise exception.PureDriverException(
                        reason=_("Unable to re-use a host that is not "
                                 "managed by Cinder with use_chap_auth=True,"))
                elif chap_username is None or chap_password is None:
                    LOG.error("Purity host %(host_name)s is managed by "
                              "Cinder but CHAP credentials could not be "
                              "retrieved from the Cinder database.",
                              {"host_name": host_name})
                    raise exception.PureDriverException(
                        reason=_("Unable to re-use host with unknown CHAP "
                                 "credentials configured."))
        else:
            host_name = self._generate_purity_host_name(connector["host"])
            LOG.info("Creating host object %(host_name)r with IQN:"
                     " %(iqn)s.", {"host_name": host_name, "iqn": iqn})
            try:
                array.create_host(host_name, iqnlist=[iqn])
            except purestorage.PureHTTPError as err:
                if (err.code == 400 and
                        (ERR_MSG_ALREADY_EXISTS in err.text or
                            ERR_MSG_ALREADY_IN_USE in err.text)):
                    # If someone created it before we could just retry, we will
                    # pick up the new host.
                    LOG.debug('Unable to create host: %s', err.text)
                    raise exception.PureRetryableException()

            if self.configuration.use_chap_auth:
                try:
                    array.set_host(host_name,
                                   host_user=chap_username,
                                   host_password=chap_password)
                except purestorage.PureHTTPError as err:
                    if (err.code == 400 and
                            ERR_MSG_HOST_NOT_EXIST in err.text):
                        # If the host disappeared out from under us that's ok,
                        # we will just retry and snag a new host.
                        LOG.debug('Unable to set CHAP info: %s', err.text)
                        raise exception.PureRetryableException()

        # TODO(patrickeast): Ensure that the host has the correct preferred
        # arrays configured for it.

        connection = self._connect_host_to_vol(array,
                                               host_name,
                                               vol_name)

        return connection


@interface.volumedriver
class PureFCDriver(PureBaseVolumeDriver, driver.FibreChannelDriver):
    """OpenStack Volume Driver to support Pure Storage FlashArray.

    This version of the driver enables the use of Fibre Channel for
    the underlying storage connectivity with the FlashArray. It fully
    supports the Cinder Fibre Channel Zone Manager.
    """

    VERSION = "6.0.0"

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureFCDriver, self).__init__(execute=execute, *args, **kwargs)
        self._storage_protocol = "FC"
        self._lookup_service = fczm_utils.create_lookup_service()

    def _get_host(self, array, connector, remote=False):
        """Return dict describing existing Purity host object or None."""
        if (remote and array.get_rest_version() in
                SYNC_REPLICATION_REQUIRED_API_VERSIONS):
            hosts = array.list_hosts(remote=True)
        else:
            hosts = array.list_hosts()
        matching_hosts = []
        for host in hosts:
            for wwn in connector["wwpns"]:
                if wwn.lower() in str(host["wwn"]).lower():
                    matching_hosts.append(host)
                    break  # go to next host
        return matching_hosts

    @staticmethod
    def _get_array_wwns(array):
        """Return list of wwns from the array"""
        ports = array.list_ports()
        return [port["wwn"] for port in ports if port["wwn"]]

    @pure_driver_debug_trace
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        pure_vol_name = self._get_vol_name(volume)
        target_arrays = [self._get_current_array()]
        if (self._is_vol_in_pod(pure_vol_name) and
                self._is_active_cluster_enabled):
            target_arrays += self._uniform_active_cluster_target_arrays

        target_luns = []
        target_wwns = []
        for array in target_arrays:
            connection = self._connect(array, pure_vol_name, connector)
            array_wwns = self._get_array_wwns(array)
            for wwn in array_wwns:
                target_wwns.append(wwn)
                target_luns.append(connection["lun"])

        # Build the zoning map based on *all* wwns, this could be multiple
        # arrays connecting to the same host with a strected volume.
        init_targ_map = self._build_initiator_target_map(target_wwns,
                                                         connector)

        properties = {
            "driver_volume_type": "fibre_channel",
            "data": {
                "target_discovered": True,
                "target_lun": target_luns[0],  # For backwards compatibility
                "target_luns": target_luns,
                "target_wwn": target_wwns,
                "target_wwns": target_wwns,
                "initiator_target_map": init_targ_map,
                "discard": True,
            }
        }
        properties["data"]["wwn"] = self._get_wwn(pure_vol_name)

        fczm_utils.add_fc_zone(properties)
        return properties

    @utils.retry(exception.PureRetryableException,
                 retries=HOST_CREATE_MAX_RETRIES)
    def _connect(self, array, vol_name, connector):
        """Connect the host and volume; return dict describing connection."""
        wwns = connector["wwpns"]
        hosts = self._get_host(array, connector, remote=False)
        host = hosts[0] if len(hosts) > 0 else None

        if host:
            host_name = host["name"]
            LOG.info("Re-using existing purity host %(host_name)r",
                     {"host_name": host_name})
        else:
            host_name = self._generate_purity_host_name(connector["host"])
            LOG.info("Creating host object %(host_name)r with WWN:"
                     " %(wwn)s.", {"host_name": host_name, "wwn": wwns})
            try:
                array.create_host(host_name, wwnlist=wwns)
            except purestorage.PureHTTPError as err:
                if (err.code == 400 and
                        (ERR_MSG_ALREADY_EXISTS in err.text or
                            ERR_MSG_ALREADY_IN_USE in err.text)):
                    # If someone created it before we could just retry, we will
                    # pick up the new host.
                    LOG.debug('Unable to create host: %s', err.text)
                    raise exception.PureRetryableException()

        # TODO(patrickeast): Ensure that the host has the correct preferred
        # arrays configured for it.

        return self._connect_host_to_vol(array, host_name, vol_name)

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

    @pure_driver_debug_trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection."""
        vol_name = self._get_vol_name(volume)
        unused_wwns = []

        if self._is_vol_in_pod(vol_name):
            # Try to disconnect from each host, they may not be online though
            # so if they fail don't cause a problem.
            for array in self._uniform_active_cluster_target_arrays:
                try:
                    no_more_connections = self._disconnect(
                        array, volume, connector, remove_remote_hosts=False)
                    if no_more_connections:
                        unused_wwns += self._get_array_wwns(array)
                except purestorage.PureError as err:
                    # Swallow any exception, just warn and continue
                    LOG.warning("Disconnect on sendondary array failed with"
                                " message: %(msg)s", {"msg": err.text})

        # Now disconnect from the current array, removing any left over
        # remote hosts that we maybe couldn't reach.
        current_array = self._get_current_array()
        no_more_connections = self._disconnect(current_array,
                                               volume, connector,
                                               remove_remote_hosts=False)
        if no_more_connections:
            unused_wwns += self._get_array_wwns(current_array)

        properties = {"driver_volume_type": "fibre_channel", "data": {}}
        if len(unused_wwns) > 0:
            init_targ_map = self._build_initiator_target_map(unused_wwns,
                                                             connector)
            properties["data"] = {"target_wwn": unused_wwns,
                                  "initiator_target_map": init_targ_map}

        fczm_utils.remove_fc_zone(properties)
        return properties
