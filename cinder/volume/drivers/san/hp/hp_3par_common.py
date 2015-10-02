#    (c) Copyright 2012-2015 Hewlett-Packard Development Company, L.P.
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
Volume driver common utilities for HP 3PAR Storage array

The 3PAR drivers requires 3.1.3 firmware on the 3PAR array.

You will need to install the python hp3parclient.
sudo pip install hp3parclient

The drivers uses both the REST service and the SSH
command line to correctly operate.  Since the
ssh credentials and the REST credentials can be different
we need to have settings for both.

The drivers requires the use of the san_ip, san_login,
san_password settings for ssh connections into the 3PAR
array.   It also requires the setting of
hp3par_api_url, hp3par_username, hp3par_password
for credentials to talk to the REST service on the 3PAR
array.
"""

import ast
import base64
import json
import math
import pprint
import re
import uuid

from oslo_utils import importutils

hp3parclient = importutils.try_import("hp3parclient")
if hp3parclient:
    from hp3parclient import client
    from hp3parclient import exceptions as hpexceptions

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import context
from cinder import exception
from cinder import flow_utils
from cinder.i18n import _, _LE, _LI, _LW
from cinder.openstack.common import loopingcall
from cinder.openstack.common import versionutils
from cinder.volume import qos_specs
from cinder.volume import utils as volume_utils
from cinder.volume import volume_types

import taskflow.engines
from taskflow.patterns import linear_flow

LOG = logging.getLogger(__name__)

MIN_CLIENT_VERSION = '3.1.2'
DEDUP_API_VERSION = 30201120
FLASH_CACHE_API_VERSION = 30201200

hp3par_opts = [
    cfg.StrOpt('hp3par_api_url',
               default='',
               help="3PAR WSAPI Server Url like "
                    "https://<3par ip>:8080/api/v1"),
    cfg.StrOpt('hp3par_username',
               default='',
               help="3PAR Super user username"),
    cfg.StrOpt('hp3par_password',
               default='',
               help="3PAR Super user password",
               secret=True),
    cfg.ListOpt('hp3par_cpg',
                default=["OpenStack"],
                help="List of the CPG(s) to use for volume creation"),
    cfg.StrOpt('hp3par_cpg_snap',
               default="",
               help="The CPG to use for Snapshots for volumes. "
                    "If empty the userCPG will be used."),
    cfg.StrOpt('hp3par_snapshot_retention',
               default="",
               help="The time in hours to retain a snapshot.  "
                    "You can't delete it before this expires."),
    cfg.StrOpt('hp3par_snapshot_expiration',
               default="",
               help="The time in hours when a snapshot expires "
                    " and is deleted.  This must be larger than expiration"),
    cfg.BoolOpt('hp3par_debug',
                default=False,
                help="Enable HTTP debugging to 3PAR"),
    cfg.ListOpt('hp3par_iscsi_ips',
                default=[],
                help="List of target iSCSI addresses to use."),
    cfg.BoolOpt('hp3par_iscsi_chap_enabled',
                default=False,
                help="Enable CHAP authentication for iSCSI connections."),
]


CONF = cfg.CONF
CONF.register_opts(hp3par_opts)


class HP3PARCommon(object):
    """Class that contains common code for the 3PAR drivers.

    Version history:
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
        2.0.41 - Improved VLUN creation and deletion logic. #1469816

    """

    VERSION = "2.0.41"

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
    hp_qos_keys = ['minIOPS', 'maxIOPS', 'minBWS', 'maxBWS', 'latency',
                   'priority']
    qos_priority_level = {'low': 1, 'normal': 2, 'high': 3}
    hp3par_valid_keys = ['cpg', 'snap_cpg', 'provisioning', 'persona', 'vvs',
                         'flash_cache']

    def __init__(self, config):
        self.config = config
        self.client = None
        self.uuid = uuid.uuid4()

    def get_version(self):
        return self.VERSION

    def check_flags(self, options, required_flags):
        for flag in required_flags:
            if not getattr(options, flag, None):
                msg = _('%s is not set') % flag
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

    def _create_client(self):
        cl = client.HP3ParClient(self.config.hp3par_api_url)
        client_version = hp3parclient.version

        if (client_version < MIN_CLIENT_VERSION):
            ex_msg = (_('Invalid hp3parclient version found (%(found)s). '
                        'Version %(minimum)s or greater required.')
                      % {'found': client_version,
                         'minimum': MIN_CLIENT_VERSION})
            LOG.error(ex_msg)
            raise exception.InvalidInput(reason=ex_msg)

        return cl

    def client_login(self):
        try:
            LOG.debug("Connecting to 3PAR")
            self.client.login(self.config.hp3par_username,
                              self.config.hp3par_password)
        except hpexceptions.HTTPUnauthorized as ex:
            msg = (_("Failed to Login to 3PAR (%(url)s) because %(err)s") %
                   {'url': self.config.hp3par_api_url, 'err': ex})
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        known_hosts_file = CONF.ssh_hosts_key_file
        policy = "AutoAddPolicy"
        if CONF.strict_ssh_host_key_policy:
            policy = "RejectPolicy"
        self.client.setSSHOptions(
            self.config.san_ip,
            self.config.san_login,
            self.config.san_password,
            port=self.config.san_ssh_port,
            conn_timeout=self.config.ssh_conn_timeout,
            privatekey=self.config.san_private_key,
            missing_key_policy=policy,
            known_hosts_file=known_hosts_file)

    def client_logout(self):
        LOG.info(_LI("Disconnect from 3PAR REST and SSH %s"), self.uuid)
        self.client.logout()
        LOG.info(_LI("logout Done %s"), self.uuid)

    def do_setup(self, context):
        if hp3parclient is None:
            msg = _('You must install hp3parclient before using 3PAR drivers.')
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            self.client = self._create_client()
            wsapi_version = self.client.getWsApiVersion()
            self.API_VERSION = wsapi_version['build']
        except hpexceptions.UnsupportedVersion as ex:
            raise exception.InvalidInput(ex)
        LOG.info(_LI("HP3PARCommon %(common_ver)s, hp3parclient %(rest_ver)s"),
                 {"common_ver": self.VERSION,
                  "rest_ver": hp3parclient.get_version_string()})
        if self.config.hp3par_debug:
            self.client.debug_rest(True)

    def check_for_setup_error(self):
        self.client_login()
        try:
            cpg_names = self.config.hp3par_cpg
            for cpg_name in cpg_names:
                self.validate_cpg(cpg_name)

        finally:
            self.client_logout()

    def validate_cpg(self, cpg_name):
        try:
            self.client.getCPG(cpg_name)
        except hpexceptions.HTTPNotFound:
            err = (_("CPG (%s) doesn't exist on array") % cpg_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

    def get_domain(self, cpg_name):
        try:
            cpg = self.client.getCPG(cpg_name)
        except hpexceptions.HTTPNotFound:
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
        except hpexceptions.HTTPNotFound:
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
            LOG.info(_LI("Virtual volume %(disp)s '%(new)s' snapCPG "
                     "is empty so it will be set to: %(cpg)s"),
                     {'disp': display_name, 'new': new_vol_name,
                      'cpg': new_vals['snapCPG']})

        # Update the existing volume with the new name and comments.
        self.client.modifyVolume(target_vol_name, new_vals)

        LOG.info(_LI("Virtual volume '%(ref)s' renamed to '%(new)s'."),
                 {'ref': existing_ref['source-name'], 'new': new_vol_name})

        retyped = False
        model_update = None
        if volume_type:
            LOG.info(_LI("Virtual volume %(disp)s '%(new)s' is "
                         "being retyped."),
                     {'disp': display_name, 'new': new_vol_name})

            try:
                retyped, model_update = self._retype_from_no_type(volume,
                                                                  volume_type)
                LOG.info(_LI("Virtual volume %(disp)s successfully retyped to "
                             "%(new_type)s."),
                         {'disp': display_name,
                          'new_type': volume_type.get('name')})
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.warning(_LW("Failed to manage virtual volume %(disp)s "
                                    "due to error during retype."),
                                {'disp': display_name})
                    # Try to undo the rename and clear the new comment.
                    self.client.modifyVolume(
                        new_vol_name,
                        {'newName': target_vol_name,
                         'comment': old_comment_str})

        updates = {'display_name': display_name}
        if retyped and model_update:
            updates.update(model_update)

        LOG.info(_LI("Virtual volume %(disp)s '%(new)s' is "
                     "now being managed."),
                 {'disp': display_name, 'new': new_vol_name})

        # Return display name to update the name displayed in the GUI and
        # any model updates from retype.
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
        except hpexceptions.HTTPNotFound:
            err = (_("Virtual volume '%s' doesn't exist on array.") %
                   target_vol_name)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        return int(math.ceil(float(vol['sizeMiB']) / units.Ki))

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management."""
        # Rename the volume's name to unm-* format so that it can be
        # easily found later.
        vol_name = self._get_3par_vol_name(volume['id'])
        new_vol_name = self._get_3par_unm_name(volume['id'])
        self.client.modifyVolume(vol_name, {'newName': new_vol_name})

        LOG.info(_LI("Virtual volume %(disp)s '%(vol)s' is no longer managed. "
                     "Volume renamed to '%(new)s'."),
                 {'disp': volume['display_name'],
                  'vol': vol_name,
                  'new': new_vol_name})

    def _get_existing_volume_ref_name(self, existing_ref):
        """Returns the volume name of an existing reference.

        Checks if an existing volume reference has a source-name or
        source-id element. If source-name or source-id is not present an
        error will be thrown.
        """
        vol_name = None
        if 'source-name' in existing_ref:
            vol_name = existing_ref['source-name']
        elif 'source-id' in existing_ref:
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
        try:
            if _convert_to_base:
                LOG.debug("Converting to base volume prior to growing.")
                model_update = self._convert_to_base_volume(volume)
            self.client.growVolume(volume_name, growth_size_mib)
        except Exception as ex:
            with excutils.save_and_reraise_exception() as ex_ctxt:
                if (not _convert_to_base and
                    isinstance(ex, hpexceptions.HTTPForbidden) and
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
                    LOG.error(_LE("Error extending volume: %(vol)s. "
                                  "Exception: %(ex)s"),
                              {'vol': volume_name, 'ex': ex})
        return model_update

    def _get_3par_vol_name(self, volume_id):
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
        return "osv-%s" % volume_name

    def _get_3par_snap_name(self, snapshot_id):
        snapshot_name = self._encode_name(snapshot_id)
        return "oss-%s" % snapshot_name

    def _get_3par_vvs_name(self, volume_id):
        vvs_name = self._encode_name(volume_id)
        return "vvs-%s" % vvs_name

    def _get_3par_unm_name(self, volume_id):
        unm_name = self._encode_name(volume_id)
        return "unm-%s" % unm_name

    def _encode_name(self, name):
        uuid_str = name.replace("-", "")
        vol_uuid = uuid.UUID('urn:uuid:%s' % uuid_str)
        vol_encoded = base64.b64encode(vol_uuid.bytes)

        # 3par doesn't allow +, nor /
        vol_encoded = vol_encoded.replace('+', '.')
        vol_encoded = vol_encoded.replace('/', '-')
        # strip off the == as 3par doesn't like those.
        vol_encoded = vol_encoded.replace('=', '')
        return vol_encoded

    def _capacity_from_size(self, vol_size):

        # because 3PAR volume sizes are in
        # Mebibytes, Gigibytes, not Megabytes.
        MB = 1000L
        MiB = 1.048576

        if int(vol_size) == 0:
            capacity = MB  # default: 1GB
        else:
            capacity = vol_size * MB

        capacity = int(round(capacity / MiB))
        return capacity

    def _delete_3par_host(self, hostname):
        self.client.deleteHost(hostname)

    def _create_3par_vlun(self, volume, hostname, nsp):
        try:
            location = None
            if nsp is None:
                location = self.client.createVLUN(volume, hostname=hostname,
                                                  auto=True)
            else:
                port = self.build_portPos(nsp)
                location = self.client.createVLUN(volume, hostname=hostname,
                                                  auto=True, portPos=port)

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

        except hpexceptions.HTTPBadRequest as e:
            if 'must be in the same domain' in e.get_description():
                LOG.error(e.get_description())
                raise exception.Invalid3PARDomain(err=e.get_description())

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

        for cpg_name in self.config.hp3par_cpg:
            try:
                cpg = self.client.getCPG(cpg_name)
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

            except hpexceptions.HTTPNotFound:
                err = (_("CPG (%s) doesn't exist on array")
                       % cpg_name)
                LOG.error(err)
                raise exception.InvalidInput(reason=err)

            pool = {'pool_name': cpg_name,
                    'total_capacity_gb': total_capacity,
                    'free_capacity_gb': free_capacity,
                    'QoS_support': True,
                    'reserved_percentage': 0,
                    'location_info': ('HP3PARDriver:%(sys_id)s:%(dest_cpg)s' %
                                      {'sys_id': info['serialNumber'],
                                       'dest_cpg': cpg_name}),
                    'total_volumes': total_volumes,
                    'capacity_utilization': capacity_utilization,
                    'filter_function': filter_function,
                    'goodness_function': goodness_function
                    }

            pools.append(pool)

        self.stats = {'driver_version': '1.0',
                      'storage_protocol': None,
                      'vendor_name': 'Hewlett-Packard',
                      'volume_backend_name': None,
                      # Use zero capacities here so we always use a pool.
                      'total_capacity_gb': 0,
                      'free_capacity_gb': 0,
                      'reserved_percentage': 0,
                      'pools': pools}

    def _get_vlun(self, volume_name, hostname, lun_id=None):
        """find a VLUN on a 3PAR host."""
        vluns = self.client.getHostVLUNs(hostname)
        found_vlun = None
        for vlun in vluns:
            if volume_name in vlun['volumeName']:
                if lun_id:
                    if vlun['lun'] == lun_id:
                        found_vlun = vlun
                        break
                else:
                    found_vlun = vlun
                    break

        if found_vlun is None:
            msg = (_("3PAR vlun %(name)s not found on host %(host)s") %
                   {'name': volume_name, 'host': hostname})
            LOG.info(msg)
        return found_vlun

    def create_vlun(self, volume, host, nsp=None):
        """Create a VLUN.

        In order to export a volume on a 3PAR box, we have to create a VLUN.
        """
        volume_name = self._get_3par_vol_name(volume['id'])
        vlun_info = self._create_3par_vlun(volume_name, host['name'], nsp)
        return self._get_vlun(volume_name, host['name'], vlun_info['lun_id'])

    def delete_vlun(self, volume, hostname):
        volume_name = self._get_3par_vol_name(volume['id'])
        vluns = self.client.getHostVLUNs(hostname)

        # Find all the VLUNs associated with the volume. The VLUNs will then
        # be split into groups based on the active status of the VLUN. If there
        # are active VLUNs detected a delete will be attempted on them. If
        # there are no active VLUNs but there are inactive VLUNs, then the
        # inactive VLUNs will be deleted. The inactive VLUNs are the templates
        # on the 3PAR backend.
        active_volume_vluns = []
        inactive_volume_vluns = []
        volume_vluns = []

        for vlun in vluns:
            if volume_name in vlun['volumeName']:
                if vlun['active']:
                    active_volume_vluns.append(vlun)
                else:
                    inactive_volume_vluns.append(vlun)
        if active_volume_vluns:
            volume_vluns = active_volume_vluns
        elif inactive_volume_vluns:
            volume_vluns = inactive_volume_vluns

        if not volume_vluns:
            msg = (
                _LW("3PAR vlun for volume %(name)s not found on "
                    "host %(host)s"), {'name': volume_name, 'host': hostname})
            LOG.warning(msg)
            return

        # VLUN Type of MATCHED_SET 4 requires the port to be provided
        removed_luns = []
        for vlun in volume_vluns:
            if self.VLUN_TYPE_MATCHED_SET == vlun['type']:
                self.client.deleteVLUN(volume_name, vlun['lun'], hostname,
                                       vlun['portPos'])
            else:
                # This is HOST_SEES or a type that is not MATCHED_SET.
                # By deleting one VLUN, all the others should be deleted, too.
                if vlun['lun'] not in removed_luns:
                    self.client.deleteVLUN(volume_name, vlun['lun'], hostname)
                    removed_luns.append(vlun['lun'])

        # Determine if there are other volumes attached to the host.
        # This will determine whether we should try removing host from host set
        # and deleting the host.
        vluns = []
        try:
            vluns = self.client.getHostVLUNs(hostname)
        except hpexceptions.HTTPNotFound:
            LOG.debug("All VLUNs removed from host %s", hostname)
            pass

        for vlun in vluns:
            if volume_name not in vlun['volumeName']:
                # Found another volume
                break
        else:
            # We deleted the last vlun, so try to delete the host too.
            # This check avoids the old unnecessary try/fail when vluns exist
            # but adds a minor race condition if a vlun is manually deleted
            # externally at precisely the wrong time. Worst case is leftover
            # host, so it is worth the unlikely risk.

            try:
                self._delete_3par_host(hostname)
            except Exception as ex:
                # Any exception down here is only logged.  The vlun is deleted.

                # If the host is in a host set, the delete host will fail and
                # the host will remain in the host set.  This is desired
                # because cinder was not responsible for the host set
                # assignment.  The host set could be used outside of cinder
                # for future needs (e.g. export volume to host set).

                # The log info explains why the host was left alone.
                msg = (_("3PAR vlun for volume '%(name)s' was deleted, "
                         "but the host '%(host)s' was not deleted because: "
                         "%(reason)s") %
                       {'name': volume_name,
                        'host': hostname,
                        'reason': ex.get_description()})
                LOG.info(msg)

    def _get_volume_type(self, type_id):
        ctxt = context.get_admin_context()
        return volume_types.get_volume_type(ctxt, type_id)

    def _get_key_value(self, hp3par_keys, key, default=None):
        if hp3par_keys is not None and key in hp3par_keys:
            return hp3par_keys[key]
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

        for key, value in kvs.iteritems():
            if 'qos:' in key:
                fields = key.split(':')
                key = fields[1]
            if key in self.hp_qos_keys:
                qos[key] = value
        return qos

    def _get_keys_by_volume_type(self, volume_type):
        hp3par_keys = {}
        specs = volume_type.get('extra_specs')
        for key, value in specs.iteritems():
            if ':' in key:
                fields = key.split(':')
                key = fields[1]
            if key in self.hp3par_valid_keys:
                hp3par_keys[key] = value
        return hp3par_keys

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
                LOG.error(_LE("Error creating QOS rule %s"), qosRule)

    def get_flash_cache_policy(self, hp3par_keys):
        if hp3par_keys is not None:
            # First check list of extra spec keys
            val = self._get_key_value(hp3par_keys, 'flash_cache', None)
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

    def _set_flash_cache_policy_in_vvs(self, flash_cache, vvs_name):
        # Update virtual volume set
        if flash_cache:
            try:
                self.client.modifyVolumeSet(vvs_name,
                                            flashCachePolicy=flash_cache)
                LOG.info(_LI("Flash Cache policy set to %s"), flash_cache)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE("Error setting Flash Cache policy "
                                  "to %s - exception"), flash_cache)

    def _add_volume_to_volume_set(self, volume, volume_name,
                                  cpg, vvs_name, qos, flash_cache):
        if vvs_name is not None:
            # Admin has set a volume set name to add the volume to
            try:
                self.client.addVolumeToVolumeSet(vvs_name, volume_name)
            except hpexceptions.HTTPNotFound:
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
        if 'userCPG' in vol:
            return vol['userCPG']
        elif allowSnap:
            return vol['snapCPG']
        return None

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
        :raises: exception.InvalidInput
        :return: persona ID
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

    def get_persona_type(self, volume, hp3par_keys=None):
        default_persona = self.valid_persona_values[0]
        type_id = volume.get('volume_type_id', None)
        if type_id is not None:
            volume_type = self._get_volume_type(type_id)
            if hp3par_keys is None:
                hp3par_keys = self._get_keys_by_volume_type(volume_type)
        persona_value = self._get_key_value(hp3par_keys, 'persona',
                                            default_persona)
        return self.validate_persona(persona_value)

    def get_type_info(self, type_id):
        """Get 3PAR type info for the given type_id.

        Reconciles VV Set, old-style extra-specs, and QOS specs
        and returns commonly used info about the type.

        :returns: hp3par_keys, qos, volume_type, vvs_name
        """
        volume_type = None
        vvs_name = None
        hp3par_keys = {}
        qos = {}
        if type_id is not None:
            volume_type = self._get_volume_type(type_id)
            hp3par_keys = self._get_keys_by_volume_type(volume_type)
            vvs_name = self._get_key_value(hp3par_keys, 'vvs')
            if vvs_name is None:
                qos = self._get_qos_by_volume_type(volume_type)
        return hp3par_keys, qos, volume_type, vvs_name

    def get_volume_settings_from_type_id(self, type_id, pool):
        """Get 3PAR volume settings given a type_id.

        Combines type info and config settings to return a dictionary
        describing the 3PAR volume settings.  Does some validation (CPG).
        Uses pool as the default cpg (when not specified in volume type specs).

        :param type_id: id of type to get settings for
        :param pool: CPG to use if type does not have one set
        :return: dict
        """

        hp3par_keys, qos, volume_type, vvs_name = self.get_type_info(type_id)

        # Default to pool extracted from host.
        # If that doesn't work use the 1st CPG in the config as the default.
        default_cpg = pool or self.config.hp3par_cpg[0]

        cpg = self._get_key_value(hp3par_keys, 'cpg', default_cpg)
        if cpg is not default_cpg:
            # The cpg was specified in a volume type extra spec so it
            # needs to be validated that it's in the correct domain.
            # log warning here
            msg = _LW("'hp3par:cpg' is not supported as an extra spec "
                      "in a volume type.  CPG's are chosen by "
                      "the cinder scheduler, as a pool, from the "
                      "cinder.conf entry 'hp3par_cpg', which can "
                      "be a list of CPGs.")
            versionutils.report_deprecated_feature(LOG, msg)
            LOG.info(_LI("Using pool %(pool)s instead of %(cpg)s"),
                     {'pool': pool, 'cpg': cpg})

            cpg = pool
            self.validate_cpg(cpg)

        # Look to see if the snap_cpg was specified in volume type
        # extra spec, if not use hp3par_cpg_snap from config as the
        # default.
        snap_cpg = self.config.hp3par_cpg_snap
        snap_cpg = self._get_key_value(hp3par_keys, 'snap_cpg', snap_cpg)
        # If it's still not set or empty then set it to the cpg.
        if not snap_cpg:
            snap_cpg = cpg

        # if provisioning is not set use thin
        default_prov = self.valid_prov_values[0]
        prov_value = self._get_key_value(hp3par_keys, 'provisioning',
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

        return {'hp3par_keys': hp3par_keys,
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
        :return: dict
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
        self.get_persona_type(volume, volume_settings['hp3par_keys'])

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
            flash_cache = self.get_flash_cache_policy(type_info['hp3par_keys'])

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
            self.client.createVolume(volume_name, cpg, capacity, extras)
            if qos or vvs_name or flash_cache is not None:
                try:
                    self._add_volume_to_volume_set(volume, volume_name,
                                                   cpg, vvs_name, qos,
                                                   flash_cache)
                except exception.InvalidInput as ex:
                    # Delete the volume if unable to add it to the volume set
                    self.client.deleteVolume(volume_name)
                    LOG.error(ex)
                    raise exception.CinderException(ex)
        except hpexceptions.HTTPConflict:
            msg = _("Volume (%s) already exists on array") % volume_name
            LOG.error(msg)
            raise exception.Duplicate(msg)
        except hpexceptions.HTTPBadRequest as ex:
            LOG.error(ex)
            raise exception.Invalid(ex.get_description())
        except exception.InvalidInput as ex:
            LOG.error(ex)
            raise ex
        except exception.CinderException as ex:
            LOG.error(ex)
            raise ex
        except Exception as ex:
            LOG.error(ex)
            raise exception.CinderException(ex)

        return self._get_model_update(volume['host'], cpg)

    def _copy_volume(self, src_name, dest_name, cpg, snap_cpg=None,
                     tpvv=True, tdvv=False):
        # Virtual volume sets are not supported with the -online option
        LOG.debug('Creating clone of a volume %(src)s to %(dest)s.',
                  {'src': src_name, 'dest': dest_name})

        optional = {'tpvv': tpvv, 'online': True}
        if snap_cpg is not None:
            optional['snapCPG'] = snap_cpg

        if self.API_VERSION >= DEDUP_API_VERSION:
            optional['tdvv'] = tdvv

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

    def _get_model_update(self, volume_host, cpg):
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
        :return: dict Model update if we need to update volume host, else None
        """
        model_update = None
        host = volume_utils.extract_host(volume_host, 'backend')
        host_and_pool = volume_utils.append_host(host, cpg)
        if volume_host != host_and_pool:
            # Since we selected a pool based on type, update the model.
            model_update = {'host': host_and_pool}
        return model_update

    def create_cloned_volume(self, volume, src_vref):
        try:
            orig_name = self._get_3par_vol_name(volume['source_volid'])
            vol_name = self._get_3par_vol_name(volume['id'])

            type_info = self.get_volume_settings_from_type(volume)

            # make the 3PAR copy the contents.
            # can't delete the original until the copy is done.
            cpg = type_info['cpg']
            self._copy_volume(orig_name, vol_name, cpg=cpg,
                              snap_cpg=type_info['snap_cpg'],
                              tpvv=type_info['tpvv'],
                              tdvv=type_info['tdvv'])

            return self._get_model_update(volume['host'], cpg)

        except hpexceptions.HTTPForbidden:
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound:
            raise exception.NotFound()
        except Exception as ex:
            LOG.error(ex)
            raise exception.CinderException(ex)

    def delete_volume(self, volume):
        try:
            volume_name = self._get_3par_vol_name(volume['id'])
            # Try and delete the volume, it might fail here because
            # the volume is part of a volume set which will have the
            # volume set name in the error.
            try:
                self.client.deleteVolume(volume_name)
            except hpexceptions.HTTPBadRequest as ex:
                if ex.get_code() == 29:
                    if self.client.isOnlinePhysicalCopy(volume_name):
                        LOG.debug("Found an online copy for %(volume)s",
                                  {'volume': volume_name})
                        # the volume is in process of being cloned.
                        # stopOnlinePhysicalCopy will also delete
                        # the volume once it stops the copy.
                        self.client.stopOnlinePhysicalCopy(volume_name)
                    else:
                        LOG.error(ex)
                        raise ex
                else:
                    LOG.error(ex)
                    raise ex
            except hpexceptions.HTTPConflict as ex:
                if ex.get_code() == 34:
                    # This is a special case which means the
                    # volume is part of a volume set.
                    vvset_name = self.client.findVolumeSet(volume_name)
                    LOG.debug("Returned vvset_name = %s", vvset_name)
                    if vvset_name is not None and \
                       vvset_name.startswith('vvs-'):
                        # We have a single volume per volume set, so
                        # remove the volume set.
                        self.client.deleteVolumeSet(
                            self._get_3par_vvs_name(volume['id']))
                    elif vvset_name is not None:
                        # We have a pre-defined volume set just remove the
                        # volume and leave the volume set.
                        self.client.removeVolumeFromVolumeSet(vvset_name,
                                                              volume_name)
                    self.client.deleteVolume(volume_name)
                elif (ex.get_code() == 151 or ex.get_code() == 32):
                    # the volume is being operated on in a background
                    # task on the 3PAR.
                    # TODO(walter-boring) do a retry a few times.
                    # for now lets log a better message
                    msg = _("The volume is currently busy on the 3PAR"
                            " and cannot be deleted at this time. "
                            "You can try again later.")
                    LOG.error(msg)
                    raise exception.VolumeIsBusy(message=msg)
                else:
                    LOG.error(ex)
                    raise exception.VolumeIsBusy(message=ex.get_description())

        except hpexceptions.HTTPNotFound as ex:
            # We'll let this act as if it worked
            # it helps clean up the cinder entries.
            msg = _("Delete volume id not found. Removing from cinder: "
                    "%(id)s Ex: %(msg)s") % {'id': volume['id'], 'msg': ex}
            LOG.warning(msg)
        except hpexceptions.HTTPForbidden as ex:
            LOG.error(ex)
            raise exception.NotAuthorized(ex.get_description())
        except hpexceptions.HTTPConflict as ex:
            LOG.error(ex)
            raise exception.VolumeIsBusy(message=ex.get_description())
        except Exception as ex:
            LOG.error(ex)
            raise exception.CinderException(ex)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        """
        LOG.debug("Create Volume from Snapshot\n%(vol_name)s\n%(ss_name)s",
                  {'vol_name': pprint.pformat(volume['display_name']),
                   'ss_name': pprint.pformat(snapshot['display_name'])})

        model_update = None
        if volume['size'] < snapshot['volume_size']:
            err = ("You cannot reduce size of the volume.  It must "
                   "be greater than or equal to the snapshot.")
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        try:
            snap_name = self._get_3par_snap_name(snapshot['id'])
            volume_name = self._get_3par_vol_name(volume['id'])

            extra = {'volume_id': volume['id'],
                     'snapshot_id': snapshot['id']}

            type_id = volume.get('volume_type_id', None)

            hp3par_keys, qos, _volume_type, vvs_name = self.get_type_info(
                type_id)

            name = volume.get('display_name', None)
            if name:
                extra['display_name'] = name

            description = volume.get('display_description', None)
            if description:
                extra['description'] = description

            optional = {'comment': json.dumps(extra),
                        'readOnly': False}

            self.client.createSnapshot(volume_name, snap_name, optional)

            # Grow the snapshot if needed
            growth_size = volume['size'] - snapshot['volume_size']
            if growth_size > 0:
                try:
                    LOG.debug('Converting to base volume type: %s.',
                              volume['id'])
                    model_update = self._convert_to_base_volume(volume)
                    growth_size_mib = growth_size * units.Gi / units.Mi
                    LOG.debug('Growing volume: %(id)s by %(size)s GiB.',
                              {'id': volume['id'], 'size': growth_size})
                    self.client.growVolume(volume_name, growth_size_mib)
                except Exception as ex:
                    LOG.error(_LE("Error extending volume %(id)s. "
                                  "Ex: %(ex)s"),
                              {'id': volume['id'], 'ex': ex})
                    # Delete the volume if unable to grow it
                    self.client.deleteVolume(volume_name)
                    raise exception.CinderException(ex)

            # Check for flash cache setting in extra specs
            flash_cache = self.get_flash_cache_policy(hp3par_keys)

            if qos or vvs_name or flash_cache is not None:
                cpg_names = self._get_key_value(hp3par_keys, 'cpg',
                                                self.config.hp3par_cpg)
                try:
                    self._add_volume_to_volume_set(volume, volume_name,
                                                   cpg_names[0], vvs_name,
                                                   qos, flash_cache)
                except Exception as ex:
                    # Delete the volume if unable to add it to the volume set
                    self.client.deleteVolume(volume_name)
                    LOG.error(ex)
                    raise exception.CinderException(ex)
        except hpexceptions.HTTPForbidden as ex:
            LOG.error(ex)
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound as ex:
            LOG.error(ex)
            raise exception.NotFound()
        except Exception as ex:
            LOG.error(ex)
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
            if self.config.hp3par_snapshot_expiration:
                optional['expirationHours'] = (
                    self.config.hp3par_snapshot_expiration)

            if self.config.hp3par_snapshot_retention:
                optional['retentionHours'] = (
                    self.config.hp3par_snapshot_retention)

            self.client.createSnapshot(snap_name, vol_name, optional)
        except hpexceptions.HTTPForbidden as ex:
            LOG.error(ex)
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound as ex:
            LOG.error(ex)
            raise exception.NotFound()

    def update_volume_key_value_pair(self, volume, key, value):
        """Updates key,value pair as metadata onto virtual volume.

        If key already exists, the value will be replaced.
        """
        LOG.debug("VOLUME (%(disp_name)s : %(vol_name)s %(id)s) "
                  "Updating KEY-VALUE pair: (%(key)s : %(val)s)",
                  {'disp_name': volume['display_name'],
                   'vol_name': volume['name'],
                   'id': self._get_3par_vol_name(volume['id']),
                   'key': key,
                   'val': value})
        try:
            volume_name = self._get_3par_vol_name(volume['id'])
            if value is None:
                value = ''
            self.client.setVolumeMetaData(volume_name, key, value)
        except Exception as ex:
            msg = _('Failure in update_volume_key_value_pair:%s') % ex
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def clear_volume_key_value_pair(self, volume, key):
        """Clears key,value pairs metadata from virtual volume."""

        LOG.debug("VOLUME (%(disp_name)s : %(vol_name)s %(id)s) "
                  "Clearing Key : %(key)s)",
                  {'disp_name': volume['display_name'],
                   'vol_name': volume['name'],
                   'id': self._get_3par_vol_name(volume['id']),
                   'key': key})
        try:
            volume_name = self._get_3par_vol_name(volume['id'])
            self.client.removeVolumeMetaData(volume_name, key)
        except Exception as ex:
            msg = _('Failure in clear_volume_key_value_pair:%s') % ex
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def attach_volume(self, volume, instance_uuid):
        """Save the instance UUID in the volume.

           TODO: add support for multi-attach

        """
        LOG.debug("Attach Volume\n%s", pprint.pformat(volume))
        try:
            self.update_volume_key_value_pair(volume,
                                              'HPQ-CS-instance_uuid',
                                              instance_uuid)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error attaching volume %s"), volume)

    def detach_volume(self, volume, attachment=None):
        """Remove the instance uuid from the volume.

           TODO: add support for multi-attach.

        """
        LOG.debug("Detach Volume\n%s", pprint.pformat(volume))
        try:
            self.clear_volume_key_value_pair(volume, 'HPQ-CS-instance_uuid')
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error detaching volume %s"), volume)

    def migrate_volume(self, volume, host):
        """Migrate directly if source and dest are managed by same storage.

        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        :returns (False, None) if the driver does not support migration,
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
                LOG.info(_LI('3PAR driver cannot perform migration. '
                             'Retype exception: %s'), e)

        LOG.debug('leave: migrate_volume: id=%(id)s, host=%(host)s, '
                  'status=%(status)s.', dbg)
        dbg_ret = {'supported': ret[0], 'model_update': ret[1]}
        LOG.debug('migrate_volume result: %(supported)s, %(model_update)s',
                  dbg_ret)
        return ret

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

            # Create a physical copy of the volume
            task_id = self._copy_volume(volume_name, temp_vol_name,
                                        cpg, cpg, type_info['tpvv'],
                                        type_info['tdvv'])

            LOG.debug('Copy volume scheduled: convert_to_base_volume: '
                      'id=%s.', volume['id'])

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

            if self._task_status['status'] is not self.client.TASK_DONE:
                dbg = {'status': self._task_status, 'id': volume['id']}
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

            LOG.info(_LI('Completed: convert_to_base_volume: '
                         'id=%s.'), volume['id'])
        except hpexceptions.HTTPConflict:
            msg = _("Volume (%s) already exists on array.") % volume_name
            LOG.error(msg)
            raise exception.Duplicate(msg)
        except hpexceptions.HTTPBadRequest as ex:
            LOG.error(ex)
            raise exception.Invalid(ex.get_description())
        except exception.InvalidInput as ex:
            LOG.error(ex)
            raise ex
        except exception.CinderException as ex:
            LOG.error(ex)
            raise ex
        except Exception as ex:
            LOG.error(ex)
            raise exception.CinderException(ex)

        return self._get_model_update(volume['host'], cpg)

    def delete_snapshot(self, snapshot):
        LOG.debug("Delete Snapshot id %(id)s %(name)s",
                  {'id': snapshot['id'], 'name': pprint.pformat(snapshot)})

        try:
            snap_name = self._get_3par_snap_name(snapshot['id'])
            self.client.deleteVolume(snap_name)
        except hpexceptions.HTTPForbidden as ex:
            LOG.error(ex)
            raise exception.NotAuthorized()
        except hpexceptions.HTTPNotFound as ex:
            # We'll let this act as if it worked
            # it helps clean up the cinder entries.
            msg = _("Delete Snapshot id not found. Removing from cinder: "
                    "%(id)s Ex: %(msg)s") % {'id': snapshot['id'], 'msg': ex}
            LOG.warning(msg)
        except hpexceptions.HTTPConflict as ex:
            LOG.error(ex)
            raise exception.SnapshotIsBusy(snapshot_name=snapshot['id'])

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
                        if wwn == fc['wwn']:
                            return host['name']

    def terminate_connection(self, volume, hostname, wwn=None, iqn=None):
        """Driver entry point to unattach a volume from an instance."""
        # does 3par know this host by a different name?
        hosts = None
        if wwn:
            hosts = self.client.queryHost(wwns=wwn)
        elif iqn:
            hosts = self.client.queryHost(iqns=[iqn])

        if hosts and hosts['members'] and 'name' in hosts['members'][0]:
            hostname = hosts['members'][0]['name']

        try:
            self.delete_vlun(volume, hostname)
            return
        except hpexceptions.HTTPNotFound as e:
            if 'host does not exist' in e.get_description():
                # use the wwn to see if we can find the hostname
                hostname = self._get_3par_hostname_from_wwn_iqn(wwn, iqn)
                # no 3par host, re-throw
                if (hostname is None):
                    LOG.error(e)
                    raise
            else:
                # not a 'host does not exist' HTTPNotFound exception, re-throw
                LOG.error(e)
                raise

        # try again with name retrieved from 3par
        self.delete_vlun(volume, hostname)

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
                old_cpg, new_cpg, volume_name):
        """Tune the volume to change the userCPG and/or provisioningType.

        The volume will be modified/tuned/converted to the new userCPG and
        provisioningType, as needed.

        TaskWaiter is used to make this function wait until the 3PAR task
        is no longer active.  When the task is no longer active, then it must
        either be done or it is in a state that we need to treat as an error.
        """

        if old_tpvv == new_tpvv and old_tdvv == new_tdvv:
            if new_cpg != old_cpg:
                LOG.info(_LI("Modifying %(volume_name)s userCPG "
                             "from %(old_cpg)s"
                             " to %(new_cpg)s"),
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
                LOG.info(_LI("Converting %(volume_name)s to thin provisioning "
                             "with userCPG=%(new_cpg)s") %
                         {'volume_name': volume_name, 'new_cpg': new_cpg})
            elif new_tdvv:
                cop = self.CONVERT_TO_DEDUP
                LOG.info(_LI("Converting %(volume_name)s to thin dedup "
                             "provisioning with userCPG=%(new_cpg)s") %
                         {'volume_name': volume_name, 'new_cpg': new_cpg})
            else:
                cop = self.CONVERT_TO_FULL
                LOG.info(_LI("Converting %(volume_name)s to full provisioning "
                             "with userCPG=%(new_cpg)s") %
                         {'volume_name': volume_name, 'new_cpg': new_cpg})

            try:
                response, body = self.client.modifyVolume(
                    volume_name,
                    {'action': 6,
                     'tuneOperation': 1,
                     'userCPG': new_cpg,
                     'conversionOperation': cop})
            except hpexceptions.HTTPBadRequest as ex:
                if ex.get_code() == 40 and "keepVV" in str(ex):
                    # Cannot retype with snapshots because we don't want to
                    # use keepVV and have straggling volumes.  Log additional
                    # info and then raise.
                    LOG.info(_LI("tunevv failed because the volume '%s' "
                                 "has snapshots."), volume_name)
                    raise ex

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

            if not (host_type == 'HP3PARDriver'):
                reason = (_("Cannot retype from HP3PARDriver to %s.") %
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
                old_comment):

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
            TuneVolumeTask(action))

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
                   'old_comment': old_comment
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
        new_hp3par_keys = new_volume_settings['hp3par_keys']
        if 'persona' in new_hp3par_keys:
            new_persona = new_hp3par_keys['persona']
        new_flash_cache = self.get_flash_cache_policy(new_hp3par_keys)

        old_qos = old_volume_settings['qos']
        old_vvs = old_volume_settings['vvs_name']
        old_hp3par_keys = old_volume_settings['hp3par_keys']
        old_flash_cache = self.get_flash_cache_policy(old_hp3par_keys)

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
                     old_comment)

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
        old_volume_settings = self.get_volume_settings_from_type(volume, host)
        return self._retype_from_old_to_new(volume, new_type,
                                            old_volume_settings, host)

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
            LOG.info(_LI("Modifying %(volume_name)s snap_cpg from "
                         "%(old_snap_cpg)s to %(new_snap_cpg)s."),
                     {'volume_name': volume_name,
                      'old_snap_cpg': old_snap_cpg,
                      'new_snap_cpg': new_snap_cpg})
            common.client.modifyVolume(
                volume_name,
                {'snapCPG': new_snap_cpg,
                 'comment': json.dumps(comment_dict)})
            self.needs_revert = True
        else:
            LOG.info(_LI("Modifying %s comments."), volume_name)
            common.client.modifyVolume(
                volume_name,
                {'comment': json.dumps(comment_dict)})
            self.needs_revert = True

    def revert(self, common, volume_name, old_snap_cpg, new_snap_cpg,
               old_comment, **kwargs):
        if self.needs_revert:
            LOG.info(_LI("Retype revert %(volume_name)s snap_cpg from "
                         "%(new_snap_cpg)s back to %(old_snap_cpg)s."),
                     {'volume_name': volume_name,
                      'new_snap_cpg': new_snap_cpg,
                      'old_snap_cpg': old_snap_cpg})
            try:
                common.client.modifyVolume(
                    volume_name,
                    {'snapCPG': old_snap_cpg, 'comment': old_comment})
            except Exception as ex:
                LOG.error(_LE("Exception during snapCPG revert: %s"), ex)


class TuneVolumeTask(flow_utils.CinderTask):

    """Task to change a volume's CPG and/or provisioning type.

    This is a task for changing the CPG and/or provisioning type.  It is
    intended for use during retype().  This task has no revert.  The current
    design is to do this task last and do revert-able tasks first. Un-doing a
    tunevv can be expensive and should be avoided.
    """

    def __init__(self, action, **kwargs):
        super(TuneVolumeTask, self).__init__(addons=[action])

    def execute(self, common, old_tpvv, new_tpvv, old_tdvv, new_tdvv,
                old_cpg, new_cpg, volume_name):
        common.tune_vv(old_tpvv, new_tpvv, old_tdvv, new_tdvv,
                       old_cpg, new_cpg, volume_name)


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
            except hpexceptions.HTTPNotFound as ex:
                # HTTPNotFound(code=102) is OK.  Set does not exist.
                if ex.get_code() != 102:
                    LOG.error(_LE("Unexpected error when retype() tried to "
                                  "deleteVolumeSet(%s)"), vvs_name)
                    raise ex

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
            except hpexceptions.HTTPNotFound as ex:
                # HTTPNotFound(code=102) is OK.  Set does not exist.
                if ex.get_code() != 102:
                    LOG.error(_LE("Unexpected error when retype() revert "
                                  "tried to deleteVolumeSet(%s)"), vvs_name)
            except Exception:
                LOG.error(_LE("Unexpected error when retype() revert "
                              "tried to deleteVolumeSet(%s)"), vvs_name)

            if old_vvs is not None or old_qos is not None:
                try:
                    common._add_volume_to_volume_set(
                        volume, volume_name, old_cpg, old_vvs, old_qos)
                except Exception as ex:
                    LOG.error(_LE("%(exception)s: Exception during revert of "
                                  "retype for volume %(volume_name)s. "
                                  "Original volume set/QOS settings may not "
                                  "have been fully restored."),
                              {'exception': ex, 'volume_name': volume_name})

            if new_vvs is not None and old_vvs != new_vvs:
                try:
                    common.client.removeVolumeFromVolumeSet(
                        new_vvs, volume_name)
                except Exception as ex:
                    LOG.error(_LE("%(exception)s: Exception during revert of "
                                  "retype for volume %(volume_name)s. "
                                  "Failed to remove from new volume set "
                                  "%(new_vvs)s."),
                              {'exception': ex,
                               'volume_name': volume_name,
                               'new_vvs': new_vvs})
