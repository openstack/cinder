#    (c) Copyright 2012-2016 Hewlett Packard Enterprise Development LP
#    All Rights Reserved.
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
#
"""
Volume driver common utilities for HPE 3PAR Storage array

The 3PAR drivers requires 3.1.3 firmware on the 3PAR array.

You will need to install the python hpe3parclient module.
sudo pip install python-3parclient

The drivers uses both the REST service and the SSH
command line to correctly operate.  Since the
ssh credentials and the REST credentials can be different
we need to have settings for both.

The drivers requires the use of the san_ip, san_login,
san_password settings for ssh connections into the 3PAR
array.   It also requires the setting of
hpe3par_api_url, hpe3par_username, hpe3par_password
for credentials to talk to the REST service on the 3PAR
array.
"""

import ast
import json
import math
import pprint
import re
import six
import uuid

from oslo_serialization import base64
from oslo_utils import importutils

hpe3parclient = importutils.try_import("hpe3parclient")
if hpe3parclient:
    from hpe3parclient import client
    from hpe3parclient import exceptions as hpeexceptions

from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _
from cinder.objects import fields
from cinder.volume import configuration
from cinder.volume import qos_specs
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types

import taskflow.engines
from taskflow.patterns import linear_flow

LOG = logging.getLogger(__name__)

MIN_CLIENT_VERSION = '4.2.0'
DEDUP_API_VERSION = 30201120
FLASH_CACHE_API_VERSION = 30201200
COMPRESSION_API_VERSION = 30301215
SRSTATLD_API_VERSION = 30201200
REMOTE_COPY_API_VERSION = 30202290

hpe3par_opts = [
    cfg.StrOpt('hpe3par_api_url',
               default='',
               help="3PAR WSAPI Server Url like "
                    "https://<3par ip>:8080/api/v1",
               deprecated_name='hp3par_api_url'),
    cfg.StrOpt('hpe3par_username',
               default='',
               help="3PAR username with the 'edit' role",
               deprecated_name='hp3par_username'),
    cfg.StrOpt('hpe3par_password',
               default='',
               help="3PAR password for the user specified in hpe3par_username",
               secret=True,
               deprecated_name='hp3par_password'),
    cfg.ListOpt('hpe3par_cpg',
                default=["OpenStack"],
                help="List of the CPG(s) to use for volume creation",
                deprecated_name='hp3par_cpg'),
    cfg.StrOpt('hpe3par_cpg_snap',
               default="",
               help="The CPG to use for Snapshots for volumes. "
                    "If empty the userCPG will be used.",
               deprecated_name='hp3par_cpg_snap'),
    cfg.StrOpt('hpe3par_snapshot_retention',
               default="",
               help="The time in hours to retain a snapshot.  "
                    "You can't delete it before this expires.",
               deprecated_name='hp3par_snapshot_retention'),
    cfg.StrOpt('hpe3par_snapshot_expiration',
               default="",
               help="The time in hours when a snapshot expires "
                    " and is deleted.  This must be larger than expiration",
               deprecated_name='hp3par_snapshot_expiration'),
    cfg.BoolOpt('hpe3par_debug',
                default=False,
                help="Enable HTTP debugging to 3PAR",
                deprecated_name='hp3par_debug'),
    cfg.ListOpt('hpe3par_iscsi_ips',
                default=[],
                help="List of target iSCSI addresses to use.",
                deprecated_name='hp3par_iscsi_ips'),
    cfg.BoolOpt('hpe3par_iscsi_chap_enabled',
                default=False,
                help="Enable CHAP authentication for iSCSI connections.",
                deprecated_name='hp3par_iscsi_chap_enabled'),
]


CONF = cfg.CONF
CONF.register_opts(hpe3par_opts, group=configuration.SHARED_CONF_GROUP)

# Input/output (total read/write) operations per second.
THROUGHPUT = 'throughput'
# Data processed (total read/write) per unit time: kilobytes per second.
BANDWIDTH = 'bandwidth'
# Response time (total read/write): microseconds.
LATENCY = 'latency'
# IO size (total read/write): kilobytes.
IO_SIZE = 'io_size'
# Queue length for processing IO requests
QUEUE_LENGTH = 'queue_length'
# Average busy percentage
AVG_BUSY_PERC = 'avg_busy_perc'


class HPE3PARCommon(object):
    """Class that contains common code for the 3PAR drivers.

    Version history:

    .. code-block:: none

        1.2.0 - Updated hp3parclient API use to 2.0.x
        1.2.1 - Check that the VVS exists
        1.2.2 - log prior to raising exceptions
        1.2.3 - Methods to update key/value pair bug #1258033
        1.2.4 - Remove deprecated config option hp3par_domain
        1.2.5 - Raise Ex when deleting snapshot with dependencies bug #1250249
        1.2.6 - Allow optional specifying n:s:p for vlun creation bug #1269515
                This update now requires 3.1.2 MU3 firmware
        1.3.0 - Removed all SSH code.  We rely on the hp3parclient now.
        2.0.0 - Update hp3parclient API uses 3.0.x
        2.0.1 - Updated to use qos_specs, added new qos settings and personas
        2.0.2 - Add back-end assisted volume migrate
        2.0.3 - Allow deleting missing snapshots bug #1283233
        2.0.4 - Allow volumes created from snapshots to be larger bug #1279478
        2.0.5 - Fix extend volume units bug #1284368
        2.0.6 - use loopingcall.wait instead of time.sleep
        2.0.7 - Allow extend volume based on snapshot bug #1285906
        2.0.8 - Fix detach issue for multiple hosts bug #1288927
        2.0.9 - Remove unused 3PAR driver method bug #1310807
        2.0.10 - Fixed an issue with 3PAR vlun location bug #1315542
        2.0.11 - Remove hp3parclient requirement from unit tests #1315195
        2.0.12 - Volume detach hangs when host is in a host set bug #1317134
        2.0.13 - Added support for managing/unmanaging of volumes
        2.0.14 - Modified manage volume to use standard 'source-name' element.
        2.0.15 - Added support for volume retype
        2.0.16 - Add a better log during delete_volume time. Bug #1349636
        2.0.17 - Added iSCSI CHAP support
                 This update now requires 3.1.3 MU1 firmware
                 and hp3parclient 3.1.0
        2.0.18 - HP 3PAR manage_existing with volume-type support
        2.0.19 - Update default persona from Generic to Generic-ALUA
        2.0.20 - Configurable SSH missing key policy and known hosts file
        2.0.21 - Remove bogus invalid snapCPG=None exception
        2.0.22 - HP 3PAR drivers should not claim to have 'infinite' space
        2.0.23 - Increase the hostname size from 23 to 31  Bug #1371242
        2.0.24 - Add pools (hp3par_cpg now accepts a list of CPGs)
        2.0.25 - Migrate without losing type settings bug #1356608
        2.0.26 - Don't ignore extra-specs snap_cpg when missing cpg #1368972
        2.0.27 - Fixing manage source-id error bug #1357075
        2.0.28 - Removing locks bug #1381190
        2.0.29 - Report a limitless cpg's stats better bug #1398651
        2.0.30 - Update the minimum hp3parclient version bug #1402115
        2.0.31 - Removed usage of host name cache #1398914
        2.0.32 - Update LOG usage to fix translations.  bug #1384312
        2.0.33 - Fix host persona to match WSAPI mapping bug #1403997
        2.0.34 - Fix log messages to match guidelines. bug #1411370
        2.0.35 - Fix default snapCPG for manage_existing bug #1393609
        2.0.36 - Added support for dedup provisioning
        2.0.37 - Added support for enabling Flash Cache
        2.0.38 - Add stats for hp3par goodness_function and filter_function
        2.0.39 - Added support for updated detach_volume attachment.
        2.0.40 - Make the 3PAR drivers honor the pool in create  bug #1432876
        2.0.41 - Only log versions at startup.  bug #1447697
        2.0.42 - Fix type for snapshot config settings. bug #1461640
        2.0.43 - Report the capability of supporting multiattach
        2.0.44 - Update help strings to reduce the 3PAR user role requirements
        2.0.45 - Python 3 fixes
        2.0.46 - Improved VLUN creation and deletion logic. #1469816
        2.0.47 - Changed initialize_connection to use getHostVLUNs. #1475064
        2.0.48 - Adding changes to support 3PAR iSCSI multipath.
        2.0.49 - Added client CPG stats to driver volume stats. bug #1482741
        2.0.50 - Add over subscription support
        2.0.51 - Adds consistency group support
        2.0.52 - Added update_migrated_volume. bug #1492023
        2.0.53 - Fix volume size conversion. bug #1513158
        3.0.0 - Rebranded HP to HPE.
        3.0.1 - Fixed find_existing_vluns bug #1515033
        3.0.2 - Python 3 support
        3.0.3 - Remove db access for consistency groups
        3.0.4 - Adds v2 managed replication support
        3.0.5 - Adds v2 unmanaged replication support
        3.0.6 - Adding manage/unmanage snapshot support
        3.0.7 - Enable standard capabilities based on 3PAR licenses
        3.0.8 - Optimize array ID retrieval
        3.0.9 - Bump minimum API version for volume replication
        3.0.10 - Added additional volumes checks to the manage snapshot API
        3.0.11 - Fix the image cache capability bug #1491088
        3.0.12 - Remove client version checks for replication
        3.0.13 - Support creating a cg from a source cg
        3.0.14 - Comparison of WWNs now handles case difference. bug #1546453
        3.0.15 - Update replication to version 2.1
        3.0.16 - Use same LUN ID for each VLUN path #1551994
        3.0.17 - Don't fail on clearing 3PAR object volume key. bug #1546392
        3.0.18 - create_cloned_volume account for larger size.  bug #1554740
        3.0.19 - Remove metadata that tracks the instance ID. bug #1572665
        3.0.20 - Fix lun_id of 0 issue. bug #1573298
        3.0.21 - Driver no longer fails to initialize if
                 System Reporter license is missing. bug #1568078
        3.0.22 - Rework delete_vlun. Bug #1582922
        3.0.23 - Fix CG create failures with long display name or special
                 characters. bug #1573647
        3.0.24 - Fix terminate connection on failover
        3.0.25 - Fix delete volume when online clone is active. bug #1349639
        3.0.26 - Fix concurrent snapshot delete conflict. bug #1600104
        3.0.27 - Fix snapCPG error during backup of attached volume.
                 Bug #1646396 and also ,Fix backup of attached ISCSI
                 and CHAP enabled volume.bug #1644238.
        3.0.28 - Remove un-necessary snapshot creation of source volume
                 while doing online copy in create_cloned_volume call.
                 Bug #1661541
        3.0.29 - Fix convert snapshot volume to base volume type. bug #1656186
        3.0.30 - Handle manage and unmanage hosts present. bug #1648067
        3.0.31 - Enable HPE-3PAR Compression Feature.
        3.0.32 - Add consistency group capability to generic volume group
                 in HPE-3APR
        3.0.33 - Added replication feature in retype flow. bug #1680313
        3.0.34 - Add cloned volume to vvset in online copy. bug #1664464
        3.0.35 - Add volume to consistency group if flag enabled. bug #1702317
        3.0.36 - Swap volume name in migration. bug #1699733
        3.0.37 - Fixed image cache enabled capability. bug #1686985
        3.0.38 - Fixed delete operation of replicated volume which is part
                 of QOS. bug #1717875
        3.0.39 - Added check to modify host after volume detach. bug #1730720
        3.0.40 - Handle force detach case. bug #1686745


    """

    VERSION = "3.0.40"

    stats = {}

    # TODO(Ramy): move these to the 3PAR Client
    VLUN_TYPE_EMPTY = 1
    VLUN_TYPE_PORT = 2
    VLUN_TYPE_HOST = 3
    VLUN_TYPE_MATCHED_SET = 4
    VLUN_TYPE_HOST_SET = 5

    THIN = 2
    DEDUP = 6
    CONVERT_TO_THIN = 1
    CONVERT_TO_FULL = 2
    CONVERT_TO_DEDUP = 3

    # v2 replication constants
    SYNC = 1
    PERIODIC = 2
    EXTRA_SPEC_REP_MODE = "replication:mode"
    EXTRA_SPEC_REP_SYNC_PERIOD = "replication:sync_period"
    RC_ACTION_CHANGE_TO_PRIMARY = 7
    DEFAULT_REP_MODE = 'periodic'
    DEFAULT_SYNC_PERIOD = 900
    RC_GROUP_STARTED = 3
    SYNC_STATUS_COMPLETED = 3
    FAILBACK_VALUE = 'default'

    # License values for reported capabilities
    PRIORITY_OPT_LIC = "Priority Optimization"
    THIN_PROV_LIC = "Thin Provisioning"
    REMOTE_COPY_LIC = "Remote Copy"
    SYSTEM_REPORTER_LIC = "System Reporter"
    COMPRESSION_LIC = "Compression"

    # Valid values for volume type extra specs
    # The first value in the list is the default value
    valid_prov_values = ['thin', 'full', 'dedup']
    valid_persona_values = ['2 - Generic-ALUA',
                            '1 - Generic',
                            '3 - Generic-legacy',
                            '4 - HPUX-legacy',
                            '5 - AIX-legacy',
                            '6 - EGENERA',
                            '7 - ONTAP-legacy',
                            '8 - VMware',
                            '9 - OpenVMS',
                            '10 - HPUX',
                            '11 - WindowsServer']
    hpe_qos_keys = ['minIOPS', 'maxIOPS', 'minBWS', 'maxBWS', 'latency',
                    'priority']
    qos_priority_level = {'low': 1, 'normal': 2, 'high': 3}
    hpe3par_valid_keys = ['cpg', 'snap_cpg', 'provisioning', 'persona', 'vvs',
                          'flash_cache', 'compression']

    def __init__(self, config, active_backend_id=None):
        self.config = config
        self.client = None
        self.uuid = uuid.uuid4()
        self._client_conf = {}
        self._replication_targets = []
        self._replication_enabled = False
        self._active_backend_id = active_backend_id

    def get_version(self):
        return self.VERSION

    def check_flags(self, options, required_flags):
        for flag in required_flags:
            if not getattr(options, flag, None):
                msg = _('%s is not set') % flag
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

    def check_replication_flags(self, options, required_flags):
        for flag in required_flags:
            if not options.get(flag, None):
                msg = (_('%s is not set and is required for the replication '
                         'device to be valid.') % flag)
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

    def _create_client(self, timeout=None):
        hpe3par_api_url = self._client_conf['hpe3par_api_url']
        cl = client.HPE3ParClient(hpe3par_api_url, timeout=timeout)
        client_version = hpe3parclient.version

        if client_version < MIN_CLIENT_VERSION:
            ex_msg = (_('Invalid hpe3parclient version found (%(found)s). '
                        'Version %(minimum)s or greater required. Run "pip'
                        ' install --upgrade python-3parclient" to upgrade'
                        ' the hpe3parclient.')
                      % {'found': client_version,
                         'minimum': MIN_CLIENT_VERSION})
            LOG.error(ex_msg)
            raise exception.InvalidInput(reason=ex_msg)

        return cl

    def client_login(self):
        try:
            LOG.debug("Connecting to 3PAR")
            self.client.login(self._client_conf['hpe3par_username'],
                              self._client_conf['hpe3par_password'])
        except hpeexceptions.HTTPUnauthorized as ex:
            msg = (_("Failed to Login to 3PAR (%(url)s) because %(err)s") %
                   {'url': self._client_conf['hpe3par_api_url'], 'err': ex})
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        known_hosts_file = CONF.ssh_hosts_key_file
        policy = "AutoAddPolicy"
        if CONF.strict_ssh_host_key_policy:
            policy = "RejectPolicy"
        self.client.setSSHOptions(
            self._client_conf['san_ip'],
            self._client_conf['san_login'],
            self._client_conf['san_password'],
            port=self._client_conf['san_ssh_port'],
            conn_timeout=self._client_conf['ssh_conn_timeout'],
            privatekey=self._client_conf['san_private_key'],
            missing_key_policy=policy,
            known_hosts_file=known_hosts_file)

    def client_logout(self):
        LOG.debug("Disconnect from 3PAR REST and SSH %s", self.uuid)
        self.client.logout()

    def _create_replication_client(self, remote_array):
        try:
            cl = client.HPE3ParClient(remote_array['hpe3par_api_url'])
            cl.login(remote_array['hpe3par_username'],
                     remote_array['hpe3par_password'])
        except hpeexceptions.HTTPUnauthorized as ex:
            msg = (_("Failed to Login to 3PAR (%(url)s) because %(err)s") %
                   {'url': remote_array['hpe3par_api_url'], 'err': ex})
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        known_hosts_file = CONF.ssh_hosts_key_file
        policy = "AutoAddPolicy"
        if CONF.strict_ssh_host_key_policy:
            policy = "RejectPolicy"
        cl.setSSHOptions(
            remote_array['san_ip'],
            remote_array['san_login'],
            remote_array['san_password'],
            port=remote_array['san_ssh_port'],
            conn_timeout=remote_array['ssh_conn_timeout'],
            privatekey=remote_array['san_private_key'],
            missing_key_policy=policy,
            known_hosts_file=known_hosts_file)
        return cl

    def _destroy_replication_client(self, client):
        if client is not None:
            client.logout()

    def do_setup(self, context, timeout=None, stats=None):
        if hpe3parclient is None:
            msg = _('You must install hpe3parclient before using 3PAR'
                    ' drivers. Run "pip install python-3parclient" to'
                    ' install the hpe3parclient.')
            raise exception.VolumeBackendAPIException(data=msg)

        try:
            # This will set self._client_conf with the proper credentials
            # to communicate with the 3PAR array. It will contain either
            # the values for the primary array or secondary array in the
            # case of a fail-over.
            self._get_3par_config()
            self.client = self._create_client(timeout=timeout)
            wsapi_version = self.client.getWsApiVersion()
            self.API_VERSION = wsapi_version['build']

            # If replication is properly configured, the primary array's
            # API version must meet the minimum requirements.
            if self._replication_enabled and (
               self.API_VERSION < REMOTE_COPY_API_VERSION):
                self._replication_enabled = False
                LOG.error("The primary array must have an API version of "
                          "%(min_ver)s or higher, but is only on "
                          "%(current_ver)s, therefore replication is not "
                          "supported.",
                          {'min_ver': REMOTE_COPY_API_VERSION,
                           'current_ver': self.API_VERSION})
        except hpeexceptions.UnsupportedVersion as ex:
            # In the event we cannot contact the configured primary array,
            # we want to allow a failover if replication is enabled.
            self._do_replication_setup()
            if self._replication_enabled:
                self.client = None
            raise exception.InvalidInput(ex)

        if context:
            # The context is None except at driver startup.
            LOG.info("HPE3PARCommon %(common_ver)s,"
                     "hpe3parclient %(rest_ver)s",
                     {"common_ver": self.VERSION,
                      "rest_ver": hpe3parclient.get_version_string()})
        if self.config.hpe3par_debug:
            self.client.debug_rest(True)
        if self.API_VERSION < SRSTATLD_API_VERSION:
            # Firmware version not compatible with srstatld
            LOG.warning("srstatld requires "
                        "WSAPI version '%(srstatld_version)s' "
                        "version '%(version)s' is installed.",
                        {'srstatld_version': SRSTATLD_API_VERSION,
                         'version': self.API_VERSION})

        # Get the client ID for provider_location. We only need to retrieve
        # the ID directly from the array if the driver stats are not provided.
        if not stats:
            try:
                self.client_login()
                info = self.client.getStorageSystemInfo()
                self.client.id = six.text_type(info['id'])
            except Exception:
                self.client.id = 0
            finally:
                self.client_logout()
        else:
            self.client.id = stats['array_id']

    def check_for_setup_error(self):
        if self.client:
            self.client_login()
            try:
                cpg_names = self._client_conf['hpe3par_cpg']
                for cpg_name in cpg_names:
                    self.validate_cpg(cpg_name)

            finally:
                self.client_logout()

    def validate_cpg(self, cpg_name):
        try:
            self.client.getCPG(cpg_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("CPG (%s) doesn't exist on array") % cpg_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

    def get_domain(self, cpg_name):
        try:
            cpg = self.client.getCPG(cpg_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("Failed to get domain because CPG (%s) doesn't "
                     "exist on array.") % cpg_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        if 'domain' in cpg:
            return cpg['domain']
        return None

    def extend_volume(self, volume, new_size):
        volume_name = self._get_3par_vol_name(volume['id'])
        old_size = volume['size']
        growth_size = int(new_size) - old_size
        LOG.debug("Extending Volume %(vol)s from %(old)s to %(new)s, "
                  " by %(diff)s GB.",
                  {'vol': volume_name, 'old': old_size, 'new': new_size,
                   'diff': growth_size})
        growth_size_mib = growth_size * units.Ki
        self._extend_volume(volume, volume_name, growth_size_mib)

    def create_group(self, context, group):
        """Creates a group."""
        if not volume_utils.is_group_a_cg_snapshot_type(group):
            raise NotImplementedError()
        if group.volume_type_ids is not None:
            for volume_type in group.volume_types:
                allow_type = self.is_volume_group_snap_type(
                    volume_type)
                if not allow_type:
                    msg = _('For a volume type to be a part of consistent '
                            'group, volume type extra spec must have '
                            'consistent_group_snapshot_enabled="<is> True"')
                    LOG.error(msg)
                    raise exception.InvalidInput(reason=msg)

        pool = volume_utils.extract_host(group.host, level='pool')
        domain = self.get_domain(pool)
        cg_name = self._get_3par_vvs_name(group.id)

        extra = {'group_id': group.id}
        if group.group_snapshot_id is not None:
            extra['group_snapshot_id'] = group.group_snapshot_id

        self.client.createVolumeSet(cg_name, domain=domain,
                                    comment=six.text_type(extra))

        model_update = {'status': fields.GroupStatus.AVAILABLE}
        return model_update

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):

        self.create_group(context, group)
        vvs_name = self._get_3par_vvs_name(group.id)
        if group_snapshot and snapshots:
            cgsnap_name = self._get_3par_snap_name(group_snapshot.id)
            snap_base = cgsnap_name
        elif source_group and source_vols:
            cg_id = source_group.id
            # Create a brand new uuid for the temp snap.
            snap_uuid = uuid.uuid4().hex

            # Create a temporary snapshot of the volume set in order to
            # perform an online copy. These temp snapshots will be deleted
            # when the source consistency group is deleted.
            temp_snap = self._get_3par_snap_name(snap_uuid, temp_snap=True)
            snap_shot_name = temp_snap + "-@count@"
            copy_of_name = self._get_3par_vvs_name(cg_id)
            optional = {'expirationHours': 1}
            self.client.createSnapshotOfVolumeSet(snap_shot_name, copy_of_name,
                                                  optional=optional)
            snap_base = temp_snap

        for i, volume in enumerate(volumes):
            snap_name = snap_base + "-" + six.text_type(i)
            volume_name = self._get_3par_vol_name(volume.id)
            type_info = self.get_volume_settings_from_type(volume)
            cpg = type_info['cpg']
            snapcpg = type_info['snap_cpg']
            tpvv = type_info.get('tpvv', False)
            tdvv = type_info.get('tdvv', False)

            compression = self.get_compression_policy(
                type_info['hpe3par_keys'])

            optional = {'online': True, 'snapCPG': snapcpg,
                        'tpvv': tpvv, 'tdvv': tdvv}

            if compression is not None:
                optional['compression'] = compression

            self.client.copyVolume(snap_name, volume_name, cpg, optional)
            self.client.addVolumeToVolumeSet(vvs_name, volume_name)

        return None, None

    def delete_group(self, context, group, volumes):
        """Deletes a group."""

        try:
            if not volume_utils.is_group_a_cg_snapshot_type(group):
                raise NotImplementedError()
            cg_name = self._get_3par_vvs_name(group.id)
            self.client.deleteVolumeSet(cg_name)
        except hpeexceptions.HTTPNotFound:
            LOG.warning("Virtual Volume Set '%s' doesn't exist on array.",
                        cg_name)
        except hpeexceptions.HTTPConflict as e:
            LOG.error("Conflict detected in Virtual Volume Set"
                      " %(volume_set)s: %(error)s",
                      {"volume_set": cg_name,
                       "error": e})

        volume_model_updates = []
        for volume in volumes:
            volume_update = {'id': volume.id}
            try:
                self.delete_volume(volume)
                volume_update['status'] = 'deleted'
            except Exception as ex:
                LOG.error("There was an error deleting volume %(id)s: "
                          "%(error)s.",
                          {'id': volume.id,
                           'error': ex})
                volume_update['status'] = 'error'
            volume_model_updates.append(volume_update)
        model_update = {'status': group.status}
        return model_update, volume_model_updates

    def update_group(self, context, group, add_volumes=None,
                     remove_volumes=None):
        grp_snap_enable = volume_utils.is_group_a_cg_snapshot_type(group)
        if not grp_snap_enable:
            raise NotImplementedError()
        volume_set_name = self._get_3par_vvs_name(group.id)
        for volume in add_volumes:
            volume_name = self._get_3par_vol_name(volume.id)
            vol_snap_enable = self.is_volume_group_snap_type(
                volume.volume_type)
            try:
                if grp_snap_enable and vol_snap_enable:
                    self.client.addVolumeToVolumeSet(volume_set_name,
                                                     volume_name)
                else:
                    msg = (_('Volume with volume id %s is not '
                             'supported as extra specs of this '
                             'volume does not have '
                             'consistent_group_snapshot_enabled="<is> True"'
                             ) % volume['id'])
                    LOG.error(msg)
                    raise exception.InvalidInput(reason=msg)
            except hpeexceptions.HTTPNotFound:
                msg = (_('Virtual Volume Set %s does not exist.') %
                       volume_set_name)
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

        for volume in remove_volumes:
            volume_name = self._get_3par_vol_name(volume.id)
            try:
                self.client.removeVolumeFromVolumeSet(
                    volume_set_name, volume_name)
            except hpeexceptions.HTTPNotFound:
                msg = (_('Virtual Volume Set %s does not exist.') %
                       volume_set_name)
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

        return None, None, None

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group snapshot."""
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()

        cg_id = group_snapshot.group_id
        snap_shot_name = self._get_3par_snap_name(group_snapshot.id) + (
            "-@count@")
        copy_of_name = self._get_3par_vvs_name(cg_id)

        extra = {'group_snapshot_id': group_snapshot.id}
        extra['group_id'] = cg_id
        extra['description'] = group_snapshot.description

        optional = {'comment': json.dumps(extra),
                    'readOnly': False}
        if self.config.hpe3par_snapshot_expiration:
            optional['expirationHours'] = (
                int(self.config.hpe3par_snapshot_expiration))

        if self.config.hpe3par_snapshot_retention:
            optional['retentionHours'] = (
                int(self.config.hpe3par_snapshot_retention))

        try:
            self.client.createSnapshotOfVolumeSet(snap_shot_name, copy_of_name,
                                                  optional=optional)
        except Exception as ex:
            msg = (_('There was an error creating the cgsnapshot: %s'),
                   six.text_type(ex))
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        snapshot_model_updates = []
        for snapshot in snapshots:
            snapshot_update = {'id': snapshot['id'],
                               'status': fields.SnapshotStatus.AVAILABLE}
            snapshot_model_updates.append(snapshot_update)

        model_update = {'status': fields.GroupSnapshotStatus.AVAILABLE}

        return model_update, snapshot_model_updates

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group snapshot."""
        if not volume_utils.is_group_a_cg_snapshot_type(group_snapshot):
            raise NotImplementedError()
        cgsnap_name = self._get_3par_snap_name(group_snapshot.id)

        snapshot_model_updates = []
        for i, snapshot in enumerate(snapshots):
            snapshot_update = {'id': snapshot['id']}
            try:
                snap_name = cgsnap_name + "-" + six.text_type(i)
                self.client.deleteVolume(snap_name)
                snapshot_update['status'] = fields.SnapshotStatus.DELETED
            except hpeexceptions.HTTPNotFound as ex:
                # We'll let this act as if it worked
                # it helps clean up the cinder entries.
                LOG.warning("Delete Snapshot id not found. Removing from "
                            "cinder: %(id)s Ex: %(msg)s",
                            {'id': snapshot['id'], 'msg': ex})
                snapshot_update['status'] = fields.SnapshotStatus.ERROR
            except Exception as ex:
                LOG.error("There was an error deleting snapshot %(id)s: "
                          "%(error)s.",
                          {'id': snapshot['id'],
                           'error': six.text_type(ex)})
                snapshot_update['status'] = fields.SnapshotStatus.ERROR
            snapshot_model_updates.append(snapshot_update)

        model_update = {'status': fields.GroupSnapshotStatus.DELETED}

        return model_update, snapshot_model_updates

    def manage_existing(self, volume, existing_ref):
        """Manage an existing 3PAR volume.

        existing_ref is a dictionary of the form:
        {'source-name': <name of the virtual volume>}
        """
        target_vol_name = self._get_existing_volume_ref_name(existing_ref)

        # Check for the existence of the virtual volume.
        old_comment_str = ""
        try:
            vol = self.client.getVolume(target_vol_name)
            if 'comment' in vol:
                old_comment_str = vol['comment']
        except hpeexceptions.HTTPNotFound:
            err = (_("Virtual volume '%s' doesn't exist on array.") %
                   target_vol_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        new_comment = {}

        # Use the display name from the existing volume if no new name
        # was chosen by the user.
        if volume['display_name']:
            display_name = volume['display_name']
            new_comment['display_name'] = volume['display_name']
        elif 'comment' in vol:
            display_name = self._get_3par_vol_comment_value(vol['comment'],
                                                            'display_name')
            if display_name:
                new_comment['display_name'] = display_name
        else:
            display_name = None

        # Generate the new volume information based on the new ID.
        new_vol_name = self._get_3par_vol_name(volume['id'])
        name = 'volume-' + volume['id']

        new_comment['volume_id'] = volume['id']
        new_comment['name'] = name
        new_comment['type'] = 'OpenStack'

        volume_type = None
        if volume['volume_type_id']:
            try:
                volume_type = self._get_volume_type(volume['volume_type_id'])
            except Exception:
                reason = (_("Volume type ID '%s' is invalid.") %
                          volume['volume_type_id'])
                raise exception.ManageExistingVolumeTypeMismatch(reason=reason)

        new_vals = {'newName': new_vol_name,
                    'comment': json.dumps(new_comment)}

        # Ensure that snapCPG is set
        if 'snapCPG' not in vol:
            new_vals['snapCPG'] = vol['userCPG']
            LOG.info("Virtual volume %(disp)s '%(new)s' snapCPG "
                     "is empty so it will be set to: %(cpg)s",
                     {'disp': display_name, 'new': new_vol_name,
                      'cpg': new_vals['snapCPG']})

        # Update the existing volume with the new name and comments.
        self.client.modifyVolume(target_vol_name, new_vals)

        LOG.info("Virtual volume '%(ref)s' renamed to '%(new)s'.",
                 {'ref': existing_ref['source-name'], 'new': new_vol_name})

        retyped = False
        model_update = None
        if volume_type:
            LOG.info("Virtual volume %(disp)s '%(new)s' is being retyped.",
                     {'disp': display_name, 'new': new_vol_name})

            try:
                retyped, model_update = self._retype_from_no_type(volume,
                                                                  volume_type)
                LOG.info("Virtual volume %(disp)s successfully retyped to "
                         "%(new_type)s.",
                         {'disp': display_name,
                          'new_type': volume_type.get('name')})
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.warning("Failed to manage virtual volume %(disp)s "
                                "due to error during retype.",
                                {'disp': display_name})
                    # Try to undo the rename and clear the new comment.
                    self.client.modifyVolume(
                        new_vol_name,
                        {'newName': target_vol_name,
                         'comment': old_comment_str})

        updates = {'display_name': display_name}
        if retyped and model_update:
            updates.update(model_update)

        LOG.info("Virtual volume %(disp)s '%(new)s' is now being managed.",
                 {'disp': display_name, 'new': new_vol_name})

        # Return display name to update the name displayed in the GUI and
        # any model updates from retype.
        return updates

    def manage_existing_snapshot(self, snapshot, existing_ref):
        """Manage an existing 3PAR snapshot.

        existing_ref is a dictionary of the form:
        {'source-name': <name of the snapshot>}
        """
        # Potential parent volume for the snapshot
        volume = snapshot['volume']

        # Do not allow for managing of snapshots for 'failed-over' volumes.
        if volume.get('replication_status') == 'failed-over':
            err = (_("Managing of snapshots to failed-over volumes is "
                     "not allowed."))
            raise exception.InvalidInput(reason=err)

        target_snap_name = self._get_existing_volume_ref_name(existing_ref,
                                                              is_snapshot=True)

        # Check for the existence of the snapshot.
        try:
            snap = self.client.getVolume(target_snap_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("Snapshot '%s' doesn't exist on array.") %
                   target_snap_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        # Make sure the snapshot is being associated with the correct volume.
        parent_vol_name = self._get_3par_vol_name(volume['id'])
        if parent_vol_name != snap['copyOf']:
            err = (_("The provided snapshot '%s' is not a snapshot of "
                     "the provided volume.") % target_snap_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        new_comment = {}

        # Use the display name from the existing snapshot if no new name
        # was chosen by the user.
        if snapshot['display_name']:
            display_name = snapshot['display_name']
            new_comment['display_name'] = snapshot['display_name']
        elif 'comment' in snap:
            display_name = self._get_3par_vol_comment_value(snap['comment'],
                                                            'display_name')
            if display_name:
                new_comment['display_name'] = display_name
        else:
            display_name = None

        # Generate the new snapshot information based on the new ID.
        new_snap_name = self._get_3par_snap_name(snapshot['id'])
        new_comment['volume_id'] = volume['id']
        new_comment['volume_name'] = 'volume-' + volume['id']
        if snapshot.get('display_description', None):
            new_comment['description'] = snapshot['display_description']
        else:
            new_comment['description'] = ""

        new_vals = {'newName': new_snap_name,
                    'comment': json.dumps(new_comment)}

        # Update the existing snapshot with the new name and comments.
        self.client.modifyVolume(target_snap_name, new_vals)

        LOG.info("Snapshot '%(ref)s' renamed to '%(new)s'.",
                 {'ref': existing_ref['source-name'], 'new': new_snap_name})

        updates = {'display_name': display_name}

        LOG.info("Snapshot %(disp)s '%(new)s' is now being managed.",
                 {'disp': display_name, 'new': new_snap_name})

        # Return display name to update the name displayed in the GUI.
        return updates

    def manage_existing_get_size(self, volume, existing_ref):
        """Return size of volume to be managed by manage_existing.

        existing_ref is a dictionary of the form:
        {'source-name': <name of the virtual volume>}
        """
        target_vol_name = self._get_existing_volume_ref_name(existing_ref)

        # Make sure the reference is not in use.
        if re.match('osv-*|oss-*|vvs-*', target_vol_name):
            reason = _("Reference must be for an unmanaged virtual volume.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=target_vol_name,
                reason=reason)

        # Check for the existence of the virtual volume.
        try:
            vol = self.client.getVolume(target_vol_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("Virtual volume '%s' doesn't exist on array.") %
                   target_vol_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        return int(math.ceil(float(vol['sizeMiB']) / units.Ki))

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        """Return size of snapshot to be managed by manage_existing_snapshot.

        existing_ref is a dictionary of the form:
        {'source-name': <name of the snapshot>}
        """
        target_snap_name = self._get_existing_volume_ref_name(existing_ref,
                                                              is_snapshot=True)

        # Make sure the reference is not in use.
        if re.match('osv-*|oss-*|vvs-*|unm-*', target_snap_name):
            reason = _("Reference must be for an unmanaged snapshot.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=target_snap_name,
                reason=reason)

        # Check for the existence of the snapshot.
        try:
            snap = self.client.getVolume(target_snap_name)
        except hpeexceptions.HTTPNotFound:
            err = (_("Snapshot '%s' doesn't exist on array.") %
                   target_snap_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        return int(math.ceil(float(snap['sizeMiB']) / units.Ki))

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management."""
        # Rename the volume's name to unm-* format so that it can be
        # easily found later.
        vol_name = self._get_3par_vol_name(volume['id'])
        new_vol_name = self._get_3par_unm_name(volume['id'])
        self.client.modifyVolume(vol_name, {'newName': new_vol_name})

        LOG.info("Virtual volume %(disp)s '%(vol)s' is no longer managed. "
                 "Volume renamed to '%(new)s'.",
                 {'disp': volume['display_name'],
                  'vol': vol_name,
                  'new': new_vol_name})

    def unmanage_snapshot(self, snapshot):
        """Removes the specified snapshot from Cinder management."""
        # Parent volume for the snapshot
        volume = snapshot['volume']

        # Do not allow unmanaging of snapshots from 'failed-over' volumes.
        if volume.get('replication_status') == 'failed-over':
            err = (_("Unmanaging of snapshots from failed-over volumes is "
                     "not allowed."))
            LOG.error(err)
            # TODO(leeantho) Change this exception to Invalid when the volume
            # manager supports handling that.
            raise exception.SnapshotIsBusy(snapshot_name=snapshot['id'])

        # Rename the snapshots's name to ums-* format so that it can be
        # easily found later.
        snap_name = self._get_3par_snap_name(snapshot['id'])
        new_snap_name = self._get_3par_ums_name(snapshot['id'])
        self.client.modifyVolume(snap_name, {'newName': new_snap_name})

        LOG.info("Snapshot %(disp)s '%(vol)s' is no longer managed. "
                 "Snapshot renamed to '%(new)s'.",
                 {'disp': snapshot['display_name'],
                  'vol': snap_name,
                  'new': new_snap_name})

    def _get_existing_volume_ref_name(self, existing_ref, is_snapshot=False):
        """Returns the volume name of an existing reference.

        Checks if an existing volume reference has a source-name or
        source-id element. If source-name or source-id is not present an
        error will be thrown.
        """
        vol_name = None
        if 'source-name' in existing_ref:
            vol_name = existing_ref['source-name']
        elif 'source-id' in existing_ref:
            if is_snapshot:
                vol_name = self._get_3par_ums_name(existing_ref['source-id'])
            else:
                vol_name = self._get_3par_unm_name(existing_ref['source-id'])
        else:
            reason = _("Reference must contain source-name or source-id.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason)

        return vol_name

    def _extend_volume(self, volume, volume_name, growth_size_mib,
                       _convert_to_base=False):
        model_update = None
        rcg_name = self._get_3par_rcg_name(volume['id'])
        is_volume_replicated = self._volume_of_replicated_type(volume)
        try:
            if _convert_to_base:
                LOG.debug("Converting to base volume prior to growing.")
                model_update = self._convert_to_base_volume(volume)
            # If the volume is replicated and we are not failed over,
            # remote copy has to be stopped before the volume can be extended.
            failed_over = volume.get("replication_status", None)
            is_failed_over = failed_over == "failed-over"
            if is_volume_replicated and not is_failed_over:
                self.client.stopRemoteCopy(rcg_name)
            self.client.growVolume(volume_name, growth_size_mib)
            if is_volume_replicated and not is_failed_over:
                self.client.startRemoteCopy(rcg_name)
        except Exception as ex:
            # If the extend fails, we must restart remote copy.
            if is_volume_replicated:
                self.client.startRemoteCopy(rcg_name)
            with excutils.save_and_reraise_exception() as ex_ctxt:
                if (not _convert_to_base and
                    isinstance(ex, hpeexceptions.HTTPForbidden) and
                        ex.get_code() == 150):
                    # Error code 150 means 'invalid operation: Cannot grow
                    # this type of volume'.
                    # Suppress raising this exception because we can
                    # resolve it by converting it into a base volume.
                    # Afterwards, extending the volume should succeed, or
                    # fail with a different exception/error code.
                    ex_ctxt.reraise = False
                    model_update = self._extend_volume(
                        volume, volume_name,
                        growth_size_mib,
                        _convert_to_base=True)
                else:
                    LOG.error("Error extending volume: %(vol)s. "
                              "Exception: %(ex)s",
                              {'vol': volume_name, 'ex': ex})
        return model_update

    def _get_3par_vol_name(self, volume_id, temp_vol=False):
        """Get converted 3PAR volume name.

        Converts the openstack volume id from
        ecffc30f-98cb-4cf5-85ee-d7309cc17cd2
        to
        osv-7P.DD5jLTPWF7tcwnMF80g

        We convert the 128 bits of the uuid into a 24character long
        base64 encoded string to ensure we don't exceed the maximum
        allowed 31 character name limit on 3Par

        We strip the padding '=' and replace + with .
        and / with -
        """
        volume_name = self._encode_name(volume_id)
        if temp_vol:
            # is this a temporary volume
            # this is done during migration
            prefix = "tsv-%s"
        else:
            prefix = "osv-%s"
        return prefix % volume_name

    def _get_3par_snap_name(self, snapshot_id, temp_snap=False):
        snapshot_name = self._encode_name(snapshot_id)
        if temp_snap:
            # is this a temporary snapshot
            # this is done during cloning
            prefix = "tss-%s"
        else:
            prefix = "oss-%s"
        return prefix % snapshot_name

    def _get_3par_ums_name(self, snapshot_id):
        ums_name = self._encode_name(snapshot_id)
        return "ums-%s" % ums_name

    def _get_3par_vvs_name(self, volume_id):
        vvs_name = self._encode_name(volume_id)
        return "vvs-%s" % vvs_name

    def _get_3par_unm_name(self, volume_id):
        unm_name = self._encode_name(volume_id)
        return "unm-%s" % unm_name

    # v2 replication conversion
    def _get_3par_rcg_name(self, volume_id):
        rcg_name = self._encode_name(volume_id)
        rcg = "rcg-%s" % rcg_name
        return rcg[:22]

    def _get_3par_remote_rcg_name(self, volume_id, provider_location):
        return self._get_3par_rcg_name(volume_id) + ".r" + (
            six.text_type(provider_location))

    def _encode_name(self, name):
        uuid_str = name.replace("-", "")
        vol_uuid = uuid.UUID('urn:uuid:%s' % uuid_str)
        vol_encoded = base64.encode_as_text(vol_uuid.bytes)

        # 3par doesn't allow +, nor /
        vol_encoded = vol_encoded.replace('+', '.')
        vol_encoded = vol_encoded.replace('/', '-')
        # strip off the == as 3par doesn't like those.
        vol_encoded = vol_encoded.replace('=', '')
        return vol_encoded

    def _capacity_from_size(self, vol_size):
        # because 3PAR volume sizes are in Mebibytes.
        if int(vol_size) == 0:
            capacity = units.Gi  # default: 1GiB
        else:
            capacity = vol_size * units.Gi

        capacity = int(math.ceil(capacity / units.Mi))
        return capacity

    def _delete_3par_host(self, hostname):
        self.client.deleteHost(hostname)

    def _get_prioritized_host_on_3par(self, host, hosts, hostname):
        # Check whether host with wwn/iqn of initiator present on 3par
        if hosts and hosts['members'] and 'name' in hosts['members'][0]:
            # Retrieving 'host' and 'hosts' from 3par using hostname
            # and wwn/iqn respectively. Compare hostname of 'host' and 'hosts',
            # if they do not match it means 3par has a pre-existing host
            # with some other name.
            if host['name'] != hosts['members'][0]['name']:
                hostname = hosts['members'][0]['name']
                LOG.info(("Prioritize the host retrieved from wwn/iqn "
                          "Hostname : %(hosts)s  is used instead "
                          "of Hostname: %(host)s"),
                         {'hosts': hostname,
                          'host': host['name']})
                host = self._get_3par_host(hostname)
                return host, hostname

        return host, hostname

    def _create_3par_vlun(self, volume, hostname, nsp, lun_id=None):
        try:
            location = None
            auto = True

            if lun_id is not None:
                auto = False

            if nsp is None:
                location = self.client.createVLUN(volume, hostname=hostname,
                                                  auto=auto, lun=lun_id)
            else:
                port = self.build_portPos(nsp)
                location = self.client.createVLUN(volume, hostname=hostname,
                                                  auto=auto, portPos=port,
                                                  lun=lun_id)

            vlun_info = None
            if location:
                # The LUN id is returned as part of the location URI
                vlun = location.split(',')
                vlun_info = {'volume_name': vlun[0],
                             'lun_id': int(vlun[1]),
                             'host_name': vlun[2],
                             }
                if len(vlun) > 3:
                    vlun_info['nsp'] = vlun[3]

            return vlun_info

        except hpeexceptions.HTTPBadRequest as e:
            if 'must be in the same domain' in e.get_description():
                LOG.error(e.get_description())
                raise exception.Invalid3PARDomain(err=e.get_description())
            else:
                raise exception.VolumeBackendAPIException(
                    data=e.get_description())

    def _safe_hostname(self, hostname):
        """We have to use a safe hostname length for 3PAR host names."""
        try:
            index = hostname.index('.')
        except ValueError:
            # couldn't find it
            index = len(hostname)

        # we'll just chop this off for now.
        if index > 31:
            index = 31

        return hostname[:index]

    def _get_3par_host(self, hostname):
        return self.client.getHost(hostname)

    def get_ports(self):
        return self.client.getPorts()

    def get_active_target_ports(self):
        ports = self.get_ports()
        target_ports = []
        for port in ports['members']:
            if (
                port['mode'] == self.client.PORT_MODE_TARGET and
                port['linkState'] == self.client.PORT_STATE_READY
            ):
                port['nsp'] = self.build_nsp(port['portPos'])
                target_ports.append(port)

        return target_ports

    def get_active_fc_target_ports(self):
        ports = self.get_active_target_ports()
        fc_ports = []
        for port in ports:
            if port['protocol'] == self.client.PORT_PROTO_FC:
                fc_ports.append(port)

        return fc_ports

    def get_active_iscsi_target_ports(self):
        ports = self.get_active_target_ports()
        iscsi_ports = []
        for port in ports:
            if port['protocol'] == self.client.PORT_PROTO_ISCSI:
                iscsi_ports.append(port)

        return iscsi_ports

    def get_volume_stats(self,
                         refresh,
                         filter_function=None,
                         goodness_function=None):
        if refresh:
            self._update_volume_stats(
                filter_function=filter_function,
                goodness_function=goodness_function)

        return self.stats

    def _update_volume_stats(self,
                             filter_function=None,
                             goodness_function=None):
        # const to convert MiB to GB
        const = 0.0009765625

        # storage_protocol and volume_backend_name are
        # set in the child classes

        pools = []
        info = self.client.getStorageSystemInfo()
        qos_support = True
        thin_support = True
        remotecopy_support = True
        sr_support = True
        compression_support = False
        if 'licenseInfo' in info:
            if 'licenses' in info['licenseInfo']:
                valid_licenses = info['licenseInfo']['licenses']
                qos_support = self._check_license_enabled(
                    valid_licenses, self.PRIORITY_OPT_LIC,
                    "QoS_support")
                thin_support = self._check_license_enabled(
                    valid_licenses, self.THIN_PROV_LIC,
                    "Thin_provisioning_support")
                remotecopy_support = self._check_license_enabled(
                    valid_licenses, self.REMOTE_COPY_LIC,
                    "Replication")
                sr_support = self._check_license_enabled(
                    valid_licenses, self.SYSTEM_REPORTER_LIC,
                    "System_reporter_support")
                compression_support = self._check_license_enabled(
                    valid_licenses, self.COMPRESSION_LIC,
                    "Compression")

        for cpg_name in self._client_conf['hpe3par_cpg']:
            try:
                stat_capabilities = {
                    THROUGHPUT: None,
                    BANDWIDTH: None,
                    LATENCY: None,
                    IO_SIZE: None,
                    QUEUE_LENGTH: None,
                    AVG_BUSY_PERC: None
                }
                cpg = self.client.getCPG(cpg_name)
                if (self.API_VERSION >= SRSTATLD_API_VERSION and sr_support):
                    interval = 'daily'
                    history = '7d'
                    try:
                        stat_capabilities = self.client.getCPGStatData(
                            cpg_name,
                            interval,
                            history)
                    except Exception as ex:
                        LOG.warning("Exception at getCPGStatData() "
                                    "for cpg: '%(cpg_name)s' "
                                    "Reason: '%(reason)s'",
                                    {'cpg_name': cpg_name, 'reason': ex})
                if 'numTDVVs' in cpg:
                    total_volumes = int(
                        cpg['numFPVVs'] + cpg['numTPVVs'] + cpg['numTDVVs']
                    )
                else:
                    total_volumes = int(
                        cpg['numFPVVs'] + cpg['numTPVVs']
                    )

                if 'limitMiB' not in cpg['SDGrowth']:
                    # cpg usable free space
                    cpg_avail_space = (
                        self.client.getCPGAvailableSpace(cpg_name))
                    free_capacity = int(
                        cpg_avail_space['usableFreeMiB'] * const)
                    # total_capacity is the best we can do for a limitless cpg
                    total_capacity = int(
                        (cpg['SDUsage']['usedMiB'] +
                         cpg['UsrUsage']['usedMiB'] +
                         cpg_avail_space['usableFreeMiB']) * const)
                else:
                    total_capacity = int(cpg['SDGrowth']['limitMiB'] * const)
                    free_capacity = int((cpg['SDGrowth']['limitMiB'] -
                                        (cpg['UsrUsage']['usedMiB'] +
                                         cpg['SDUsage']['usedMiB'])) * const)
                capacity_utilization = (
                    (float(total_capacity - free_capacity) /
                     float(total_capacity)) * 100)
                provisioned_capacity = int((cpg['UsrUsage']['totalMiB'] +
                                            cpg['SAUsage']['totalMiB'] +
                                            cpg['SDUsage']['totalMiB']) *
                                           const)

            except hpeexceptions.HTTPNotFound:
                err = (_("CPG (%s) doesn't exist on array")
                       % cpg_name)
                LOG.error(err)
                raise exception.InvalidInput(reason=err)

            pool = {'pool_name': cpg_name,
                    'total_capacity_gb': total_capacity,
                    'free_capacity_gb': free_capacity,
                    'provisioned_capacity_gb': provisioned_capacity,
                    'QoS_support': qos_support,
                    'thin_provisioning_support': thin_support,
                    'thick_provisioning_support': True,
                    'max_over_subscription_ratio': (
                        self.config.safe_get('max_over_subscription_ratio')),
                    'reserved_percentage': (
                        self.config.safe_get('reserved_percentage')),
                    'location_info': ('HPE3PARDriver:%(sys_id)s:%(dest_cpg)s' %
                                      {'sys_id': info['serialNumber'],
                                       'dest_cpg': cpg_name}),
                    'total_volumes': total_volumes,
                    'capacity_utilization': capacity_utilization,
                    THROUGHPUT: stat_capabilities[THROUGHPUT],
                    BANDWIDTH: stat_capabilities[BANDWIDTH],
                    LATENCY: stat_capabilities[LATENCY],
                    IO_SIZE: stat_capabilities[IO_SIZE],
                    QUEUE_LENGTH: stat_capabilities[QUEUE_LENGTH],
                    AVG_BUSY_PERC: stat_capabilities[AVG_BUSY_PERC],
                    'filter_function': filter_function,
                    'goodness_function': goodness_function,
                    'multiattach': False,
                    'consistent_group_snapshot_enabled': True,
                    'compression': compression_support,
                    }

            if remotecopy_support:
                pool['replication_enabled'] = self._replication_enabled
                pool['replication_type'] = ['sync', 'periodic']
                pool['replication_count'] = len(self._replication_targets)

            pools.append(pool)

        self.stats = {'driver_version': '3.0',
                      'storage_protocol': None,
                      'vendor_name': 'Hewlett Packard Enterprise',
                      'volume_backend_name': None,
                      'array_id': info['id'],
                      'replication_enabled': self._replication_enabled,
                      'replication_targets': self._get_replication_targets(),
                      'pools': pools}

    def _check_license_enabled(self, valid_licenses,
                               license_to_check, capability):
        """Check a license against valid licenses on the array."""
        if valid_licenses:
            for license in valid_licenses:
                if license_to_check in license.get('name'):
                    return True
            LOG.debug("'%(capability)s' requires a '%(license)s' "
                      "license which is not installed.",
                      {'capability': capability,
                       'license': license_to_check})
        return False

    def _get_vlun(self, volume_name, hostname, lun_id=None, nsp=None):
        """find a VLUN on a 3PAR host."""
        vluns = self.client.getHostVLUNs(hostname)
        found_vlun = None
        for vlun in vluns:
            if volume_name in vlun['volumeName']:
                if lun_id is not None:
                    if vlun['lun'] == lun_id:
                        if nsp:
                            port = self.build_portPos(nsp)
                            if vlun['portPos'] == port:
                                found_vlun = vlun
                                break
                        else:
                            found_vlun = vlun
                            break
                else:
                    found_vlun = vlun
                    break

        if found_vlun is None:
            LOG.info("3PAR vlun %(name)s not found on host %(host)s",
                     {'name': volume_name, 'host': hostname})
        return found_vlun

    def create_vlun(self, volume, host, nsp=None, lun_id=None):
        """Create a VLUN.

        In order to export a volume on a 3PAR box, we have to create a VLUN.
        """
        volume_name = self._get_3par_vol_name(volume['id'])
        vlun_info = self._create_3par_vlun(volume_name, host['name'], nsp,
                                           lun_id=lun_id)
        return self._get_vlun(volume_name,
                              host['name'],
                              vlun_info['lun_id'],
                              nsp)

    def delete_vlun(self, volume, hostname, wwn=None, iqn=None):
        volume_name = self._get_3par_vol_name(volume['id'])
        if hostname:
            vluns = self.client.getHostVLUNs(hostname)
        else:
            # In case of 'force detach', hostname is None
            vluns = self.client.getVLUNs()['members']

        # When deleteing VLUNs, you simply need to remove the template VLUN
        # and any active VLUNs will be automatically removed.  The template
        # VLUN are marked as active: False

        modify_host = True
        volume_vluns = []

        for vlun in vluns:
            if volume_name in vlun['volumeName']:
                # template VLUNs are 'active' = False
                if not vlun['active']:
                    volume_vluns.append(vlun)

        if not volume_vluns:
            LOG.warning("3PAR vlun for volume %(name)s not found on host "
                        "%(host)s", {'name': volume_name, 'host': hostname})
            return

        # VLUN Type of MATCHED_SET 4 requires the port to be provided
        for vlun in volume_vluns:
            if hostname is None:
                hostname = vlun.get('hostname')
            if 'portPos' in vlun:
                self.client.deleteVLUN(volume_name, vlun['lun'],
                                       hostname=hostname,
                                       port=vlun['portPos'])
            else:
                self.client.deleteVLUN(volume_name, vlun['lun'],
                                       hostname=hostname)

        # Determine if there are other volumes attached to the host.
        # This will determine whether we should try removing host from host set
        # and deleting the host.
        vluns = []
        try:
            vluns = self.client.getHostVLUNs(hostname)
        except hpeexceptions.HTTPNotFound:
            LOG.debug("All VLUNs removed from host %s", hostname)
            pass

        if wwn is not None and not isinstance(wwn, list):
            wwn = [wwn]
        if iqn is not None and not isinstance(iqn, list):
            iqn = [iqn]

        for vlun in vluns:
            if vlun.get('active'):
                if (wwn is not None and vlun.get('remoteName').lower() in wwn)\
                    or (iqn is not None and vlun.get('remoteName').lower() in
                        iqn):
                    # vlun with wwn/iqn exists so do not modify host.
                    modify_host = False
                    break

        if len(vluns) == 0:
            # We deleted the last vlun, so try to delete the host too.
            # This check avoids the old unnecessary try/fail when vluns exist
            # but adds a minor race condition if a vlun is manually deleted
            # externally at precisely the wrong time. Worst case is leftover
            # host, so it is worth the unlikely risk.

            try:
                # TODO(sonivi): since multiattach is not supported for now,
                # delete only single host, if its not exported to volume.
                self._delete_3par_host(hostname)
            except Exception as ex:
                # Any exception down here is only logged.  The vlun is deleted.

                # If the host is in a host set, the delete host will fail and
                # the host will remain in the host set.  This is desired
                # because cinder was not responsible for the host set
                # assignment.  The host set could be used outside of cinder
                # for future needs (e.g. export volume to host set).

                # The log info explains why the host was left alone.
                LOG.info("3PAR vlun for volume '%(name)s' was deleted, "
                         "but the host '%(host)s' was not deleted "
                         "because: %(reason)s",
                         {'name': volume_name, 'host': hostname,
                          'reason': ex.get_description()})
        elif modify_host:
            if wwn is not None:
                mod_request = {'pathOperation': self.client.HOST_EDIT_REMOVE,
                               'FCWWNs': wwn}
            else:
                mod_request = {'pathOperation': self.client.HOST_EDIT_REMOVE,
                               'iSCSINames': iqn}
            try:
                self.client.modifyHost(hostname, mod_request)
            except Exception as ex:
                LOG.info("3PAR vlun for volume '%(name)s' was deleted, "
                         "but the host '%(host)s' was not Modified "
                         "because: %(reason)s",
                         {'name': volume_name, 'host': hostname,
                          'reason': ex.get_description()})

    def _get_volume_type(self, type_id):
        ctxt = context.get_admin_context()
        return volume_types.get_volume_type(ctxt, type_id)

    def _get_key_value(self, hpe3par_keys, key, default=None):
        if hpe3par_keys is not None and key in hpe3par_keys:
            return hpe3par_keys[key]
        else:
            return default

    def _get_qos_value(self, qos, key, default=None):
        if key in qos:
            return qos[key]
        else:
            return default

    def _get_qos_by_volume_type(self, volume_type):
        qos = {}
        qos_specs_id = volume_type.get('qos_specs_id')
        specs = volume_type.get('extra_specs')

        # NOTE(kmartin): We prefer the qos_specs association
        # and override any existing extra-specs settings
        # if present.
        if qos_specs_id is not None:
            kvs = qos_specs.get_qos_specs(context.get_admin_context(),
                                          qos_specs_id)['specs']
        else:
            kvs = specs

        for key, value in kvs.items():
            if 'qos:' in key:
                fields = key.split(':')
                key = fields[1]
            if key in self.hpe_qos_keys:
                qos[key] = value
        return qos

    def _get_keys_by_volume_type(self, volume_type):
        hpe3par_keys = {}
        specs = volume_type.get('extra_specs')
        for key, value in specs.items():
            if ':' in key:
                fields = key.split(':')
                key = fields[1]
            if key in self.hpe3par_valid_keys:
                hpe3par_keys[key] = value
        return hpe3par_keys

    def _set_qos_rule(self, qos, vvs_name):
        min_io = self._get_qos_value(qos, 'minIOPS')
        max_io = self._get_qos_value(qos, 'maxIOPS')
        min_bw = self._get_qos_value(qos, 'minBWS')
        max_bw = self._get_qos_value(qos, 'maxBWS')
        latency = self._get_qos_value(qos, 'latency')
        priority = self._get_qos_value(qos, 'priority', 'normal')

        qosRule = {}
        if min_io:
            qosRule['ioMinGoal'] = int(min_io)
            if max_io is None:
                qosRule['ioMaxLimit'] = int(min_io)
        if max_io:
            qosRule['ioMaxLimit'] = int(max_io)
            if min_io is None:
                qosRule['ioMinGoal'] = int(max_io)
        if min_bw:
            qosRule['bwMinGoalKB'] = int(min_bw) * units.Ki
            if max_bw is None:
                qosRule['bwMaxLimitKB'] = int(min_bw) * units.Ki
        if max_bw:
            qosRule['bwMaxLimitKB'] = int(max_bw) * units.Ki
            if min_bw is None:
                qosRule['bwMinGoalKB'] = int(max_bw) * units.Ki
        if latency:
            qosRule['latencyGoal'] = int(latency)
        if priority:
            qosRule['priority'] = self.qos_priority_level.get(priority.lower())

        try:
            self.client.createQoSRules(vvs_name, qosRule)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error creating QOS rule %s", qosRule)

    def get_flash_cache_policy(self, hpe3par_keys):
        if hpe3par_keys is not None:
            # First check list of extra spec keys
            val = self._get_key_value(hpe3par_keys, 'flash_cache', None)
            if val is not None:
                # If requested, see if supported on back end
                if self.API_VERSION < FLASH_CACHE_API_VERSION:
                    err = (_("Flash Cache Policy requires "
                             "WSAPI version '%(fcache_version)s' "
                             "version '%(version)s' is installed.") %
                           {'fcache_version': FLASH_CACHE_API_VERSION,
                            'version': self.API_VERSION})
                    LOG.error(err)
                    raise exception.InvalidInput(reason=err)
                else:
                    if val.lower() == 'true':
                        return self.client.FLASH_CACHE_ENABLED
                    else:
                        return self.client.FLASH_CACHE_DISABLED

        return None

    def get_compression_policy(self, hpe3par_keys):
        if hpe3par_keys is not None:
            # here it should return true/false/None
            val = self._get_key_value(hpe3par_keys, 'compression', None)
            compression_support = False
        if val is not None:
            info = self.client.getStorageSystemInfo()
            if 'licenseInfo' in info:
                if 'licenses' in info['licenseInfo']:
                    valid_licenses = info['licenseInfo']['licenses']
                    compression_support = self._check_license_enabled(
                        valid_licenses, self.COMPRESSION_LIC,
                        "Compression")
            # here check the wsapi version
            if self.API_VERSION < COMPRESSION_API_VERSION:
                err = (_("Compression Policy requires "
                         "WSAPI version '%(compression_version)s' "
                         "version '%(version)s' is installed.") %
                       {'compression_version': COMPRESSION_API_VERSION,
                        'version': self.API_VERSION})
                LOG.error(err)
                raise exception.InvalidInput(reason=err)
            else:
                if val.lower() == 'true':
                    if not compression_support:
                        msg = _('Compression is not supported on '
                                'underlying hardware')
                        LOG.error(msg)
                        raise exception.InvalidInput(reason=msg)
                    return True
                else:
                    return False
        return None

    def _set_flash_cache_policy_in_vvs(self, flash_cache, vvs_name):
        # Update virtual volume set
        if flash_cache:
            try:
                self.client.modifyVolumeSet(vvs_name,
                                            flashCachePolicy=flash_cache)
                LOG.info("Flash Cache policy set to %s", flash_cache)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error("Error setting Flash Cache policy "
                              "to %s - exception", flash_cache)

    def _add_volume_to_volume_set(self, volume, volume_name,
                                  cpg, vvs_name, qos, flash_cache):
        if vvs_name is not None:
            # Admin has set a volume set name to add the volume to
            try:
                self.client.addVolumeToVolumeSet(vvs_name, volume_name)
            except hpeexceptions.HTTPNotFound:
                msg = _('VV Set %s does not exist.') % vvs_name
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)
        else:
            vvs_name = self._get_3par_vvs_name(volume['id'])
            domain = self.get_domain(cpg)
            self.client.createVolumeSet(vvs_name, domain)
            try:
                self._set_qos_rule(qos, vvs_name)
                self._set_flash_cache_policy_in_vvs(flash_cache, vvs_name)
                self.client.addVolumeToVolumeSet(vvs_name, volume_name)
            except Exception as ex:
                # Cleanup the volume set if unable to create the qos rule
                # or flash cache policy or add the volume to the volume set
                self.client.deleteVolumeSet(vvs_name)
                raise exception.CinderException(ex)

    def get_cpg(self, volume, allowSnap=False):
        volume_name = self._get_3par_vol_name(volume['id'])
        vol = self.client.getVolume(volume_name)
        # Search for 'userCPG' in the get volume REST API,
        # if found return userCPG , else search for snapCPG attribute
        # when allowSnap=True. For the cases where 3PAR REST call for
        # get volume doesn't have either userCPG or snapCPG ,
        # take the default value of cpg from 'host' attribute from volume param
        LOG.debug("get volume response is: %s", vol)
        if 'userCPG' in vol:
            return vol['userCPG']
        elif allowSnap and 'snapCPG' in vol:
            return vol['snapCPG']
        else:
            return volume_utils.extract_host(volume['host'], 'pool')

    def _get_3par_vol_comment(self, volume_name):
        vol = self.client.getVolume(volume_name)
        if 'comment' in vol:
            return vol['comment']
        return None

    def validate_persona(self, persona_value):
        """Validate persona value.

        If the passed in persona_value is not valid, raise InvalidInput,
        otherwise return the persona ID.

        :param persona_value:
        :raises exception.InvalidInput:
        :returns: persona ID
        """
        if persona_value not in self.valid_persona_values:
            err = (_("Must specify a valid persona %(valid)s,"
                     "value '%(persona)s' is invalid.") %
                   {'valid': self.valid_persona_values,
                   'persona': persona_value})
            LOG.error(err)
            raise exception.InvalidInput(reason=err)
        # persona is set by the id so remove the text and return the id
        # i.e for persona '1 - Generic' returns 1
        persona_id = persona_value.split(' ')
        return persona_id[0]

    def get_persona_type(self, volume, hpe3par_keys=None):
        default_persona = self.valid_persona_values[0]
        type_id = volume.get('volume_type_id', None)
        if type_id is not None:
            volume_type = self._get_volume_type(type_id)
            if hpe3par_keys is None:
                hpe3par_keys = self._get_keys_by_volume_type(volume_type)
        persona_value = self._get_key_value(hpe3par_keys, 'persona',
                                            default_persona)
        return self.validate_persona(persona_value)

    def get_type_info(self, type_id):
        """Get 3PAR type info for the given type_id.

        Reconciles VV Set, old-style extra-specs, and QOS specs
        and returns commonly used info about the type.

        :returns: hpe3par_keys, qos, volume_type, vvs_name
        """
        volume_type = None
        vvs_name = None
        hpe3par_keys = {}
        qos = {}
        if type_id is not None:
            volume_type = self._get_volume_type(type_id)
            hpe3par_keys = self._get_keys_by_volume_type(volume_type)
            vvs_name = self._get_key_value(hpe3par_keys, 'vvs')
            if vvs_name is None:
                qos = self._get_qos_by_volume_type(volume_type)
        return hpe3par_keys, qos, volume_type, vvs_name

    def get_volume_settings_from_type_id(self, type_id, pool):
        """Get 3PAR volume settings given a type_id.

        Combines type info and config settings to return a dictionary
        describing the 3PAR volume settings.  Does some validation (CPG).
        Uses pool as the default cpg (when not specified in volume type specs).

        :param type_id: id of type to get settings for
        :param pool: CPG to use if type does not have one set
        :returns: dict
        """

        hpe3par_keys, qos, volume_type, vvs_name = self.get_type_info(type_id)

        # Default to pool extracted from host.
        # If that doesn't work use the 1st CPG in the config as the default.
        default_cpg = pool or self._client_conf['hpe3par_cpg'][0]

        cpg = self._get_key_value(hpe3par_keys, 'cpg', default_cpg)
        if cpg is not default_cpg:
            # The cpg was specified in a volume type extra spec so it
            # needs to be validated that it's in the correct domain.
            # log warning here
            msg = ("'hpe3par:cpg' is not supported as an extra spec "
                   "in a volume type.  CPG's are chosen by "
                   "the cinder scheduler, as a pool, from the "
                   "cinder.conf entry 'hpe3par_cpg', which can "
                   "be a list of CPGs.")
            versionutils.report_deprecated_feature(LOG, msg)
            LOG.info("Using pool %(pool)s instead of %(cpg)s",
                     {'pool': pool, 'cpg': cpg})

            cpg = pool
            self.validate_cpg(cpg)
        # Look to see if the snap_cpg was specified in volume type
        # extra spec, if not use hpe3par_cpg_snap from config as the
        # default.
        snap_cpg = self.config.hpe3par_cpg_snap
        snap_cpg = self._get_key_value(hpe3par_keys, 'snap_cpg', snap_cpg)
        # If it's still not set or empty then set it to the cpg.
        if not snap_cpg:
            snap_cpg = cpg

        # if provisioning is not set use thin
        default_prov = self.valid_prov_values[0]
        prov_value = self._get_key_value(hpe3par_keys, 'provisioning',
                                         default_prov)
        # check for valid provisioning type
        if prov_value not in self.valid_prov_values:
            err = (_("Must specify a valid provisioning type %(valid)s, "
                     "value '%(prov)s' is invalid.") %
                   {'valid': self.valid_prov_values,
                    'prov': prov_value})
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        tpvv = True
        tdvv = False
        if prov_value == "full":
            tpvv = False
        elif prov_value == "dedup":
            tpvv = False
            tdvv = True

        if tdvv and (self.API_VERSION < DEDUP_API_VERSION):
            err = (_("Dedup is a valid provisioning type, "
                     "but requires WSAPI version '%(dedup_version)s' "
                     "version '%(version)s' is installed.") %
                   {'dedup_version': DEDUP_API_VERSION,
                    'version': self.API_VERSION})
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        return {'hpe3par_keys': hpe3par_keys,
                'cpg': cpg, 'snap_cpg': snap_cpg,
                'vvs_name': vvs_name, 'qos': qos,
                'tpvv': tpvv, 'tdvv': tdvv, 'volume_type': volume_type}

    def get_volume_settings_from_type(self, volume, host=None):
        """Get 3PAR volume settings given a volume.

        Combines type info and config settings to return a dictionary
        describing the 3PAR volume settings.  Does some validation (CPG and
        persona).

        :param volume:
        :param host: Optional host to use for default pool.
        :returns: dict
        """

        type_id = volume.get('volume_type_id', None)

        pool = None
        if host:
            pool = volume_utils.extract_host(host['host'], 'pool')
        else:
            pool = volume_utils.extract_host(volume['host'], 'pool')

        volume_settings = self.get_volume_settings_from_type_id(type_id, pool)

        # check for valid persona even if we don't use it until
        # attach time, this will give the end user notice that the
        # persona type is invalid at volume creation time
        self.get_persona_type(volume, volume_settings['hpe3par_keys'])

        return volume_settings

    def create_volume(self, volume):
        LOG.debug('CREATE VOLUME (%(disp_name)s: %(vol_name)s %(id)s on '
                  '%(host)s)',
                  {'disp_name': volume['display_name'],
                   'vol_name': volume['name'],
                   'id': self._get_3par_vol_name(volume['id']),
                   'host': volume['host']})
        try:
            comments = {'volume_id': volume['id'],
                        'name': volume['name'],
                        'type': 'OpenStack'}

            name = volume.get('display_name', None)
            if name:
                comments['display_name'] = name

            # get the options supported by volume types
            type_info = self.get_volume_settings_from_type(volume)
            volume_type = type_info['volume_type']
            vvs_name = type_info['vvs_name']
            qos = type_info['qos']
            cpg = type_info['cpg']
            snap_cpg = type_info['snap_cpg']
            tpvv = type_info['tpvv']
            tdvv = type_info['tdvv']
            flash_cache = self.get_flash_cache_policy(
                type_info['hpe3par_keys'])
            compression = self.get_compression_policy(
                type_info['hpe3par_keys'])

            consis_group_snap_type = False
            if volume_type is not None:
                extra_specs = volume_type.get('extra_specs', None)
                if extra_specs:
                    gsnap_val = extra_specs.get(
                        'consistent_group_snapshot_enabled', None)
                    if gsnap_val is not None and gsnap_val == "<is> True":
                        consis_group_snap_type = True

            cg_id = volume.get('group_id', None)
            if cg_id and consis_group_snap_type:
                vvs_name = self._get_3par_vvs_name(cg_id)

            type_id = volume.get('volume_type_id', None)
            if type_id is not None:
                comments['volume_type_name'] = volume_type.get('name')
                comments['volume_type_id'] = type_id
                if vvs_name is not None:
                    comments['vvs'] = vvs_name
                else:
                    comments['qos'] = qos

            extras = {'comment': json.dumps(comments),
                      'snapCPG': snap_cpg,
                      'tpvv': tpvv}

            # Only set the dedup option if the backend supports it.
            if self.API_VERSION >= DEDUP_API_VERSION:
                extras['tdvv'] = tdvv

            capacity = self._capacity_from_size(volume['size'])
            volume_name = self._get_3par_vol_name(volume['id'])

            if compression is not None:
                extras['compression'] = compression

            self.client.createVolume(volume_name, cpg, capacity, extras)
            if qos or vvs_name or flash_cache is not None:
                try:
                    self._add_volume_to_volume_set(volume, volume_name,
                                                   cpg, vvs_name, qos,
                                                   flash_cache)
                except exception.InvalidInput as ex:
                    # Delete the volume if unable to add it to the volume set
                    self.client.deleteVolume(volume_name)
                    LOG.error("Exception: %s", ex)
                    raise exception.CinderException(ex)

            # v2 replication check
            replication_flag = False
            if self._volume_of_replicated_type(volume) and (
               self._do_volume_replication_setup(volume)):
                replication_flag = True

        except hpeexceptions.HTTPConflict:
            msg = _("Volume (%s) already exists on array") % volume_name
            LOG.error(msg)
            raise exception.Duplicate(msg)
        except hpeexceptions.HTTPBadRequest as ex:
            LOG.error("Exception: %s", ex)
            raise exception.Invalid(ex.get_description())
        except exception.InvalidInput as ex:
            LOG.error("Exception: %s", ex)
            raise
        except exception.CinderException as ex:
            LOG.error("Exception: %s", ex)
            raise
        except Exception as ex:
            LOG.error("Exception: %s", ex)
            raise exception.CinderException(ex)

        return self._get_model_update(volume['host'], cpg,
                                      replication=replication_flag,
                                      provider_location=self.client.id)

    def _copy_volume(self, src_name, dest_name, cpg, snap_cpg=None,
                     tpvv=True, tdvv=False, compression=None):
        # Virtual volume sets are not supported with the -online option
        LOG.debug('Creating clone of a volume %(src)s to %(dest)s.',
                  {'src': src_name, 'dest': dest_name})

        optional = {'tpvv': tpvv, 'online': True}
        if snap_cpg is not None:
            optional['snapCPG'] = snap_cpg

        if self.API_VERSION >= DEDUP_API_VERSION:
            optional['tdvv'] = tdvv

        if (compression is not None and
                self.API_VERSION >= COMPRESSION_API_VERSION):
            optional['compression'] = compression

        body = self.client.copyVolume(src_name, dest_name, cpg, optional)
        return body['taskid']

    def get_next_word(self, s, search_string):
        """Return the next word.

        Search 's' for 'search_string', if found return the word preceding
        'search_string' from 's'.
        """
        word = re.search(search_string.strip(' ') + ' ([^ ]*)', s)
        return word.groups()[0].strip(' ')

    def _get_3par_vol_comment_value(self, vol_comment, key):
        comment_dict = dict(ast.literal_eval(vol_comment))
        if key in comment_dict:
            return comment_dict[key]
        return None

    def _get_model_update(self, volume_host, cpg, replication=False,
                          provider_location=None):
        """Get model_update dict to use when we select a pool.

        The pools implementation uses a volume['host'] suffix of :poolname.
        When the volume comes in with this selected pool, we sometimes use
        a different pool (e.g. because the type says to use a different pool).
        So in the several places that we do this, we need to return a model
        update so that the volume will have the actual pool name in the host
        suffix after the operation.

        Given a volume_host, which should (might) have the pool suffix, and
        given the CPG we actually chose to use, return a dict to use for a
        model update iff an update is needed.

        :param volume_host: The volume's host string.
        :param cpg: The actual pool (cpg) used, for example from the type.
        :returns: dict Model update if we need to update volume host, else None
        """
        model_update = {}
        host = volume_utils.extract_host(volume_host, 'backend')
        host_and_pool = volume_utils.append_host(host, cpg)
        if volume_host != host_and_pool:
            # Since we selected a pool based on type, update the model.
            model_update['host'] = host_and_pool
        if replication:
            model_update['replication_status'] = 'enabled'
        if replication and provider_location:
            model_update['provider_location'] = provider_location
        if not model_update:
            model_update = None
        return model_update

    def _create_temp_snapshot(self, volume):
        """This creates a temporary snapshot of a volume.

        This is used by cloning a volume so that we can then
        issue extend volume against the original volume.
        """
        vol_name = self._get_3par_vol_name(volume['id'])
        # create a brand new uuid for the temp snap
        snap_uuid = uuid.uuid4().hex

        # this will be named tss-%s
        snap_name = self._get_3par_snap_name(snap_uuid, temp_snap=True)

        extra = {'volume_name': volume['name'],
                 'volume_id': volume['id']}

        optional = {'comment': json.dumps(extra)}

        # let the snapshot die in an hour
        optional['expirationHours'] = 1

        LOG.info("Creating temp snapshot %(snap)s from volume %(vol)s",
                 {'snap': snap_name, 'vol': vol_name})

        self.client.createSnapshot(snap_name, vol_name, optional)
        return self.client.getVolume(snap_name)

    def create_cloned_volume(self, volume, src_vref):
        try:
            vol_name = self._get_3par_vol_name(volume['id'])
            src_vol_name = self._get_3par_vol_name(src_vref['id'])
            back_up_process = False
            vol_chap_enabled = False

            # Check whether a volume is ISCSI and CHAP enabled on it.
            if self._client_conf['hpe3par_iscsi_chap_enabled']:
                try:
                    vol_chap_enabled = self.client.getVolumeMetaData(
                        src_vol_name, 'HPQ-cinder-CHAP-name')['value']
                except hpeexceptions.HTTPNotFound:
                    LOG.debug("CHAP is not enabled on volume %(vol)s ",
                              {'vol': src_vref['id']})
                    vol_chap_enabled = False

            # Check whether a process is a backup
            if str(src_vref['status']) == 'backing-up':
                back_up_process = True

            # if the sizes of the 2 volumes are the same and except backup
            # process for ISCSI volume with chap enabled on it.
            # we can do an online copy, which is a background process
            # on the 3PAR that makes the volume instantly available.
            # We can't resize a volume, while it's being copied.
            if volume['size'] == src_vref['size'] and not (
               back_up_process and vol_chap_enabled):
                LOG.debug("Creating a clone of volume, using online copy.")

                type_info = self.get_volume_settings_from_type(volume)
                snapshot = self._create_temp_snapshot(src_vref)
                cpg = type_info['cpg']
                qos = type_info['qos']
                vvs_name = type_info['vvs_name']
                flash_cache = self.get_flash_cache_policy(
                    type_info['hpe3par_keys'])

                compression_val = self.get_compression_policy(
                    type_info['hpe3par_keys'])
                # make the 3PAR copy the contents.
                # can't delete the original until the copy is done.
                self._copy_volume(snapshot['name'], vol_name, cpg=cpg,
                                  snap_cpg=type_info['snap_cpg'],
                                  tpvv=type_info['tpvv'],
                                  tdvv=type_info['tdvv'],
                                  compression=compression_val)

                if qos or vvs_name or flash_cache is not None:
                    try:
                        self._add_volume_to_volume_set(
                            volume, vol_name, cpg, vvs_name, qos, flash_cache)
                    except exception.InvalidInput as ex:
                        # Delete volume if unable to add it to the volume set
                        self.client.deleteVolume(vol_name)
                        dbg = {'volume': vol_name,
                               'vvs_name': vvs_name,
                               'err': six.text_type(ex)}
                        msg = _("Failed to add volume '%(volume)s' to vvset "
                                "'%(vvs_name)s' because '%(err)s'") % dbg
                        LOG.error(msg)
                        raise exception.CinderException(msg)

                # v2 replication check
                replication_flag = False
                if self._volume_of_replicated_type(volume) and (
                   self._do_volume_replication_setup(volume)):
                    replication_flag = True

                return self._get_model_update(volume['host'], cpg,
                                              replication=replication_flag,
                                              provider_location=self.client.id)
            else:
                # The size of the new volume is different, so we have to
                # copy the volume and wait.  Do the resize after the copy
                # is complete.
                LOG.debug("Creating a clone of volume, using non-online copy.")

                # we first have to create the destination volume
                model_update = self.create_volume(volume)

                optional = {'priority': 1}
                body = self.client.copyVolume(src_vol_name, vol_name, None,
                                              optional=optional)
                task_id = body['taskid']

                task_status = self._wait_for_task_completion(task_id)
                if task_status['status'] is not self.client.TASK_DONE:
                    dbg = {'status': task_status, 'id': volume['id']}
                    msg = _('Copy volume task failed: create_cloned_volume '
                            'id=%(id)s, status=%(status)s.') % dbg
                    raise exception.CinderException(msg)
                else:
                    LOG.debug('Copy volume completed: create_cloned_volume: '
                              'id=%s.', volume['id'])

                return model_update

        except hpeexceptions.HTTPForbidden:
            raise exception.NotAuthorized()
        except hpeexceptions.HTTPNotFound:
            raise exception.NotFound()
        except Exception as ex:
            LOG.error("Exception: %s", ex)
            raise exception.CinderException(ex)

    def delete_volume(self, volume):
        # v2 replication check
        # If the volume type is replication enabled, we want to call our own
        # method of deconstructing the volume and its dependencies
        if self._volume_of_replicated_type(volume):
            replication_status = volume.get('replication_status', None)
            if replication_status and replication_status == "failed-over":
                self._delete_replicated_failed_over_volume(volume)
            else:
                self._do_volume_replication_destroy(volume)
            return

        try:
            volume_name = self._get_3par_vol_name(volume['id'])
            # Try and delete the volume, it might fail here because
            # the volume is part of a volume set which will have the
            # volume set name in the error.
            try:
                self.client.deleteVolume(volume_name)
            except hpeexceptions.HTTPBadRequest as ex:
                if ex.get_code() == 29:
                    if self.client.isOnlinePhysicalCopy(volume_name):
                        LOG.debug("Found an online copy for %(volume)s",
                                  {'volume': volume_name})
                        # the volume is in process of being cloned.
                        # stopOnlinePhysicalCopy will also delete
                        # the volume once it stops the copy.
                        self.client.stopOnlinePhysicalCopy(volume_name)
                    else:
                        LOG.error("Exception: %s", ex)
                        raise
                else:
                    LOG.error("Exception: %s", ex)
                    raise
            except hpeexceptions.HTTPConflict as ex:
                if ex.get_code() == 34:
                    # This is a special case which means the
                    # volume is part of a volume set.
                    self._delete_vvset(volume)
                    self.client.deleteVolume(volume_name)
                elif ex.get_code() == 151:
                    if self.client.isOnlinePhysicalCopy(volume_name):
                        LOG.debug("Found an online copy for %(volume)s",
                                  {'volume': volume_name})
                        # the volume is in process of being cloned.
                        # stopOnlinePhysicalCopy will also delete
                        # the volume once it stops the copy.
                        self.client.stopOnlinePhysicalCopy(volume_name)
                    else:
                        # the volume is being operated on in a background
                        # task on the 3PAR.
                        # TODO(walter-boring) do a retry a few times.
                        # for now lets log a better message
                        msg = _("The volume is currently busy on the 3PAR"
                                " and cannot be deleted at this time. "
                                "You can try again later.")
                        LOG.error(msg)
                        raise exception.VolumeIsBusy(message=msg)
                elif (ex.get_code() == 32):
                    # Error 32 means that the volume has children

                    # see if we have any temp snapshots
                    snaps = self.client.getVolumeSnapshots(volume_name)
                    for snap in snaps:
                        if snap.startswith('tss-'):
                            # looks like we found a temp snapshot.
                            LOG.info(
                                "Found a temporary snapshot %(name)s",
                                {'name': snap})
                            try:
                                self.client.deleteVolume(snap)
                            except hpeexceptions.HTTPNotFound:
                                # if the volume is gone, it's as good as a
                                # successful delete
                                pass
                            except Exception:
                                msg = _("Volume has a temporary snapshot that "
                                        "can't be deleted at this time.")
                                raise exception.VolumeIsBusy(message=msg)

                    try:
                        self.delete_volume(volume)
                    except Exception:
                        msg = _("Volume has children and cannot be deleted!")
                        raise exception.VolumeIsBusy(message=msg)
                else:
                    LOG.error("Exception: %s", ex)
                    raise exception.VolumeIsBusy(message=ex.get_description())

        except hpeexceptions.HTTPNotFound as ex:
            # We'll let this act as if it worked
            # it helps clean up the cinder entries.
            LOG.warning("Delete volume id not found. Removing from "
                        "cinder: %(id)s Ex: %(msg)s",
                        {'id': volume['id'], 'msg': ex})
        except hpeexceptions.HTTPForbidden as ex:
            LOG.error("Exception: %s", ex)
            raise exception.NotAuthorized(ex.get_description())
        except hpeexceptions.HTTPConflict as ex:
            LOG.error("Exception: %s", ex)
            raise exception.VolumeIsBusy(message=ex.get_description())
        except Exception as ex:
            LOG.error("Exception: %s", ex)
            raise exception.CinderException(ex)

    def create_volume_from_snapshot(self, volume, snapshot, snap_name=None,
                                    vvs_name=None):
        """Creates a volume from a snapshot."""
        LOG.debug("Create Volume from Snapshot\n%(vol_name)s\n%(ss_name)s",
                  {'vol_name': pprint.pformat(volume['display_name']),
                   'ss_name': pprint.pformat(snapshot['display_name'])})

        model_update = {}
        if volume['size'] < snapshot['volume_size']:
            err = ("You cannot reduce size of the volume.  It must "
                   "be greater than or equal to the snapshot.")
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        try:
            if not snap_name:
                snap_name = self._get_3par_snap_name(snapshot['id'])
            volume_name = self._get_3par_vol_name(volume['id'])

            extra = {'volume_id': volume['id'],
                     'snapshot_id': snapshot['id']}

            type_id = volume.get('volume_type_id', None)

            hpe3par_keys, qos, _volume_type, vvs = self.get_type_info(
                type_id)
            if vvs:
                vvs_name = vvs

            name = volume.get('display_name', None)
            if name:
                extra['display_name'] = name

            description = volume.get('display_description', None)
            if description:
                extra['description'] = description

            optional = {'comment': json.dumps(extra),
                        'readOnly': False}

            self.client.createSnapshot(volume_name, snap_name, optional)

            # Convert snapshot volume to base volume type
            LOG.debug('Converting to base volume type: %s.',
                      volume['id'])
            model_update = self._convert_to_base_volume(volume)

            # Grow the snapshot if needed
            growth_size = volume['size'] - snapshot['volume_size']
            if growth_size > 0:
                try:
                    growth_size_mib = growth_size * units.Gi / units.Mi
                    LOG.debug('Growing volume: %(id)s by %(size)s GiB.',
                              {'id': volume['id'], 'size': growth_size})
                    self.client.growVolume(volume_name, growth_size_mib)
                except Exception as ex:
                    LOG.error("Error extending volume %(id)s. "
                              "Ex: %(ex)s",
                              {'id': volume['id'], 'ex': ex})
                    # Delete the volume if unable to grow it
                    self.client.deleteVolume(volume_name)
                    raise exception.CinderException(ex)

            # Check for flash cache setting in extra specs
            flash_cache = self.get_flash_cache_policy(hpe3par_keys)

            if qos or vvs_name or flash_cache is not None:
                cpg_names = self._get_key_value(
                    hpe3par_keys, 'cpg', self._client_conf['hpe3par_cpg'])
                try:
                    self._add_volume_to_volume_set(volume, volume_name,
                                                   cpg_names[0], vvs_name,
                                                   qos, flash_cache)
                except Exception as ex:
                    # Delete the volume if unable to add it to the volume set
                    self.client.deleteVolume(volume_name)
                    LOG.error("Exception: %s", ex)
                    raise exception.CinderException(ex)

            # v2 replication check
            if self._volume_of_replicated_type(volume) and (
               self._do_volume_replication_setup(volume)):
                model_update['replication_status'] = 'enabled'
                model_update['provider_location'] = self.client.id

        except hpeexceptions.HTTPForbidden as ex:
            LOG.error("Exception: %s", ex)
            raise exception.NotAuthorized()
        except hpeexceptions.HTTPNotFound as ex:
            LOG.error("Exception: %s", ex)
            raise exception.NotFound()
        except Exception as ex:
            LOG.error("Exception: %s", ex)
            raise exception.CinderException(ex)
        return model_update

    def create_snapshot(self, snapshot):
        LOG.debug("Create Snapshot\n%s", pprint.pformat(snapshot))

        try:
            snap_name = self._get_3par_snap_name(snapshot['id'])
            vol_name = self._get_3par_vol_name(snapshot['volume_id'])

            extra = {'volume_name': snapshot['volume_name']}
            vol_id = snapshot.get('volume_id', None)
            if vol_id:
                extra['volume_id'] = vol_id

            try:
                extra['display_name'] = snapshot['display_name']
            except AttributeError:
                pass

            try:
                extra['description'] = snapshot['display_description']
            except AttributeError:
                pass

            optional = {'comment': json.dumps(extra),
                        'readOnly': True}
            if self.config.hpe3par_snapshot_expiration:
                optional['expirationHours'] = (
                    int(self.config.hpe3par_snapshot_expiration))

            if self.config.hpe3par_snapshot_retention:
                optional['retentionHours'] = (
                    int(self.config.hpe3par_snapshot_retention))

            self.client.createSnapshot(snap_name, vol_name, optional)
        except hpeexceptions.HTTPForbidden as ex:
            LOG.error("Exception: %s", ex)
            raise exception.NotAuthorized()
        except hpeexceptions.HTTPNotFound as ex:
            LOG.error("Exception: %s", ex)
            raise exception.NotFound()

    def migrate_volume(self, volume, host):
        """Migrate directly if source and dest are managed by same storage.

        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        :returns: (False, None) if the driver does not support migration,
                 (True, model_update) if successful

        """

        dbg = {'id': volume['id'],
               'host': host['host'],
               'status': volume['status']}
        LOG.debug('enter: migrate_volume: id=%(id)s, host=%(host)s, '
                  'status=%(status)s.', dbg)
        ret = False, None

        if volume['status'] in ['available', 'in-use']:
            volume_type = None
            if volume['volume_type_id']:
                volume_type = self._get_volume_type(volume['volume_type_id'])

            try:
                ret = self.retype(volume, volume_type, None, host)
            except Exception as e:
                LOG.info('3PAR driver cannot perform migration. '
                         'Retype exception: %s', e)

        LOG.debug('leave: migrate_volume: id=%(id)s, host=%(host)s, '
                  'status=%(status)s.', dbg)
        dbg_ret = {'supported': ret[0], 'model_update': ret[1]}
        LOG.debug('migrate_volume result: %(supported)s, %(model_update)s',
                  dbg_ret)
        return ret

    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        """Rename the new (temp) volume to it's original name.


        This method tries to rename the new volume to it's original
        name after the migration has completed.

        """
        LOG.debug("Update volume name for %(id)s", {'id': new_volume['id']})
        name_id = None
        provider_location = None
        if original_volume_status == 'available':
            # volume isn't attached and can be updated
            original_name = self._get_3par_vol_name(volume['id'])
            temp_name = self._get_3par_vol_name(volume['id'], temp_vol=True)
            current_name = self._get_3par_vol_name(new_volume['id'])
            try:
                volumeMods = {'newName': original_name}
                volumeTempMods = {'newName': temp_name}
                volumeCurrentMods = {'newName': current_name}
                # swap volume name in backend
                self.client.modifyVolume(original_name, volumeTempMods)
                self.client.modifyVolume(current_name, volumeMods)
                self.client.modifyVolume(temp_name, volumeCurrentMods)
                LOG.info("Volume name changed from %(tmp)s to %(orig)s",
                         {'tmp': current_name, 'orig': original_name})
            except Exception as e:
                LOG.error("Changing the volume name from %(tmp)s to "
                          "%(orig)s failed because %(reason)s",
                          {'tmp': current_name, 'orig': original_name,
                           'reason': e})
                name_id = new_volume['_name_id'] or new_volume['id']
                provider_location = new_volume['provider_location']
        else:
            # the backend can't change the name.
            name_id = new_volume['_name_id'] or new_volume['id']
            provider_location = new_volume['provider_location']

        return {'_name_id': name_id, 'provider_location': provider_location}

    def _wait_for_task_completion(self, task_id):
        """This waits for a 3PAR background task complete or fail.

        This looks for a task to get out of the 'active' state.
        """
        # Wait for the physical copy task to complete
        def _wait_for_task(task_id):
            status = self.client.getTask(task_id)
            LOG.debug("3PAR Task id %(id)s status = %(status)s",
                      {'id': task_id,
                       'status': status['status']})
            if status['status'] is not self.client.TASK_ACTIVE:
                self._task_status = status
                raise loopingcall.LoopingCallDone()

        self._task_status = None
        timer = loopingcall.FixedIntervalLoopingCall(
            _wait_for_task, task_id)
        timer.start(interval=1).wait()

        return self._task_status

    def _convert_to_base_volume(self, volume, new_cpg=None):
        try:
            type_info = self.get_volume_settings_from_type(volume)
            if new_cpg:
                cpg = new_cpg
            else:
                cpg = type_info['cpg']

            # Change the name such that it is unique since 3PAR
            # names must be unique across all CPGs
            volume_name = self._get_3par_vol_name(volume['id'])
            temp_vol_name = volume_name.replace("osv-", "omv-")

            compression = self.get_compression_policy(
                type_info['hpe3par_keys'])
            # Create a physical copy of the volume
            task_id = self._copy_volume(volume_name, temp_vol_name,
                                        cpg, cpg, type_info['tpvv'],
                                        type_info['tdvv'],
                                        compression)

            LOG.debug('Copy volume scheduled: convert_to_base_volume: '
                      'id=%s.', volume['id'])

            task_status = self._wait_for_task_completion(task_id)

            if task_status['status'] is not self.client.TASK_DONE:
                dbg = {'status': task_status, 'id': volume['id']}
                msg = _('Copy volume task failed: convert_to_base_volume: '
                        'id=%(id)s, status=%(status)s.') % dbg
                raise exception.CinderException(msg)
            else:
                LOG.debug('Copy volume completed: convert_to_base_volume: '
                          'id=%s.', volume['id'])

            comment = self._get_3par_vol_comment(volume_name)
            if comment:
                self.client.modifyVolume(temp_vol_name, {'comment': comment})
            LOG.debug('Volume rename completed: convert_to_base_volume: '
                      'id=%s.', volume['id'])

            # Delete source volume after the copy is complete
            self.client.deleteVolume(volume_name)
            LOG.debug('Delete src volume completed: convert_to_base_volume: '
                      'id=%s.', volume['id'])

            # Rename the new volume to the original name
            self.client.modifyVolume(temp_vol_name, {'newName': volume_name})

            LOG.info('Completed: convert_to_base_volume: '
                     'id=%s.', volume['id'])
        except hpeexceptions.HTTPConflict:
            msg = _("Volume (%s) already exists on array.") % volume_name
            LOG.error(msg)
            raise exception.Duplicate(msg)
        except hpeexceptions.HTTPBadRequest as ex:
            LOG.error("Exception: %s", ex)
            raise exception.Invalid(ex.get_description())
        except exception.CinderException as ex:
            LOG.error("Exception: %s", ex)
            raise
        except Exception as ex:
            LOG.error("Exception: %s", ex)
            raise exception.CinderException(ex)

        return self._get_model_update(volume['host'], cpg)

    def delete_snapshot(self, snapshot):
        LOG.debug("Delete Snapshot id %(id)s %(name)s",
                  {'id': snapshot['id'], 'name': pprint.pformat(snapshot)})

        try:
            snap_name = self._get_3par_snap_name(snapshot['id'])
            self.client.deleteVolume(snap_name)
        except hpeexceptions.HTTPForbidden as ex:
            LOG.error("Exception: %s", ex)
            raise exception.NotAuthorized()
        except hpeexceptions.HTTPNotFound as ex:
            # We'll let this act as if it worked
            # it helps clean up the cinder entries.
            LOG.warning("Delete Snapshot id not found. Removing from "
                        "cinder: %(id)s Ex: %(msg)s",
                        {'id': snapshot['id'], 'msg': ex})
        except hpeexceptions.HTTPConflict as ex:
            if (ex.get_code() == 32):
                # Error 32 means that the snapshot has children
                # see if we have any temp snapshots
                snaps = self.client.getVolumeSnapshots(snap_name)
                for snap in snaps:
                    if snap.startswith('tss-'):
                        LOG.info(
                            "Found a temporary snapshot %(name)s",
                            {'name': snap})
                        try:
                            self.client.deleteVolume(snap)
                        except hpeexceptions.HTTPNotFound:
                            # if the volume is gone, it's as good as a
                            # successful delete
                            pass
                        except Exception:
                            msg = _("Snapshot has a temporary snapshot that "
                                    "can't be deleted at this time.")
                            raise exception.SnapshotIsBusy(message=msg)

                try:
                    self.client.deleteVolume(snap_name)
                except Exception:
                    msg = _("Snapshot has children and cannot be deleted!")
                    raise exception.SnapshotIsBusy(message=msg)
            else:
                LOG.error("Exception: %s", ex)
                raise exception.SnapshotIsBusy(message=ex.get_description())

    def _get_3par_hostname_from_wwn_iqn(self, wwns, iqns):
        if wwns is not None and not isinstance(wwns, list):
            wwns = [wwns]
        if iqns is not None and not isinstance(iqns, list):
            iqns = [iqns]

        out = self.client.getHosts()
        hosts = out['members']
        for host in hosts:
            if 'iSCSIPaths' in host and iqns is not None:
                iscsi_paths = host['iSCSIPaths']
                for iscsi in iscsi_paths:
                    for iqn in iqns:
                        if iqn == iscsi['name']:
                            return host['name']

            if 'FCPaths' in host and wwns is not None:
                fc_paths = host['FCPaths']
                for fc in fc_paths:
                    for wwn in wwns:
                        if wwn.upper() == fc['wwn'].upper():
                            return host['name']

    def terminate_connection(self, volume, hostname, wwn=None, iqn=None):
        """Driver entry point to unattach a volume from an instance."""
        # does 3par know this host by a different name?
        hosts = None
        if wwn:
            hosts = self.client.queryHost(wwns=wwn)
        elif iqn:
            hosts = self.client.queryHost(iqns=[iqn])

        if hosts is not None:
            if hosts and hosts['members'] and 'name' in hosts['members'][0]:
                hostname = hosts['members'][0]['name']

        try:
            self.delete_vlun(volume, hostname, wwn=wwn, iqn=iqn)
            return
        except hpeexceptions.HTTPNotFound as e:
            if 'host does not exist' in e.get_description():
                # If a host is failed-over, we want to allow the detach to
                # 'succeed' when it cannot find the host. We can simply
                # return out of the terminate connection in order for things
                # to be updated correctly.
                if self._active_backend_id:
                    LOG.warning("Because the host is currently in a "
                                "failed-over state, the volume will not "
                                "be properly detached from the primary "
                                "array. The detach will be considered a "
                                "success as far as Cinder is concerned. "
                                "The volume can now be attached to the "
                                "secondary target.")
                    return
                else:
                    if hosts is None:
                        # In case of 'force detach', hosts is None
                        LOG.error("Exception: %s", e)
                        raise
                    else:
                        # use the wwn to see if we can find the hostname
                        hostname = self._get_3par_hostname_from_wwn_iqn(
                            wwn,
                            iqn)
                        # no 3par host, re-throw
                        if hostname is None:
                            LOG.error("Exception: %s", e)
                            raise
            else:
                # not a 'host does not exist' HTTPNotFound exception, re-throw
                LOG.error("Exception: %s", e)
                raise

        # try again with name retrieved from 3par
        self.delete_vlun(volume, hostname, wwn=wwn, iqn=iqn)

    def build_nsp(self, portPos):
        return '%s:%s:%s' % (portPos['node'],
                             portPos['slot'],
                             portPos['cardPort'])

    def build_portPos(self, nsp):
        split = nsp.split(":")
        portPos = {}
        portPos['node'] = int(split[0])
        portPos['slot'] = int(split[1])
        portPos['cardPort'] = int(split[2])
        return portPos

    def tune_vv(self, old_tpvv, new_tpvv, old_tdvv, new_tdvv,
                old_cpg, new_cpg, volume_name, new_compression):
        """Tune the volume to change the userCPG and/or provisioningType.

        The volume will be modified/tuned/converted to the new userCPG and
        provisioningType, as needed.

        TaskWaiter is used to make this function wait until the 3PAR task
        is no longer active.  When the task is no longer active, then it must
        either be done or it is in a state that we need to treat as an error.
        """

        compression = False
        if new_compression is not None:
            compression = new_compression

        if old_tpvv == new_tpvv and old_tdvv == new_tdvv:
            if new_cpg != old_cpg:
                LOG.info("Modifying %(volume_name)s userCPG "
                         "from %(old_cpg)s"
                         " to %(new_cpg)s",
                         {'volume_name': volume_name,
                          'old_cpg': old_cpg, 'new_cpg': new_cpg})
                _response, body = self.client.modifyVolume(
                    volume_name,
                    {'action': 6,
                     'tuneOperation': 1,
                     'userCPG': new_cpg})
                task_id = body['taskid']
                status = self.TaskWaiter(self.client, task_id).wait_for_task()
                if status['status'] is not self.client.TASK_DONE:
                    msg = (_('Tune volume task stopped before it was done: '
                             'volume_name=%(volume_name)s, '
                             'task-status=%(status)s.') %
                           {'status': status, 'volume_name': volume_name})
                    raise exception.VolumeBackendAPIException(msg)
        else:
            if new_tpvv:
                cop = self.CONVERT_TO_THIN
                LOG.info("Converting %(volume_name)s to thin provisioning "
                         "with userCPG=%(new_cpg)s",
                         {'volume_name': volume_name, 'new_cpg': new_cpg})
            elif new_tdvv:
                cop = self.CONVERT_TO_DEDUP
                LOG.info("Converting %(volume_name)s to thin dedup "
                         "provisioning with userCPG=%(new_cpg)s",
                         {'volume_name': volume_name, 'new_cpg': new_cpg})
            else:
                cop = self.CONVERT_TO_FULL
                LOG.info("Converting %(volume_name)s to full provisioning "
                         "with userCPG=%(new_cpg)s",
                         {'volume_name': volume_name, 'new_cpg': new_cpg})

            try:
                if self.API_VERSION < COMPRESSION_API_VERSION:
                    response, body = self.client.modifyVolume(
                        volume_name,
                        {'action': 6,
                         'tuneOperation': 1,
                         'userCPG': new_cpg,
                         'conversionOperation': cop})
                else:
                    response, body = self.client.modifyVolume(
                        volume_name,
                        {'action': 6,
                         'tuneOperation': 1,
                         'userCPG': new_cpg,
                         'compression': compression,
                         'conversionOperation': cop})
            except hpeexceptions.HTTPBadRequest as ex:
                if ex.get_code() == 40 and "keepVV" in six.text_type(ex):
                    # Cannot retype with snapshots because we don't want to
                    # use keepVV and have straggling volumes.  Log additional
                    # info and then raise.
                    LOG.info("tunevv failed because the volume '%s' "
                             "has snapshots.", volume_name)
                    raise

            task_id = body['taskid']
            status = self.TaskWaiter(self.client, task_id).wait_for_task()
            if status['status'] is not self.client.TASK_DONE:
                msg = (_('Tune volume task stopped before it was done: '
                         'volume_name=%(volume_name)s, '
                         'task-status=%(status)s.') %
                       {'status': status, 'volume_name': volume_name})
                raise exception.VolumeBackendAPIException(msg)

    def _retype_pre_checks(self, volume, host, new_persona,
                           old_cpg, new_cpg,
                           new_snap_cpg):
        """Test retype parameters before making retype changes.

        Do pre-retype parameter validation.  These checks will
        raise an exception if we should not attempt this retype.
        """

        if new_persona:
            self.validate_persona(new_persona)

        if host is not None:
            (host_type, host_id, _host_cpg) = (
                host['capabilities']['location_info']).split(':')

            if not (host_type == 'HPE3PARDriver'):
                reason = (_("Cannot retype from HPE3PARDriver to %s.") %
                          host_type)
                raise exception.InvalidHost(reason)

            sys_info = self.client.getStorageSystemInfo()
            if not (host_id == sys_info['serialNumber']):
                reason = (_("Cannot retype from one 3PAR array to another."))
                raise exception.InvalidHost(reason)

        # Validate new_snap_cpg.  A white-space snapCPG will fail eventually,
        # but we'd prefer to fail fast -- if this ever happens.
        if not new_snap_cpg or new_snap_cpg.isspace():
            reason = (_("Invalid new snapCPG name for retype.  "
                        "new_snap_cpg='%s'.") % new_snap_cpg)
            raise exception.InvalidInput(reason)

        # Check to make sure CPGs are in the same domain
        domain = self.get_domain(old_cpg)
        if domain != self.get_domain(new_cpg):
            reason = (_('Cannot retype to a CPG in a different domain.'))
            raise exception.Invalid3PARDomain(reason)

        if domain != self.get_domain(new_snap_cpg):
            reason = (_('Cannot retype to a snap CPG in a different domain.'))
            raise exception.Invalid3PARDomain(reason)

    def _retype(self, volume, volume_name, new_type_name, new_type_id, host,
                new_persona, old_cpg, new_cpg, old_snap_cpg, new_snap_cpg,
                old_tpvv, new_tpvv, old_tdvv, new_tdvv,
                old_vvs, new_vvs, old_qos, new_qos,
                old_flash_cache, new_flash_cache,
                old_comment, new_compression):

        action = "volume:retype"

        self._retype_pre_checks(volume, host, new_persona,
                                old_cpg, new_cpg,
                                new_snap_cpg)

        flow_name = action.replace(":", "_") + "_api"
        retype_flow = linear_flow.Flow(flow_name)
        # Keep this linear and do the big tunevv last.  Everything leading
        # up to that is reversible, but we'd let the 3PAR deal with tunevv
        # errors on its own.
        retype_flow.add(
            ModifyVolumeTask(action),
            ModifySpecsTask(action),
            TuneVolumeTask(action),
            ReplicateVolumeTask(action))

        taskflow.engines.run(
            retype_flow,
            store={'common': self,
                   'volume_name': volume_name, 'volume': volume,
                   'old_tpvv': old_tpvv, 'new_tpvv': new_tpvv,
                   'old_tdvv': old_tdvv, 'new_tdvv': new_tdvv,
                   'old_cpg': old_cpg, 'new_cpg': new_cpg,
                   'old_snap_cpg': old_snap_cpg, 'new_snap_cpg': new_snap_cpg,
                   'old_vvs': old_vvs, 'new_vvs': new_vvs,
                   'old_qos': old_qos, 'new_qos': new_qos,
                   'old_flash_cache': old_flash_cache,
                   'new_flash_cache': new_flash_cache,
                   'new_type_name': new_type_name, 'new_type_id': new_type_id,
                   'old_comment': old_comment,
                   'new_compression': new_compression
                   })

    def _retype_from_old_to_new(self, volume, new_type, old_volume_settings,
                                host):
        """Convert the volume to be of the new type.  Given old type settings.

        Returns True if the retype was successful.
        Uses taskflow to revert changes if errors occur.

        :param volume: A dictionary describing the volume to retype
        :param new_type: A dictionary describing the volume type to convert to
        :param old_volume_settings: Volume settings describing the old type.
        :param host: A dictionary describing the host, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.  Host validation
                     is just skipped if host is None.
        """
        volume_id = volume['id']
        volume_name = self._get_3par_vol_name(volume_id)
        new_type_name = None
        new_type_id = None
        if new_type:
            new_type_name = new_type['name']
            new_type_id = new_type['id']
        pool = None
        if host:
            pool = volume_utils.extract_host(host['host'], 'pool')
        else:
            pool = volume_utils.extract_host(volume['host'], 'pool')
        new_volume_settings = self.get_volume_settings_from_type_id(
            new_type_id, pool)
        new_cpg = new_volume_settings['cpg']
        new_snap_cpg = new_volume_settings['snap_cpg']
        new_tpvv = new_volume_settings['tpvv']
        new_tdvv = new_volume_settings['tdvv']
        new_qos = new_volume_settings['qos']
        new_vvs = new_volume_settings['vvs_name']
        new_persona = None
        new_hpe3par_keys = new_volume_settings['hpe3par_keys']
        if 'persona' in new_hpe3par_keys:
            new_persona = new_hpe3par_keys['persona']
        new_flash_cache = self.get_flash_cache_policy(new_hpe3par_keys)

        # it will return None / True /False$
        new_compression = self.get_compression_policy(new_hpe3par_keys)

        old_qos = old_volume_settings['qos']
        old_vvs = old_volume_settings['vvs_name']
        old_hpe3par_keys = old_volume_settings['hpe3par_keys']
        old_flash_cache = self.get_flash_cache_policy(old_hpe3par_keys)

        # Get the current volume info because we can get in a bad state
        # if we trust that all the volume type settings are still the
        # same settings that were used with this volume.
        old_volume_info = self.client.getVolume(volume_name)
        old_tpvv = old_volume_info['provisioningType'] == self.THIN
        old_tdvv = old_volume_info['provisioningType'] == self.DEDUP
        old_cpg = old_volume_info['userCPG']
        old_comment = old_volume_info['comment']
        old_snap_cpg = None
        if 'snapCPG' in old_volume_info:
            old_snap_cpg = old_volume_info['snapCPG']

        LOG.debug("retype old_volume_info=%s", old_volume_info)
        LOG.debug("retype old_volume_settings=%s", old_volume_settings)
        LOG.debug("retype new_volume_settings=%s", new_volume_settings)

        self._retype(volume, volume_name, new_type_name, new_type_id,
                     host, new_persona, old_cpg, new_cpg,
                     old_snap_cpg, new_snap_cpg, old_tpvv, new_tpvv,
                     old_tdvv, new_tdvv, old_vvs, new_vvs,
                     old_qos, new_qos, old_flash_cache, new_flash_cache,
                     old_comment, new_compression)

        if host:
            return True, self._get_model_update(host['host'], new_cpg)
        else:
            return True, self._get_model_update(volume['host'], new_cpg)

    def _retype_from_no_type(self, volume, new_type):
        """Convert the volume to be of the new type.  Starting from no type.

        Returns True if the retype was successful.
        Uses taskflow to revert changes if errors occur.

        :param volume: A dictionary describing the volume to retype. Except the
                       volume-type is not used here. This method uses None.
        :param new_type: A dictionary describing the volume type to convert to
        """
        pool = volume_utils.extract_host(volume['host'], 'pool')
        none_type_settings = self.get_volume_settings_from_type_id(None, pool)
        return self._retype_from_old_to_new(volume, new_type,
                                            none_type_settings, None)

    def retype(self, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns True if the retype was successful.
        Uses taskflow to revert changes if errors occur.

        :param volume: A dictionary describing the volume to retype
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.  Host validation
                     is just skipped if host is None.
        """
        LOG.debug(("enter: retype: id=%(id)s, new_type=%(new_type)s,"
                   "diff=%(diff)s, host=%(host)s"), {'id': volume['id'],
                                                     'new_type': new_type,
                                                     'diff': diff,
                                                     'host': host})
        self.remove_temporary_snapshots(volume)
        old_volume_settings = self.get_volume_settings_from_type(volume, host)
        return self._retype_from_old_to_new(volume, new_type,
                                            old_volume_settings, host)

    def remove_temporary_snapshots(self, volume):
        vol_name = self._get_3par_vol_name(volume['id'])
        snapshots_list = self.client.getVolumeSnapshots(vol_name)
        tmp_snapshots_list = [snap
                              for snap in snapshots_list
                              if snap.startswith('tss-')]
        LOG.debug("temporary snapshot list %(name)s",
                  {'name': tmp_snapshots_list})
        for temp_snap in tmp_snapshots_list:
            LOG.debug("Found a temporary snapshot %(name)s",
                      {'name': temp_snap})
            try:
                self.client.deleteVolume(temp_snap)
            except hpeexceptions.HTTPNotFound:
                # if the volume is gone, it's as good as a
                # successful delete
                pass
            except Exception:
                msg = _("Volume has a temporary snapshot.")
                raise exception.VolumeIsBusy(message=msg)

    def find_existing_vlun(self, volume, host):
        """Finds an existing VLUN for a volume on a host.

        Returns an existing VLUN's information. If no existing VLUN is found,
        None is returned.

        :param volume: A dictionary describing a volume.
        :param host: A dictionary describing a host.
        """
        existing_vlun = None
        try:
            vol_name = self._get_3par_vol_name(volume['id'])
            host_vluns = self.client.getHostVLUNs(host['name'])

            # The first existing VLUN found will be returned.
            for vlun in host_vluns:
                if vlun['volumeName'] == vol_name:
                    existing_vlun = vlun
                    break
        except hpeexceptions.HTTPNotFound:
            # ignore, no existing VLUNs were found
            LOG.debug("No existing VLUNs were found for host/volume "
                      "combination: %(host)s, %(vol)s",
                      {'host': host['name'],
                       'vol': vol_name})
            pass
        return existing_vlun

    def find_existing_vluns(self, volume, host):
        existing_vluns = []
        try:
            vol_name = self._get_3par_vol_name(volume['id'])
            host_vluns = self.client.getHostVLUNs(host['name'])

            for vlun in host_vluns:
                if vlun['volumeName'] == vol_name:
                    existing_vluns.append(vlun)
        except hpeexceptions.HTTPNotFound:
            # ignore, no existing VLUNs were found
            LOG.debug("No existing VLUNs were found for host/volume "
                      "combination: %(host)s, %(vol)s",
                      {'host': host['name'],
                       'vol': vol_name})
            pass
        return existing_vluns

    # v2 replication methods
    def failover_host(self, context, volumes, secondary_backend_id):
        """Force failover to a secondary replication target."""
        # Ensure replication is enabled before we try and failover.
        if not self._replication_enabled:
            msg = _("Issuing a fail-over failed because replication is "
                    "not properly configured.")
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        # Check to see if the user requested to failback.
        if (secondary_backend_id and
                secondary_backend_id == self.FAILBACK_VALUE):
            volume_update_list = self._replication_failback(volumes)
            target_id = None
        else:
            # Find the failover target.
            failover_target = None
            for target in self._replication_targets:
                if target['backend_id'] == secondary_backend_id:
                    failover_target = target
                    break
            if not failover_target:
                msg = _("A valid secondary target MUST be specified in order "
                        "to failover.")
                LOG.error(msg)
                raise exception.InvalidReplicationTarget(reason=msg)

            target_id = failover_target['backend_id']
            # For each volume, if it is replicated, we want to fail it over.
            volume_update_list = []
            for volume in volumes:
                if self._volume_of_replicated_type(volume):
                    try:
                        # Try and stop remote-copy on main array. We eat the
                        # exception here because when an array goes down, the
                        # groups will stop automatically.
                        rcg_name = self._get_3par_rcg_name(volume['id'])
                        self.client.stopRemoteCopy(rcg_name)
                    except Exception:
                        pass

                    try:
                        # Failover to secondary array.
                        remote_rcg_name = self._get_3par_remote_rcg_name(
                            volume['id'], volume['provider_location'])
                        cl = self._create_replication_client(failover_target)
                        cl.recoverRemoteCopyGroupFromDisaster(
                            remote_rcg_name, self.RC_ACTION_CHANGE_TO_PRIMARY)
                        volume_update_list.append(
                            {'volume_id': volume['id'],
                             'updates': {'replication_status': 'failed-over'}})
                    except Exception as ex:
                        LOG.error("There was a problem with the failover "
                                  "(%(error)s) and it was unsuccessful. "
                                  "Volume '%(volume)s will not be available "
                                  "on the failed over target.",
                                  {'error': ex,
                                   'volume': volume['id']})
                        LOG.error(msg)
                        volume_update_list.append(
                            {'volume_id': volume['id'],
                             'updates': {'replication_status': 'error'}})
                    finally:
                        self._destroy_replication_client(cl)
                else:
                    # If the volume is not of replicated type, we need to
                    # force the status into error state so a user knows they
                    # do not have access to the volume.
                    volume_update_list.append(
                        {'volume_id': volume['id'],
                         'updates': {'status': 'error'}})

        return target_id, volume_update_list

    def _replication_failback(self, volumes):
        # Make sure the proper steps on the backend have been completed before
        # we allow a fail-over.
        if not self._is_host_ready_for_failback(volumes):
            msg = _("The host is not ready to be failed back. Please "
                    "resynchronize the volumes and resume replication on the "
                    "3PAR backends.")
            LOG.error(msg)
            raise exception.InvalidReplicationTarget(reason=msg)

        # Update the volumes status to available.
        volume_update_list = []
        for volume in volumes:
            if self._volume_of_replicated_type(volume):
                volume_update_list.append(
                    {'volume_id': volume['id'],
                     'updates': {'replication_status': 'available'}})
            else:
                # Upon failing back, we can move the non-replicated volumes
                # back into available state.
                volume_update_list.append(
                    {'volume_id': volume['id'],
                     'updates': {'status': 'available'}})

        return volume_update_list

    def _is_host_ready_for_failback(self, volumes):
        """Checks to make sure the volume has been synchronized

        This ensures that all the remote copy targets have been restored
        to their natural direction, and all of the volumes have been
        fully synchronized.
        """
        try:
            for volume in volumes:
                if self._volume_of_replicated_type(volume):
                    location = volume.get('provider_location')
                    remote_rcg_name = self._get_3par_remote_rcg_name(
                        volume['id'],
                        location)
                    rcg = self.client.getRemoteCopyGroup(remote_rcg_name)

                    # Make sure all targets are in their natural direction.
                    targets = rcg['targets']
                    for target in targets:
                        if target['roleReversed'] or (
                           target['state'] != self.RC_GROUP_STARTED):
                            return False

                    # Make sure all volumes are fully synced.
                    volumes = rcg['volumes']
                    for volume in volumes:
                        remote_volumes = volume['remoteVolumes']
                        for remote_volume in remote_volumes:
                            if remote_volume['syncStatus'] != (
                               self.SYNC_STATUS_COMPLETED):
                                return False
        except Exception:
            # If there was a problem, we will return false so we can
            # log an error in the parent function.
            return False

        return True

    def _do_replication_setup(self):
        replication_targets = []
        replication_devices = self.config.replication_device
        if replication_devices:
            for dev in replication_devices:
                remote_array = dict(dev.items())
                # Override and set defaults for certain entries
                remote_array['managed_backend_name'] = (
                    dev.get('managed_backend_name'))
                remote_array['replication_mode'] = (
                    self._get_remote_copy_mode_num(
                        dev.get('replication_mode')))
                remote_array['san_ssh_port'] = (
                    dev.get('san_ssh_port', self.config.san_ssh_port))
                remote_array['ssh_conn_timeout'] = (
                    dev.get('ssh_conn_timeout', self.config.ssh_conn_timeout))
                remote_array['san_private_key'] = (
                    dev.get('san_private_key', self.config.san_private_key))
                # Format iscsi IPs correctly
                iscsi_ips = dev.get('hpe3par_iscsi_ips')
                if iscsi_ips:
                    remote_array['hpe3par_iscsi_ips'] = iscsi_ips.split(' ')
                # Format hpe3par_iscsi_chap_enabled as a bool
                remote_array['hpe3par_iscsi_chap_enabled'] = (
                    dev.get('hpe3par_iscsi_chap_enabled') == 'True')
                array_name = remote_array['backend_id']

                # Make sure we can log into the array, that it has been
                # correctly configured, and its API version meets the
                # minimum requirement.
                cl = None
                try:
                    cl = self._create_replication_client(remote_array)
                    array_id = six.text_type(cl.getStorageSystemInfo()['id'])
                    remote_array['id'] = array_id
                    wsapi_version = cl.getWsApiVersion()['build']

                    if wsapi_version < REMOTE_COPY_API_VERSION:
                        LOG.warning("The secondary array must have an API "
                                    "version of %(min_ver)s or higher. Array "
                                    "'%(target)s' is on %(target_ver)s, "
                                    "therefore it will not be added as a "
                                    "valid replication target.",
                                    {'target': array_name,
                                     'min_ver': REMOTE_COPY_API_VERSION,
                                     'target_ver': wsapi_version})
                    elif not self._is_valid_replication_array(remote_array):
                        LOG.warning("'%s' is not a valid replication array. "
                                    "In order to be valid, backend_id, "
                                    "replication_mode, "
                                    "hpe3par_api_url, hpe3par_username, "
                                    "hpe3par_password, cpg_map, san_ip, "
                                    "san_login, and san_password "
                                    "must be specified. If the target is "
                                    "managed, managed_backend_name must be "
                                    "set as well.", array_name)
                    else:
                        replication_targets.append(remote_array)
                except Exception:
                    LOG.error("Could not log in to 3PAR array (%s) with the "
                              "provided credentials.", array_name)
                finally:
                    self._destroy_replication_client(cl)

            self._replication_targets = replication_targets
            if self._is_replication_configured_correct():
                self._replication_enabled = True

    def _is_valid_replication_array(self, target):
        required_flags = ['hpe3par_api_url', 'hpe3par_username',
                          'hpe3par_password', 'san_ip', 'san_login',
                          'san_password', 'backend_id',
                          'replication_mode', 'cpg_map']
        try:
            self.check_replication_flags(target, required_flags)
            return True
        except Exception:
            return False

    def _is_replication_configured_correct(self):
        rep_flag = True
        # Make sure there is at least one replication target.
        if len(self._replication_targets) < 1:
            LOG.error("There must be at least one valid replication "
                      "device configured.")
            rep_flag = False
        return rep_flag

    def _is_replication_mode_correct(self, mode, sync_num):
        rep_flag = True
        # Make sure replication_mode is set to either sync|periodic.
        mode = self._get_remote_copy_mode_num(mode)
        if not mode:
            LOG.error("Extra spec replication:mode must be set and must "
                      "be either 'sync' or 'periodic'.")
            rep_flag = False
        else:
            # If replication:mode is periodic, replication_sync_period must be
            # set between 300 - 31622400 seconds.
            if mode == self.PERIODIC and (
               sync_num < 300 or sync_num > 31622400):
                LOG.error("Extra spec replication:sync_period must be "
                          "greater than 299 and less than 31622401 "
                          "seconds.")
                rep_flag = False
        return rep_flag

    def is_volume_group_snap_type(self, volume_type):
        consis_group_snap_type = False
        if volume_type:
            extra_specs = volume_type.extra_specs
            if 'consistent_group_snapshot_enabled' in extra_specs:
                gsnap_val = extra_specs['consistent_group_snapshot_enabled']
                consis_group_snap_type = (gsnap_val == "<is> True")
        return consis_group_snap_type

    def _volume_of_replicated_type(self, volume):
        replicated_type = False
        volume_type_id = volume.get('volume_type_id')
        if volume_type_id:
            volume_type = self._get_volume_type(volume_type_id)

            extra_specs = volume_type.get('extra_specs')
            if extra_specs and 'replication_enabled' in extra_specs:
                rep_val = extra_specs['replication_enabled']
                replicated_type = (rep_val == "<is> True")

        return replicated_type

    def _is_volume_in_remote_copy_group(self, volume):
        rcg_name = self._get_3par_rcg_name(volume['id'])
        try:
            self.client.getRemoteCopyGroup(rcg_name)
            return True
        except hpeexceptions.HTTPNotFound:
            return False

    def _get_remote_copy_mode_num(self, mode):
        ret_mode = None
        if mode == "sync":
            ret_mode = self.SYNC
        if mode == "periodic":
            ret_mode = self.PERIODIC
        return ret_mode

    def _get_3par_config(self):
        self._do_replication_setup()
        conf = None
        if self._replication_enabled:
            for target in self._replication_targets:
                if target['backend_id'] == self._active_backend_id:
                    conf = target
                    break
        self._build_3par_config(conf)

    def _build_3par_config(self, conf=None):
        """Build 3PAR client config dictionary.

        self._client_conf will contain values from self.config if the volume
        is located on the primary array in order to properly contact it. If
        the volume has been failed over and therefore on a secondary array,
        self._client_conf will contain values on how to contact that array.
        The only time we will return with entries from a secondary array is
        with unmanaged replication.
        """
        if conf:
            self._client_conf['hpe3par_cpg'] = self._generate_hpe3par_cpgs(
                conf.get('cpg_map'))
            self._client_conf['hpe3par_username'] = (
                conf.get('hpe3par_username'))
            self._client_conf['hpe3par_password'] = (
                conf.get('hpe3par_password'))
            self._client_conf['san_ip'] = conf.get('san_ip')
            self._client_conf['san_login'] = conf.get('san_login')
            self._client_conf['san_password'] = conf.get('san_password')
            self._client_conf['san_ssh_port'] = conf.get('san_ssh_port')
            self._client_conf['ssh_conn_timeout'] = (
                conf.get('ssh_conn_timeout'))
            self._client_conf['san_private_key'] = conf.get('san_private_key')
            self._client_conf['hpe3par_api_url'] = conf.get('hpe3par_api_url')
            self._client_conf['hpe3par_iscsi_ips'] = (
                conf.get('hpe3par_iscsi_ips'))
            self._client_conf['hpe3par_iscsi_chap_enabled'] = (
                conf.get('hpe3par_iscsi_chap_enabled'))
            self._client_conf['iscsi_ip_address'] = (
                conf.get('iscsi_ip_address'))
            self._client_conf['iscsi_port'] = conf.get('iscsi_port')
        else:
            self._client_conf['hpe3par_cpg'] = (
                self.config.hpe3par_cpg)
            self._client_conf['hpe3par_username'] = (
                self.config.hpe3par_username)
            self._client_conf['hpe3par_password'] = (
                self.config.hpe3par_password)
            self._client_conf['san_ip'] = self.config.san_ip
            self._client_conf['san_login'] = self.config.san_login
            self._client_conf['san_password'] = self.config.san_password
            self._client_conf['san_ssh_port'] = self.config.san_ssh_port
            self._client_conf['ssh_conn_timeout'] = (
                self.config.ssh_conn_timeout)
            self._client_conf['san_private_key'] = self.config.san_private_key
            self._client_conf['hpe3par_api_url'] = self.config.hpe3par_api_url
            self._client_conf['hpe3par_iscsi_ips'] = (
                self.config.hpe3par_iscsi_ips)
            self._client_conf['hpe3par_iscsi_chap_enabled'] = (
                self.config.hpe3par_iscsi_chap_enabled)
            self._client_conf['iscsi_ip_address'] = (
                self.config.iscsi_ip_address)
            self._client_conf['iscsi_port'] = self.config.iscsi_port

    def _get_cpg_from_cpg_map(self, cpg_map, target_cpg):
        ret_target_cpg = None
        cpg_pairs = cpg_map.split(' ')
        for cpg_pair in cpg_pairs:
            cpgs = cpg_pair.split(':')
            cpg = cpgs[0]
            dest_cpg = cpgs[1]
            if cpg == target_cpg:
                ret_target_cpg = dest_cpg

        return ret_target_cpg

    def _generate_hpe3par_cpgs(self, cpg_map):
        hpe3par_cpgs = []
        cpg_pairs = cpg_map.split(' ')
        for cpg_pair in cpg_pairs:
            cpgs = cpg_pair.split(':')
            hpe3par_cpgs.append(cpgs[1])

        return hpe3par_cpgs

    def _get_replication_targets(self):
        replication_targets = []
        for target in self._replication_targets:
            replication_targets.append(target['backend_id'])

        return replication_targets

    def _do_volume_replication_setup(self, volume, retype=False,
                                     dist_type_id=None):
        """This function will do or ensure the following:

        -Create volume on main array (already done in create_volume)
        -Create Remote Copy Group on main array
        -Add volume to Remote Copy Group on main array
        -Start remote copy

        If anything here fails, we will need to clean everything up in
        reverse order, including the original volume.
        """

        rcg_name = self._get_3par_rcg_name(volume['id'])
        # If the volume is already in a remote copy group, return True
        # after starting remote copy. If remote copy is already started,
        # issuing this command again will be fine.
        if self._is_volume_in_remote_copy_group(volume):
            try:
                self.client.startRemoteCopy(rcg_name)
            except Exception:
                pass
            return True

        try:
            # Grab the extra_spec entries for replication and make sure they
            # are set correctly.
            volume_type = self._get_volume_type(volume["volume_type_id"])
            if retype and dist_type_id is not None:
                dist_type = self._get_volume_type(dist_type_id)
                extra_specs = dist_type.get("extra_specs")
            else:
                extra_specs = volume_type.get("extra_specs")
            replication_mode = extra_specs.get(
                self.EXTRA_SPEC_REP_MODE, self.DEFAULT_REP_MODE)
            replication_mode_num = self._get_remote_copy_mode_num(
                replication_mode)
            replication_sync_period = extra_specs.get(
                self.EXTRA_SPEC_REP_SYNC_PERIOD, self.DEFAULT_SYNC_PERIOD)
            if replication_sync_period:
                replication_sync_period = int(replication_sync_period)
            if not self._is_replication_mode_correct(replication_mode,
                                                     replication_sync_period):
                msg = _("The replication mode was not configured correctly "
                        "in the volume type extra_specs. If replication:mode "
                        "is periodic, replication:sync_period must also be "
                        "specified and be between 300 and 31622400 seconds.")
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            vol_settings = self.get_volume_settings_from_type(volume)
            local_cpg = vol_settings['cpg']
            vol_name = self._get_3par_vol_name(volume['id'])

            # Create remote copy group on main array.
            rcg_targets = []
            sync_targets = []
            for target in self._replication_targets:
                # Only add targets that match the volumes replication mode.
                if target['replication_mode'] == replication_mode_num:
                    cpg = self._get_cpg_from_cpg_map(target['cpg_map'],
                                                     local_cpg)
                    rcg_target = {'targetName': target['backend_id'],
                                  'mode': replication_mode_num,
                                  'snapCPG': cpg,
                                  'userCPG': cpg}
                    rcg_targets.append(rcg_target)
                    sync_target = {'targetName': target['backend_id'],
                                   'syncPeriod': replication_sync_period}
                    sync_targets.append(sync_target)

            optional = {'localSnapCPG': vol_settings['snap_cpg'],
                        'localUserCPG': local_cpg}
            pool = volume_utils.extract_host(volume['host'], level='pool')
            domain = self.get_domain(pool)
            if domain:
                optional["domain"] = domain
            try:
                self.client.createRemoteCopyGroup(rcg_name, rcg_targets,
                                                  optional)
            except Exception as ex:
                msg = (_("There was an error creating the remote copy "
                         "group: %s.") %
                       six.text_type(ex))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # Add volume to remote copy group.
            rcg_targets = []
            for target in self._replication_targets:
                # Only add targets that match the volumes replication mode.
                if target['replication_mode'] == replication_mode_num:
                    rcg_target = {'targetName': target['backend_id'],
                                  'secVolumeName': vol_name}
                    rcg_targets.append(rcg_target)
            optional = {'volumeAutoCreation': True}
            try:
                self.client.addVolumeToRemoteCopyGroup(rcg_name, vol_name,
                                                       rcg_targets,
                                                       optional=optional)
            except Exception as ex:
                msg = (_("There was an error adding the volume to the remote "
                         "copy group: %s.") %
                       six.text_type(ex))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            # Check and see if we are in periodic mode. If we are, update
            # Remote Copy Group to have a sync period.
            if replication_sync_period and (
               replication_mode_num == self.PERIODIC):
                opt = {'targets': sync_targets}
                try:
                    self.client.modifyRemoteCopyGroup(rcg_name, opt)
                except Exception as ex:
                    msg = (_("There was an error setting the sync period for "
                             "the remote copy group: %s.") %
                           six.text_type(ex))
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)

            # Start the remote copy.
            try:
                self.client.startRemoteCopy(rcg_name)
            except Exception as ex:
                msg = (_("There was an error starting remote copy: %s.") %
                       six.text_type(ex))
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

            return True
        except Exception as ex:
            self._do_volume_replication_destroy(volume)
            msg = (_("There was an error setting up a remote copy group "
                     "on the 3PAR arrays: ('%s'). The volume will not be "
                     "recognized as replication type.") %
                   six.text_type(ex))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _do_volume_replication_destroy(self, volume, rcg_name=None,
                                       retype=False):
        """This will completely remove all traces of a remote copy group.

        It should be used when deleting a replication enabled volume
        or if setting up a remote copy group fails. It will try and do the
        following:
        -Stop remote copy
        -Remove volume from Remote Copy Group on main array
        -Delete Remote Copy Group from main array
        -Delete volume from main array
        """
        if not rcg_name:
            rcg_name = self._get_3par_rcg_name(volume['id'])
        vol_name = self._get_3par_vol_name(volume['id'])

        # Stop remote copy.
        try:
            self.client.stopRemoteCopy(rcg_name)
        except Exception:
            pass

        # Delete volume from remote copy group on main array.
        try:
            self.client.removeVolumeFromRemoteCopyGroup(
                rcg_name, vol_name, removeFromTarget=True)
        except Exception:
            pass

        # Delete remote copy group on main array.
        try:
            self.client.removeRemoteCopyGroup(rcg_name)
        except Exception:
            pass

        # Delete volume on the main array.
        try:
            if not retype:
                self.client.deleteVolume(vol_name)
        except hpeexceptions.HTTPConflict as ex:
                if ex.get_code() == 34:
                    # This is a special case which means the
                    # volume is part of a volume set.
                    self._delete_vvset(volume)
                    self.client.deleteVolume(vol_name)
        except Exception:
            pass

    def _delete_replicated_failed_over_volume(self, volume):
        location = volume.get('provider_location')
        rcg_name = self._get_3par_remote_rcg_name(volume['id'], location)
        targets = self.client.getRemoteCopyGroup(rcg_name)['targets']
        # When failed over, we want to temporarily disable config mirroring
        # in order to be allowed to delete the volume and remote copy group
        for target in targets:
            target_name = target['targetName']
            self.client.toggleRemoteCopyConfigMirror(target_name,
                                                     mirror_config=False)

        # Do regular volume replication destroy now config mirroring is off
        try:
            self._do_volume_replication_destroy(volume, rcg_name)
        except Exception as ex:
            msg = (_("The failed-over volume could not be deleted: %s") %
                   six.text_type(ex))
            LOG.error(msg)
            raise exception.VolumeIsBusy(message=msg)
        finally:
            # Turn config mirroring back on
            for target in targets:
                target_name = target['targetName']
                self.client.toggleRemoteCopyConfigMirror(target_name,
                                                         mirror_config=True)

    def _delete_vvset(self, volume):

        # volume is part of a volume set.
        volume_name = self._get_3par_vol_name(volume['id'])
        vvset_name = self.client.findVolumeSet(volume_name)
        LOG.debug("Returned vvset_name = %s", vvset_name)
        if vvset_name is not None:
            if vvset_name.startswith('vvs-'):
                # We have a single volume per volume set, so
                # remove the volume set.
                self.client.deleteVolumeSet(
                    self._get_3par_vvs_name(volume['id']))
            else:
                # We have a pre-defined volume set just remove the
                # volume and leave the volume set.
                self.client.removeVolumeFromVolumeSet(vvset_name,
                                                      volume_name)

    class TaskWaiter(object):
        """TaskWaiter waits for task to be not active and returns status."""

        def __init__(self, client, task_id, interval=1, initial_delay=0):
            self.client = client
            self.task_id = task_id
            self.interval = interval
            self.initial_delay = initial_delay

        def _wait_for_task(self):
            status = self.client.getTask(self.task_id)
            LOG.debug("3PAR Task id %(id)s status = %(status)s",
                      {'id': self.task_id,
                       'status': status['status']})
            if status['status'] is not self.client.TASK_ACTIVE:
                raise loopingcall.LoopingCallDone(status)

        def wait_for_task(self):
            timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_task)
            return timer.start(interval=self.interval,
                               initial_delay=self.initial_delay).wait()


class ReplicateVolumeTask(flow_utils.CinderTask):

    """Task to replicate a volume.

    This is a task for adding/removing the replication feature to volume.
    It is intended for use during retype(). This task has no revert.
    # TODO(sumit): revert back to original volume extra-spec
    """

    def __init__(self, action, **kwargs):
        super(ReplicateVolumeTask, self).__init__(addons=[action])

    def execute(self, common, volume, new_type_id):

        new_replicated_type = False

        if new_type_id:
            new_volume_type = common._get_volume_type(new_type_id)

            extra_specs = new_volume_type.get('extra_specs', None)
            if extra_specs and 'replication_enabled' in extra_specs:
                rep_val = extra_specs['replication_enabled']
                new_replicated_type = (rep_val == "<is> True")

        if common._volume_of_replicated_type(volume) and new_replicated_type:
            # Retype from replication enabled to replication enable.
            common._do_volume_replication_destroy(volume, retype=True)
            common._do_volume_replication_setup(
                volume,
                retype=True,
                dist_type_id=new_type_id)
        elif (not common._volume_of_replicated_type(volume)
              and new_replicated_type):
            # Retype from replication disabled to replication enable.
            common._do_volume_replication_setup(
                volume,
                retype=True,
                dist_type_id=new_type_id)
        elif common._volume_of_replicated_type(volume):
            # Retype from replication enabled to replication disable.
            common._do_volume_replication_destroy(volume, retype=True)


class ModifyVolumeTask(flow_utils.CinderTask):

    """Task to change a volume's snapCPG and comment.

    This is a task for changing the snapCPG and comment.  It is intended for
    use during retype().  These changes are done together with a single
    modify request which should be fast and easy to revert.

    Because we do not support retype with existing snapshots, we can change
    the snapCPG without using a keepVV.  If snapshots exist, then this will
    fail, as desired.

    This task does not change the userCPG or provisioningType.  Those changes
    may require tunevv, so they are done by the TuneVolumeTask.

    The new comment will contain the new type, VVS and QOS information along
    with whatever else was in the old comment dict.

    The old comment and snapCPG are restored if revert is called.
    """

    def __init__(self, action):
        self.needs_revert = False
        super(ModifyVolumeTask, self).__init__(addons=[action])

    def _get_new_comment(self, old_comment, new_vvs, new_qos,
                         new_type_name, new_type_id):

        # Modify the comment during ModifyVolume
        comment_dict = dict(ast.literal_eval(old_comment))
        if 'vvs' in comment_dict:
            del comment_dict['vvs']
        if 'qos' in comment_dict:
            del comment_dict['qos']
        if new_vvs:
            comment_dict['vvs'] = new_vvs
        elif new_qos:
            comment_dict['qos'] = new_qos
        else:
            comment_dict['qos'] = {}

        if new_type_name:
            comment_dict['volume_type_name'] = new_type_name
        else:
            comment_dict.pop('volume_type_name', None)

        if new_type_id:
            comment_dict['volume_type_id'] = new_type_id
        else:
            comment_dict.pop('volume_type_id', None)

        return comment_dict

    def execute(self, common, volume_name, old_snap_cpg, new_snap_cpg,
                old_comment, new_vvs, new_qos, new_type_name, new_type_id):

        comment_dict = self._get_new_comment(
            old_comment, new_vvs, new_qos, new_type_name, new_type_id)

        if new_snap_cpg != old_snap_cpg:
            # Modify the snap_cpg.  This will fail with snapshots.
            LOG.info("Modifying %(volume_name)s snap_cpg from "
                     "%(old_snap_cpg)s to %(new_snap_cpg)s.",
                     {'volume_name': volume_name,
                      'old_snap_cpg': old_snap_cpg,
                      'new_snap_cpg': new_snap_cpg})
            common.client.modifyVolume(
                volume_name,
                {'snapCPG': new_snap_cpg,
                 'comment': json.dumps(comment_dict)})
            self.needs_revert = True
        else:
            LOG.info("Modifying %s comments.", volume_name)
            common.client.modifyVolume(
                volume_name,
                {'comment': json.dumps(comment_dict)})
            self.needs_revert = True

    def revert(self, common, volume_name, old_snap_cpg, new_snap_cpg,
               old_comment, **kwargs):
        if self.needs_revert:
            LOG.info("Retype revert %(volume_name)s snap_cpg from "
                     "%(new_snap_cpg)s back to %(old_snap_cpg)s.",
                     {'volume_name': volume_name,
                      'new_snap_cpg': new_snap_cpg,
                      'old_snap_cpg': old_snap_cpg})
            try:
                common.client.modifyVolume(
                    volume_name,
                    {'snapCPG': old_snap_cpg, 'comment': old_comment})
            except Exception as ex:
                LOG.error("Exception during snapCPG revert: %s", ex)


class TuneVolumeTask(flow_utils.CinderTask):

    """Task to change a volume's CPG and/or provisioning type.

    This is a task for changing the CPG and/or provisioning type.
    It is intended for use during retype().

    This task has no revert.  The current design is to do this task last
    and do revert-able tasks first. Un-doing a tunevv can be expensive
    and should be avoided.
    """

    def __init__(self, action, **kwargs):
        super(TuneVolumeTask, self).__init__(addons=[action])

    def execute(self, common, old_tpvv, new_tpvv, old_tdvv, new_tdvv,
                old_cpg, new_cpg, volume_name, new_compression):
        common.tune_vv(old_tpvv, new_tpvv, old_tdvv, new_tdvv,
                       old_cpg, new_cpg, volume_name, new_compression)


class ModifySpecsTask(flow_utils.CinderTask):

    """Set/unset the QOS settings and/or VV set for the volume's new type.

    This is a task for changing the QOS settings and/or VV set.  It is intended
    for use during retype().  If changes are made during execute(), then they
    need to be undone if revert() is called (i.e., if a later task fails).

    For 3PAR, we ignore QOS settings if a VVS is explicitly set, otherwise we
    create a VV set and use that for QOS settings.  That is why they are lumped
    together here.  Most of the decision-making about VVS vs. QOS settings vs.
    old-style scoped extra-specs is handled in existing reusable code.  Here
    we mainly need to know what old stuff to remove before calling the function
    that knows how to set the new stuff.

    Basic task flow is as follows:  Remove the volume from the old externally
    created VVS (when appropriate), delete the old cinder-created VVS, call
    the function that knows how to set a new VVS or QOS settings.

    If any changes are made during execute, then revert needs to reverse them.
    """

    def __init__(self, action):
        self.needs_revert = False
        super(ModifySpecsTask, self).__init__(addons=[action])

    def execute(self, common, volume_name, volume, old_cpg, new_cpg,
                old_vvs, new_vvs, old_qos, new_qos,
                old_flash_cache, new_flash_cache):

        if (old_vvs != new_vvs or
                old_qos != new_qos or
                old_flash_cache != new_flash_cache):

            # Remove VV from old VV Set.
            if old_vvs is not None and old_vvs != new_vvs:
                common.client.removeVolumeFromVolumeSet(old_vvs,
                                                        volume_name)
                self.needs_revert = True

            # If any extra or qos specs changed then remove the old
            # special VV set that we create.  We'll recreate it
            # as needed.
            vvs_name = common._get_3par_vvs_name(volume['id'])
            try:
                common.client.deleteVolumeSet(vvs_name)
                self.needs_revert = True
            except hpeexceptions.HTTPNotFound as ex:
                # HTTPNotFound(code=102) is OK.  Set does not exist.
                if ex.get_code() != 102:
                    LOG.error("Unexpected error when retype() tried to "
                              "deleteVolumeSet(%s)", vvs_name)
                    raise

            if new_vvs or new_qos or new_flash_cache:
                common._add_volume_to_volume_set(
                    volume, volume_name, new_cpg, new_vvs, new_qos,
                    new_flash_cache)
                self.needs_revert = True

    def revert(self, common, volume_name, volume, old_vvs, new_vvs, old_qos,
               old_cpg, **kwargs):
        if self.needs_revert:
            # If any extra or qos specs changed then remove the old
            # special VV set that we create and recreate it per
            # the old type specs.
            vvs_name = common._get_3par_vvs_name(volume['id'])
            try:
                common.client.deleteVolumeSet(vvs_name)
            except hpeexceptions.HTTPNotFound as ex:
                # HTTPNotFound(code=102) is OK.  Set does not exist.
                if ex.get_code() != 102:
                    LOG.error("Unexpected error when retype() revert "
                              "tried to deleteVolumeSet(%s)", vvs_name)
            except Exception:
                LOG.error("Unexpected error when retype() revert "
                          "tried to deleteVolumeSet(%s)", vvs_name)

            if old_vvs is not None or old_qos is not None:
                try:
                    common._add_volume_to_volume_set(
                        volume, volume_name, old_cpg, old_vvs, old_qos)
                except Exception as ex:
                    LOG.error("%(exception)s: Exception during revert of "
                              "retype for volume %(volume_name)s. "
                              "Original volume set/QOS settings may not "
                              "have been fully restored.",
                              {'exception': ex, 'volume_name': volume_name})

            if new_vvs is not None and old_vvs != new_vvs:
                try:
                    common.client.removeVolumeFromVolumeSet(
                        new_vvs, volume_name)
                except Exception as ex:
                    LOG.error("%(exception)s: Exception during revert of "
                              "retype for volume %(volume_name)s. "
                              "Failed to remove from new volume set "
                              "%(new_vvs)s.",
                              {'exception': ex,
                               'volume_name': volume_name,
                               'new_vvs': new_vvs})
