#    (c) Copyright 2012-2014 Hewlett-Packard Development Company, L.P.
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
import pprint
import re
import uuid

from cinder.openstack.common import importutils
hp3parclient = importutils.try_import("hp3parclient")
if hp3parclient:
    from hp3parclient import client
    from hp3parclient import exceptions as hpexceptions

from oslo.config import cfg

from cinder import context
from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder import units
from cinder.volume import qos_specs
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)

MIN_CLIENT_VERSION = '3.0.0'

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
    cfg.StrOpt('hp3par_cpg',
               default="OpenStack",
               help="The CPG to use for volume creation"),
    cfg.StrOpt('hp3par_cpg_snap',
               default="",
               help="The CPG to use for Snapshots for volumes. "
                    "If empty hp3par_cpg will be used"),
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
                help="List of target iSCSI addresses to use.")
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

    """

    VERSION = "2.0.12"

    stats = {}

    # TODO(Ramy): move these to the 3PAR Client
    VLUN_TYPE_EMPTY = 1
    VLUN_TYPE_PORT = 2
    VLUN_TYPE_HOST = 3
    VLUN_TYPE_MATCHED_SET = 4
    VLUN_TYPE_HOST_SET = 5

    # Valid values for volume type extra specs
    # The first value in the list is the default value
    valid_prov_values = ['thin', 'full']
    valid_persona_values = ['1 - Generic',
                            '2 - Generic-ALUA',
                            '6 - Generic-legacy',
                            '7 - HPUX-legacy',
                            '8 - AIX-legacy',
                            '9 - EGENERA',
                            '10 - ONTAP-legacy',
                            '11 - VMware',
                            '12 - OpenVMS',
                            '13 - HPUX',
                            '15 - WindowsServer']
    hp_qos_keys = ['minIOPS', 'maxIOPS', 'minBWS', 'maxBWS', 'latency',
                   'priority']
    qos_priority_level = {'low': 1, 'normal': 2, 'high': 3}
    hp3par_valid_keys = ['cpg', 'snap_cpg', 'provisioning', 'persona', 'vvs']

    def __init__(self, config):
        self.config = config
        self.hosts_naming_dict = dict()
        self.client = None

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

        cl.setSSHOptions(self.config.san_ip,
                         self.config.san_login,
                         self.config.san_password,
                         port=self.config.san_ssh_port,
                         conn_timeout=self.config.ssh_conn_timeout,
                         privatekey=self.config.san_private_key)

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

    def client_logout(self):
        self.client.logout()
        LOG.debug("Disconnect from 3PAR")

    def do_setup(self, context):
        if hp3parclient is None:
            msg = _('You must install hp3parclient before using 3PAR drivers.')
            raise exception.VolumeBackendAPIException(data=msg)
        try:
            self.client = self._create_client()
        except hpexceptions.UnsupportedVersion as ex:
            raise exception.InvalidInput(ex)
        LOG.info(_("HP3PARCommon %(common_ver)s, hp3parclient %(rest_ver)s")
                 % {"common_ver": self.VERSION,
                     "rest_ver": hp3parclient.get_version_string()})
        if self.config.hp3par_debug:
            self.client.debug_rest(True)

        self.client_login()

        try:
            # make sure the default CPG exists
            self.validate_cpg(self.config.hp3par_cpg)
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
        LOG.debug(_("Extending Volume %(vol)s from %(old)s to %(new)s, "
                    " by %(diff)s GB.") %
                  {'vol': volume_name, 'old': old_size, 'new': new_size,
                   'diff': growth_size})
        growth_size_mib = growth_size * units.KiB
        self._extend_volume(volume, volume_name, growth_size_mib)

    def _extend_volume(self, volume, volume_name, growth_size_mib,
                       _convert_to_base=False):
        try:
            if _convert_to_base:
                LOG.debug(_("Converting to base volume prior to growing."))
                self._convert_to_base_volume(volume)
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
                        self._extend_volume(volume, volume_name,
                                            growth_size_mib,
                                            _convert_to_base=True)
                else:
                    LOG.error(_("Error extending volume: %(vol)s. "
                                "Exception: %(ex)s") %
                              {'vol': volume_name, 'ex': ex})

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
        if index > 23:
            index = 23

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

    def get_volume_stats(self, refresh):
        if refresh:
            self._update_volume_stats()

        return self.stats

    def _update_volume_stats(self):
        # const to convert MiB to GB
        const = 0.0009765625

        # storage_protocol and volume_backend_name are
        # set in the child classes
        stats = {'driver_version': '1.0',
                 'free_capacity_gb': 'unknown',
                 'reserved_percentage': 0,
                 'storage_protocol': None,
                 'total_capacity_gb': 'unknown',
                 'QoS_support': True,
                 'vendor_name': 'Hewlett-Packard',
                 'volume_backend_name': None}

        try:
            cpg = self.client.getCPG(self.config.hp3par_cpg)
            if 'limitMiB' not in cpg['SDGrowth']:
                total_capacity = 'infinite'
                free_capacity = 'infinite'
            else:
                total_capacity = int(cpg['SDGrowth']['limitMiB'] * const)
                free_capacity = int((cpg['SDGrowth']['limitMiB'] -
                                    cpg['UsrUsage']['usedMiB']) * const)

            stats['total_capacity_gb'] = total_capacity
            stats['free_capacity_gb'] = free_capacity
        except hpexceptions.HTTPNotFound:
            err = (_("CPG (%s) doesn't exist on array")
                   % self.config.hp3par_cpg)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        info = self.client.getStorageSystemInfo()
        stats['location_info'] = ('HP3PARDriver:%(sys_id)s:%(dest_cpg)s' %
                                  {'sys_id': info['serialNumber'],
                                   'dest_cpg': self.config.safe_get(
                                       'hp3par_cpg')})
        self.stats = stats

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

        for vlun in vluns:
            if volume_name in vlun['volumeName']:
                break
        else:
            msg = (
                _("3PAR vlun for volume %(name)s not found on host %(host)s") %
                {'name': volume_name, 'host': hostname})
            LOG.info(msg)
            return

        # VLUN Type of MATCHED_SET 4 requires the port to be provided
        if self.VLUN_TYPE_MATCHED_SET == vlun['type']:
            self.client.deleteVLUN(volume_name, vlun['lun'], hostname,
                                   vlun['portPos'])
        else:
            self.client.deleteVLUN(volume_name, vlun['lun'], hostname)

        # Determine if there are other volumes attached to the host.
        # This will determine whether we should try removing host from host set
        # and deleting the host.
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
                self._remove_hosts_naming_dict_host(hostname)
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

    def _remove_hosts_naming_dict_host(self, hostname):
        items = self.hosts_naming_dict.items()
        lkey = None
        for key, value in items:
            if value == hostname:
                lkey = key
        if lkey is not None:
            del self.hosts_naming_dict[lkey]

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

        #NOTE(kmartin): We prefer the qos_specs association
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
            qosRule['bwMinGoalKB'] = int(min_bw) * units.KiB
            if max_bw is None:
                qosRule['bwMaxLimitKB'] = int(min_bw) * units.KiB
        if max_bw:
            qosRule['bwMaxLimitKB'] = int(max_bw) * units.KiB
            if min_bw is None:
                qosRule['bwMinGoalKB'] = int(max_bw) * units.KiB
        if latency:
            qosRule['latencyGoal'] = int(latency)
        if priority:
            qosRule['priority'] = self.qos_priority_level.get(priority.lower())

        try:
            self.client.createQoSRules(vvs_name, qosRule)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Error creating QOS rule %s") % qosRule)

    def _add_volume_to_volume_set(self, volume, volume_name,
                                  cpg, vvs_name, qos):
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
                self.client.addVolumeToVolumeSet(vvs_name, volume_name)
            except Exception as ex:
                # Cleanup the volume set if unable to create the qos rule
                # or add the volume to the volume set
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

    def get_persona_type(self, volume, hp3par_keys=None):
        default_persona = self.valid_persona_values[0]
        type_id = volume.get('volume_type_id', None)
        volume_type = None
        if type_id is not None:
            volume_type = self._get_volume_type(type_id)
            if hp3par_keys is None:
                hp3par_keys = self._get_keys_by_volume_type(volume_type)
        persona_value = self._get_key_value(hp3par_keys, 'persona',
                                            default_persona)
        if persona_value not in self.valid_persona_values:
            err = _("Must specify a valid persona %(valid)s, "
                    "value '%(persona)s' is invalid.") % \
                   ({'valid': self.valid_persona_values,
                     'persona': persona_value})
            LOG.error(err)
            raise exception.InvalidInput(reason=err)
        # persona is set by the id so remove the text and return the id
        # i.e for persona '1 - Generic' returns 1
        persona_id = persona_value.split(' ')
        return persona_id[0]

    def get_volume_settings_from_type(self, volume):
        cpg = None
        snap_cpg = None
        volume_type = None
        vvs_name = None
        hp3par_keys = {}
        qos = {}
        type_id = volume.get('volume_type_id', None)
        if type_id is not None:
            volume_type = self._get_volume_type(type_id)
            hp3par_keys = self._get_keys_by_volume_type(volume_type)
            vvs_name = self._get_key_value(hp3par_keys, 'vvs')
            if vvs_name is None:
                qos = self._get_qos_by_volume_type(volume_type)

        cpg = self._get_key_value(hp3par_keys, 'cpg',
                                  self.config.hp3par_cpg)
        if cpg is not self.config.hp3par_cpg:
            # The cpg was specified in a volume type extra spec so it
            # needs to be validated that it's in the correct domain.
            self.validate_cpg(cpg)
            # Also, look to see if the snap_cpg was specified in volume
            # type extra spec, if not use the extra spec cpg as the
            # default.
            snap_cpg = self._get_key_value(hp3par_keys, 'snap_cpg', cpg)
        else:
            # default snap_cpg to hp3par_cpg_snap if it's not specified
            # in the volume type extra specs.
            snap_cpg = self.config.hp3par_cpg_snap
            # if it's still not set or empty then set it to the cpg
            # specified in the cinder.conf file.
            if not self.config.hp3par_cpg_snap:
                snap_cpg = cpg

        # if provisioning is not set use thin
        default_prov = self.valid_prov_values[0]
        prov_value = self._get_key_value(hp3par_keys, 'provisioning',
                                         default_prov)
        # check for valid provisioning type
        if prov_value not in self.valid_prov_values:
            err = _("Must specify a valid provisioning type %(valid)s, "
                    "value '%(prov)s' is invalid.") % \
                   ({'valid': self.valid_prov_values,
                     'prov': prov_value})
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        tpvv = True
        if prov_value == "full":
            tpvv = False

        # check for valid persona even if we don't use it until
        # attach time, this will give the end user notice that the
        # persona type is invalid at volume creation time
        self.get_persona_type(volume, hp3par_keys)

        return {'cpg': cpg, 'snap_cpg': snap_cpg,
                'vvs_name': vvs_name, 'qos': qos,
                'tpvv': tpvv, 'volume_type': volume_type}

    def create_volume(self, volume):
        LOG.debug("CREATE VOLUME (%s : %s %s)" %
                  (volume['display_name'], volume['name'],
                   self._get_3par_vol_name(volume['id'])))
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

            capacity = self._capacity_from_size(volume['size'])
            volume_name = self._get_3par_vol_name(volume['id'])
            self.client.createVolume(volume_name, cpg, capacity, extras)
            if qos or vvs_name is not None:
                try:
                    self._add_volume_to_volume_set(volume, volume_name,
                                                   cpg, vvs_name, qos)
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

    def _copy_volume(self, src_name, dest_name, cpg, snap_cpg=None,
                     tpvv=True):
        # Virtual volume sets are not supported with the -online option
        LOG.debug(_('Creating clone of a volume %(src)s to %(dest)s.') %
                  {'src': src_name, 'dest': dest_name})

        optional = {'tpvv': tpvv, 'online': True}
        if snap_cpg is not None:
            optional['snapCPG'] = snap_cpg

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

    def create_cloned_volume(self, volume, src_vref):
        try:
            orig_name = self._get_3par_vol_name(volume['source_volid'])
            vol_name = self._get_3par_vol_name(volume['id'])

            type_info = self.get_volume_settings_from_type(volume)

            # make the 3PAR copy the contents.
            # can't delete the original until the copy is done.
            self._copy_volume(orig_name, vol_name, cpg=type_info['cpg'],
                              snap_cpg=type_info['snap_cpg'],
                              tpvv=type_info['tpvv'])
            return None
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
                        LOG.debug(_("Found an online copy for %(volume)s")
                                  % {'volume': volume_name})
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
                    LOG.debug("Returned vvset_name = %s" % vvset_name)
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
                else:
                    LOG.error(ex)
                    raise ex

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
            raise exception.VolumeIsBusy(ex.get_description())
        except Exception as ex:
            LOG.error(ex)
            raise exception.CinderException(ex)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot.

        """
        LOG.debug("Create Volume from Snapshot\n%s\n%s" %
                  (pprint.pformat(volume['display_name']),
                   pprint.pformat(snapshot['display_name'])))

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

            volume_type = None
            type_id = volume.get('volume_type_id', None)
            vvs_name = None
            qos = {}
            hp3par_keys = {}
            if type_id is not None:
                volume_type = self._get_volume_type(type_id)
                hp3par_keys = self._get_keys_by_volume_type(volume_type)
                vvs_name = self._get_key_value(hp3par_keys, 'vvs')
                if vvs_name is None:
                    qos = self._get_qos_by_volume_type(volume_type)

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
                    LOG.debug(_('Converting to base volume type: %s.') %
                              volume['id'])
                    self._convert_to_base_volume(volume)
                    growth_size_mib = growth_size * units.GiB / units.MiB
                    LOG.debug(_('Growing volume: %(id)s by %(size)s GiB.') %
                              {'id': volume['id'], 'size': growth_size})
                    self.client.growVolume(volume_name, growth_size_mib)
                except Exception as ex:
                    LOG.error(_("Error extending volume %(id)s. Ex: %(ex)s") %
                              {'id': volume['id'], 'ex': ex})
                    # Delete the volume if unable to grow it
                    self.client.deleteVolume(volume_name)
                    raise exception.CinderException(ex)

            if qos or vvs_name is not None:
                cpg = self._get_key_value(hp3par_keys, 'cpg',
                                          self.config.hp3par_cpg)
                try:
                    self._add_volume_to_volume_set(volume, volume_name,
                                                   cpg, vvs_name, qos)
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

    def create_snapshot(self, snapshot):
        LOG.debug("Create Snapshot\n%s" % pprint.pformat(snapshot))

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
        LOG.debug("VOLUME (%s : %s %s) Updating KEY-VALUE pair: (%s : %s)" %
                  (volume['display_name'],
                   volume['name'],
                   self._get_3par_vol_name(volume['id']),
                   key,
                   value))
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

        LOG.debug("VOLUME (%s : %s %s) Clearing Key : %s)" %
                  (volume['display_name'], volume['name'],
                   self._get_3par_vol_name(volume['id']), key))
        try:
            volume_name = self._get_3par_vol_name(volume['id'])
            self.client.removeVolumeMetaData(volume_name, key)
        except Exception as ex:
            msg = _('Failure in clear_volume_key_value_pair:%s') % ex
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def attach_volume(self, volume, instance_uuid):
        LOG.debug("Attach Volume\n%s" % pprint.pformat(volume))
        try:
            self.update_volume_key_value_pair(volume,
                                              'HPQ-CS-instance_uuid',
                                              instance_uuid)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Error attaching volume %s") % volume)

    def detach_volume(self, volume):
        LOG.debug("Detach Volume\n%s" % pprint.pformat(volume))
        try:
            self.clear_volume_key_value_pair(volume, 'HPQ-CS-instance_uuid')
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Error detaching volume %s") % volume)

    def migrate_volume(self, volume, host):
        """Migrate directly if source and dest are managed by same storage.

        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        :returns (False, None) if the driver does not support migration,
                 (True, None) if sucessful

        """

        dbg = {'id': volume['id'], 'host': host['host']}
        LOG.debug(_('enter: migrate_volume: id=%(id)s, host=%(host)s.') % dbg)

        false_ret = (False, None)

        # Make sure volume is not attached
        if volume['status'] != 'available':
            LOG.debug(_('Volume is attached: migrate_volume: '
                        'id=%(id)s, host=%(host)s.') % dbg)
            return false_ret

        if 'location_info' not in host['capabilities']:
            return false_ret

        info = host['capabilities']['location_info']
        try:
            (dest_type, dest_id, dest_cpg) = info.split(':')
        except ValueError:
            return false_ret

        sys_info = self.client.getStorageSystemInfo()
        if not (dest_type == 'HP3PARDriver' and
                dest_id == sys_info['serialNumber']):
            LOG.debug(_('Dest does not match: migrate_volume: '
                        'id=%(id)s, host=%(host)s.') % dbg)
            return false_ret

        type_info = self.get_volume_settings_from_type(volume)

        if dest_cpg == type_info['cpg']:
            LOG.debug(_('CPGs are the same: migrate_volume: '
                        'id=%(id)s, host=%(host)s.') % dbg)
            return false_ret

        # Check to make sure CPGs are in the same domain
        src_domain = self.get_domain(type_info['cpg'])
        dst_domain = self.get_domain(dest_cpg)
        if src_domain != dst_domain:
            LOG.debug(_('CPGs in different domains: migrate_volume: '
                        'id=%(id)s, host=%(host)s.') % dbg)
            return false_ret

        self._convert_to_base_volume(volume, new_cpg=dest_cpg)

        # TODO(Ramy) When volume retype is available,
        # use that to change the type
        LOG.debug(_('leave: migrate_volume: id=%(id)s, host=%(host)s.') % dbg)
        return (True, None)

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
                                        cpg, cpg, type_info['tpvv'])

            LOG.debug(_('Copy volume scheduled: convert_to_base_volume: '
                        'id=%s.') % volume['id'])

            # Wait for the physical copy task to complete
            def _wait_for_task(task_id):
                status = self.client.getTask(task_id)
                LOG.debug("3PAR Task id %(id)s status = %(status)s" %
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
                LOG.debug(_('Copy volume completed: convert_to_base_volume: '
                            'id=%s.') % volume['id'])

            comment = self._get_3par_vol_comment(volume_name)
            if comment:
                self.client.modifyVolume(temp_vol_name, {'comment': comment})
            LOG.debug(_('Volume rename completed: convert_to_base_volume: '
                        'id=%s.') % volume['id'])

            # Delete source volume after the copy is complete
            self.client.deleteVolume(volume_name)
            LOG.debug(_('Delete src volume completed: convert_to_base_volume: '
                        'id=%s.') % volume['id'])

            # Rename the new volume to the original name
            self.client.modifyVolume(temp_vol_name, {'newName': volume_name})

            LOG.info(_('Completed: convert_to_base_volume: '
                       'id=%s.') % volume['id'])
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

    def delete_snapshot(self, snapshot):
        LOG.debug("Delete Snapshot id %s %s" % (snapshot['id'],
                                                pprint.pformat(snapshot)))

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
        try:
            # does 3par know this host by a different name?
            if hostname in self.hosts_naming_dict:
                hostname = self.hosts_naming_dict.get(hostname)
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
