# Copyright (c) 2024 Pure Storage, Inc.
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
"""Volume driver for Pure Storage FlashArray storage system.

This driver requires Purity version 6.1.0 or higher.
"""

import functools
import ipaddress
import math
import re
import time
import uuid

import distro
from os_brick import constants as brick_constants
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import units
from packaging import version
try:
    from pypureclient import flasharray
except ImportError:
    flasharray = None

from cinder.common import constants
from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.objects import fields
from cinder.objects import volume_type
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import volume_types
from cinder.volume import volume_utils
from cinder.zonemanager import utils as fczm_utils

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
    cfg.StrOpt("pure_host_personality",
               default=None,
               choices=['aix', 'esxi', 'hitachi-vsp', 'hpux',
                        'oracle-vm-server', 'solaris', 'vms', None],
               help="Determines how the Purity system tunes the protocol used "
                    "between the array and the initiator."),
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
    cfg.StrOpt("pure_trisync_pg_name", default="cinder-trisync",
               help="Pure Protection Group name to use for trisync "
                    "replication leg inside the sync replication pod "
                    "(will be created if it does not exist)."),
    cfg.StrOpt("pure_replication_pod_name", default="cinder-pod",
               help="Pure Pod name to use for sync replication "
                    "(will be created if it does not exist)."),
    cfg.StrOpt("pure_iscsi_cidr", default="0.0.0.0/0",
               help="CIDR of FlashArray iSCSI targets hosts are allowed to "
                    "connect to. Default will allow connection to any "
                    "IPv4 address. This parameter now supports IPv6 subnets. "
                    "Ignored when pure_iscsi_cidr_list is set."),
    cfg.ListOpt("pure_iscsi_cidr_list", default=None,
                help="Comma-separated list of CIDR of FlashArray iSCSI "
                     "targets hosts are allowed to connect to. It supports "
                     "IPv4 and IPv6 subnets. This parameter supersedes "
                     "pure_iscsi_cidr."),
    cfg.StrOpt("pure_nvme_cidr", default="0.0.0.0/0",
               help="CIDR of FlashArray NVMe targets hosts are allowed to "
                    "connect to. Default will allow connection to any "
                    "IPv4 address. This parameter now supports IPv6 subnets. "
                    "Ignored when pure_nvme_cidr_list is set."),
    cfg.ListOpt("pure_nvme_cidr_list", default=None,
                help="Comma-separated list of CIDR of FlashArray NVMe "
                     "targets hosts are allowed to connect to. It supports "
                     "IPv4 and IPv6 subnets. This parameter supersedes "
                     "pure_nvme_cidr."),
    cfg.StrOpt("pure_nvme_transport", default="roce",
               choices=['roce', 'tcp'],
               help="The NVMe transport layer to be used by the NVMe driver."),
    cfg.BoolOpt("pure_eradicate_on_delete",
                default=False,
                help="When enabled, all Pure volumes, snapshots, and "
                     "protection groups will be eradicated at the time of "
                     "deletion in Cinder. Data will NOT be recoverable after "
                     "a delete with this set to True! When disabled, volumes "
                     "and snapshots will go into pending eradication state "
                     "and can be recovered."),
    cfg.BoolOpt("pure_trisync_enabled",
                default=False,
                help="When enabled and two replication devices are provided, "
                     "one each of types sync and async, this will enable "
                     "the ability to create a volume that is sync replicated "
                     "to one array and async replicated to a separate array.")
]

CONF = cfg.CONF
CONF.register_opts(PURE_OPTS, group=configuration.SHARED_CONF_GROUP)

INVALID_CHARACTERS = re.compile(r"[^-a-zA-Z0-9]")
GENERATED_NAME = re.compile(r".*-[a-f0-9]{32}-cinder$")

REPLICATION_TYPE_SYNC = "sync"
REPLICATION_TYPE_ASYNC = "async"
REPLICATION_TYPE_TRISYNC = "trisync"
REPLICATION_TYPES = [
    REPLICATION_TYPE_SYNC,
    REPLICATION_TYPE_ASYNC,
    REPLICATION_TYPE_TRISYNC
]

CHAP_SECRET_KEY = "PURE_TARGET_CHAP_SECRET"

ERR_MSG_NOT_EXIST = "does not exist"
ERR_MSG_HOST_NOT_EXIST = "Host " + ERR_MSG_NOT_EXIST
ERR_MSG_NO_SUCH_SNAPSHOT = "No such volume or snapshot"
ERR_MSG_PENDING_ERADICATION = "has been destroyed"
ERR_MSG_ALREADY_EXISTS = "already exists"
ERR_MSG_COULD_NOT_BE_FOUND = "could not be found"
ERR_MSG_ALREADY_INCLUDES = "already includes"
ERR_MSG_ALREADY_ALLOWED = "already allowed on"
ERR_MSG_ALREADY_BELONGS = "already belongs to"
ERR_MSG_EXISTING_CONNECTIONS = "cannot be deleted due to existing connections"
ERR_MSG_ALREADY_IN_USE = "already in use"
ERR_MSG_ARRAY_LIMIT = "limit reached"

EXTRA_SPECS_REPL_ENABLED = "replication_enabled"
EXTRA_SPECS_REPL_TYPE = "replication_type"

MAX_VOL_LENGTH = 63
MAX_SNAP_LENGTH = 96
UNMANAGED_SUFFIX = '-unmanaged'

NVME_PORT = 4420

REPL_SETTINGS_PROPAGATE_RETRY_INTERVAL = 5  # 5 seconds
REPL_SETTINGS_PROPAGATE_MAX_RETRIES = 36  # 36 * 5 = 180 seconds

HOST_CREATE_MAX_RETRIES = 5

USER_AGENT_BASE = 'OpenStack Cinder'

MIN_IOPS = 100
MAX_IOPS = 100000000  # 100M
MIN_BWS = 1048576  # 1 MB/s
MAX_BWS = 549755813888  # 512 GB/s


class PureDriverException(exception.VolumeDriverException):
    message = _("Pure Storage Cinder driver failure: %(reason)s")


class PureRetryableException(exception.VolumeBackendAPIException):
    message = _("Retryable Pure Storage Exception encountered")


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
        backend_name = driver._get_current_array(True).backend_id
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

    SUPPORTS_ACTIVE_ACTIVE = True
    PURE_QOS_KEYS = ['maxIOPS', 'maxBWS']
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
        self._trisync_pg_name = None
        self._replication_pg_name = None
        self._trisync_name = None
        self._replication_pod_name = None
        self._replication_interval = None
        self._replication_retention_short_term = None
        self._replication_retention_long_term = None
        self._replication_retention_long_term_per_day = None
        self._async_replication_retention_policy = {}
        self._is_replication_enabled = False
        self._is_active_cluster_enabled = False
        self._is_trisync_enabled = False
        self._active_backend_id = kwargs.get('active_backend_id', None)
        self._failed_over_primary_array = None
        self._user_agent = '%(base)s %(class)s/%(version)s (%(platform)s)' % {
            'base': USER_AGENT_BASE,
            'class': self.__class__.__name__,
            'version': self.VERSION,
            'platform': distro.name(pretty=True)
        }

    @classmethod
    def get_driver_options(cls):
        additional_opts = cls._get_oslo_driver_opts(
            'san_ip', 'driver_ssl_cert_verify', 'driver_ssl_cert_path',
            'use_chap_auth', 'replication_device', 'reserved_percentage',
            'max_over_subscription_ratio', 'pure_nvme_transport',
            'pure_nvme_cidr_list', 'pure_nvme_cidr',
            'pure_trisync_enabled', 'pure_trisync_pg_name')
        return PURE_OPTS + additional_opts

    def parse_replication_configs(self):
        self._trisync_pg_name = (
            self.configuration.pure_trisync_pg_name)
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
                verify_ssl = strutils.bool_from_string(
                    replication_device.get("ssl_cert_verify", False))
                ssl_cert_path = replication_device.get("ssl_cert_path", None)
                repl_type = replication_device.get("type",
                                                   REPLICATION_TYPE_ASYNC)
                uniform = strutils.bool_from_string(
                    replication_device.get("uniform", False))

                target_array = self._get_flasharray(
                    san_ip,
                    api_token,
                    verify_ssl=verify_ssl,
                    ssl_cert_path=ssl_cert_path
                )
                if target_array:
                    target_array_info = list(
                        target_array.get_arrays().items
                    )[0]
                    target_array.array_name = target_array_info.name
                    target_array.array_id = target_array_info.id
                    target_array.replication_type = repl_type
                    target_array.backend_id = backend_id
                    target_array.uniform = uniform

                    LOG.info("Added secondary array: backend_id='%s',"
                             " name='%s', id='%s', type='%s', uniform='%s'",
                             target_array.backend_id,
                             target_array.array_name,
                             target_array.array_id,
                             target_array.replication_type,
                             target_array.uniform)
                else:
                    LOG.warning("Failed to set up secondary array: %(ip)s",
                                {"ip": san_ip})
                    continue

                self._replication_target_arrays.append(target_array)
                if repl_type == REPLICATION_TYPE_SYNC:
                    self._active_cluster_target_arrays.append(target_array)
                    if target_array.uniform:
                        self._uniform_active_cluster_target_arrays.append(
                            target_array)

    @pure_driver_debug_trace
    def set_qos(self, array, vol_name, qos):
        if qos['maxIOPS'] == 0 and qos['maxBWS'] == 0:
            array.patch_volumes(names=[vol_name],
                                volume=flasharray.VolumePatch(
                                    qos=flasharray.Qos(
                                        iops_limit=MAX_IOPS,
                                        bandwidth_limit=MAX_BWS)))
        elif qos['maxIOPS'] == 0:
            array.patch_volumes(names=[vol_name],
                                volume=flasharray.VolumePatch(
                                    qos=flasharray.Qos(
                                        iops_limit=MAX_IOPS,
                                        bandwidth_limit=qos['maxBWS'])))
        elif qos['maxBWS'] == 0:
            array.patch_volumes(names=[vol_name],
                                volume=flasharray.VolumePatch(
                                    qos=flasharray.Qos(
                                        iops_limit=qos['maxIOPS'],
                                        bandwidth_limit=MAX_BWS)))
        else:
            array.patch_volumes(names=[vol_name],
                                volume=flasharray.VolumePatch(
                                    qos=flasharray.Qos(
                                        iops_limit=qos['maxIOPS'],
                                        bandwidth_limit=qos['maxBWS'])))
        return

    @pure_driver_debug_trace
    def create_from_snap_in_vgroup(self,
                                   array,
                                   vol_name,
                                   snap_name,
                                   vgroup,
                                   vg_iop,
                                   vg_bw):
        if not (MIN_IOPS <= int(vg_iop) <= MAX_IOPS):
            msg = (_('vg_maxIOPS QoS error. Must be more than '
                     '%(min_iops)s and less than %(max_iops)s') %
                   {'min_iops': MIN_IOPS, 'max_iops': MAX_IOPS})
            raise exception.InvalidQoSSpecs(message=msg)
        if not (MIN_BWS <= int(vg_bw) <= MAX_BWS):
            msg = (_('vg_maxBWS QoS error. Must be between '
                     '%(min_bws)s and %(max_bws)s') %
                   {'min_bws': MIN_BWS, 'max_bws': MAX_BWS})
            raise exception.InvalidQoSSpecs(message=msg)
        self._create_volume_group_if_not_exist(array,
                                               vgroup,
                                               int(vg_iop),
                                               int(vg_bw))
        vg_volname = vgroup + "/" + vol_name
        if self._array.safemode:
            array.post_volumes(names=[vg_volname],
                               with_default_protection=False,
                               volume=flasharray.VolumePost(
                                   source=flasharray.Reference(
                                       name=snap_name)))
        else:
            array.post_volumes(names=[vg_volname],
                               volume=flasharray.VolumePost(
                               source=flasharray.Reference(name=snap_name)))
        return vg_volname

    @pure_driver_debug_trace
    def create_in_vgroup(self,
                         array,
                         vol_name,
                         vol_size,
                         vgroup,
                         vg_iop,
                         vg_bw):
        if not (MIN_IOPS <= int(vg_iop) <= MAX_IOPS):
            msg = (_('vg_maxIOPS QoS error. Must be more than '
                     '%(min_iops)s and less than %(max_iops)s') %
                   {'min_iops': MIN_IOPS, 'max_iops': MAX_IOPS})
            raise exception.InvalidQoSSpecs(message=msg)
        if not (MIN_BWS <= int(vg_bw) <= MAX_BWS):
            msg = (_('vg_maxBWS QoS error. Must be between '
                     '%(min_bws)s and %(max_bws)s') %
                   {'min_bws': MIN_BWS, 'max_bws': MAX_BWS})
            raise exception.InvalidQoSSpecs(message=msg)
        self._create_volume_group_if_not_exist(array,
                                               vgroup,
                                               int(vg_iop),
                                               int(vg_bw))
        vg_volname = vgroup + "/" + vol_name
        if self._array.safemode:
            array.post_volumes(names=[vg_volname],
                               with_default_protection=False,
                               volume=flasharray.VolumePost(
                               provisioned=vol_size))
        else:
            array.post_volumes(names=[vg_volname],
                               volume=flasharray.VolumePost(
                               provisioned=vol_size))
        return vg_volname

    @pure_driver_debug_trace
    def create_with_qos(self, array, vol_name, vol_size, qos):
        if self._array.safemode:
            if qos['maxIOPS'] == 0 and qos['maxBWS'] == 0:
                array.post_volumes(names=[vol_name],
                                   with_default_protection=False,
                                   volume=flasharray.VolumePost(
                                       provisioned=vol_size))
            elif qos['maxIOPS'] == 0:
                array.post_volumes(names=[vol_name],
                                   with_default_protection=False,
                                   volume=flasharray.VolumePost(
                                       provisioned=vol_size,
                                       qos=flasharray.Qos(
                                           bandwidth_limit=qos['maxBWS'])))
            elif qos['maxBWS'] == 0:
                array.post_volumes(names=[vol_name],
                                   with_default_protection=False,
                                   volume=flasharray.VolumePost(
                                       provisioned=vol_size,
                                       qos=flasharray.Qos(
                                           iops_limit=qos['maxIOPS'])))
            else:
                array.post_volumes(names=[vol_name],
                                   with_default_protection=False,
                                   volume=flasharray.VolumePost(
                                       provisioned=vol_size,
                                       qos=flasharray.Qos(
                                           iops_limit=qos['maxIOPS'],
                                           bandwidth_limit=qos['maxBWS'])))
        else:
            if qos['maxIOPS'] == 0 and qos['maxBWS'] == 0:
                array.post_volumes(names=[vol_name],
                                   volume=flasharray.VolumePost(
                                       provisioned=vol_size))
            elif qos['maxIOPS'] == 0:
                array.post_volumes(names=[vol_name],
                                   volume=flasharray.VolumePost(
                                       provisioned=vol_size,
                                       qos=flasharray.Qos(
                                           bandwidth_limit=qos['maxBWS'])))
            elif qos['maxBWS'] == 0:
                array.post_volumes(names=[vol_name],
                                   volume=flasharray.VolumePost(
                                       provisioned=vol_size,
                                       qos=flasharray.Qos(
                                           iops_limit=qos['maxIOPS'])))
            else:
                array.post_volumes(names=[vol_name],
                                   volume=flasharray.VolumePost(
                                       provisioned=vol_size,
                                       qos=flasharray.Qos(
                                           iops_limit=qos['maxIOPS'],
                                           bandwidth_limit=qos['maxBWS'])))
        return

    def do_setup(self, context):
        """Performs driver initialization steps that could raise exceptions."""
        if flasharray is None:
            msg = _("Missing 'py-pure-client' python module, ensure the"
                    " library is installed and available.")
            raise PureDriverException(msg)

        # Raises PureDriverException if unable to connect and PureError
        # if unable to authenticate.
        self._array = self._get_flasharray(
            san_ip=self.configuration.san_ip,
            api_token=self.configuration.pure_api_token,
            verify_ssl=self.configuration.driver_ssl_cert_verify,
            ssl_cert_path=self.configuration.driver_ssl_cert_path
        )
        if self._array:
            array_info = list(self._array.get_arrays().items)[0]
            if version.parse(array_info.version) < version.parse(
                '6.1.0'
            ):
                msg = _("FlashArray Purity version less than 6.1.0 "
                        "unsupported. Please upgrade your backend to "
                        "a supported version.")
                raise PureDriverException(msg)
            if version.parse(array_info.version) < version.parse(
                '6.4.2'
            ) and self._storage_protocol == constants.NVMEOF_TCP:
                msg = _("FlashArray Purity version less than 6.4.2 "
                        "unsupported for NVMe-TCP. Please upgrade your "
                        "backend to a supported version.")
                raise PureDriverException(msg)

            self._array.array_name = array_info.name
            self._array.array_id = array_info.id
            self._array.replication_type = None
            self._array.backend_id = self._backend_name
            self._array.preferred = True
            self._array.uniform = True
            self._array.version = array_info.version
            if version.parse(array_info.version) < version.parse(
                '6.3.4'
            ):
                self._array.safemode = False
            else:
                self._array.safemode = True

            LOG.info("Primary array: backend_id='%s', name='%s', id='%s'",
                     self.configuration.config_group,
                     self._array.array_name,
                     self._array.array_id)
        else:
            LOG.warning("self.do_setup failed to set up primary array: %(ip)s",
                        {"ip": self.configuration.san_ip})

        self.do_setup_replication()

        if self.configuration.pure_trisync_enabled:
            # If trisync is enabled check that we have only 1 sync and 1 async
            # replication device set up and that the async target is not the
            # same as any of the sync targets.
            self.do_setup_trisync()

        # If we have failed over at some point we need to adjust our current
        # array based on the one that we have failed over to
        if (self._active_backend_id and
                self._active_backend_id != self._array.backend_id):
            secondary_array = self._get_secondary(self._active_backend_id)
            self._swap_replication_state(self._array, secondary_array)

    def do_setup_trisync(self):
        repl_device = {}
        async_target = []
        count = 0
        replication_devices = self.configuration.safe_get(
            'replication_device')
        if not replication_devices or len(replication_devices) != 2:
            LOG.error("Unable to configure TriSync Replication. Incorrect "
                      "number of replication devices enabled. "
                      "Only 2 are supported.")
        else:
            for replication_device in replication_devices:
                san_ip = replication_device["san_ip"]
                api_token = replication_device["api_token"]
                repl_type = replication_device.get(
                    "type", REPLICATION_TYPE_ASYNC)
                repl_device[count] = {
                    "rep_type": repl_type,
                    "token": api_token,
                    "san_ip": san_ip,
                }
                count += 1
            if (repl_device[0]["rep_type"] == repl_device[1]["rep_type"]) or (
                    (repl_device[0]["token"] == repl_device[1]["token"])
            ):
                LOG.error("Replication devices provided must be one each "
                          "of sync and async and targets must be different "
                          "to enable TriSync Replication.")
                return
            for replication_device in replication_devices:
                repl_type = replication_device.get(
                    "type", REPLICATION_TYPE_ASYNC)
                if repl_type == "async":
                    san_ip = replication_device["san_ip"]
                    api_token = replication_device["api_token"]
                    verify_ssl = strutils.bool_from_string(
                        replication_device.get("ssl_cert_verify", False))
                    ssl_cert_path = replication_device.get(
                        "ssl_cert_path", None)
                    target_array = self._get_flasharray(
                        san_ip,
                        api_token,
                        verify_ssl=verify_ssl,
                        ssl_cert_path=ssl_cert_path
                    )
                    trisync_async_info = list(
                        target_array.get_arrays().items)[0]
                    target_array.array_name = trisync_async_info.name

                    async_target.append(target_array)

            self._trisync_name = self._replication_pod_name + \
                "::" + \
                self._trisync_pg_name
            self._is_trisync_enabled = True
            self._setup_replicated_pgroups(
                self._get_current_array(),
                async_target,
                self._trisync_name,
                self._replication_interval,
                self._async_replication_retention_policy
            )

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
                    self._get_current_array(True),
                    self._active_cluster_target_arrays,
                    self._replication_pod_name
                )

            # Even if the array is configured for sync rep set it
            # up to handle async too
            self._setup_replicated_pgroups(
                self._get_current_array(True),
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
                vol.provider_id = self._get_vol_name(vol)
                vol_name = self._generate_purity_vol_name(vol)
                if vol.metadata:
                    vol_updates.append({
                        'id': vol.id,
                        'provider_id': vol_name,
                        'metadata': {**vol.metadata,
                                     'array_volume_name': vol_name,
                                     'array_name': self._array.array_name},
                    })
                else:
                    vol_updates.append({
                        'id': vol.id,
                        'provider_id': vol_name,
                        'metadata': {'array_volume_name': vol_name,
                                     'array_name': self._array.array_name},
                    })
        return vol_updates, None

    @pure_driver_debug_trace
    def revert_to_snapshot(self, context, volume, snapshot):
        """Is called to perform revert volume from snapshot.

        :param context: Our working context.
        :param volume: the volume to be reverted.
        :param snapshot: the snapshot data revert to volume.
        :return None
        """
        vol_name = self._generate_purity_vol_name(volume)
        if snapshot['group_snapshot'] or snapshot['cgsnapshot']:
            snap_name = self._get_pgroup_snap_name_from_snapshot(snapshot)
        else:
            snap_name = self._get_snap_name(snapshot)

        LOG.debug("Reverting from snapshot %(snap)s to volume "
                  "%(vol)s", {'vol': vol_name, 'snap': snap_name})

        current_array = self._get_current_array()

        current_array.post_volumes(names=[snap_name], overwrite=True,
                                   volume=flasharray.VolumePost(
                                       source=flasharray.Reference(
                                           name=vol_name)))

    @pure_driver_debug_trace
    def create_volume(self, volume):
        """Creates a volume.

        Note that if a vgroup is specified in the volume type
        extra_spec then we do not apply volume level qos as this is
        incompatible with volume group qos settings.

        We will force a volume group to have the maximum qos settings
        if not specified in the volume type extra_spec as this can
        cause retyping issues in the future if not defined.
        """
        qos = None
        vol_name = self._generate_purity_vol_name(volume)
        vol_size = volume["size"] * units.Gi
        ctxt = context.get_admin_context()
        type_id = volume.get('volume_type_id')
        current_array = self._get_current_array()
        if type_id is not None:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            vg_iops = self._get_volume_type_extra_spec(type_id,
                                                       'vg_maxIOPS',
                                                       default_value=MAX_IOPS)
            vg_bws = self._get_volume_type_extra_spec(type_id,
                                                      'vg_maxBWS',
                                                      default_value=MAX_BWS)
            vgroup = self._get_volume_type_extra_spec(type_id, 'vg_name')
            if vgroup:
                vgroup = INVALID_CHARACTERS.sub("-", vgroup)
                vg_volname = self.create_in_vgroup(current_array,
                                                   vol_name,
                                                   vol_size,
                                                   vgroup,
                                                   vg_iops,
                                                   vg_bws)
                return self._setup_volume(current_array,
                                          volume,
                                          vg_volname)
            else:
                qos = self._get_qos_settings(volume_type)
        if qos is not None:
            self.create_with_qos(current_array, vol_name, vol_size, qos)
        else:
            if self._array.safemode:
                current_array.post_volumes(names=[vol_name],
                                           with_default_protection=False,
                                           volume=flasharray.VolumePost(
                                               provisioned=vol_size))
            else:
                current_array.post_volumes(names=[vol_name],
                                           volume=flasharray.VolumePost(
                                               provisioned=vol_size))

        return self._setup_volume(current_array, volume, vol_name)

    @pure_driver_debug_trace
    def create_volume_from_snapshot(self, volume, snapshot, cgsnapshot=False):
        """Creates a volume from a snapshot."""
        qos = None
        vol_name = self._generate_purity_vol_name(volume)
        if cgsnapshot:
            snap_name = self._get_pgroup_snap_name_from_snapshot(snapshot)
        else:
            snap_name = self._get_snap_name(snapshot)

        current_array = self._get_current_array()
        ctxt = context.get_admin_context()
        type_id = volume.get('volume_type_id')
        if type_id is not None:
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            vg_iops = self._get_volume_type_extra_spec(type_id,
                                                       'vg_maxIOPS',
                                                       default_value=MAX_IOPS)
            vg_bws = self._get_volume_type_extra_spec(type_id,
                                                      'vg_maxBWS',
                                                      default_value=MAX_BWS)
            vgroup = self._get_volume_type_extra_spec(type_id, 'vg_name')
            if vgroup:
                vgroup = INVALID_CHARACTERS.sub("-", vgroup)
                vg_volname = self.create_from_snap_in_vgroup(current_array,
                                                             vol_name,
                                                             snap_name,
                                                             vgroup,
                                                             vg_iops,
                                                             vg_bws)
                return self._setup_volume(current_array,
                                          volume,
                                          vg_volname)
            else:
                qos = self._get_qos_settings(volume_type)

        if self._array.safemode:
            current_array.post_volumes(names=[vol_name],
                                       with_default_protection=False,
                                       volume=flasharray.VolumePost(
                                           source=flasharray.Reference(
                                               name=snap_name)))
        else:
            current_array.post_volume(names=[vol_name],
                                      volume=flasharray.VolumePost(
                                          source=flasharray.Reference(
                                              name=snap_name)))
        self._extend_if_needed(current_array,
                               vol_name,
                               snapshot["volume_size"],
                               volume["size"])
        if qos is not None:
            self.set_qos(current_array, vol_name, qos)
        else:
            current_array.patch_volumes(names=[vol_name],
                                        volume=flasharray.VolumePatch(
                                            qos=flasharray.Qos(
                                                iops_limit=MAX_IOPS,
                                                bandwidth_limit=MAX_BWS)))

        return self._setup_volume(current_array, volume, vol_name)

    def _setup_volume(self, array, volume, purity_vol_name):
        # set provider_id early so other methods can use it even though
        # it wont be set in the cinder DB until we return from create_volume
        volume.provider_id = purity_vol_name
        async_enabled = False
        trisync_enabled = False
        self._add_to_group_if_needed(volume, purity_vol_name)
        async_enabled = self._enable_async_replication_if_needed(
            array, volume)
        trisync_enabled = self._enable_trisync_replication_if_needed(
            array, volume)
        repl_type = self._get_replication_type_from_vol_type(
            volume.volume_type)
        try:
            pgroup = array.get_protection_groups_volumes(
                member_names=[volume.provider_id]).items
        except AttributeError:
            # AttributeError from pypureclient SDK as volume
            # not in a protection group
            pgroup = None
        if (repl_type in [REPLICATION_TYPE_ASYNC, REPLICATION_TYPE_TRISYNC] and
                not pgroup):
            LOG.error("Failed to add volume %s to pgroup, removing volume")
            array.patch_volumes(names=[purity_vol_name],
                                volume=flasharray.VolumePatch(
                                    destroyed=True))
            array.delete_volumes(names=[purity_vol_name])

        repl_status = fields.ReplicationStatus.DISABLED
        if (self._is_vol_in_pod(purity_vol_name) or
                (async_enabled or trisync_enabled)):
            repl_status = fields.ReplicationStatus.ENABLED

        if not volume.metadata:
            model_update = {
                'id': volume.id,
                'provider_id': purity_vol_name,
                'replication_status': repl_status,
                'metadata': {'array_volume_name': purity_vol_name,
                             'array_name': self._array.array_name}
            }
        else:
            model_update = {
                'id': volume.id,
                'provider_id': purity_vol_name,
                'replication_status': repl_status,
                'metadata': {**volume.metadata,
                             'array_volume_name': purity_vol_name,
                             'array_name': self._array.array_name}
            }
        return model_update

    def _enable_async_replication_if_needed(self, array, volume):
        repl_type = self._get_replication_type_from_vol_type(
            volume.volume_type)
        if repl_type == REPLICATION_TYPE_ASYNC:
            self._enable_async_replication(array, volume)
            return True
        return False

    def _enable_trisync_replication_if_needed(self, array, volume):
        repl_type = self._get_replication_type_from_vol_type(
            volume.volume_type)
        if (self.configuration.pure_trisync_enabled and
                repl_type == REPLICATION_TYPE_TRISYNC):
            self._enable_trisync_replication(array, volume)
            return True
        return False

    def _enable_trisync_replication(self, array, volume):
        """Add volume to sync-replicated protection group"""
        array.post_protection_groups_volumes(
            group_names=[self._trisync_name],
            member_names=[self._get_vol_name(volume)])

    def _disable_trisync_replication(self, array, volume):
        """Remove volume from sync-replicated protection group"""
        array.delete_protection_groups_volumes(
            group_names=[self._trisync_name],
            member_names=[self._get_vol_name(volume)])

    def _enable_async_replication(self, array, volume):
        """Add volume to replicated protection group."""
        array.post_protection_groups_volumes(
            group_names=[self._replication_pg_name],
            member_names=[self._get_vol_name(volume)])

    @pure_driver_debug_trace
    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol_name = self._generate_purity_vol_name(volume)
        src_name = self._get_vol_name(src_vref)

        # Check which backend the source volume is on. In case of failover
        # the source volume may be on the secondary array.
        current_array = self._get_current_array()
        current_array.post_volumes(volume=flasharray.VolumePost(
            source=flasharray.Reference(name=src_name)), names=[vol_name])
        self._extend_if_needed(current_array,
                               vol_name,
                               src_vref["size"],
                               volume["size"])
        # Check if the volume_type has QoS settings and if so
        # apply them to the newly created volume
        qos = self._get_qos_settings(volume.volume_type)
        if qos:
            self.set_qos(current_array, vol_name, qos)

        return self._setup_volume(current_array, volume, vol_name)

    def _extend_if_needed(self, array, vol_name, src_size, vol_size):
        """Extend the volume from size src_size to size vol_size."""
        if vol_size > src_size:
            vol_size = vol_size * units.Gi
            array.patch_volumes(names=[vol_name],
                                volume=flasharray.VolumePatch(
                                    provisioned=vol_size))

    @pure_driver_debug_trace
    def delete_volume(self, volume):
        """Disconnect all hosts and delete the volume"""
        vol_name = self._get_vol_name(volume)
        current_array = self._get_current_array()
        # Do a pass over remaining connections on the current array, if
        # we can try and remove any remote connections too.
        hosts = list(current_array.get_connections(
            volume_names=[vol_name]).items)
        for host_info in range(0, len(hosts)):
            host_name = hosts[host_info].host.name
            self._disconnect_host(current_array, host_name, vol_name)

        # Finally, it should be safe to delete the volume
        res = current_array.patch_volumes(names=[vol_name],
                                          volume=flasharray.VolumePatch(
                                              destroyed=True))
        if self.configuration.pure_eradicate_on_delete:
            current_array.delete_volumes(names=[vol_name])
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if ERR_MSG_NOT_EXIST in res.errors[0].message:
                    # Happens if the volume does not exist.
                    ctxt.reraise = False
                    LOG.warning("Volume deletion failed with message: %s",
                                res.errors[0].message)
        # Now check to see if deleting this volume left an empty volume
        # group. If so, we delete / eradicate the volume group
        if "/" in vol_name:
            vgroup = vol_name.split("/")[0]
            self._delete_vgroup_if_empty(current_array, vgroup)

    @pure_driver_debug_trace
    def _delete_vgroup_if_empty(self, array, vgroup):
        """Delete volume group if empty"""

        vgroup_volumes = list(array.get_volume_groups(
            names=[vgroup]).items)[0].volume_count
        if vgroup_volumes == 0:
            # Delete the volume group
            array.patch_volume_groups(
                names=[vgroup],
                volume_group=flasharray.VolumeGroupPatch(
                    destroyed=True))
            if self.configuration.pure_eradicate_on_delete:
                # Eradciate the volume group
                res = array.delete_volume_groups(names=[vgroup])
                if res.status_code == 400:
                    with excutils.save_and_reraise_exception() as ctxt:
                        ctxt.reraise = False
                        LOG.warning("Volume group deletion failed "
                                    "with message: %s",
                                    res.errors[0].message)

    @pure_driver_debug_trace
    def create_snapshot(self, snapshot):
        """Creates a snapshot."""

        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array()
        vol_name, snap_suff = self._get_snap_name(snapshot).split(".")
        volume_snapshot = flasharray.VolumeSnapshotPost(suffix=snap_suff)
        current_array.post_volume_snapshots(source_names=[vol_name],
                                            volume_snapshot=volume_snapshot)
        if not snapshot.metadata:
            snapshot_update = {
                'metadata': {'array_snapshot_name': self._get_snap_name(
                    snapshot),
                    'array_name': self._array.array_name}
            }
        else:
            snapshot_update = {
                'metadata': {**snapshot.metadata,
                             'array_snapshot_name': self._get_snap_name(
                                 snapshot),
                             'array_name': self._array.array_name}
            }
        return snapshot_update

    @pure_driver_debug_trace
    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""

        # Get current array in case we have failed over via replication.
        current_array = self._get_current_array()

        snap_name = self._get_snap_name(snapshot)
        volume_snap = flasharray.VolumeSnapshotPatch(destroyed=True)
        res = current_array.patch_volume_snapshots(names=[snap_name],
                                                   volume_snapshot=volume_snap)
        if self.configuration.pure_eradicate_on_delete:
            current_array.delete_volume_snapshots(names=[snap_name])
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if (ERR_MSG_NOT_EXIST in res.errors[0].message or
                        ERR_MSG_NO_SUCH_SNAPSHOT in res.errors[0].message or
                        ERR_MSG_PENDING_ERADICATION in res.errors[0].message):
                    # Happens if the snapshot does not exist.
                    ctxt.reraise = False
                    LOG.warning("Unable to delete snapshot, assuming "
                                "already deleted. Error: %s",
                                res.errors[0].message)

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

    def _is_multiattach_to_host(self, volume_attachment, host_name):
        # When multiattach is enabled a volume could be attached to multiple
        # instances which are hosted on the same Nova compute.
        # Because Purity cannot recognize the volume is attached more than
        # one instance we should keep the volume attached to the Nova compute
        # until the volume is detached from the last instance
        if not volume_attachment:
            return False

        attachment = [a for a in volume_attachment
                      if a.attach_status == "attached" and
                      a.attached_host == host_name]
        return len(attachment) > 1

    @pure_driver_debug_trace
    def _disconnect(self, array, volume, connector, remove_remote_hosts=True,
                    is_multiattach=False):
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
            connections = list(array.get_connections(
                volume_names=[vol_name]).items)
            for connection in range(0, len(connections)):
                self._disconnect_host(array,
                                      connections[connection]['host'],
                                      vol_name)
            return False
        else:
            # Normal case with a specific initiator to detach it from
            hosts = self._get_host(array, connector,
                                   remote=remove_remote_hosts)
            if hosts:
                any_in_use = False
                host_in_use = False
                for host in hosts:
                    host_name = host.name
                    if not is_multiattach:
                        host_in_use = self._disconnect_host(array,
                                                            host_name,
                                                            vol_name)
                    else:
                        LOG.warning("Unable to disconnect host from volume. "
                                    "Volume is multi-attached.")
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
        # None `connector` indicates force detach, then delete all even
        # if the volume is multi-attached.
        multiattach = (connector is not None and
                       self._is_multiattach_to_host(volume.volume_attachment,
                                                    connector["host"]))
        if self._is_vol_in_pod(vol_name):
            # Try to disconnect from each host, they may not be online though
            # so if they fail don't cause a problem.
            for array in self._uniform_active_cluster_target_arrays:
                res = self._disconnect(array, volume, connector,
                                       remove_remote_hosts=False,
                                       is_multiattach=multiattach)
                if not res:
                    # Swallow any exception, just warn and continue
                    LOG.warning("Disconnect on secondary array failed")
        # Now disconnect from the current array
        self._disconnect(self._get_current_array(), volume,
                         connector, remove_remote_hosts=False,
                         is_multiattach=multiattach)

    @pure_driver_debug_trace
    def _disconnect_host(self, array, host_name, vol_name):
        """Return value indicates if host should be cleaned up."""
        res = array.delete_connections(host_names=[host_name],
                                       volume_names=[vol_name])
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if (ERR_MSG_NOT_EXIST in res.errors[0].message or
                        ERR_MSG_HOST_NOT_EXIST in res.errors[0].message):
                    # Happens if the host and volume are not connected or
                    # the host has already been deleted
                    ctxt.reraise = False
                    LOG.warning("Disconnection failed with message: "
                                "%(msg)s.",
                                {"msg": res.errors[0].message})

        # If it is a remote host, call it quits here. We cannot delete a remote
        # host even if it should be cleaned up now.
        if ':' in host_name:
            return

        connections = None
        res = array.get_connections(host_names=[host_name])
        connection_obj = getattr(res, "items", None)
        if connection_obj:
            connections = list(connection_obj)
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if ERR_MSG_NOT_EXIST in res.errors[0].message:
                    ctxt.reraise = False

        # Assume still used if volumes are attached
        host_still_used = bool(connections)
        if GENERATED_NAME.match(host_name) and not host_still_used:
            LOG.info("Attempting to delete unneeded host %(host_name)r.",
                     {"host_name": host_name})
            res = array.delete_hosts(names=[host_name])
            if res.status_code == 200:
                host_still_used = False
            else:
                with excutils.save_and_reraise_exception() as ctxt:
                    if ERR_MSG_NOT_EXIST in res.errors[0].message:
                        # Happens if the host is already deleted.
                        # This is fine though, just log so we know what
                        # happened.
                        ctxt.reraise = False
                        host_still_used = False
                        LOG.debug("Purity host deletion failed: "
                                  "%(msg)s.", {"msg": res.errors[0].message})
                    if ERR_MSG_EXISTING_CONNECTIONS in res.errors[0].message:
                        # If someone added a connection underneath us
                        # that's ok, just keep going.
                        ctxt.reraise = False
                        host_still_used = True
                        LOG.debug("Purity host deletion ignored: %(msg)s",
                                  {"msg": res.errors[0].message})
        return not host_still_used

    @pure_driver_debug_trace
    def _update_volume_stats(self):
        """Set self._stats with relevant information."""
        current_array = self._get_current_array()
        space_info = list(current_array.get_arrays_space().items)[0]
        perf_info = list(current_array.get_arrays_performance(
            end_time=int(time.time()) * 1000,
            start_time=(int(time.time()) * 1000) - 30000,
            resolution=30000
        ).items)[0]
        hosts = list(current_array.get_hosts().items)
        volumes = list(current_array.get_volumes().items)
        snaps = list(current_array.get_volume_snapshots().items)
        pgroups = list(current_array.get_protection_groups().items)

        # Perform some translations and calculations
        total_capacity = float(space_info.capacity) / units.Gi
        used_space = float(space_info.space.total_physical) / units.Gi
        free_space = float(total_capacity - used_space)
        # If array uses Evergreen/One model then total_provisioned
        # is not reported so use the closest value avaible in that
        # consumption model
        try:
            provisioned_space = float(space_info.space.
                                      total_provisioned) / units.Gi
        except AttributeError:
            provisioned_space = float(space_info.space.
                                      used_provisioned) / units.Gi
        total_reduction = float(space_info.space.total_reduction)
        total_vols = len(volumes)
        total_hosts = len(hosts)
        total_snaps = len(snaps)
        total_pgroups = len(pgroups)
        thin_provisioning = self._get_thin_provisioning(total_reduction)

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
        data['consistent_group_replication_enabled'] = True
        data['consistent_group_snapshot_enabled'] = True
        data['QoS_support'] = True

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
        data['writes_per_sec'] = perf_info.writes_per_sec
        data['reads_per_sec'] = perf_info.reads_per_sec

        #  Bandwidth
        data['input_per_sec'] = perf_info.write_bytes_per_sec
        data['output_per_sec'] = perf_info.read_bytes_per_sec

        #  Latency
        data['usec_per_read_op'] = perf_info.usec_per_read_op
        data['usec_per_write_op'] = perf_info.usec_per_write_op

        # TODO: Queue depth - deprecated - remove in 2026.1 cycle
        data['queue_depth'] = getattr(perf_info, 'queue_depth', 0)
        # Detailed I/O queuieing information
        data['queue_usec_per_mirrored_write_op'] = (
            perf_info.queue_usec_per_mirrored_write_op)
        data['queue_usec_per_read_op'] = perf_info.queue_usec_per_read_op
        data['queue_usec_per_write_op'] = perf_info.queue_usec_per_write_op

        #  Replication
        data["replication_capability"] = self._get_replication_capability()
        data["replication_enabled"] = self._is_replication_enabled
        repl_types = []
        if self._is_replication_enabled:
            repl_types = [REPLICATION_TYPE_ASYNC]
        if self._is_active_cluster_enabled:
            repl_types.append(REPLICATION_TYPE_SYNC)
        if self._is_trisync_enabled:
            repl_types.append(REPLICATION_TYPE_TRISYNC)
        data["replication_type"] = repl_types
        data["replication_count"] = len(self._replication_target_arrays)
        data["replication_targets"] = [array.backend_id for array
                                       in self._replication_target_arrays]
        self._stats = data

    def _get_replication_capability(self):
        """Discovered connected arrays status for replication"""
        connections = list(
            self._get_current_array().get_array_connections().items)
        is_sync, is_async, is_trisync = False, False, False
        for conn in range(0, len(connections)):
            # If connection status is connected, we can have
            # either sync or async replication
            if connections[conn].status == "connected":
                # check for async replication
                if connections[conn].type == "async-replication":
                    is_async = True
                # check for sync replication
                elif connections[conn].type == "sync-replication":
                    is_sync = True
            # If we've connections for both sync and async
            # replication, we can set trisync replication
            # and exit the loop
            if is_sync and is_async:
                is_trisync = True
                break
        # Check if it is a trisync replication
        if is_trisync:
            replication_type = "trisync"
        # If replication is not trisync, it will be either
        # sync or async
        elif is_sync:
            replication_type = "sync"
        elif is_async:
            replication_type = "async"
        else:
            replication_type = None
        return replication_type

    def _get_thin_provisioning(self, total_reduction):
        """Get the current value for the thin provisioning ratio.

        If pure_automatic_max_oversubscription_ratio is True we will calculate
        a value, if not we will respect the configuration option for the
        max_over_subscription_ratio.
        """

        if (self.configuration.pure_automatic_max_oversubscription_ratio and
                total_reduction < 100):
            # If total_reduction is > 100 then this is a very under-utilized
            # array and therefore the oversubscription rate is effectively
            # meaningless.
            # In this case we look to the config option as a starting
            # point. Once some volumes are actually created and some data is
            # stored on the array a much more accurate number will be
            # presented based on current usage.
            thin_provisioning = total_reduction
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
        current_array.patch_volumes(names=[vol_name],
                                    volume=flasharray.VolumePatch(
                                    provisioned=new_size))

    def _add_volume_to_consistency_group(self, group, vol_name):
        pgroup_name = self._get_pgroup_name(group)
        current_array = self._get_current_array()
        current_array.post_protection_groups_volumes(
            group_names=[pgroup_name],
            member_names=[vol_name])

    @pure_driver_debug_trace
    def create_consistencygroup(self, context, group, grp_type=None):
        """Creates a consistencygroup."""

        current_array = self._get_current_array()
        group_name = self._get_pgroup_name(group)
        LOG.debug('Creating Consistency Group %(group_name)s',
                  {'group_name': group_name})
        current_array.post_protection_groups(
            names=[group_name])
        if grp_type:
            current_array.patch_protection_groups(
                names=[group_name],
                protection_group=flasharray.ProtectionGroup(
                    replication_schedule=flasharray.ReplicationSchedule(
                        frequency=self._replication_interval)))
            for target_array in self._replication_target_arrays:
                # Configure PG to replicate to target_array.
                current_array.post_protection_groups_targets(
                    group_names=[group_name],
                    member_names=[target_array.array_name])
                # Wait until "Target Group" setting propagates to target_array.
                pgroup_name_on_target = self._get_pgroup_name_on_target(
                    current_array.array_name, group_name)

                if grp_type == REPLICATION_TYPE_TRISYNC:
                    pgroup_name_on_target = group_name.replace("::", ":")

                target_array.patch_protection_groups_targets(
                    group_names=[pgroup_name_on_target],
                    target=flasharray.TargetProtectionGroupPostPatch(
                        allowed=True))

                # Wait until source array acknowledges previous operation.
                self._wait_until_source_array_allowed(current_array,
                                                      group_name)
                # Start replication on the PG.
                current_array.patch_protection_groups(
                    names=[group_name],
                    protection_group=flasharray.ProtectionGroup(
                        replication_schedule=flasharray.ReplicationSchedule(
                            enabled=True)))

        model_update = {'status': fields.ConsistencyGroupStatus.AVAILABLE}
        return model_update

    def _create_cg_from_cgsnap(self, volumes, snapshots):
        """Creates a new consistency group from a cgsnapshot.

        The new volumes will be consistent with the snapshot.
        """
        vol_models = []
        for volume, snapshot in zip(volumes, snapshots):
            vol_models.append(self.create_volume_from_snapshot(
                volume,
                snapshot,
                cgsnapshot=True))
        return vol_models

    def _create_cg_from_cg(self, group, source_group, volumes, source_vols):
        """Creates a new consistency group from an existing cg.

        The new volumes will be in a consistent state, but this requires
        taking a new temporary group snapshot and cloning from that.
        """
        vol_models = []
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
        suffix = flasharray.ProtectionGroupSnapshotPost(suffix=tmp_suffix)
        current_array.post_protection_group_snapshots(
            source_names=[pgroup_name],
            protection_group_snapshot=suffix)
        volumes, _ = self.update_provider_info(volumes, None)
        try:
            for source_vol, cloned_vol in zip(source_vols, volumes):
                vol_models.append(cloned_vol)
                source_snap_name = self._get_pgroup_vol_snap_name(
                    pgroup_name,
                    tmp_suffix,
                    self._get_vol_name(source_vol)
                )
                cloned_vol_name = self._get_vol_name(cloned_vol)
                current_array.post_volumes(names=[cloned_vol_name],
                                           volume=flasharray.VolumePost(
                                           source=flasharray.Reference(
                                               name=source_snap_name)))
                self._add_volume_to_consistency_group(
                    group,
                    cloned_vol_name
                )
                repl_type = self._get_replication_type_from_vol_type(
                    source_vol.volume_type)
                if (self.configuration.pure_trisync_enabled and
                        repl_type == REPLICATION_TYPE_TRISYNC):
                    self._enable_trisync_replication(current_array, cloned_vol)
                    LOG.info('Trisync replication set for new cloned '
                             'volume %s', cloned_vol_name)

        finally:
            self._delete_pgsnapshot(tmp_pgsnap_name)
        return vol_models

    @pure_driver_debug_trace
    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None,
                                         group_type=None):
        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        model_update = self.create_consistencygroup(context, group, group_type)
        if cgsnapshot and snapshots:
            vol_models = self._create_cg_from_cgsnap(volumes,
                                                     snapshots)
        elif source_cg:
            vol_models = self._create_cg_from_cg(group, source_cg,
                                                 volumes, source_vols)

        return model_update, vol_models

    @pure_driver_debug_trace
    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group."""

        # let generic volume group support handle non-cgsnapshots
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        pgroup_name = self._get_pgroup_name(group)
        current_array = self._get_current_array()
        pgres = current_array.patch_protection_groups(
            names=[pgroup_name],
            protection_group=flasharray.ProtectionGroup(
                destroyed=True))
        if pgres.status_code == 200:
            if self.configuration.pure_eradicate_on_delete:
                current_array.delete_protection_groups(
                    names=[pgroup_name])
        else:
            with excutils.save_and_reraise_exception() as ctxt:
                if (ERR_MSG_PENDING_ERADICATION in pgres.errors[0].message or
                        ERR_MSG_NOT_EXIST in pgres.errors[0].message):
                    # Treat these as a "success" case since we are trying
                    # to delete them anyway.
                    ctxt.reraise = False
                    LOG.warning("Unable to delete Protection Group: %s",
                                pgres.errors[0].context)

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
        current_array.post_protection_groups_volumes(
            group_names=[pgroup_name],
            member_names=addvollist)
        current_array.delete_protection_groups_volumes(
            group_names=[pgroup_name],
            member_names=remvollist)

        return None, None, None

    @pure_driver_debug_trace
    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot."""

        pgroup_name = self._get_pgroup_name(cgsnapshot.group)
        pgsnap_suffix = self._get_pgroup_snap_suffix(cgsnapshot)
        current_array = self._get_current_array()
        suffix = flasharray.ProtectionGroupSnapshotPost(suffix=pgsnap_suffix)
        current_array.post_protection_group_snapshots(
            source_names=[pgroup_name],
            protection_group_snapshot=suffix)

        return None, None

    def _delete_pgsnapshot(self, pgsnap_name):
        current_array = self._get_current_array()
        pg_snapshot = flasharray.ProtectionGroupSnapshotPatch(destroyed=True)
        res = current_array.patch_protection_group_snapshots(
            protection_group_snapshot=pg_snapshot,
            names=[pgsnap_name])
        if self.configuration.pure_eradicate_on_delete:
            current_array.delete_protection_group_snapshots(
                names=[pgsnap_name])
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if (ERR_MSG_PENDING_ERADICATION in res.errors[0].message or
                        ERR_MSG_NOT_EXIST in res.errors[0].message):
                    # Treat these as a "success" case since we are trying
                    # to delete them anyway.
                    ctxt.reraise = False
                    LOG.warning("Unable to delete Protection Group "
                                "Snapshot: %s", res.errors[0].message)

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
        if ("source-name" not in existing_ref
                or not existing_ref["source-name"]):
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("manage_existing requires a 'source-name'"
                         " key to identify an existing volume."))

        if is_snap:
            # Purity snapshot names are prefixed with the source volume name.
            ref_vol_name, ref_snap_suffix = existing_ref['source-name'].split(
                '.')
        else:
            ref_vol_name = existing_ref['source-name']

        current_array = self._get_current_array()
        if not is_snap and self._pod_check(current_array, ref_vol_name):
            # Don't allow for managing volumes in a replicated pod
            raise exception.ManageExistingInvalidReference(
                _("Unable to manage volume in a Replicated Pod"))

        volres = current_array.get_volumes(names=[ref_vol_name])
        if volres.status_code == 200:
            volume_info = list(volres.items)[0]
            if volume_info:
                if is_snap:
                    snapres = current_array.get_volume_snapshots(
                        names=[existing_ref['source-name']])
                    if snapres.status_code == 200:
                        snap = list(snapres.items)[0]
                        return snap
                    else:
                        with excutils.save_and_reraise_exception() as ctxt:
                            if ERR_MSG_NOT_EXIST in volres.errors[0].message:
                                ctxt.reraise = False

                else:
                    return volume_info
        else:
            with excutils.save_and_reraise_exception() as ctxt:
                if ERR_MSG_NOT_EXIST in volres.errors[0].message:
                    ctxt.reraise = False

        # If volume information was unable to be retrieved we need
        # to throw an Invalid Reference exception.
        raise exception.ManageExistingInvalidReference(
            existing_ref=existing_ref,
            reason=(_("Unable to find Purity ref with source-name=%s")
                    % ref_vol_name))

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
        cgr_type = None
        repl_type = None
        if volume_utils.is_group_a_cg_snapshot_type(group):
            if volume_utils.is_group_a_type(
                    group, "consistent_group_replication_enabled"):
                if not self._is_replication_enabled:
                    msg = _("Replication not properly configured on backend.")
                    LOG.error(msg)
                    raise PureDriverException(msg)
                for vol_type_id in group.volume_type_ids:
                    vol_type = volume_type.VolumeType.get_by_name_or_id(
                        ctxt,
                        vol_type_id)
                    repl_type = self._get_replication_type_from_vol_type(
                        vol_type)
                    if repl_type not in [REPLICATION_TYPE_ASYNC,
                                         REPLICATION_TYPE_TRISYNC]:
                        # Unsupported configuration
                        LOG.error("Unable to create group: create consistent "
                                  "replication group with non-replicated or "
                                  "sync replicated volume type is not "
                                  "supported.")
                        model_update = {'status': fields.GroupStatus.ERROR}
                        return model_update
                    if not cgr_type:
                        cgr_type = repl_type
                    elif cgr_type != repl_type:
                        LOG.error("Unable to create group: create consistent "
                                  "replication group with different "
                                  "replication types is not supported.")
                        model_update = {'status': fields.GroupStatus.ERROR}
                        return model_update
            return self.create_consistencygroup(ctxt, group, cgr_type)

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
        cgr_type = None
        if volume_utils.is_group_a_cg_snapshot_type(group):
            if volume_utils.is_group_a_type(
                    group, "consistent_group_replication_enabled"):
                cgr_type = True
            return self.create_consistencygroup_from_src(ctxt,
                                                         group,
                                                         volumes,
                                                         group_snapshot,
                                                         snapshots,
                                                         source_group,
                                                         source_vols,
                                                         cgr_type)

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

        ref_vol_name = existing_ref['source-name']
        current_array = self._get_current_array()
        volume_data = list(current_array.get_volumes(
            names=[ref_vol_name]).items)[0]
        connected_hosts = volume_data.connection_count
        if connected_hosts > 0:
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
        # If existing volume has QoS settings then clear these out
        vol_iops = getattr(volume_data.qos, "iops_limit", None)
        vol_bw = getattr(volume_data.qos, "bandwidth_limit", None)
        if vol_bw or vol_iops:
            LOG.info("Removing pre-existing QoS settings on managed volume.")
            current_array.patch_volumes(
                names=[new_vol_name],
                volume=flasharray.VolumePatch(
                    qos=flasharray.Qos(iops_limit=MAX_IOPS,
                                       bandwidth_limit=MAX_BWS)))
        # If we are managing to a volume type that is a volume group
        # make sure that the target volume group exists with the
        # correct QoS settings.
        if self._get_volume_type_extra_spec(volume.volume_type['id'],
                                            'vg_name'):
            target_vg = self._get_volume_type_extra_spec(
                volume.volume_type['id'],
                'vg_name')
            target_vg = INVALID_CHARACTERS.sub("-", target_vg)
            vg_iops = self._get_volume_type_extra_spec(
                volume.volume_type['id'],
                'vg_maxIOPS',
                default_value=MAX_IOPS)
            vg_bws = self._get_volume_type_extra_spec(
                volume.volume_type['id'],
                'vg_maxBWS',
                default_value=MAX_BWS)
            if not (MIN_IOPS <= int(vg_iops) <= MAX_IOPS):
                msg = (_('vg_maxIOPS QoS error. Must be more than '
                         '%(min_iops)s and less than %(max_iops)s') %
                       {'min_iops': MIN_IOPS, 'max_iops': MAX_IOPS})
                raise exception.InvalidQoSSpecs(message=msg)
            if not (MIN_BWS <= int(vg_bws) <= MAX_BWS):
                msg = (_('vg_maxBWS QoS error. Must be between '
                         '%(min_bws)s and less than %(max_bws)s') %
                       {'min_bws': MIN_BWS, 'max_bws': MAX_BWS})
                raise exception.InvalidQoSSpecs(message=msg)
            self._create_volume_group_if_not_exist(current_array,
                                                   target_vg,
                                                   vg_iops,
                                                   vg_bws)
            res = current_array.patch_volumes(
                names=[new_vol_name],
                volume=flasharray.VolumePatch(
                    volume_group=flasharray.Reference(
                        name=target_vg)))
            if res.status_code != 200:
                LOG.warning("Failed to move volume %(vol)s, to volume "
                            "group %(vg)s. Error: %(mess)s", {
                                "vol": new_vol_name,
                                "vg": target_vg,
                                "mess": res.errors[0].message})
            new_vol_name = target_vg + "/" + new_vol_name
        if "/" in ref_vol_name:
            source_vg = ref_vol_name.split('/')[0]
            self._delete_vgroup_if_empty(current_array, source_vg)
        # Check if the volume_type has QoS settings and if so
        # apply them to the newly managed volume
        qos = None
        qos = self._get_qos_settings(volume.volume_type)
        if qos:
            self.set_qos(current_array, new_vol_name, qos)
        volume.provider_id = new_vol_name
        async_enabled = self._enable_async_replication_if_needed(current_array,
                                                                 volume)
        repl_status = fields.ReplicationStatus.DISABLED
        if async_enabled:
            repl_status = fields.ReplicationStatus.ENABLED
        return {
            'provider_id': new_vol_name,
            'replication_status': repl_status,
            'metadata': {'array_volume_name': new_vol_name,
                         'array_name': current_array.array_name},
        }

    @pure_driver_debug_trace
    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        We expect a volume name in the existing_ref that matches one in Purity.
        """
        volume_info = self._validate_manage_existing_ref(existing_ref)
        size = self._round_bytes_to_gib(volume_info.provisioned)

        return size

    def _pod_check(self, array, volume):
        """Check if volume is in a replicated pod."""
        if "::" in volume:
            pod = volume.split("::")[0]
            pod_info = list(array.get_pods(names=[pod]).items)[0]
            if (pod_info.link_source_count == 0
                    and pod_info.link_target_count == 0
                    and pod_info.array_count == 1):
                return False
            else:
                return True
        else:
            return False

    def _rename_volume_object(self,
                              old_name,
                              new_name,
                              raise_not_exist=False,
                              snapshot=False):
        """Rename a volume object (could be snapshot) in Purity.

        This will not raise an exception if the object does not exist.

        We need to ensure that if we are renaming to a different
        container in the backend, eg a pod, volume group, or just
        the main array container, we have to rename first and then
        move the object.
        """
        current_array = self._get_current_array()
        if snapshot:
            res = current_array.patch_volume_snapshots(
                names=[old_name],
                volume_snapshot=flasharray.VolumePatch(name=new_name))
        else:
            if "/" in old_name and "::" not in old_name:
                interim_name = old_name.split("/")[1]
                res = current_array.patch_volumes(
                    names=[old_name],
                    volume=flasharray.VolumePatch(
                        volume_group=flasharray.Reference(name="")))
                if res.status_code == 400:
                    LOG.warning("Unable to move %(old_name)s, error "
                                "message: %(error)s",
                                {"old_name": old_name,
                                 "error": res.errors[0].message})
                old_name = interim_name
            if "/" not in old_name and "::" in old_name:
                interim_name = old_name.split("::")[1]
                res = current_array.patch_volumes(
                    names=[old_name],
                    volume=flasharray.VolumePatch(
                        pod=flasharray.Reference(name="")))
                if res.status_code == 400:
                    LOG.warning("Unable to move %(old_name)s, error "
                                "message: %(error)s",
                                {"old_name": old_name,
                                 "error": res.errors[0].message})
                old_name = interim_name
            if "/" in old_name and "::" in old_name:
                # This is a VVOL which can't be moved, so have
                # to take a copy
                interim_name = old_name.split("/")[1]
                res = current_array.post_volumes(
                    names=[interim_name],
                    volume=flasharray.VolumePost(
                        source=flasharray.Reference(name=old_name)))
                if res.status_code == 400:
                    LOG.warning("Unable to copy %(old_name)s, error "
                                "message: %(error)s",
                                {"old_name": old_name,
                                 "error": res.errors[0].message})
                old_name = interim_name

            res = current_array.patch_volumes(
                names=[old_name],
                volume=flasharray.VolumePatch(name=new_name))
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if ERR_MSG_NOT_EXIST in res.errors[0].message:
                    ctxt.reraise = raise_not_exist
                    LOG.warning("Unable to rename %(old_name)s, error "
                                "message: %(error)s",
                                {"old_name": old_name,
                                 "error": res.errors[0].message})
        return new_name

    @pure_driver_debug_trace
    def unmanage(self, volume):
        """Removes the specified volume from Cinder management.

        Does not delete the underlying backend storage object.

        The volume will be renamed with "-unmanaged" as a suffix
        """

        vol_name = self._get_vol_name(volume)
        if len(vol_name + UNMANAGED_SUFFIX) > MAX_VOL_LENGTH:
            unmanaged_vol_name = vol_name[:-len(UNMANAGED_SUFFIX)] + \
                UNMANAGED_SUFFIX
        else:
            unmanaged_vol_name = vol_name + UNMANAGED_SUFFIX
        LOG.info("Renaming existing volume %(ref_name)s to %(new_name)s",
                 {"ref_name": vol_name, "new_name": unmanaged_vol_name})
        self._rename_volume_object(vol_name, unmanaged_vol_name)

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Brings an existing backend storage object under Cinder management.

        We expect a snapshot name in the existing_ref that matches one in
        Purity.
        """
        self._validate_manage_existing_ref(existing_ref, is_snap=True)
        ref_snap_name = existing_ref['source-name']
        new_snap_name = self._get_snap_name(snapshot)
        LOG.info("Renaming existing snapshot %(ref_name)s to "
                 "%(new_name)s", {"ref_name": ref_snap_name,
                                  "new_name": new_snap_name})
        self._rename_volume_object(ref_snap_name,
                                   new_snap_name,
                                   raise_not_exist=True,
                                   snapshot=True)
        return {
            'metadata': {'array_snapshot_name': new_snap_name,
                         'array_name': self._array.array_name},
        }

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing.

        We expect a snapshot name in the existing_ref that matches one in
        Purity.
        """
        snap_info = self._validate_manage_existing_ref(existing_ref,
                                                       is_snap=True)
        size = self._round_bytes_to_gib(snap_info.provisioned)
        return size

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management.

        Does not delete the underlying backend storage object.

        We expect a snapshot name in the existing_ref that matches one in
        Purity.
        """
        snap_name = self._get_snap_name(snapshot)
        if len(snap_name + UNMANAGED_SUFFIX) > MAX_SNAP_LENGTH:
            unmanaged_snap_name = snap_name[:-len(UNMANAGED_SUFFIX)] + \
                UNMANAGED_SUFFIX
        else:
            unmanaged_snap_name = snap_name + UNMANAGED_SUFFIX
        LOG.info("Renaming existing snapshot %(ref_name)s to "
                 "%(new_name)s", {"ref_name": snap_name,
                                  "new_name": unmanaged_snap_name})
        self._rename_volume_object(snap_name,
                                   unmanaged_snap_name,
                                   snapshot=True)

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
        pure_vols = list(array.get_volumes().items)
        connections = list(array.get_connections().items)

        # Put together a map of volumes that are connected to hosts
        connected_vols = {}
        for connect in range(0, len(connections)):
            connected_vols[connections[connect].volume.name] = \
                getattr(connections[connect].host, "name", None)

        # Put together a map of existing cinder volumes on the array
        # so we can lookup cinder id's by purity volume names
        existing_vols = {}
        for cinder_vol in cinder_volumes:
            existing_vols[self._get_vol_name(cinder_vol)] = cinder_vol.name_id

        manageable_vols = []
        for pure_vol in range(0, len(pure_vols)):
            vol_name = pure_vols[pure_vol].name
            cinder_id = existing_vols.get(vol_name)
            not_safe_msgs = []
            host = connected_vols.get(vol_name)
            in_pod = self._pod_check(array, vol_name)
            is_deleted = pure_vols[pure_vol].destroyed

            if host:
                not_safe_msgs.append(_('Volume connected to host %s') % host)

            if cinder_id:
                not_safe_msgs.append(_('Volume already managed'))

            if in_pod:
                not_safe_msgs.append(_('Volume is in a Replicated Pod'))

            if is_deleted:
                not_safe_msgs.append(_('Volume is deleted'))

            is_safe = (len(not_safe_msgs) == 0)
            reason_not_safe = ''
            if not is_safe:
                for i, msg in enumerate(not_safe_msgs):
                    if i > 0:
                        reason_not_safe += ' && '
                    reason_not_safe += "%s" % msg

            manageable_vols.append({
                'reference': {'name': vol_name},
                'size': self._round_bytes_to_gib(
                    pure_vols[pure_vol].provisioned),
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
        pure_snapshots = list(array.get_volume_snapshots().items)
        # Put together a map of existing cinder snapshots on the array
        # so we can lookup cinder id's by purity snapshot names
        existing_snapshots = {}
        for cinder_snap in cinder_snapshots:
            name = self._get_snap_name(cinder_snap)
            existing_snapshots[name] = cinder_snap.id

        manageable_snaps = []
        for pure_snap in range(0, len(pure_snapshots)):
            snap_name = pure_snapshots[pure_snap].name
            cinder_id = existing_snapshots.get(snap_name)

            is_safe = True
            reason_not_safe = None

            if cinder_id:
                is_safe = False
                reason_not_safe = _("Snapshot already managed.")

            if pure_snapshots[pure_snap].destroyed:
                is_safe = False
                reason_not_safe = _("Snapshot is deleted.")

            manageable_snaps.append({
                'reference': {'name': snap_name},
                'size': self._round_bytes_to_gib(
                    pure_snapshots[pure_snap].provisioned),
                'safe_to_manage': is_safe,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': None,
                'source_reference': {
                    'name': getattr(pure_snapshots[pure_snap].source,
                                    "name", None)},
            })

        return volume_utils.paginate_entries_list(
            manageable_snaps, marker, limit, offset, sort_keys, sort_dirs)

    @staticmethod
    def _round_bytes_to_gib(size):
        return int(math.ceil(float(size) / units.Gi))

    def _get_flasharray(self, san_ip, api_token, rest_version=None,
                        verify_ssl=None, ssl_cert_path=None):

        try:
            array = flasharray.Client(target=san_ip,
                                      api_token=api_token,
                                      verify_ssl=verify_ssl,
                                      ssl_cert=ssl_cert_path,
                                      user_agent=self._user_agent,
                                      )
        except Exception:
            return None
        array_info = list(array.get_arrays().items)[0]
        array.array_name = array_info.name
        array.array_id = array_info.id
        array._rest_version = array.get_rest_version()

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
            raise PureDriverException(
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
                elif replication_type_spec == "<in> trisync":
                    return REPLICATION_TYPE_TRISYNC
            else:
                # if no type was specified but replication is enabled assume
                # that async replication is enabled
                return REPLICATION_TYPE_ASYNC
        return None

    def _get_volume_type_extra_spec(self, type_id, spec_key,
                                    possible_values=None,
                                    default_value=None):
        """Get extra spec value.

        If the spec value is not present in the input possible_values, then
        default_value will be returned.
        If the type_id is None, then default_value is returned.

        The caller must not consider scope and the implementation adds/removes
        scope. the scope used here is 'flasharray' e.g. key
        'flasharray:vg_name' and so the caller must pass vg_name as an
        input ignoring the scope.

        :param type_id: volume type id
        :param spec_key: extra spec key
        :param possible_values: permitted values for the extra spec if known
        :param default_value: default value for the extra spec incase of an
                              invalid value or if the entry does not exist
        :return: extra spec value
        """
        if not type_id:
            return default_value

        spec_key = ('flasharray:%s') % spec_key
        spec_value = volume_types.get_volume_type_extra_specs(type_id).get(
            spec_key, False)
        if not spec_value:
            LOG.debug("Returning default spec value: %s.", default_value)
            return default_value

        if possible_values is None:
            return spec_value

        if spec_value in possible_values:
            LOG.debug("Returning spec value %s", spec_value)
            return spec_value

        LOG.debug("Invalid spec value: %s specified.", spec_value)

    def _get_qos_settings(self, volume_type):
        """Get extra_specs and qos_specs of a volume_type.

        This fetches the keys from the volume type. Anything set
        from qos_specs will override keys set from extra_specs
        """

        # Deal with volume with no type
        qos = {}
        qos_specs_id = volume_type.get('qos_specs_id')
        specs = volume_type.get('extra_specs')
        # We prefer QoS specs associations to override
        # any existing extra-specs settings
        if qos_specs_id is not None:
            ctxt = context.get_admin_context()
            kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
        else:
            kvs = specs

        for key, value in kvs.items():
            if key in self.PURE_QOS_KEYS:
                qos[key] = value
        if qos == {}:
            return None
        else:
            # Check set vslues are within limits
            iops_qos = int(qos.get('maxIOPS', 0))
            bw_qos = int(qos.get('maxBWS', 0)) * MIN_BWS
            if iops_qos != 0 and not (MIN_IOPS <= iops_qos <= MAX_IOPS):
                msg = (_('maxIOPS QoS error. Must be more than '
                         '%(min_iops)s and less than %(max_iops)s') %
                       {'min_iops': MIN_IOPS, 'max_iops': MAX_IOPS})
                raise exception.InvalidQoSSpecs(message=msg)
            if bw_qos != 0 and not (MIN_BWS <= bw_qos <= MAX_BWS):
                msg = (_('maxBWS QoS error. Must be between '
                         '%(min_bws)s and %(max_bws)s') %
                       {'min_bws': MIN_BWS, 'max_bws': MAX_BWS})
                raise exception.InvalidQoSSpecs(message=msg)

            qos['maxIOPS'] = iops_qos
            qos['maxBWS'] = bw_qos
        return qos

    def _generate_purity_vol_name(self, volume):
        """Return the name of the volume Purity will use.

        This expects to be given a Volume OVO and not a volume
        dictionary.
        """
        base_name = volume.name

        # Some OpenStack deployments, eg PowerVC, create a volume.name that
        # when appended with our '-cinder' string will exceed the maximum
        # volume name length for Pure, so here we left truncate the true volume
        # name before the opennstack volume_name_template affected it and
        # then put back the template format
        if len(base_name) > 56:
            actual_name = base_name[(len(CONF.volume_name_template) - 2):]
            base_name = CONF.volume_name_template % \
                actual_name[-(56 - len(CONF.volume_name_template)):]

        repl_type = self._get_replication_type_from_vol_type(
            volume.volume_type)
        vgroup_type = self._get_volume_type_extra_spec(volume.volume_type_id,
                                                       'vg_name')
        if repl_type in [REPLICATION_TYPE_SYNC, REPLICATION_TYPE_TRISYNC]:
            if vgroup_type:
                raise exception.InvalidVolumeType(
                    reason=_("Synchronously replicated volume group volumes "
                             "are not supported"))
            else:
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
        if ((REPLICATION_TYPE_SYNC in
                self._group_potential_repl_types(pgroup)) or
                (REPLICATION_TYPE_TRISYNC in
                    self._group_potential_repl_types(pgroup))):
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
        if "::" in volume_name:
            volume_name = volume_name.split("::")[1]
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
        volume_name = self._get_vol_name(snapshot.volume)
        if "::" in volume_name:
            volume_name = volume_name.split("::")[1]
        pg_vol_snap_name = "%(group_snap)s.%(volume_name)s" % {
            'group_snap': self._get_pgroup_snap_name(group_snap),
            'volume_name': volume_name
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
        LOG.debug("Connecting volume %(vol)s to host %(host)s.",
                  {"vol": vol_name,
                   "host": host_name})
        res = array.post_connections(
            host_names=[host_name],
            volume_names=[vol_name])
        connection_obj = getattr(res, "items", None)
        if connection_obj:
            connection = list(connection_obj)
        if res.status_code == 400:
            if ERR_MSG_HOST_NOT_EXIST in res.errors[0].message:
                LOG.debug(
                    'Unable to attach volume to host: %s',
                    res.errors[0].context
                )
                raise PureRetryableException()
            with excutils.save_and_reraise_exception() as ctxt:
                ctxt.reraise = False
                if (res.status_code == 400 and
                        ERR_MSG_ALREADY_EXISTS in res.errors[0].message):
                    # Happens if the volume is already connected to the host.
                    # Treat this as a success.
                    ctxt.reraise = False
                    LOG.debug("Volume connection already exists for Purity "
                              "host with message: %s", res.errors[0].message)

                    vol_data = list(array.get_volumes(names=[vol_name]).items)
                    vol_id = vol_data[0].id
                    connected_host = list(
                        array.get_connections(
                            volume_names=[vol_name], host_names=[host_name]
                        ).items
                    )[0]
                    connection = [
                        {
                            "host": {"name": host_name},
                            "host_group": {},
                            'protocol_endpoint': {},
                            "volume": {"name": vol_name, "id": vol_id},
                            "lun": getattr(connected_host, "lun", None),
                            "nsid": getattr(connected_host, "nsid", None),
                        }
                    ]
        if not connection:
            raise PureDriverException(
                reason=_("Unable to connect or find connection to host"))

        return connection

    @pure_driver_debug_trace
    def retype(self, context, volume, new_type, diff, host):
        """Retype from one volume type to another on the same backend.

        For a Pure Array there is currently no differentiation between types
        of volumes other than some being part of a protection group to be
        replicated for async, or part of a pod for sync replication.
        """

        qos = None
        # TODO: Can remove this once new_type is a VolumeType OVO
        new_type = volume_type.VolumeType.get_by_name_or_id(context,
                                                            new_type['id'])
        previous_vol_replicated = volume.is_replicated()
        new_vol_replicated = (new_type and new_type.is_replicated())

        prev_repl_type = None
        new_repl_type = None
        source_vg = False
        target_vg = False

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
            elif prev_repl_type in [REPLICATION_TYPE_SYNC,
                                    REPLICATION_TYPE_TRISYNC]:
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
            elif new_repl_type in [REPLICATION_TYPE_SYNC,
                                   REPLICATION_TYPE_TRISYNC]:
                # We can't add a volume to a stretched pod, they must be
                # created in one, indicate to the volume manager that it
                # should do a migration.
                return False, None
        elif previous_vol_replicated and new_vol_replicated:
            if prev_repl_type == REPLICATION_TYPE_ASYNC:
                if new_repl_type in [REPLICATION_TYPE_SYNC,
                                     REPLICATION_TYPE_TRISYNC]:
                    # We can't add a volume to a stretched pod, they must be
                    # created in one, indicate to the volume manager that it
                    # should do a migration.
                    return False, None
            if prev_repl_type == REPLICATION_TYPE_SYNC:
                if new_repl_type == REPLICATION_TYPE_ASYNC:
                    # We can't move a volume in or out of a pod, indicate to
                    # the manager that it should do a migration for this retype
                    return False, None
                elif new_repl_type == REPLICATION_TYPE_TRISYNC:
                    # Add to trisync protection group
                    self._enable_trisync_replication(self._get_current_array(),
                                                     volume)
            if prev_repl_type == REPLICATION_TYPE_TRISYNC:
                if new_repl_type == REPLICATION_TYPE_ASYNC:
                    # We can't move a volume in or out of a pod, indicate to
                    # the manager that it should do a migration for this retype
                    return False, None
                elif new_repl_type == REPLICATION_TYPE_SYNC:
                    # Remove from trisync protection group
                    self._disable_trisync_replication(
                        self._get_current_array(), volume
                    )

        current_array = self._get_current_array()
        # Now check if we are retyping to/from a type with volume groups
        if "/" in self._get_vol_name(volume):
            source_vg = self._get_vol_name(volume).split('/')[0]
        if self._get_volume_type_extra_spec(new_type['id'], 'vg_name'):
            target_vg = self._get_volume_type_extra_spec(new_type['id'],
                                                         'vg_name')
        if source_vg or target_vg:
            if target_vg:
                target_vg = INVALID_CHARACTERS.sub("-", target_vg)
                vg_iops = self._get_volume_type_extra_spec(
                    new_type['id'],
                    'vg_maxIOPS',
                    default_value=MAX_IOPS)
                vg_bws = self._get_volume_type_extra_spec(
                    new_type['id'],
                    'vg_maxBWS',
                    default_value=MAX_BWS)
                if not (MIN_IOPS <= int(vg_iops) <= MAX_IOPS):
                    msg = (_('vg_maxIOPS QoS error. Must be more than '
                             '%(min_iops)s and less than %(max_iops)s') %
                           {'min_iops': MIN_IOPS, 'max_iops': MAX_IOPS})
                    raise exception.InvalidQoSSpecs(message=msg)
                if not (MIN_BWS <= int(vg_bws) <= MAX_BWS):
                    msg = (_('vg_maxBWS QoS error. Must be more than '
                             '%(min_bws)s and less than %(max_bws)s') %
                           {'min_bws': MIN_BWS, 'max_bws': MAX_BWS})
                    raise exception.InvalidQoSSpecs(message=msg)
                self._create_volume_group_if_not_exist(current_array,
                                                       target_vg,
                                                       vg_iops,
                                                       vg_bws)
                current_array.patch_volumes(
                    names=[self._get_vol_name(volume)],
                    volume=flasharray.VolumePatch(
                        volume_group=flasharray.Reference(
                            name=target_vg)))
                vol_name = self._get_vol_name(volume)
                if source_vg:
                    target_vol_name = (target_vg +
                                       "/" +
                                       vol_name.split('/')[1])
                else:
                    target_vol_name = (target_vg +
                                       "/" +
                                       vol_name)
                model_update = {
                    'id': volume.id,
                    'provider_id': target_vol_name,
                    'metadata': {**volume.metadata,
                                 'array_volume_name': target_vol_name,
                                 'array_name': self._array.array_name}
                }
                # If we have empied a VG by retyping out of it then delete VG
                if source_vg:
                    self._delete_vgroup_if_empty(current_array, source_vg)
            else:
                current_array.patch_volumes(
                    names=[self._get_vol_name(volume)],
                    volume=flasharray.VolumePatch(
                        volume_group=flasharray.Reference(
                            name="")))
                target_vol_name = self._get_vol_name(volume).split('/')[1]
                model_update = {
                    'id': volume.id,
                    'provider_id': target_vol_name,
                    'metadata': {**volume.metadata,
                                 'array_volume_name': target_vol_name,
                                 'array_name': self._array.array_name}
                }
                if source_vg:
                    self._delete_vgroup_if_empty(current_array, source_vg)
            return True, model_update
        # If we are moving to a volume type with QoS settings then
        # make sure the volume gets the correct new QoS settings.
        # This could mean removing existing QoS settings.
        qos = self._get_qos_settings(new_type)
        vol_name = self._generate_purity_vol_name(volume)
        if qos is not None:
            self.set_qos(current_array, vol_name, qos)
        else:
            current_array.patch_volumes(names=[vol_name],
                                        volume=flasharray.VolumePatch(
                                            qos=flasharray.Qos(
                                                iops_limit=MAX_IOPS,
                                                bandwidth_limit=MAX_BWS)))

        return True, model_update

    @pure_driver_debug_trace
    def _disable_async_replication(self, volume):
        """Disable replication on the given volume."""

        current_array = self._get_current_array()
        LOG.debug("Disabling replication for volume %(id)s residing on "
                  "array %(backend_id)s.",
                  {"id": volume["id"],
                   "backend_id": current_array.backend_id})
        res = current_array.delete_protection_groups_volumes(
            group_names=[self._replication_pg_name],
            member_names=[self._get_vol_name(volume)])
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if ERR_MSG_COULD_NOT_BE_FOUND in res.errors[0].message:
                    ctxt.reraise = False
                    LOG.warning("Disable replication on volume failed: "
                                "already disabled: %s",
                                res.errors[0].message)
                else:
                    LOG.error("Disable replication on volume failed with "
                              "message: %s",
                              res.errors[0].message)

    @pure_driver_debug_trace
    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failover to replication target.

        This function combines calls to failover() and failover_completed() to
        perform failover when Active/Active is not enabled.
        """
        active_backend_id, volume_update_list, group_update_list = (
            self.failover(context, volumes, secondary_id, groups))
        self.failover_completed(context, active_backend_id)
        return active_backend_id, volume_update_list, group_update_list

    @pure_driver_debug_trace
    def failover_completed(self, context, active_backend_id=None):
        """Failover to replication target."""
        LOG.info('Driver failover completion started.')
        current = self._get_current_array()
        # This should not happen unless we receive the same RPC message twice
        if active_backend_id == current.backend_id:
            LOG.info('No need to switch replication backend, already using it')
        # Manager sets the active_backend to '' when secondary_id was default,
        # but the driver failover_host method calls us with "default"
        elif not active_backend_id or active_backend_id == 'default':
            if self._failed_over_primary_array is not None:
                LOG.info('Failing back to %s', self._failed_over_primary_array)
                self._swap_replication_state(current,
                                             self._failed_over_primary_array,
                                             failback=True)
            else:
                LOG.info('Failover not occured - secondary array '
                         'cannot be same as primary')
        else:
            secondary = self._get_secondary(active_backend_id)
            LOG.info('Failing over to %s', secondary.backend_id)
            self._swap_replication_state(current,
                                         secondary)
        LOG.info('Driver failover completion completed.')

    @pure_driver_debug_trace
    def failover(self, context, volumes, secondary_id=None, groups=None):
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

                current_array = self._get_current_array(True)
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
                return secondary_id, model_updates, []
            else:
                msg = _('Unable to failback to "default", this can only be '
                        'done after a failover has completed.')
                raise exception.InvalidReplicationTarget(message=msg)

        current_array = self._get_current_array(True)
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
            secondary_array = self._get_secondary(secondary_id)
            if secondary_array.replication_type in [REPLICATION_TYPE_ASYNC,
                                                    REPLICATION_TYPE_SYNC]:
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
            raise PureDriverException(
                reason=_("Unable to find viable secondary array from "
                         "configured targets: %(targets)s.") %
                {"targets": str(self._replication_target_arrays)}
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

        current_array = self._get_current_array(True)

        return secondary_array.backend_id, model_updates, []

    @pure_driver_debug_trace
    def set_personality(self, array, host_name, personality):
        res = array.patch_hosts(names=[host_name],
                                host=flasharray.HostPatch(
                                    personality=personality))
        if res.status_code == 400:
            if ERR_MSG_HOST_NOT_EXIST in res.errors[0].message:
                # If the host disappeared out from under us that's
                # ok, we will just retry and snag a new host.
                LOG.debug('Unable to set host personality: %s',
                          res.errors[0].message)
                raise PureRetryableException()
        return

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
            self._failed_over_primary_array = None

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
            self._is_replication_enabled = True

        if secondary_array.uniform:
            if secondary_array in self._uniform_active_cluster_target_arrays:
                self._uniform_active_cluster_target_arrays.remove(
                    secondary_array)
            current_array.uniform = True
            self._uniform_active_cluster_target_arrays.append(current_array)

        self._set_current_array(secondary_array)

    def _does_pgroup_exist(self, array, pgroup_name):
        """Return True/False"""
        pgroupres = array.get_protection_groups(
            names=[pgroup_name])
        if pgroupres.status_code == 200:
            return True
        else:
            with excutils.save_and_reraise_exception() as ctxt:
                if ERR_MSG_NOT_EXIST in pgroupres.errors[0].message:
                    ctxt.reraise = False
                    return False
            # Any unexpected exception to be handled by caller.

    @pure_driver_debug_trace
    @utils.retry(PureDriverException,
                 REPL_SETTINGS_PROPAGATE_RETRY_INTERVAL,
                 REPL_SETTINGS_PROPAGATE_MAX_RETRIES)
    def _wait_until_target_group_setting_propagates(
            self, target_array, pgroup_name_on_target):
        # Wait for pgroup to show up on target array.
        if self._does_pgroup_exist(target_array, pgroup_name_on_target):
            return
        else:
            raise PureDriverException(message=_('Protection Group not ready.'))

    @pure_driver_debug_trace
    @utils.retry(PureDriverException,
                 REPL_SETTINGS_PROPAGATE_RETRY_INTERVAL,
                 REPL_SETTINGS_PROPAGATE_MAX_RETRIES)
    def _wait_until_source_array_allowed(self, source_array, pgroup_name):
        result = list(source_array.get_protection_groups_targets(
            group_names=[pgroup_name]).items)[0]
        if result.allowed:
            return
        else:
            raise PureDriverException(message=_('Replication not '
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
            res = primary.post_pods_arrays(
                group_names=[pod_name],
                member_names=[target_array.array_name])
            if res.status_code == 400:
                with excutils.save_and_reraise_exception() as ctxt:
                    if (
                        ERR_MSG_ALREADY_EXISTS in res.errors[0].message
                        or ERR_MSG_ARRAY_LIMIT in res.errors[0].message
                    ):
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
        primary.patch_protection_groups(
            names=[pg_name],
            protection_group=flasharray.ProtectionGroup(
                target_retention=retention_policy))

        # Configure replication propagation frequency on a
        # protection group.
        primary.patch_protection_groups(
            names=[pg_name],
            protection_group=flasharray.ProtectionGroup(
                replication_schedule=flasharray.ReplicationSchedule(
                    frequency=replication_interval)))
        for target_array in secondaries:
            # Configure PG to replicate to target_array.
            res = primary.post_protection_groups_targets(
                group_names=[pg_name],
                member_names=[target_array.array_name])
            if res.status_code == 400:
                with excutils.save_and_reraise_exception() as ctxt:
                    if ERR_MSG_ALREADY_INCLUDES in res.errors[0].message:
                        ctxt.reraise = False
                        LOG.info("Skipping add target %(target_array)s"
                                 " to protection group %(pgname)s"
                                 " since it's already added.",
                                 {"target_array": target_array.array_name,
                                  "pgname": pg_name})

        # Wait until "Target Group" setting propagates to target_array.
        pgroup_name_on_target = self._get_pgroup_name_on_target(
            primary.array_name, pg_name)

        if self._is_trisync_enabled:
            pgroup_name_on_target = pg_name.replace("::", ":")

        for target_array in secondaries:
            self._wait_until_target_group_setting_propagates(
                target_array,
                pgroup_name_on_target)
            # Configure the target_array to allow replication from the
            # PG on source_array.
            res = target_array.patch_protection_groups_targets(
                group_names=[pgroup_name_on_target],
                target=flasharray.TargetProtectionGroupPostPatch(
                    allowed=True))
            if res.status_code == 400:
                with excutils.save_and_reraise_exception() as ctxt:
                    if ERR_MSG_ALREADY_ALLOWED in res.errors[0].message:
                        ctxt.reraise = False
                        LOG.info("Skipping allow pgroup %(pgname)s on "
                                 "target array %(target_array)s since "
                                 "it is already allowed.",
                                 {"pgname": pg_name,
                                  "target_array": target_array.array_name})

        # Wait until source array acknowledges previous operation.
        self._wait_until_source_array_allowed(primary, pg_name)
        # Start replication on the PG.
        primary.patch_protection_groups(
            names=[pg_name],
            protection_group=flasharray.ProtectionGroup(
                replication_schedule=flasharray.ReplicationSchedule(
                    enabled=True)))

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
        replication_retention = flasharray.RetentionPolicy(
            all_for_sec=self._replication_retention_short_term,
            per_day=self._replication_retention_long_term_per_day,
            days=self._replication_retention_long_term
        )
        return replication_retention

    @pure_driver_debug_trace
    def _get_latest_replicated_pg_snap(self,
                                       target_array,
                                       source_array_name,
                                       pgroup_name):
        # Get all protection group snapshots where replication has completed.
        # Sort into reverse order to get the latest.
        snap_name = "%s:%s" % (source_array_name, pgroup_name)
        LOG.debug("Looking for snap %(snap)s on array id %(array_id)s",
                  {"snap": snap_name, "array_id": target_array.array_id})
        try:
            pg_snaps = list(
                target_array.get_protection_group_snapshots_transfer(
                    names=[snap_name],
                    destroyed=False,
                    filter='progress="1.0"',
                    sort=["started-"]).items)
            pg_snap = pg_snaps[0] if pg_snaps else None
        except AttributeError:
            pg_snap = None

        LOG.debug("Selecting snapshot %(pg_snap)s for failover.",
                  {"pg_snap": pg_snap})

        return pg_snap

    @pure_driver_debug_trace
    def _create_pod_if_not_exist(self, source_array, name):
        if not name:
            raise PureDriverException(
                reason=_("Empty string passed for Pod name."))
        res = source_array.post_pods(names=[name], pod=flasharray.PodPost())
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if ERR_MSG_ALREADY_EXISTS in res.errors[0].message:
                    # Happens if the pod already exists
                    ctxt.reraise = False
                    LOG.warning("Skipping creation of pod %s since it "
                                "already exists.", name)
                    return
                if list(source_array.get_pods(
                        names=[name]).items)[0].destroyed:
                    ctxt.reraise = False
                    LOG.warning("Pod %s is deleted but not"
                                " eradicated - will recreate.", name)
                    source_array.delete_pods(names=[name])
                    self._create_pod_if_not_exist(source_array, name)
        else:
            if self._array.safemode:
                # Now we check to ensure that the created pod does not have a
                # safemode protection group attached to it as this is not
                # supported by Cinder
                safemode_pg = list(
                    source_array.get_container_default_protections(
                        names=[name]).items)[0].default_protections
                if safemode_pg:
                    pgname = safemode_pg[0].name
                    res = source_array.patch_container_default_protections(
                        names=[name],
                        container_default_protection=(
                            flasharray.ContainerDefaultProtection(
                                default_protections=[])))
                    if res.status_code != 200:
                        LOG.warning("Failed to remove Default Protection "
                                    "Container: %s", res.errors[0])
                    else:
                        source_array.patch_protection_groups(
                            names=[pgname],
                            protection_group=flasharray.ProtectionGroup(
                                destroyed=True))
                        source_array.delete_protection_groups(
                            names=[pgname])

    @pure_driver_debug_trace
    def _create_volume_group_if_not_exist(self,
                                          source_array,
                                          vgname,
                                          vg_iops,
                                          vg_bws):
        res = source_array.post_volume_groups(
            names=[vgname],
            volume_group=flasharray.VolumeGroupPost(
                qos=flasharray.Qos(
                    bandwidth_limit=vg_bws,
                    iops_limit=vg_iops)))
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if ERR_MSG_ALREADY_EXISTS in res.errors[0].message:
                    # Happens if the vg already exists
                    ctxt.reraise = False
                    LOG.warning("Skipping creation of vg %s since it "
                                "already exists. Resetting QoS", vgname)
                    res = source_array.patch_volume_groups(
                        names=[vgname],
                        volume_group=flasharray.VolumeGroupPatch(
                            qos=flasharray.Qos(
                                bandwidth_limit=vg_bws,
                                iops_limit=vg_iops)))
                    if res.status_code == 400:
                        with excutils.save_and_reraise_exception() as ctxt:
                            if ERR_MSG_NOT_EXIST in res.errors[0].message:
                                ctxt.reraise = False
                                LOG.warning("Unable to change %(vgroup)s QoS, "
                                            "error message: %(error)s",
                                            {"vgroup": vgname,
                                             "error": res.errors[0].message})
                    return
                if list(source_array.get_volume_groups(
                        names=[vgname]).items)[0].destroyed:
                    ctxt.reraise = False
                    LOG.warning("Volume group %s is deleted but not"
                                " eradicated - will recreate.", vgname)
                    source_array.delete_volume_groups(names=[vgname])

                    self._create_volume_group_if_not_exist(source_array,
                                                           vgname,
                                                           vg_iops,
                                                           vg_bws)

    @pure_driver_debug_trace
    def _create_protection_group_if_not_exist(self, source_array, pgname):
        if not pgname:
            raise PureDriverException(
                reason=_("Empty string passed for PG name."))
        res = source_array.post_protection_groups(names=[pgname])
        if res.status_code == 400:
            with excutils.save_and_reraise_exception() as ctxt:
                if ERR_MSG_ALREADY_EXISTS in res.errors[0].message:
                    # Happens if the PG already exists
                    ctxt.reraise = False
                    LOG.warning("Skipping creation of PG %s since it "
                                "already exists.", pgname)
                    # We assume PG has already been setup with correct
                    # replication settings.
                    return
                if list(source_array.get_protection_groups(
                        names=[pgname]).items)[0].destroyed:
                    ctxt.reraise = False
                    LOG.warning("Protection group %s is deleted but not"
                                " eradicated - will recreate.", pgname)
                    source_array.delete_protection_groups(names=[pgname])
                    self._create_protection_group_if_not_exist(source_array,
                                                               pgname)

    def _find_async_failover_target(self):
        if not self._replication_target_arrays:
            raise PureDriverException(
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
            raise PureDriverException(
                reason=_("Unable to find viable pg snapshot to use for "
                         "failover on selected secondary array: %(id)s.") %
                {"id": secondary_array.backend_id if secondary_array else None}
            )

        return secondary_array, pg_snap

    def _get_secondary(self, secondary_id):
        for array in self._replication_target_arrays:
            if array.backend_id == secondary_id:
                return array
        raise exception.InvalidReplicationTarget(
            reason=_("Unable to determine secondary_array from"
                     " supplied secondary: %(secondary)s.") %
            {"secondary": secondary_id}
        )

    def _find_sync_failover_target(self):
        secondary_array = None
        if not self._active_cluster_target_arrays:
            LOG.warning("Unable to find failover target, no "
                        "sync rep secondary targets configured.")
            return secondary_array

        for array in self._active_cluster_target_arrays:
            secondary_array = array
            # Ensure the pod is in a good state on the array
            res = secondary_array.get_pods(
                names=[self._replication_pod_name])
            if res.status_code == 200:
                pod_info = list(res.items)[0]
                for pod_array in range(0, len(pod_info.arrays)):
                    # Compare against Purity ID's
                    if pod_info.arrays[pod_array].id == \
                            secondary_array.array_id:
                        if pod_info.arrays[pod_array].status == "online":
                            # Success! Use this array.
                            break
                        else:
                            secondary_array = None
            else:
                LOG.warning("Failed to get pod status for secondary array "
                            "%(id)s: %(err)s",
                            {
                                "id": secondary_array.backend_id,
                                "err": res.errors[0].message,
                            })
                secondary_array = None
        return secondary_array

    def _async_failover_host(self, volumes, secondary_array, pg_snap):
        # Try to copy the flasharray as close as we can.
        secondary_info = list(secondary_array.get_arrays().items)[0]
        if version.parse(secondary_info.version) < version.parse('6.3.4'):
            secondary_safemode = False
        else:
            secondary_safemode = True

        volume_snaps = list(secondary_array.get_volume_snapshots(
            filter="name='" + pg_snap.name + ".*'"
        ).items)

        # We only care about volumes that are in the list we are given.
        vol_names = set()
        for vol in volumes:
            vol_names.add(self._get_vol_name(vol))

        for snap in range(0, len(volume_snaps)):
            vol_name = volume_snaps[snap].name.split('.')[-1]
            if vol_name in vol_names:
                vol_names.remove(vol_name)
                LOG.debug('Creating volume %(vol)s from replicated snapshot '
                          '%(snap)s', {'vol': vol_name,
                                       'snap': volume_snaps[snap].name})
                if "/" in vol_name:
                    # We have to create the target vgroup with assosiated QoS
                    vg_iops = self._get_volume_type_extra_spec(
                        vol.volume_type_id,
                        'vg_maxIOPS',
                        default_value=MAX_IOPS)
                    vg_bws = self._get_volume_type_extra_spec(
                        vol.volume_type_id,
                        'vg_maxBWS',
                        default_value=MAX_BWS)
                    self._create_volume_group_if_not_exist(
                        secondary_array,
                        vol_name.split("/")[0],
                        int(vg_iops),
                        int(vg_bws))
                if secondary_safemode:
                    secondary_array.post_volumes(
                        with_default_protection=False,
                        volume=flasharray.VolumePost(
                            source=flasharray.Reference(
                                name=volume_snaps[snap].name)
                        ),
                        names=[vol_name],
                        overwrite=True)
                else:
                    secondary_array.post_volumes(
                        volume=flasharray.VolumePost(
                            source=flasharray.Reference(
                                name=volume_snaps[snap].name)
                        ),
                        names=[vol_name],
                        overwrite=True)
            else:
                LOG.debug('Ignoring unmanaged volume %(vol)s from replicated '
                          'snapshot %(snap)s.',
                          {'vol': vol_name,
                           'snap': volume_snaps[snap].name})
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

        array_volumes = list(secondary_array.get_volumes(
            filter="pod.name='" + self._replication_pod_name + "'").items)
        replicated_vol_names = set()
        for vol in array_volumes:
            replicated_vol_names.add(vol.name)

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
        volume_info = list(array.get_volumes(names=[pure_vol_name]).items)[0]
        wwn = '3624a9370' + volume_info.serial
        return wwn.lower()

    def _get_current_array(self, init=False):
        if (not init and
                self._is_active_cluster_enabled and
                not self._failed_over_primary_array):
            res = self._array.get_pods(names=[self._replication_pod_name])
            if res.status_code == 200:
                pod_info = list(res.items)[0]
                for target_array in self._active_cluster_target_arrays:
                    LOG.info("Checking target array %s...",
                             target_array.array_name)
                    status_ok = False
                    for pod_array in range(0, len(pod_info.arrays)):
                        if pod_info.arrays[pod_array].id == \
                                target_array.array_id:
                            if pod_info.arrays[pod_array].status == \
                                    'online':
                                status_ok = True
                            break
                    if not status_ok:
                        LOG.warning("Target array is offline. Volume "
                                    "replication in unknown state. Check "
                                    "replication links and array state.")
            else:
                LOG.warning("self.get_pod failed with"
                            " message: %(msg)s",
                            {"msg": res.errors[0].message})
                raise PureDriverException(
                    reason=_("No functional arrays available"))

        return self._array

    def _set_current_array(self, array):
        self._array = array

    @pure_driver_debug_trace
    def _get_valid_ports(self, array):
        ports = []
        res = array.get_controllers(filter="status='ready'")
        if res.status_code != 200:
            with excutils.save_and_reraise_exception() as ctxt:
                ctxt.reraise = False
                LOG.warning("No live controllers found: %s", res.errors[0])
                return ports
        else:
            live_controllers = list(res.items)
        if len(live_controllers) != 0:
            controllers = [controller.name for controller in live_controllers]
            for controller in controllers:
                ports += list(
                    array.get_ports(filter="name='" + controller + ".*'").items
                )
            lacps = list(
                array.get_network_interfaces(
                    filter="eth.subtype='lacp_bond'"
                ).items
            )
            if lacps:
                for lacp in range(0, len(lacps)):
                    ports += list(
                        array.get_ports(
                            names=[lacps[lacp].name.upper()]
                        ).items
                    )
        return ports


@interface.volumedriver
class PureISCSIDriver(PureBaseVolumeDriver, san.SanISCSIDriver):
    """OpenStack Volume Driver to support Pure Storage FlashArray.

    This version of the driver enables the use of iSCSI for
    the underlying storage connectivity with the FlashArray.
    """

    VERSION = "21.0.iscsi"

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureISCSIDriver, self).__init__(execute=execute, *args, **kwargs)
        self._storage_protocol = constants.ISCSI

    def _get_host(self, array, connector, remote=False):
        """Return dict describing existing Purity host object or None."""
        if remote:
            hosts = list(
                getattr(
                    array.get_hosts(
                        filter="iqns='"
                        + connector["initiator"]
                        + "' and not is_local"
                    ),
                    "items",
                    []
                )
            )
        else:
            hosts = list(
                getattr(
                    array.get_hosts(
                        filter="iqns='"
                        + connector["initiator"]
                        + "' and is_local"
                    ),
                    "items",
                    []
                )
            )
        return hosts

    @pure_driver_debug_trace
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        pure_vol_name = self._get_vol_name(volume)
        target_arrays = [self._get_current_array()]
        if (self._is_vol_in_pod(pure_vol_name) and
                self._is_active_cluster_enabled and
                not self._failed_over_primary_array):
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
            if not connection[0].lun:
                # Swallow any exception, just warn and continue
                LOG.warning("self._connect failed.")
                continue
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
                "addressing_mode": brick_constants.SCSI_ADDRESSING_SAM2,
            },
        }

        if self.configuration.pure_iscsi_cidr_list:
            iscsi_cidrs = self.configuration.pure_iscsi_cidr_list
            if self.configuration.pure_iscsi_cidr != "0.0.0.0/0":
                LOG.warning("pure_iscsi_cidr was ignored as "
                            "pure_iscsi_cidr_list is set")
        else:
            iscsi_cidrs = [self.configuration.pure_iscsi_cidr]

        check_iscsi_cidrs = [
            ipaddress.ip_network(item) for item in iscsi_cidrs
        ]

        target_luns = []
        target_iqns = []
        target_portals = []

        # Aggregate all targets together if they're in the allowed CIDR. We may
        # end up with different LUNs for different target iqn/portal sets (ie.
        # it could be a unique LUN for each FlashArray)
        for target in range(0, len(targets)):
            port_iter = iter(targets[target]["ports"])
            for port in port_iter:
                # Check to ensure that the portal IP is in the iSCSI target
                # CIDR before adding it
                target_portal = port.portal
                portal, p_port = target_portal.rsplit(':', 1)
                portal = portal.strip('[]')
                check_ip = ipaddress.ip_address(portal)
                for check_cidr in check_iscsi_cidrs:
                    if check_ip in check_cidr:
                        target_luns.append(
                            targets[target]["connection"][0].lun)
                        target_iqns.append(port.iqn)
                        target_portals.append(target_portal)

        LOG.info("iSCSI target portals that match CIDR range: '%s'",
                 target_portals)
        LOG.info("iSCSI target IQNs that match CIDR range: '%s'",
                 target_iqns)

        # If we have multiple ports always report them.
        if target_luns and target_iqns and target_portals:
            props["data"]["target_luns"] = target_luns
            props["data"]["target_iqns"] = target_iqns
            props["data"]["target_portals"] = target_portals

        return props

    def _get_target_iscsi_ports(self, array):
        """Return list of iSCSI-enabled port descriptions."""
        ports = self._get_valid_ports(array)
        iscsi_ports = [port for port in ports if getattr(port, "iqn", None)]
        if not iscsi_ports:
            raise PureDriverException(
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

    @utils.retry(PureRetryableException,
                 retries=HOST_CREATE_MAX_RETRIES)
    def _connect(self, array, vol_name, connector,
                 chap_username, chap_password):
        """Connect the host and volume; return dict describing connection."""
        iqn = connector["initiator"]
        hosts = self._get_host(array, connector, remote=False)
        host = hosts[0] if len(hosts) > 0 else None
        if host:
            host_name = host.name
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
                    raise PureDriverException(
                        reason=_("Unable to re-use a host that is not "
                                 "managed by Cinder with use_chap_auth=True,"))
                elif chap_username is None or chap_password is None:
                    LOG.error("Purity host %(host_name)s is managed by "
                              "Cinder but CHAP credentials could not be "
                              "retrieved from the Cinder database.",
                              {"host_name": host_name})
                    raise PureDriverException(
                        reason=_("Unable to re-use host with unknown CHAP "
                                 "credentials configured."))
        else:
            personality = self.configuration.safe_get('pure_host_personality')
            host_name = self._generate_purity_host_name(connector["host"])
            LOG.info("Creating host object %(host_name)r with IQN:"
                     " %(iqn)s.", {"host_name": host_name, "iqn": iqn})
            res = array.post_hosts(names=[host_name],
                                   host=flasharray.HostPost(iqns=[iqn]))
            if res.status_code == 400:
                if (ERR_MSG_ALREADY_EXISTS in res.errors[0].message or
                        ERR_MSG_ALREADY_IN_USE in res.errors[0].message):
                    # If someone created it before we could just retry, we will
                    # pick up the new host.
                    LOG.debug('Unable to create host: %s',
                              res.errors[0].message)
                    raise PureRetryableException()

            if personality:
                self.set_personality(array, host_name, personality)

            if self.configuration.use_chap_auth:
                res = array.patch_hosts(names=[host_name],
                                        host=flasharray.HostPatch(
                                            chap=flasharray.Chap(
                                                host_user=chap_username,
                                                host_password=chap_password)))
                if (res.status_code == 400 and
                        ERR_MSG_HOST_NOT_EXIST in res.errors[0].message):
                    # If the host disappeared out from under us that's ok,
                    # we will just retry and snag a new host.
                    LOG.debug('Unable to set CHAP info: %s',
                              res.errors[0].message)
                    raise PureRetryableException()

        # TODO: Ensure that the host has the correct preferred
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

    VERSION = "21.0.fc"

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureFCDriver, self).__init__(execute=execute, *args, **kwargs)
        self._storage_protocol = constants.FC
        self._lookup_service = fczm_utils.create_lookup_service()

    def _get_host(self, array, connector, remote=False):
        """Return dict describing existing Purity host object or None."""
        if remote:
            for wwn in connector["wwpns"]:
                hosts = list(
                    getattr(
                        array.get_hosts(
                            filter="wwns='"
                            + wwn.upper()
                            + "' and not is_local"
                        ),
                        "items",
                        []
                    )
                )
        else:
            for wwn in connector["wwpns"]:
                hosts = list(
                    getattr(
                        array.get_hosts(
                            filter="wwns='"
                            + wwn.upper()
                            + "' and is_local"
                        ),
                        "items",
                        []
                    )
                )
        return hosts

    def _get_array_wwns(self, array):
        """Return list of wwns from the array

        Ensure that only true scsi FC ports are selected
        and not any that are enabled for NVMe-based FC with
        an associated NQN.
        """
        ports = self._get_valid_ports(array)
        valid_ports = [port.wwn.replace(":", "") for port in ports if getattr(
            port, "wwn", None) and not getattr(port, "nqn", None)]
        return valid_ports

    @pure_driver_debug_trace
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        pure_vol_name = self._get_vol_name(volume)
        target_arrays = [self._get_current_array()]
        if (self._is_vol_in_pod(pure_vol_name) and
                self._is_active_cluster_enabled and
                not self._failed_over_primary_array):
            target_arrays += self._uniform_active_cluster_target_arrays

        target_luns = []
        target_wwns = []
        for array in target_arrays:
            connection = self._connect(array, pure_vol_name, connector)
            if not connection[0].lun:
                # Swallow any exception, just warn and continue
                LOG.warning("self._connect failed.")
                continue
            array_wwns = self._get_array_wwns(array)
            for wwn in array_wwns:
                target_wwns.append(wwn)
                target_luns.append(connection[0].lun)

        # Build the zoning map based on *all* wwns, this could be multiple
        # arrays connecting to the same host with a stretched volume.
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
                "addressing_mode": brick_constants.SCSI_ADDRESSING_SAM2,
            }
        }
        properties["data"]["wwn"] = self._get_wwn(pure_vol_name)

        fczm_utils.add_fc_zone(properties)
        return properties

    @utils.retry(PureRetryableException,
                 retries=HOST_CREATE_MAX_RETRIES)
    def _connect(self, array, vol_name, connector):
        """Connect the host and volume; return dict describing connection."""
        wwns = connector["wwpns"]
        hosts = self._get_host(array, connector, remote=False)
        host = hosts[0] if len(hosts) > 0 else None

        if host:
            host_name = host.name
            LOG.info("Re-using existing purity host %(host_name)r",
                     {"host_name": host_name})
        else:
            personality = self.configuration.safe_get('pure_host_personality')
            host_name = self._generate_purity_host_name(connector["host"])
            LOG.info("Creating host object %(host_name)r with WWN:"
                     " %(wwn)s.", {"host_name": host_name, "wwn": wwns})
            res = array.post_hosts(names=[host_name],
                                   host=flasharray.HostPost(wwns=wwns))
            if (res.status_code == 400 and
                    (ERR_MSG_ALREADY_EXISTS in res.errors[0].message or
                        ERR_MSG_ALREADY_IN_USE in res.errors[0].message)):
                # If someone created it before we could just retry, we will
                # pick up the new host.
                LOG.debug('Unable to create host: %s',
                          res.errors[0].message)
                raise PureRetryableException()

            if personality:
                self.set_personality(array, host_name, personality)

        # TODO: Ensure that the host has the correct preferred
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
        # None `connector` indicates force detach, then delete all even
        # if the volume is multi-attached.
        multiattach = (connector is not None and
                       self._is_multiattach_to_host(volume.volume_attachment,
                                                    connector["host"]))
        unused_wwns = []

        if self._is_vol_in_pod(vol_name):
            # Try to disconnect from each host, they may not be online though
            # so if they fail don't cause a problem.
            for array in self._uniform_active_cluster_target_arrays:
                no_more_connections = self._disconnect(
                    array, volume, connector, remove_remote_hosts=True,
                    is_multiattach=multiattach)
                if no_more_connections:
                    unused_wwns += self._get_array_wwns(array)

        # Now disconnect from the current array, removing any left over
        # remote hosts that we maybe couldn't reach.
        current_array = self._get_current_array()
        no_more_connections = self._disconnect(current_array,
                                               volume, connector,
                                               remove_remote_hosts=False,
                                               is_multiattach=multiattach)
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


@interface.volumedriver
class PureNVMEDriver(PureBaseVolumeDriver, driver.BaseVD):
    """OpenStack Volume Driver to support Pure Storage FlashArray.

    This version of the driver enables the use of NVMe over different
    transport types for the underlying storage connectivity with the
    FlashArray.
    """

    VERSION = "21.0.nvme"

    def __init__(self, *args, **kwargs):
        execute = kwargs.pop("execute", utils.execute)
        super(PureNVMEDriver, self).__init__(execute=execute,
                                             *args, **kwargs)
        if self.configuration.pure_nvme_transport == "roce":
            self.transport_type = "rdma"
            self._storage_protocol = constants.NVMEOF_ROCE
        else:
            self.transport_type = "tcp"
            self._storage_protocol = constants.NVMEOF_TCP

    def _get_nguid(self, pure_vol_name):
        """Return the NGUID based on the volume's serial number

        The NGUID is constructed from the volume serial number and
        3 octet OUI

        // octet 0:              padding
        // octets 1 - 7:         first 7 octets of volume serial number
        // octets 8 - 10:        3 octet OUI (24a937)
        // octets 11 - 15:       last 5 octets of volume serial number
        """
        array = self._get_current_array()
        volume_info = list(array.get_volumes(names=[pure_vol_name]).items)[0]
        nguid = ("00" + volume_info.serial[0:14] +
                 "24a937" + volume_info.serial[-10:])
        return nguid.lower()

    def _get_host(self, array, connector, remote=False):
        """Return a list of dicts describing existing host objects or None."""
        if remote:
            hosts = list(
                getattr(
                    array.get_hosts(
                        filter="nqns='"
                        + connector["nqn"]
                        + "' and not is_local"
                    ),
                    "items",
                    []
                )
            )
        else:
            hosts = list(
                getattr(
                    array.get_hosts(
                        filter="nqns='"
                        + connector["nqn"]
                        + "' and is_local"
                    ),
                    "items",
                    []
                )
            )
        return hosts

    @pure_driver_debug_trace
    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        pure_vol_name = self._get_vol_name(volume)
        target_arrays = [self._get_current_array()]
        if (
            self._is_vol_in_pod(pure_vol_name)
            and self._is_active_cluster_enabled and
            not self._failed_over_primary_array
        ):
            target_arrays += self._uniform_active_cluster_target_arrays

        targets = []
        for array in target_arrays:
            connection = self._connect(array, pure_vol_name, connector)
            array_info = list(self._array.get_arrays().items)[0]
            # Minimum NVMe-TCP support is 6.4.2, but at 6.6.0 Purity
            # changes from using LUN to NSID
            if version.parse(array_info.version) < version.parse(
                '6.6.0'
            ):
                if not connection[0].lun:
                    # Swallow any exception, just warn and continue
                    LOG.warning("self._connect failed.")
                    continue
            else:
                if not connection[0].nsid:
                    # Swallow any exception, just warn and continue
                    LOG.warning("self._connect failed.")
                    continue
            target_ports = self._get_target_nvme_ports(array)
            targets.append(
                {
                    "connection": connection,
                    "ports": target_ports,
                }
            )
        properties = self._build_connection_properties(targets)

        properties["data"]["volume_nguid"] = self._get_nguid(pure_vol_name)

        return properties

    def _build_connection_properties(self, targets):
        props = {
            "driver_volume_type": "nvmeof",
            "data": {
                "discard": True,
            },
        }

        if self.configuration.pure_nvme_cidr_list:
            nvme_cidrs = self.configuration.pure_nvme_cidr_list
            if self.configuration.pure_nvme_cidr != "0.0.0.0/0":
                LOG.warning(
                    "pure_nvme_cidr was ignored as "
                    "pure_nvme_cidr_list is set"
                )
        else:
            nvme_cidrs = [self.configuration.pure_nvme_cidr]

        check_nvme_cidrs = [
            ipaddress.ip_network(item) for item in nvme_cidrs
        ]

        target_luns = []
        target_nqns = []
        target_portals = []

        array_info = list(self._array.get_arrays().items)[0]
        # Aggregate all targets together, we may end up with different
        # namespaces for different target nqn/subsys sets (ie. it could
        # be a unique namespace for each FlashArray)
        for target in range(0, len(targets)):
            for port in targets[target]["ports"]:
                # Check to ensure that the portal IP is in the NVMe target
                # CIDR before adding it
                target_portal = port.portal
                if target_portal and port.nqn:
                    portal, p_port = target_portal.rsplit(':', 1)
                    portal = portal.strip("[]")
                    check_ip = ipaddress.ip_address(portal)
                    for check_cidr in check_nvme_cidrs:
                        if check_ip in check_cidr:
                            # Minimum NVMe-TCP support is 6.4.2,
                            # but at 6.6.0 Purity changes from using LUN to
                            # NSID
                            if version.parse(
                                array_info.version
                            ) < version.parse("6.6.0"):
                                target_luns.append(
                                    targets[target]["connection"][0].lun)
                            else:
                                target_luns.append(
                                    targets[target]["connection"][0].nsid)
                            target_nqns.append(port.nqn)
                            target_portals.append(
                                (portal, NVME_PORT, self.transport_type)
                            )
        LOG.debug(
            "NVMe target portals that match CIDR range: '%s'", target_portals
        )

        # If we have multiple ports always report them.
        if target_luns and target_nqns:
            props["data"]["portals"] = target_portals
            props["data"]["target_nqn"] = target_nqns[0]
        else:
            raise PureDriverException(
                reason=_("No approrpiate nvme ports on target array.")
            )

        return props

    def _get_target_nvme_ports(self, array):
        """Return list of correct nvme-enabled port descriptions."""
        ports = self._get_valid_ports(array)
        valid_nvme_ports = []
        nvme_ports = [port for port in ports if getattr(port, "nqn", None)]
        for port in range(0, len(nvme_ports)):
            port_detail = list(array.get_network_interfaces(
                names=[nvme_ports[port].name.lower()]
            ).items)[0]
            if hasattr(port_detail.eth, "address") and (
                    port_detail.services[0] == "nvme-" +
                    self.configuration.pure_nvme_transport):
                valid_nvme_ports.append(nvme_ports[port])
        if not nvme_ports:
            raise PureDriverException(
                reason=_("No %(type)s enabled ports on target array.") %
                {"type": self._storage_protocol}
            )
        return valid_nvme_ports

    @utils.retry(PureRetryableException, retries=HOST_CREATE_MAX_RETRIES)
    def _connect(self, array, vol_name, connector):
        """Connect the host and volume; return dict describing connection."""
        nqn = connector["nqn"]
        hosts = self._get_host(array, connector, remote=False)
        host = hosts[0] if len(hosts) > 0 else None
        if host:
            host_name = host.name
            LOG.info(
                "Re-using existing purity host %(host_name)r",
                {"host_name": host_name},
            )
        else:
            personality = self.configuration.safe_get('pure_host_personality')
            host_name = self._generate_purity_host_name(connector["host"])
            LOG.info(
                "Creating host object %(host_name)r with NQN:" " %(nqn)s.",
                {"host_name": host_name, "nqn": connector["nqn"]},
            )
            res = array.post_hosts(names=[host_name],
                                   host=flasharray.HostPost(nqns=[nqn]))
            if res.status_code == 400 and (
                    ERR_MSG_ALREADY_EXISTS in res.errors[0].message
                    or ERR_MSG_ALREADY_IN_USE in res.errors[0].message):
                # If someone created it before we could just retry, we will
                # pick up the new host.
                LOG.debug("Unable to create host: %s",
                          res.errors[0].message)
                raise PureRetryableException()

            if personality:
                self.set_personality(array, host_name, personality)

        # TODO: Ensure that the host has the correct preferred
        # arrays configured for it.

        return self._connect_host_to_vol(array, host_name, vol_name)
